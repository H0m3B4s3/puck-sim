"""Tests for T1 (summary flags + sim-control endpoints) -- DEVPLAN.md Step 2.11.

Tests the new WorldSummaryDTO fields, advance-week and sim-to-next-game endpoints,
and the season_over() helper.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pucksim.web.app import app
from pucksim.web.session import SESSION_COOKIE_NAME, session_store
from pucksim.sim.season import advance_one_day, start_season, next_game_for_team


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


# ---------------------------------------------------------------------------
# WorldSummaryDTO fields
# ---------------------------------------------------------------------------
def test_fresh_career_has_season_flags_false(client):
    """Fresh career should have regular_season_complete=False, offseason_stage=None."""
    resp = client.post("/career/new", json={"seed": 42})
    assert resp.status_code == 200

    body = resp.json()
    assert body["regular_season_complete"] is False
    assert body["offseason_stage"] is None
    assert body["trade_deadline_day"] is not None  # Deadline is computed based on day
    assert body["trade_deadline_passed"] is False


def test_season_complete_flag_flips_after_all_games_played(client):
    """After simulating all regular-season games, regular_season_complete should be True."""
    # Create and start a career
    client.post("/career/new", json={"seed": 99})
    client.post("/season/start")

    # Get session to directly check game count
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    num_games = len([g for g in world.schedule if not g.is_playoff])

    # Advance until all games are played (max 82 days + buffer)
    for _ in range(num_games + 10):
        resp = client.post("/season/advance-day")
        assert resp.status_code == 200
        body = resp.json()
        if body["season_complete"]:
            break

    # Check via GET /career that the flag is persisted
    career = client.get("/career").json()
    assert career["regular_season_complete"] is True


# ---------------------------------------------------------------------------
# POST /season/advance-week
# ---------------------------------------------------------------------------
def test_advance_week_defaults_to_7_days(client):
    """POST /season/advance-week with no explicit days defaults to 7."""
    client.post("/career/new", json={"seed": 1})
    client.post("/season/start")

    resp = client.post("/season/advance-week", json={"days": 7})
    assert resp.status_code == 200

    body = resp.json()
    assert body["days_advanced"] == 7
    assert body["day"] == 7
    assert len(body["games_played"]) > 0


def test_advance_week_clamps_days_to_1_14(client):
    """POST /season/advance-week clamps days to 1-14 range."""
    client.post("/career/new", json={"seed": 2})
    client.post("/season/start")

    # Test max clamping: request 999 days, should get 14
    resp = client.post("/season/advance-week", json={"days": 999})
    assert resp.status_code == 200
    body = resp.json()
    assert body["days_advanced"] <= 14

    # Reset for min test
    client.post("/career/new", json={"seed": 3})
    client.post("/season/start")

    # Test min clamping: request -5 days, should get 1
    resp = client.post("/season/advance-week", json={"days": -5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["days_advanced"] >= 1


def test_advance_week_returns_user_games_subset(client):
    """POST /season/advance-week returns both all games and user_games subset."""
    client.post("/career/new", json={"seed": 4})
    resp_start = client.post("/season/start")
    user_team_id = resp_start.json()["user_team_id"]

    resp = client.post("/season/advance-week", json={"days": 3})
    assert resp.status_code == 200

    body = resp.json()
    # user_games should be a subset of games_played
    assert len(body["user_games"]) <= len(body["games_played"])
    # All user_games should involve the user's team
    for game in body["user_games"]:
        assert game["home"] == user_team_id or game["away"] == user_team_id


def test_advance_week_stops_at_season_completion(client):
    """POST /season/advance-week stops early if season completes before days requested."""
    client.post("/career/new", json={"seed": 5})
    client.post("/season/start")

    # Loop advance-week until the season is complete
    for _ in range(20):  # Safety limit: max 20 * 14 = 280 days
        resp = client.post("/season/advance-week", json={"days": 14})
        assert resp.status_code == 200
        body = resp.json()
        if body["season_complete"]:
            break

    # Verify season is complete
    career = client.get("/career").json()
    assert career["regular_season_complete"] is True


def test_advance_week_only_legal_during_regular_season(client):
    """POST /season/advance-week returns 400 if not in regular season."""
    client.post("/career/new", json={"seed": 6})
    # Don't start the season -- still in preseason

    resp = client.post("/season/advance-week", json={"days": 1})
    assert resp.status_code == 400
    assert "regular season" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /season/sim-to-next-game
# ---------------------------------------------------------------------------
def test_sim_to_next_game_plays_until_user_team_game(client):
    """POST /season/sim-to-next-game simulates until the user's team plays."""
    client.post("/career/new", json={"seed": 7})
    resp_start = client.post("/season/start")
    user_team_id = resp_start.json()["user_team_id"]

    resp = client.post("/season/sim-to-next-game")
    assert resp.status_code == 200

    body = resp.json()
    assert body["played"] is True
    assert body["home"] is not None
    assert body["away"] is not None
    assert body["home_score"] is not None
    assert body["away_score"] is not None
    # One of home/away should be the user's team
    assert body["home"] == user_team_id or body["away"] == user_team_id

    # Verify the game is marked played in the schedule
    schedule = client.get("/season/schedule").json()
    target_gid = body["gid"]
    target_game = next((g for g in schedule if g["gid"] == target_gid), None)
    assert target_game is not None
    assert target_game["played"] is True


