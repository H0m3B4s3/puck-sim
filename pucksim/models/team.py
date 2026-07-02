"""The Team model plus roster/lineup helper functions.

Team stores player *ids* only (the authoritative Player objects live on the World, mirroring
HoopR's ``hoopsim/models/team.py`` pattern exactly). Helpers that need player data take a
``players`` mapping so the model stays pure data with no embedded Player objects.

Critical decision (DESIGN.md point 1 / DEVPLAN.md Step 1.7): on-ice groups are plain
``List[List[int]]`` -- NOT hard-coded ``Line``/``Pair`` classes. ``Team.lines`` (4 x 3 ids,
forward lines) and ``Team.pairs`` (3 x 2 ids, D pairs) are ordinary Python lists so a later pass
can splice arbitrary ids into them (a player "caught" for an extended shift, or a mixed group left
over when a special-teams unit reverts to 5v5 mid-shift) without any schema/type change.

Position flexibility & handedness (DEVPLAN.md Step 1.7 amendment, 2026-07-01): a player's
``position`` is their primary slot, but the auto-line-builder can slot forwards into any forward
slot and pair D on either side, at a fit-score cost (see ``position_fit_score()``/
``d_pair_fit_bonus()`` below, driven by ``config.POSITION_FIT_PENALTY``/
``config.HANDEDNESS_FIT_PENALTY``). This is consumed only here, in the line-builder -- never by
``attributes.overall()``, which stays position-agnostic.

``tactics``/``coach`` are left as ``Optional[dict]`` placeholders -- Step 1.10 (building in
parallel) owns the real ``Tactics``/``Coach`` classes; this step must not import a module that may
not exist yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from pucksim.config import HANDEDNESS_FIT_PENALTY, POSITION_FIT_PENALTY
from pucksim.models.attributes import composite
from pucksim.models.player import Player


@dataclass
class Team:
    tid: int
    name: str
    abbrev: str
    conference: str
    division: str = ""

    roster: List[int] = field(default_factory=list)          # player ids only, pure data

    # On-ice groups: plain lists of ids, deliberately not a Line/Pair class
    # (DESIGN.md point 1) -- 4 forward lines of 3 ids, 3 D pairs of 2 ids.
    lines: List[List[int]] = field(default_factory=list)
    pairs: List[List[int]] = field(default_factory=list)
    goalie_starter: Optional[int] = None
    goalie_backup: Optional[int] = None

    # Special-teams units (DEVPLAN.md Step 2.1) -- same "plain list of ids" philosophy as
    # lines/pairs above, never a hard class. ``pp_unit_1`` is the top power-play unit (4F/1D or
    # 3F/2D depending on the team's coach ``pp_forwards`` setting -- see
    # ``auto_build_special_teams_units`` below); ``pk_unit_1`` is the top penalty-kill unit
    # (typically 2F/2D). Only "unit 1" (each team's best group) is modeled in this step -- a
    # second-unit PP/PK rotation is a reasonable future refinement, not required here since the
    # engine only ever needs one PP/PK group on the ice at a time for the v1 penalty model.
    pp_unit_1: List[int] = field(default_factory=list)
    pk_unit_1: List[int] = field(default_factory=list)

    chemistry: Dict[str, float] = field(default_factory=dict)  # pair_key(a,b) -> shared secs

    # Placeholders -- Step 1.10 (tactics.py/coach.py) is being built in parallel
    # and may not exist yet. A later step replaces these with real dataclass
    # types; keep the field names stable so that migration doesn't need a
    # schema rewrite.
    tactics: Optional[dict] = None
    coach: Optional[dict] = None

    wins: int = 0
    losses: int = 0
    ot_losses: int = 0
    streak: int = 0                                          # + win streak / - losing streak

    # -- identity -------------------------------------------------------------
    @property
    def games_played(self) -> int:
        return self.wins + self.losses + self.ot_losses

    @property
    def record_str(self) -> str:
        return f"{self.wins}-{self.losses}-{self.ot_losses}"

    @property
    def streak_str(self) -> str:
        if self.streak == 0:
            return "-"
        return f"{'W' if self.streak > 0 else 'L'}{abs(self.streak)}"

    # -- membership -------------------------------------------------------------
    def add_player(self, pid: int) -> None:
        if pid not in self.roster:
            self.roster.append(pid)

    def remove_player(self, pid: int) -> None:
        if pid in self.roster:
            self.roster.remove(pid)
        self.lines = [[p for p in line if p != pid] for line in self.lines]
        self.pairs = [[p for p in pair if p != pid] for pair in self.pairs]
        self.pp_unit_1 = [p for p in self.pp_unit_1 if p != pid]
        self.pk_unit_1 = [p for p in self.pk_unit_1 if p != pid]
        if self.goalie_starter == pid:
            self.goalie_starter = None
        if self.goalie_backup == pid:
            self.goalie_backup = None
        # Chemistry travels with the pairing: a departing player takes his
        # shared history with him.
        self.chemistry = {k: v for k, v in self.chemistry.items() if pid not in _pair_pids(k)}

    # -- on-ice group accessors -------------------------------------------------
    def current_forward_line(self, idx: int) -> List[int]:
        """Plain-list accessor for forward line ``idx`` (0-3), NOT a Line object.

        Returns the actual list object (not a copy) so a later "caught players"
        pass can splice ids into it without a data-model change.
        """
        if 0 <= idx < len(self.lines):
            return self.lines[idx]
        return []

    def current_d_pair(self, idx: int) -> List[int]:
        """Plain-list accessor for D pair ``idx`` (0-2), NOT a Pair object."""
        if 0 <= idx < len(self.pairs):
            return self.pairs[idx]
        return []

    # -- results ------------------------------------------------------------
    def record_result(self, outcome: str, pf: int = 0, pa: int = 0) -> None:
        """Record a game result. ``outcome`` is one of 'win'/'loss'/'ot_loss'."""
        if outcome == "win":
            self.wins += 1
            self.streak = self.streak + 1 if self.streak >= 0 else 1
        elif outcome == "ot_loss":
            self.ot_losses += 1
            self.streak = self.streak - 1 if self.streak <= 0 else -1
        else:
            self.losses += 1
            self.streak = self.streak - 1 if self.streak <= 0 else -1

    def reset_record(self) -> None:
        self.wins = self.losses = self.ot_losses = 0
        self.streak = 0

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "tid": self.tid,
            "name": self.name,
            "abbrev": self.abbrev,
            "conference": self.conference,
            "division": self.division,
            "roster": list(self.roster),
            "lines": [list(line) for line in self.lines],
            "pairs": [list(pair) for pair in self.pairs],
            "pp_unit_1": list(self.pp_unit_1),
            "pk_unit_1": list(self.pk_unit_1),
            "goalie_starter": self.goalie_starter,
            "goalie_backup": self.goalie_backup,
            "chemistry": {k: round(v, 1) for k, v in self.chemistry.items()},
            "tactics": dict(self.tactics) if self.tactics else None,
            "coach": dict(self.coach) if self.coach else None,
            "wins": self.wins,
            "losses": self.losses,
            "ot_losses": self.ot_losses,
            "streak": self.streak,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Team":
        return cls(
            tid=d["tid"],
            name=d["name"],
            abbrev=d["abbrev"],
            conference=d["conference"],
            division=d.get("division", ""),
            roster=list(d.get("roster", [])),
            lines=[list(line) for line in d.get("lines", [])],
            pairs=[list(pair) for pair in d.get("pairs", [])],
            pp_unit_1=list(d.get("pp_unit_1", [])),
            pk_unit_1=list(d.get("pk_unit_1", [])),
            goalie_starter=d.get("goalie_starter"),
            goalie_backup=d.get("goalie_backup"),
            chemistry={k: float(v) for k, v in d.get("chemistry", {}).items()},
            tactics=(dict(d["tactics"]) if d.get("tactics") else None),
            coach=(dict(d["coach"]) if d.get("coach") else None),
            wins=d.get("wins", 0),
            losses=d.get("losses", 0),
            ot_losses=d.get("ot_losses", 0),
            streak=d.get("streak", 0),
        )


# ---------------------------------------------------------------------------
# Roster helpers (operate on a players mapping) -- live OUTSIDE the dataclass
# so Team itself stays pure data with no dependency on a players dict.
# ---------------------------------------------------------------------------
def roster_players(team: Team, players: Dict[int, Player]) -> List[Player]:
    return [players[pid] for pid in team.roster if pid in players]


def team_salary(team: Team, players: Dict[int, Player]) -> int:
    """Payroll counting toward the cap: sum of active contracts' current_salary."""
    return sum(players[pid].contract.current_salary for pid in team.roster if pid in players)


