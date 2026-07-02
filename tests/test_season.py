"""Tests for pucksim.sim.season -- Step 1.13 done-criteria (tie-reconciliation section rewritten
by DEVPLAN.md Step 2.6 -- see season.py's module docstring for the full history).

Uses ``pucksim.gen.leaguegen.build_world(seed=...)`` for realistic populated Worlds (same pattern
as test_engine.py), then drives ``start_season()``/``advance_one_day()`` to simulate full or
partial seasons, checking schedule balance, win-total reconciliation, standings-math correctness
across all 3 rules, and -- the key regression coverage for this step, now reflecting Step 2.6's
real OT/shootout resolution -- that every game under a has_shootout=True rule comes back decisive
straight from ``sim/engine.py`` (no season-level placeholder involved, since Step 2.6 removed
it), "retro" can still legitimately end level, and ``_apply_result()`` defensively raises rather
than silently mis-recording if it's ever handed an unresolved tie under a has_shootout=True rule.
"""
from __future__ import annotations

import itertools

import pytest

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.models.league import standings
from pucksim.sim.boxscore import GameResult
from pucksim.sim.season import (
    _apply_result,
    advance_one_day,
    generate_schedule,
    regular_season_complete,
    sim_one,
    start_season,
)

ALL_RULES = ["standard", "retro", "three_two_one_zero"]


# ---------------------------------------------------------------------------
# Schedule generation
# ---------------------------------------------------------------------------
def test_generate_schedule_every_team_plays_target_games():
    world = build_world(seed=1)
    schedule = generate_schedule(world, target_games=config.SEASON_GAMES)

    games_per_team = {tid: 0 for tid in world.teams}
    for g in schedule:
        games_per_team[g.home] += 1
        games_per_team[g.away] += 1

    assert set(games_per_team.values()) == {config.SEASON_GAMES}


def test_generate_schedule_full_82_game_32_team_path():
    """Cover the real config.SEASON_GAMES / config.NUM_TEAMS path explicitly (not just a smaller
    stand-in), per the step's test requirements."""
    world = build_world(seed=2)
    assert len(world.teams) == config.NUM_TEAMS
    schedule = generate_schedule(world, target_games=config.SEASON_GAMES)

    games_per_team = {tid: 0 for tid in world.teams}
    for g in schedule:
        games_per_team[g.home] += 1
        games_per_team[g.away] += 1
    assert all(count == config.SEASON_GAMES for count in games_per_team.values())
    assert len(schedule) == config.NUM_TEAMS * config.SEASON_GAMES // 2


def test_generate_schedule_no_team_plays_twice_same_day():
    world = build_world(seed=3)
    schedule = generate_schedule(world, target_games=20)

    by_day = {}
    for g in schedule:
        by_day.setdefault(g.day, []).append(g)

    for day, games in by_day.items():
        seen = set()
        for g in games:
            assert g.home not in seen, f"team {g.home} double-booked on day {day}"
            assert g.away not in seen, f"team {g.away} double-booked on day {day}"
            seen.add(g.home)
            seen.add(g.away)


def test_generate_schedule_unique_gids():
    world = build_world(seed=4)
    schedule = generate_schedule(world, target_games=20)
    gids = [g.gid for g in schedule]
    assert len(gids) == len(set(gids))


def test_generate_schedule_small_target_games():
    """A short season (for fast tests elsewhere) still balances correctly."""
    world = build_world(seed=5)
    schedule = generate_schedule(world, target_games=6)
    games_per_team = {tid: 0 for tid in world.teams}
    for g in schedule:
        games_per_team[g.home] += 1
        games_per_team[g.away] += 1
    assert set(games_per_team.values()) == {6}


