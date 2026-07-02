"""``/career`` endpoints: new-career, session fetch, save/load, standings (DEVPLAN.md Step 2.9a).

Deliberately its own small router file, not a monolithic ``app.py`` (see ``web/app.py``'s
docstring) -- later steps add sibling routers (``roster.py``, ``season.py``,
``transactions.py``) rather than growing this one.

Every route here calls straight through to the same engine/gen/save functions the ``testkit``
CLI harness and the pytest suite already exercise (``gen.leaguegen.build_world``,
``save.store.save_game``/``load_game``/``list_saves``, ``models.league.standings``) -- this
router is a thin HTTP adapter over that existing surface, not a second implementation of any of
it, mirroring HoopR's own "each route calls the same engine functions the CLI does" principle
(DEVPLAN.md Step 2.9's HoopR reference note).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from pucksim.config import AUTOSAVE_SLOT
from pucksim.gen.leaguegen import build_world
from pucksim.save import store
from pucksim.web.serializers import StandingsEntryDTO, WorldSummaryDTO, standings_response, world_summary
from pucksim.web.session import (
    get_session_id_optional,
    get_world,
    session_store,
    set_session_cookie,
)

router = APIRouter(prefix="/career", tags=["career"])


# ---------------------------------------------------------------------------
# POST /career/new
# ---------------------------------------------------------------------------
class NewCareerRequest(BaseModel):
    seed: Optional[int] = None
    user_team_abbrev: Optional[str] = None


@router.post("/new", response_model=WorldSummaryDTO)
def new_career(body: NewCareerRequest, response: Response) -> WorldSummaryDTO:
    """Generate a fresh 32-team league (``gen.leaguegen.build_world``), pick the user's team,
    store it as a brand-new session, and set the session cookie on the response.

    ``user_team_abbrev`` is matched case-insensitively against the generated teams' abbrevs; if
    omitted (or unmatched against nothing supplied), the first generated team (lowest ``tid``,
    deterministic given ``seed``) is used as a sensible default so this endpoint never requires
    the caller to already know a generated league's team abbrevs up front.
    """
    world = build_world(seed=body.seed)

    user_team = None
    if body.user_team_abbrev:
        user_team = next(
            (t for t in world.team_list() if t.abbrev.lower() == body.user_team_abbrev.lower()),
            None,
        )
        if user_team is None:
            raise HTTPException(
                status_code=400,
                detail=f"unknown user_team_abbrev {body.user_team_abbrev!r}",
            )
    else:
        user_team = world.team_list()[0]
    world.user_team_id = user_team.tid

    sid = session_store.create(world)
    set_session_cookie(response, sid)
    return world_summary(world)


# ---------------------------------------------------------------------------
# GET /career
# ---------------------------------------------------------------------------
@router.get("", response_model=WorldSummaryDTO)
def get_career(world=Depends(get_world)) -> WorldSummaryDTO:
    return world_summary(world)


# ---------------------------------------------------------------------------
# POST /career/save
# ---------------------------------------------------------------------------
class SaveRequest(BaseModel):
    slot: Optional[str] = None


class SaveResponse(BaseModel):
    slot: str
    path: str


@router.post("/save", response_model=SaveResponse)
def save_career(body: SaveRequest, world=Depends(get_world)) -> SaveResponse:
    slot = body.slot or AUTOSAVE_SLOT
    path = store.save_game(world, slot)
    return SaveResponse(slot=slot, path=path)


# ---------------------------------------------------------------------------
# POST /career/load
# ---------------------------------------------------------------------------
class LoadRequest(BaseModel):
    slot: str


@router.post("/load", response_model=WorldSummaryDTO)
def load_career(
    body: LoadRequest,
    response: Response,
    sid: Optional[str] = Depends(get_session_id_optional),
) -> WorldSummaryDTO:
    """Load ``slot`` (``save.store.load_game``) and make it the active session's World.

    Judgment call: this works whether or not a session cookie already exists. If one does, the
    existing session is overwritten in place (the common "load a different save mid-session"
    case). If not (e.g. loading a save as the very first action of a fresh browser session, with
    no prior ``POST /career/new`` call), a brand-new session is created and its cookie set --
    same "creates one if absent" cookie behavior ``POST /career/new`` gets, so a client never has
    to call ``/career/new`` just to get a cookie before it can load a save.
    """
    if not store.exists(body.slot):
        raise HTTPException(status_code=404, detail=f"no save found in slot {body.slot!r}")
    world = store.load_game(body.slot)

    if sid is None:
        sid = session_store.create(world)
    else:
        session_store.save(sid, world)
    set_session_cookie(response, sid)
    return world_summary(world)


# ---------------------------------------------------------------------------
# GET /career/saves
# ---------------------------------------------------------------------------
@router.get("/saves", response_model=List[str])
def get_saves() -> List[str]:
    return store.list_saves()


# ---------------------------------------------------------------------------
# GET /career/standings
# ---------------------------------------------------------------------------
@router.get("/standings", response_model=List[StandingsEntryDTO])
def get_standings(world=Depends(get_world)) -> List[StandingsEntryDTO]:
    return standings_response(world)
