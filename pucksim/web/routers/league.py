"""``/league`` endpoints: leaders, history, Hall of Fame, all-time leaderboards (DEVPLAN.md Step 2.11 T3).

Read-only league-wide statistics endpoints: current-season leaders (top 10 in each category),
archived season history with awards, Hall of Fame inductees, and all-time career leaderboards.

All endpoints require an active session (Depends(get_world)) but are read-only (no mutations).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pucksim.models.world import World
from pucksim.systems import legacy
from pucksim.web.session import get_world

router = APIRouter(prefix="/league", tags=["league"])


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
class LeaderDTO(BaseModel):
    """A single player in a leaderboard."""
    pid: int
    name: str
    position: str
    team_id: Optional[int]
    team_abbrev: str
    team_color: str
    value: Union[int, float]


class LeaderCategoryDTO(BaseModel):
    """One leaderboard category with its top 10 leaders."""
    stat: str
    label: str
    leaders: List[LeaderDTO]


class LeagueLeadersResponseDTO(BaseModel):
    """Response for GET /league/leaders."""
    categories: List[LeaderCategoryDTO]


class HistoryAwardEntryDTO(BaseModel):
    """An award winner's summary (stored as-is in world.history)."""
    pass  # Unstructured dict passthrough


class HistorySeasonDTO(BaseModel):
    """One archived season entry."""
    year: int
    champion_tid: Optional[int]
    champion_name: str
    champion_abbrev: str
    champion_color: str
    awards: Dict[str, dict]


class LeagueHistoryResponseDTO(BaseModel):
    """Response for GET /league/history."""
    seasons: List[HistorySeasonDTO]


class HallOfFameMemberDTO(BaseModel):
    """A single Hall of Fame inductee."""
    pid: int
    name: str
    position: str
    seasons: int
    peak_ovr: int
    last_team: str
    first_year: int
    last_year: int
    draft: Optional[dict]
    active: bool
    totals: dict
    accolades: List[dict]
    hof_score: float
    hof: bool
    induction_year: Optional[int]


class LeagueHallOfFameResponseDTO(BaseModel):
    """Response for GET /league/hall-of-fame."""
    members: List[HallOfFameMemberDTO]


class LeaderboardRowDTO(BaseModel):
    """A single row in an all-time leaderboard."""
    pass  # Unstructured dict passthrough


class LeagueLeaderboardsResponseDTO(BaseModel):
    """Response for GET /league/leaderboards?category=."""
    category: str
    categories: List[str]
    rows: List[dict]


# ---------------------------------------------------------------------------
# GET /league/leaders -- current-season top-10 leaders by category
# ---------------------------------------------------------------------------
def _get_player_team_info(world: World, pid: int) -> tuple[Optional[int], str, str]:
    """Get team_id, abbrev, and primary_color for a player."""
    player = world.players.get(pid)
    if player is None:
        return None, "FA", "#9aa0a6"

    team_id = player.team_id
    if team_id is None:
        return None, "FA", "#9aa0a6"

    team = world.teams.get(team_id)
    if team is None:
        return team_id, "FA", "#9aa0a6"

    return team_id, team.abbrev, team.primary_color


