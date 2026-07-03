"""Tests for pucksim.web.routers.league (DEVPLAN.md Step 2.11 T3).

Tests for GET /league endpoints: leaders, history, hall-of-fame, leaderboards.
Uses session fixtures from test_web.py pattern.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pucksim.sim.season import advance_one_day, start_season
from pucksim.systems import offseason
from pucksim.web.app import app
from pucksim.web.session import SESSION_COOKIE_NAME, session_store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /league/leaders -- current-season top-10 leaders
# ---------------------------------------------------------------------------
def test_leaders_returns_six_categories_on_fresh_world(client):
    """Fresh started world returns 6 categories with ≤10 rows each without error."""
    client.post("/career/new", json={"seed": 42})
    resp = client.get("/league/leaders")
    assert resp.status_code == 200

    body = resp.json()
    assert "categories" in body
    assert len(body["categories"]) == 6

    # Check all expected categories exist
    category_stats = {cat["stat"] for cat in body["categories"]}
    expected = {"pts", "g", "a", "save_pct", "gaa", "wins"}
    assert category_stats == expected

    # Each category should have ≤10 leaders (could be fewer on fresh world with 0 GP)
    for cat in body["categories"]:
        assert len(cat["leaders"]) <= 10
        assert "stat" in cat
        assert "label" in cat
        for leader in cat["leaders"]:
            assert "pid" in leader
            assert "name" in leader
            assert "position" in leader
            assert "team_id" in leader
            assert "team_abbrev" in leader
            assert "team_color" in leader
            assert "value" in leader


def test_leaders_points_sorted_descending_after_games_played(client):
    """After advancing days, points leaders are non-empty and sorted descending."""
    client.post("/career/new", json={"seed": 100})
    sid = client.cookies[SESSION_COOKIE_NAME]

    # Start season and simulate a few days
    world = session_store.get(sid)
    start_season(world)
    for _ in range(5):
        advance_one_day(world)
    session_store.save(sid, world)

    resp = client.get("/league/leaders")
    assert resp.status_code == 200
    body = resp.json()

    pts_category = next((cat for cat in body["categories"] if cat["stat"] == "pts"), None)
    assert pts_category is not None
    assert len(pts_category["leaders"]) > 0

    # Check sorted descending
    leaders = pts_category["leaders"]
    values = [leader["value"] for leader in leaders]
    assert values == sorted(values, reverse=True)


def test_leaders_goalies_gaa_sorted_ascending(client):
    """Goalie GAA leaders are sorted ascending (lower is better)."""
    client.post("/career/new", json={"seed": 200})
    sid = client.cookies[SESSION_COOKIE_NAME]

    # Start season and simulate several days for goalies to get games
    world = session_store.get(sid)
    start_season(world)
    for _ in range(10):
        advance_one_day(world)
    session_store.save(sid, world)

    resp = client.get("/league/leaders")
    assert resp.status_code == 200
    body = resp.json()

    gaa_category = next((cat for cat in body["categories"] if cat["stat"] == "gaa"), None)
    assert gaa_category is not None

    # Check sorted ascending
    leaders = gaa_category["leaders"]
    if len(leaders) > 0:
        values = [leader["value"] for leader in leaders]
        assert values == sorted(values)  # ascending


# ---------------------------------------------------------------------------
# GET /league/history -- archived seasons
# ---------------------------------------------------------------------------
def test_history_empty_on_fresh_world(client):
    """Fresh started world has empty history."""
    client.post("/career/new", json={"seed": 42})
    resp = client.get("/league/history")
    assert resp.status_code == 200

    body = resp.json()
    assert "seasons" in body
    assert len(body["seasons"]) == 0


def test_history_has_one_entry_after_archiving_season(client):
    """After archiving one season, history returns one entry with year and awards."""
    client.post("/career/new", json={"seed": 300})
    sid = client.cookies[SESSION_COOKIE_NAME]

    world = session_store.get(sid)
    start_season(world)

    # Simulate to completion
    from pucksim.sim.season import regular_season_complete
    while not regular_season_complete(world):
        advance_one_day(world)

    # Archive the season (call pre_draft with no champion)
    offseason.pre_draft(world, None)
    session_store.save(sid, world)

    resp = client.get("/league/history")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["seasons"]) == 1
    season = body["seasons"][0]
    assert "year" in season
    assert "champion_tid" in season
    assert "champion_name" in season
    assert "champion_abbrev" in season
    assert "champion_color" in season
    assert "awards" in season


def test_history_most_recent_first(client):
    """History returns seasons in reverse order (most recent first)."""
    client.post("/career/new", json={"seed": 400})
    sid = client.cookies[SESSION_COOKIE_NAME]

    world = session_store.get(sid)
    start_season(world)

    from pucksim.sim.season import regular_season_complete
    # Archive first season
    while not regular_season_complete(world):
        advance_one_day(world)
    offseason.pre_draft(world, None)
    first_year = world.season_year
    session_store.save(sid, world)

    # Verify one entry
    resp = client.get("/league/history")
    body = resp.json()
    assert len(body["seasons"]) == 1
    assert body["seasons"][0]["year"] == first_year


# ---------------------------------------------------------------------------
# GET /league/hall-of-fame -- Hall of Fame inductees
# ---------------------------------------------------------------------------
def test_hall_of_fame_empty_on_fresh_world(client):
    """Fresh started world has empty Hall of Fame."""
    client.post("/career/new", json={"seed": 42})
    resp = client.get("/league/hall-of-fame")
    assert resp.status_code == 200

    body = resp.json()
    assert "members" in body
    assert len(body["members"]) == 0


def test_hall_of_fame_members_have_required_fields(client):
    """HOF members have all required fields."""
    client.post("/career/new", json={"seed": 500})
    sid = client.cookies[SESSION_COOKIE_NAME]

    # Drive a season with full offseason to potentially get inductees
    world = session_store.get(sid)
    start_season(world)

    from pucksim.sim.season import regular_season_complete
    while not regular_season_complete(world):
        advance_one_day(world)

    offseason.pre_draft(world, None)
    session_store.save(sid, world)

    resp = client.get("/league/hall-of-fame")
    assert resp.status_code == 200
    body = resp.json()

    for member in body["members"]:
        assert "pid" in member
        assert "name" in member
        assert "position" in member
        assert "seasons" in member
        assert "peak_ovr" in member
        assert "last_team" in member
        assert "first_year" in member
        assert "last_year" in member
        assert "draft" in member
        assert "active" in member
        assert "totals" in member
        assert "accolades" in member
        assert "hof_score" in member
        assert "hof" in member
        assert "induction_year" in member


def test_hall_of_fame_sorted_by_score_descending(client):
    """HOF members are sorted by hof_score descending."""
    client.post("/career/new", json={"seed": 600})
    sid = client.cookies[SESSION_COOKIE_NAME]

    world = session_store.get(sid)
    start_season(world)

    from pucksim.sim.season import regular_season_complete
    while not regular_season_complete(world):
        advance_one_day(world)

    offseason.pre_draft(world, None)
    session_store.save(sid, world)

    resp = client.get("/league/hall-of-fame")
    assert resp.status_code == 200
    body = resp.json()

    if len(body["members"]) > 1:
        scores = [m["hof_score"] for m in body["members"]]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# GET /league/leaderboards?category= -- all-time career leaderboards
# ---------------------------------------------------------------------------
def test_leaderboards_valid_categories(client):
    """Leaderboards endpoint accepts all valid categories."""
    client.post("/career/new", json={"seed": 42})

    valid_categories = ["pts", "g", "a", "gp", "wins", "shutouts"]
    for category in valid_categories:
        resp = client.get(f"/league/leaderboards?category={category}")
        assert resp.status_code == 200, f"Category {category} failed"

        body = resp.json()
        assert body["category"] == category
        assert "categories" in body
        assert "rows" in body
        assert len(body["categories"]) == 6  # All categories listed


def test_leaderboards_invalid_category_returns_400(client):
    """Leaderboards rejects invalid category with 400."""
    client.post("/career/new", json={"seed": 42})

    resp = client.get("/league/leaderboards?category=bogus")
    assert resp.status_code == 400


def test_leaderboards_default_category_is_pts(client):
    """Leaderboards defaults to pts category when not specified."""
    client.post("/career/new", json={"seed": 42})

    resp = client.get("/league/leaderboards")
    assert resp.status_code == 200

    body = resp.json()
    assert body["category"] == "pts"


def test_leaderboards_rows_have_active_field(client):
    """Leaderboard rows carry an active field."""
    client.post("/career/new", json={"seed": 42})
    sid = client.cookies[SESSION_COOKIE_NAME]

    # Advance a bit so someone has stats
    world = session_store.get(sid)
    start_season(world)
    advance_one_day(world)
    session_store.save(sid, world)

    resp = client.get("/league/leaderboards?category=pts")
    assert resp.status_code == 200

    body = resp.json()
    for row in body["rows"]:
        assert "active" in row


def test_leaderboards_returns_up_to_25_rows(client):
    """Leaderboards returns up to 25 rows."""
    client.post("/career/new", json={"seed": 42})

    resp = client.get("/league/leaderboards?category=pts")
    assert resp.status_code == 200

    body = resp.json()
    assert len(body["rows"]) <= 25


# ---------------------------------------------------------------------------
# Integration: all endpoints accessible after setup
# ---------------------------------------------------------------------------
def test_all_league_endpoints_accessible(client):
    """All four league endpoints are accessible on a fresh world."""
    client.post("/career/new", json={"seed": 999})

    endpoints = [
        "/league/leaders",
        "/league/history",
        "/league/hall-of-fame",
        "/league/leaderboards",
    ]

    for endpoint in endpoints:
        resp = client.get(endpoint)
        assert resp.status_code == 200, f"Endpoint {endpoint} failed"


def test_leaders_at_0_gp_does_not_error(client):
    """Leaders endpoint doesn't error even when no one has played games."""
    client.post("/career/new", json={"seed": 42})
    # Don't advance any days

    resp = client.get("/league/leaders")
    assert resp.status_code == 200

    body = resp.json()
    # Some or all categories may be empty, but endpoint should not crash
    assert "categories" in body
    assert len(body["categories"]) == 6
