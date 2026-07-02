"""Tests for pucksim.web -- DEVPLAN.md Step 2.9a done-criteria.

Uses ``fastapi.testclient.TestClient`` against a real app instance (``pucksim.web.app.app``) --
no mocking of domain logic; every request exercises the real ``build_world``/``save.store``/
``models.league.standings`` call chain, same as HoopR's own web-layer test philosophy.

``monkeypatch.chdir(tmp_path)`` isolates ``saves/`` the same way ``tests/test_save.py`` already
does (``save.store.saves_dir()`` resolves relative to the current working directory) so these
tests never touch the repo's real ``./saves`` directory.

Each test gets its own fresh ``TestClient`` (a fresh cookie jar) so sessions from one test never
leak into another -- ``pucksim.web.session.session_store`` is a module-level singleton shared
across the whole test process, but since sessions are looked up by an unguessable per-test cookie
value, tests don't interfere with each other's stored Worlds even though the store itself isn't
reset between tests.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from pucksim.web.app import app
from pucksim.web.session import SESSION_COOKIE_NAME

_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /career/new
# ---------------------------------------------------------------------------
def test_new_career_creates_a_career_with_expected_shape(client):
    resp = client.post("/career/new", json={"seed": 42})
    assert resp.status_code == 200

    body = resp.json()
    assert body["season_year"] == 2025
    assert body["phase"] == "preseason"
    assert body["day"] == 0
    assert body["standings_rule"] == "standard"
    assert body["user_team_id"] is not None


def test_new_career_sets_a_session_cookie(client):
    resp = client.post("/career/new", json={"seed": 1})
    assert SESSION_COOKIE_NAME in resp.cookies


def test_new_career_honors_seed_determinism():
    """Two separate clients/sessions created with the same seed produce the same league (and
    thus the same default user team), proving /career/new threads the seed through to
    build_world() rather than ignoring it."""
    c1 = TestClient(app)
    c2 = TestClient(app)
    body1 = c1.post("/career/new", json={"seed": 123}).json()
    body2 = c2.post("/career/new", json={"seed": 123}).json()
    assert body1["user_team_id"] == body2["user_team_id"]


def test_new_career_honors_user_team_abbrev(client):
    default_body = client.post("/career/new", json={"seed": 5}).json()
    default_team_id = default_body["user_team_id"]

    # Fetch standings (any team list works) to find a *different* team's abbrev to request
    # explicitly, then start a new career picking that team on purpose.
    all_teams = client.get("/career/standings").json()
    other = next(t for t in all_teams if t["id"] != default_team_id)

    resp = client.post("/career/new", json={"seed": 5, "user_team_abbrev": other["abbrev"]})
    assert resp.status_code == 200
    assert resp.json()["user_team_id"] == other["id"]


def test_new_career_rejects_unknown_user_team_abbrev(client):
    resp = client.post("/career/new", json={"seed": 5, "user_team_abbrev": "ZZZ-NOT-A-TEAM"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /career -- no session vs. cookie round-trip
# ---------------------------------------------------------------------------
def test_get_career_without_a_session_is_a_clean_404(client):
    resp = client.get("/career")
    assert resp.status_code == 404


def test_get_career_round_trips_through_the_session_cookie(client):
    created = client.post("/career/new", json={"seed": 77}).json()
    fetched = client.get("/career").json()
    assert fetched == created


def test_different_clients_get_independent_sessions():
    c1 = TestClient(app)
    c2 = TestClient(app)
    c1.post("/career/new", json={"seed": 1})
    # c2 never created a career -- its own (empty) cookie jar means no session for it.
    resp = c2.get("/career")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /career/save + POST /career/load round-trip
# ---------------------------------------------------------------------------
def test_save_then_load_round_trips_season_day_and_phase(client):
    from pucksim.sim.season import advance_one_day, start_season
    from pucksim.web.session import session_store

    created = client.post("/career/new", json={"seed": 9}).json()
    assert created["phase"] == "preseason"

    # Directly advance the session's World a bit (no /career/advance-day endpoint exists yet --
    # that's Step 2.9b's gameplay-endpoint scope, out of bounds here) so save/load has real
    # non-default day/phase state to prove it actually round-trips, not just re-returns the
    # freshly-generated default.
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    advance_one_day(world)
    advance_one_day(world)
    session_store.save(sid, world)

    mid = client.get("/career").json()
    assert mid["phase"] == "regular_season"
    assert mid["day"] > 0

    save_resp = client.post("/career/save", json={"slot": "roundtrip-test"})
    assert save_resp.status_code == 200
    assert save_resp.json()["slot"] == "roundtrip-test"

    # Mutate the live session further so load-back is a real, observable change.
    world2 = session_store.get(sid)
    advance_one_day(world2)
    session_store.save(sid, world2)
    changed = client.get("/career").json()
    assert changed["day"] > mid["day"]

    load_resp = client.post("/career/load", json={"slot": "roundtrip-test"})
    assert load_resp.status_code == 200
    loaded = load_resp.json()
    assert loaded["phase"] == mid["phase"]
    assert loaded["day"] == mid["day"]

    # And the session's own World was actually replaced, not just the response body.
    after = client.get("/career").json()
    assert after == loaded


def test_load_unknown_slot_is_a_clean_404(client):
    client.post("/career/new", json={"seed": 1})
    resp = client.post("/career/load", json={"slot": "does-not-exist"})
    assert resp.status_code == 404


def test_load_with_no_prior_session_creates_one():
    """POST /career/load is legal as a client's very first call -- no /career/new needed first
    just to get a session cookie (see routers/career.py's load_career docstring)."""
    c = TestClient(app)
    c.post("/career/new", json={"seed": 3})
    c.post("/career/save", json={"slot": "fresh-load-test"})

    fresh_client = TestClient(app)
    assert SESSION_COOKIE_NAME not in fresh_client.cookies
    resp = fresh_client.post("/career/load", json={"slot": "fresh-load-test"})
    assert resp.status_code == 200
    assert SESSION_COOKIE_NAME in resp.cookies

    follow_up = fresh_client.get("/career")
    assert follow_up.status_code == 200


# ---------------------------------------------------------------------------
# GET /career/saves
# ---------------------------------------------------------------------------
def test_get_saves_lists_the_saved_slot(client):
    client.post("/career/new", json={"seed": 11})
    client.post("/career/save", json={"slot": "list-me"})

    resp = client.get("/career/saves")
    assert resp.status_code == 200
    assert "list-me" in resp.json()


def test_save_without_slot_uses_autosave_slot(client):
    from pucksim.config import AUTOSAVE_SLOT

    client.post("/career/new", json={"seed": 12})
    resp = client.post("/career/save", json={})
    assert resp.status_code == 200
    assert resp.json()["slot"] == AUTOSAVE_SLOT
    assert AUTOSAVE_SLOT in client.get("/career/saves").json()


def test_save_without_a_session_is_a_clean_404(client):
    resp = client.post("/career/save", json={"slot": "no-session"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /career/standings
# ---------------------------------------------------------------------------
def test_standings_returns_every_team_without_erroring_on_a_fresh_world(client):
    client.post("/career/new", json={"seed": 13})
    resp = client.get("/career/standings")
    assert resp.status_code == 200

    entries = resp.json()
    assert len(entries) == 32
    for entry in entries:
        assert entry["points"] == 0
        assert entry["wins"] == 0
        assert entry["losses"] == 0
        assert entry["ot_losses"] == 0
        assert entry["record"] is None  # no games played yet


def test_standings_are_correctly_sorted_by_points(client):
    from pucksim.sim.season import advance_one_day, start_season
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 14})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    for _ in range(5):
        advance_one_day(world)
    session_store.save(sid, world)

    resp = client.get("/career/standings")
    entries = resp.json()
    assert len(entries) == 32

    points = [e["points"] for e in entries]
    assert points == sorted(points, reverse=True)

    # At least one game should have been played by now across 5 sim days.
    assert any(e["wins"] + e["losses"] + e["ot_losses"] > 0 for e in entries)


def test_standings_without_a_session_is_a_clean_404(client):
    resp = client.get("/career/standings")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Team colors surfaced in DTOs
# ---------------------------------------------------------------------------
def test_team_colors_present_and_valid_hex_in_standings(client):
    client.post("/career/new", json={"seed": 15})
    resp = client.get("/career/standings")
    entries = resp.json()
    assert len(entries) == 32
    seen_pairs = set()
    for entry in entries:
        assert _HEX_COLOR_RE.match(entry["primary_color"]), entry["primary_color"]
        assert _HEX_COLOR_RE.match(entry["secondary_color"]), entry["secondary_color"]
        seen_pairs.add((entry["primary_color"], entry["secondary_color"]))
    assert len(seen_pairs) == 32


# ---------------------------------------------------------------------------
# POST /season/start
# ---------------------------------------------------------------------------
def test_start_season_generates_schedule_and_advances_phase(client):
    """Regression test (found during review): nothing in the web layer originally called
    sim.season.start_season(), so a fresh career's schedule stayed empty and phase stuck on
    'preseason' forever -- every other /season/* endpoint was unreachable-in-practice for a
    real client with no way to call start_season() directly. This pins the fix."""
    client.post("/career/new", json={"seed": 30})

    before = client.get("/career").json()
    assert before["phase"] == "preseason"
    assert client.get("/season/schedule").json() == []

    resp = client.post("/season/start")
    assert resp.status_code == 200
    body = resp.json()
    assert body["phase"] == "regular_season"
    assert body["day"] == 0

    schedule = client.get("/season/schedule").json()
    assert len(schedule) == 1312  # 32 teams * 82 games / 2


def test_start_season_twice_is_a_clean_400(client):
    client.post("/career/new", json={"seed": 31})
    client.post("/season/start")
    resp = client.post("/season/start")
    assert resp.status_code == 400


def test_start_season_without_a_session_is_a_clean_404(client):
    resp = client.post("/season/start")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /season/schedule
# ---------------------------------------------------------------------------
def test_schedule_returns_all_games(client):
    from pucksim.sim.season import start_season
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 16})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    session_store.save(sid, world)

    resp = client.get("/season/schedule")
    assert resp.status_code == 200

    schedule = resp.json()
    assert len(schedule) > 0
    # In a 32-team league with 82 games per team, there should be 32*82/2 = 1312 games
    assert len(schedule) == 1312

    # Spot-check a game's shape
    game = schedule[0]
    assert "gid" in game
    assert "day" in game
    assert "home" in game
    assert "away" in game
    assert "home_score" in game
    assert "away_score" in game
    assert "played" in game
    assert game["played"] is False  # fresh schedule, no games played yet


