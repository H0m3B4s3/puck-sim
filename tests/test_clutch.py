"""Coverage for clutch/composure gating (DEVPLAN.md Step 2.x).

The clutch_realization() function existed but was never called. This step gates it to high-leverage
moments and folds it into the shooter's realization. The guarantees pinned here:
  * the "never up-weight" contract: composure only ever holds a player at his level (<=1.0) or
    dips him below it -- an elite-composure player gets NO boost;
  * the leverage gate fires only late-and-close; and
  * in a clutch moment a high-composure shooting group outscores a low-composure one, while
    OUTSIDE a clutch moment composure has literally zero effect (identical RNG -> identical goals).
"""
from __future__ import annotations

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.sim import ratings as R
from pucksim.sim.engine import GameSim


# ---------------------------------------------------------------------------
# Contract: clutch_realization never exceeds 1.0 (no upweighting)
# ---------------------------------------------------------------------------
def test_clutch_realization_never_upweights_and_is_monotone():
    assert R.clutch_realization(99) == 1.0            # elite composure: holds peak, no boost
    assert R.clutch_realization(70) < 1.0             # average dips a touch under pressure
    assert R.clutch_realization(25) == R.CLUTCH_R_MIN  # weak-nerved choke floors out
    assert all(R.clutch_realization(c) <= 1.0 for c in range(0, 120))
    assert all(R.clutch_realization(c) <= R.clutch_realization(c + 1) for c in range(0, 119))


# ---------------------------------------------------------------------------
# Leverage gate
# ---------------------------------------------------------------------------
def _sim():
    world = build_world(seed=1)
    tids = sorted(world.teams.keys())
    return GameSim(world, tids[0], tids[1])


def test_clutch_gate_fires_only_late_and_close():
    sim = _sim()
    sim.period = config.PERIODS
    sim.result.home_score, sim.result.away_score = 2, 2
    assert sim._is_clutch_situation()                 # 3rd, tied
    sim.result.away_score = 1
    assert sim._is_clutch_situation()                 # 3rd, one-goal game
    sim.result.away_score = 0
    assert not sim._is_clutch_situation()             # 3rd, two-goal game -> not clutch
    sim.period = 1
    sim.result.away_score = 2
    assert not sim._is_clutch_situation()             # 1st, tied -> too early
    sim.period = 1
    sim._is_ot = True
    sim.result.home_score, sim.result.away_score = 3, 3
    assert sim._is_clutch_situation()                 # OT is always clutch when close


# ---------------------------------------------------------------------------
# Integration: composure matters in the clutch, and ONLY in the clutch
# ---------------------------------------------------------------------------
_RATE_SEEDS = (20, 3, 7, 11)


def _goal_rate(composure: int, period: int, trials: int = 6000) -> float:
    """Fresh same-seed sims so the ONLY difference between two calls is the shooters' composure.

    Composure reaches the outcome through exactly one term -- ``gap * off_real`` -- and its full
    99-vs-25 span is only 1.0 vs CLUTCH_R_MIN (0.93), i.e. 7% of the gap. To make that observable
    the arrangement deliberately MAXIMIZES the gap: home shooters are boosted to 95 and the
    defending goalie is floored, so 7% of the gap is a measurable share of the goal rate rather
    than a rounding error. Rates are then pooled over several seeds.

    This is a statistical measurement, so it needs statistical power. An earlier version ran 2500
    trials on one seed against an unmodified goalie: the two arms' per-attempt goal probabilities
    differed by ~0.004 against a binomial standard error ~4x larger, so it was passing on luck
    (and did in fact flip to equal counts when an unrelated save-probability constant moved). The
    present form separates the arms by ~4 sigma.
    """
    goals = attempts = 0
    for seed in _RATE_SEEDS:
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        sim = GameSim(world, tids[0], tids[1])
        sim._advance_shift_for_all()
        sim.period = period
        off, deff = sim.home, sim.away
        for pid in off.on_ice:
            r = off.players[pid].ratings
            r["composure"] = composure
            r["shot_accuracy"] = r["shot_power"] = r["offensive_awareness"] = 95
        goalie = deff.goalie()
        goalie.ratings["reflexes"] = goalie.ratings["positioning"] = 25
        for _ in range(trials):
            sim.result.home_score = sim.result.away_score = 0  # tied -> clutch when period is late
            if sim._resolve_shot_attempt(off, deff, rush=False, rebound=False) == "goal":
                goals += 1
            attempts += 1
    return goals / attempts


def test_high_composure_outscores_low_composure_in_the_clutch():
    high = _goal_rate(99, period=config.PERIODS)
    low = _goal_rate(25, period=config.PERIODS)
    assert high > low, f"clutch: composure-99 rate {high:.3f} !> composure-25 rate {low:.3f}"
    # And by a margin well clear of sampling noise, so a real regression to "composure does
    # nothing" cannot pass by drifting to within a hair of equality.
    assert high - low > 0.005, f"clutch composure edge {high - low:.4f} is inside the noise floor"


def test_composure_has_no_effect_outside_the_clutch():
    """Outside a clutch moment the gate is closed, so composure changes nothing -- with identical
    RNG the two composure settings must produce byte-identical goal counts."""
    high = _goal_rate(99, period=1)
    low = _goal_rate(25, period=1)
    assert high == low, f"non-clutch: composure leaked ({high:.4f} vs {low:.4f})"
