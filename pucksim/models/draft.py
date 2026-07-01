"""Draft structures.

A :class:`DraftClass` is a pool of generated prospect players plus the pick order for one
draft year. Prospects are ordinary ``Player`` ids (no team) at this stage; once picked they
sign a rookie-scale deal and join the drafting team's roster (later steps' concern, not this
module's).

Mirrors the shape of HoopR's ``hoopsim/models/draft.py`` (94 lines): ``DraftPick`` (a
tradeable future selection identified by ``(year, round, original_tid)``, currently
controlled by ``owner_tid``) and ``DraftClass`` (prospect pool + pick order + recorded
picks), with ``team_on_clock()``/``remaining_prospects()``/``record_pick()``.

Deviations from HoopR, called out explicitly:

- ``DraftClass.current_pick`` is 0-based here (an index into ``order``), not HoopR's
  1-based ``current_pick``/``total_picks`` pair. ``team_on_clock()`` returns ``None`` once
  the draft is complete instead of requiring a separate ``complete`` check before calling it.
- ``picks_made`` is a ``List[Tuple[int, int]]`` of ``(prospect_id, team_id)`` recording
  picks *in the order they happened*, rather than HoopR's ``Dict[pick_number, pid]``. This
  keeps prospect id AND drafting team together per entry without relying on ``order`` being
  replayed alongside it, and is what this step's spec asks for.
- ``record_pick()`` validates ``team_id`` against ``team_on_clock()`` and ``prospect_id``
  against ``remaining_prospects()``, raising ``ValueError`` on a mismatch (HoopR's version
  trusts the caller and only takes a ``pid``). PuckSim's caller set is different enough at
  this stage (no engine driving picks yet) that a stricter guard is worth the extra
  friction.
- No ``origins`` field yet -- HoopR uses it to label a traded pick's original owner for
  display. PuckSim's simplified v1 trade model (Step 2.4) doesn't have pick-trading
  wired up yet; ``DraftPick.original_tid`` vs. ``owner_tid`` already carries that
  information at the individual-pick level for when it's needed, so a parallel
  ``DraftClass.origins`` list would be redundant to add before it has a consumer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class DraftPick:
    """A tradeable future draft selection.

    A pick's *slot* in a given draft is determined by ``original_tid``'s standing that
    year; ``owner_tid`` is whoever currently controls it (changes when the pick is
    traded). At most one pick exists per ``(year, round, original_tid)`` key -- see
    :attr:`key`.
    """

    year: int
    round: int            # 1, 2, ... (round count is league-configurable, not fixed here)
    original_tid: int     # whose draft slot this is (sets the pick position)
    owner_tid: int         # who currently controls it

    @property
    def key(self) -> str:
        """Unique identifier for this specific pick, independent of current ownership.

        Useful for trade tracking -- looking up "the pick that was originally team X's
        Nth-round pick in year Y" regardless of how many times it has changed hands.
        """
        return f"{self.year}-{self.round}-{self.original_tid}"

    def to_dict(self) -> dict:
        return {
            "year": self.year,
            "round": self.round,
            "original_tid": self.original_tid,
            "owner_tid": self.owner_tid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DraftPick":
        return cls(
            year=d["year"],
            round=d["round"],
            original_tid=d["original_tid"],
            owner_tid=d["owner_tid"],
        )


@dataclass
class DraftClass:
    """One draft year's prospect pool plus pick-order state.

    ``order`` is a flat list of team ids, one entry per pick across all rounds (e.g. for a
    2-round, 32-team draft: 32 entries for round 1 in reverse-standings order, then 32 more
    for round 2). Flattening the round structure into a single list keeps
    ``team_on_clock()``/``record_pick()`` simple index operations instead of needing
    separate round/pick-within-round bookkeeping -- mirrors HoopR's own flat-``order``
    approach.
    """

    year: int
    prospect_ids: List[int] = field(default_factory=list)   # generated, undrafted players
    order: List[int] = field(default_factory=list)           # owner team ids, one per pick
    current_pick: int = 0                                     # 0-based index into `order`
    picks_made: List[Tuple[int, int]] = field(default_factory=list)  # (prospect_id, team_id)

    @property
    def total_picks(self) -> int:
        return len(self.order)

    @property
    def complete(self) -> bool:
        return self.current_pick >= self.total_picks

    def team_on_clock(self) -> Optional[int]:
        """The team currently picking, or ``None`` if the draft is complete."""
        if self.complete:
            return None
        return self.order[self.current_pick]

    def remaining_prospects(self) -> List[int]:
        """Prospect ids not yet claimed by a recorded pick, in original pool order."""
        drafted = {pid for pid, _tid in self.picks_made}
        return [pid for pid in self.prospect_ids if pid not in drafted]

    def record_pick(self, prospect_id: int, team_id: int) -> None:
        """Record the next pick, advancing the clock.

        Validates that ``team_id`` matches :meth:`team_on_clock` and that
        ``prospect_id`` is still available, raising ``ValueError`` otherwise (this
        module has no engine/AI driving picks yet, so a strict guard catches
        integration bugs early rather than silently corrupting draft state).
        """
        if self.complete:
            raise ValueError("draft is already complete -- no picks remain")

        on_clock = self.team_on_clock()
        if team_id != on_clock:
            raise ValueError(
                f"team {team_id} is not on the clock (expected {on_clock})"
            )

        if prospect_id not in self.remaining_prospects():
            raise ValueError(f"prospect {prospect_id} is not available to be picked")

        self.picks_made.append((prospect_id, team_id))
        self.current_pick += 1

    def to_dict(self) -> dict:
        return {
            "year": self.year,
            "prospect_ids": list(self.prospect_ids),
            "order": list(self.order),
            "current_pick": self.current_pick,
            "picks_made": [[pid, tid] for pid, tid in self.picks_made],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DraftClass":
        return cls(
            year=d["year"],
            prospect_ids=list(d.get("prospect_ids", [])),
            order=list(d.get("order", [])),
            current_pick=d.get("current_pick", 0),
            picks_made=[(pid, tid) for pid, tid in d.get("picks_made", [])],
        )
