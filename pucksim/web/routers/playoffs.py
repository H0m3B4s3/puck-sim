"""`/playoffs` endpoints: bracket state, playoff start, and slate advancement (DEVPLAN.md Step 2.11 T4).

Sibling to other routers in ``web/routers/`` (see ``web/app.py``'s docstring) -- mounted as
``APIRouter(prefix="/playoffs")`` and included in the main app.

Every route calls through to functions in ``sim/playoffs.py`` (the engine's playoff bracket logic
that was already complete but had no web-layer consumer until now). This router is a thin HTTP
adapter over that surface.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pucksim.models.league import Phase
from pucksim.web.session import get_world, session_store, get_session_id
from pucksim.sim import playoffs

router = APIRouter(prefix="/playoffs", tags=["playoffs"])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
class PlayoffsStateDTO(BaseModel):
    """Shared response for playoff state queries."""
    in_playoffs: bool
    can_start: bool
    bracket: Optional[Dict] = None
    complete: bool
    champion_tid: Optional[int] = None
    champion_name: Optional[str] = None
    champion_abbrev: Optional[str] = None
    champion_color: Optional[str] = None
    round: Optional[str] = None
    round_label: Optional[str] = None


class SlateGameDTO(BaseModel):
    """A single game result in a playoff slate."""
    sid: str
    round: str
    status: str
    home_tid: int
    away_tid: int
    home_abbrev: str
    away_abbrev: str
    home_score: int
    away_score: int
    went_ot: bool
    went_so: bool


class AdvancePlayoffsResponse(BaseModel):
    """Result of advancing one playoff slate."""
    in_playoffs: bool
    can_start: bool
    bracket: Optional[Dict] = None
    complete: bool
    champion_tid: Optional[int] = None
    champion_name: Optional[str] = None
    champion_abbrev: Optional[str] = None
    champion_color: Optional[str] = None
    round: Optional[str] = None
    round_label: Optional[str] = None
    slate: List[SlateGameDTO]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _can_start_playoffs(world) -> bool:
    """Check if playoffs can be started from the current state.

    Can start if:
    - phase is REGULAR_SEASON
    - schedule is non-empty
    - all non-playoff games are played
    - world.bracket is None
    """
    if world.phase != Phase.REGULAR_SEASON:
        return False
    if not world.schedule:
        return False
    # All non-playoff games must be played
    non_playoff_games = [g for g in world.schedule if not g.is_playoff]
    if not all(g.played for g in non_playoff_games):
        return False
    # No bracket yet
    if world.bracket is not None:
        return False
    return True


def _playoffs_state_dto(world) -> PlayoffsStateDTO:
    """Build a PlayoffsStateDTO from the current world state."""
    in_playoffs = world.phase == Phase.PLAYOFFS
    can_start = _can_start_playoffs(world)
    complete = playoffs.playoffs_complete(world)

    champion_tid = None
    champion_name = None
    champion_abbrev = None
    champion_color = None
    round_str = None
    round_label = None
    bracket = None

    if world.bracket:
        bracket = world.bracket
        round_str = world.bracket.get("round")
        if round_str in playoffs.ROUND_LABELS:
            round_label = playoffs.ROUND_LABELS[round_str]

        champ_tid = playoffs.champion(world)
        if champ_tid is not None:
            champion_tid = champ_tid
            champ_team = world.teams.get(champ_tid)
            if champ_team:
                champion_name = champ_team.name
                champion_abbrev = champ_team.abbrev
                champion_color = champ_team.primary_color

    return PlayoffsStateDTO(
        in_playoffs=in_playoffs,
        can_start=can_start,
        bracket=bracket,
        complete=complete,
        champion_tid=champion_tid,
        champion_name=champion_name,
        champion_abbrev=champion_abbrev,
        champion_color=champion_color,
        round=round_str,
        round_label=round_label,
    )


# ---------------------------------------------------------------------------
# GET /playoffs
# ---------------------------------------------------------------------------
@router.get("", response_model=PlayoffsStateDTO)
def get_playoffs(world=Depends(get_world)) -> PlayoffsStateDTO:
    """Return the current playoff state: bracket, round, and completion status.

    Bracket is returned whenever ``world.bracket`` is not None, including in the
    DRAFT phase after the Finals have been won (so the final bracket persists through
    the offseason for viewing).
    """
    return _playoffs_state_dto(world)


# ---------------------------------------------------------------------------
# POST /playoffs/start
# ---------------------------------------------------------------------------
@router.post("/start", response_model=PlayoffsStateDTO)
def start_playoffs_endpoint(
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> PlayoffsStateDTO:
    """Seed the bracket from the finished regular season and enter playoffs.

    Only legal if the regular season is complete and playoffs haven't started yet
    (400 otherwise).
    """
    if not _can_start_playoffs(world):
        raise HTTPException(
            status_code=400,
            detail="Cannot start playoffs: regular season must be complete, schedule non-empty, all non-playoff games played, and no bracket yet",
        )

    playoffs.start_playoffs(world)
    session_store.save(sid, world)

    return _playoffs_state_dto(world)


# ---------------------------------------------------------------------------
# POST /playoffs/advance
# ---------------------------------------------------------------------------
@router.post("/advance", response_model=AdvancePlayoffsResponse)
def advance_playoffs_endpoint(
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> AdvancePlayoffsResponse:
    """Simulate one slate of playoff games (one per active series) and advance the bracket.

    Only legal if in PLAYOFFS phase with an active bracket (400 otherwise).

    Note: The engine automatically sets phase to DRAFT when the Finals resolve, so
    no phase-setting happens in this endpoint.
    """
    if world.phase != Phase.PLAYOFFS or not world.bracket or playoffs.playoffs_complete(world):
        raise HTTPException(
            status_code=400,
            detail="Cannot advance playoffs: must be in PLAYOFFS phase with an active, unfinished bracket",
        )

    # Play one slate of games
    results = playoffs.advance_playoff_slate(world)
    session_store.save(sid, world)

    # Build slate response
    slate = []
    for series_dict, game_result in results:
        home_team = world.teams[game_result.home_tid]
        away_team = world.teams[game_result.away_tid]

        slate.append(SlateGameDTO(
            sid=series_dict["sid"],
            round=series_dict["round"],
            status=playoffs.series_status(world, series_dict),
            home_tid=game_result.home_tid,
            away_tid=game_result.away_tid,
            home_abbrev=home_team.abbrev,
            away_abbrev=away_team.abbrev,
            home_score=game_result.home_score,
            away_score=game_result.away_score,
            went_ot=game_result.went_ot,
            went_so=game_result.went_so,
        ))

    # Build final state
    in_playoffs = world.phase == Phase.PLAYOFFS
    can_start = _can_start_playoffs(world)
    complete = playoffs.playoffs_complete(world)

    champion_tid = None
    champion_name = None
    champion_abbrev = None
    champion_color = None
    round_str = None
    round_label = None
    bracket = None

    if world.bracket:
        bracket = world.bracket
        round_str = world.bracket.get("round")
        if round_str in playoffs.ROUND_LABELS:
            round_label = playoffs.ROUND_LABELS[round_str]

        champ_tid = playoffs.champion(world)
        if champ_tid is not None:
            champion_tid = champ_tid
            champ_team = world.teams.get(champ_tid)
            if champ_team:
                champion_name = champ_team.name
                champion_abbrev = champ_team.abbrev
                champion_color = champ_team.primary_color

    return AdvancePlayoffsResponse(
        in_playoffs=in_playoffs,
        can_start=can_start,
        bracket=bracket,
        complete=complete,
        champion_tid=champion_tid,
        champion_name=champion_name,
        champion_abbrev=champion_abbrev,
        champion_color=champion_color,
        round=round_str,
        round_label=round_label,
        slate=slate,
    )
