"""Tests for pucksim.sim.engine -- Step 1.12 done-criteria.

Uses ``pucksim.gen.leaguegen.build_world(seed=...)`` for realistic populated Worlds (per
DEVPLAN.md's explicit suggestion), then drives ``GameSim(...).play()`` and checks internal
box-score consistency, determinism, a light-weight many-game "doesn't crash" sweep, shot-attempt
event context, plus_minus correctness, and that no game in this step's scope ever resolves via a
shootout (``went_so`` stays False everywhere -- shootouts don't exist until Step 2.6).
"""
from __future__ import annotations

import itertools

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.sim.boxscore import EVENT_GOAL, EVENT_SHOT, SHOT_TYPES
from pucksim.sim.engine import GameSim


def _play(seed: int, home_idx: int = 0, away_idx: int = 1, collect_pbp: bool = False):
    world = build_world(seed=seed)
    tids = sorted(world.teams.keys())
    home_tid, away_tid = tids[home_idx], tids[away_idx]
    result = GameSim(world, home_tid, away_tid, collect_pbp=collect_pbp).play()
    return world, home_tid, away_tid, result


# ---------------------------------------------------------------------------
# Box-score internal consistency
# ---------------------------------------------------------------------------
def test_goals_reconcile_with_team_score():
    world, home_tid, away_tid, result = _play(seed=1)
    home_team = world.team(home_tid)
    away_team = world.team(away_tid)

    home_goals = sum(result.skater_box[pid].g for pid in home_team.roster
                     if pid in result.skater_box)
    away_goals = sum(result.skater_box[pid].g for pid in away_team.roster
                     if pid in result.skater_box)

    assert home_goals == result.home_score
    assert away_goals == result.away_score


def test_sog_reconciles_with_opposing_goalie_shots_faced():
    world, home_tid, away_tid, result = _play(seed=2)
    home_team = world.team(home_tid)
    away_team = world.team(away_tid)

    home_sog = sum(result.skater_box[pid].sog for pid in home_team.roster
                  if pid in result.skater_box)
    away_sog = sum(result.skater_box[pid].sog for pid in away_team.roster
                  if pid in result.skater_box)

    # Home team's shots on goal all went at the away goalie, and vice versa.
    away_goalie_faced = result.goalie_box[away_team.goalie_starter].shots_faced
    home_goalie_faced = result.goalie_box[home_team.goalie_starter].shots_faced

    assert home_sog == away_goalie_faced
    assert away_sog == home_goalie_faced


def test_every_boxed_player_has_positive_ice_time():
    world, home_tid, away_tid, result = _play(seed=3)
    for pid, line in result.skater_box.items():
        assert line.secs > 0, f"skater {pid} has 0 secs"
    for pid, line in result.goalie_box.items():
        assert line.secs > 0, f"goalie {pid} has 0 secs"


def test_total_ice_time_reconciles_with_game_length():
    """5 skaters + 1 goalie always on ice per team per second of play -- both teams' total
    skater-seconds summed should land in the right ballpark for a full game (+ approximate OT).
    Not exact precision (shift lengths are jittered), just the right order of magnitude."""
    world, home_tid, away_tid, result = _play(seed=4)
    home_team = world.team(home_tid)
    away_team = world.team(away_tid)

    total_skater_secs = sum(l.secs for l in result.skater_box.values())
    game_len = config.PERIODS * config.PERIOD_SECONDS
    max_len = game_len + (config.OT_SECONDS_REGULAR_SEASON if result.went_ot else 0)

    # 5 skaters per team on ice at all times -> 10 skater-seconds per second of game clock.
    expected_min = 10 * game_len * 0.85       # allow slack for shift-length jitter / rounding
    expected_max = 10 * max_len * 1.15
    assert expected_min <= total_skater_secs <= expected_max

    home_goalie_secs = result.goalie_box[home_team.goalie_starter].secs
    away_goalie_secs = result.goalie_box[away_team.goalie_starter].secs
    assert abs(home_goalie_secs - max_len) <= max_len * 0.15
    assert abs(away_goalie_secs - max_len) <= max_len * 0.15


