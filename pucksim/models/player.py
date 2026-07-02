"""The Player model -- the central entity of the game.

Single-class-vs-two-classes decision (DEVPLAN.md Step 1.6 "First sub-task"):
DESIGN.md/DEVPLAN.md recommend a single ``Player`` dataclass with a
``position`` field, rather than a parallel ``Skater``/``Goalie`` class
hierarchy. This module implements that recommendation. Concretely, the two
structurally-different box-score shapes required by Step 1.3
(``SkaterStatLine`` vs. ``GoalieStatLine``) are handled by choosing the
stat-line type *at construction time* based on ``position == "G"``, not by
the dataclass schema itself -- ``Player.season``/``Player.playoffs`` are
typed ``StatLine`` (a ``Union[SkaterStatLine, GoalieStatLine]`` alias) and
``__post_init__`` fills in the correct concrete type if the caller didn't
supply one explicitly.

Why this works cleanly (no strong reason found to deviate): every other
position-dependent concern already dispatches on ``position`` as data rather
than as a type distinction -- ``attributes.overall(position, ratings)``
picks skater-composite vs. goalie-flat-average internally, and the two
rating vocabularies (``ALL_RATINGS`` vs. ``ALL_GOALIE_RATINGS``) are just
different keys in the same ``Dict[str, int]``. A ``Skater``/``Goalie``
class split would force every downstream consumer (Team roster lists,
World's player dict, save/load, the sim engine's per-shift lookups) to
either duplicate handling for two types or immediately upcast back to a
common interface -- essentially reinventing the single-class shape with
extra ceremony. The one place the split literally matters (StatLine shape)
is handled locally in ``__post_init__``/``to_dict``/``from_dict`` without
needing separate classes.

Mirrors the shape of HoopR's ``hoopsim/models/player.py`` (178 lines):
``Injury`` dataclass; ``Player`` dataclass with identity fields, a flat
``ratings`` dict, ``potential``, ``contract``, ``condition``/``morale``/
``injury``, ``scout_error``, ``pre_draft``/``draft`` bio dicts, ``season``/
``playoffs`` stat lines, ``career``, ``accolades``; ``overall``/
``is_free_agent``/``is_injured``/``available``/``rating()``/
``scouted_potential()`` properties; full ``to_dict()``/``from_dict()``.

Team membership: mirrors HoopR exactly -- ``team_id: Optional[int] = None``
lives directly on ``Player`` (HoopR's ``Team.roster`` is a plain list of
ids; ``Player.team_id`` is the only place membership is recorded, and
``is_free_agent`` is simply ``team_id is None``). PuckSim's Step 1.7
(``team.py``) will need the same thing: ``Team.roster``/``lines``/``pairs``
as plain lists of player ids, with ``Player.team_id`` as the source of
truth for "which team is this player on." Keeping it on Player (rather
than, say, only deriving it by scanning every Team's roster) is what makes
``is_free_agent`` a cheap local property instead of a World-level query.

``condition``/``morale`` defaults and scale match HoopR's actual values
(checked directly, not assumed): ``condition: float = 100.0`` (0-100
between-game freshness) and ``morale: int = 70`` (0-100), not a 0.0-1.0
scale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

from pucksim.config import RATING_MIN
from pucksim.models.attributes import ALL_GOALIE_RATINGS, ALL_RATINGS, overall
from pucksim.models.contract import Contract
from pucksim.models.stats import GoalieStatLine, SkaterStatLine

# The two box-score shapes from Step 1.3. Which concrete type a given
# Player's season/playoffs fields hold is determined by position (see
# __post_init__), not encoded in the type system as a separate class.
StatLine = Union[SkaterStatLine, GoalieStatLine]


@dataclass
class Injury:
    """Data container only -- injury-generation logic lands in Step 2.3."""

    description: str
    games_remaining: int
    severity: str = "minor"   # minor | moderate | major

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "games_remaining": self.games_remaining,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Injury":
        return cls(d["description"], d["games_remaining"], d.get("severity", "minor"))


@dataclass
class Player:
    pid: int
    name: str
    age: int
    position: str                        # one of attributes.POSITIONS
    ratings: Dict[str, int] = field(default_factory=dict)
    potential: int = 25                  # overall ceiling, 25-99
    scout_error: float = 0.0             # hidden noise driving scouted_potential() fog-of-war
    secondary_position: Optional[str] = None
    shoots: str = "L"                    # "L" or "R" -- shot/stick handedness.
    # Distinct from `position`: two players can both be "D" but shoot opposite
    # hands, which matters for pairing (a lefty/righty D pair covers the blue
    # line without both reaching across their body) and for wingers (a player's
    # natural wing side generally matches their handedness -- left shots on
    # left wing, right shots on right wing -- though real NHL rosters routinely
    # deploy players on their "off wing"). Position stays a single "D" slot for
    # now (see attributes.py's POSITIONS docstring); handedness is what actually
    # drives side-of-ice fit, and is consumed by team.py's line/pair builder as
    # a fit-penalty input, not baked into overall().
    team_id: Optional[int] = None        # None == free agent; source of truth for membership

    contract: Contract = field(default_factory=Contract.free_agent)

    condition: float = 100.0             # 0-100 between-game freshness (100 = fully rested)
    morale: int = 70                     # 0-100
    injury: Optional[Injury] = None

    # Pre-draft scouting bio (production line, etc.) for draft-eligible prospects;
    # None for everyone else.
    pre_draft: Optional[Dict] = None

    # Which feeder path this prospect came up through -- DESIGN.md point 11's
    # CHL/NCAA mutual-exclusivity fork (Canadian major junior forfeits NCAA
    # eligibility, unlike basketball's overlapping college/G-League routes).
    # Always "none" (config.DEFAULT_LEAGUE_ORIGIN) in v1/Phase 2 -- there is no
    # feeder-league layer yet, every prospect is just "generic." This field
    # exists now, populated with the inert default, purely so Phase 2's CHL/NCAA
    # fork (DEVPLAN.md Step 3.2) doesn't need a save-migration rewrite to add it
    # later. See config.LEAGUE_ORIGIN_CHOICES for the legal values.
    league_origin: str = "none"

    # How the player entered the league: {"year", "round", "pick", "team"} or
    # None if undrafted/not yet drafted.
    draft: Optional[Dict] = None

    # Current-year stat lines. Concrete type (SkaterStatLine vs. GoalieStatLine)
    # is chosen in __post_init__ based on position if not supplied explicitly.
    season: Optional[StatLine] = None
    playoffs: Optional[StatLine] = None

    career: List[dict] = field(default_factory=list)         # one summary dict per finished season
    accolades: Dict[str, int] = field(default_factory=dict)  # award tally

    def __post_init__(self) -> None:
        if self.season is None:
            self.season = GoalieStatLine() if self.is_goalie else SkaterStatLine()
        if self.playoffs is None:
            self.playoffs = GoalieStatLine() if self.is_goalie else SkaterStatLine()

    # -- identity -------------------------------------------------------------
    @property
    def is_goalie(self) -> bool:
        return self.position == "G"

    @property
    def short_name(self) -> str:
        parts = self.name.split()
        if len(parts) < 2:
            return self.name
        return f"{parts[0][0]}. {' '.join(parts[1:])}"

    @property
    def overall(self) -> int:
        return overall(self.position, self.ratings)

    @property
    def is_free_agent(self) -> bool:
        return self.team_id is None

    @property
    def is_injured(self) -> bool:
        return self.injury is not None and self.injury.games_remaining > 0

    @property
    def available(self) -> bool:
        return not self.is_injured

    def rating(self, key: str, default: int = RATING_MIN) -> int:
        """Safe lookup into ``ratings`` -- validates against the vocabulary
        implied by position (ALL_GOALIE_RATINGS for goalies, ALL_RATINGS for
        skaters) only loosely: any key is accepted, since callers may probe
        either vocabulary defensively (e.g. generic code iterating both)."""
        return self.ratings.get(key, default)

    # -- scouting ---------------------------------------------------------------
    def scouted_potential(self) -> int:
        """Potential as a scout would estimate it (fuzzed by hidden scout_error).

        Mirrors HoopR's exact formula: never reported below the player's
        current overall (a scout can always see how good the player already
        is), and clamped at 99 on the high end.
        """
        return max(self.overall, min(99, int(round(self.potential + self.scout_error))))

    # -- serialization ----------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "name": self.name,
            "age": self.age,
            "position": self.position,
            "secondary_position": self.secondary_position,
            "shoots": self.shoots,
            "ratings": dict(self.ratings),
            "potential": self.potential,
            "scout_error": self.scout_error,
            "team_id": self.team_id,
            "contract": self.contract.to_dict(),
            "condition": self.condition,
            "morale": self.morale,
            "injury": self.injury.to_dict() if self.injury else None,
            "pre_draft": dict(self.pre_draft) if self.pre_draft else None,
            "draft": dict(self.draft) if self.draft else None,
            "league_origin": self.league_origin,
            "season": self.season.to_dict(),
            "playoffs": self.playoffs.to_dict(),
            "career": list(self.career),
            "accolades": dict(self.accolades),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Player":
        position = d["position"]
        is_goalie = position == "G"
        vocabulary = ALL_GOALIE_RATINGS if is_goalie else ALL_RATINGS
        raw_ratings = d.get("ratings", {})
        ratings = {k: int(raw_ratings.get(k, RATING_MIN)) for k in vocabulary}

        stat_cls = GoalieStatLine if is_goalie else SkaterStatLine

        return cls(
            pid=d["pid"],
            name=d["name"],
            age=d["age"],
            position=position,
            secondary_position=d.get("secondary_position"),
            shoots=d.get("shoots", "L"),
            ratings=ratings,
            potential=d.get("potential", RATING_MIN),
            scout_error=d.get("scout_error", 0.0),
            team_id=d.get("team_id"),
            contract=Contract.from_dict(d.get("contract", {})),
            condition=d.get("condition", 100.0),
            morale=d.get("morale", 70),
            injury=Injury.from_dict(d["injury"]) if d.get("injury") else None,
            pre_draft=(dict(d["pre_draft"]) if d.get("pre_draft") else None),
            draft=(dict(d["draft"]) if d.get("draft") else None),
            league_origin=d.get("league_origin", "none"),
            season=stat_cls.from_dict(d.get("season", {})),
            playoffs=stat_cls.from_dict(d.get("playoffs", {})),
            career=list(d.get("career", [])),
            accolades={k: int(v) for k, v in d.get("accolades", {}).items()},
        )
