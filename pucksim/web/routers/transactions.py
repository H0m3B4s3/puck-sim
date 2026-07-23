"""``/transactions`` endpoints: cap, trades, free agents, draft, and awards (DEVPLAN.md Step 2.9b-iii).

Thin HTTP adapter over existing domain systems (``systems/cap.py``, ``systems/trades.py``,
``systems/freeagency.py``, ``systems/draft_system.py``, ``systems/awards.py``, ``systems/legacy.py``).
Every route calls straight through to the same engine functions the ``testkit`` CLI harness
and pytest suite already exercise, mirroring HoopR's "each route calls the same engine
functions as the CLI does" principle (DEVPLAN.md Step 2.9's HoopR reference note).

All roster mutations (trades, FA signings, draft picks) go through ``World.sign_player``/
``release_player``/``transfer_player`` per DEVPLAN.md's hard constraint -- never direct
``Team.roster``/``Player.team_id`` manipulation.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pucksim.models.world import World
from pucksim.systems import awards, cap, draft_system, freeagency, trades
from pucksim.systems.prospects import is_reserved_prospect
from pucksim.web.serializers import (
    CapSummaryDTO,
    DraftBoardDTO,
    TradeResponseDTO,
    TransactionPlayerSummaryDTO,
    cap_summary,
    draft_board_dto,
)
from pucksim.web.session import get_session_id, get_world, session_store

router = APIRouter(prefix="/transactions", tags=["transactions"])


# ---------------------------------------------------------------------------
# GET /transactions/cap
# ---------------------------------------------------------------------------
@router.get("/cap", response_model=CapSummaryDTO)
def get_cap_summary(world=Depends(get_world)) -> CapSummaryDTO:
    """The user's team's payroll, cap space, and cap-related summary via ``systems/cap.py``."""
    user_team = world.teams.get(world.user_team_id)
    if user_team is None:
        raise HTTPException(status_code=404, detail="No user team set.")
    return cap_summary(world, user_team)


# ---------------------------------------------------------------------------
# POST /transactions/trades/propose
# ---------------------------------------------------------------------------
class TradeOfferRequest(BaseModel):
    other_team_id: int
    user_sends: List[int] = []  # player ids
    user_receives: List[int] = []  # player ids


class TradeValidationResponse(BaseModel):
    legal: bool
    legal_reason: str
    accepts: bool
    ai_reason: str


@router.post("/trades/propose", response_model=TradeResponseDTO)
def propose_trade(
    body: TradeOfferRequest,
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> TradeResponseDTO:
    """Propose a trade between the user's team and another team. Request body specifies
    which players each side sends. Response indicates accepted/rejected and, if accepted,
    a summary of both teams' roster changes.
    """
    user_team = world.teams.get(world.user_team_id)
    if user_team is None:
        raise HTTPException(status_code=404, detail="No user team set.")

    offer = trades.TradeOffer(
        a=user_team.tid,
        b=body.other_team_id,
        a_sends=body.user_sends,
        b_sends=body.user_receives,
    )

    ok, reason = trades.propose_trade(world, offer)
    if not ok:
        return TradeResponseDTO(accepted=False, reason=reason)

    # Trade was accepted - persist and return details
    session_store.save(sid, world)
    return TradeResponseDTO(accepted=True, reason=reason)


# ---------------------------------------------------------------------------
# POST /transactions/trades/validate
# ---------------------------------------------------------------------------
@router.post("/trades/validate", response_model=TradeValidationResponse)
def validate_trade(
    body: TradeOfferRequest,
    world=Depends(get_world),
) -> TradeValidationResponse:
    """Validate a trade offer without executing it (pure read).

    Checks legality (cap, roster, no-trade clauses) and AI acceptance threshold.
    Does not save the world.
    """
    user_team = world.teams.get(world.user_team_id)
    if user_team is None:
        raise HTTPException(status_code=404, detail="No user team set.")

    offer = trades.TradeOffer(
        a=user_team.tid,
        b=body.other_team_id,
        a_sends=body.user_sends,
        b_sends=body.user_receives,
    )

    legal, legal_why = trades.validate_trade(world, offer)
    accepts = False
    ai_why = "Trade is not legal."

    if legal:
        accepts, ai_why = trades.ai_evaluates(world, offer, body.other_team_id)

    return TradeValidationResponse(
        legal=legal,
        legal_reason=legal_why,
        accepts=accepts,
        ai_reason=ai_why,
    )


# ---------------------------------------------------------------------------
# POST /transactions/trades/execute
# ---------------------------------------------------------------------------
class TradeExecuteResponse(BaseModel):
    executed: bool
    reason: str


@router.post("/trades/execute", response_model=TradeExecuteResponse)
def execute_trade(
    body: TradeOfferRequest,
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> TradeExecuteResponse:
    """Validate and execute a trade if both legal and AI-accepted.

    Returns {executed: true/false, reason: explanation}.
    """
    user_team = world.teams.get(world.user_team_id)
    if user_team is None:
        raise HTTPException(status_code=404, detail="No user team set.")

    offer = trades.TradeOffer(
        a=user_team.tid,
        b=body.other_team_id,
        a_sends=body.user_sends,
        b_sends=body.user_receives,
    )

    # Validate legality
    legal, legal_why = trades.validate_trade(world, offer)
    if not legal:
        raise HTTPException(status_code=400, detail=legal_why)

    # Evaluate AI acceptance
    accepts, ai_why = trades.ai_evaluates(world, offer, body.other_team_id)
    if not accepts:
        return TradeExecuteResponse(executed=False, reason=ai_why)

    # Execute the trade
    trades.execute_trade(world, offer)
    session_store.save(sid, world)

    return TradeExecuteResponse(executed=True, reason="Trade completed.")


# ---------------------------------------------------------------------------
# GET /transactions/freeagents
# ---------------------------------------------------------------------------
@router.get("/freeagents", response_model=List[TransactionPlayerSummaryDTO])
def get_free_agents(world=Depends(get_world)) -> List[TransactionPlayerSummaryDTO]:
    """Current free-agent board with lightweight player summaries.

    Includes wave-adjusted ask (market salary) and preferred contract years when
    in the offseason FA market (fa_wave is set), otherwise uses full market salary.
    """
    # Use wave pool when in offseason, otherwise all FAs. Either way reserved prospects
    # (systems/prospects.py) are excluded -- they're developing, not on the market, and
    # listing a few hundred unsignable teenagers would swamp the board.
    if getattr(world, "fa_wave", None) is not None:
        fa_players = freeagency.fa_wave_pool(world)
    else:
        fa_players = [p for p in world.free_agent_players()
                      if not is_reserved_prospect(p, world.season_year)]
        # Sort by overall (highest first) to match draft board behavior
        fa_players = sorted(fa_players, key=lambda p: p.overall, reverse=True)

    return [
        TransactionPlayerSummaryDTO(
            pid=p.pid,
            name=p.name,
            position=p.position,
            age=p.age,
            overall=p.overall,
            team_id=p.team_id,
            ask=freeagency.wave_market_salary(world, p),
            preferred_years=freeagency.contract_years_for(p),
        )
        for p in fa_players
    ]


# ---------------------------------------------------------------------------
# POST /transactions/freeagents/{pid}/sign
# ---------------------------------------------------------------------------
class SignFreeAgentRequest(BaseModel):
    salary: Optional[int] = None
    years: Optional[int] = None


@router.post("/freeagents/{pid}/sign", response_model=dict)
def sign_free_agent(
    pid: int,
    body: SignFreeAgentRequest,
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> dict:
    """Sign a free agent to the user's team with contract terms.
    If salary/years not provided, uses market defaults.
    """
    user_team = world.teams.get(world.user_team_id)
    if user_team is None:
        raise HTTPException(status_code=404, detail="No user team set.")

    player = world.players.get(pid)
    if player is None:
        raise HTTPException(status_code=404, detail="Player not found.")
    if not player.is_free_agent:
        raise HTTPException(status_code=400, detail="Player is not a free agent.")

    # Use provided salary or market default
    salary = body.salary if body.salary is not None else freeagency.wave_market_salary(world, player)
    years = body.years if body.years is not None else freeagency.contract_years_for(player)

    ok, reason = freeagency.sign_free_agent(world, user_team, pid, salary, years)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    # Persist the world back to session
    session_store.save(sid, world)
    return {"success": True, "message": reason}


# ---------------------------------------------------------------------------
# GET /draft/board
# ---------------------------------------------------------------------------
@router.get("/draft/board", response_model=DraftBoardDTO)
def get_draft_board(world=Depends(get_world)) -> DraftBoardDTO:
    """Current draft order and prospect pool. Only meaningful when in draft phase;
    returns empty board otherwise."""
    return draft_board_dto(world)


# ---------------------------------------------------------------------------
# POST /transactions/draft/pick
# ---------------------------------------------------------------------------
class DraftPickRequest(BaseModel):
    prospect_id: int


@router.post("/draft/pick", response_model=dict)
def make_draft_pick(
    body: DraftPickRequest,
    world=Depends(get_world),
    sid: str = Depends(get_session_id),
) -> dict:
    """Make the on-the-clock pick for the user's team. Only legal if the user's team
    is actually on the clock."""
    if world.draft_class is None:
        raise HTTPException(status_code=400, detail="No active draft.")

    on_clock = world.draft_class.team_on_clock()
    if on_clock != world.user_team_id:
        raise HTTPException(
            status_code=403,
            detail=f"Your team is not on the clock (currently: {on_clock}).",
        )

    try:
        signed = draft_system.make_pick(world, body.prospect_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    prospect = world.players[body.prospect_id]
    session_store.save(sid, world)
    return {
        "prospect_id": body.prospect_id,
        "prospect_name": prospect.name,
        "signed": signed,
        "message": "Pick recorded." if not signed else "Pick recorded and signed.",
    }


# ---------------------------------------------------------------------------
# GET /transactions/awards
# ---------------------------------------------------------------------------
@router.get("/awards", response_model=dict)
def get_awards(world=Depends(get_world)) -> dict:
    """End-of-season awards/legacy view for the most recently completed season.

    Only meaningful once a season has actually completed; empty dict otherwise. NOTE: awards
    aren't archived to ``world.history`` anywhere yet (that's ``systems/offseason.py``'s job,
    out of this step's scope), so this computes live from current-season stats rather than
    reading an archived result -- a real "most recently completed season" view for a career
    that's already moved past FREE_AGENCY into a new season would need that archival wired up
    first. ``compute_awards()`` itself already returns an empty dict of award keys (never
    raises) when no candidate has played enough games yet -- see its docstring -- so no
    try/except is needed here; wrapping it would only risk silently swallowing a real bug.
    """
    from pucksim.models.league import Phase

    if world.phase not in (Phase.REGULAR_SEASON, Phase.PLAYOFFS, Phase.DRAFT, Phase.FREE_AGENCY):
        return {"season_year": world.season_year, "awards": {}}

    return {"season_year": world.season_year, "awards": awards.compute_awards(world)}