def available_players(team: Team, players: Dict[int, Player]) -> List[Player]:
    return [p for p in roster_players(team, players) if p.available]


# ---------------------------------------------------------------------------
# Chemistry (lineup familiarity) -- mirrors HoopR's pair_key()/
# lineup_familiarity_secs()/seed_chemistry() pattern directly.
# ---------------------------------------------------------------------------
def pair_key(a: int, b: int) -> str:
    """Order-independent key for a pair of player ids in ``team.chemistry``."""
    return f"{a},{b}" if a < b else f"{b},{a}"


def _pair_pids(key: str) -> Tuple[int, int]:
    lo, hi = key.split(",")
    return int(lo), int(hi)


def lineup_familiarity_secs(team: Team, id_a: int, id_b: int) -> float:
    """Shared on-ice seconds for a pair of ids, via ``team.chemistry``. Missing pair -> 0.0."""
    return team.chemistry.get(pair_key(id_a, id_b), 0.0)


def seed_chemistry(team: Team, rng, base: float = 0.0, spread: float = 0.0) -> None:
    """Seed every current roster pair with a small random baseline (an established roster).

    Mirrors HoopR's "called at world creation so a league that has already existed plays at
    full chemistry from the opening tip" approach, but uses a small randomized baseline (via
    ``rng.uniform``) rather than a single flat constant, so a freshly generated league doesn't
    read as perfectly uniform. Players who arrive later (traded/signed) start cold at 0.0 since
    this only touches pairs present on the roster at call time.
    """
    roster = team.roster
    for i in range(len(roster)):
        for j in range(i + 1, len(roster)):
            secs = base + (rng.uniform(0.0, spread) if spread > 0 else 0.0)
            team.chemistry[pair_key(roster[i], roster[j])] = secs