def test_schedule_without_a_session_is_a_clean_404(client):
    resp = client.get("/season/schedule")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /season/advance-day
# ---------------------------------------------------------------------------
def test_advance_day_simulates_games_and_returns_new_phase(client):
    from pucksim.sim.season import start_season
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 17})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    session_store.save(sid, world)

    resp = client.post("/season/advance-day")
    assert resp.status_code == 200

    body = resp.json()
    assert body["day"] == 1
    assert body["phase"] == "regular_season"
    # A fresh day should have some games (not all days have games, but most do)
    # For the first day of a fresh schedule, there should definitely be games
    assert isinstance(body["games_played"], list)


def test_advance_day_changes_world_state(client):
    from pucksim.sim.season import start_season
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 18})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    session_store.save(sid, world)

    initial = client.get("/career").json()
    assert initial["day"] == 0

    client.post("/season/advance-day")

    updated = client.get("/career").json()
    assert updated["day"] == 1


def test_advance_day_without_a_session_is_a_clean_404(client):
    resp = client.post("/season/advance-day")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /season/games/{gid}/sim
# ---------------------------------------------------------------------------
def test_sim_single_game_on_demand(client):
    from pucksim.sim.season import start_season
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 19})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    session_store.save(sid, world)

    # Find an unplayed game
    schedule_resp = client.get("/season/schedule").json()
    unplayed_game = next(g for g in schedule_resp if not g["played"])
    gid = unplayed_game["gid"]

    # Sim it
    resp = client.post(f"/season/games/{gid}/sim")
    assert resp.status_code == 200

    body = resp.json()
    assert body["gid"] == gid
    assert body["home_score"] >= 0
    assert body["away_score"] >= 0
    assert isinstance(body["went_ot"], bool)
    assert isinstance(body["went_so"], bool)