def test_corsi_and_fenwick_tallied_as_event_stream_filter():
    """Corsi (every attempt, blocked included) and Fenwick (unblocked only) must reconcile
    exactly against a direct filter over the collected event stream, proving these are tallied
    as a filter over the shot-attempt events rather than a separately-bolted-on pass."""
    world, home_tid, away_tid, result = _play(seed=5, collect_pbp=True)
    home_team = world.team(home_tid)

    shot_events = [e for e in result.pbp if e.event_type in (EVENT_SHOT, EVENT_GOAL)]
    home_corsi_for_events = sum(1 for e in shot_events if e.team_id == home_tid)
    home_fenwick_for_events = sum(1 for e in shot_events
                                  if e.team_id == home_tid and e.outcome != "block")

    home_corsi_for_box = sum(result.skater_box[pid].corsi_for for pid in home_team.roster
                             if pid in result.skater_box) // 5
    home_fenwick_for_box = sum(result.skater_box[pid].fenwick_for for pid in home_team.roster
                               if pid in result.skater_box) // 5

    assert home_corsi_for_box == home_corsi_for_events
    assert home_fenwick_for_box == home_fenwick_for_events


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def _serialize_result(result) -> tuple:
    return (
        result.home_score, result.away_score, result.went_ot, result.went_so,
        {pid: line.to_dict() for pid, line in result.skater_box.items()},
        {pid: line.to_dict() for pid, line in result.goalie_box.items()},
    )


def test_same_seed_produces_byte_identical_game_result():
    world_a = build_world(seed=99)
    world_b = build_world(seed=99)
    tids = sorted(world_a.teams.keys())

    result_a = GameSim(world_a, tids[5], tids[6]).play()
    result_b = GameSim(world_b, tids[5], tids[6]).play()

    assert _serialize_result(result_a) == _serialize_result(result_b)


def test_different_seeds_produce_different_results():
    _, _, _, result_a = _play(seed=10)
    _, _, _, result_b = _play(seed=11)
    assert _serialize_result(result_a) != _serialize_result(result_b)


# ---------------------------------------------------------------------------
# Many-game sweep -- doesn't crash, no shootouts.
# ---------------------------------------------------------------------------
def test_sweep_of_games_across_matchups_and_seeds_does_not_crash():
    results = []
    for seed in range(1, 6):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        pairs = list(itertools.islice(itertools.combinations(tids, 2), 5))
        for home_tid, away_tid in pairs:
            result = GameSim(world, home_tid, away_tid).play()
            results.append(result)

    assert len(results) >= 25
    for result in results:
        assert result.home_score >= 0
        assert result.away_score >= 0
        # MVP scope: shootouts don't exist yet -- never set went_so=True.
        assert result.went_so is False


# ---------------------------------------------------------------------------
# Shot-attempt event schema
# ---------------------------------------------------------------------------
def test_shot_attempt_event_carries_full_analytics_context():
    world, home_tid, away_tid, result = _play(seed=6, collect_pbp=True)
    shot_events = [e for e in result.pbp if e.event_type in (EVENT_SHOT, EVENT_GOAL)]
    assert shot_events, "expected at least one shot-attempt event"

    event = shot_events[0]
    assert event.shot_type in SHOT_TYPES
    assert isinstance(event.zone, str) and event.zone
    # Step 2.1: strength_state is now real, live game state (not an always-5v5 literal) -- any
    # single sampled event may land during a PP/PK/etc. shift, so just check it's a legal value.
    # See tests/test_special_teams.py for coverage that PP/PK shifts specifically log the right
    # strength_state.
    assert event.strength_state in config.STRENGTH_STATES
    assert isinstance(event.rebound, bool)
    assert isinstance(event.rush, bool)
    assert event.team_id in (home_tid, away_tid)
    assert event.player_id is not None
    assert event.outcome in ("goal", "save", "miss", "block")


