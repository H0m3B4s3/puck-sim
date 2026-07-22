"""Procedural player generation: skaters and goalies.

Structural precedent: HoopR's ``hoopsim/gen/playergen.py`` (139 lines). The
pattern reused here -- described in DEVPLAN.md Step 1.11 as "archetype-driven:
pick a position, pick an archetype for that position (normal pool most of the
time, rare pool occasionally), roll a target overall, then generate a baseline
ratings dict and apply the archetype's skews, then calibrate/adjust so the
resulting overall lands close to the target" -- is, concretely:

    1. Pick a position (if not supplied) and an archetype for that position
       (``ARCHETYPES_BY_POSITION``/``GOALIE_ARCHETYPES_BY_POSITION`` almost
       always, ``RARE_ARCHETYPES_BY_POSITION``/``RARE_GOALIE_ARCHETYPES_BY_POSITION``
       only for an elite-ceiling ``target_overall`` that also wins a
       low-probability roll on top -- see ``_RARE_ARCHETYPE_MIN_OVERALL``/
       ``_RARE_ARCHETYPE_CHANCE`` below for the full gate and its derivation).
    2. Build a *baseline* ratings dict: every rating in the position's
       vocabulary (``ALL_RATINGS`` for skaters, ``ALL_GOALIE_RATINGS`` for
       goalies) drawn independently near ``target_overall`` with Gaussian
       noise, clamped to the legal [25, 99] scale via ``clamp_rating``.
    3. Apply the archetype's ``skews`` additively (clamped) -- this carves the
       player's signature identity (elite strengths, genuine holes) on top of
       the bland baseline.
    4. Calibrate: since skewing perturbs the resulting ``overall()`` away from
       ``target_overall`` (skews are rarely symmetric), do a small 1-2
       iteration uniform nudge of every rating so the final overall lands
       close to the target. This is *not* an exact solver (HoopR's own
       version does a single exact pre-clamp shift and accepts drift after
       skewing) -- a couple of coarse iterations is enough for MVP; the design
       explicitly says not to over-engineer this.

Both ``generate_skater`` and ``generate_goalie`` return a fully-formed
``Player`` with ``team_id=None`` -- the caller (``leaguegen.build_world``)
signs the player onto a team afterward via ``World.sign_player()``, keeping
roster/team_id bookkeeping in one place (Step 1.9's documented invariant).

``generate_goalie`` additionally runs a 5th step after calibration (DEVPLAN.md Step 2.7,
"Generation-time rarity correlation"): a gk_consistency rarity gate that resamples
``gk_consistency`` from a capped low/mid band by default once the goalie's calibrated
overall clears a high-skill threshold, UNLESS a separate low-probability "reliability
roll" succeeds (in which case it's resampled from the elite band instead) -- see the
module-level comment above ``_GK_HIGH_SKILL_THRESHOLD``/``_GK_RELIABILITY_ROLL_CHANCE``
for the full mechanism and derivation. This is a SEPARATE, ADDITIONAL gate from the
rare-archetype gate in step 1 above -- not the same mechanism, see that comment block.
This makes "elite skill AND elite year-to-year consistency" (a true franchise goalie)
a genuinely rare combination rather than something that falls out for free whenever a
high-overall goalie happens to also roll a high gk_consistency independently.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pucksim.gen.namegen import random_name
from pucksim.models.attributes import (
    ALL_GOALIE_RATINGS,
    ALL_RATINGS,
    ARCHETYPES_BY_POSITION,
    GOALIE_ARCHETYPES_BY_POSITION,
    RARE_ARCHETYPES_BY_POSITION,
    RARE_GOALIE_ARCHETYPES_BY_POSITION,
    Archetype,
    SKATER_POSITIONS,
    clamp_rating,
    overall,
)
from pucksim.models.contract import Contract, flat_contract
from pucksim.models.player import Player
from pucksim.rng import Rng

# --- Rare/"unicorn" archetype gate (BUG FIX, 2026-07-02) -------------------
# attributes.py's RARE_ARCHETYPES docstring has always claimed these are
# "generated only on elite-ceiling players... and never in the normal pool"
# (see attributes.py's RARE_ARCHETYPES -- the distinct legend styles like
# "Offensive Juggernaut"/"Two-Way Driver"/"Puck-Moving Norris", each modeled on a
# real McDavid/Crosby/Makar-caliber talent).
# That gate was never actually implemented: _choose_archetype() below used to
# roll the rare chance unconditionally for every generated skater/goalie
# regardless of target_overall, so a replacement-level player had the exact
# same shot at "Generational Forward" as a true superstar target. Root-caused
# and fixed here (not special-cased in gen/prospectgen.py's draft-prospect
# path) since _choose_archetype/generate_skater/generate_goalie are shared by
# both the base leaguegen.py roster-fill pipeline and the draft-prospect
# pipeline -- a fix that only lived in one caller would leave the other
# caller with the exact same bug.
#
# Two-stage gate now required (mirrors DEVPLAN.md Step 2.7's not-yet-built
# gk_consistency rarity design -- "high skill alone isn't enough to be rare;
# it should require winning an independent, low-probability roll ON TOP of
# already being elite-ceiling", same shape applied here for consistency):
#   1. target_overall must clear _RARE_ARCHETYPE_MIN_OVERALL at all -- below
#      that, a rare archetype is categorically unreachable, no roll happens.
#   2. Only among that already-elite-ceiling slice does the (now much lower)
#      _RARE_ARCHETYPE_CHANCE roll apply.
#
# Threshold choice (82): roughly the top ~6% of leaguegen.py's full-roster
# target_overall distribution (_OVERALL_MU=66.0, _OVERALL_SIGMA=10.0) and the
# top ~0.05% of gen/prospectgen.py's draft-prospect target_overall
# distribution (_PROSPECT_OVERALL_MU=52.0 -- prospects target a LOWER current
# overall than veterans by design, since their draft value is about
# potential/ceiling, not polish; only a truly precocious, already-dominant
# prospect clears 82). One shared threshold across both pipelines rather than
# a per-caller value, since both ultimately feed the same target_overall
# parameter into the same shared function.
_RARE_ARCHETYPE_MIN_OVERALL = 82

# Chance derivation, worked explicitly (this codebase's convention for
# probability tunables -- see e.g. Step 2.7's design note in DEVPLAN.md):
#   leaguegen.py generates ~640 skaters ONE TIME at league creation (32 teams
#     * 20 skaters/team); ~6.06% of a Gaussian(66.0, 10.0) sample clears 82
#     => ~38.8 elite-ceiling-eligible skaters, once.
#   gen/prospectgen.py generates ~135 skater prospects PER SEASON (150-player
#     pool * ~90% skaters); ~0.049% of a Gaussian(52.0, 9.0) sample clears 82
#     => ~0.066 elite-ceiling-eligible prospects/season, ~0.66 over a decade.
#   Total elite-ceiling-eligible skaters over a 10-season span:
#     ~38.8 (one-time roster fill) + ~0.66 (draft classes) =~ 39.4.
# Target: "once a decade" for a rare/"unicorn" archetype at all (any of the
# distinct legend styles in RARE_ARCHETYPES -- Crosby/McDavid/Makar-caliber
# talent should be that rare). chance = 1 / eligible_count =~ 1/39.4 =~ 0.0254;
# rounded to a clean 0.025 (2.5%) -- roughly HALF of one expected
# "generational" skater across a decade of both pipelines combined, since a
# rare archetype assignment alone doesn't guarantee the FINAL calibrated
# player actually lands at true generational overall after skew+calibration
# (see _build_calibrated_ratings) -- erring rare rather than exactly-one
# keeps the "once-a-decade" framing as a ceiling, not a guarantee.
_RARE_ARCHETYPE_CHANCE = 0.025

# Noise (std dev, rating points) applied per-rating when building the baseline
# ratings dict before archetype skews are applied. Provisional/tunable -- a
# moderate spread gives generated players some texture without regularly
# blowing a single rating far off the target overall before skewing.
_BASELINE_SPREAD = 6.0

# Calibration pass: how many uniform-nudge iterations to run trying to bring
# the post-skew overall back near the target, and how close is "close enough"
# to stop early. Deliberately coarse -- not an exact solver, per DEVPLAN.md.
_CALIBRATION_ITERATIONS = 2
_CALIBRATION_TOLERANCE = 1

# Handedness split (DEVPLAN.md: "roughly real-NHL-plausible weighting is
# fine"). Provisional/illustrative default, not sourced from real handedness
# statistics: ~60/40 L/R is a commonly cited rough split for NHL forwards and
# wingers; applied uniformly across all skater positions here for simplicity
# (a finer per-position split, e.g. wingers skewing toward their natural
# side, is a reasonable future refinement but not required for MVP).
_SHOOTS_L_WEIGHT = 0.60
_SHOOTS_R_WEIGHT = 0.40


# --- gk_consistency generation-time rarity gate (DEVPLAN.md Step 2.7, "Generation-time
# rarity correlation") ------------------------------------------------------------------
# High skill AND high gk_consistency together must be RARE -- a true "franchise goalie"
# (Vasilevskiy/Shesterkin/Hellebuyck-caliber: reliably good-to-very-good EVERY year, not
# just talented) is the scarce, special case; a bad-or-average goalie who happens to be
# consistently bad/average is common and unremarkable. Left alone, _build_calibrated_ratings
# above would sample gk_consistency exactly like every other rating -- independently, near
# target_overall -- which would make "elite skill + elite consistency" just as common as
# "elite skill + anything else," contradicting the whole point of this gate.
#
# This is a SEPARATE, ADDITIONAL mechanism from the rare-archetype gate above
# (_RARE_ARCHETYPE_MIN_OVERALL/_RARE_ARCHETYPE_CHANCE) -- that gate decides which
# *archetype* (skew template) a player gets; this gate decides which *band* a single
# rating (gk_consistency) gets resampled from, independent of archetype choice. A
# "Battler Goalie" archetype (which already skews gk_consistency +12, see attributes.py)
# and a plain "Reflex Goalie" archetype are both subject to this same post-archetype
# resample -- the two mechanisms compose rather than overlap.
#
# Mechanism (per DEVPLAN.md's concrete spec):
#   1. Only engages when the goalie's calibrated overall clears _GK_HIGH_SKILL_THRESHOLD
#      (a high-skill cutoff). Below it, gk_consistency is left exactly as
#      _build_calibrated_ratings already drew it (normal/independent sampling, no gating --
#      "a bad goalie being consistently bad is unremarkable").
#   2. Above that threshold, gk_consistency is by DEFAULT resampled from a capped low/mid
#      band (_GK_CONSISTENCY_COMMON_MAX) -- representing the much more common "talented but
#      streaky" case -- UNLESS a separate, low-probability "reliability roll"
#      (_GK_RELIABILITY_ROLL_CHANCE) succeeds, in which case gk_consistency is instead
#      resampled from the elite band (_GK_CONSISTENCY_ELITE_MIN and up). Landing in the
#      elite band therefore requires BOTH an independent high-skill roll (governed by
#      target_overall's own distribution) AND this low-probability reliability roll --
#      exactly the "requires winning both rolls" scarcity DEVPLAN.md calls for.
#
# Threshold derivation (_GK_HIGH_SKILL_THRESHOLD = 76, "top ~15-20% of goalie talent" per
# DEVPLAN.md): gen/leaguegen.py generates every goalie (like every skater) from a
# Gaussian(_OVERALL_MU=66.0, _OVERALL_SIGMA=10.0) target_overall (verified directly against
# leaguegen.py -- goalies and skaters share the same target-overall distribution, just a
# separate archetype/rating vocabulary). Under that distribution, P(target_overall >= 76)
# ~= 15.9% (standard normal tail, (76-66)/10 = 1.0 sigma above the mean) -- squarely inside
# DEVPLAN's stated "top 15-20%" band, so 76 is used as-is rather than hand-tuned further.
#
# Reliability-roll-chance derivation (_GK_RELIABILITY_ROLL_CHANCE = 0.08), shown explicitly
# per this codebase's established convention for probability tunables (see playergen.py's
# own _RARE_ARCHETYPE_CHANCE derivation immediately above, and DEVPLAN.md Step 2.7's design
# note pointing back at exactly that convention):
#   leaguegen.py generates GOALIES_PER_TEAM=2 goalies/team * NUM_TEAMS=32 = 64 goalies ONE
#     TIME at league creation; ~15.9% clear the 76 high-skill threshold =>
#     ~10.15 high-skill-eligible goalies, once.
#   gen/prospectgen.py generates ~15 goalie prospects/season (PROSPECT_GOALIE_FRACTION=0.10
#     * PROSPECT_POOL_SIZE=150), drawn from a MUCH lower target_overall distribution
#     (_PROSPECT_OVERALL_MU=52.0, since a prospect's *current* ability is deliberately
#     rawer than an established veteran's -- see prospectgen.py's own docstring); only
#     ~0.38% of THAT distribution clears 76, so high-skill goalie prospects are a rare
#     event on their own (~0.057/season, ~0.57 over a decade) well before this gate even
#     engages.
#   Total high-skill-eligible goalies over a 10-season span: ~10.15 (one-time roster fill,
#     dominates the total) + ~0.57 (draft classes) =~ 10.7.
# Target: DEVPLAN.md frames the elite tier as "top 3-5 in the league" (a 32-team league
# fields 64 starting-caliber goalies at leaguegen) -- i.e. only a handful of truly elite-
# skill-AND-elite-consistency "franchise goalies" should exist at any one time, not dozens.
# chance = 0.08 (near the top of DEVPLAN's explicitly suggested 5-10% band, chosen over a
# lower value in that band because the high-skill-eligible pool itself is already fairly
# small at ~10.7/decade) gives an expected ~10.15 * 0.08 =~ 0.81 franchise-tier goalies per
# one-time league generation -- comfortably inside "only a handful league-wide," and
# consistent with real hockey's Vasilevskiy/Shesterkin/Hellebuyck tier being genuinely
# scarce (often literally zero-to-a-few such goalies existing at once), not a guarantee
# every league gets one.
_GK_HIGH_SKILL_THRESHOLD = 76

# gk_consistency resample bands (25-99 scale, same RATING_MIN/MAX bounds as every other
# rating). PROVISIONAL/TUNABLE magnitudes -- no real save-percentage-variance data is being
# fit here (none exists yet to fit against), just plausible band widths: the "common"
# band's ceiling sits at the scale's rough midpoint (a high-skill-but-streaky goalie is
# capped at "average consistency," never accidentally elite), while the "elite" band's
# floor sits well into the upper quartile (a goalie who wins the reliability roll is
# genuinely, unambiguously more consistent than the pack, not just barely above the cap).
_GK_CONSISTENCY_COMMON_MIN = 25
_GK_CONSISTENCY_COMMON_MAX = 65
_GK_CONSISTENCY_ELITE_MIN = 80
_GK_CONSISTENCY_ELITE_MAX = 99

_GK_RELIABILITY_ROLL_CHANCE = 0.08


# --- Overall-weighted archetype selection (archetype-refresh round, Phase B) -------------
# Fixes grinder over-production. The old selection was a flat, OVERALL-BLIND rng.choice over the
# position's normal pool, so a 90-target winger was exactly as likely to roll Grinder as a
# 60-target one -- and since a majority of forward archetypes are checking/physical, most rosters
# came out grinder-heavy. Real rosters concentrate scorers in the top-6 (which auto_build_lines
# fills by descending overall) and checking/physical depth in the bottom-6.
#
# Each normal archetype gets a (depth_weight, star_weight); its effective selection weight blends
# between them by the player's target overall:
#     t = clamp((target_overall - _ARCHETYPE_WEIGHT_OVR_LO) / (HI - LO), 0, 1)
#     weight = depth_weight * (1 - t) + star_weight * t
# High targets -> star weights dominate (scorers); low targets -> depth weights (grinders). It is a
# LEAN, not a hard rule: a two-way winger or the odd depth scorer still appears off-tier, matching
# real hockey. Breakpoints/weights are provisional and re-tuned against the per-line distribution
# check in Phase D. Archetypes absent from the table (all GOALIE archetypes) fall back to a flat
# (1.0, 1.0), i.e. unchanged uniform behavior -- goalies are intentionally left alone this round.
_ARCHETYPE_WEIGHT_OVR_LO = 56.0
_ARCHETYPE_WEIGHT_OVR_HI = 78.0
_DEFAULT_ARCHETYPE_WEIGHT = (1.0, 1.0)

_ARCHETYPE_SELECTION_WEIGHTS: Dict[str, tuple] = {
    # Scorers / pure skill -- concentrate in the top-6.
    "Sniper": (0.3, 3.0),
    "Playmaking Center": (0.3, 3.0),
    "Pass-First Winger": (0.3, 3.0),
    "Speedster": (0.8, 1.8),
    # Physical-but-skilled -- top-6 capable, lean scoring (Tkachuk / Messier flavor).
    "Power Winger": (0.8, 2.0),
    "Power Center": (0.8, 2.0),
    # Flexible two-way -- appears everywhere, flat.
    "Two-Way Forward": (1.2, 1.2),
    # Checking / physical depth -- concentrate in the bottom-6.
    "Power Forward": (2.0, 0.6),
    "Grinder": (3.0, 0.2),
    "Checking Center": (3.0, 0.2),
    # Pure enforcers are a niche/dying breed in the modern game -- keep the depth weight well below
    # Grinder/Stay-at-Home so they stay uncommon rather than filling every 4th line and 3rd pair.
    "Enforcer-Physical": (1.6, 0.12),
    # Defensemen -- milder tilt than forwards: a shutdown stud is a legit top-pair option, unlike a
    # 4th-line grinder, so the depth/star spread is compressed toward 1.0. The Shutdown *stud* (elite
    # defensive D, defensive_awareness +16) leans slightly top-pair; the *limited* Stay-at-Home D is
    # the depth defensive specialist that concentrates on the 3rd pair.
    "Offensive Defenseman": (0.7, 1.8),
    "Puck-Rushing Defenseman": (2.4, 0.5),
    "Two-Way Defenseman": (1.2, 1.2),
    "Shutdown Defenseman": (1.0, 1.3),
    "Stay-at-Home Defenseman": (2.6, 0.4),
}


def _archetype_weight(name: str, target_overall: int) -> float:
    """Blend an archetype's (depth_weight, star_weight) by target overall -- see the table above."""
    depth, star = _ARCHETYPE_SELECTION_WEIGHTS.get(name, _DEFAULT_ARCHETYPE_WEIGHT)
    span = _ARCHETYPE_WEIGHT_OVR_HI - _ARCHETYPE_WEIGHT_OVR_LO
    t = (target_overall - _ARCHETYPE_WEIGHT_OVR_LO) / span
    t = max(0.0, min(1.0, t))
    return depth * (1.0 - t) + star * t


