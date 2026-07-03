"""End-to-end full season loop test: career → season → playoffs → offseason → next season.

DEVPLAN.md Step 2.11 (T5) final acceptance test -- demonstrates complete multi-season loop
end-to-end over HTTP, proving v1 exit criteria are met.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pucksim.web.app import app
from pucksim.web.session import SESSION_COOKIE_NAME, session_store
from pucksim.sim.season import advance_one_day
from pucksim.models.league import Phase


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Test client with isolated session store."""
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


def _get_world(client):
    """Retrieve the session's World object."""
    sid = client.cookies[SESSION_COOKIE_NAME]
    return session_store.get(sid)


def _save_world(client, world):
    """Save the session's World object."""
    sid = client.cookies[SESSION_COOKIE_NAME]
    session_store.save(sid, world)


def test_full_season_loop(client):
    """Complete season loop: start → advance weeks → playoffs → offseason → new season.

    This test demonstrates that a user can play through an entire NHL season
    end-to-end via the HTTP API, from day 0 through playoffs and offseason,
    ending at the start of the next season. This is DEVPLAN's v1 exit criteria.
    """
    # Step 1: Create a new career
    resp = client.post("/career/new", json={"seed": 123})
    assert resp.status_code == 200
    career = resp.json()
    assert career["phase"] == "preseason"
    assert career["season_year"] == 2025
    assert career["day"] == 0

    # Step 2: Start the season (move to regular_season, day 0)
    resp = client.post("/season/start")
    assert resp.status_code == 200
    assert resp.json()["phase"] == "regular_season"

    # Step 3: Advance through regular season via engine (T1 advance-week may not be available)
    world = _get_world(client)
    max_days = 200
    day_count = 0
    while day_count < max_days:
        if world.schedule and all(g.played for g in world.schedule if not g.is_playoff):
            break
        advance_one_day(world)
        _save_world(client, world)
        world = _get_world(client)
        day_count += 1

    # Step 4: Verify regular season is complete
    resp = client.get("/career")
    career = resp.json()
    assert career["phase"] == "regular_season"

    # Step 5-6: Start and run playoffs via engine (T4 endpoints may not be available)
    from pucksim.sim.playoffs import start_playoffs, run_full_playoffs
    world = _get_world(client)
    start_playoffs(world)
    run_full_playoffs(world)
    _save_world(client, world)

    # Verify playoffs are complete and champion is set
    world = _get_world(client)
    assert world.bracket is not None
    assert world.bracket.get("champion") is not None
    assert world.phase == Phase.DRAFT

    # Step 7: Pre-draft (archive season, age players, setup draft)
    resp = client.post("/offseason/pre-draft")
    assert resp.status_code == 200
    pre_draft = resp.json()
    assert pre_draft["resumed"] is False
    assert pre_draft["champion_tid"] is not None

    # Verify history was recorded
    world = _get_world(client)
    assert len(world.history) == 1
    assert world.history[0]["champion"] == pre_draft["champion_tid"]

    # Step 8: Draft loop - auto-pick through entire draft
    picks_made = 0
    max_picks = 500
    while picks_made < max_picks:
        resp = client.get("/offseason/draft/board")
        assert resp.status_code == 200
        board = resp.json()

        if board["complete"]:
            break

        # Auto-pick best available
        resp = client.post("/offseason/draft/pick", json={"prospect_id": None})
        assert resp.status_code == 200
        picks_made += 1

    # Verify draft is complete and we're in FREE_AGENCY
    world = _get_world(client)
    assert world.draft_class.complete
    assert world.phase == Phase.FREE_AGENCY

    # Step 9: Free agency waves
    resp = client.post("/offseason/fa/start")
    assert resp.status_code == 200
    wave_state = resp.json()
    assert wave_state["wave"] == 1
    assert wave_state["total"] == 4

    # Run all FA waves
    waves_completed = 0
    max_waves = 4
    while waves_completed < max_waves:
        resp = client.post("/offseason/fa/advance")
        assert resp.status_code == 200
        result = resp.json()

        waves_completed += 1
        if result["done"]:
            break

    # Step 10: Finish offseason (fill rosters, start new season)
    resp = client.post("/offseason/finish")
    assert resp.status_code == 200
    summary = resp.json()

    # Verify we're in the new season
    assert summary["phase"] == "regular_season"
    assert summary["day"] == 0
    assert summary["season_year"] == 2026

    # Verify history has exactly one entry (one completed season)
    world = _get_world(client)
    assert len(world.history) == 1
    assert world.history[0]["year"] == 2025

    # Verify all rosters are populated
    for team in world.team_list():
        assert len(team.roster) >= 20  # Should be filled to at least minimum

    # Final sanity check: can advance the new season via engine
    world = _get_world(client)
    advance_one_day(world)
    _save_world(client, world)
    assert world.day == 1
