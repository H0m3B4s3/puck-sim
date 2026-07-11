"""Counting-stat containers for hockey box scores.

Unlike basketball's single ``StatLine`` shape (every player, regardless of
position, fills the same fields), hockey box scores are structurally two
different shapes: skaters (G/A/P/+-/PIM/SOG/hits/blocks/FO%) and goalies
(GAA/SV%/shutouts/W-L-OTL). See DESIGN.md point 9. This module therefore
defines two dataclasses, :class:`SkaterStatLine` and :class:`GoalieStatLine`,
each following HoopR's counters-tuple + derived-properties + add/reset/
to_dict/from_dict pattern (`hoopsim/models/stats.py`).

Both classes accumulate raw counters; derived rates (points, percentages,
GAA) are computed on demand from those counters, and are never themselves
serialized or accumulated directly.

Corsi/Fenwick/xG placement (DESIGN.md point 10): the authoritative source
for these advanced/analytics stats is the shot-attempt event stream that
will be built in the sim engine (``pucksim/sim/engine.py``, Step 1.12),
which carries full per-shot context (type, zone, strength state, rebound
flag) needed to score xG and to filter Corsi/Fenwick correctly (e.g. by
strength state). ``SkaterStatLine`` only carries simple ``corsi_for`` /
``corsi_against`` / ``fenwick_for`` / ``fenwick_against`` counters as a
convenience aggregate (a running tally the engine can increment as it
generates events), not as the source of truth. xG/xA are intentionally
*not* included as StatLine fields yet -- they require the event-log
machinery to compute at all, and that machinery doesn't exist until the
sim engine is built. They can be added as counters (e.g. ``xg_for``) once
that machinery lands, following the same field-iteration serialization
approach so no hand-written serialization code needs to change.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Dict

_SKATER_COUNTERS = (
    "gp", "gs", "secs",
    "g", "a", "sog", "pim",
    "hits", "blocks", "giveaways", "takeaways",
    "fo_won", "fo_lost",
    "plus_minus",
    "corsi_for", "corsi_against",
    "fenwick_for", "fenwick_against",
    "xg", "xa",
)

_GOALIE_COUNTERS = (
    "gp", "gs", "secs",
    "shots_faced", "saves", "goals_against",
    "wins", "losses", "otl",
    "shutouts",
    "xga",
)


@dataclass
class SkaterStatLine:
    gp: int = 0                # games played
    gs: int = 0                # games started
    secs: int = 0               # shift-seconds played
    g: int = 0                  # goals
    a: int = 0                  # assists
    sog: int = 0                # shots on goal
    pim: int = 0                # penalty minutes
    hits: int = 0
    blocks: int = 0
    giveaways: int = 0
    takeaways: int = 0
    fo_won: int = 0              # faceoffs won
    fo_lost: int = 0             # faceoffs lost
    # Tracked as a running counter updated during the game (like real NHL
    # plus/minus bookkeeping), not derivable from any other counters here.
    plus_minus: int = 0
    # Convenience aggregates -- authoritative source is the sim engine's
    # shot-attempt event stream, not this StatLine. See module docstring.
    corsi_for: int = 0
    corsi_against: int = 0
    fenwick_for: int = 0
    fenwick_against: int = 0
    # Expected goals / assists (DESIGN.md point 10): xg is the summed shot-quality goal
    # probability of this skater's own shots on goal; xa is the xg of goals this skater assisted.
    # Floats -- a good xG model is roughly unbiased, so a team's summed xg tracks its actual goals.
    xg: float = 0.0
    xa: float = 0.0

    # -- derived ------------------------------------------------------------
    @property
    def points(self) -> int:
        return self.g + self.a

    @property
    def fo_pct(self) -> float:
        total = self.fo_won + self.fo_lost
        return self.fo_won / total if total else 0.0

    # -- mutation -------------------------------------------------------------
    def add(self, other: "SkaterStatLine") -> None:
        for name in _SKATER_COUNTERS:
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def reset(self) -> None:
        for name in _SKATER_COUNTERS:
            setattr(self, name, 0)

    # -- serialization --------------------------------------------------------
    def to_dict(self) -> Dict[str, int]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: Dict[str, int]) -> "SkaterStatLine":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class GoalieStatLine:
    gp: int = 0                  # games played
    gs: int = 0                  # games started
    secs: int = 0                 # seconds played
    shots_faced: int = 0
    saves: int = 0
    goals_against: int = 0
    wins: int = 0
    losses: int = 0
    otl: int = 0                  # OT/SO losses
    # Incremented by the caller when a goalie completes a game with 0
    # goals_against, rather than derived from other counters here.
    shutouts: int = 0
    # Expected goals against (DESIGN.md point 10): summed shot-quality goal probability of the
    # shots this goalie faced. xga well below goals_against is a goalie stealing games; well above
    # is a goalie being bailed out by his defense's shot suppression.
    xga: float = 0.0

    # -- derived ------------------------------------------------------------
    @property
    def save_pct(self) -> float:
        return self.saves / self.shots_faced if self.shots_faced else 0.0

    @property
    def gaa(self) -> float:
        """Goals-against average, scaled per 60 minutes (3600 seconds)."""
        return self.goals_against * 3600 / self.secs if self.secs else 0.0

    # -- mutation -------------------------------------------------------------
    def add(self, other: "GoalieStatLine") -> None:
        for name in _GOALIE_COUNTERS:
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def reset(self) -> None:
        for name in _GOALIE_COUNTERS:
            setattr(self, name, 0)

    # -- serialization --------------------------------------------------------
    def to_dict(self) -> Dict[str, int]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, d: Dict[str, int]) -> "GoalieStatLine":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})
