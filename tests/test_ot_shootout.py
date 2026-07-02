"""Tests for real OT/shootout resolution -- DEVPLAN.md Step 2.6 done-criteria.

Covers: regular-season 3-on-3 OT -> real shootout resolution under has_shootout=True standings
rules (correct point awards per Step 1.8's tables, always a decisive winner straight from the
engine, no season.py placeholder involved -- see sim/season.py's module docstring, which
documents that the MVP-era placeholder tiebreak was REMOVED, not just left unused, by this step);
"retro" never invokes the shootout and can legitimately end level; full tests/test_season.py and
tests/test_engine.py still pass with the placeholder logic actually gone.
"""
from __future__ import annotations

import itertools

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.models.league import Game, points_for_game
from pucksim.sim.boxscore import EVENT_GAME_END
from pucksim.sim.engine import GameSim, simulate_game
from pucksim.sim.season import sim_one


def _tids(world):
    return sorted(world.teams.keys())


# ---------------------------------------------------------------------------
# 3-on-3 regular-season OT strength state
# ---------------------------------------------------------------------------
def test_regular_season_ot_uses_3v3_base_state():
    """A regular-season game (is_playoff=False, the default) that reaches OT should set the
    strength machine's base_state to STRENGTH_3V3, not STRENGTH_5V5 -- the core Step 2.6
    requirement that regular-season OT is a real 3-on-3 strength state, not a re-run of the
    regulation 5v5 shift logic."""
    found = False
    for seed in range(1, 40):
        world = build_world(seed=seed)
        tids = _tids(world)
        sim = GameSim(world, tids[0], tids[1], collect_pbp=True)
        result = sim.play()
        if result.went_ot:
            assert sim.strength.base_state == config.STRENGTH_3V3
            found = True
            break
    assert found, "expected at least one regular-season OT game across 40 seeds"


def test_regular_season_ot_shift_events_log_3v3_strength_state():
    """Shot-attempt events logged during regular-season OT (period > config.PERIODS, no active
    penalty) should carry strength_state == STRENGTH_3V3 in the PBP log -- proving the 3-on-3
    state is real, live game state consumed by shot resolution, not just a label."""
    found = False
    for seed in range(1, 40):
        world = build_world(seed=seed)
        tids = _tids(world)
        result = GameSim(world, tids[0], tids[1], collect_pbp=True).play()
        if not result.went_ot:
            continue
        ot_events = [e for e in result.pbp
                    if e.period > config.PERIODS and e.strength_state is not None]
        threev3_events = [e for e in ot_events if e.strength_state == config.STRENGTH_3V3]
        if threev3_events:
            found = True
            break
    assert found, "expected at least one OT shot/goal event logged at STRENGTH_3V3"


# ---------------------------------------------------------------------------
# Playoff OT uses 5v5, never 3v3, never a shootout
# ---------------------------------------------------------------------------
def test_playoff_ot_uses_5v5_base_state_not_3v3():
    found = False
    for seed in range(1, 40):
        world = build_world(seed=seed)
        tids = _tids(world)
        sim = GameSim(world, tids[0], tids[1], is_playoff=True, collect_pbp=True)
        result = sim.play()
        if result.went_ot:
            assert sim.strength.base_state == config.STRENGTH_5V5
            found = True
            break
    assert found, "expected at least one playoff OT game across 40 seeds"


def test_playoff_games_never_go_to_shootout():
    """DESIGN.md point 8: playoff OT is full 5-on-5 sudden death, repeated until decided -- never
    a shootout, ever, regardless of the active standings rule."""
    for seed in range(1, 15):
        world = build_world(seed=seed)
        tids = _tids(world)
        for home_tid, away_tid in itertools.islice(itertools.combinations(tids, 2), 3):
            result = GameSim(world, home_tid, away_tid, is_playoff=True).play()
            assert result.went_so is False
            assert result.winner is not None


# ---------------------------------------------------------------------------
# Shootout resolution correctness (regular season, has_shootout=True rules)
# ---------------------------------------------------------------------------
def _find_shootout_game(seed_range=range(1, 60)):
    """Search for a regular-season game that goes all the way to a real shootout."""
    for seed in seed_range:
        world = build_world(seed=seed)
        tids = _tids(world)
        for home_tid, away_tid in itertools.islice(itertools.combinations(tids, 2), 4):
            result = GameSim(world, home_tid, away_tid, collect_pbp=True).play()
            if result.went_so:
                return world, home_tid, away_tid, result
    return None


def test_shootout_is_reachable_and_always_decisive():
    found = _find_shootout_game()
    assert found is not None, "expected at least one shootout game across the search sweep"
    _, _, _, result = found
    assert result.went_ot is True
    assert result.went_so is True
    assert result.winner is not None
    assert result.home_score != result.away_score


def test_shootout_logs_a_distinguishing_pbp_event():
    found = _find_shootout_game()
    assert found is not None
    _, _, _, result = found
    game_end_events = [e for e in result.pbp if e.event_type == EVENT_GAME_END]
    assert game_end_events
    assert any("shootout" in e.description.lower() for e in game_end_events)


