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
# (see attributes.py's "Generational Forward"/"Unicorn Defenseman" -- the
# former is literally commented "McDavid/Crosby-style generational forward").
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
# Target: "once a decade" for Generational Forward/Unicorn Defenseman
# specifically (per direct design input -- Crosby/McDavid-caliber prospects
# should be that rare). chance = 1 / eligible_count =~ 1/39.4 =~ 0.0254;
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
    return rng.choice(normal_pool[position])


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
        shoots=_pick_shoots(rng),
        team_id=None,
        contract=_modest_contract(rng, target_overall, age),
    )


def generate_goalie(pid: int, rng: Rng, age: int, target_overall: int) -> Player:
    """Generate one goalie Player at a given age/target overall.

    Same shape as ``generate_skater`` but over ``ALL_GOALIE_RATINGS`` and the
    goalie-specific archetype pools (both keyed just to "G").
    """
    position = "G"
    archetype = _choose_archetype(
        rng, position, target_overall,
        GOALIE_ARCHETYPES_BY_POSITION, RARE_GOALIE_ARCHETYPES_BY_POSITION
    )
    ratings = _build_calibrated_ratings(rng, position, target_overall, ALL_GOALIE_RATINGS, archetype)
    final_ovr = overall(position, ratings)

    return Player(
        pid=pid,
        name=random_name(rng),
        age=age,
        position=position,
        ratings=ratings,
        potential=_potential(rng, final_ovr, age),
        scout_error=_scout_error(rng, age),
        shoots=_pick_shoots(rng),
        team_id=None,
        contract=_modest_contract(rng, target_overall, age),
    )
