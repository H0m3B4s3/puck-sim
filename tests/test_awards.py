"""Tests for pucksim.systems.awards -- DEVPLAN.md Step 2.7 done-criteria.

Covers award eligibility gating for all five hockey awards (Hart/Norris/Vezina/Calder/Selke):
gp-fraction eligibility bars are respected, position-restricted awards (Norris=D-only,
Selke=forward-only, Vezina=goalie-only) never cross position lines, Calder rookie-eligibility
gating works, and the whole pipeline runs end-to-end against a real generated league without
crashing or picking an ineligible winner.
"""
from __future__ import annotations

from pucksim import config
from pucksim.models import attributes as attr
from pucksim.models.player import Player
from pucksim.models.stats import GoalieStatLine, SkaterStatLine
from pucksim.models.team import Team
from pucksim.models.world import World
from pucksim.rng import Rng
from pucksim.systems import awards


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def build_world_with_teams(n_teams: int = 2) -> World:
    world = World(rng=Rng(seed=1))
    for i in range(n_teams):
        team = Team(tid=i, name=f"Team {i}", abbrev=f"T{i}", conference="Eastern")
        world.register_team(team)
    return world


def make_skater(pid: int, tid: int, position: str = "C", overall: int = 75, age: int = 27,
                 gp: int = 60, g: int = 20, a: int = 30, hits: int = 50, blocks: int = 20,
                 takeaways: int = 20, fo_won: int = 100, fo_lost: int = 80,
                 career: list = None) -> Player:
    ratings = {name: overall for name in attr.ALL_RATINGS}
    p = Player(pid=pid, name=f"Skater {pid}", age=age, position=position, ratings=ratings,
               team_id=tid, career=career or [])
    p.season = SkaterStatLine(gp=gp, g=g, a=a, hits=hits, blocks=blocks, takeaways=takeaways,
                               fo_won=fo_won, fo_lost=fo_lost)
    return p


def make_goalie(pid: int, tid: int, overall: int = 75, age: int = 27, gp: int = 55,
                 shots_faced: int = 1600, saves: int = 1480, goals_against: int = 120,
                 wins: int = 30, secs: int = 55 * 3600, shutouts: int = 4,
                 career: list = None) -> Player:
    ratings = {name: overall for name in attr.ALL_GOALIE_RATINGS}
    p = Player(pid=pid, name=f"Goalie {pid}", age=age, position="G", ratings=ratings,
               team_id=tid, career=career or [])
    p.season = GoalieStatLine(gp=gp, shots_faced=shots_faced, saves=saves,
                               goals_against=goals_against, wins=wins, secs=secs,
                               shutouts=shutouts)
    return p


def sign(world: World, tid: int, player: Player) -> None:
    world.add_player(player)
    world.teams[tid].add_player(player.pid)
    world.teams[tid].wins += 1   # give every team at least 1 GP so win_pct is well-defined


# ---------------------------------------------------------------------------
# Games-played eligibility gating
# ---------------------------------------------------------------------------
def test_hart_ignores_a_player_below_the_min_gp_fraction():
    world = build_world_with_teams()
    games = config.SEASON_GAMES
    eligible_gp = int(games * awards.MIN_GP_FRACTION) + 2
    below_gp = int(games * awards.MIN_GP_FRACTION) - 5

    star = make_skater(1, 0, overall=90, gp=eligible_gp, g=50, a=60)
    thin_sample_star = make_skater(2, 1, overall=99, gp=below_gp, g=40, a=40)
    sign(world, 0, star)
    sign(world, 1, thin_sample_star)

    result = awards.compute_awards(world)
    assert result["hart"]["pid"] == star.pid   # the higher-rated but thin-sample player is out


def test_vezina_uses_a_lower_gp_bar_than_skater_awards():
    """Vezina eligibility bar is GOALIE_MIN_GP_FRACTION (lower than MIN_GP_FRACTION) since
    starters split time with a backup by design -- a goalie who wouldn't clear the skater bar
    should still be Vezina-eligible."""
    world = build_world_with_teams()
    games = config.SEASON_GAMES
    gp = int(games * awards.GOALIE_MIN_GP_FRACTION) + 1
    assert gp < games * awards.MIN_GP_FRACTION   # confirms this gp genuinely fails the higher bar

    g = make_goalie(1, 0, gp=gp)
    sign(world, 0, g)
    result = awards.compute_awards(world)
    assert "vezina" in result
    assert result["vezina"]["pid"] == g.pid


def test_calder_uses_rookie_gp_fraction_not_the_stricter_bar():
    world = build_world_with_teams()
    games = config.SEASON_GAMES
    gp = int(games * awards.ROOKIE_GP_FRACTION) + 1
    assert gp < games * awards.MIN_GP_FRACTION

    rookie = make_skater(1, 0, age=19, gp=gp, g=15, a=10, career=[])
    sign(world, 0, rookie)
    result = awards.compute_awards(world)
    assert "calder" in result
    assert result["calder"]["pid"] == rookie.pid


