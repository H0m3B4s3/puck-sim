"""Rating definitions, position weights, and player archetypes.

Ratings live on a 25-99 scale (see ``config.RATING_MIN``/``RATING_MAX``). The engine
consumes individual ratings directly; *composites* and *overall* are derived summaries
used for display, AI valuation, and development. Archetypes shape generation so players
have a recognizable identity rather than uniform noise.

Mirrors the shape of HoopR's ``hoopsim/models/attributes.py`` (POSITIONS, RATING_GROUPS,
ALL_RATINGS, COMPOSITES + weighted-blend formula, POSITION_WEIGHTS, clamp_rating(),
composite()/all_composites()/overall(), Archetype + ARCHETYPES/RARE_ARCHETYPES) — the
*shape* is reused, the numbers are hockey's own.

-------------------------------------------------------------------------------
PROVISIONAL, FIRST-PASS RATING LIST — see DESIGN.md "Open items for the next
working session": "Concrete rating list for skaters vs. goalies ... needs its own
pass, not decided here." This module IS that pass. Nothing below is final — these
names/groupings/weights are a reasonable starting point grounded in real hockey
scouting categories, tunable as generation/sim data comes in.

SKATER ratings (grouped, analogous to HoopR's Physical/Offense/Defense/Mental):
  Physical  — skating, agility, strength, stamina
  Offense   — shot_power, shot_accuracy, playmaking, puck_handling, offensive_awareness
  Defense   — checking, defensive_awareness, shot_blocking, discipline
              (deliberately NO fighting/enforcer rating — DESIGN.md puts
              fighting/enforcers out of scope for v1)
  Mental    — faceoffs (meaningfully used by centers only), composure, work_ethic

GOALIE ratings (separate, smaller set per DESIGN.md point 4 — goalies are "a
single-player position with outsized impact... Separate rating category"):
  reflexes, positioning, rebound_control, puck_handling, consistency

Goalie ``puck_handling`` is a distinct rating name from the skater one (see
GOALIE_RATINGS / ALL_GOALIE_RATINGS below) — same concept (control of the puck with
the stick), different scale/context (behind-the-net puck plays vs. stickhandling
through traffic), so it is namespaced separately rather than shared to avoid
collisions in a combined ratings dict on a single Player record.
-------------------------------------------------------------------------------
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from pucksim.config import RATING_MAX, RATING_MIN

# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------
# 5-slot split: three forward slots + one blended defenseman slot + goalie.
# Deliberately NOT split into LD/RD (left/right defenseman) — a finer split would
# require every downstream consumer (archetypes, position weights, Step 1.7's
# line-builder/auto-lineup logic) to track handedness-based slot-fill, which is
# real NHL flavor but not required for MVP. Keeping D as one slot is simpler and
# safer; Step 1.7 (team.py) depends on this tuple being stable, so revisit only
# with a strong reason and a coordinated migration across both files.
POSITIONS: Tuple[str, ...] = ("LW", "C", "RW", "D", "G")

# Skater positions only (everything in POSITIONS except goalie). Convenience
# subset for code that only ever deals with on-ice skaters (line-building,
# skater overall/composite math, skater archetypes).
SKATER_POSITIONS: Tuple[str, ...] = tuple(p for p in POSITIONS if p != "G")

# ---------------------------------------------------------------------------
# Skater ratings
# ---------------------------------------------------------------------------
# Ratings grouped for display. Order within a group is the display order.
RATING_GROUPS: Dict[str, List[str]] = {
    "Physical": ["skating", "agility", "strength", "stamina"],
    "Offense": ["shot_power", "shot_accuracy", "playmaking", "puck_handling",
                "offensive_awareness"],
    # No fighting/enforcer rating by design — DESIGN.md explicitly puts
    # fighting/enforcers out of scope for v1.
    "Defense": ["checking", "defensive_awareness", "shot_blocking", "discipline"],
    # faceoffs is only meaningfully exercised by centers (see POSITION_WEIGHTS
    # below, where non-center positions weight the faceoffs composite near zero).
    "Mental": ["faceoffs", "composure", "work_ethic"],
}

ALL_RATINGS: List[str] = [r for group in RATING_GROUPS.values() for r in group]

# Composites are intermediate skill axes the skater overall is built from.
COMPOSITES: Tuple[str, ...] = (
    "scoring", "playmaking_c", "physicality", "defense", "faceoff_c", "intangibles",
)

# How each composite is assembled from raw ratings (weights need not sum to 1;
# normalized in composite() below).
_COMPOSITE_FORMULA: Dict[str, Dict[str, float]] = {
    "scoring": {"shot_power": 0.35, "shot_accuracy": 0.45, "offensive_awareness": 0.20},
    "playmaking_c": {"playmaking": 0.5, "puck_handling": 0.35, "offensive_awareness": 0.15},
    "physicality": {"strength": 0.35, "checking": 0.35, "skating": 0.15, "agility": 0.15},
    "defense": {"defensive_awareness": 0.40, "shot_blocking": 0.25, "checking": 0.20,
                "discipline": 0.15},
    "faceoff_c": {"faceoffs": 1.0},
    "intangibles": {"composure": 0.40, "work_ethic": 0.30, "discipline": 0.15,
                    "stamina": 0.15},
}

# Per-position weighting of composites into the skater overall rating (each row
# sums to 1.0). Faceoffs matter almost exclusively for centers; wings and
# defensemen get a token weight (occasional emergency-draw duty) rather than zero.
POSITION_WEIGHTS: Dict[str, Dict[str, float]] = {
    "LW": {"scoring": 0.32, "playmaking_c": 0.20, "physicality": 0.18,
           "defense": 0.15, "faceoff_c": 0.02, "intangibles": 0.13},
    "RW": {"scoring": 0.32, "playmaking_c": 0.20, "physicality": 0.18,
           "defense": 0.15, "faceoff_c": 0.02, "intangibles": 0.13},
    "C": {"scoring": 0.24, "playmaking_c": 0.28, "physicality": 0.12,
          "defense": 0.16, "faceoff_c": 0.10, "intangibles": 0.10},
    "D": {"scoring": 0.14, "playmaking_c": 0.16, "physicality": 0.22,
          "defense": 0.35, "faceoff_c": 0.01, "intangibles": 0.12},
}

# ---------------------------------------------------------------------------
# Goalie ratings
# ---------------------------------------------------------------------------
# Separate, smaller rating set per DESIGN.md point 4 ("a single-player position
# with outsized game impact... Separate rating category"). Namespaced distinctly
# from skater ratings (e.g. "gk_puck_handling" not "puck_handling") so a combined
# lookup on a Player record never collides between the two rating vocabularies.
GOALIE_RATING_GROUPS: Dict[str, List[str]] = {
    "Goaltending": ["reflexes", "positioning", "rebound_control", "gk_puck_handling",
                    "gk_consistency"],
}

ALL_GOALIE_RATINGS: List[str] = [r for group in GOALIE_RATING_GROUPS.values() for r in group]

# Goalie overall design decision (see module docstring / DESIGN.md point 4):
#
# A skater's game impact is genuinely a *blend* of several independent skill axes
# (a winger can be a great scorer and a poor defender and still be a good player
# overall) — that's why the skater overall above is built from a multi-composite,
# per-position weighted formula.
#
# A goalie's impact is far more concentrated: reflexes and positioning alone
# account for the large majority of real save-percentage variance, and a goalie
# who is weak in those two categories is simply a bad goalie regardless of how
# good their rebound control or puck-handling is (unlike a skater's compensating
# skill blend). So rather than force goalies through the same multi-composite
# machinery (which would imply an averaging/compensating structure that doesn't
# match how goalies actually earn or lose games), GOALIE_WEIGHTS below is a
# single flat weighted average directly over goalie ratings (no intermediate
# composite layer) with reflexes/positioning dominating the total. This still
# reuses composite()'s weighted-blend mechanics (see composite() below, which is
# generic over any ratings-dict + formula-dict pair) — it's the same formula
# shape, just one flat "goalie_overall" axis instead of several skater axes
# blended per position.
GOALIE_WEIGHTS: Dict[str, float] = {
    "reflexes": 0.35,
    "positioning": 0.30,
    "rebound_control": 0.15,
    "gk_puck_handling": 0.10,
    "gk_consistency": 0.10,
}


def clamp_rating(value: float) -> int:
    """Round and clamp a rating to the legal [RATING_MIN, RATING_MAX] range."""
    return int(max(RATING_MIN, min(RATING_MAX, round(value))))


def composite(ratings: Dict[str, int], name: str) -> float:
    """Compute a single skater composite axis from raw ratings."""
    formula = _COMPOSITE_FORMULA[name]
    total = sum(formula.values())
    return sum(ratings.get(k, RATING_MIN) * w for k, w in formula.items()) / total


def all_composites(ratings: Dict[str, int]) -> Dict[str, float]:
    """Compute every skater composite axis from raw ratings."""
    return {name: composite(ratings, name) for name in COMPOSITES}


def _weighted_average(ratings: Dict[str, int], weights: Dict[str, float]) -> float:
    """Generic weighted-average helper (weights normalized, need not sum to 1)."""
    total = sum(weights.values())
    return sum(ratings.get(k, RATING_MIN) * w for k, w in weights.items()) / total


def overall(position: str, ratings: Dict[str, int]) -> int:
    """Position-weighted overall rating (25-99).

    Dispatches on position: goalies ("G") use the flat GOALIE_WEIGHTS average
    over goalie-specific ratings; every other position uses the skater
    multi-composite POSITION_WEIGHTS blend.
    """
    if position == "G":
        value = _weighted_average(ratings, GOALIE_WEIGHTS)
        return clamp_rating(value)

    weights = POSITION_WEIGHTS[position]
    comps = all_composites(ratings)
    value = sum(comps[name] * w for name, w in weights.items())
    return clamp_rating(value)


# ---------------------------------------------------------------------------
# Archetypes — generation templates. ``skews`` are additive deltas applied to a
# player's base ratings to carve out an identity.
# ---------------------------------------------------------------------------
class Archetype:
    __slots__ = ("name", "positions", "skews", "height_in")

    def __init__(self, name: str, positions: List[str], skews: Dict[str, int],
                 height_in: Tuple[int, int]) -> None:
        self.name = name
        self.positions = positions
        self.skews = skews
        self.height_in = height_in  # (min, max) inches, typical for the archetype


# Skews are applied AFTER the overall is calibrated to a target (see playergen,
# a later step), so they carve a real identity: large positive deltas are
# signature elite skills, large negatives are genuine holes. No fighting/enforcer
# skew exists here by design (DESIGN.md: out of scope for v1) — "Power Forward"
# below is a physical, high-strength/high-checking archetype without any
# fighting-specific rating, since none exists in this rating set.
ARCHETYPES: List[Archetype] = [
    Archetype("Sniper", ["LW", "RW", "C"],
              {"shot_accuracy": 16, "shot_power": 12, "offensive_awareness": 8,
               "playmaking": -6, "checking": -10, "defensive_awareness": -8},
              (70, 74)),
    Archetype("Playmaking Center", ["C"],
              {"playmaking": 16, "puck_handling": 12, "offensive_awareness": 10,
               "faceoffs": 6, "shot_power": -8, "checking": -8},
              (71, 75)),
    Archetype("Power Forward", ["LW", "RW"],
              {"strength": 16, "checking": 14, "shot_power": 8, "skating": -8,
               "agility": -10, "playmaking": -6},
              (74, 78)),
    Archetype("Two-Way Forward", ["LW", "RW", "C"],
              {"defensive_awareness": 8, "checking": 6, "shot_accuracy": 5,
               "work_ethic": 7, "composure": 5},
              (72, 76)),
    Archetype("Speedster", ["LW", "RW"],
              {"skating": 18, "agility": 14, "puck_handling": 6, "strength": -12,
               "checking": -10, "shot_power": -6},
              (69, 73)),
    Archetype("Grinder", ["LW", "RW", "C"],
              {"checking": 12, "work_ethic": 12, "stamina": 10, "defensive_awareness": 8,
               "shot_accuracy": -10, "playmaking": -10, "offensive_awareness": -6},
              (71, 75)),
    Archetype("Shutdown Defenseman", ["D"],
              {"defensive_awareness": 16, "shot_blocking": 14, "checking": 10,
               "strength": 8, "shot_accuracy": -10, "playmaking": -8, "skating": -4},
              (73, 77)),
    Archetype("Offensive Defenseman", ["D"],
              {"playmaking": 14, "shot_power": 10, "puck_handling": 10,
               "offensive_awareness": 8, "checking": -10, "shot_blocking": -8,
               "defensive_awareness": -6},
              (72, 76)),
    Archetype("Two-Way Defenseman", ["D"],
              {"defensive_awareness": 6, "playmaking": 6, "skating": 5,
               "composure": 6, "work_ethic": 5},
              (73, 77)),
    Archetype("Enforcer-Physical", ["LW", "RW", "D"],
              # Physical, high-strength/high-checking identity WITHOUT any
              # fighting-specific rating (none exists in this rating set — see
              # module docstring: fighting/enforcers explicitly out of scope
              # for v1 per DESIGN.md). This archetype represents the "physical
              # depth player" flavor using only in-scope ratings.
              {"strength": 18, "checking": 16, "stamina": 8, "shot_accuracy": -14,
               "playmaking": -14, "puck_handling": -10, "agility": -8},
              (74, 78)),
]

ARCHETYPES_BY_POSITION: Dict[str, List[Archetype]] = {pos: [] for pos in SKATER_POSITIONS}
for _arch in ARCHETYPES:
    for _pos in _arch.positions:
        ARCHETYPES_BY_POSITION[_pos].append(_arch)


# ---------------------------------------------------------------------------
# Rare "unicorn" archetypes — generated only on elite-ceiling players (see a
# later playergen step's _choose_archetype-equivalent) and never in the normal
# pool, so they stay special.
# ---------------------------------------------------------------------------
RARE_ARCHETYPES: List[Archetype] = [
    # Do-everything forward: elite shot AND elite playmaking AND real faceoff
    # ability, minimal holes (McDavid/Crosby-style generational forward).
    Archetype("Generational Forward", ["C", "LW", "RW"],
              {"shot_accuracy": 14, "playmaking": 14, "skating": 12, "puck_handling": 10,
               "offensive_awareness": 10, "faceoffs": 6, "composure": 6},
              (71, 75)),
    # Defenseman who plays 30 minutes a night and quarterbacks the power play
    # while still shutting down top lines (Bobby-Orr-into-modern-Norris flavor).
    Archetype("Unicorn Defenseman", ["D"],
              {"playmaking": 12, "skating": 14, "defensive_awareness": 12,
               "shot_power": 8, "puck_handling": 10, "stamina": 8,
               "shot_blocking": 6},
              (73, 77)),
]

RARE_ARCHETYPES_BY_POSITION: Dict[str, List[Archetype]] = {pos: [] for pos in SKATER_POSITIONS}
for _arch in RARE_ARCHETYPES:
    for _pos in _arch.positions:
        RARE_ARCHETYPES_BY_POSITION[_pos].append(_arch)


# ---------------------------------------------------------------------------
# Goalie archetypes — separate tier since goalies use a wholly separate rating
# vocabulary (ALL_GOALIE_RATINGS, not ALL_RATINGS).
# ---------------------------------------------------------------------------
GOALIE_ARCHETYPES: List[Archetype] = [
    Archetype("Reflex Goalie", ["G"],
              {"reflexes": 16, "positioning": -6, "rebound_control": -6},
              (70, 74)),
    Archetype("Positional Goalie", ["G"],
              {"positioning": 16, "rebound_control": 8, "reflexes": -8},
              (72, 76)),
    Archetype("Puck-Moving Goalie", ["G"],
              {"gk_puck_handling": 20, "positioning": 4, "reflexes": -6,
               "rebound_control": -4},
              (72, 76)),
    Archetype("Battler Goalie", ["G"],
              {"gk_consistency": 12, "rebound_control": 10, "reflexes": 6,
               "positioning": -6},
              (71, 75)),
]

GOALIE_ARCHETYPES_BY_POSITION: Dict[str, List[Archetype]] = {"G": list(GOALIE_ARCHETYPES)}

# Rare "unicorn" goalie tier — a goaltender elite across the board with no real
# hole, the goalie equivalent of a generational skater. Kept rare/extreme per
# the same "unicorn" convention as RARE_ARCHETYPES above.
RARE_GOALIE_ARCHETYPES: List[Archetype] = [
    Archetype("Generational Goalie", ["G"],
              {"reflexes": 12, "positioning": 12, "rebound_control": 10,
               "gk_puck_handling": 8, "gk_consistency": 10},
              (73, 77)),
]

RARE_GOALIE_ARCHETYPES_BY_POSITION: Dict[str, List[Archetype]] = {
    "G": list(RARE_GOALIE_ARCHETYPES)
}
