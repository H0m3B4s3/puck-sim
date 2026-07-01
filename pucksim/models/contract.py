"""Player contracts — simplified v1 cap/contract model.

Per DESIGN.md's v1 cap/contract fidelity decision, this is a HoopR-style
simplified model: a single cap number, basic contract terms, and nothing
more. Real NHL CBA detail (arbitration, offer sheets, LTIR cap relief,
waivers, one-way/two-way entry-level contracts) is explicitly deferred to
a later pass (DEVPLAN.md Step 3.1) once the core loop works.

This is a near-verbatim structural port of HoopR's ``hoopsim/models/contract.py``:
a contract is a list of annual salaries (index 0 == the current season).
Options and guarantees are tracked per year. When a season ends the current
year is dropped; an empty contract means the player reaches free agency.

Deviation from HoopR: NBA's Bird-rights concept (a soft-cap re-signing
exception unlocked by years with the team) is dropped entirely. Hockey's
simplified v1 cap model has no soft-cap re-signing exception, so
``years_with_team`` is kept (it's a generically useful tenure counter that
may drive other things later, e.g. simplified loyalty/no-trade eligibility)
but no ``has_bird_rights``/``has_early_bird_rights``-style properties exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Contract:
    salaries: List[int] = field(default_factory=list)          # dollars per remaining year
    guaranteed: List[bool] = field(default_factory=list)       # parallel to salaries
    # year_index -> "player" | "team"; that year is an option to be decided in the offseason.
    options: Dict[int, str] = field(default_factory=dict)
    no_trade: bool = False
    signed_year: int = 0            # season year the deal was signed
    years_with_team: int = 0        # tenure counter (no Bird-rights-style cap exception in v1)
    is_rookie_scale: bool = False

    # -- queries ------------------------------------------------------------
    @property
    def years_remaining(self) -> int:
        return len(self.salaries)

    @property
    def is_expiring(self) -> bool:
        return self.years_remaining <= 1

    @property
    def current_salary(self) -> int:
        return self.salaries[0] if self.salaries else 0

    @property
    def total_remaining(self) -> int:
        return sum(self.salaries)

    def option_for_year(self, year_index: int) -> Optional[str]:
        return self.options.get(year_index)

    # -- mutation -----------------------------------------------------------
    def advance_year(self) -> None:
        """Drop the just-completed season; shift option indices down by one."""
        if self.salaries:
            self.salaries.pop(0)
            if self.guaranteed:
                self.guaranteed.pop(0)
        self.years_with_team += 1
        self.options = {idx - 1: kind for idx, kind in self.options.items() if idx - 1 >= 0}

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "salaries": list(self.salaries),
            "guaranteed": list(self.guaranteed),
            "options": {str(k): v for k, v in self.options.items()},
            "no_trade": self.no_trade,
            "signed_year": self.signed_year,
            "years_with_team": self.years_with_team,
            "is_rookie_scale": self.is_rookie_scale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Contract":
        return cls(
            salaries=list(d.get("salaries", [])),
            guaranteed=list(d.get("guaranteed", [])),
            options={int(k): v for k, v in d.get("options", {}).items()},
            no_trade=d.get("no_trade", False),
            signed_year=d.get("signed_year", 0),
            years_with_team=d.get("years_with_team", 0),
            is_rookie_scale=d.get("is_rookie_scale", False),
        )

    @classmethod
    def free_agent(cls) -> "Contract":
        return cls()


def flat_contract(salary: int, years: int, guaranteed: bool = True, *,
                   is_rookie_scale: bool = False, signed_year: int = 0,
                   years_with_team: int = 0) -> Contract:
    """Build a simple, fully-guaranteed-by-default flat-salary contract.

    Used for quick test fixtures and simple draftee/UFA signings. ``is_rookie_scale``
    is a generic flag (not full NHL ELC rules) that can later drive simplified
    entry-level pay for draftees.
    """
    return Contract(
        salaries=[salary] * years,
        guaranteed=[guaranteed] * years,
        signed_year=signed_year,
        is_rookie_scale=is_rookie_scale,
        years_with_team=years_with_team,
    )
