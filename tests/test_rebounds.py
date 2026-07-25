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


def _conversion(rebound: bool, trials: int = 4000) -> float:
    """Directly resolve many shot attempts flagged rebound / not-rebound against the SAME shooters
    and goalie, and return the goal rate. Driving _resolve_shot_attempt directly (rather than
    counting the rare in-game rebounds) isolates the rebound danger bonus from game-flow noise, so
    the effect is measured cleanly and deterministically. Period 1 so clutch gating never fires."""
    world = build_world(seed=20)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    sim._advance_shift_for_all()
    sim.period = 1
    off, deff = sim.home, sim.away
    goals = 0
    for _ in range(trials):
        sim.result.home_score = sim.result.away_score = 0
        if sim._resolve_shot_attempt(off, deff, rush=False, rebound=rebound) == "goal":
            goals += 1
    return goals / trials


def test_rebound_shots_convert_at_a_higher_rate_than_normal_shots():
    """The load-bearing assertion for the user's directive: rebound goals happen at a higher rate
    than normal ones. Measured directly on the shot-resolution math (same shooters/goalie) so it's
    a clean, deterministic read of the rebound danger bonus, not a rare-and-noisy in-game count."""
    reb_conv = _conversion(rebound=True)
    norm_conv = _conversion(rebound=False)
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
    loop) plus their higher conversion must keep total scoring in a realistic NHL band.

    Samples every team in each world exactly once (16 disjoint matchups) rather than always playing
    ``tids[0]`` against ``tids[1]``. That fixed pairing was a biased sample, not a neutral one --
    team 0 draws a top-5 goalie in most seeds, so 0-vs-1 games average 4.55 goals where sampling
    all 32 teams from the same worlds gives 5.37. The bias was harmless while it happened to land
    inside the band, and became a spurious failure the moment scoring moved for legitimate reasons.
    An arbitrary pair is also a high-variance estimator: two different pairing schemes over the same
    80 games disagreed by 0.7 goals, which is more than the distance to the band edge.

    Note this measures single games out of freshly generated worlds, a different quantity from
    league-wide goals per game over a played season (~6.2 -- see ``goals_per_game`` in
    testkit/distribution.py and docs/DISTRIBUTION_TARGETS.md). Fresh worlds have no accumulated
    injuries, no goalie rotation and un-juggled lines, all of which suppress scoring relative to a
    real season. This band is wide enough to cover both readings; the season-level instrument is
    the tighter one.
    """
    total_goals = 0
    games = 0
    for seed in range(5):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        half = len(tids) // 2
        for i in range(half):
            result = GameSim(world, tids[i], tids[i + half]).play()
            total_goals += result.home_score + result.away_score
            games += 1
    per_game = total_goals / games
    assert 4.8 <= per_game <= 6.6, f"goals/game drifted to {per_game:.2f}"
