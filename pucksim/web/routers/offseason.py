"""``/offseason`` endpoints: staged offseason (pre-draft → draft room → tiered FA waves → finish).

Thin HTTP adapter over existing domain systems (``systems/offseason.py``,
``systems/draft_system.py``, ``systems/freeagency.py``, ``sim/playoffs.py``).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pucksim.models.league import Phase
from pucksim.sim.playoffs import champion
from pucksim.systems import draft_system, freeagency, offseason, prospects
from pucksim.web.session import get_session_id, get_world, session_store

router = APIRouter(prefix="/offseason", tags=["offseason"])


# ---------------------------------------------------------------------------
# Request/Response DTOs (defined in this module per PARITY_PLAN.md collision rules)
# ---------------------------------------------------------------------------
class OffseasonPreDraftResponse(BaseModel):
    """Response from POST /offseason/pre-draft"""
    resumed: bool
    retired: int
    new_fas: int
    inducted: List[dict]
    milestones: List[dict]
    champion_tid: Optional[int] = None
    champion_name: str = ""
    awards: Optional[dict] = None


class DraftBoardProspect(BaseModel):
    """A prospect on the draft board"""
    pid: int
    name: str
    position: str
    age: int
    overall: int
    potential: int


class DraftBoardResponse(BaseModel):
    """Response from GET /offseason/draft/board"""
    complete: bool
    pick: Optional[int] = None  # 1-based pick number
    round: Optional[int] = None
    recent: List[dict]  # Recent AI picks: {pick, team_abbrev, name, position, overall}
    board: List[DraftBoardProspect]


class DraftPickRequest(BaseModel):
    """Request body for POST /offseason/draft/pick"""
    prospect_id: Optional[int] = None


class DraftPickResponse(BaseModel):
    """Response from POST /offseason/draft/pick"""
    pick: int  # 1-based pick number
    pid: int
    name: str
    position: str
    overall: int
    potential: int
    signed: bool


class FAWaveDTO(BaseModel):
    """Free agency wave state"""
    active: bool
    wave: int  # 1-based (wave 1 is the first wave)
    total: int  # total number of waves
    name: str


class FAAdvanceResponse(BaseModel):
    """Response from POST /offseason/fa/advance"""
    signings: int
    done: bool
    next: Optional[FAWaveDTO] = None


# ---------------------------------------------------------------------------
# POST /offseason/pre-draft
# ---------------------------------------------------------------------------
@router.post("/pre-draft", response_model=OffseasonPreDraftResponse)
def pre_draft_handler(
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> OffseasonPreDraftResponse:
    """Initialize the draft: archive the season, age/retire players, generate prospect pool.

    Idempotency guard: if world.draft_class is not None, return resumed: True (pre_draft
    must never run twice on the same World, as it ages/retires/expires players).

    Requires Phase.DRAFT (playoffs must be complete).
    """

    if world.draft_class is not None:
        # Draft already initialized -- this is a resume, not a fresh pre_draft
        return OffseasonPreDraftResponse(
            resumed=True, retired=0, new_fas=0, inducted=[], milestones=[],
            champion_tid=None, champion_name="", awards=None
        )

    if world.phase != Phase.DRAFT:
        raise HTTPException(
            status_code=409,
            detail="Playoffs are not complete."
        )

    # Get champion from the bracket
    champ_tid = champion(world)

    # Run pre_draft (archive, age/retire, expire contracts)
    summary = offseason.pre_draft(world, champ_tid)

    # Setup the draft (generate prospects, create DraftClass)
    draft_system.setup_draft(world)

    # Save the world
    session_store.save(sid, world)

    # Get awards from history (if available)
    awards_dict = None
    if world.history:
        awards_dict = world.history[-1].get("awards")

    # Build the response
    champ_name = ""
    if champ_tid is not None and champ_tid in world.teams:
        champ_name = world.teams[champ_tid].name

    return OffseasonPreDraftResponse(
        resumed=False,
        retired=summary.get("retired", 0),
        new_fas=summary.get("new_fas", 0),
        inducted=summary.get("inducted", []),
        milestones=summary.get("milestones", []),
        champion_tid=champ_tid,
        champion_name=champ_name,
        awards=awards_dict,
    )


# ---------------------------------------------------------------------------
# GET /offseason/draft/board
# ---------------------------------------------------------------------------
@router.get("/draft/board", response_model=DraftBoardResponse)
def get_draft_board(
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> DraftBoardResponse:
    """Get the current draft board state with auto-advance loop for AI teams.

    Auto-advances AI picks until it's the user's turn or the draft is complete.
    Returns the board for the current turn (if not complete) and recent AI picks.
    """

    if world.draft_class is None:
        raise HTTPException(status_code=409, detail="No active draft class.")

    dc = world.draft_class
    recent = []

    # Auto-advance loop: run AI picks until it's the user's turn or draft is complete
    while not dc.complete and dc.team_on_clock() != world.user_team_id:
        pick_no = dc.current_pick + 1  # 1-based
        on_clock_tid = dc.team_on_clock()
        team = world.teams.get(on_clock_tid)

        pid = draft_system.ai_pick(world)
        player = world.players[pid]

        recent.append({
            "pick": pick_no,
            "team_abbrev": team.abbrev if team else "?",
            "name": player.name,
            "position": player.position,
            "overall": player.overall,
        })

    # Check if draft is complete
    if dc.complete:
        # Move remaining prospects to free agency, enforce roster max
        draft_system.undrafted_to_free_agency(world)
        offseason.enforce_roster_max(world)
        # Graduate everyone whose rating says they belong, mirroring headless
        # `offseason.run_offseason`'s ordering exactly (after the draft and roster-max
        # enforcement, before free agency) so a team fills holes from its own system first.
        # Not excluded for the user's team: every other pre-free-agency step here
        # (aging, contract expiry, entry-level signings) already runs for all 32 teams,
        # and leaving the user's ready prospects stranded in the minors with no UI to
        # promote them would be worse than promoting them automatically.
        prospects.promote_ready_prospects(world)
        world.phase = Phase.FREE_AGENCY
        session_store.save(sid, world)

        return DraftBoardResponse(
            complete=True,
            pick=None,
            round=None,
            recent=recent,
            board=[],
        )

    # Draft is not complete and it's the user's turn
    session_store.save(sid, world)

    pick_number = dc.current_pick + 1  # 1-based
    round_number = (pick_number - 1) // len(world.teams) + 1

    board = draft_system.draft_board(world)[:60]
    board_dto = [
        DraftBoardProspect(
            pid=p.pid,
            name=p.name,
            position=p.position,
            age=p.age,
            overall=p.overall,
            potential=p.scouted_potential(),
        )
        for p in board
    ]

    return DraftBoardResponse(
        complete=False,
        pick=pick_number,
        round=round_number,
        recent=recent,
        board=board_dto,
    )


# ---------------------------------------------------------------------------
# POST /offseason/draft/pick
# ---------------------------------------------------------------------------
@router.post("/draft/pick", response_model=DraftPickResponse)
def make_draft_pick(
    body: DraftPickRequest,
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> DraftPickResponse:
    """Record the user's draft pick.

    Requires the user team to be on the clock.
    """

    if world.draft_class is None:
        raise HTTPException(status_code=409, detail="No active draft class.")

    dc = world.draft_class
    if dc.complete:
        raise HTTPException(status_code=409, detail="Draft is already complete.")

    if dc.team_on_clock() != world.user_team_id:
        raise HTTPException(status_code=409, detail="Your team is not on the clock.")

    # Get the prospect ID (use best available if not specified)
    prospect_id = body.prospect_id
    if prospect_id is None:
        prospect_id = draft_system.best_available(world)

    # Make the pick
    try:
        signed = draft_system.make_pick(world, prospect_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    prospect = world.players[prospect_id]

    # The pick was already advanced by make_pick's record_pick() call
    pick_number = dc.current_pick  # This is now the next pick, so the one we just made was current_pick-1

    session_store.save(sid, world)

    return DraftPickResponse(
        pick=pick_number,
        pid=prospect.pid,
        name=prospect.name,
        position=prospect.position,
        overall=prospect.overall,
        potential=prospect.scouted_potential(),
        signed=signed,
    )


# ---------------------------------------------------------------------------
# POST /offseason/fa/start
# ---------------------------------------------------------------------------
@router.post("/fa/start", response_model=FAWaveDTO)
def fa_start(
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> FAWaveDTO:
    """Start the free agency market at wave 1.

    Requires Phase.FREE_AGENCY.
    """

    if world.phase != Phase.FREE_AGENCY:
        raise HTTPException(status_code=400, detail="Not in free agency phase.")

    # Enforce roster max before starting FA
    offseason.enforce_roster_max(world)

    # Start the market if not already started
    if getattr(world, "fa_wave", None) is None:
        freeagency.start_fa_market(world)

    session_store.save(sid, world)

    wave_num = world.fa_wave + 1  # fa_wave is 0-based internally, display as 1-based
    wave_name = freeagency.FA_WAVE_NAMES[world.fa_wave]

    return FAWaveDTO(
        active=True,
        wave=wave_num,
        total=freeagency.NUM_FA_WAVES,
        name=wave_name,
    )


# ---------------------------------------------------------------------------
# POST /offseason/fa/advance
# ---------------------------------------------------------------------------
@router.post("/fa/advance", response_model=FAAdvanceResponse)
def fa_advance(
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> FAAdvanceResponse:
    """Run the current free agency wave with AI teams, then advance to the next wave.

    AI never signs players onto the user's roster (exclude_tid=world.user_team_id).
    Requires Phase.FREE_AGENCY.
    """

    if world.phase != Phase.FREE_AGENCY:
        raise HTTPException(status_code=400, detail="Not in free agency phase.")

    # Start the market if not already started
    if getattr(world, "fa_wave", None) is None:
        offseason.enforce_roster_max(world)
        freeagency.start_fa_market(world)

    # Run the current wave (exclude user team)
    result = freeagency.run_fa_wave(world, exclude_tid=world.user_team_id)
    signings = result.get("signings", 0)

    # Advance to the next wave
    more = freeagency.advance_fa_wave(world)

    session_store.save(sid, world)

    # Build response
    next_wave = None
    if more:
        wave_num = world.fa_wave + 1  # 1-based
        wave_name = freeagency.FA_WAVE_NAMES[world.fa_wave]
        next_wave = FAWaveDTO(
            active=True,
            wave=wave_num,
            total=freeagency.NUM_FA_WAVES,
            name=wave_name,
        )

    return FAAdvanceResponse(
        signings=signings,
        done=not more,
        next=next_wave,
    )


# ---------------------------------------------------------------------------
# POST /offseason/finish
# ---------------------------------------------------------------------------
@router.post("/finish")
def finish_offseason(
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
):
    """Finish the offseason: fill rosters, cull FAs, grow cap, start the new season.

    Requires Phase.FREE_AGENCY.
    """
    from pucksim.web.serializers import world_summary

    if world.phase != Phase.FREE_AGENCY:
        raise HTTPException(status_code=400, detail="Not in free agency phase.")

    # Run post_offseason (fill rosters, cull FAs, grow cap, start new season)
    offseason.post_offseason(world)

    session_store.save(sid, world)

    return world_summary(world)