def _pick_shoots(rng: Rng) -> str:
    return rng.weighted_one(("L", "R"), (_SHOOTS_L_WEIGHT, _SHOOTS_R_WEIGHT))


def _choose_archetype(rng: Rng, position: str, target_overall: int,
                       normal_pool: Dict[str, List[Archetype]],
                       rare_pool: Dict[str, List[Archetype]]) -> Archetype:
    """Pick an archetype for ``position``: normal pool the vast majority of the time,
    rare/"unicorn" pool only for a genuinely elite-ceiling target AND only after also
    winning a low-probability roll on top of that -- see the module-level comment above
    ``_RARE_ARCHETYPE_MIN_OVERALL``/``_RARE_ARCHETYPE_CHANCE`` for the full derivation
    of both numbers. A ``target_overall`` below the threshold makes a rare archetype
    categorically unreachable (no roll even happens) -- this is the gate that was
    missing before this function took ``target_overall`` at all.
    """
    rare_choices = rare_pool.get(position, [])
    # NOTE on RNG-draw ordering: `rng.chance()` is called unconditionally (not
    # short-circuited behind the `target_overall` check) so this function burns the
    # same one random draw per call regardless of whether a given player clears the
    # elite-ceiling threshold. This keeps the RNG call sequence for the (overwhelming
    # majority) below-threshold case identical to this function's pre-fix behavior --
    # purely an RNG-determinism hygiene choice for this already-seeded-everywhere
    # codebase, not something the gate's correctness depends on (the threshold check
    # below still makes a rare archetype categorically unreachable below
    # _RARE_ARCHETYPE_MIN_OVERALL regardless of the roll's outcome).
    rolled_rare = rng.chance(_RARE_ARCHETYPE_CHANCE)
    if rare_choices and target_overall >= _RARE_ARCHETYPE_MIN_OVERALL and rolled_rare:
        return rng.choice(rare_choices)
    # Normal pool: overall-weighted rather than uniform (see _ARCHETYPE_SELECTION_WEIGHTS) so
    # scorers concentrate at high targets (top-6) and checking/physical depth at low ones (bottom-6).
    pool = normal_pool[position]
    weights = [_archetype_weight(a.name, target_overall) for a in pool]
    return rng.weighted_one(pool, weights)


