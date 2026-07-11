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

import math
from dataclasses import dataclass, field
from typing import List

from pucksim import config
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
# Strength-state -> shot-probability modifiers (DEVPLAN.md Step 2.1)
# ---------------------------------------------------------------------------
# Mirrors the shot_volume_multiplier / shot_quality_bias_delta pattern shape directly above:
# a strength state maps to a volume multiplier (how many shot attempts get generated) and a
# quality delta (how much the "quality roll" is skewed), consumed by engine.py's shift/shot
# loop exactly like the coach tactic modifiers are. PROVISIONAL/TUNABLE constants -- same
# framing as every other first-pass constant in this codebase (DEVPLAN.md Step 2.1's own
# "exact strength-state probability tuning is unresolved" note covers these too).
#
# Real hockey intuition these are modeling: a power play creates far more zone time and
# better looks (a extra body creates space/passing lanes) -- both more volume AND higher
# quality. A penalty kill is the mirror image for the shorthanded team's own offense: fewer
# looks, and the ones it gets are lower quality (desperate clears, no set breakout). PP/PK
# also change the QUALITY OF DEFENSE faced (the shorthanded defense should suppress the
# power play's shot quality somewhat even as the PP still nets a net positive edge) --
# handled in engine.py by applying the offense's own strength-state modifier only; the
# defense's suppression is implicit in the offense being at a numbers disadvantage on the PK
# (fewer skaters to generate their own offense, not a separate defensive-quality knob here).
STRENGTH_SHOT_VOLUME_MULT = {
    config.STRENGTH_5V5: 1.0,
    config.STRENGTH_PP: 1.6,     # man advantage -- meaningfully more attempts
    config.STRENGTH_PK: 0.55,    # shorthanded -- suppressed offense while defending
    config.STRENGTH_4V4: 1.05,   # slightly more open ice than 5v5
    config.STRENGTH_3V3: 1.35,   # OT 3-on-3 -- very open ice, high event rate
    config.STRENGTH_5V3: 2.1,    # two-man advantage -- a near-guaranteed extended zone time
}

STRENGTH_SHOT_QUALITY_DELTA = {
    config.STRENGTH_5V5: 0.0,
    config.STRENGTH_PP: 0.22,    # man advantage creates meaningfully better looks -- real NHL PP
                                  # shooting% runs well above 5v5 (roughly 40-70% higher in most
                                  # seasons), so this needs to be a real, reliably-measurable
                                  # effect on scoring rate, not just a subtle nudge.
    config.STRENGTH_PK: -0.18,   # desperation clears / low-quality looks while shorthanded
    config.STRENGTH_4V4: 0.03,
    config.STRENGTH_3V3: 0.08,
    config.STRENGTH_5V3: 0.32,
}


def strength_state_shot_volume_multiplier(strength_state: str) -> float:
    """Scales expected shot-attempts-per-shift for the offense's current strength state.
    Unknown/legacy strength-state strings default to a neutral 1.0x rather than raising."""
    return STRENGTH_SHOT_VOLUME_MULT.get(strength_state, 1.0)


