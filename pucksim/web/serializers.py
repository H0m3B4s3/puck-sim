"""DTO builders: domain objects -> JSON-safe response shapes (DEVPLAN.md Step 2.9a).

Pydantic ``BaseModel`` subclasses (not plain dicts) -- FastAPI turns these into both response
validation and free OpenAPI docs, and it keeps this module symmetrical with ``routers/career.py``'s
Pydantic *request* models rather than mixing two different "shape of data crossing the wire"
conventions in the same web layer.

Deliberately additive-only for this step (per the Step 2.9a brief): just enough DTOs to back
``routers/career.py``'s endpoints -- a team summary, a world/career summary, and a standings
entry. Player/game/box-score/transaction DTOs are explicitly out of scope here; later steps
(2.9b-i/ii/iii) extend this file rather than replace it.

Every DTO builder takes live domain objects (``Team``, ``World``) and returns a DTO instance --
none of them mutate the domain object or duplicate its logic. Standings math in particular is
never reimplemented here: ``standings_response()`` calls straight through to
``pucksim.models.league.standings()``/``points_for_game()`` (Step 1.8's existing, tested standings
math), exactly the way ``testkit/run_season.py``'s own ``_team_points()`` helper already does --
this module isn't the first place to recompute points-from-games, it's following an established
in-repo precedent.
"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from pucksim.models.league import points_for_game, standings
from pucksim.models.player import Player
from pucksim.models.team import Team
from pucksim.models.world import World


# ---------------------------------------------------------------------------
# Team summary
# ---------------------------------------------------------------------------
class TeamRecordDTO(BaseModel):
    wins: int
    losses: int
    ot_losses: int
    points: int
    streak: str


class TeamSummaryDTO(BaseModel):
    id: int
    name: str
    abbrev: str
    conference: str
    division: str
    primary_color: str
    secondary_color: str
    # None until the team has actually played a game this season (a freshly generated,
    # still-preseason career has no meaningful win/loss/points line yet) -- see
    # team_summary()'s docstring.
    record: Optional[TeamRecordDTO] = None


def _team_points(world: World, team: Team) -> int:
    """Total accumulated standings points for ``team`` under ``world.standings_rule``.

    Mirrors ``league.standings()``'s own internal accumulation (every played game the team is
    involved in, via the public ``points_for_game()`` -- ``standings()``'s per-team accumulator
    dict is a private local, not something this module reaches into) -- same approach
    ``testkit/run_season.py``'s ``_team_points()`` already uses.
    """
    return sum(
        points_for_game(world.standings_rule, team.tid, g)
        for g in world.schedule
        if g.played and g.involves(team.tid)
    )


def team_summary(team: Team, world: World) -> TeamSummaryDTO:
    """Build a :class:`TeamSummaryDTO` for ``team``. ``record`` is populated only once the team
    has played at least one game this season."""
    record = None
    if team.games_played > 0:
        record = TeamRecordDTO(
            wins=team.wins,
            losses=team.losses,
            ot_losses=team.ot_losses,
            points=_team_points(world, team),
            streak=team.streak_str,
        )
    return TeamSummaryDTO(
        id=team.tid,
        name=team.name,
        abbrev=team.abbrev,
        conference=team.conference,
        division=team.division,
        primary_color=team.primary_color,
        secondary_color=team.secondary_color,
        record=record,
    )


# ---------------------------------------------------------------------------
# World / career summary
# ---------------------------------------------------------------------------
class WorldSummaryDTO(BaseModel):
    season_year: int
    phase: str
    day: int
    standings_rule: str
    user_team_id: Optional[int] = None
    regular_season_complete: bool = False
    offseason_stage: Optional[str] = None
    trade_deadline_day: Optional[int] = None
    trade_deadline_passed: bool = False


def season_over(world: World) -> bool:
    """Check if the regular season is complete.

    Computes: world.phase != Phase.PRESEASON and bool(world.schedule) and
    all(g.played for g in world.schedule if not g.is_playoff).

    This guards against the bare regular_season_complete() function returning True
    on an empty preseason schedule (all([]) == True). The phase guard means the flag
    stays true through playoffs/draft/FA until start_season() regenerates the schedule.
    """
    from pucksim.models.league import Phase

    if world.phase == Phase.PRESEASON:
        return False
    if not world.schedule:
        return False
    return all(g.played for g in world.schedule if not g.is_playoff)


def _offseason_stage(world: World) -> Optional[str]:
    """Derive the offseason stage from world state (no new World field needed).

    Returns one of: "pre_draft", "draft", "free_agency", or None.
    """
    from pucksim.models.league import Phase

    if world.phase == Phase.DRAFT:
        if world.draft_class is None:
            return "pre_draft"
        if world.draft_class.complete:
            return "free_agency"
        return "draft"
    if world.phase == Phase.FREE_AGENCY:
        return "free_agency"
    return None


def world_summary(world: World) -> WorldSummaryDTO:
    from pucksim.systems.trades import trade_deadline_day, trade_deadline_passed

    return WorldSummaryDTO(
        season_year=world.season_year,
        phase=world.phase,
        day=world.day,
        standings_rule=world.standings_rule,
        user_team_id=world.user_team_id,
        regular_season_complete=season_over(world),
        offseason_stage=_offseason_stage(world),
        trade_deadline_day=trade_deadline_day(world),
        trade_deadline_passed=trade_deadline_passed(world),
    )


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------
class StandingsEntryDTO(TeamSummaryDTO):
    """A team's standings row -- always carries a live points/wins/losses/OTL line (unlike the
    plain ``TeamSummaryDTO.record``, which is ``None`` pre-season), since a standings table with
    no rule-scored point totals wouldn't be useful even for a 0-games-played league."""

    points: int
    wins: int
    losses: int
    ot_losses: int