def _build_calibrated_ratings(rng: Rng, position: str, target_overall: int,
                               all_ratings: List[str], archetype: Archetype) -> Dict[str, int]:
    """Generate-baseline -> apply-skew -> calibrate-to-target, per the module docstring."""
    # 1. Baseline: independent Gaussian noise around the target for every rating.
    ratings = {r: clamp_rating(rng.gauss(target_overall, _BASELINE_SPREAD)) for r in all_ratings}

    # 2. Apply archetype skews additively (clamped).
    for key, delta in archetype.skews.items():
        if key in ratings:
            ratings[key] = clamp_rating(ratings[key] + delta)

    # 3. Calibrate: a couple of coarse uniform-nudge passes toward the target
    # overall. Not an exact solver -- just enough that the final overall lands
    # reasonably close, while archetype skews still leave a genuine signature.
    for _ in range(_CALIBRATION_ITERATIONS):
        current = overall(position, ratings)
        gap = target_overall - current
        if abs(gap) <= _CALIBRATION_TOLERANCE:
            break
        for r in all_ratings:
            ratings[r] = clamp_rating(ratings[r] + gap)

    return ratings


def _apply_gk_consistency_rarity_gate(rng: Rng, ratings: Dict[str, int], calibrated_overall: int
                                       ) -> None:
    """Resample ``ratings["gk_consistency"]`` per the rarity-correlation gate above.

    Mutates ``ratings`` in place. Below ``_GK_HIGH_SKILL_THRESHOLD`` this is a no-op --
    gk_consistency stays exactly as ``_build_calibrated_ratings`` already drew it (normal,
    independent sampling). At or above the threshold, gk_consistency is overwritten:
    the elite band only on a successful (and independent-of-the-skill-roll)
    ``_GK_RELIABILITY_ROLL_CHANCE`` roll, the capped common band otherwise.

    Deliberately does NOT re-run the overall-calibration loop afterward: gk_consistency is
    only a GOALIE_WEIGHTS-weighted 0.10 of the goalie overall, so overwriting it can only
    move the final ``overall()`` a small, bounded amount off ``target_overall`` -- the same
    kind of small post-hoc drift archetype skews already introduce and that
    ``_build_calibrated_ratings``'s own 2-iteration calibration is explicitly documented as
    not fully erasing (see that function's docstring: "not an exact solver"). Re-calibrating
    here would fight this gate's own resample right back toward the pre-resample value
    through the *other* ratings, partially undoing the very rarity effect this function
    exists to create.
    """
    if calibrated_overall < _GK_HIGH_SKILL_THRESHOLD:
        return
    if rng.chance(_GK_RELIABILITY_ROLL_CHANCE):
        band = (_GK_CONSISTENCY_ELITE_MIN, _GK_CONSISTENCY_ELITE_MAX)
    else:
        band = (_GK_CONSISTENCY_COMMON_MIN, _GK_CONSISTENCY_COMMON_MAX)
    ratings["gk_consistency"] = clamp_rating(rng.uniform(*band))