def strength_state_shot_quality_delta(strength_state: str) -> float:
    """Delta added to a shot attempt's "quality roll" for the offense's current strength
    state (see engine._pick_zone_and_shot_type). Unknown/legacy strength states default to a
    neutral 0.0 delta rather than raising."""
    return STRENGTH_SHOT_QUALITY_DELTA.get(strength_state, 0.0)


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
# Goalie hot hand -- a gap-closing realization factor (DEVPLAN.md Step 2.2).
# ---------------------------------------------------------------------------
# THE "NO UPWEIGHTING" PRINCIPLE (reaffirmed in the session that authored this function --
# read this before touching the shape below):
#
#   Players never perform better than their rating implies. No mechanic in this codebase may
#   push effective performance above a player's rating-implied ceiling ("nobody can give
#   110%"). Every realization factor above (morale/clutch/familiarity/fatigue) is a
#   multiplicative scalar bounded in [floor, 1.0] -- capped at exactly 1.0, NEVER higher. The
#   asymmetry is deliberate: a player doesn't get BETTER under good conditions, he simply keeps
#   performing at his own ceiling instead of dipping below it ("the good/greats merely continue
#   to perform at their level in important situations... some players absolutely do choke
#   though" -- i.e. only decline is modeled as a distinct mechanic; "playing well" is just "not
#   declining").
#
#   A goalie hot-hand mechanic is real (real goaltenders do ride streaks), but it MUST be
#   implemented as a one-directional pull of ``def_real`` back toward 1.0 -- narrowing the gap
#   between wherever OTHER realization factors (morale, fatigue, chemistry) have already dragged
#   a goalie's realized performance and his true rating ceiling -- never as an additive bonus
#   layered directly onto a raw save probability. An earlier version of this engine DID add a
#   flat nudge (``goalie_hot_hand``, up to +0.06) straight onto ``save_p`` BEFORE the def_real
#   rescale -- that let a neutral shot (skill gap == 0, def_real would be exactly 1.0) resolve
#   above the 0.90 baseline purely from a hot streak, which is a real, measurable violation of
#   "never above your rating ceiling." This function/its caller in engine.py fix that.
#
# The fix -- gap-closing, not additive:
#
#     effective_def_real = def_real + (1.0 - def_real) * hot_hand_fraction
#
#   ``hot_hand_fraction`` (this function's return value) is bounded to [0, HOT_HAND_MAX_FRACTION]
#   -- at most, being fully "hot" closes HOT_HAND_MAX_FRACTION of the remaining gap between
#   wherever def_real currently sits and the 1.0 ceiling. This is mathematically guaranteed to
#   satisfy the invariant for any def_real in [0, 1] and any fraction in [0, 1]:
#
#     def_real <= effective_def_real <= 1.0
#
#   -- proof: (1.0 - def_real) >= 0 and hot_hand_fraction in [0, 1], so the added term is always
#   >= 0 (never pulls DOWN, that's morale/fatigue/chemistry's job, not hot hand's) and always
#   <= (1.0 - def_real) (so the sum never exceeds 1.0). A neutral shot where def_real is ALREADY
#   1.0 (no other realization factor is dragging it down) gets effective_def_real == 1.0
#   regardless of how hot the streak is -- hot hand has *nothing left to close*, which is exactly
#   the desired "cannot exceed your ceiling" behavior. Do NOT reintroduce an additive nudge here
#   or in engine.py; if you're tempted to make a goalie "even better than fully realized," that's
#   the upweighting bug this function exists to prevent.
# ---------------------------------------------------------------------------
HOT_HAND_MAX_FRACTION = 0.5     # a maximally "hot" goalie closes at most half the remaining gap
                                 # to his own ceiling -- provisional/tunable magnitude, same
                                 # framing as every other first-pass constant in this codebase.
HOT_HAND_STREAK_SATURATION = 6.0  # streak value (see engine.py's per-save increment cadence) at
                                   # which hot_hand_fraction reaches its max; a smooth, saturating
                                   # ramp rather than a hard step so the effect builds gradually
                                   # over a run of consecutive saves rather than snapping on.


def hot_hand_boost(streak_value: float) -> float:
    """Fraction (0..HOT_HAND_MAX_FRACTION) of the gap between a goalie's currently-realized
    ``def_real`` and his rating ceiling (1.0) that a save streak closes.

    ``streak_value`` is a small non-negative rolling counter the engine maintains per goalie
    (incremented a bit per consecutive save, reset/decayed on a goal against -- same
    streak-tracking cadence the old additive ``goalie_hot_hand`` nudge used, just reinterpreted:
    see engine.py's ``_TeamState.goalie_hot_hand`` field and ``_score_goal``/
    ``_resolve_shot_attempt``). Zero streak -> zero fraction (a cold/neutral goalie gets no
    boost, full stop). The ramp saturates smoothly at HOT_HAND_STREAK_SATURATION consecutive-save
    "credits" via ``1 - exp(-streak/saturation)``, so the marginal boost from one more save
    shrinks the hotter the goalie already is (diminishing returns), never overshoots the max
    fraction, and never goes negative for a non-negative streak value.

    This is consumed EXCLUSIVELY via the gap-closing formula documented above
    (``effective_def_real = def_real + (1.0 - def_real) * hot_hand_boost(streak)``) -- never
    added directly to a raw probability. See this module's "no upweighting" note just above.
    """
    s = max(0.0, streak_value)
    ramp = 1.0 - math.exp(-s / HOT_HAND_STREAK_SATURATION)
    return max(0.0, min(HOT_HAND_MAX_FRACTION, HOT_HAND_MAX_FRACTION * ramp))


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
    # This group's average defensive value (SIM_SYNERGY_PLAN.md Phase 2). When this group is the
    # DEFENDING on-ice unit, the engine suppresses the opponent's shot quality by how far this
    # sits above config.DEF_SUPPRESSION_PIVOT. Defaults to the pivot so an empty/degenerate cache
    # is neutral (no suppression) rather than accidentally strong or weak.
    def_value: float = config.DEF_SUPPRESSION_PIVOT
    # This group's offensive line-role synergy (SIM_SYNERGY_PLAN.md Phase 3). When this group is
    # the ATTACKING on-ice unit, the engine raises/lowers the attempt's shot quality by how far
    # this sits from config.SYNERGY_PIVOT_SCORE. Defaults to the pivot so an empty cache is neutral.
    synergy_score: float = config.SYNERGY_PIVOT_SCORE


