"""Tests for pucksim.gen -- Step 1.11 done-criteria.

This step is the integration test of every model file built so far: it
exercises attributes.py, contract.py, player.py, team.py (roster + auto line-
builder), coach.py, and world.py all at once via `build_world()`.
"""
from __future__ import annotations

from pucksim import config
from pucksim.gen.leaguegen import build_world


# ---------------------------------------------------------------------------
# League shape
# ---------------------------------------------------------------------------
def test_build_world_produces_correct_team_count():
    world = build_world(seed=42)
    assert len(world.teams) == config.NUM_TEAMS


def test_teams_distributed_across_conferences_and_divisions():
    world = build_world(seed=42)
    by_conf = {}
    by_div = {}
    for team in world.teams.values():
        by_conf.setdefault(team.conference, []).append(team)
        by_div.setdefault((team.conference, team.division), []).append(team)

    assert set(by_conf.keys()) == set(config.CONFERENCES)
    for conf, teams in by_conf.items():
        assert len(teams) == config.TEAMS_PER_CONFERENCE

    assert len(by_div) == len(config.CONFERENCES) * config.DIVISIONS_PER_CONFERENCE
    for key, teams in by_div.items():
        assert len(teams) == config.TEAMS_PER_DIVISION


# ---------------------------------------------------------------------------
# Roster legality
# ---------------------------------------------------------------------------
def test_every_team_has_legal_roster_size():
    world = build_world(seed=42)
    for team in world.teams.values():
        skaters = [pid for pid in team.roster if world.player(pid).position != "G"]
        goalies = [pid for pid in team.roster if world.player(pid).position == "G"]

        assert config.SKATERS_MIN <= len(skaters) <= config.SKATERS_MAX
        assert config.GOALIES_MIN <= len(goalies) <= config.GOALIES_MAX
        assert len(goalies) >= 2
        assert config.ROSTER_MIN <= len(team.roster) <= config.ROSTER_MAX


def test_roster_membership_consistent_with_player_team_id():
    world = build_world(seed=42)
    for team in world.teams.values():
        for pid in team.roster:
            assert world.player(pid).team_id == team.tid


# ---------------------------------------------------------------------------
# Lines / pairs / goalies
# ---------------------------------------------------------------------------
def test_every_team_has_four_complete_forward_lines():
    world = build_world(seed=42)
    for team in world.teams.values():
        assert len(team.lines) == 4
        for line in team.lines:
            assert len(line) == 3


def test_every_team_has_three_complete_d_pairs():
    world = build_world(seed=42)
    for team in world.teams.values():
        assert len(team.pairs) == 3
        for pair in team.pairs:
            assert len(pair) == 2


def test_every_team_has_goalie_starter_and_backup():
    world = build_world(seed=42)
    for team in world.teams.values():
        assert team.goalie_starter is not None
        assert world.player(team.goalie_starter).position == "G"
        assert team.goalie_backup is not None
        assert world.player(team.goalie_backup).position == "G"
        assert team.goalie_starter != team.goalie_backup


def test_every_team_has_a_coach():
    world = build_world(seed=42)
    for team in world.teams.values():
        assert team.coach is not None
        # Stored as a dict (see leaguegen.py's Team.coach typing note) --
        # a plain dataclass-shaped dict with at least an archetype name.
        assert "archetype" in team.coach


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def _serialize_players(world) -> dict:
    return {pid: p.to_dict() for pid, p in world.players.items()}


def _serialize_teams(world) -> dict:
    return {tid: t.to_dict() for tid, t in world.teams.items()}


def test_same_seed_produces_byte_identical_rosters():
    world_a = build_world(seed=42)
    world_b = build_world(seed=42)

    assert _serialize_players(world_a) == _serialize_players(world_b)
    assert _serialize_teams(world_a) == _serialize_teams(world_b)


def test_different_seeds_produce_different_rosters():
    world_a = build_world(seed=1)
    world_b = build_world(seed=2)

    assert _serialize_players(world_a) != _serialize_players(world_b)


# ---------------------------------------------------------------------------
# Overall distribution sanity (loose bounds -- gen tuning parameters, not
# exact-value tests; these are expected to be iterated on later).
# ---------------------------------------------------------------------------
def test_generated_overall_distribution_is_believable():
    world = build_world(seed=42)
    overalls = [p.overall for p in world.players.values()]

    avg = sum(overalls) / len(overalls)
    assert 55 <= avg <= 75

    assert any(o > 80 for o in overalls)
    assert any(o < 55 for o in overalls)

    # Legal rating bounds never violated.
    assert all(config.RATING_MIN <= o <= config.RATING_MAX for o in overalls)
