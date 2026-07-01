"""Tests for pucksim.models.world.World -- Step 1.9 done-criteria."""
from __future__ import annotations

from pucksim.config import SCHEMA_VERSION
from pucksim.models.league import Game, Phase
from pucksim.models.player import Player
from pucksim.models.team import Team
from pucksim.rng import Rng
from pucksim.models.world import World


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_team(tid: int, conference: str = "Eastern") -> Team:
    return Team(tid=tid, name=f"Team {tid}", abbrev=f"T{tid}", conference=conference)


def make_player(pid: int, team_id=None, position: str = "C") -> Player:
    return Player(pid=pid, name=f"Player {pid}", age=25, position=position, team_id=team_id)


def build_basic_world(seed: int = 42) -> World:
    world = World(rng=Rng(seed=seed))
    team_a = make_team(1, "Eastern")
    team_b = make_team(2, "Western")
    world.register_team(team_a)
    world.register_team(team_b)
    return world


# ---------------------------------------------------------------------------
# Construction / registration
# ---------------------------------------------------------------------------
def test_register_teams_and_add_players_free_agent_tracking():
    world = build_basic_world()

    signed_player = make_player(1, team_id=1)
    world.add_player(signed_player)
    world.team(1).add_player(1)

    fa_player = make_player(2, team_id=None)
    world.add_player(fa_player)

    other_signed = make_player(3, team_id=2)
    world.add_player(other_signed)
    world.team(2).add_player(3)

    assert set(world.teams.keys()) == {1, 2}
    assert set(world.players.keys()) == {1, 2, 3}
    # Only the team_id=None player should have landed in free_agents automatically.
    assert world.free_agents == [2]
    assert world.team_list() and len(world.team_list()) == 2


def test_team_and_player_accessors():
    world = build_basic_world()
    world.add_player(make_player(1, team_id=1))

    assert world.team(1).tid == 1
    assert world.player(1).pid == 1


# ---------------------------------------------------------------------------
# sign_player
# ---------------------------------------------------------------------------
def test_sign_player_updates_team_id_roster_and_free_agents():
    world = build_basic_world()
    fa = make_player(10, team_id=None)
    world.add_player(fa)
    assert 10 in world.free_agents

    world.sign_player(10, 1)

    assert world.player(10).team_id == 1
    assert 10 in world.team(1).roster
    assert 10 not in world.free_agents


def test_sign_player_from_one_team_removes_from_old_roster():
    world = build_basic_world()
    p = make_player(11, team_id=1)
    world.add_player(p)
    world.team(1).add_player(11)

    world.sign_player(11, 2)

    assert 11 not in world.team(1).roster
    assert 11 in world.team(2).roster
    assert world.player(11).team_id == 2


# ---------------------------------------------------------------------------
# release_player
# ---------------------------------------------------------------------------
def test_release_player_reverses_sign():
    world = build_basic_world()
    p = make_player(20, team_id=1)
    world.add_player(p)
    world.team(1).add_player(20)

    world.release_player(20)

    assert world.player(20).team_id is None
    assert 20 not in world.team(1).roster
    assert 20 in world.free_agents


def test_release_player_is_idempotent_for_free_agents_list():
    world = build_basic_world()
    p = make_player(21, team_id=1)
    world.add_player(p)
    world.team(1).add_player(21)

    world.release_player(21)
    world.release_player(21)  # releasing again should not duplicate

    assert world.free_agents.count(21) == 1


# ---------------------------------------------------------------------------
# transfer_player
# ---------------------------------------------------------------------------
def test_transfer_player_moves_between_teams():
    world = build_basic_world()
    p = make_player(30, team_id=1)
    world.add_player(p)
    world.team(1).add_player(30)

    world.transfer_player(30, 2)

    assert 30 not in world.team(1).roster
    assert 30 in world.team(2).roster
    assert world.player(30).team_id == 2
    # Never touches free_agents.
    assert 30 not in world.free_agents


def test_transfer_player_from_free_agency_also_works():
    world = build_basic_world()
    p = make_player(31, team_id=None)
    world.add_player(p)

    world.transfer_player(31, 1)

    assert world.player(31).team_id == 1
    assert 31 in world.team(1).roster


# ---------------------------------------------------------------------------
# id counters
# ---------------------------------------------------------------------------
def test_new_pid_and_new_gid_increase_and_are_unique():
    world = build_basic_world()
    pids = [world.new_pid() for _ in range(5)]
    gids = [world.new_gid() for _ in range(5)]

    assert pids == sorted(pids)
    assert len(set(pids)) == len(pids)
    assert gids == sorted(gids)
    assert len(set(gids)) == len(gids)
    # pid/gid counters are independent sequences.
    assert pids == [1, 2, 3, 4, 5]
    assert gids == [1, 2, 3, 4, 5]