def defensive_value(player: Player) -> float:
    """A skater's on-ice defensive value: mostly positional/gap defense (defensive_awareness)
    plus some physical engagement (checking). Deliberately does NOT include shot_blocking -- that
    rating already drives its own separate mechanic (the blocker pick / block-vs-miss split in
    engine.py), so folding it in here too would double-count it."""
    r = player.ratings
    return 0.7 * r.get("defensive_awareness", 25) + 0.3 * r.get("checking", 25)


# ---------------------------------------------------------------------------
# Line-role synergy (SIM_SYNERGY_PLAN.md Phase 3) -- a well-composed offensive group manufactures
# better looks (a playmaker setting up a finisher's one-timer); a lopsided one settles for worse
# ones. Implemented as a shot-QUALITY effect (the same mechanical class as the PP/rush/rebound/
# defender quality deltas the engine already applies), NOT a rating-realization multiplier: no
# player's finishing rating is ever exceeded -- the CHANCE quality changes, exactly as a power play
# already changes it. Centered on the league-mean composition (see engine's SYNERGY_PIVOT_SCORE)
# so an average line is a no-op and league goals/game is conserved.
# ---------------------------------------------------------------------------
# Per-role (creation, finishing) offensive tendencies in 0..1. Creation = sets up chances
# (distributes, quarterbacks); finishing = buries them. A line needs BOTH to click.
_ROLE_CREATE_FINISH = {
    "finisher": (0.15, 1.00),      # elite trigger, needs feeding
    "playmaker": (1.00, 0.35),     # elite distributor, modest shot
    "two_way_f": (0.55, 0.60),     # balanced glue -- complements either half
    "grinder": (0.25, 0.30),       # neither; offense is not their game
    "physical": (0.35, 0.55),      # net-front / tips, some finish
    "offensive_d": (0.85, 0.45),   # creates/quarterbacks from the back end
    "shutdown_d": (0.20, 0.20),    # defensive specialist
    "two_way_d": (0.45, 0.40),     # balanced defenseman
    "generational": (0.95, 0.95),  # does everything -- carries a line on its own
    "goalie": (0.0, 0.0),          # never in an offensive on-ice group
}
_DEFAULT_CREATE_FINISH = (0.40, 0.40)   # unknown/missing role -> neutral-ish


def line_synergy_score(roles: List[str]) -> float:
    """0..1 offensive complementarity of an on-ice group: high only when the group has BOTH a real
    creator (a playmaker / offensive-D / generational to set up the look) AND a real finisher
    (someone to bury it). ``sqrt(best_create * best_finish)`` -- one great distributor is enough to
    feed and one great finisher enough to bury (so we take the best of each, not a sum), but a
    group missing either half scores low: three finishers with nobody to set them up, or three
    passers with nobody to shoot. A group with neither (a checking line) scores low too, which is
    correct -- their low offense is their ratings, not a composition the engine should rescue."""
    if not roles:
        return 0.0
    best_create = max(_ROLE_CREATE_FINISH.get(r, _DEFAULT_CREATE_FINISH)[0] for r in roles)
    best_finish = max(_ROLE_CREATE_FINISH.get(r, _DEFAULT_CREATE_FINISH)[1] for r in roles)
    return math.sqrt(best_create * best_finish)


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
        cache.def_value = sum(defensive_value(p) for p in players) / len(players)
        # Line synergy is a FORWARD-line concept -- the creator/finisher chemistry among the three
        # forwards. Scoping it to forwards (not the two D) keeps the signal sharp: otherwise an
        # offensive defenseman on the ice every shift would backstop ``best_create`` and quietly
        # make the forward playmaker redundant, washing the effect out. A group with no forwards
        # (edge cases only -- never a 5v5 line) keeps the neutral default. Whether the D pair gets
        # its own synergy term is a flagged Phase-5 open item, not folded in here.
        fwd_roles = [p.role for p in players if p.position in ("LW", "C", "RW")]
        if fwd_roles:
            cache.synergy_score = line_synergy_score(fwd_roles)
    return cache
