"""``/players`` endpoints: player detail (DEVPLAN.md Step 2.11, T2).

Player detail endpoint that exposes comprehensive player information including bio,
contract, injury, season/playoff stats, ratings, and career history.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from pucksim.models.attributes import RATING_GROUPS, GOALIE_RATING_GROUPS
from pucksim.models.world import World
from pucksim.systems.legacy import resume as compute_resume
from pucksim.web.serializers import role_label
from pucksim.web.session import get_world

router = APIRouter(prefix="/players", tags=["players"])


# ---------------------------------------------------------------------------
# DTOs for player detail response
# ---------------------------------------------------------------------------
class RatingEntryDTO(BaseModel):
    """A single rating in a group."""
    key: str
    label: str
    value: int


class RatingGroupDTO(BaseModel):
    """A group of ratings with display labels."""
    group: str
    ratings: List[RatingEntryDTO]


class PlayerDetailDTO(BaseModel):
    """Complete player detail: bio, contract, stats, ratings, and legacy."""
    # Identity
    pid: int
    name: str
    age: int
    position: str
    secondary_position: Optional[str] = None
    shoots: str
    is_goalie: bool
    overall: int
    potential: int
    archetype: Optional[str] = None      # generation-template name (e.g. "Sniper")
    role: Optional[str] = None           # coarse sim role slug (attributes.ROLE_*)
    role_label: Optional[str] = None     # display label for `role`

    # Team
    team_id: Optional[int] = None
    team_abbrev: str
    team_name: str
    team_color: str

    # Contract and condition
    salary: int
    years_remaining: int
    morale: int

    # Injury
    injury: Optional[str] = None
    injury_games: int = 0

    # Draft history
    draft: Optional[dict] = None

    # Stats
    season_stats: dict
    playoff_stats: Optional[dict] = None

    # Ratings grouped by display category
    rating_groups: Dict[str, List[RatingEntryDTO]]

    # Career history (per-season entries)
    career: List[dict]

    # Legacy/HoF resume (None if no career)
    legacy: Optional[dict] = None


def _format_label(key: str) -> str:
    """Convert rating key to display label: strip gk_ prefix, replace _ with space, title case."""
    label = key
    if label.startswith("gk_"):
        label = label[3:]
    label = label.replace("_", " ").title()
    return label


def _build_rating_groups_dto(player) -> Dict[str, List[RatingEntryDTO]]:
    """Build rating_groups DTO from RATING_GROUPS or GOALIE_RATING_GROUPS."""
    groups_def = GOALIE_RATING_GROUPS if player.is_goalie else RATING_GROUPS
    result = {}

    for group_name, rating_keys in groups_def.items():
        ratings = []
        for key in rating_keys:
            value = player.rating(key)
            label = _format_label(key)
            ratings.append(RatingEntryDTO(key=key, label=label, value=value))
        result[group_name] = ratings

    return result


def _build_season_stats_dto(player) -> dict:
    """Build season_stats DTO from player.season."""
    if player.is_goalie:
        # Goalie stats
        return {
            "gp": player.season.gp,
            "wins": player.season.wins,
            "losses": player.season.losses,
            "otl": player.season.otl,
            "save_pct": round(player.season.save_pct, 3),
            "gaa": round(player.season.gaa, 2),
            "shutouts": player.season.shutouts,
            "shots_faced": player.season.shots_faced,
            "saves": player.season.saves,
        }
    else:
        # Skater stats
        return {
            "gp": player.season.gp,
            "g": player.season.g,
            "a": player.season.a,
            "pts": player.season.points,
            "ppg": round(player.season.points / player.season.gp, 2) if player.season.gp else 0.0,
            "sog": player.season.sog,
            "hits": player.season.hits,
            "blocks": player.season.blocks,
            "pim": player.season.pim,
            "plus_minus": player.season.plus_minus,
            "fo_pct": round(player.season.fo_pct, 2) if player.season.gp else 0.0,
        }


def _build_playoff_stats_dto(player) -> Optional[dict]:
    """Build playoff_stats DTO from player.playoffs, or None if no playoff games."""
    if player.is_goalie:
        if player.playoffs.gp == 0:
            return None
        return {
            "gp": player.playoffs.gp,
            "wins": player.playoffs.wins,
            "losses": player.playoffs.losses,
            "otl": player.playoffs.otl,
            "save_pct": round(player.playoffs.save_pct, 3),
            "gaa": round(player.playoffs.gaa, 2),
            "shutouts": player.playoffs.shutouts,
            "shots_faced": player.playoffs.shots_faced,
            "saves": player.playoffs.saves,
        }
    else:
        if player.playoffs.gp == 0:
            return None
        return {
            "gp": player.playoffs.gp,
            "g": player.playoffs.g,
            "a": player.playoffs.a,
            "pts": player.playoffs.points,
            "ppg": round(player.playoffs.points / player.playoffs.gp, 2) if player.playoffs.gp else 0.0,
            "sog": player.playoffs.sog,
            "hits": player.playoffs.hits,
            "blocks": player.playoffs.blocks,
            "pim": player.playoffs.pim,
            "plus_minus": player.playoffs.plus_minus,
            "fo_pct": round(player.playoffs.fo_pct, 2) if player.playoffs.gp else 0.0,
        }


# ---------------------------------------------------------------------------
# GET /players/{pid} -- player detail
# ---------------------------------------------------------------------------
@router.get("/{pid}", response_model=PlayerDetailDTO)
def get_player_detail(pid: int, world: World = Depends(get_world)) -> PlayerDetailDTO:
    """Return detailed information for a single player.

    Includes bio (name, age, position, ratings, potential), contract (salary, years),
    injury status, season and playoff stats, rating breakdown by category, career
    history, and legacy/Hall of Fame resume if the player has completed seasons.

    Returns 404 if the player does not exist.
    """
    player = world.players.get(pid)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Player {pid} not found")

    # Resolve team info
    team = world.teams.get(player.team_id) if player.team_id is not None else None
    team_abbrev = "FA" if team is None else team.abbrev
    team_name = "" if team is None else team.name
    team_color = "#9aa0a6" if team is None else team.primary_color

    # Build injury info
    injury_description = None
    injury_games = 0
    if player.is_injured:
        injury_description = player.injury.description
        injury_games = player.injury.games_remaining

    # Build legacy resume (only if player has completed seasons)
    legacy_data = None
    if player.career:
        legacy_data = compute_resume(world, player)

    return PlayerDetailDTO(
        pid=player.pid,
        name=player.name,
        age=player.age,
        position=player.position,
        secondary_position=player.secondary_position,
        shoots=player.shoots,
        is_goalie=player.is_goalie,
        overall=player.overall,
        potential=player.scouted_potential(),
        archetype=player.archetype,
        role=player.role,
        role_label=role_label(player.role),
        team_id=player.team_id,
        team_abbrev=team_abbrev,
        team_name=team_name,
        team_color=team_color,
        salary=player.contract.current_salary,
        years_remaining=player.contract.years_remaining,
        morale=player.morale,
        injury=injury_description,
        injury_games=injury_games,
        draft=dict(player.draft) if player.draft else None,
        season_stats=_build_season_stats_dto(player),
        playoff_stats=_build_playoff_stats_dto(player),
        rating_groups=_build_rating_groups_dto(player),
        career=list(player.career),
        legacy=legacy_data,
    )