def standings_response(world: World) -> List[StandingsEntryDTO]:
    """Every team, ordered per ``world.standings_rule`` via ``league.standings()`` -- the sort
    itself is never reimplemented here, only wrapped into DTO shape. Safe to call on a freshly
    generated, 0-games-played world: every team just sorts to 0 points/wins/losses (stable on
    ``team.tid``, per ``standings()``'s documented tiebreaker chain)."""
    ordered = standings(world.team_list(), world.schedule, world.standings_rule)
    out = []
    for team in ordered:
        base = team_summary(team, world)
        out.append(
            StandingsEntryDTO(
                **base.model_dump(),
                points=_team_points(world, team),
                wins=team.wins,
                losses=team.losses,
                ot_losses=team.ot_losses,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Cap summary (Step 2.9b-iii)
# ---------------------------------------------------------------------------
class CapSummaryDTO(BaseModel):
    payroll: int
    cap_space: int
    over_cap: bool
    salary_cap: int


def cap_summary(world: World, team: Team) -> CapSummaryDTO:
    """Cap/payroll summary for a team via ``systems/cap.py``'s existing functions."""
    from pucksim.systems.cap import cap_space, over_cap, payroll

    return CapSummaryDTO(
        payroll=payroll(world, team),
        cap_space=cap_space(world, team),
        over_cap=over_cap(world, team),
        salary_cap=world.salary_cap,
    )


# ---------------------------------------------------------------------------
# Player summary (lightweight, for boards/lists -- free agents, trade targets)
# ---------------------------------------------------------------------------
# Named distinctly from roster.py's PlayerSummaryDTO (added in Step 2.9b-i, which carries
# contract/injury/shoots detail for a roster view) -- this is a deliberately lighter shape for
# board/list contexts (free-agent board, trade targets) that don't need that detail, and reusing
# the same class name would have silently shadowed one definition with the other on import.
class TransactionPlayerSummaryDTO(BaseModel):
    pid: int
    name: str
    position: str
    age: int
    overall: int
    team_id: Optional[int] = None
    ask: int = 0  # Market salary (wave-adjusted if in offseason)
    preferred_years: int = 1  # Preferred contract length


# ---------------------------------------------------------------------------
# Trade response
# ---------------------------------------------------------------------------
class TradeResponseDTO(BaseModel):
    accepted: bool
    reason: str


# ---------------------------------------------------------------------------
# Draft board
# ---------------------------------------------------------------------------
class DraftBoardEntryDTO(BaseModel):
    pid: int
    name: str
    position: str
    age: int
    overall: int
    scouted_potential: int


class DraftBoardDTO(BaseModel):
    in_draft: bool
    board: List[DraftBoardEntryDTO] = []
    team_on_clock: Optional[int] = None
    round_number: Optional[int] = None


def draft_board_dto(world: World) -> DraftBoardDTO:
    """Current draft board state."""
    from pucksim.systems.draft_system import draft_board, _round_for_pick

    if world.draft_class is None:
        return DraftBoardDTO(in_draft=False, board=[], team_on_clock=None, round_number=None)

    board = draft_board(world)
    entries = [
        DraftBoardEntryDTO(
            pid=p.pid,
            name=p.name,
            position=p.position,
            age=p.age,
            overall=p.overall,
            scouted_potential=p.scouted_potential(),
        )
        for p in board
    ]

    on_clock = world.draft_class.team_on_clock()
    round_no = None
    if on_clock is not None:
        round_no = _round_for_pick(world.draft_class, world.draft_class.current_pick)

    return DraftBoardDTO(
        in_draft=True,
        board=entries,
        team_on_clock=on_clock,
        round_number=round_no,
    )


# ---------------------------------------------------------------------------
# Awards
# ---------------------------------------------------------------------------
class AwardsEntryDTO(BaseModel):
    pid: int
    name: str
    team: str
    position: str
    overall: int
    gp: int
    # Skater fields (optional, present for skaters)
    g: Optional[int] = None
    a: Optional[int] = None
    pts: Optional[int] = None
    ppg: Optional[float] = None
    # Goalie fields (optional, present for goalies)
    wins: Optional[int] = None
    save_pct: Optional[float] = None
    gaa: Optional[float] = None
    shutouts: Optional[int] = None


# ---------------------------------------------------------------------------
# Player summary (for roster views)
# ---------------------------------------------------------------------------
class ContractSummaryDTO(BaseModel):
    """Lightweight contract summary for a roster entry."""
    current_salary: int
    years_remaining: int


class PlayerSummaryDTO(BaseModel):
    """A player entry for roster lists -- id, name, position, ratings, and contract."""
    pid: int
    name: str
    position: str
    age: int
    overall: int
    shoots: str
    secondary_position: Optional[str] = None
    injury_status: Optional[str] = None
    contract: ContractSummaryDTO


class RosterDTO(BaseModel):
    """Full roster for a team with player summaries."""
    players: List[PlayerSummaryDTO]


def player_summary(player: Player) -> PlayerSummaryDTO:
    """Build a :class:`PlayerSummaryDTO` for ``player``. Used by roster endpoints."""
    injury_status = None
    if player.is_injured:
        injury_status = f"{player.injury.description} ({player.injury.games_remaining} games)"

    return PlayerSummaryDTO(
        pid=player.pid,
        name=player.name,
        position=player.position,
        age=player.age,
        overall=player.overall,
        shoots=player.shoots,
        secondary_position=player.secondary_position,
        injury_status=injury_status,
        contract=ContractSummaryDTO(
            current_salary=player.contract.current_salary,
            years_remaining=player.contract.years_remaining,
        ),
    )


# ---------------------------------------------------------------------------
# Lines and pairs with player summaries
# ---------------------------------------------------------------------------
class LineWithPlayersDTO(BaseModel):
    """A forward line with player summaries resolved."""
    players: List[PlayerSummaryDTO]


class PairWithPlayersDTO(BaseModel):
    """A D pair with player summaries resolved."""
    players: List[PlayerSummaryDTO]


class GoalieSlotDTO(BaseModel):
    """A goalie slot (starter or backup) with optional player summary."""
    player: Optional[PlayerSummaryDTO] = None


class SpecialTeamsUnitDTO(BaseModel):
    """A special teams unit (PP/PK) with player summaries resolved."""
    players: List[PlayerSummaryDTO]


class RosterLinesDTO(BaseModel):
    """Forward lines, D pairs, and goalies resolved to player summaries."""
    lines: List[LineWithPlayersDTO]
    pairs: List[PairWithPlayersDTO]
    goalie_starter: GoalieSlotDTO
    goalie_backup: GoalieSlotDTO
    pp_unit_1: SpecialTeamsUnitDTO
    pk_unit_1: SpecialTeamsUnitDTO


def roster_lines_response(team: Team, world: World) -> RosterLinesDTO:
    """Build a :class:`RosterLinesDTO` for ``team``, resolving all ids to player summaries."""
    players_dict = world.players

    # Forward lines
    lines = [
        LineWithPlayersDTO(
            players=[player_summary(players_dict[pid]) for pid in line if pid in players_dict]
        )
        for line in team.lines
    ]

    # D pairs
    pairs = [
        PairWithPlayersDTO(
            players=[player_summary(players_dict[pid]) for pid in pair if pid in players_dict]
        )
        for pair in team.pairs
    ]

    # Goalies
    goalie_starter = GoalieSlotDTO(
        player=player_summary(players_dict[team.goalie_starter])
        if team.goalie_starter is not None and team.goalie_starter in players_dict
        else None
    )
    goalie_backup = GoalieSlotDTO(
        player=player_summary(players_dict[team.goalie_backup])
        if team.goalie_backup is not None and team.goalie_backup in players_dict
        else None
    )

    # Special teams units
    pp_unit_1 = SpecialTeamsUnitDTO(
        players=[player_summary(players_dict[pid]) for pid in team.pp_unit_1 if pid in players_dict]
    )
    pk_unit_1 = SpecialTeamsUnitDTO(
        players=[player_summary(players_dict[pid]) for pid in team.pk_unit_1 if pid in players_dict]
    )

    return RosterLinesDTO(
        lines=lines,
        pairs=pairs,
        goalie_starter=goalie_starter,
        goalie_backup=goalie_backup,
        pp_unit_1=pp_unit_1,
        pk_unit_1=pk_unit_1,
    )


# ---------------------------------------------------------------------------
# Tactics with coach summary
# ---------------------------------------------------------------------------
class TacticsDTO(BaseModel):
    """The team's current tactics settings."""
    forecheck_style: str
    pp_style: str
    pk_aggression: str


class CoachSummaryDTO(BaseModel):
    """Lightweight coach summary for a tactics view."""
    archetype: str
    line_juggling_patience: float
    pp_forwards: int
    shot_volume: float
    shot_quality_bias: float
    defensive_risk_tolerance: float
    goalie_pull_max_deficit: int
    goalie_pull_time_threshold_secs: float


class RosterTacticsDTO(BaseModel):
    """Team tactics and coach profile summary."""
    tactics: TacticsDTO
    coach: CoachSummaryDTO


def roster_tactics_response(team: Team) -> RosterTacticsDTO:
    """Build a :class:`RosterTacticsDTO` for ``team``, including tactics and coach summary."""
    from pucksim.models.coach import profile_for

    # Build tactics DTO, using defaults if None
    tactics_data = team.tactics.to_dict() if team.tactics is not None else {}
    tactics_dto = TacticsDTO(
        forecheck_style=tactics_data.get("forecheck_style", "balanced"),
        pp_style=tactics_data.get("pp_style", "overload"),
        pk_aggression=tactics_data.get("pk_aggression", "balanced"),
    )

    # Build coach DTO from the stored coach dict
    archetype_name = "Balanced"
    if team.coach and isinstance(team.coach, dict):
        archetype_name = team.coach.get("archetype", "Balanced")

    profile = profile_for(archetype_name)
    coach_dto = CoachSummaryDTO(
        archetype=profile.name,
        line_juggling_patience=profile.line_juggling_patience,
        pp_forwards=profile.pp_forwards,
        shot_volume=profile.shot_volume,
        shot_quality_bias=profile.shot_quality_bias,
        defensive_risk_tolerance=profile.defensive_risk_tolerance,
        goalie_pull_max_deficit=profile.goalie_pull_max_deficit,
        goalie_pull_time_threshold_secs=profile.goalie_pull_time_threshold_secs,
    )

    return RosterTacticsDTO(tactics=tactics_dto, coach=coach_dto)


# ---------------------------------------------------------------------------
# Box score DTOs (Step 2.9b-ii)
# ---------------------------------------------------------------------------
# ``pid``/``name``/``position``/``team_id`` (added post-review, ahead of Step 2.10d): the
# raw stat-line fields alone give a frontend no way to label a box-score row -- ``pid`` is
# only available as the *dict key* the router returns these under, and a box score needs to
# show BOTH teams' players, not just the session's own user_team (whose roster the
# 2.9b-i ``/roster`` endpoint already exposes with names). ``routers/season.py``'s
# ``get_boxscore()`` populates these from ``world.players`` at response time -- they are
# never stored in ``World.game_results`` itself (that dict holds only the raw StatLine
# ``to_dict()`` output from Step 2.9b-ii, unchanged), so a player traded away after this
# game was played still resolves correctly (``world.players`` is keyed by pid for the
# player's whole career, independent of current team).
class SkaterBoxScoreDTO(BaseModel):
    """Per-skater box score line."""
    pid: int = 0
    name: str = ""
    position: str = ""
    team_id: Optional[int] = None
    gp: int = 0
    gs: int = 0
    secs: int = 0
    g: int = 0
    a: int = 0
    sog: int = 0
    pim: int = 0
    hits: int = 0
    blocks: int = 0
    giveaways: int = 0
    takeaways: int = 0
    fo_won: int = 0
    fo_lost: int = 0
    plus_minus: int = 0
    corsi_for: int = 0
    corsi_against: int = 0
    fenwick_for: int = 0
    fenwick_against: int = 0


class GoalieBoxScoreDTO(BaseModel):
    """Per-goalie box score line."""
    pid: int = 0
    name: str = ""
    position: str = ""
    team_id: Optional[int] = None
    gp: int = 0
    gs: int = 0
    secs: int = 0
    shots_faced: int = 0
    saves: int = 0
    goals_against: int = 0
    wins: int = 0
    losses: int = 0
    otl: int = 0
    shutouts: int = 0


class GameSummaryDTO(BaseModel):
    """A single game in the schedule."""
    gid: int
    day: int
    home: int
    away: int
    home_score: int
    away_score: int
    played: bool
    is_playoff: bool


def game_summary(game) -> GameSummaryDTO:
    """Build a :class:`GameSummaryDTO` for a scheduled game."""
    from pucksim.models.league import Game
    return GameSummaryDTO(
        gid=game.gid,
        day=game.day,
        home=game.home,
        away=game.away,
        home_score=game.home_score,
        away_score=game.away_score,
        played=game.played,
        is_playoff=game.is_playoff,
    )


def boxscore_response(skater_box, goalie_box) -> tuple:
    """Convert raw stat-line dicts into DTO dicts for a box-score response."""
    return (
        {pid: SkaterBoxScoreDTO(**line) for pid, line in skater_box.items()},
        {pid: GoalieBoxScoreDTO(**line) for pid, line in goalie_box.items()},
    )