def test_id_counters_survive_round_trip_without_collision():
    world = build_basic_world()
    used_pids = [world.new_pid() for _ in range(3)]   # 1, 2, 3
    used_gids = [world.new_gid() for _ in range(2)]   # 1, 2

    restored = World.from_dict(world.to_dict())

    next_pid = restored.new_pid()
    next_gid = restored.new_gid()

    assert next_pid not in used_pids
    assert next_gid not in used_gids
    assert next_pid == 4
    assert next_gid == 3


# ---------------------------------------------------------------------------
# to_dict / from_dict round trip
# ---------------------------------------------------------------------------
def test_schema_version_present_and_correct():
    world = build_basic_world()
    d = world.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION


def test_full_round_trip_preserves_core_fields():
    world = build_basic_world()
    world.season_year = 2030
    world.phase = Phase.REGULAR_SEASON
    world.day = 15
    world.standings_rule = "retro"
    world.salary_cap = 90_000_000
    world.user_team_id = 1

    signed = make_player(100, team_id=1)
    world.add_player(signed)
    world.team(1).add_player(100)

    fa = make_player(101, team_id=None)
    world.add_player(fa)

    game = Game(gid=1, day=1, home=1, away=2, home_score=3, away_score=2, played=True)
    world.schedule.append(game)

    d = world.to_dict()
    restored = World.from_dict(d)

    assert restored.season_year == 2030
    assert restored.phase == Phase.REGULAR_SEASON
    assert restored.day == 15
    assert restored.standings_rule == "retro"
    assert restored.salary_cap == 90_000_000
    assert restored.user_team_id == 1

    assert set(restored.teams.keys()) == {1, 2}
    assert set(restored.players.keys()) == {100, 101}
    assert restored.player(100).team_id == 1
    assert 100 in restored.team(1).roster
    assert restored.free_agents == [101]

    assert len(restored.schedule) == 1
    restored_game = restored.schedule[0]
    assert restored_game.gid == 1
    assert restored_game.home == 1
    assert restored_game.away == 2
    assert restored_game.home_score == 3
    assert restored_game.away_score == 2
    assert restored_game.played is True


def test_round_trip_preserves_dormant_multileague_fields_while_empty():
    world = build_basic_world()
    # Confirm the dormant fields exist with the expected default shapes.
    assert world.mode == "nhl"
    assert world.other_teams == {}
    assert world.recruits == []
    assert world.pipeline == {}

    restored = World.from_dict(world.to_dict())

    assert restored.mode == "nhl"
    assert restored.other_teams == {}
    assert restored.recruits == []
    assert restored.pipeline == {}


def test_round_trip_preserves_dormant_multileague_fields_when_populated():
    world = build_basic_world()
    world.mode = "chl"
    other_team = make_team(500, "Eastern")
    world.register_other_team(other_team)
    world.recruits = [900, 901]
    world.pipeline = {"season": 2031, "results": [1, 2, 3]}

    restored = World.from_dict(world.to_dict())

    assert restored.mode == "chl"
    assert set(restored.other_teams.keys()) == {500}
    assert restored.recruits == [900, 901]
    assert restored.pipeline == {"season": 2031, "results": [1, 2, 3]}


def test_round_trip_rng_state_mid_sequence():
    """Mid-sequence save/restore must reproduce the same subsequent draws --
    same technique as Step 1.2's rng tests, exercised through World's envelope."""
    world = build_basic_world(seed=555)

    # Burn some draws so we're mid-sequence, not at a fresh seed.
    for _ in range(5):
        world.rng.random()
        world.rng.randint(1, 6)

    d = world.to_dict()

    # Draws taken right after the save on the *original* world -- the "expected future".
    expected_future = [world.rng.random() for _ in range(10)] + [
        world.rng.randint(1, 100) for _ in range(10)
    ]

    restored = World.from_dict(d)
    replayed_future = [restored.rng.random() for _ in range(10)] + [
        restored.rng.randint(1, 100) for _ in range(10)
    ]

    assert replayed_future == expected_future


def test_from_dict_backfills_next_pid_when_missing():
    """If a save predates the id-counter fields, next_pid should backfill from
    the highest player id present rather than colliding."""
    world = build_basic_world()
    world.add_player(make_player(7, team_id=1))
    world.team(1).add_player(7)

    d = world.to_dict()
    del d["next_pid"]
    del d["next_gid"]

    restored = World.from_dict(d)
    assert restored.new_pid() == 8
    assert restored.new_gid() == 1
