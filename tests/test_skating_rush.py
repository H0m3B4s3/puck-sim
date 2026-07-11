"""Coverage for skating/agility driving the rush and zone entry (DEVPLAN.md Step 2.x).

skating and agility were composite-only ratings that never touched a live outcome. This step gives
a player's speed (0.5*skating + 0.5*agility) two effects: it scales the rush finishing bonus, and
it reduces how often the attacking team is blown offside. Guarantees pinned here:
  * a faster shooter finishes a rush at a higher rate;
  * the offside chance falls as a team gets faster (cleaner zone entries);
  * fast teams outscore slow ones; and
  * league scoring stays realistic (both effects are centered on the rating mean).
"""
from __future__ import annotations

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.sim.engine import GameSim


def _team_skater_pids(world, tid) -> set[int]:
    return {p.pid for p in world.players.values() if p.team_id == tid and not p.is_goalie}


def _pin_team_speed(world, tid, value: int) -> set[int]:
    pids = _team_skater_pids(world, tid)
    for pid in pids:
        world.players[pid].ratings["skating"] = value
        world.players[pid].ratings["agility"] = value
    return pids


def _rush_goal_rate(speed: int, trials: int = 2500) -> float:
    """Fresh same-seed sim so the only difference is the shooters' speed. Shooting is boosted so
    the skill gap is clearly positive; every attempt is forced to be a rush."""
    world = build_world(seed=20)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    sim._advance_shift_for_all()
    off, deff = sim.home, sim.away
    for pid in off.on_ice:
        rr = off.players[pid].ratings
        rr["skating"] = rr["agility"] = speed
        rr["shot_accuracy"] = rr["shot_power"] = rr["offensive_awareness"] = 95
    goals = 0
    for _ in range(trials):
        if sim._resolve_shot_attempt(off, deff, rush=True, rebound=False) == "goal":
            goals += 1
    return goals / trials


def test_faster_shooters_finish_the_rush_at_a_higher_rate():
    fast = _rush_goal_rate(99)
    slow = _rush_goal_rate(25)
    assert fast > slow, f"rush: speed-99 rate {fast:.3f} !> speed-25 rate {slow:.3f}"


def test_offside_chance_falls_as_a_team_gets_faster():
    """Unit check on the zone-entry multiplier: a faster attacking group is blown offside less."""
    world = build_world(seed=1)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    sim._advance_shift_for_all()
    off = sim.home
    for pid in off.on_ice:
        off.players[pid].ratings["skating"] = off.players[pid].ratings["agility"] = 99
    fast_mult = sim._team_speed_mult_for_offside(off)
    for pid in off.on_ice:
        off.players[pid].ratings["skating"] = off.players[pid].ratings["agility"] = 25
    slow_mult = sim._team_speed_mult_for_offside(off)
    assert fast_mult < 1.0 < slow_mult, f"fast {fast_mult:.3f}, slow {slow_mult:.3f}"


def test_fast_teams_outscore_slow_teams():
    def team_goals(speed: int) -> int:
        total = 0
        for g in range(40):
            world = build_world(seed=600 + g)
            tids = sorted(world.teams.keys())
            _pin_team_speed(world, tids[0], speed)   # team A = home
            result = GameSim(world, tids[0], tids[1]).play()
            total += result.home_score
        return total
    assert team_goals(99) > team_goals(25)


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
