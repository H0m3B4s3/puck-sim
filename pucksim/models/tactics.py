"""Team tactical settings.

Pure data: a later sim step (``sim/ratings.py``/``sim/engine.py``) reads these and maps
them to numeric modifiers. Each setting is a labelled discrete option so a UI can cycle
through choices, mirroring HoopR's ``hoopsim/models/tactics.py`` (84 lines) shape --
``SETTINGS`` dict + ``Tactics`` dataclass with ``cycle()``/``items()``/``to_dict()``/
``from_dict()``.

**MVP scope note** (DEVPLAN.md Step 1.10): this module started as a deliberately
near-empty stub. PuckSim's MVP engine (Step 1.12) was 5v5-only -- no penalties, no power
play, no penalty kill -- so full PP/PK tactic dimensions had no consumer yet and were
explicitly deferred to v1 (Step 2.1/2.8). What existed then was the one dimension that
*does* apply at 5v5 (forecheck style) plus a stable, minimal shape so ``Team`` (built in
parallel, Step 1.7) had a concrete field type to reference.

**PP/PK extension (DEVPLAN.md Step 2.8):** now that Step 2.1 gave the engine real
PP/PK strength states, this module adds the two style axes real hockey tactics boards
actually offer a coach for those situations: ``pp_style`` (power-play zone shape) and
``pk_aggression`` (penalty-kill pressure posture). Both are discrete-labelled-option
fields, same shape as ``forecheck_style`` -- no new mechanism, just two more
``SETTINGS`` entries, exactly as this module's original docstring predicted ("additive
... new dict keys and dataclass fields with their own defaults").

Deliberately NOT wired into any shot-quality/save-probability computation yet: unlike
``CoachProfile.pp_style_aggression``/``pk_style_aggression`` (floats already consumed by
``sim/special_teams.py`` since Step 2.1 -- a coach BEHAVIORAL tendency), these two new
fields are a discrete team-level TACTICS BOARD choice a UI can cycle through, analogous
to ``forecheck_style`` staying pure data through the whole MVP. Step 2.8's actual mandate
is the line-juggling reshuffle trigger (see ``sim/engine.py``) plus giving ``Team.tactics``
a real, round-trippable data shape (see ``models/team.py``) -- mapping these two new style
axes onto real shot-quality/save-probability numbers is additive future work once there's
simulated data to tune reasonable deltas against, same "don't invent tuning numbers before
there's a corpus to check them against" restraint DEVPLAN.md applies to xG weighting
(cross-cutting open item #4) and strength-state probabilities (#2).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

# Each setting: ordered discrete options; the first is treated as the "conservative" end,
# not necessarily the default (see Tactics' field defaults below, which pick the middle
# option explicitly).
FORECHECK_STYLE_OPTIONS: Tuple[str, ...] = ("passive", "balanced", "aggressive")

# Power-play zone shape (DEVPLAN.md Step 2.8). Three real-NHL PP setups, ordered
# conservative -> aggressive by how much they commit to one strong-side zone:
#   "umbrella" -- 1-3-1 shape, puck up top at the point with a triangle below it; the most
#                 puck-possession-oriented/conservative shape, easiest to retreat from if it
#                 breaks down.
#   "overload" -- 4 players stacked on the strong-side half-wall/corner, one weak-side
#                 shooter for a cross-ice one-timer look; real hockey's most common modern
#                 shape, kept as the SETTINGS-middle/default entry.
#   "spread"   -- max ice-surface width, both half-boards manned, point kept high; the most
#                 aggressive/possession-risk shape (thinnest coverage if it turns over) --
#                 mirrors the "high-risk/high-reward" end of ``CoachProfile.pp_style_aggression``
#                 conceptually, but as a discrete tactics-board pick, not that float.
PP_STYLE_OPTIONS: Tuple[str, ...] = ("umbrella", "overload", "spread")

# Penalty-kill pressure posture (DEVPLAN.md Step 2.8). Ordered passive -> aggressive:
#   "passive"    -- collapse to the house, protect the slot/net-front, concede the perimeter.
#   "balanced"   -- the standard "box" shape with occasional puck pressure -- default entry.
#   "aggressive" -- active wedge/pressure PK that gambles for turnovers and shorthanded
#                   chances, at the cost of more east-west scrambling if beaten.
PK_AGGRESSION_OPTIONS: Tuple[str, ...] = ("passive", "balanced", "aggressive")

SETTINGS: Dict[str, Tuple[str, ...]] = {
    "forecheck_style": FORECHECK_STYLE_OPTIONS,
    "pp_style": PP_STYLE_OPTIONS,
    "pk_aggression": PK_AGGRESSION_OPTIONS,
}

SETTING_LABELS: Dict[str, str] = {
    "forecheck_style": "Forecheck Style",
    "pp_style": "Power Play Style",
    "pk_aggression": "Penalty Kill Aggression",
}


@dataclass
class Tactics:
    """One field per :data:`SETTINGS` key, defaulting to the middle/balanced option."""

    forecheck_style: str = "balanced"
    pp_style: str = "overload"
    pk_aggression: str = "balanced"

    def get(self, field_name: str) -> str:
        return getattr(self, field_name)

    def cycle(self, field_name: str) -> None:
        """Advance ``field_name`` to its next allowed option, wrapping around."""
        options = SETTINGS[field_name]
        current = getattr(self, field_name)
        idx = (options.index(current) + 1) % len(options)
        setattr(self, field_name, options[idx])

    def items(self) -> List[Tuple[str, str]]:
        """(field_name, current_value) pairs, in ``SETTINGS`` order."""
        return [(k, getattr(self, k)) for k in SETTINGS]

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in SETTINGS}

    @classmethod
    def from_dict(cls, d: dict) -> "Tactics":
        """Reconstruct from a dict, guarding against unknown/invalid option values.

        Any value not present in that field's allowed ``SETTINGS`` tuple falls back to
        the field's default rather than raising -- protects against corrupted saves or
        stale values left over from a rebalanced/renamed option set.
        """
        defaults = cls()
        valid = {}
        for k, options in SETTINGS.items():
            v = d.get(k)
            valid[k] = v if v in options else getattr(defaults, k)
        return cls(**valid)
