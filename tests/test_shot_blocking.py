"""Coverage for shot_blocking driving block outcomes + the blocks stat (DEVPLAN.md Step 2.x).

Before this step the block-vs-miss split was a flat zone-only probability and the SkaterStatLine
``blocks`` field was never incremented. These tests pin the two guarantees added:
  * a defending corps of elite shot-blockers blocks materially more attempts than a corps of poor
    ones (monotonic in the rating), and
  * every block outcome is credited to exactly one on-ice defender (the box-score sum reconciles
    with the play-by-play block count), and the league-wide block rate stays near its pre-rating
    baseline (this step wires a rating in; it does NOT re-scale how many blocks happen overall).
"""
from __future__ import annotations

from pucksim.gen.leaguegen import build_world
from pucksim.sim.boxscore import EVENT_SHOT, SHOT_OUTCOME_BLOCK
from pucksim.sim.engine import GameSim


def _team_skater_pids(world, tid) -> set[int]:
    return {p.pid for p in world.players.values()
            if p.team_id == tid and not p.is_goalie}


def _blocks_for_team_defending(seed_base: int, block_rating: int, n_games: int = 30) -> int:
    """Total blocks credited to team B's skaters across ``n_games``, with every one of B's skaters
    pinned to ``block_rating`` shot_blocking. B is the defending team we measure; A is left alone."""
    total = 0
    for g in range(n_games):
        world = build_world(seed=seed_base + g)
        tids = sorted(world.teams.keys())
        a, b = tids[0], tids[1]
        b_skaters = _team_skater_pids(world, b)
        for pid in b_skaters:
            world.players[pid].ratings["shot_blocking"] = block_rating
        result = GameSim(world, a, b).play()
        total += sum(line.blocks for pid, line in result.skater_box.items()
                     if pid in b_skaters)
    return total


def test_elite_shot_blockers_block_more_than_poor_ones():
    """The load-bearing monotonicity assertion: a wall of 99-rated shot-blockers blocks more of
    the opponent's off-goal attempts than a wall of 25-rated ones, seeds/teams held fixed."""
    elite = _blocks_for_team_defending(500, block_rating=99)
    poor = _blocks_for_team_defending(500, block_rating=25)
    assert elite > poor, f"elite blockers recorded {elite}, poor blockers {poor}"


def test_every_block_outcome_is_credited_to_a_skater():
    """Box-score blocks must reconcile exactly with play-by-play block outcomes -- no block is
    ever dropped on the floor or double-counted."""
    for seed in range(20):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        result = GameSim(world, tids[0], tids[1], collect_pbp=True).play()
        pbp_blocks = sum(1 for e in result.pbp
                         if e.event_type == EVENT_SHOT and e.outcome == SHOT_OUTCOME_BLOCK)
        credited = sum(line.blocks for line in result.skater_box.values())
        assert credited == pbp_blocks


def test_block_rate_stays_near_baseline_with_normal_ratings():
    """Wiring shot_blocking in must not silently re-scale how many blocks happen league-wide. With
    unmodified generated ratings the total block outcomes per game stays in a tight band around the
    pre-rating baseline (~4.6/game across both teams)."""
    total_blocks = 0
    n = 40
    for seed in range(n):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        result = GameSim(world, tids[0], tids[1], collect_pbp=True).play()
        total_blocks += sum(1 for e in result.pbp
                            if e.event_type == EVENT_SHOT and e.outcome == SHOT_OUTCOME_BLOCK)
    per_game = total_blocks / n
    assert 3.0 <= per_game <= 6.5, f"block rate drifted to {per_game:.2f}/game"
