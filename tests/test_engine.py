"""Tests for pucksim.sim.engine -- Step 1.12 done-criteria (updated by Step 2.6 for real
OT/shootout resolution -- see the "Every game under a has_shootout=True rule resolves
decisively" section near the bottom).

Uses ``pucksim.gen.leaguegen.build_world(seed=...)`` for realistic populated Worlds (per
DEVPLAN.md's explicit suggestion), then drives ``GameSim(...).play()`` and checks internal
box-score consistency, determinism, a light-weight many-game "doesn't crash" sweep, shot-attempt
event context, and plus_minus correctness. Real OT/shootout-specific coverage (3-on-3 OT, real
shootout point awards, playoff 5-on-5 sudden death, the playoff discipline mode) lives in
``tests/test_ot_shootout.py``/``tests/test_playoffs.py``, not here.
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
    """SOG should reconcile with the opposing goalie's shots_faced -- WITH one deliberate,
    real-NHL-accurate exception (same one ``test_goal_credits_scorer_and_updates_goalie_goals_
    against`` already documents just below): an on-goal attempt against a pulled (empty) net
    still counts as a shot on goal for the shooter (``SkaterStatLine.sog``), but there is no
    goalie in net to charge ``shots_faced`` to (see engine.py's ``_resolve_shot_attempt``/
    ``_resolve_empty_net_shot``). ``collect_pbp=True`` here (an earlier version of this test
    didn't collect PBP and simply asserted flat equality -- that only ever held by coincidence,
    whether a goalie happened to get pulled within this test's specific seed; discovered while
    reworking on-ice-group/possession logic in this same territory for DEVPLAN.md Step 2.3) so
    empty-net on-goal attempts can be identified and excluded from the reconciliation, same as
    goals already are."""
    world, home_tid, away_tid, result = _play(seed=2, collect_pbp=True)
    home_team = world.team(home_tid)
    away_team = world.team(away_tid)

    home_sog = sum(result.skater_box[pid].sog for pid in home_team.roster
                  if pid in result.skater_box)
    away_sog = sum(result.skater_box[pid].sog for pid in away_team.roster
                  if pid in result.skater_box)

    # Empty-net on-goal attempts (goalie_id is None on the logged event) by each team -- these
    # inflate the shooting team's sog with no corresponding shots_faced to reconcile against.
    home_empty_net_attempts = sum(
        1 for e in result.pbp
        if e.event_type in (EVENT_SHOT, EVENT_GOAL) and e.team_id == home_tid and e.goalie_id is None
    )
    away_empty_net_attempts = sum(
        1 for e in result.pbp
        if e.event_type in (EVENT_SHOT, EVENT_GOAL) and e.team_id == away_tid and e.goalie_id is None
    )

    # Home team's shots on goal all went at the away goalie, and vice versa.
    away_goalie_faced = result.goalie_box[away_team.goalie_starter].shots_faced
    home_goalie_faced = result.goalie_box[home_team.goalie_starter].shots_faced

    assert home_sog - home_empty_net_attempts == away_goalie_faced
    assert away_sog - away_empty_net_attempts == home_goalie_faced


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
# Many-game sweep -- doesn't crash.
# ---------------------------------------------------------------------------
def test_sweep_of_games_across_matchups_and_seeds_does_not_crash():
    """DEVPLAN.md Step 2.6: went_so=True is now a legitimate, expected outcome (real 3-on-3 OT ->
    shootout resolution for a has_shootout=True default-standings-rule game) -- an earlier
    version of this test asserted went_so is always False, which was an MVP-scope-only invariant
    Step 2.6 explicitly obsoletes (see tests/test_ot_shootout.py for the real shootout-specific
    coverage this step adds). This test's own job is unchanged: a many-game sweep across varied
    seeds/matchups must not crash and must always produce a non-negative, decisive score."""
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
        # Every game under the default "standard" (has_shootout=True) standings rule must now
        # resolve decisively straight from the engine -- no unresolved ties.
        assert result.winner is not None


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
    """Statistical property over several simulated games: the sum of every skater's plus_minus
    on a team is net-zero across both teams FOR EVEN-STRENGTH GOALS specifically (every +1 for
    a scoring team's on-ice skaters at even strength is balanced by a -1 for the conceding
    team's on-ice skaters, since both sides field the same number of skaters), and at least one
    player somewhere should show a nonzero plus_minus given goals were scored.

    NOT a claim that plus_minus nets to zero for the WHOLE game unconditionally -- a real-NHL
    accurate detail, and a deliberate one (see engine.py's _score_goal docstring): a shorthanded
    goal-for is correctly credited to plus/minus (that's real hockey), but the two on-ice groups
    are asymmetric-by-definition on a PK goal (4 skaters for vs. 5 skaters against), so that
    single event nets to -1, not 0 -- exactly matching real NHL scorekeeping, where plus/minus
    is not a globally net-zero stat once shorthanded goals happen. An earlier version of this
    test asserted a flat "nets to zero across the whole game" invariant, which only ever held
    by coincidence (whether a shorthanded goal happened to occur within this test's specific
    seed range) rather than because it was actually true in general -- discovered while
    reworking on-ice-group sizing in this same territory for DEVPLAN.md Step 2.3 (see also the
    real STRENGTH_4V4 on/off-ice-size bug this step fixed in special_teams.py, a separate,
    genuine bug that could ALSO break net-zero even at even strength before that fix)."""
    any_nonzero = False
    for seed in range(1, 6):
        world, home_tid, away_tid, result = _play(seed=seed, collect_pbp=True)
        sh_goals_for = sum(
            1 for ev in result.pbp
            if ev.event_type == EVENT_GOAL and ev.strength_state == config.STRENGTH_PK
        )
        total_pm = sum(line.plus_minus for line in result.skater_box.values())
        # Each shorthanded goal-for nets to exactly -1 (4 PK skaters credited +1, 5 PP skaters
        # charged -1); every other counted goal (even-strength) nets to 0. So the whole-game
        # total must land at exactly -1 * (number of shorthanded goals-for).
        assert total_pm == -sh_goals_for, (
            f"plus_minus should net to -{sh_goals_for} (one per shorthanded goal-for) given "
            f"{sh_goals_for} SH goals this game, got {total_pm}"
        )
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
# Every game under a has_shootout=True rule resolves decisively (DEVPLAN.md Step 2.6).
# ---------------------------------------------------------------------------
def test_every_game_resolves_decisively_under_default_standings_rule():
    """DEVPLAN.md Step 2.6 superseded this test's original MVP-scope premise (an earlier version
    asserted went_so is NEVER true, since no shootout existed yet). Now the inverse invariant
    holds: build_world()'s default standings_rule ("standard", has_shootout=True) means every
    game -- however it gets there (regulation, 3-on-3 OT, or a real shootout) -- must come back
    with a decisive winner and legal went_ot/went_so flags. See tests/test_ot_shootout.py for
    shootout-specific coverage (point awards, retro's legitimate-tie exception, etc.)."""
    for seed in range(20, 26):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        for home_tid, away_tid in itertools.islice(itertools.combinations(tids, 2), 3):
            result = GameSim(world, home_tid, away_tid).play()
            assert result.winner is not None
            # went_so=True only ever accompanies went_ot=True (a shootout is always preceded by
            # an undecided OT period) -- never the reverse implication (plenty of games decide in
            # regulation or in OT without needing a shootout at all).
            if result.went_so:
                assert result.went_ot is True


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