def _potential(rng: Rng, ovr: int, age: int) -> int:
    """Potential ceiling: >= overall, with more upside for younger players.

    Provisional/tunable curve, loosely mirroring HoopR's age-based potential
    shaping: veterans (28+) sit at or barely above their current overall,
    younger players carry a growing gaussian-distributed upside blob.
    """
    if age >= 28:
        return clamp_rating(ovr + rng.randint(0, 1))
    mu = max(0.0, (26 - age) * 1.6)
    upside = max(0.0, rng.gauss(mu, mu * 0.6 + 2.0))
    return clamp_rating(ovr + upside)


def _scout_error(rng: Rng, age: int) -> float:
    """Hidden noise driving Player.scouted_potential() fog-of-war.

    Larger for younger/less-established players (real scouting is noisier for
    an 18-year-old prospect than a 30-year-old veteran with a decade of NHL
    data). Provisional/tunable magnitude.
    """
    if age <= 20:
        spread = 8.0
    elif age <= 23:
        spread = 5.0
    elif age <= 27:
        spread = 2.5
    else:
        spread = 1.0
    return rng.gauss(0.0, spread)


def _modest_contract(rng: Rng, target_overall: int, age: int) -> Contract:
    """A modest rookie/vet flat contract -- not economically sophisticated (MVP scope).

    Salary is a coarse function of overall (higher-rated players cost more),
    with a bit of noise; young players (<=21) get a rookie-scale flag. Purely
    illustrative -- real cap/contract fidelity is out of scope until Step 3.1.
    """
    base = 750_000 + max(0, target_overall - 60) * 90_000
    salary = int(max(750_000, base * rng.uniform(0.85, 1.2)))
    years = rng.randint(1, 4)
    is_rookie_scale = age <= 21
    return flat_contract(salary, years, is_rookie_scale=is_rookie_scale)