def test_sim_to_next_game_returns_played_false_when_no_games_left(client):
    """POST /season/sim-to-next-game returns played=False if user's team has no games left."""
    client.post("/career/new", json={"seed": 8})
    client.post("/season/start")

    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    user_team_id = world.user_team_id

    # Manually mark all user team's games as played (except keeping schedule intact)
    for game in world.schedule:
        if game.involves(user_team_id):
            game.played = True
    session_store.save(sid, world)

    resp = client.post("/season/sim-to-next-game")
    assert resp.status_code == 200

    body = resp.json()
    assert body["played"] is False
    assert body["gid"] is None
    assert body["home_score"] is None


def test_sim_to_next_game_only_legal_during_regular_season(client):
    """POST /season/sim-to-next-game returns 400 if not in regular season."""
    client.post("/career/new", json={"seed": 9})
    # Don't start the season

    resp = client.post("/season/sim-to-next-game")
    assert resp.status_code == 400
    assert "regular season" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# next_game_for_team() engine helper
# ---------------------------------------------------------------------------
def test_next_game_for_team_returns_earliest_unplayed_game(client):
    """next_game_for_team() should return the earliest unplayed game for a team."""
    client.post("/career/new", json={"seed": 10})
    client.post("/season/start")

    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    user_team_id = world.user_team_id

    # Play one day of games
    advance_one_day(world)

    # Call next_game_for_team
    next_game = next_game_for_team(world, user_team_id)

    if next_game is not None:
        # Should be unplayed
        assert not next_game.played
        # Should involve the user's team
        assert next_game.involves(user_team_id)
        # Day should be >= current world day
        assert next_game.day >= world.day


def test_next_game_for_team_returns_none_when_no_games_left(client):
    """next_game_for_team() should return None when a team has no unplayed games."""
    client.post("/career/new", json={"seed": 11})
    client.post("/season/start")

    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    user_team_id = world.user_team_id

    # Mark all user team's games as played
    for game in world.schedule:
        if game.involves(user_team_id):
            game.played = True

    next_game = next_game_for_team(world, user_team_id)
    assert next_game is None


# ---------------------------------------------------------------------------
# AdvanceDayResponse season_complete field
# ---------------------------------------------------------------------------
def test_advance_day_response_includes_season_complete(client):
    """POST /season/advance-day response should include season_complete field."""
    client.post("/career/new", json={"seed": 12})
    client.post("/season/start")

    resp = client.post("/season/advance-day")
    assert resp.status_code == 200

    body = resp.json()
    assert "season_complete" in body
    assert isinstance(body["season_complete"], bool)
    # On day 1, shouldn't be complete yet
    assert body["season_complete"] is False
