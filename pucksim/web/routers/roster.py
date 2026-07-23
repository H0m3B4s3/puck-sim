"""``/roster`` endpoints: roster, lines/pairs/units, and tactics (DEVPLAN.md Step 2.9b-i).

Roster management endpoints that expose Team's on-ice-group data structures (lines, pairs,
special-teams units, goalies, tactics) for editing via the web API. Mirrors the career.py
pattern: each endpoint calls straight through to existing domain functions
(team.auto_build_lines, team.auto_build_special_teams_units, Tactics.cycle) rather than
reimplementing logic.

All endpoints require an active session (Depends(get_world)) and operate on the user's team
(world.user_team). Mutations are persisted back to the session store (session_store.save).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from pucksim.config import MAX_CONTRACTS
from pucksim.models.tactics import Tactics, SETTINGS as TACTICS_SETTINGS
from pucksim.models.team import auto_build_lines, auto_build_special_teams_units, Team
from pucksim.systems import prospects
from pucksim.web.serializers import (
    PlayerSummaryDTO,
    ProspectDTO,
    ProspectPoolDTO,
    RosterDTO,
    RosterLinesDTO,
    RosterTacticsDTO,
    TacticsDTO,
    player_summary,
    prospect_dto,
    roster_lines_response,
    roster_tactics_response,
)
from pucksim.web.session import (
    get_session_id,
    get_world,
    session_store,
    SESSION_COOKIE_NAME,
)
from pucksim.models.world import World

router = APIRouter(prefix="/roster", tags=["roster"])


# ---------------------------------------------------------------------------
# GET /roster -- full roster
# ---------------------------------------------------------------------------
@router.get("", response_model=RosterDTO)
def get_roster(world: World = Depends(get_world)) -> RosterDTO:
    """Return the user's team's full roster as player summaries.

    Includes every player on the roster: starters, bench, scratches, injured.
    Each player carries id, name, position, age, overall rating, shoots, contract summary.
    """
    team = world.user_team
    if team is None:
        raise HTTPException(status_code=404, detail="no user team found")

    players = [player_summary(world.players[pid]) for pid in team.roster if pid in world.players]
    return RosterDTO(players=players)


# ---------------------------------------------------------------------------
# GET /roster/lines -- current lines, pairs, units with player summaries
# ---------------------------------------------------------------------------
@router.get("/lines", response_model=RosterLinesDTO)
def get_roster_lines(world: World = Depends(get_world)) -> RosterLinesDTO:
    """Return the user's team's current lines, pairs, and special-teams units.

    Resolves all player ids to lightweight player summaries (id/name/position/overall)
    so a frontend can render full lineups without a second roundtrip.
    """
    team = world.user_team
    if team is None:
        raise HTTPException(status_code=404, detail="no user team found")

    return roster_lines_response(team, world)


# ---------------------------------------------------------------------------
# POST /roster/lines/auto -- auto-build lines and optional special teams
# ---------------------------------------------------------------------------
class AutoBuildLinesRequest(BaseModel):
    """Auto-build request: rebuild lines, optionally rebuild special teams too."""
    include_special_teams: bool = False


@router.post("/lines/auto", response_model=RosterLinesDTO)
def auto_build_lines_post(
    body: AutoBuildLinesRequest,
    world: World = Depends(get_world),
    sid: str = Depends(get_session_id),
) -> RosterLinesDTO:
    """Re-run the auto-line-builder on the user's team.

    Rebuilds forward lines (4 x LW/C/RW), D pairs (3 x 2), and goalie assignments
    by calling team.auto_build_lines(). If include_special_teams=true, also rebuilds
    the power-play and penalty-kill units via auto_build_special_teams_units().

    Returns the updated lines/pairs/units in the same shape as GET /roster/lines,
    and persists the mutation back to the session so the new lineup is live.
    """
    team = world.user_team
    if team is None:
        raise HTTPException(status_code=404, detail="no user team found")

    # Rebuild lines
    auto_build_lines(team, world.players)

    # Optionally rebuild special teams
    if body.include_special_teams:
        # Get the coach's pp_forwards setting if a coach exists
        pp_forwards = 3
        if team.coach and isinstance(team.coach, dict):
            from pucksim.models.coach import profile_for
            archetype_name = team.coach.get("archetype", "Balanced")
            profile = profile_for(archetype_name)
            pp_forwards = profile.pp_forwards
        auto_build_special_teams_units(team, world.players, pp_forwards=pp_forwards)

    # Persist the mutation back to session store
    session_store.save(sid, world)

    return roster_lines_response(team, world)


# ---------------------------------------------------------------------------
# PUT /roster/lines -- manual line editing
# ---------------------------------------------------------------------------
class ManualLinesEditRequest(BaseModel):
    """Request body for manual line/pair/goalie edits."""
    lines: Optional[List[List[int]]] = None
    pairs: Optional[List[List[int]]] = None
    goalie_starter: Optional[int] = None
    goalie_backup: Optional[int] = None


@router.put("/lines", response_model=RosterLinesDTO)
def put_roster_lines(
    body: ManualLinesEditRequest,
    world: World = Depends(get_world),
    sid: str = Depends(get_session_id),
) -> RosterLinesDTO:
    """Manually edit the user's team's lines, pairs, and goalie assignments.

    Request body specifies only the fields to update (partial update). Validates:
    - Every player id must be on the roster
    - No player id can appear in two forward-line slots simultaneously
    - Line/pair structure must be valid (e.g., 4 lines of 3, 3 pairs of 2)

    Does NOT validate position legality (wing vs. center, D on the line) -- that's
    left as a legal, just penalized, fit choice per team.position_fit_score().
    Returns 400 with a clear message on structural/ownership violation.
    """
    team = world.user_team
    if team is None:
        raise HTTPException(status_code=404, detail="no user team found")

    roster_ids = set(team.roster)

    # Validate and apply line edits
    if body.lines is not None:
        # Validate structure: 4 lines, each with 3 players
        if len(body.lines) > 4:
            raise HTTPException(status_code=400, detail="too many lines (max 4)")
        for i, line in enumerate(body.lines):
            if len(line) != 3:
                raise HTTPException(status_code=400, detail=f"line {i} has {len(line)} players, expected 3")
            for pid in line:
                if pid not in roster_ids:
                    raise HTTPException(status_code=400, detail=f"player {pid} not on roster")

        # Check for duplicates across forward-line slots
        all_forward_ids = []
        for line in body.lines:
            all_forward_ids.extend(line)
        if len(all_forward_ids) != len(set(all_forward_ids)):
            raise HTTPException(status_code=400, detail="duplicate player in forward lines")

        team.lines = [list(line) for line in body.lines]

    # Validate and apply pair edits
    if body.pairs is not None:
        # Validate structure: up to 3 pairs, each with 2 players
        if len(body.pairs) > 3:
            raise HTTPException(status_code=400, detail="too many pairs (max 3)")
        for i, pair in enumerate(body.pairs):
            if len(pair) != 2:
                raise HTTPException(status_code=400, detail=f"pair {i} has {len(pair)} players, expected 2")
            for pid in pair:
                if pid not in roster_ids:
                    raise HTTPException(status_code=400, detail=f"player {pid} not on roster")

        # Check for duplicates across D-pair slots
        all_d_ids = []
        for pair in body.pairs:
            all_d_ids.extend(pair)
        if len(all_d_ids) != len(set(all_d_ids)):
            raise HTTPException(status_code=400, detail="duplicate player in D pairs")

        team.pairs = [list(pair) for pair in body.pairs]

    # Validate and apply goalie edits
    if body.goalie_starter is not None:
        if body.goalie_starter not in roster_ids:
            raise HTTPException(status_code=400, detail=f"starter goalie {body.goalie_starter} not on roster")
        team.goalie_starter = body.goalie_starter

    if body.goalie_backup is not None:
        if body.goalie_backup not in roster_ids:
            raise HTTPException(status_code=400, detail=f"backup goalie {body.goalie_backup} not on roster")
        team.goalie_backup = body.goalie_backup

    # Persist the mutation back to session store
    session_store.save(sid, world)

    return roster_lines_response(team, world)


# ---------------------------------------------------------------------------
# GET /roster/tactics -- tactics and coach summary
# ---------------------------------------------------------------------------
@router.get("/tactics", response_model=RosterTacticsDTO)
def get_roster_tactics(world: World = Depends(get_world)) -> RosterTacticsDTO:
    """Return the user's team's tactics board settings and coach profile summary.

    Tactics include forecheck_style, pp_style, and pk_aggression discrete options.
    Coach summary includes the archetype name and behavior-knob values relevant to
    roster management (line_juggling_patience, pp_forwards, shot volume/quality bias, etc.).
    """
    team = world.user_team
    if team is None:
        raise HTTPException(status_code=404, detail="no user team found")

    return roster_tactics_response(team)


# ---------------------------------------------------------------------------
# PUT /roster/tactics -- set tactics (partial update)
# ---------------------------------------------------------------------------
class TacticsUpdateRequest(BaseModel):
    """Request body for updating tactics -- any field can be omitted (partial update)."""
    forecheck_style: Optional[str] = None
    pp_style: Optional[str] = None
    pk_aggression: Optional[str] = None


@router.put("/tactics", response_model=RosterTacticsDTO)
def put_roster_tactics(
    body: TacticsUpdateRequest,
    world: World = Depends(get_world),
    sid: str = Depends(get_session_id),
) -> RosterTacticsDTO:
    """Update the user's team's tactics (partial update -- only supplied fields change).

    Each tactic field accepts one of its legal discrete values (e.g., forecheck_style
    in ["passive", "balanced", "aggressive"]). Invalid values return 400.

    This does NOT cycle to the next option -- it sets the value directly. Use this
    for API-driven tactics setting; a UI that cycles options should call this endpoint
    with the next option value, not with a separate cycle-direction parameter.
    """
    team = world.user_team
    if team is None:
        raise HTTPException(status_code=404, detail="no user team found")

    # Ensure we have a Tactics instance (shouldn't be None, but guard it)
    if team.tactics is None:
        team.tactics = Tactics()

    # Validate and apply each field
    if body.forecheck_style is not None:
        valid = TACTICS_SETTINGS.get("forecheck_style", ())
        if body.forecheck_style not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"invalid forecheck_style {body.forecheck_style!r}, expected one of {valid}",
            )
        team.tactics.forecheck_style = body.forecheck_style

    if body.pp_style is not None:
        valid = TACTICS_SETTINGS.get("pp_style", ())
        if body.pp_style not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"invalid pp_style {body.pp_style!r}, expected one of {valid}",
            )
        team.tactics.pp_style = body.pp_style

    if body.pk_aggression is not None:
        valid = TACTICS_SETTINGS.get("pk_aggression", ())
        if body.pk_aggression not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"invalid pk_aggression {body.pk_aggression!r}, expected one of {valid}",
            )
        team.tactics.pk_aggression = body.pk_aggression

    # Persist the mutation back to session store
    session_store.save(sid, world)

    return roster_tactics_response(team)


# ---------------------------------------------------------------------------
# GET /roster/prospects -- the user's development system
# ---------------------------------------------------------------------------
# Placed BEFORE the /{tid} route below for the same reason /lines and /tactics are: a
# parameterized route would otherwise swallow the literal one.
@router.get("/prospects", response_model=ProspectPoolDTO)
def get_prospects(world: World = Depends(get_world)) -> ProspectPoolDTO:
    """The user team's reserve list: everyone developing in junior, college, the AHL or
    Europe whose rights it holds.

    Derived rather than stored -- see ``systems/prospects.team_prospects`` for why there is
    no ``Team.prospects`` list to keep in sync. Also reports the team's professional
    contract count against ``config.MAX_CONTRACTS``, since entry-level deals cost no cap
    space and the contract limit is the only thing that pushes back on signing everyone.
    """
    team = world.user_team
    if team is None:
        raise HTTPException(status_code=404, detail="no user team found")

    pool = prospects.team_prospects(world, team.tid)
    return ProspectPoolDTO(
        prospects=[prospect_dto(world, p) for p in pool],
        contracts_used=prospects.contracts_held(world, team.tid),
        contracts_max=MAX_CONTRACTS,
    )


class SignProspectResponse(BaseModel):
    """Result of an entry-level signing attempt."""
    ok: bool
    message: str
    prospect: Optional[ProspectDTO] = None


@router.post("/prospects/{pid}/sign", response_model=SignProspectResponse)
def sign_prospect(
    pid: int,
    world: World = Depends(get_world),
    sid: str = Depends(get_session_id),
) -> SignProspectResponse:
    """Sign one of the user team's prospects to an entry-level contract.

    He does NOT join the NHL roster -- he stays where he is developing, now under
    contract. That is the real mechanic: sign your 18-year-old first-rounder, send him back
    to junior, and the deal slides instead of burning (``systems/prospects.tick_contract``).
    Signing is also what unlocks the AHL, since a professional league needs a professional
    contract, so an unsigned junior graduate has nowhere left to go.

    Failures (wrong team, already signed, too old for entry level, at the 50-contract limit)
    come back as ``ok: false`` with the reason rather than as an HTTP error -- they're
    ordinary game states a manager needs to read, not exceptional conditions.
    """
    team = world.user_team
    if team is None:
        raise HTTPException(status_code=404, detail="no user team found")

    ok, message = prospects.sign_elc(world, team.tid, pid)
    if ok:
        session_store.save(sid, world)
    player = world.players.get(pid)
    return SignProspectResponse(
        ok=ok,
        message=message,
        prospect=prospect_dto(world, player) if player is not None and player.is_prospect
        else None,
    )


# ---------------------------------------------------------------------------
# GET /roster/{tid} -- any team's roster
# ---------------------------------------------------------------------------
@router.get("/{tid}", response_model=RosterDTO)
def get_team_roster(tid: int, world: World = Depends(get_world)) -> RosterDTO:
    """Return a team's full roster as player summaries.

    Works for any team in the league (not just the user's team). Includes every player
    on the roster: starters, bench, scratches, injured. Each player carries id, name,
    position, age, overall rating, shoots, contract summary.

    Returns 404 if the team does not exist.

    Note: This route is placed AFTER the /lines and /tactics literal routes so those
    match first and this parameterized route doesn't shadow them.
    """
    team = world.teams.get(tid)
    if team is None:
        raise HTTPException(status_code=404, detail=f"Team {tid} not found")

    players = [player_summary(world.players[pid]) for pid in team.roster if pid in world.players]
    return RosterDTO(players=players)