def test_sim_single_game_marks_game_as_played(client):
    from pucksim.sim.season import start_season
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 20})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    session_store.save(sid, world)

    schedule_resp = client.get("/season/schedule").json()
    unplayed_game = next(g for g in schedule_resp if not g["played"])
    gid = unplayed_game["gid"]

    client.post(f"/season/games/{gid}/sim")

    # Verify the game is now marked played
    updated_schedule = client.get("/season/schedule").json()
    updated_game = next(g for g in updated_schedule if g["gid"] == gid)
    assert updated_game["played"] is True


def test_sim_single_game_updates_team_records_and_standings(client):
    """Regression test (found during review): an earlier version of this endpoint called
    sim.engine.simulate_game() directly and reimplemented a partial subset of
    sim.season._apply_result() inline, silently skipping Team.record_result() -- so a game
    simmed via this endpoint never showed up in either team's win/loss/streak or in
    standings points. The endpoint now delegates to sim.season.sim_one() (the same function
    advance_one_day() calls per game), which correctly applies the full result. This test
    pins that behavior so a future refactor can't silently regress back to the partial
    reimplementation."""
    from pucksim.sim.season import start_season
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 23})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    session_store.save(sid, world)

    schedule_resp = client.get("/season/schedule").json()
    unplayed_game = next(g for g in schedule_resp if not g["played"])
    gid, home_id, away_id = unplayed_game["gid"], unplayed_game["home"], unplayed_game["away"]

    before = {e["id"]: e for e in client.get("/career/standings").json()}
    assert before[home_id]["wins"] + before[home_id]["losses"] + before[home_id]["ot_losses"] == 0
    assert before[away_id]["wins"] + before[away_id]["losses"] + before[away_id]["ot_losses"] == 0

    client.post(f"/season/games/{gid}/sim")

    after = {e["id"]: e for e in client.get("/career/standings").json()}
    home_decisions = after[home_id]["wins"] + after[home_id]["losses"] + after[home_id]["ot_losses"]
    away_decisions = after[away_id]["wins"] + after[away_id]["losses"] + after[away_id]["ot_losses"]
    assert home_decisions == 1
    assert away_decisions == 1
    # Exactly one side won (games created via a fresh regular-season schedule are never ties
    # under the default "standard" rule this career started with).
    assert (after[home_id]["wins"] == 1) != (after[away_id]["wins"] == 1)


