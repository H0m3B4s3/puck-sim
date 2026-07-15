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

from typing import Dict, List, Optional, Tuple

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
    # Pass-first winger -- the wing-eligible playmaker archetype. Before this, playmaking was a
    # center-only identity (Playmaking Center), so a scoring line's setup man could only sit at
    # C; this lets a distributor play the wing too (real NHL: plenty of pass-first wingers), which
    # the line-synergy system needs so a finisher+playmaker pairing isn't forced onto the same
    # center slot. Distinct from Sniper (shoots to score) by inverting the shot/pass skew.
    Archetype("Pass-First Winger", ["LW", "RW"],
              {"playmaking": 16, "puck_handling": 10, "offensive_awareness": 10,
               "shot_power": -8, "shot_accuracy": -6, "checking": -6},
              (70, 74)),
    Archetype("Power Forward", ["LW", "RW"],
              {"strength": 16, "checking": 14, "shot_power": 8, "skating": -8,
               "agility": -10, "playmaking": -6},
              (74, 78)),
    # Skilled power forward (Tkachuk-style "pest who can actually score") -- physical AND a real
    # finisher, the everyday-tier gap between Power Forward (which guts offense) and Sniper (which
    # has no physical game). Maps to the FINISHER role: he finishes, and still wants a setup man.
    Archetype("Power Winger", ["LW", "RW"],
              {"strength": 12, "checking": 10, "shot_power": 10, "shot_accuracy": 8,
               "offensive_awareness": 6, "agility": -6, "playmaking": -6},
              (73, 77)),
    Archetype("Two-Way Forward", ["LW", "RW", "C"],
              {"defensive_awareness": 8, "checking": 6, "shot_accuracy": 5,
               "work_ethic": 7, "composure": 5},
              (72, 76)),
    Archetype("Speedster", ["LW", "RW"],
              {"skating": 18, "agility": 14, "puck_handling": 6, "strength": -12,
               "checking": -10, "shot_power": -6},
              (69, 73)),
    # Grinder skews tuned (SIM_SYNERGY_PLAN.md Phase 1) so a grinder-heavy line reads as
    # genuinely defensive/low-offense: deeper defensive_awareness/checking, deeper offensive
    # holes. This is what gives a checking line its Phase-3 identity (strong defensive
    # suppression, little finish) instead of merely being a slightly-worse scoring line.
    Archetype("Grinder", ["LW", "RW", "C"],
              {"checking": 14, "work_ethic": 12, "stamina": 10, "defensive_awareness": 12,
               "shot_accuracy": -12, "playmaking": -12, "offensive_awareness": -8},
              (71, 75)),
    # Bottom-six defensive/faceoff center -- the center-position grinder identity (the plain
    # Grinder is wing-or-center but skews toward wing usage; this leans into center duties:
    # faceoffs + defensive-zone coverage). Maps to the grinder role. Fills the "shutdown fourth
    # line needs a real defensive C" gap the line-synergy system exposes.
    Archetype("Checking Center", ["C"],
              {"defensive_awareness": 12, "checking": 10, "faceoffs": 10, "work_ethic": 8,
               "shot_accuracy": -10, "playmaking": -8, "offensive_awareness": -6},
              (72, 76)),
    # Power center (Messier-style physical driving center) -- strength/checking plus real shot and
    # faceoff ability, unlike Checking Center (which guts offense). Maps to the flexible TWO_WAY_F
    # role: a do-a-bit-of-everything pivot rather than a pure finisher or setup man.
    Archetype("Power Center", ["C"],
              {"strength": 10, "checking": 8, "shot_power": 8, "faceoffs": 10,
               "offensive_awareness": 6, "work_ethic": 6, "agility": -6},
              (73, 77)),
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
# Distinct legend styles rather than one blurry "generational forward." Only the true
# do-everything talents (Two-Way Driver / Offensive Juggernaut) carry ROLE_GENERATIONAL (no holes,
# complements any line); the others map to their NATURAL role (an elite sniper is still a
# ROLE_FINISHER who wants a setup man, an elite distributor is still a ROLE_PLAYMAKER), so lineup
# construction stays meaningful even with stars -- see ROLE_FOR_ARCHETYPE and the synergy engine.
RARE_ARCHETYPES: List[Archetype] = [
    # Crosby-style two-way driver: elite create AND finish AND faceoffs, defensively responsible,
    # no real holes. ROLE_GENERATIONAL.
    Archetype("Two-Way Driver", ["C"],
              {"playmaking": 14, "shot_accuracy": 12, "offensive_awareness": 12,
               "puck_handling": 10, "faceoffs": 8, "defensive_awareness": 8, "composure": 8},
              (71, 75)),
    # McDavid-style offensive juggernaut: game-breaking speed + puck skill that generates and
    # finishes. ROLE_GENERATIONAL.
    Archetype("Offensive Juggernaut", ["C", "LW", "RW"],
              {"skating": 16, "agility": 14, "puck_handling": 14, "playmaking": 12,
               "offensive_awareness": 12, "shot_accuracy": 8},
              (71, 75)),
    # Gretzky-style playmaking juggernaut: otherworldly vision/setup, a distributor first rather
    # than a volume shooter. ROLE_PLAYMAKER (elite, but still unlocks finishers around him).
    Archetype("Playmaking Juggernaut", ["C"],
              {"playmaking": 18, "offensive_awareness": 16, "puck_handling": 12,
               "composure": 10, "faceoffs": 6, "shot_power": -4},
              (71, 75)),
    # Ovechkin/Matthews-style franchise sniper: elite shot volume + accuracy, the pure finisher a
    # scoring line is built around. ROLE_FINISHER.
    Archetype("Elite Sniper", ["LW", "RW", "C"],
              {"shot_power": 16, "shot_accuracy": 18, "offensive_awareness": 12,
               "puck_handling": 6, "checking": -6},
              (72, 76)),
    # Jagr/Lindros-style skilled power winger: big, strong, AND an elite finisher -- the pure-offense
    # ceiling above the everyday Power Winger. ROLE_FINISHER.
    Archetype("Elite Power Winger", ["LW", "RW"],
              {"strength": 14, "shot_power": 14, "shot_accuracy": 12, "puck_handling": 12,
               "offensive_awareness": 10, "checking": 6},
              (74, 78)),
    # Bergeron/Datsyuk-style defensive driver: elite defense-first two-way center who still moves
    # the puck and scores. ROLE_TWO_WAY_F (does everything, defensively anchored).
    Archetype("Defensive Driver", ["C"],
              {"defensive_awareness": 16, "faceoffs": 14, "playmaking": 10, "puck_handling": 10,
               "offensive_awareness": 8, "checking": 8, "composure": 8},
              (72, 76)),
    # Defenseman who plays 30 minutes a night and quarterbacks the power play
    # while still shutting down top lines (Bobby-Orr-into-modern-Norris flavor). ROLE_GENERATIONAL.
    Archetype("Unicorn Defenseman", ["D"],
              {"playmaking": 12, "skating": 14, "defensive_awareness": 12,
               "shot_power": 8, "puck_handling": 10, "stamina": 8,
               "shot_blocking": 6},
              (73, 77)),
    # Makar-style puck-moving Norris: his DEFENSE is possession -- elite skating/handling/vision,
    # so defensive_awareness stays neutral/slightly-positive rather than a hole. ROLE_OFFENSIVE_D.
    Archetype("Puck-Moving Norris", ["D"],
              {"skating": 16, "puck_handling": 14, "playmaking": 14, "offensive_awareness": 12,
               "agility": 10, "shot_power": 8, "defensive_awareness": 4},
              (72, 76)),
    # Leetch/Fox-style smooth two-way defenseman: elite mobility and puck-moving with genuine
    # defensive chops -- balanced rather than tilted either way. ROLE_TWO_WAY_D.
    Archetype("Smooth Two-Way D", ["D"],
              {"playmaking": 12, "skating": 12, "puck_handling": 10, "offensive_awareness": 8,
               "defensive_awareness": 8, "composure": 8},
              (73, 77)),
    # Lidstrom/Chara-style shutdown colossus: minutes-eating defensive anchor, elite defensive
    # awareness + shot-blocking + reach/strength. ROLE_SHUTDOWN_D.
    Archetype("Shutdown Colossus", ["D"],
              {"defensive_awareness": 16, "shot_blocking": 12, "strength": 12, "checking": 10,
               "composure": 8, "playmaking": 4},
              (75, 80)),
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


# ---------------------------------------------------------------------------
# Player roles (SIM_SYNERGY_PLAN.md Phase 0) -- a coarse identity tag the sim's
# line-synergy system keys on, persisted on Player. Distinct from the specific
# archetype NAME (kept for UI/flavor): many archetypes collapse to one role, and
# roles are the vocabulary the synergy math is written against so the archetype
# roster can be refined (Phase 1) without rewriting the engine.
# ---------------------------------------------------------------------------
ROLE_FINISHER = "finisher"          # shoots to score; realizes his scoring only when set up
ROLE_PLAYMAKER = "playmaker"        # sets up finishers; a playmaker on the ice unlocks one-timers
ROLE_TWO_WAY_F = "two_way_f"        # flexible forward; mild positive fit with anything
ROLE_GRINDER = "grinder"            # low offense, strong defensive suppression (energy/checking)
ROLE_PHYSICAL = "physical"          # heavy forechecker; physical/defensive lean
ROLE_OFFENSIVE_D = "offensive_d"    # PP/transition offense from the back end
ROLE_SHUTDOWN_D = "shutdown_d"      # max defensive suppression from the pair
ROLE_TWO_WAY_D = "two_way_d"        # balanced defenseman
ROLE_GENERATIONAL = "generational"  # no holes; complements every composition
ROLE_GOALIE = "goalie"              # sentinel -- goalies are not part of line synergy

SKATER_ROLES: Tuple[str, ...] = (
    ROLE_FINISHER, ROLE_PLAYMAKER, ROLE_TWO_WAY_F, ROLE_GRINDER, ROLE_PHYSICAL,
    ROLE_OFFENSIVE_D, ROLE_SHUTDOWN_D, ROLE_TWO_WAY_D, ROLE_GENERATIONAL,
)
ALL_ROLES: Tuple[str, ...] = SKATER_ROLES + (ROLE_GOALIE,)

DEFAULT_SKATER_ROLE = ROLE_TWO_WAY_F   # fallback for an unknown/missing skater archetype

# Archetype NAME -> role. Every archetype defined above (normal, rare, and goalie) has an
# entry so ``role_for_archetype`` never has to guess for a generated player.
ROLE_FOR_ARCHETYPE: Dict[str, str] = {
    "Sniper": ROLE_FINISHER,
    "Playmaking Center": ROLE_PLAYMAKER,
    "Pass-First Winger": ROLE_PLAYMAKER,
    "Checking Center": ROLE_GRINDER,
    "Power Forward": ROLE_PHYSICAL,
    "Power Winger": ROLE_FINISHER,
    "Power Center": ROLE_TWO_WAY_F,
    "Two-Way Forward": ROLE_TWO_WAY_F,
    "Speedster": ROLE_TWO_WAY_F,
    "Grinder": ROLE_GRINDER,
    "Shutdown Defenseman": ROLE_SHUTDOWN_D,
    "Offensive Defenseman": ROLE_OFFENSIVE_D,
    "Two-Way Defenseman": ROLE_TWO_WAY_D,
    "Enforcer-Physical": ROLE_PHYSICAL,
    # Elite/rare skaters map to their NATURAL role, not all to generational (see RARE_ARCHETYPES).
    "Two-Way Driver": ROLE_GENERATIONAL,
    "Offensive Juggernaut": ROLE_GENERATIONAL,
    "Playmaking Juggernaut": ROLE_PLAYMAKER,
    "Elite Sniper": ROLE_FINISHER,
    "Elite Power Winger": ROLE_FINISHER,
    "Defensive Driver": ROLE_TWO_WAY_F,
    "Unicorn Defenseman": ROLE_GENERATIONAL,
    "Puck-Moving Norris": ROLE_OFFENSIVE_D,
    "Smooth Two-Way D": ROLE_TWO_WAY_D,
    "Shutdown Colossus": ROLE_SHUTDOWN_D,
    "Reflex Goalie": ROLE_GOALIE,
    "Positional Goalie": ROLE_GOALIE,
    "Puck-Moving Goalie": ROLE_GOALIE,
    "Battler Goalie": ROLE_GOALIE,
    "Generational Goalie": ROLE_GOALIE,
}

# Margins (composite-rating points) for the rating-only fallback classifier below. Provisional/
# tunable, and low-stakes: this path only runs for players with no stored archetype (pre-role
# saves, hand-built test players), never for freshly-generated players (those map by name).
_ROLE_D_OFFENSE_MARGIN = 4.0
_ROLE_D_DEFENSE_MARGIN = 4.0
_ROLE_F_GRINDER_MARGIN = 3.0
_ROLE_F_PHYSICAL_MARGIN = 5.0
_ROLE_F_FINISHER_MARGIN = 4.0
_ROLE_F_PLAYMAKER_MARGIN = 4.0


def role_for_archetype(archetype_name: Optional[str], position: str) -> str:
    """Map an archetype NAME to its coarse role. Goalies always map to ``ROLE_GOALIE``
    regardless of the (goalie) archetype. An unknown/missing skater name falls back to
    ``DEFAULT_SKATER_ROLE`` rather than raising -- same never-crash-on-stale-data philosophy
    as ``coach.profile_for``."""
    if position == "G":
        return ROLE_GOALIE
    if archetype_name and archetype_name in ROLE_FOR_ARCHETYPE:
        return ROLE_FOR_ARCHETYPE[archetype_name]
    return DEFAULT_SKATER_ROLE


def role_for_ratings(ratings: Dict[str, int], position: str) -> str:
    """Best-effort role classification from a rating profile alone -- the fallback used ONLY to
    backfill a role for a player with no stored archetype (a save from before roles existed, or a
    hand-built test player). Deterministic (no RNG) and compares the same composites ``overall()``
    is built from, so it never disagrees with how a player is otherwise valued."""
    if position == "G":
        return ROLE_GOALIE
    comps = all_composites(ratings)
    scoring, playmaking = comps["scoring"], comps["playmaking_c"]
    defense, physicality = comps["defense"], comps["physicality"]
    if position == "D":
        off = 0.5 * scoring + 0.5 * playmaking
        if off - defense >= _ROLE_D_OFFENSE_MARGIN:
            return ROLE_OFFENSIVE_D
        if defense - off >= _ROLE_D_DEFENSE_MARGIN:
            return ROLE_SHUTDOWN_D
        return ROLE_TWO_WAY_D
    # Forwards.
    offense = max(scoring, playmaking)
    if defense - offense >= _ROLE_F_GRINDER_MARGIN and physicality >= scoring:
        return ROLE_GRINDER
    if physicality - offense >= _ROLE_F_PHYSICAL_MARGIN:
        return ROLE_PHYSICAL
    if scoring - playmaking >= _ROLE_F_FINISHER_MARGIN:
        return ROLE_FINISHER
    if playmaking - scoring >= _ROLE_F_PLAYMAKER_MARGIN:
        return ROLE_PLAYMAKER
    return ROLE_TWO_WAY_F