def test_rebound_flag_is_set_on_the_attempt_following_an_unconverted_save():
    """At least across a handful of games, some shot attempt should be flagged as a rebound of a
    prior save (statistical property, since a controlled single-shift scenario would require
    reaching into private shift-loop internals)."""
    found_rebound = False
    for seed in range(1, 8):
        world, home_tid, away_tid, result = _play(seed=seed, collect_pbp=True)
        if any(e.rebound for e in result.pbp if e.event_type in (EVENT_SHOT, EVENT_GOAL)):
            found_rebound = True
            break
    assert found_rebound


# ---------------------------------------------------------------------------
# Plus/minus on goals
# ---------------------------------------------------------------------------
def test_goal_updates_plus_minus_for_on_ice_skaters_both_teams():
    """Statistical property over several simulated games: the sum of every skater's plus_minus on
    a team should be net-zero across both teams for any single game (every +1 for a scoring team's
    on-ice skaters is balanced by a -1 for the conceding team's on-ice skaters), and at least one
    player somewhere should show a nonzero plus_minus given goals were scored."""
    any_nonzero = False
    for seed in range(1, 6):
        world, home_tid, away_tid, result = _play(seed=seed)
        total_pm = sum(line.plus_minus for line in result.skater_box.values())
        assert total_pm == 0, f"plus_minus should net to zero league-wide, got {total_pm}"
        if any(line.plus_minus != 0 for line in result.skater_box.values()):
            any_nonzero = True
    assert any_nonzero


def test_goal_credits_scorer_and_updates_goalie_goals_against():
    """Every goal is charged to SOME goalie's goals_against, with one deliberate real-NHL
    exception introduced by Step 2.2's pull-the-goalie mechanic: an empty-net goal (scored
    against a team whose goalie was pulled for an extra attacker, ``goalie_id`` logged as
    ``None`` on that event) is never charged against any goalie's box score -- matching real NHL
    scorekeeping, where an ENG doesn't count against a goalie's save percentage/GAA. So the
    correct invariant is goals_against + empty_net_goals == total goals, not a flat equality."""
    world, home_tid, away_tid, result = _play(seed=12, collect_pbp=True)
    home_team = world.team(home_tid)
    away_team = world.team(away_tid)

    home_goalie_ga = result.goalie_box.get(away_team.goalie_starter)
    away_goalie_ga = result.goalie_box.get(home_team.goalie_starter)
    total_goals_against = (home_goalie_ga.goals_against if home_goalie_ga else 0) \
        + (away_goalie_ga.goals_against if away_goalie_ga else 0)

    empty_net_goals = sum(1 for e in result.pbp
                          if e.event_type == EVENT_GOAL and e.goalie_id is None)

    assert total_goals_against + empty_net_goals == result.home_score + result.away_score


# ---------------------------------------------------------------------------
# went_so never True this step
# ---------------------------------------------------------------------------
def test_went_so_is_never_true_across_many_games():
    for seed in range(20, 26):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        for home_tid, away_tid in itertools.islice(itertools.combinations(tids, 2), 3):
            result = GameSim(world, home_tid, away_tid).play()
            assert result.went_so is False


# ---------------------------------------------------------------------------
# Faceoffs -- won/lost tallies exist and are consistent
# ---------------------------------------------------------------------------
def test_faceoff_tallies_recorded():
    world, home_tid, away_tid, result = _play(seed=13)
    total_won = sum(line.fo_won for line in result.skater_box.values())
    total_lost = sum(line.fo_lost for line in result.skater_box.values())
    # Every faceoff produces exactly one winner and one loser.
    assert total_won == total_lost
    assert total_won > 0