def test_shootout_never_leaves_score_tied():
    """A shootout must always produce a decisive final score (winner gets exactly +1 goal over
    the OT-tied score) across many independent trials -- statistical sweep, not a single seed."""
    trials = 0
    for seed in range(1, 80):
        world = build_world(seed=seed)
        tids = _tids(world)
        result = GameSim(world, tids[0], tids[1]).play()
        if result.went_so:
            trials += 1
            assert result.home_score != result.away_score
            assert abs(result.home_score - result.away_score) == 1
    assert trials >= 1


# ---------------------------------------------------------------------------
# Standings-points correctness for a shootout-decided game (Step 1.8's tables)
# ---------------------------------------------------------------------------
def test_shootout_win_awards_correct_points_standard_rule():
    found = _find_shootout_game()
    assert found is not None
    world, home_tid, away_tid, result = found
    world.standings_rule = "standard"
    game = Game(gid=world.new_gid(), day=0, home=home_tid, away=away_tid,
               home_score=result.home_score, away_score=result.away_score,
               played=True, went_ot=result.went_ot, went_so=result.went_so)

    winner_tid = game.winner
    loser_tid = game.loser
    assert winner_tid is not None

    win_pts = points_for_game("standard", winner_tid, game)
    loss_pts = points_for_game("standard", loser_tid, game)
    assert win_pts == config.STANDINGS_RULES["standard"]["so_win"] == 2
    assert loss_pts == config.STANDINGS_RULES["standard"]["so_loss"] == 1


def test_shootout_win_awards_correct_points_three_two_one_zero_rule():
    found = _find_shootout_game()
    assert found is not None
    world, home_tid, away_tid, result = found
    world.standings_rule = "three_two_one_zero"
    game = Game(gid=world.new_gid(), day=0, home=home_tid, away=away_tid,
               home_score=result.home_score, away_score=result.away_score,
               played=True, went_ot=result.went_ot, went_so=result.went_so)

    winner_tid = game.winner
    loser_tid = game.loser
    win_pts = points_for_game("three_two_one_zero", winner_tid, game)
    loss_pts = points_for_game("three_two_one_zero", loser_tid, game)
    assert win_pts == config.STANDINGS_RULES["three_two_one_zero"]["so_win"] == 2
    assert loss_pts == config.STANDINGS_RULES["three_two_one_zero"]["so_loss"] == 1


# ---------------------------------------------------------------------------
# Retro: no shootout ever, undecided OT can legitimately stand as a tie
# ---------------------------------------------------------------------------
def test_retro_never_invokes_shootout():
    for seed in range(1, 30):
        world = build_world(seed=seed)
        world.standings_rule = "retro"
        tids = _tids(world)
        for home_tid, away_tid in itertools.islice(itertools.combinations(tids, 2), 3):
            result = simulate_game(world, home_tid, away_tid)
            assert result.went_so is False


def test_retro_can_end_in_a_legitimate_tie_via_sim_one():
    found = False
    for seed in range(1, 120):
        world = build_world(seed=seed)
        world.standings_rule = "retro"
        tids = _tids(world)
        home_tid, away_tid = tids[0], tids[1]
        game = Game(gid=world.new_gid(), day=0, home=home_tid, away=away_tid)
        sim_one(world, game)
        if game.is_tie:
            assert game.winner is None
            assert game.went_so is False
            assert game.went_ot is True   # 3-on-3 OT was played and didn't decide it
            found = True
            break
    assert found, "expected at least one legitimate retro tie across 120 seeds"


# ---------------------------------------------------------------------------
# The MVP-era season.py placeholder tiebreak is actually gone, not just unused.
# ---------------------------------------------------------------------------
def test_placeholder_tiebreak_function_no_longer_exists():
    """DEVPLAN.md Step 2.6 explicit instruction: remove season.py's now-redundant placeholder
    tiebreak once the engine makes it obsolete, don't leave it dangling as dead/unused code."""
    import pucksim.sim.season as season_mod
    assert not hasattr(season_mod, "_placeholder_tiebreak_winner")
    assert not hasattr(season_mod, "_average_overall")


def test_full_short_season_still_passes_under_every_standings_rule():
    """Regression coverage mirroring tests/test_season.py's own full-season sweep, run here too
    since this step is what makes has_shootout=True season runs never need the old placeholder."""
    from pucksim.sim.season import advance_one_day, generate_schedule, regular_season_complete

    for rule in ("standard", "retro", "three_two_one_zero"):
        world = build_world(seed=55)
        world.standings_rule = rule
        world.schedule = generate_schedule(world, target_games=6)
        world.day = 0
        for team in world.teams.values():
            team.reset_record()
        while not regular_season_complete(world):
            advance_one_day(world)
        for g in world.schedule:
            assert g.played
            if rule != "retro":
                assert g.winner is not None