def test_sim_single_game_cant_sim_twice(client):
    from pucksim.sim.season import start_season
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 21})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    session_store.save(sid, world)

    schedule_resp = client.get("/season/schedule").json()
    unplayed_game = next(g for g in schedule_resp if not g["played"])
    gid = unplayed_game["gid"]

    client.post(f"/season/games/{gid}/sim")

    # Try to sim it again -- should fail
    resp = client.post(f"/season/games/{gid}/sim")
    assert resp.status_code == 400


def test_sim_single_game_nonexistent_game_is_404(client):
    client.post("/career/new", json={"seed": 22})
    resp = client.post("/season/games/99999/sim")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /season/games/{gid}/boxscore
# ---------------------------------------------------------------------------
def test_boxscore_retrieval_after_sim(client):
    from pucksim.sim.season import start_season
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 23})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    session_store.save(sid, world)

    schedule_resp = client.get("/season/schedule").json()
    unplayed_game = next(g for g in schedule_resp if not g["played"])
    gid = unplayed_game["gid"]

    sim_resp = client.post(f"/season/games/{gid}/sim").json()

    # Now fetch the box score
    resp = client.get(f"/season/games/{gid}/boxscore")
    assert resp.status_code == 200

    body = resp.json()
    assert body["gid"] == gid
    assert body["home_score"] == sim_resp["home_score"]
    assert body["away_score"] == sim_resp["away_score"]
    assert body["went_ot"] == sim_resp["went_ot"]
    assert body["went_so"] == sim_resp["went_so"]
    assert isinstance(body["skater_box"], dict)
    assert isinstance(body["goalie_box"], dict)


def test_boxscore_not_yet_played_is_400(client):
    from pucksim.sim.season import start_season
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 24})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    session_store.save(sid, world)

    schedule_resp = client.get("/season/schedule").json()
    unplayed_game = next(g for g in schedule_resp if not g["played"])
    gid = unplayed_game["gid"]

    resp = client.get(f"/season/games/{gid}/boxscore")
    assert resp.status_code == 400


def test_boxscore_nonexistent_game_is_404(client):
    client.post("/career/new", json={"seed": 25})
    resp = client.get("/season/games/99999/boxscore")
    assert resp.status_code == 404


def test_boxscore_reconciliation_skaters_and_goalies_separate(client):
    """Box scores have two separate shapes (skaters vs. goalies), per DESIGN.md point 9."""
    from pucksim.sim.season import start_season
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 26})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    start_season(world)
    session_store.save(sid, world)

    schedule_resp = client.get("/season/schedule").json()
    unplayed_game = next(g for g in schedule_resp if not g["played"])
    gid = unplayed_game["gid"]

    client.post(f"/season/games/{gid}/sim")

    resp = client.get(f"/season/games/{gid}/boxscore").json()

    # Skater box should have skater-specific fields (g, a, sog, etc.)
    # Goalie box should have goalie-specific fields (shots_faced, saves, etc.)
    for pid, skater_line in resp["skater_box"].items():
        assert "g" in skater_line
        assert "a" in skater_line
        assert "sog" in skater_line

    for pid, goalie_line in resp["goalie_box"].items():
        assert "shots_faced" in goalie_line
        assert "saves" in goalie_line
        assert "goals_against" in goalie_line


# ---------------------------------------------------------------------------
# GET /season/playoffs/bracket
# ---------------------------------------------------------------------------
def test_playoffs_bracket_not_yet_in_playoffs_returns_none(client):
    client.post("/career/new", json={"seed": 27})
    resp = client.get("/season/playoffs/bracket")
    assert resp.status_code == 200
    assert resp.json() is None


def test_playoffs_bracket_without_session_is_404(client):
    resp = client.get("/season/playoffs/bracket")
    assert resp.status_code == 404
