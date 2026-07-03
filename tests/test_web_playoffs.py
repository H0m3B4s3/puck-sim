"""Tests for pucksim.web.routers.playoffs (DEVPLAN.md Step 2.11 T4).

Uses FastAPI TestClient against the real app, following the session fixture pattern
from test_web.py. Tests drive a session's World through a full regular season and then
through the playoff bracket.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pucksim.web.app import app
from pucksim.web.session import SESSION_COOKIE_NAME, session_store
from pucksim.sim.season import advance_one_day, start_season
from pucksim.models.league import Phase


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /playoffs
# ---------------------------------------------------------------------------
def test_get_playoffs_on_fresh_career_shows_not_in_playoffs(client):
    """Fresh career should have in_playoffs=False, can_start=False."""
    client.post("/career/new", json={"seed": 100})
    resp = client.get("/playoffs")
    assert resp.status_code == 200

    body = resp.json()
    assert body["in_playoffs"] is False
    assert body["can_start"] is False
    assert body["bracket"] is None
    assert body["complete"] is False
    assert body["champion_tid"] is None


def test_get_playoffs_shows_can_start_after_regular_season_completes(client):
    """After playing out the regular season, can_start should be True."""
    client.post("/career/new", json={"seed": 101})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Start the season
    start_season(world)
    session_store.save(sid, world)

    # Play out the entire regular season
    guard = 0
    guard_limit = 100
    while world.phase == Phase.REGULAR_SEASON and guard < guard_limit:
        advance_one_day(world)
        guard += 1
        # Safety: stop if we've already completed playoffs (shouldn't happen in regular season)
        if guard >= guard_limit - 1:
            break
    session_store.save(sid, world)

    # Now check playoffs state
    resp = client.get("/playoffs")
    assert resp.status_code == 200

    body = resp.json()
    # If we're still in regular season, can_start should be true
    if body["in_playoffs"] is False:
        assert body["can_start"] is True


# ---------------------------------------------------------------------------
# POST /playoffs/start
# ---------------------------------------------------------------------------
def test_start_playoffs_before_season_complete_is_400(client):
    """Cannot start playoffs before the regular season is complete."""
    client.post("/career/new", json={"seed": 102})
    resp = client.post("/playoffs/start")
    assert resp.status_code == 400


def test_start_playoffs_seeds_bracket_and_enters_playoffs_phase(client):
    """Starting playoffs should seed the bracket and change phase to PLAYOFFS."""
    client.post("/career/new", json={"seed": 103})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Start the season
    start_season(world)
    session_store.save(sid, world)

    # Play out the entire regular season
    guard = 0
    guard_limit = 100
    while world.phase == Phase.REGULAR_SEASON and guard < guard_limit:
        advance_one_day(world)
        guard += 1
    session_store.save(sid, world)

    # Start playoffs
    resp = client.post("/playoffs/start")
    assert resp.status_code == 200

    body = resp.json()
    assert body["in_playoffs"] is True
    assert body["can_start"] is False
    assert body["bracket"] is not None
    assert body["complete"] is False
    assert len(body["bracket"]["series"]) == 8  # First round has 8 series (4 per conference)


# ---------------------------------------------------------------------------
# POST /playoffs/advance
# ---------------------------------------------------------------------------
def test_advance_playoffs_before_starting_is_400(client):
    """Cannot advance playoffs before starting them."""
    client.post("/career/new", json={"seed": 104})
    resp = client.post("/playoffs/advance")
    assert resp.status_code == 400


def test_advance_playoffs_and_complete_bracket(client):
    """Run a full playoff bracket from start to completion."""
    client.post("/career/new", json={"seed": 105})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Start and complete the regular season
    start_season(world)
    session_store.save(sid, world)

    guard = 0
    guard_limit = 100
    while world.phase == Phase.REGULAR_SEASON and guard < guard_limit:
        advance_one_day(world)
        guard += 1
    session_store.save(sid, world)

    # Start playoffs
    resp = client.post("/playoffs/start")
    assert resp.status_code == 200
    assert resp.json()["in_playoffs"] is True

    # Repeatedly advance until complete (bounded to prevent infinite loops)
    advance_count = 0
    advance_limit = 40
    while advance_count < advance_limit:
        state_resp = client.get("/playoffs")
        state = state_resp.json()
        if state["complete"]:
            break

        resp = client.post("/playoffs/advance")
        assert resp.status_code == 200
        body = resp.json()

        # Each advance should return a slate
        assert "slate" in body
        assert isinstance(body["slate"], list)

        # Slate items should have required fields
        for game in body["slate"]:
            assert "sid" in game
            assert "round" in game
            assert "status" in game
            assert "home_tid" in game
            assert "away_tid" in game
            assert "home_abbrev" in game
            assert "away_abbrev" in game
            assert "home_score" in game
            assert "away_score" in game
            assert "went_ot" in game
            assert "went_so" in game

        advance_count += 1

    # After completion, check final state
    final_resp = client.get("/playoffs")
    final = final_resp.json()
    assert final["complete"] is True
    assert final["champion_tid"] is not None
    assert final["champion_name"] is not None
    assert final["champion_abbrev"] is not None
    assert final["champion_color"] is not None
    # Phase should have auto-set to DRAFT by the engine
    world_final = session_store.get(sid)
    assert world_final.phase == Phase.DRAFT


def test_advance_after_playoffs_complete_is_400(client):
    """Cannot advance after the bracket is complete."""
    client.post("/career/new", json={"seed": 106})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Start and complete the regular season
    start_season(world)
    session_store.save(sid, world)

    guard = 0
    guard_limit = 100
    while world.phase == Phase.REGULAR_SEASON and guard < guard_limit:
        advance_one_day(world)
        guard += 1
    session_store.save(sid, world)

    # Start playoffs
    client.post("/playoffs/start")

    # Run through to completion
    advance_count = 0
    advance_limit = 40
    while advance_count < advance_limit:
        state_resp = client.get("/playoffs")
        state = state_resp.json()
        if state["complete"]:
            break
        client.post("/playoffs/advance")
        advance_count += 1

    # Now trying to advance should be 400
    resp = client.post("/playoffs/advance")
    assert resp.status_code == 400


def test_bracket_persists_in_get_after_completion(client):
    """Bracket should remain visible via GET /playoffs even after completion (in DRAFT phase)."""
    client.post("/career/new", json={"seed": 107})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Start and complete the regular season
    start_season(world)
    session_store.save(sid, world)

    guard = 0
    guard_limit = 100
    while world.phase == Phase.REGULAR_SEASON and guard < guard_limit:
        advance_one_day(world)
        guard += 1
    session_store.save(sid, world)

    # Start playoffs
    client.post("/playoffs/start")

    # Run through to completion
    advance_count = 0
    advance_limit = 40
    while advance_count < advance_limit:
        state_resp = client.get("/playoffs")
        state = state_resp.json()
        if state["complete"]:
            break
        client.post("/playoffs/advance")
        advance_count += 1

    # After completion, GET /playoffs should still return the bracket
    final_resp = client.get("/playoffs")
    final = final_resp.json()
    assert final["bracket"] is not None
    assert final["champion_tid"] is not None
    assert "series" in final["bracket"]
    assert "all_series" in final["bracket"]
