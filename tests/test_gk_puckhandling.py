"""Coverage for goalie puck-handling killing rushes (DEVPLAN.md Step 2.x).

gk_puck_handling was a composite-only rating that never touched live play. Now a puck-moving
defending goalie sometimes cuts off a zone entry before the rush develops, so the attacking team
generates fewer rush chances against him. Guarantees pinned here:
  * the rush-kill chance rises with gk_puck_handling and is one-sided (no effect below the pivot);
  * a game against an elite puck-handling goalie produces fewer rush shots than against a poor one;
  * league scoring stays realistic.
"""
from __future__ import annotations

from pucksim.gen.leaguegen import build_world
from pucksim.sim.boxscore import EVENT_GOAL, EVENT_SHOT
from pucksim.sim.engine import GameSim


def _pin_goalies(world, tid, gkph: int) -> None:
    for p in world.players.values():
        if p.is_goalie and p.team_id == tid:
            p.ratings["gk_puck_handling"] = gkph


def test_rush_kill_rises_with_puck_handling_and_is_one_sided():
    world = build_world(seed=5)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])

    def kills(gkph: int, trials: int = 3000) -> int:
        for p in world.players.values():
            if p.is_goalie:
                p.ratings["gk_puck_handling"] = gkph
        return sum(sim._goalie_negates_rush(sim.away) for _ in range(trials))

    elite = kills(99)
    average = kills(67)     # at the pivot -> no effect
    poor = kills(40)        # below the pivot -> no effect (one-sided)
    assert elite > 0
    assert average == 0
    assert poor == 0
    assert elite > average


def test_puck_handling_goalie_faces_fewer_rush_shots():
    def rush_shots_against(gkph: int) -> int:
        total = 0
        for s in range(50):
            world = build_world(seed=700 + s)
            tids = sorted(world.teams.keys())
            _pin_goalies(world, tids[1], gkph)      # away goalie
            result = GameSim(world, tids[0], tids[1], collect_pbp=True).play()
            total += sum(1 for e in result.pbp
                         if e.event_type in (EVENT_SHOT, EVENT_GOAL)
                         and e.team_id == tids[0] and e.rush)
        return total
    assert rush_shots_against(99) < rush_shots_against(40)


def test_goals_per_game_stays_realistic():
    total_goals = 0
    n = 100
    for seed in range(n):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        result = GameSim(world, tids[0], tids[1]).play()
        total_goals += result.home_score + result.away_score
    per_game = total_goals / n
    assert 4.6 <= per_game <= 6.6, f"goals/game drifted to {per_game:.2f}"