def generate_skater(pid: int, rng: Rng, age: int, target_overall: int,
                     position: Optional[str] = None) -> Player:
    """Generate one skater (non-goalie) Player at a given age/target overall.

    Picks a position from ``SKATER_POSITIONS`` if not given, an archetype
    (mostly normal, rarely rare), builds+calibrates ratings around the
    target, and constructs a full ``Player`` with ``team_id=None``.
    """
    position = position or rng.choice(SKATER_POSITIONS)
    archetype = _choose_archetype(rng, position, target_overall,
                                   ARCHETYPES_BY_POSITION, RARE_ARCHETYPES_BY_POSITION)
    ratings = _build_calibrated_ratings(rng, position, target_overall, ALL_RATINGS, archetype)
    final_ovr = overall(position, ratings)

    return Player(
        pid=pid,
        name=random_name(rng),
        age=age,
        position=position,
        ratings=ratings,
        potential=_potential(rng, final_ovr, age),
        scout_error=_scout_error(rng, age),
        archetype=archetype.name,   # role auto-derives from this in Player.__post_init__
        shoots=_pick_shoots(rng),
        team_id=None,
        contract=_modest_contract(rng, target_overall, age),
    )


def generate_goalie(pid: int, rng: Rng, age: int, target_overall: int) -> Player:
    """Generate one goalie Player at a given age/target overall.

    Same shape as ``generate_skater`` but over ``ALL_GOALIE_RATINGS`` and the
    goalie-specific archetype pools (both keyed just to "G"). Also applies the
    gk_consistency generation-time rarity gate (DEVPLAN.md Step 2.7, see the
    module-level comment above ``_GK_HIGH_SKILL_THRESHOLD``) AFTER calibration, so
    the gate sees the player's real, final skill level rather than the pre-skew
    target -- a genuinely elite-skill goalie (post-archetype-skew) is what should be
    rare when paired with elite consistency, not merely a high initial target.
    """
    position = "G"
    archetype = _choose_archetype(
        rng, position, target_overall,
        GOALIE_ARCHETYPES_BY_POSITION, RARE_GOALIE_ARCHETYPES_BY_POSITION
    )
    ratings = _build_calibrated_ratings(rng, position, target_overall, ALL_GOALIE_RATINGS, archetype)
    _apply_gk_consistency_rarity_gate(rng, ratings, overall(position, ratings))
    final_ovr = overall(position, ratings)

    return Player(
        pid=pid,
        name=random_name(rng),
        age=age,
        position=position,
        ratings=ratings,
        potential=_potential(rng, final_ovr, age),
        scout_error=_scout_error(rng, age),
        archetype=archetype.name,   # role auto-derives from this in Player.__post_init__
        shoots=_pick_shoots(rng),
        team_id=None,
        contract=_modest_contract(rng, target_overall, age),
    )
