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
