"""Team tactical settings.

Pure data: a later sim step (``sim/ratings.py``/``sim/engine.py``) reads these and maps
them to numeric modifiers. Each setting is a labelled discrete option so a UI can cycle
through choices, mirroring HoopR's ``hoopsim/models/tactics.py`` (84 lines) shape --
``SETTINGS`` dict + ``Tactics`` dataclass with ``cycle()``/``items()``/``to_dict()``/
``from_dict()``.

**MVP scope note** (DEVPLAN.md Step 1.10): this module is deliberately a near-empty stub.
PuckSim's MVP engine (Step 1.12) is 5v5-only -- no penalties, no power play, no penalty
kill -- so full PP/PK tactic dimensions have no consumer yet and are explicitly deferred
to v1 (Step 2.1/2.8). What exists here is the one dimension that *does* apply at 5v5
(forecheck style) plus a stable, minimal shape so ``Team`` (built in parallel, Step 1.7)
has a concrete field type to reference now. Extending ``SETTINGS``/``Tactics`` with
PP/PK dimensions later is additive -- new dict keys and dataclass fields with their own
defaults -- and won't require a schema rewrite of what's here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

# Each setting: ordered discrete options; the first is treated as the "conservative" end,
# not necessarily the default (see Tactics' field defaults below, which pick the middle
# option explicitly).
FORECHECK_STYLE_OPTIONS: Tuple[str, ...] = ("passive", "balanced", "aggressive")

SETTINGS: Dict[str, Tuple[str, ...]] = {
    "forecheck_style": FORECHECK_STYLE_OPTIONS,
}

SETTING_LABELS: Dict[str, str] = {
    "forecheck_style": "Forecheck Style",
}


@dataclass
class Tactics:
    """One field per :data:`SETTINGS` key, defaulting to the middle/balanced option."""

    forecheck_style: str = "balanced"

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
