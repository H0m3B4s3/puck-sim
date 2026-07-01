"""The World — root aggregate holding all league state and the save target.

Mirrors HoopR's ``hoopsim/models/world.py`` (267 lines) pattern: a single object holds
teams, players, schedule, and the RNG, so a save file is just this one object's
``to_dict()``. Players live in a single ``players`` map keyed by id; teams reference
players by id only (``Team.roster``). This keeps signings/releases/trades simple
reassignments and avoids duplicated state -- ``Team.roster`` is the list of ids and
``Player.team_id`` is the mirror; every roster-transaction method on this class keeps
both sides in sync (see ``sign_player``/``release_player``/``transfer_player`` below),
per Step 1.7's documented "roster is pure data" design.

The RNG (``pucksim.rng.Rng``) lives on the world so a reloaded save reproduces sim
results exactly -- all game logic should draw randomness from ``World.rng``, never the
global ``random`` module.

Standings rule (DEVPLAN.md Step 1.9): unlike HoopR (single win/loss scheme), PuckSim's
standings math is rule-parameterized (Step 1.8 / config.STANDINGS_RULES). ``config.py``
holds the three presets as data; ``World.standings_rule`` is the *per-save* selection of
which preset is active, consumed by ``league.standings()``/``points_for_game()``.

Multi-league hook fields (DESIGN.md point 11 / "What carries over directly from HoopR" /
"Multi-league expansion" section): ``mode``, ``other_teams``, ``recruits``, and
``pipeline`` are dormant in v1 (NHL-only) -- they exist now, empty and unused, purely so
Phase 2 (NCAA/CHL feeder leagues, DEVPLAN.md Step 3.2) never needs a save-migration
rewrite to add them later. This directly mirrors HoopR's own ``mode``/``other_teams``/
``recruits``/``pipeline`` fields, which were exactly this kind of forward-looking hook
before HoopR's college layer was actually built.

Cap fields stay minimal per DESIGN.md's v1 cap/contract fidelity decision: one flat
``salary_cap: int``, no luxury-tax-line/apron complexity (that's HoopR-NBA-specific and
explicitly deferred past v1 for PuckSim -- see DEVPLAN.md Step 3.1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pucksim.config import DEFAULT_STANDINGS_RULE, SCHEMA_VERSION
from pucksim.models.draft import DraftClass
from pucksim.models.league import Game, Phase
from pucksim.models.player import Player
from pucksim.models.team import Team
from pucksim.rng import Rng

# v1 has no config.SALARY_CAP constant yet (HoopR's NBA-specific cap dollar figure
# doesn't have a hockey-tuned equivalent decided at this step) -- a reasonable
# placeholder flat number lives here, explicitly commented as provisional/tunable,
# consistent with how config.py itself flags similarly-unresolved constants
# (e.g. development/aging placeholders) elsewhere in this codebase.
_DEFAULT_SALARY_CAP = 82_500_000  # provisional placeholder, NHL-scale dollar figure


@dataclass
class World:
    rng: Rng
    season_year: int = 2025
    phase: str = Phase.PRESEASON
    day: int = 0

    teams: Dict[int, Team] = field(default_factory=dict)
    players: Dict[int, Player] = field(default_factory=dict)
    schedule: List[Game] = field(default_factory=list)
    free_agents: List[int] = field(default_factory=list)      # pids with no team

    draft_class: Optional[DraftClass] = None

    user_team_id: Optional[int] = None

    # Per-save standings-rule selection (Step 1.8's three presets live in
    # config.STANDINGS_RULES; this is just the active key).
    standings_rule: str = DEFAULT_STANDINGS_RULE

    # v1 simplified cap model (DESIGN.md): single flat number, no apron/tax tiers.
    salary_cap: int = _DEFAULT_SALARY_CAP

    # -- dormant multi-league hook fields (DESIGN.md point 11) ------------------
    # NHL-only in v1; these exist now, empty, so Phase 2 (CHL/NCAA, DEVPLAN.md
    # Step 3.2) and Phase 3 (Europe, Step 3.3) can populate them later without a
    # save-schema rewrite. Mirrors HoopR's mode/other_teams/recruits/pipeline
    # fields exactly (that pattern is what unlocked HoopR's NBA->NBA+college
    # expansion without breaking old saves).
    mode: str = "nhl"                              # the (only) league mode in v1
    other_teams: Dict[int, Team] = field(default_factory=dict)   # future CHL/NCAA/Europe pools
    recruits: List[int] = field(default_factory=list)            # future unsigned prospect pids
    pipeline: dict = field(default_factory=dict)                 # future feeder->NHL draft results

    # -- id allocation (private counters, incremented so ids never collide
    # across a save's lifetime even after players/games are removed) ----------
    _next_pid: int = 1
    _next_gid: int = 1

    # -- id allocation --------------------------------------------------------
    def new_pid(self) -> int:
        pid = self._next_pid
        self._next_pid += 1
        return pid

    def new_gid(self) -> int:
        gid = self._next_gid
        self._next_gid += 1
        return gid

    # -- accessors --------------------------------------------------------------
    def team(self, tid: int) -> Team:
        return self.teams[tid]

    def player(self, pid: int) -> Player:
        return self.players[pid]

    def team_list(self) -> List[Team]:
        return list(self.teams.values())

    def other_team_list(self) -> List[Team]:
        return list(self.other_teams.values())

    @property
    def user_team(self) -> Optional[Team]:
        if self.user_team_id is None:
            return None
        return self.teams.get(self.user_team_id)

    def free_agent_players(self) -> List[Player]:
        return [self.players[pid] for pid in self.free_agents if pid in self.players]

    # -- registration -------------------------------------------------------
    def add_player(self, player: Player) -> None:
        """Register a player into ``self.players``.

        If the player has no team (``team_id is None``), it also joins
        ``free_agents`` -- this keeps the free-agent list accurate for players
        constructed already-unsigned (e.g. undrafted prospects), without
        requiring callers to separately call ``release_player()``.
        """
        self.players[player.pid] = player
        if player.team_id is None and player.pid not in self.free_agents:
            self.free_agents.append(player.pid)

    def register_team(self, team: Team) -> None:
        self.teams[team.tid] = team

    def register_other_team(self, team: Team) -> None:
        self.other_teams[team.tid] = team

    # -- roster transactions --------------------------------------------------
    # These three methods are the single source of truth for keeping
    # Team.roster (the list of ids) and Player.team_id (the mirror) in sync --
    # per Step 1.7's documented design, nothing else should mutate either side
    # directly.
    def sign_player(self, pid: int, tid: int) -> None:
        """Sign a player (typically a free agent) to a team's roster."""
        player = self.players[pid]
        old_tid = player.team_id
        if old_tid is not None and old_tid in self.teams and old_tid != tid:
            self.teams[old_tid].remove_player(pid)
        if pid in self.free_agents:
            self.free_agents.remove(pid)
        player.team_id = tid
        self.teams[tid].add_player(pid)

    def release_player(self, pid: int) -> None:
        """Waive a player to free agency: reverse of ``sign_player``."""
        player = self.players[pid]
        team = self.teams.get(player.team_id) if player.team_id is not None else None
        if team is not None:
            team.remove_player(pid)
        player.team_id = None
        if pid not in self.free_agents:
            self.free_agents.append(pid)

    def transfer_player(self, pid: int, to_tid: int) -> None:
        """Move a player directly from their current team to ``to_tid`` (e.g. a trade).

        Equivalent to a release-then-sign, but never touches ``free_agents``
        since the player is never actually a free agent mid-transfer.
        """
        player = self.players[pid]
        old_tid = player.team_id
        if old_tid is not None and old_tid in self.teams:
            self.teams[old_tid].remove_player(pid)
        player.team_id = to_tid
        self.teams[to_tid].add_player(pid)

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "rng_seed": self.rng.seed,
            "rng_state": self.rng.get_state(),
            "season_year": self.season_year,
            "phase": self.phase,
            "day": self.day,
            "teams": {str(t): team.to_dict() for t, team in self.teams.items()},
            "players": {str(p): pl.to_dict() for p, pl in self.players.items()},
            "schedule": [g.to_dict() for g in self.schedule],
            "free_agents": list(self.free_agents),
            "draft_class": self.draft_class.to_dict() if self.draft_class else None,
            "user_team_id": self.user_team_id,
            "standings_rule": self.standings_rule,
            "salary_cap": self.salary_cap,
            "mode": self.mode,
            "other_teams": {str(t): team.to_dict() for t, team in self.other_teams.items()},
            "recruits": list(self.recruits),
            "pipeline": dict(self.pipeline),
            "next_pid": self._next_pid,
            "next_gid": self._next_gid,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "World":
        rng = Rng.from_state(d.get("rng_seed"), d.get("rng_state"))
        world = cls(rng=rng)
        world.season_year = d.get("season_year", 2025)
        world.phase = d.get("phase", Phase.PRESEASON)
        world.day = d.get("day", 0)
        world.teams = {int(t): Team.from_dict(td) for t, td in d.get("teams", {}).items()}
        world.players = {int(p): Player.from_dict(pd) for p, pd in d.get("players", {}).items()}
        world.schedule = [Game.from_dict(gd) for gd in d.get("schedule", [])]
        world.free_agents = list(d.get("free_agents", []))
        dc = d.get("draft_class")
        world.draft_class = DraftClass.from_dict(dc) if dc else None
        world.user_team_id = d.get("user_team_id")
        world.standings_rule = d.get("standings_rule", DEFAULT_STANDINGS_RULE)
        world.salary_cap = d.get("salary_cap", _DEFAULT_SALARY_CAP)
        world.mode = d.get("mode", "nhl")
        world.other_teams = {
            int(t): Team.from_dict(td) for t, td in d.get("other_teams", {}).items()
        }
        world.recruits = list(d.get("recruits", []))
        world.pipeline = dict(d.get("pipeline") or {})
        world._next_pid = d.get("next_pid", max(world.players, default=0) + 1)
        world._next_gid = d.get("next_gid", 1)
        return world