# ---------------------------------------------------------------------------
# Full short season simulation
# ---------------------------------------------------------------------------
def _run_short_season(seed: int, games: int = 8, standings_rule: str = "standard"):
    world = build_world(seed=seed)
    world.standings_rule = standings_rule
    world.schedule = generate_schedule(world, target_games=games)
    world.day = 0
    for team in world.teams.values():
        team.reset_record()
    while not regular_season_complete(world):
        advance_one_day(world)
    return world


@pytest.mark.parametrize("rule", ALL_RULES)
def test_short_season_completes_without_exception(rule):
    world = _run_short_season(seed=10, games=8, standings_rule=rule)
    assert regular_season_complete(world)
    for g in world.schedule:
        assert g.played


def test_full_82_game_32_team_season_runs_without_exception():
    """The real config.SEASON_GAMES/config.NUM_TEAMS path -- DEVPLAN.md's MVP exit criterion
    ("testkit/run_season.py runs a full 82-game season for all 32 teams without exception") is
    exercised directly here, using the default 'standard' rule (has_shootout=True, so this also
    exercises the tie-reconciliation path over a realistically large number of games)."""
    world = build_world(seed=42)
    start_season(world)
    assert len(world.teams) == config.NUM_TEAMS
    while not regular_season_complete(world):
        advance_one_day(world)
    assert regular_season_complete(world)
    for team in world.teams.values():
        assert team.games_played == config.SEASON_GAMES


# ---------------------------------------------------------------------------
# Win totals reconcile
# ---------------------------------------------------------------------------
def test_win_totals_reconcile_with_decisive_games_standard_rule():
    """Under 'standard' (has_shootout=True), every played game has a decisive winner/loser, so
    sum(wins) should equal the number of played games, and sum(losses + ot_losses) should too."""
    world = _run_short_season(seed=11, games=10, standings_rule="standard")
    total_wins = sum(t.wins for t in world.teams.values())
    total_losses_otl = sum(t.losses + t.ot_losses for t in world.teams.values())
    total_games = len(world.schedule)
    assert total_wins == total_games
    assert total_losses_otl == total_games


def test_win_totals_reconcile_with_retro_ties_excluded():
    """Under 'retro', a tie contributes to neither team's win column (Team has no tie bucket --
    see season.py's _apply_result docstring), so sum(wins) + number_of_ties == number of decisive
    games, and total decisive games + ties == total games played."""
    world = _run_short_season(seed=12, games=12, standings_rule="retro")
    total_wins = sum(t.wins for t in world.teams.values())
    total_losses = sum(t.losses + t.ot_losses for t in world.teams.values())
    ties = sum(1 for g in world.schedule if g.is_tie)
    decisive = sum(1 for g in world.schedule if not g.is_tie)

    assert total_wins == decisive
    assert total_losses == decisive
    assert ties + decisive == len(world.schedule)


# ---------------------------------------------------------------------------
# Standings ordering across all 3 rules -- the key regression test proving
# tie-reconciliation actually works for "standard"/"three_two_one_zero".
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rule", ALL_RULES)
def test_standings_does_not_raise_after_full_short_season(rule):
    world = _run_short_season(seed=13, games=10, standings_rule=rule)
    ordered = standings(list(world.teams.values()), world.schedule, rule)
    assert len(ordered) == len(world.teams)


@pytest.mark.parametrize("rule", ALL_RULES)
def test_standings_does_not_raise_after_full_82_game_season(rule):
    """Run the real 82-game/32-team season under each rule -- the strongest version of the
    regression test, since a realistic number of games all but guarantees at least one unresolved
    tie shows up somewhere along the way for the has_shootout=True rules."""
    world = build_world(seed=7)
    world.standings_rule = rule
    start_season(world)
    while not regular_season_complete(world):
        advance_one_day(world)
    ordered = standings(list(world.teams.values()), world.schedule, rule)
    assert len(ordered) == config.NUM_TEAMS


