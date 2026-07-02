"""`/season` endpoints: schedule, day advancement, game simulation, box scores, and
playoffs bracket (DEVPLAN.md Step 2.9b-ii).

Sibling to ``career.py`` (see ``web/app.py``'s docstring) -- mounted as ``APIRouter(prefix="/season")``
and included in the main app.

Every route here calls straight through to the same engine/sim functions the ``testkit``
CLI harness and the pytest suite already exercise (``sim.season.advance_one_day``,
``sim.engine.simulate_game``, ``sim/playoffs.py`` bracket logic) -- this router is a thin
HTTP adapter over that existing surface (see ``routers/career.py``'s docstring for the
full "each route calls the same engine functions" principle).

Box-score persistence (DEVPLAN.md Step 2.9b-ii): ``World.game_results: Dict[int, dict]`` is
an additive field that stores per-game box scores. Both ``advance_one_day`` (in ``sim/season.py``)
and the ``POST /season/games/{gid}/sim`` endpoint populate it. The ``GET /season/games/{gid}/boxscore``
endpoint reads from this dict.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pucksim.models.league import Phase
from pucksim.web.serializers import SkaterBoxScoreDTO, GoalieBoxScoreDTO, WorldSummaryDTO, world_summary
from pucksim.web.session import get_world, session_store, get_session_id
from pucksim.sim.season import advance_one_day, sim_one, start_season

router = APIRouter(prefix="/season", tags=["season"])


# ---------------------------------------------------------------------------
# POST /season/start
# ---------------------------------------------------------------------------
@router.post("/start", response_model=WorldSummaryDTO)
def start(
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> WorldSummaryDTO:
    """Generate the regular-season schedule and move the career out of preseason.

    Found missing during Step 2.9b-ii review: none of this router's other endpoints
    (``GET /season/schedule``, ``POST /season/advance-day``) do anything useful on a
    freshly created career -- ``World.schedule`` is empty and ``World.phase`` stays
    "preseason" until ``sim.season.start_season()`` runs, but nothing in the web layer
    called it. Every existing test reached around this gap by calling ``start_season()``
    directly against the session's ``World`` rather than through an endpoint (see the
    ``/season/*`` tests in ``tests/test_web.py``) -- a real client (the future frontend)
    has no such backdoor, so this endpoint is required for the API to be usable at all,
    not an optional nicety. Only legal from preseason -- 400 if the season has already
    been started (this is a one-shot transition, not an idempotent reset).
    """
    if world.phase != Phase.PRESEASON:
        raise HTTPException(
            status_code=400,
            detail=f"season already started (phase={world.phase!r}); this is a one-time preseason-only transition",
        )
    start_season(world)
    session_store.save(sid, world)
    return world_summary(world)


# ---------------------------------------------------------------------------
# GET /season/schedule
# ---------------------------------------------------------------------------
class GameDTO(BaseModel):
    """A single game in the schedule."""
    gid: int
    day: int
    home: int
    away: int
    home_score: int
    away_score: int
    played: bool
    is_playoff: bool


@router.get("/schedule", response_model=List[GameDTO])
def get_schedule(world=Depends(get_world)) -> List[GameDTO]:
    """Return all games in the season schedule.

    Currently returns the entire schedule. A future pass might add ``?team_id=`` filtering
    to return just one team's games.
    """
    return [
        GameDTO(
            gid=g.gid,
            day=g.day,
            home=g.home,
            away=g.away,
            home_score=g.home_score,
            away_score=g.away_score,
            played=g.played,
            is_playoff=g.is_playoff,
        )
        for g in world.schedule
    ]


# ---------------------------------------------------------------------------
# POST /season/advance-day
# ---------------------------------------------------------------------------
class GamePlayedDTO(BaseModel):
    """Summary of a game played during the day."""
    gid: int
    home: int
    away: int
    home_score: int
    away_score: int


class AdvanceDayResponse(BaseModel):
    """Result of advancing one game day."""
    day: int
    phase: str
    games_played: List[GamePlayedDTO]


@router.post("/advance-day", response_model=AdvanceDayResponse)
def advance_day(
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> AdvanceDayResponse:
    """Simulate all games scheduled for today, advance the day, and persist the World back to
    the session.

    Returns the new day/phase and a summary of each game played today.
    """
    games_played = advance_one_day(world)
    session_store.save(sid, world)

    return AdvanceDayResponse(
        day=world.day,
        phase=world.phase,
        games_played=[
            GamePlayedDTO(
                gid=g.gid,
                home=g.home,
                away=g.away,
                home_score=g.home_score,
                away_score=g.away_score,
            )
            for g in games_played
        ],
    )


# ---------------------------------------------------------------------------
# POST /season/games/{gid}/sim
# ---------------------------------------------------------------------------
class SimGameResponse(BaseModel):
    """Result of simulating a single game."""
    gid: int
    home_score: int
    away_score: int
    went_ot: bool
    went_so: bool


@router.post("/games/{gid}/sim", response_model=SimGameResponse)
def sim_game(
    gid: int,
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> SimGameResponse:
    """Simulate a single scheduled game on demand.

    The game must be scheduled and not yet played. Delegates to ``sim.season.sim_one()`` --
    the same function ``advance_one_day()`` calls per game -- rather than calling
    ``sim.engine.simulate_game()`` directly, so this endpoint gets the exact same
    goalie rest-based rotation (Step 2.2's ``_choose_and_record_starter``) and
    ``_apply_result()`` bookkeeping (team win/loss/streak via ``Team.record_result()``,
    season stat-line accumulation, in-game injuries) that every other simulated game in
    this codebase goes through. An earlier version of this endpoint reimplemented a
    partial subset of ``_apply_result()`` inline and silently skipped team records and
    injuries -- fixed during review, not a design choice worth re-deriving per endpoint.

    Persists the box score in ``world.game_results`` for later retrieval via
    ``GET /season/games/{gid}/boxscore``.
    """
    # Find the game in the schedule
    game = next((g for g in world.schedule if g.gid == gid), None)
    if game is None:
        raise HTTPException(status_code=404, detail=f"game {gid} not found in schedule")
    if game.played:
        raise HTTPException(status_code=400, detail=f"game {gid} already played")

    # Simulate and fully apply it (record/stats/injuries/goalie-rotation), same as
    # advance_one_day() does per game.
    result = sim_one(world, game)

    # Persist box score for later retrieval (DEVPLAN.md Step 2.9b-ii)
    world.game_results[gid] = {
        'home_score': result.home_score,
        'away_score': result.away_score,
        'went_ot': result.went_ot,
        'went_so': result.went_so,
        'skater_box': {pid: line.to_dict() for pid, line in result.skater_box.items()},
        'goalie_box': {pid: line.to_dict() for pid, line in result.goalie_box.items()},
    }

    # Persist everything back to the session
    session_store.save(sid, world)

    return SimGameResponse(
        gid=gid,
        home_score=result.home_score,
        away_score=result.away_score,
        went_ot=result.went_ot,
        went_so=result.went_so,
    )


# ---------------------------------------------------------------------------
# GET /season/games/{gid}/boxscore
# ---------------------------------------------------------------------------
class BoxScoreResponse(BaseModel):
    """Complete box score for a game."""
    gid: int
    home_score: int
    away_score: int
    went_ot: bool
    went_so: bool
    skater_box: Dict[int, SkaterBoxScoreDTO]
    goalie_box: Dict[int, GoalieBoxScoreDTO]


@router.get("/games/{gid}/boxscore", response_model=BoxScoreResponse)
def get_boxscore(
    gid: int,
    world=Depends(get_world),
) -> BoxScoreResponse:
    """Retrieve the box score for a played game.

    The game must already be played (via ``advance_one_day`` or ``POST /season/games/{gid}/sim``).
    Returns skater and goalie box scores separately (two different shapes, per DESIGN.md point 9).
    """
    # Find the game
    game = next((g for g in world.schedule if g.gid == gid), None)
    if game is None:
        raise HTTPException(status_code=404, detail=f"game {gid} not found in schedule")
    if not game.played:
        raise HTTPException(status_code=400, detail=f"game {gid} not yet played")

    # Look up box score from world.game_results
    skater_box: Dict[int, SkaterBoxScoreDTO] = {}
    goalie_box: Dict[int, GoalieBoxScoreDTO] = {}

    if gid in world.game_results:
        stored = world.game_results[gid]
        # Reconstruct DTOs from stored dicts
        for pid, data in stored.get('skater_box', {}).items():
            skater_box[int(pid)] = SkaterBoxScoreDTO(**data)
        for pid, data in stored.get('goalie_box', {}).items():
            goalie_box[int(pid)] = GoalieBoxScoreDTO(**data)

    return BoxScoreResponse(
        gid=gid,
        home_score=game.home_score,
        away_score=game.away_score,
        went_ot=game.went_ot,
        went_so=game.went_so,
        skater_box=skater_box,
        goalie_box=goalie_box,
    )


# ---------------------------------------------------------------------------
# GET /season/playoffs/bracket
# ---------------------------------------------------------------------------
@router.get("/playoffs/bracket", response_model=Optional[dict])
def get_playoff_bracket(world=Depends(get_world)) -> Optional[dict]:
    """Retrieve the current playoff bracket state, if in the playoffs phase.

    Returns ``None`` if the season hasn't reached the playoffs yet.
    The bracket structure is JSON-native and mirrors ``sim/playoffs.py``'s internal shape.
    """
    if world.phase != "playoffs":
        return None
    return world.bracket
