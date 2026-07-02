"""Derived on-ice-group ratings and tactic-to-number mappings consumed by the engine.

Keeping this separate from ``engine.py`` mirrors HoopR's ``hoopsim/sim/ratings.py`` (148 lines):
the math that turns a group of players + a coach's tendencies into modifiers is testable on its
own and easy to rebalance without touching control flow.

Realization model (DESIGN.md's "What carries over directly from HoopR" section, ported nearly
verbatim -- same shape/scaling, hockey-renamed rating keys): morale x chemistry x clutch as
multiplicative factors, each in ``[floor, 1.0]``, that scale the *skill gap* between two competing
ratings (e.g. a shooter's shot_accuracy vs. a goalie's reflexes+positioning) rather than the base
rate. All three are capped at 1.0 by design -- a player reaches his ceiling when confident, gelled,
and composed under pressure, but never exceeds his own rating. Neutral (rating 70 / full
familiarity / not in a clutch situation) realizes fully; only slumps, scrambled lines, and chokes
dip below. HoopR's "clutch" rating renames to PuckSim's ``composure`` (attributes.py's Mental
group) -- same mechanism, hockey-appropriate name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from pucksim.models.player import Player

# ---------------------------------------------------------------------------
# Coach shot_volume / shot_quality_bias -> numeric modifiers
# ---------------------------------------------------------------------------
# Consumed starting at this step (DEVPLAN.md Step 1.12) per coach.py's own docstring. Both floats
# are 0..1 tendency knobs on CoachProfile; these helpers turn them into the two things a shift
# actually needs: how many shot attempts to generate, and how much to skew shot selection toward
# higher-quality (danger-zone, non-rebound-adjacent) looks vs. pure volume.
#
# Baseline (0.5, "Balanced"): 1.0x attempt rate, neutral quality skew. PROVISIONAL/TUNABLE, same
# framing as every other first-pass constant in this codebase -- these are reasonable starting
# magnitudes, not a tuned model.
SHOT_VOLUME_MIN_MULT = 0.70    # shot_volume = 0.0: fewest attempts
SHOT_VOLUME_MAX_MULT = 1.30    # shot_volume = 1.0: most attempts

SHOT_QUALITY_MIN_BIAS = -0.15  # shot_quality_bias = 0.0: fires from anywhere (volume over quality)
SHOT_QUALITY_MAX_BIAS = 0.15   # shot_quality_bias = 1.0: works for the high-danger look


def shot_volume_multiplier(shot_volume: float) -> float:
    """Scales expected shot-attempts-per-shift for a team's offensive system.

    Linear interpolation between SHOT_VOLUME_MIN_MULT (0.0) and SHOT_VOLUME_MAX_MULT (1.0),
    anchored so the 0.5 "Balanced" archetype nets to 1.0x (no change from today's tuning).
    """
    sv = max(0.0, min(1.0, shot_volume))
    return SHOT_VOLUME_MIN_MULT + (SHOT_VOLUME_MAX_MULT - SHOT_VOLUME_MIN_MULT) * sv


def shot_quality_bias_delta(shot_quality_bias: float) -> float:
    """A delta added to a shot attempt's "quality roll" (see engine._pick_zone_and_shot_type):

    higher shot_quality_bias nudges shot selection toward better-danger zones/shot types; lower
    pushes toward volume shots from lower-quality areas. Zero at the 0.5 "Balanced" archetype.
    """
    sqb = max(0.0, min(1.0, shot_quality_bias))
    return SHOT_QUALITY_MIN_BIAS + (SHOT_QUALITY_MAX_BIAS - SHOT_QUALITY_MIN_BIAS) * sqb


# ---------------------------------------------------------------------------
# Realization: morale, chemistry (lineup familiarity), and clutch/composure
# ---------------------------------------------------------------------------
# Ported nearly verbatim from HoopR's hoopsim/sim/ratings.py -- same constants' *shape*, hockey's
# own numbers where the baseline differs (PuckSim's rating scale is also 25-99, centered near a
# 70 "average NHL regular" per gen/leaguegen.py, matching HoopR's own 70-baseline league).
MORALE_R_MIN = 0.85              # deepest a total funk drags a player below his ceiling
MORALE_R_SLOPE = 0.0024          # realization lost per morale point below neutral (70)
CHEM_R_MIN = 0.92                # a line/pair of strangers vs. a fully gelled unit
CLUTCH_R_MIN = 0.93              # worst choke under pressure
CLUTCH_PRESSURE_ANCHOR = 0.97    # realization for an average-composure player under pressure

# Shared on-ice seconds at which a pair of players is "fully gelled" -- mirrors HoopR's
# FULL_CHEM_SECS exactly (rosters seeded at world creation via team.py's seed_chemistry() start an
# established league at close to full chemistry; new acquisitions start cold and gel with minutes
# played together).
FULL_CHEM_SECS = 40_000.0


def morale_realization(morale: int) -> float:
    """How fully a player realizes his ability given his morale (0..100).

    Neutral (70) and above realize fully (1.0); a slump drags it down toward MORALE_R_MIN.
    Downside-only: high morale never pushes a player past his rating, it just keeps him there.
    """
    return max(MORALE_R_MIN, min(1.0, 1.0 + (morale - 70) * MORALE_R_SLOPE))


def clutch_realization(composure: int) -> float:
    """Realization under pressure, from a player's ``composure`` rating (attributes.py's Mental
    group -- PuckSim's hockey-appropriate rename of HoopR's basketball "clutch" rating).

    Composure is resistance to choking, not a boost: elite composure (~97+) holds peak (1.0), an
    average player dips a touch (CLUTCH_PRESSURE_ANCHOR), and the weak-nerved choke toward
    CLUTCH_R_MIN. Only meaningfully applied in clutch situations (see engine.py's clutch gating).
    """
    return max(CLUTCH_R_MIN, min(1.0, CLUTCH_PRESSURE_ANCHOR + (composure - 70) * 0.0011))


def familiarity_realization(shared_secs: float) -> float:
    """How fully an on-ice group realizes its talent given its average shared ice-time.

    Strangers sit at CHEM_R_MIN (miscommunication, blown coverages, turnovers); a group that has
    logged FULL_CHEM_SECS together plays to its full ability (1.0). Linear ramp between.
    """
    frac = max(0.0, min(1.0, shared_secs / FULL_CHEM_SECS))
    return CHEM_R_MIN + (1.0 - CHEM_R_MIN) * frac


# ---------------------------------------------------------------------------
# Fatigue realization -- hockey-specific addition (not in HoopR's ratings.py, since basketball's
# fatigue model lives inline in engine.py's FATIGUE_MAKE_PENALTY). Small enough, and similar enough
# in shape to the other realization factors (a multiplicative, floor-capped scalar on skill gap),
# that it belongs alongside them rather than as a bespoke inline formula in engine.py.
# ---------------------------------------------------------------------------
FATIGUE_R_MIN = 0.90   # a fully gassed player (fatigue == 100) still contributes at 90% realization


def fatigue_realization(fatigue: float) -> float:
    """Realization penalty from within-game fatigue (0..100, 0 = fresh). Linear, floored at
    FATIGUE_R_MIN. Reset to 0 at the start of every game -- fatigue never persists across games in
    this step (that's Step 2.2 territory)."""
    f = max(0.0, min(100.0, fatigue))
    return max(FATIGUE_R_MIN, 1.0 - f * (1.0 - FATIGUE_R_MIN) / 100.0)


# ---------------------------------------------------------------------------
# LineupCache-equivalent: precomputed aggregates for an on-ice group of skaters.
# ---------------------------------------------------------------------------
# Hockey's per-shift (not per-possession) structure makes this a good fit after all: a shift's
# on-ice five skaters stay constant for the whole shift, so caching their aggregate weights once
# per shift (rather than recomputing per shot attempt within that shift) avoids repeated O(5) scans
# for every event. Rebuilt once per shift in GameSim._start_shift(), not per event.
@dataclass
class OnIceCache:
    """Pre-computed aggregates for one team's 5 on-ice skaters (goalie excluded -- goalie
    resolution reads the opposing team's goalie directly, not this cache)."""

    players: List[Player] = field(default_factory=list)
    shot_weights: List[float] = field(default_factory=list)     # shooter-selection weights
    playmaking_weights: List[float] = field(default_factory=list)  # assist-credit weights
    chem_real: float = 1.0     # this group's familiarity realization (see familiarity_realization)
    avg_morale_real: float = 1.0


def build_on_ice_cache(players: List[Player], chem_real: float = 1.0) -> OnIceCache:
    cache = OnIceCache(players=players, chem_real=chem_real)
    for p in players:
        r = p.ratings
        # Favor higher shot_accuracy/shot_power/offensive_awareness for shot selection (per
        # DEVPLAN.md's "weight by a scoring-relevant composite" instruction).
        scoring = (0.45 * r.get("shot_accuracy", 25) + 0.30 * r.get("shot_power", 25)
                   + 0.25 * r.get("offensive_awareness", 25))
        cache.shot_weights.append(max(1.0, scoring - 40))
        cache.playmaking_weights.append(max(0.5, r.get("playmaking", 25) - 20))
    if players:
        cache.avg_morale_real = sum(morale_realization(p.morale) for p in players) / len(players)
    return cache