# ---------------------------------------------------------------------------
# Explicit tie-reconciliation test: force an unresolved tie result through
# _apply_result()/sim_one() under each of the 3 rules.
# ---------------------------------------------------------------------------
def _make_tied_result(world) -> tuple:
    """Find (or engineer) an unresolved tie GameResult for the first scheduled game."""
    tids = sorted(world.teams.keys())
    home_tid, away_tid = tids[0], tids[1]
    # Directly construct an unresolved tie GameResult -- this is the exact shape the MVP engine's
    # OT placeholder can produce (winner is None, went_ot True, went_so always False), without
    # needing to search seeds for a real one.
    result = GameResult(home_tid=home_tid, away_tid=away_tid, home_score=2, away_score=2,
                         went_ot=True, went_so=False)
    assert result.winner is None
    return home_tid, away_tid, result


@pytest.mark.parametrize("rule", ["retro"])
def test_tie_reconciliation_produces_legal_game_for_retro(rule):
    """DEVPLAN.md Step 2.6: only "retro" can legally represent an unresolved-tie GameResult
    anymore -- see the AssertionError-guard test just below for the has_shootout=True case."""
    from pucksim.models.league import Game

    world = build_world(seed=20)
    world.standings_rule = rule
    home_tid, away_tid, result = _make_tied_result(world)
    game = Game(gid=world.new_gid(), day=0, home=home_tid, away=away_tid)

    _apply_result(world, game, result)

    assert game.played is True
    assert game.is_tie is True
    assert game.winner is None

    # standings() must not raise.
    ordered = standings(list(world.teams.values()), [game], rule)
    assert len(ordered) == len(world.teams)


@pytest.mark.parametrize("rule", ["standard", "three_two_one_zero"])
def test_apply_result_raises_on_unresolved_tie_under_has_shootout_rule(rule):
    """DEVPLAN.md Step 2.6 removed the MVP-era placeholder tiebreak that used to manufacture a
    decisive winner here (season.py's module docstring: "Tie-reconciliation" section) -- the real
    engine now always resolves a has_shootout=True game decisively on its own (3-on-3 OT -> real
    shootout simulation), so _apply_result() no longer has anything to reconcile on this path.
    What remains is a defensive integrity check: an unresolved tie handed to _apply_result()
    under a has_shootout=True rule (which should never happen via the real engine -- only
    reachable here via a hand-constructed GameResult, exactly as this test does) must raise
    loudly rather than silently mis-recording an illegal Game."""
    from pucksim.models.league import Game

    world = build_world(seed=20)
    world.standings_rule = rule
    home_tid, away_tid, result = _make_tied_result(world)
    game = Game(gid=world.new_gid(), day=0, home=home_tid, away=away_tid)

    with pytest.raises(AssertionError):
        _apply_result(world, game, result)


@pytest.mark.parametrize("rule", ["standard", "three_two_one_zero"])
def test_sim_one_never_produces_an_unresolved_tie_under_has_shootout_rule(rule):
    """DEVPLAN.md Step 2.6's core invariant, exercised end-to-end via sim_one(): the real engine's
    3-on-3-OT -> shootout resolution means every played game under a has_shootout=True rule comes
    back decisive, straight from the engine, with no season-level placeholder involved. Swept
    across enough seeds/matchups that this would fail loudly (via the AssertionError guard in
    _apply_result, see the test above) if the engine ever regressed to producing an unresolved
    tie under this rule."""
    from pucksim.models.league import Game

    world = build_world(seed=1)
    world.standings_rule = rule
    tids = sorted(world.teams.keys())

    checked = 0
    for home_tid, away_tid in itertools.islice(itertools.combinations(tids, 2), 12):
        game = Game(gid=world.new_gid(), day=0, home=home_tid, away=away_tid)
        sim_one(world, game)   # would raise AssertionError if this ever came back undecided
        assert game.played is True
        assert game.is_tie is False
        assert game.winner is not None
        standings(list(world.teams.values()), [game], rule)
        checked += 1

    assert checked == 12


