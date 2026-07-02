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


def world_summary(world: World) -> WorldSummaryDTO:
    return WorldSummaryDTO(
        season_year=world.season_year,
        phase=world.phase,
        day=world.day,
        standings_rule=world.standings_rule,
        user_team_id=world.user_team_id,
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
                **base.model_dump(exclude={"record"}),
                points=_team_points(world, team),
                wins=team.wins,
                losses=team.losses,
                ot_losses=team.ot_losses,
            )
        )
    return out


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