@router.get("/leaders", response_model=LeagueLeadersResponseDTO)
def get_leaders(world: World = Depends(get_world)) -> LeagueLeadersResponseDTO:
    """Return current-season top-10 leaderboards for six categories.

    Skaters (non-goalies, min GP based on elapsed days):
    - Points (descending)
    - Goals (descending)
    - Assists (descending)

    Goalies (min GP based on elapsed days):
    - Save % (descending, 3dp)
    - GAA (ascending, 2dp)
    - Wins (descending)
    """
    # Minimum games-played threshold scales with season progress (day // 4)
    min_gp_skater = max(1, world.day // 4)
    min_gp_goalie = max(2, world.day // 4)

    categories: List[LeaderCategoryDTO] = []

    # Skater categories
    skaters = [p for p in world.players.values()
               if not p.is_goalie and p.season.gp >= min_gp_skater]

    # Points (g + a)
    skaters_by_pts = sorted(skaters, key=lambda p: (p.season.points, p.season.g), reverse=True)
    pts_leaders = []
    for p in skaters_by_pts[:10]:
        tid, abbrev, color = _get_player_team_info(world, p.pid)
        pts_leaders.append(LeaderDTO(
            pid=p.pid,
            name=p.name,
            position=p.position,
            team_id=tid,
            team_abbrev=abbrev,
            team_color=color,
            value=p.season.points,
        ))
    categories.append(LeaderCategoryDTO(stat="pts", label="Points", leaders=pts_leaders))

    # Goals
    skaters_by_g = sorted(skaters, key=lambda p: (p.season.g, p.season.a), reverse=True)
    g_leaders = []
    for p in skaters_by_g[:10]:
        tid, abbrev, color = _get_player_team_info(world, p.pid)
        g_leaders.append(LeaderDTO(
            pid=p.pid,
            name=p.name,
            position=p.position,
            team_id=tid,
            team_abbrev=abbrev,
            team_color=color,
            value=p.season.g,
        ))
    categories.append(LeaderCategoryDTO(stat="g", label="Goals", leaders=g_leaders))

    # Assists
    skaters_by_a = sorted(skaters, key=lambda p: (p.season.a, p.season.g), reverse=True)
    a_leaders = []
    for p in skaters_by_a[:10]:
        tid, abbrev, color = _get_player_team_info(world, p.pid)
        a_leaders.append(LeaderDTO(
            pid=p.pid,
            name=p.name,
            position=p.position,
            team_id=tid,
            team_abbrev=abbrev,
            team_color=color,
            value=p.season.a,
        ))
    categories.append(LeaderCategoryDTO(stat="a", label="Assists", leaders=a_leaders))

    # Goalie categories
    goalies = [p for p in world.players.values()
               if p.is_goalie and p.season.gp >= min_gp_goalie]

    # Save % (descending)
    goalies_by_sv_pct = sorted(goalies, key=lambda p: (p.season.save_pct, -p.season.gaa), reverse=True)
    sv_pct_leaders = []
    for p in goalies_by_sv_pct[:10]:
        tid, abbrev, color = _get_player_team_info(world, p.pid)
        sv_pct_leaders.append(LeaderDTO(
            pid=p.pid,
            name=p.name,
            position=p.position,
            team_id=tid,
            team_abbrev=abbrev,
            team_color=color,
            value=round(p.season.save_pct, 3),
        ))
    categories.append(LeaderCategoryDTO(stat="save_pct", label="Save %", leaders=sv_pct_leaders))

    # GAA (ascending -- lower is better)
    goalies_by_gaa = sorted(goalies, key=lambda p: (p.season.gaa, -p.season.save_pct))
    gaa_leaders = []
    for p in goalies_by_gaa[:10]:
        tid, abbrev, color = _get_player_team_info(world, p.pid)
        gaa_leaders.append(LeaderDTO(
            pid=p.pid,
            name=p.name,
            position=p.position,
            team_id=tid,
            team_abbrev=abbrev,
            team_color=color,
            value=round(p.season.gaa, 2),
        ))
    categories.append(LeaderCategoryDTO(stat="gaa", label="GAA", leaders=gaa_leaders))

    # Wins (descending)
    goalies_by_wins = sorted(goalies, key=lambda p: (p.season.wins, p.season.save_pct), reverse=True)
    wins_leaders = []
    for p in goalies_by_wins[:10]:
        tid, abbrev, color = _get_player_team_info(world, p.pid)
        wins_leaders.append(LeaderDTO(
            pid=p.pid,
            name=p.name,
            position=p.position,
            team_id=tid,
            team_abbrev=abbrev,
            team_color=color,
            value=p.season.wins,
        ))
    categories.append(LeaderCategoryDTO(stat="wins", label="Wins", leaders=wins_leaders))

    return LeagueLeadersResponseDTO(categories=categories)


# ---------------------------------------------------------------------------
# GET /league/history -- archived seasons with awards
# ---------------------------------------------------------------------------
@router.get("/history", response_model=LeagueHistoryResponseDTO)
def get_history(world: World = Depends(get_world)) -> LeagueHistoryResponseDTO:
    """Return league history: past seasons' champions and awards, most recent first.

    Each season entry includes the champion team info and all award winners
    (Hart, Norris, Vezina, Calder, Selke).
    """
    seasons: List[HistorySeasonDTO] = []

    # Reverse to get most recent first
    for hist_entry in reversed(world.history):
        year = hist_entry.get("year")
        champ_tid = hist_entry.get("champion")
        champ_name = hist_entry.get("champion_name", "")

        # Get champion team info
        champ_team = world.teams.get(champ_tid) if champ_tid is not None else None
        champ_abbrev = champ_team.abbrev if champ_team else ""
        champ_color = champ_team.primary_color if champ_team else "#9aa0a6"

        # Enrich awards with team colors
        awards_dict = hist_entry.get("awards", {})
        enriched_awards = {}
        for award_key, award_entry in awards_dict.items():
            if award_entry is not None:
                enriched = dict(award_entry)
                # Add team_color to each award entry
                award_tid = award_entry.get("tid")
                award_team = world.teams.get(award_tid) if award_tid is not None else None
                enriched["team_color"] = award_team.primary_color if award_team else "#9aa0a6"
                enriched_awards[award_key] = enriched
            else:
                enriched_awards[award_key] = None

        seasons.append(HistorySeasonDTO(
            year=year,
            champion_tid=champ_tid,
            champion_name=champ_name,
            champion_abbrev=champ_abbrev,
            champion_color=champ_color,
            awards=enriched_awards,
        ))

    return LeagueHistoryResponseDTO(seasons=seasons)


# ---------------------------------------------------------------------------
# GET /league/hall-of-fame -- Hall of Fame inductees
# ---------------------------------------------------------------------------
@router.get("/hall-of-fame", response_model=LeagueHallOfFameResponseDTO)
def get_hall_of_fame(world: World = Depends(get_world)) -> LeagueHallOfFameResponseDTO:
    """Return Hall of Fame members, sorted by HOF score descending.

    Each member is a flattened résumé snapshot with HOF score, induction year,
    and active status.
    """
    members: List[HallOfFameMemberDTO] = []

    # Sort by hof_score descending
    hof_list = sorted(world.hall_of_fame, key=lambda m: m.get("hof_score", 0), reverse=True)

    for hof_entry in hof_list:
        pid = hof_entry.get("pid")
        # Check if player is still active
        active = pid in world.players

        # Build accolades list with labels
        accolades_dict = hof_entry.get("accolades", {})
        accolades_list = []
        for key, count in accolades_dict.items():
            if count and count > 0:
                label = legacy.ACCOLADE_LABELS.get(key, key)
                accolades_list.append({"key": key, "label": label, "count": count})
        # Sort by ACCOLADE_WEIGHTS
        accolades_list.sort(
            key=lambda a: legacy.ACCOLADE_WEIGHTS.get(a["key"], 0),
            reverse=True
        )

        members.append(HallOfFameMemberDTO(
            pid=hof_entry.get("pid"),
            name=hof_entry.get("name"),
            position=hof_entry.get("position"),
            seasons=hof_entry.get("seasons", 0),
            peak_ovr=hof_entry.get("peak_ovr", 0),
            last_team=hof_entry.get("last_team", "FA"),
            first_year=hof_entry.get("first_year", 0),
            last_year=hof_entry.get("last_year", 0),
            draft=hof_entry.get("draft"),
            active=active,
            totals=hof_entry.get("totals", {}),
            accolades=accolades_list,
            hof_score=hof_entry.get("hof_score", 0),
            hof=hof_entry.get("hof", False),
            induction_year=hof_entry.get("induction_year"),
        ))

    return LeagueHallOfFameResponseDTO(members=members)


# ---------------------------------------------------------------------------
# GET /league/leaderboards?category= -- all-time career leaderboards
# ---------------------------------------------------------------------------
@router.get("/leaderboards", response_model=LeagueLeaderboardsResponseDTO)
def get_leaderboards(category: str = "pts", world: World = Depends(get_world)) -> LeagueLeaderboardsResponseDTO:
    """Return all-time career leaderboards for a given category.

    Valid categories: pts, g, a, gp, wins, shutouts
    Returns top 25 players/records, including both active and retired players.
    """
    if category not in legacy.LEADERBOARD_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{category}'. Valid categories: {', '.join(legacy.LEADERBOARD_CATEGORIES)}"
        )

    rows = legacy.leaderboards(world, category=category, limit=25)

    return LeagueLeaderboardsResponseDTO(
        category=category,
        categories=list(legacy.LEADERBOARD_CATEGORIES),
        rows=rows,
    )