# ---------------------------------------------------------------------------
# Position / handedness fit scoring (DEVPLAN.md Step 1.7 amendment)
# ---------------------------------------------------------------------------
_FORWARD_SLOTS = ("LW", "C", "RW")
_LEFT_SIDE_SLOT = "LW"
_RIGHT_SIDE_SLOT = "RW"


def position_fit_score(player: Player, slot: str) -> int:
    """Fit score for slotting ``player`` into forward ``slot`` (LW/C/RW).

    Returns ``player.overall`` minus the position-category penalty (0 if on
    primary position) minus a handedness penalty (only applicable for LW/RW
    slots -- see module docstring / config.py). Higher is a better fit.
    """
    if player.position == slot:
        category_penalty = 0
    else:
        category_penalty = POSITION_FIT_PENALTY.get((player.position, slot), 0)

    handedness_penalty = 0
    if slot == _LEFT_SIDE_SLOT and player.shoots == "R":
        handedness_penalty = HANDEDNESS_FIT_PENALTY
    elif slot == _RIGHT_SIDE_SLOT and player.shoots == "L":
        handedness_penalty = HANDEDNESS_FIT_PENALTY
    # C: no handedness penalty -- centers play the middle regardless of hand.

    return player.overall - category_penalty - handedness_penalty


def d_pair_fit_bonus(player_a: Player, player_b: Player) -> int:
    """Pair-composition fit bonus for a D pair: 0 if opposite-handed, penalized if same-handed.

    Real-NHL norm is an opposite-handed pair (one L, one R) so each defenseman's forehand covers
    the far half of the blue line without reaching across his body; a same-handed pair remains
    legal but is a worse fit, all else equal.
    """
    if player_a.shoots != player_b.shoots:
        return 0
    return -HANDEDNESS_FIT_PENALTY


# ---------------------------------------------------------------------------
# Auto line-builder -- straightforward slot-fill-by-fit, not a global
# optimizer (mirrors HoopR's assign_positions()'s simplicity).
# ---------------------------------------------------------------------------
def auto_build_lines(team: Team, players: Dict[int, Player]) -> None:
    """Greedily build 4 forward lines, 3 D pairs, and starter/backup goalie assignments.

    Mutates ``team.lines``/``team.pairs``/``team.goalie_starter``/``team.goalie_backup`` in
    place. A reasonable greedy approach, not an optimal solver -- consistent with HoopR's own
    ``assign_positions()``, which is a straightforward slot-fill-by-fit, not a global optimizer.
    """
    roster = roster_players(team, players)
    forwards = [p for p in roster if p.position in _FORWARD_SLOTS]
    defensemen = [p for p in roster if p.position == "D"]
    goalies = [p for p in roster if p.position == "G"]

    team.lines = _build_forward_lines(forwards)
    team.pairs = _build_d_pairs(defensemen)

    goalies_sorted = sorted(goalies, key=lambda p: p.overall, reverse=True)
    team.goalie_starter = goalies_sorted[0].pid if len(goalies_sorted) >= 1 else None
    team.goalie_backup = goalies_sorted[1].pid if len(goalies_sorted) >= 2 else None