def test_sim_one_retro_can_still_produce_a_legitimate_tie():
    """Under "retro" (no shootout), a game can still legitimately end level after 3-on-3 OT --
    search across seeds/matchups for at least one (real 3-on-3 OT converts at a meaningfully
    higher rate than the old MVP placeholder period did, so this needs a somewhat wider seed
    sweep than the pre-Step-2.6 version of this test used to reliably find one)."""
    from pucksim.models.league import Game

    found = False
    for seed in range(1, 120):
        world = build_world(seed=seed)
        world.standings_rule = "retro"
        tids = sorted(world.teams.keys())
        home_tid, away_tid = tids[0], tids[1]

        game = Game(gid=world.new_gid(), day=0, home=home_tid, away=away_tid)
        sim_one(world, game)
        if not game.is_tie:
            continue

        assert game.played is True
        assert game.winner is None
        standings(list(world.teams.values()), [game], "retro")
        found = True
        break

    assert found, "expected at least one legitimate retro tie across 120 seeds"


# ---------------------------------------------------------------------------
# Player season stat accumulation
# ---------------------------------------------------------------------------
def test_player_season_stats_accumulate_across_games():
    world = build_world(seed=30)
    world.schedule = generate_schedule(world, target_games=4)
    world.day = 0
    for team in world.teams.values():
        team.reset_record()
    for player in world.players.values():
        player.season.reset()

    while not regular_season_complete(world):
        advance_one_day(world)

    # At least one skater should have accumulated multiple games' worth of ice time/goals across
    # several games played.
    any_multi_game_secs = False
    for player in world.players.values():
        if player.is_goalie:
            continue
        if player.season.secs > 0:
            any_multi_game_secs = True
    assert any_multi_game_secs

    # gp should reflect the number of games actually played by a team whose roster this player is
    # on -- spot check goalies too (secs accumulate for the starter across played games).
    for team in world.teams.values():
        starter = world.player(team.goalie_starter) if team.goalie_starter else None
        if starter is not None:
            assert starter.season.gp >= 1


# ---------------------------------------------------------------------------
# start_season resets records/stats and builds a fresh schedule
# ---------------------------------------------------------------------------
def test_start_season_resets_records_and_stats_and_builds_schedule():
    world = build_world(seed=40)
    # Simulate some "leftover" state from a prior season.
    any_team = next(iter(world.teams.values()))
    any_team.wins = 10
    any_team.losses = 5
    any_team.ot_losses = 2
    any_team.streak = 3
    any_player = next(iter(world.players.values()))
    if any_player.is_goalie:
        any_player.season.wins = 3
    else:
        any_player.season.g = 7

    start_season(world)

    assert any_team.wins == 0
    assert any_team.losses == 0
    assert any_team.ot_losses == 0
    assert any_team.streak == 0
    if any_player.is_goalie:
        assert any_player.season.wins == 0
    else:
        assert any_player.season.g == 0
    assert len(world.schedule) > 0
    assert world.day == 0
    from pucksim.models.league import Phase
    assert world.phase == Phase.REGULAR_SEASON


def test_regular_season_complete_false_until_all_games_played():
    world = build_world(seed=41)
    world.schedule = generate_schedule(world, target_games=2)
    assert not regular_season_complete(world)
    world.day = 0
    while not regular_season_complete(world):
        advance_one_day(world)
    assert regular_season_complete(world)


def test_advance_one_day_only_plays_todays_games_and_increments_day():
    world = build_world(seed=42)
    world.schedule = generate_schedule(world, target_games=4)
    world.day = 0
    start_day = world.day
    played_today = advance_one_day(world)

    assert all(g.day == start_day for g in played_today)
    assert all(g.played for g in played_today)
    assert world.day == start_day + 1
    # Any game scheduled for a later day should still be unplayed.
    later_games = [g for g in world.schedule if g.day > start_day]
    assert all(not g.played for g in later_games)
