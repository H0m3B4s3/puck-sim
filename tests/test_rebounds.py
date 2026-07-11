"""Coverage for rebound_control + rebound high-danger conversion (DEVPLAN.md Step 2.x).

Two guarantees this step adds:
  * a shot off a rebound converts at a materially HIGHER rate than a normal shot (goalie out of
    position, open net) -- rebounds are genuine high-danger chances; and
  * a goalie's `rebound_control` rating suppresses how often a save kicks out a rebound in the
    first place (elite goalies smother pucks).
Plus a calibration guardrail: making rebounds resolve as immediate extra looks (rather than being
lost to the shift clock) must not blow up total scoring -- goals/game stays in the realistic band.
"""
from __future__ import annotations

from pucksim.gen.leaguegen import build_world
from pucksim.sim.boxscore import EVENT_GOAL, EVENT_SHOT
from pucksim.sim.engine import GameSim


def _shot_events(result):
    return [e for e in result.pbp if e.event_type in (EVENT_SHOT, EVENT_GOAL)]


def test_rebound_shots_convert_at_a_higher_rate_than_normal_shots():
    """The load-bearing assertion for the user's directive: rebound goals happen at a higher rate
    than normal ones. Aggregated across many games so the (rarer) rebound sample is meaningful."""
    reb_att = reb_goals = norm_att = norm_goals = 0
    for seed in range(80):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        result = GameSim(world, tids[0], tids[1], collect_pbp=True).play()
        for e in _shot_events(result):
            is_goal = e.event_type == EVENT_GOAL
            if e.rebound:
                reb_att += 1
                reb_goals += is_goal
            else:
                norm_att += 1
                norm_goals += is_goal
    assert reb_att > 100, f"too few rebound attempts to judge ({reb_att})"
    reb_conv = reb_goals / reb_att
    norm_conv = norm_goals / norm_att
    assert reb_conv > norm_conv * 1.3, (
        f"rebound conv {reb_conv:.3f} not distinctly above normal {norm_conv:.3f}")


def _rebound_count(rebound_control: int, n_games: int = 40) -> int:
    """Total rebound shot-events across ``n_games`` with every goalie pinned to ``rebound_control``."""
    total = 0
    for g in range(n_games):
        world = build_world(seed=1000 + g)
        tids = sorted(world.teams.keys())
        for p in world.players.values():
            if p.is_goalie:
                p.ratings["rebound_control"] = rebound_control
        result = GameSim(world, tids[0], tids[1], collect_pbp=True).play()
        total += sum(1 for e in _shot_events(result) if e.rebound)
    return total


def test_high_rebound_control_surrenders_fewer_rebounds():
    """Elite rebound_control goalies (99) kick out materially fewer rebounds than poor ones (25),
    seeds/teams held fixed -- the rating is monotonic in the outcome it governs."""
    elite = _rebound_count(99)
    poor = _rebound_count(25)
    assert elite < poor, f"rc=99 gave {elite} rebounds, rc=25 gave {poor}"


def test_goals_per_game_stays_realistic():
    """Calibration guardrail: resolving rebounds as immediate extra looks (a change to the shift
    loop) plus their higher conversion must keep total scoring in a realistic NHL band."""
    total_goals = 0
    n = 80
    for seed in range(n):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        result = GameSim(world, tids[0], tids[1]).play()
        total_goals += result.home_score + result.away_score
    per_game = total_goals / n
    assert 4.8 <= per_game <= 6.6, f"goals/game drifted to {per_game:.2f}"