def _build_forward_lines(forwards: List[Player]) -> List[List[int]]:
    """Greedily fill up to 4 lines of LW/C/RW, maximizing per-slot fit score.

    For each of the 4 lines, and for each slot in a fixed order (C first, since centers are the
    scarcest/most constrained resource -- worst penalty is wing->C -- then LW, then RW), picks the
    best remaining player by fit score for that slot.
    """
    remaining = list(forwards)
    lines: List[List[int]] = []
    num_lines = min(4, len(forwards) // 3)
    slot_order = ("C", "LW", "RW")
    for _ in range(num_lines):
        line_slots: Dict[str, int] = {}
        for slot in slot_order:
            if not remaining:
                break
            best = max(remaining, key=lambda p: position_fit_score(p, slot))
            line_slots[slot] = best.pid
            remaining.remove(best)
        if len(line_slots) == 3:
            lines.append([line_slots["LW"], line_slots["C"], line_slots["RW"]])
    return lines


def _build_d_pairs(defensemen: List[Player]) -> List[List[int]]:
    """Greedily pair D into up to 3 pairs, preferring opposite-handed pairs via fit bonus."""
    remaining = list(defensemen)
    pairs: List[List[int]] = []
    num_pairs = min(3, len(defensemen) // 2)
    for _ in range(num_pairs):
        if len(remaining) < 2:
            break
        best_score = None
        best_combo: Optional[Tuple[Player, Player]] = None
        for i in range(len(remaining)):
            for j in range(i + 1, len(remaining)):
                a, b = remaining[i], remaining[j]
                score = a.overall + b.overall + d_pair_fit_bonus(a, b)
                if best_score is None or score > best_score:
                    best_score = score
                    best_combo = (a, b)
        a, b = best_combo
        pairs.append([a.pid, b.pid])
        remaining.remove(a)
        remaining.remove(b)
    return pairs


# ---------------------------------------------------------------------------
# Special-teams unit builder (DEVPLAN.md Step 2.1) -- picks a team's top power-play unit
# and top penalty-kill unit. Reuses attributes.py's composite() machinery rather than
# inventing a new rating system: PP unit selection ranks by an offense-flavored blend
# (scoring + playmaking), PK unit selection ranks by the existing "defense" composite.
# Greedy top-N by composite, same simplicity level as auto_build_lines/_build_d_pairs
# above -- not a global optimizer.
# ---------------------------------------------------------------------------
def _pp_offensive_value(player: Player) -> float:
    """Composite offensive value driving PP unit selection: a blend of scoring and
    playmaking (both already-defined composites in attributes.py), not a new formula."""
    return 0.55 * composite(player.ratings, "scoring") + 0.45 * composite(player.ratings, "playmaking_c")


def _pk_defensive_value(player: Player) -> float:
    """Composite defensive value driving PK unit selection: attributes.py's existing
    "defense" composite (defensive_awareness/shot_blocking/checking/discipline blend)."""
    return composite(player.ratings, "defense")


def auto_build_special_teams_units(team: Team, players: Dict[int, Player],
                                    pp_forwards: int = 3) -> None:
    """Build the team's top power-play unit (``team.pp_unit_1``) and top penalty-kill unit
    (``team.pk_unit_1``) from its current roster. Mutates both fields in place.

    ``pp_forwards`` (3 or 4, mirrors ``CoachProfile.pp_forwards``) controls the PP unit shape:
    3 forwards + 2 D (conservative) or 4 forwards + 1 D (aggressive overload). Falls back to
    whatever the roster can actually supply if it's short on bodies (e.g. an injury-depleted
    roster) rather than crashing -- a partial/undersized unit is legal, just not ideal, same
    philosophy as auto_build_lines's "not an optimal solver" framing.

    PK unit is always the classic 2F/2D defensive-shutdown shape (config.PK_UNIT_SIZE == 4).

    A player can appear on both units (real NHL rosters often double up their best two-way
    players across both special-teams groups) -- no exclusivity is enforced between PP and PK
    selection, only within each unit's own slot-fill.
    """
    roster = roster_players(team, players)
    forwards = [p for p in roster if p.position in _FORWARD_SLOTS]
    defensemen = [p for p in roster if p.position == "D"]

    pp_forwards = 4 if pp_forwards == 4 else 3
    pp_d = 5 - pp_forwards

    top_forwards = sorted(forwards, key=_pp_offensive_value, reverse=True)[:pp_forwards]
    top_pp_d = sorted(defensemen, key=_pp_offensive_value, reverse=True)[:pp_d]
    team.pp_unit_1 = [p.pid for p in top_forwards] + [p.pid for p in top_pp_d]

    top_pk_forwards = sorted(forwards, key=_pk_defensive_value, reverse=True)[:2]
    top_pk_d = sorted(defensemen, key=_pk_defensive_value, reverse=True)[:2]
    team.pk_unit_1 = [p.pid for p in top_pk_forwards] + [p.pid for p in top_pk_d]


def rotation_pool(team: Team, players: Dict[int, Player]) -> List[int]:
    """The bench/scratch pool: roster ids minus whoever's in an active line/pair/goalie slot."""
    active = set()
    for line in team.lines:
        active.update(line)
    for pair in team.pairs:
        active.update(pair)
    if team.goalie_starter is not None:
        active.add(team.goalie_starter)
    if team.goalie_backup is not None:
        active.add(team.goalie_backup)
    return [pid for pid in team.roster if pid not in active]