# ---------------------------------------------------------------------------
# Position-restricted awards never cross position lines
# ---------------------------------------------------------------------------
def test_norris_only_considers_defensemen():
    world = build_world_with_teams()
    gp = config.SEASON_GAMES
    forward = make_skater(1, 0, position="C", overall=95, gp=gp, g=60, a=70)
    dman = make_skater(2, 1, position="D", overall=70, gp=gp, g=10, a=25, blocks=90, hits=80)
    sign(world, 0, forward)
    sign(world, 1, dman)

    result = awards.compute_awards(world)
    assert result["norris"]["pid"] == dman.pid
    assert result["norris"]["position"] == "D"


def test_norris_absent_when_no_defenseman_is_eligible():
    world = build_world_with_teams()
    forward = make_skater(1, 0, position="C", gp=config.SEASON_GAMES)
    sign(world, 0, forward)
    result = awards.compute_awards(world)
    assert "norris" not in result


def test_selke_only_considers_forwards():
    world = build_world_with_teams()
    gp = config.SEASON_GAMES
    dman = make_skater(1, 0, position="D", overall=90, gp=gp, blocks=100, takeaways=60)
    forward = make_skater(2, 1, position="LW", overall=70, gp=gp, blocks=40, takeaways=40)
    sign(world, 0, dman)
    sign(world, 1, forward)

    result = awards.compute_awards(world)
    assert result["selke"]["pid"] == forward.pid
    assert result["selke"]["position"] in ("LW", "C", "RW")


def test_vezina_only_considers_goalies():
    world = build_world_with_teams()
    gp = config.SEASON_GAMES
    skater = make_skater(1, 0, overall=99, gp=gp)
    goalie = make_goalie(2, 1, gp=int(gp * awards.GOALIE_MIN_GP_FRACTION) + 1)
    sign(world, 0, skater)
    sign(world, 1, goalie)

    result = awards.compute_awards(world)
    assert result["vezina"]["pid"] == goalie.pid
    assert result["vezina"]["position"] == "G"


# ---------------------------------------------------------------------------
# Vezina value ordering (save_pct-driven)
# ---------------------------------------------------------------------------
def test_vezina_prefers_higher_save_percentage():
    world = build_world_with_teams()
    gp = config.SEASON_GAMES
    great = make_goalie(1, 0, gp=gp, shots_faced=1600, saves=1500, goals_against=100)   # .9375
    mediocre = make_goalie(2, 1, gp=gp, shots_faced=1600, saves=1400, goals_against=200)  # .875
    sign(world, 0, great)
    sign(world, 1, mediocre)

    result = awards.compute_awards(world)
    assert result["vezina"]["pid"] == great.pid


# ---------------------------------------------------------------------------
# Rookie (Calder) eligibility
# ---------------------------------------------------------------------------
def test_calder_excludes_a_veteran_with_career_history():
    world = build_world_with_teams()
    gp = config.SEASON_GAMES
    veteran = make_skater(1, 0, age=30, gp=gp, g=40, a=40,
                           career=[{"year": 2020, "gp": 70, "g": 20, "a": 20, "ovr": 75}])
    rookie = make_skater(2, 1, age=19, gp=gp, g=15, a=15, career=[])
    sign(world, 0, veteran)
    sign(world, 1, rookie)

    result = awards.compute_awards(world)
    assert result["calder"]["pid"] == rookie.pid


def test_calder_absent_when_no_rookie_is_eligible():
    world = build_world_with_teams()
    veteran = make_skater(1, 0, age=32, gp=config.SEASON_GAMES,
                           career=[{"year": 2020, "gp": 70, "ovr": 75}])
    sign(world, 0, veteran)
    result = awards.compute_awards(world)
    assert "calder" not in result


def test_calder_can_be_won_by_a_goalie():
    world = build_world_with_teams()
    rookie_goalie = make_goalie(1, 0, age=20, gp=int(config.SEASON_GAMES * 0.5),
                                 saves=1500, shots_faced=1600, goals_against=90, career=[])
    sign(world, 0, rookie_goalie)
    result = awards.compute_awards(world)
    assert "calder" in result
    assert result["calder"]["pid"] == rookie_goalie.pid


# ---------------------------------------------------------------------------
# Empty-league / no-eligible-candidate handling (should never crash, keys simply absent)
# ---------------------------------------------------------------------------
def test_compute_awards_on_empty_world_returns_empty_dict_no_crash():
    world = build_world_with_teams()
    result = awards.compute_awards(world)
    assert result == {}


def test_compute_awards_never_crashes_when_only_goalies_are_rostered():
    world = build_world_with_teams()
    g = make_goalie(1, 0, gp=int(config.SEASON_GAMES * awards.GOALIE_MIN_GP_FRACTION) + 1)
    sign(world, 0, g)
    result = awards.compute_awards(world)
    assert "vezina" in result
    assert "norris" not in result
    assert "selke" not in result


# ---------------------------------------------------------------------------
# End-to-end integration against a real generated league (no hand-built fixtures)
# ---------------------------------------------------------------------------
def test_compute_awards_end_to_end_against_a_simulated_season():
    from pucksim.gen.leaguegen import build_world
    from pucksim.sim import season as S

    world = build_world(seed=21)
    S.start_season(world)
    while not S.regular_season_complete(world):
        S.advance_one_day(world)

    result = awards.compute_awards(world)
    # At least Hart/Vezina should always be decidable in a full generated 82-game season.
    assert "hart" in result
    assert "vezina" in result
    for key in ("hart", "norris", "vezina", "calder", "selke"):
        if key in result:
            pid = result[key]["pid"]
            assert pid in world.players
