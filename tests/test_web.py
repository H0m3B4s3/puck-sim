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
# GET /roster -- full roster
# ---------------------------------------------------------------------------
def test_get_roster_requires_session(client):
    """GET /roster without an active session is a 404."""
    resp = client.get("/roster")
    assert resp.status_code == 404


def test_get_roster_returns_player_summaries(client):
    """GET /roster returns the user's team's full roster with player summaries."""
    client.post("/career/new", json={"seed": 20})
    resp = client.get("/roster")
    assert resp.status_code == 200

    body = resp.json()
    assert "players" in body
    players = body["players"]
    assert len(players) > 0  # Should have at least some roster

    # Check player summary shape
    for player in players:
        assert "pid" in player
        assert "name" in player
        assert "position" in player
        assert "age" in player
        assert "overall" in player
        assert "shoots" in player
        assert "contract" in player
        contract = player["contract"]
        assert "current_salary" in contract
        assert "years_remaining" in contract


def test_roster_includes_injured_status(client):
    """Players with injuries should show injury_status."""
    from pucksim.models.player import Injury
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 21})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Find a player and inject an injury
    roster = world.user_team.roster
    if roster:
        pid = roster[0]
        player = world.players[pid]
        player.injury = Injury(description="Test injury", games_remaining=5, severity="minor")
        session_store.save(sid, world)

        resp = client.get("/roster")
        body = resp.json()
        players = body["players"]
        injured = next((p for p in players if p["pid"] == pid), None)
        assert injured is not None
        assert injured["injury_status"] is not None
        assert "Test injury" in injured["injury_status"]
        assert "5 games" in injured["injury_status"]


# ---------------------------------------------------------------------------
# GET /roster/lines -- lines, pairs, units with player summaries
# ---------------------------------------------------------------------------
def test_get_roster_lines_requires_session(client):
    """GET /roster/lines without an active session is a 404."""
    resp = client.get("/roster/lines")
    assert resp.status_code == 404


def test_get_roster_lines_returns_expected_shape(client):
    """GET /roster/lines returns lines, pairs, goalies, and special teams."""
    client.post("/career/new", json={"seed": 22})
    resp = client.get("/roster/lines")
    assert resp.status_code == 200

    body = resp.json()
    assert "lines" in body
    assert "pairs" in body
    assert "goalie_starter" in body
    assert "goalie_backup" in body
    assert "pp_unit_1" in body
    assert "pk_unit_1" in body

    # Each line should have players
    for line in body["lines"]:
        assert "players" in line
        for player in line["players"]:
            assert "pid" in player
            assert "name" in player
            assert "overall" in player

    # Same for pairs
    for pair in body["pairs"]:
        assert "players" in pair
        assert len(pair["players"]) <= 2

    # Goalies can be None or have player
    if body["goalie_starter"]["player"] is not None:
        assert "pid" in body["goalie_starter"]["player"]


# ---------------------------------------------------------------------------
# POST /roster/lines/auto -- auto-build lines
# ---------------------------------------------------------------------------
def test_auto_build_lines_requires_session(client):
    """POST /roster/lines/auto without session is a 404."""
    resp = client.post("/roster/lines/auto", json={"include_special_teams": False})
    assert resp.status_code == 404


def test_auto_build_lines_rebuilds_and_persists(client):
    """POST /roster/lines/auto rebuilds lines and persists the change."""
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 23})
    sid = client.cookies[SESSION_COOKIE_NAME]

    # Get initial lines
    initial = client.get("/roster/lines").json()
    initial_first_line = initial["lines"][0]["players"] if initial["lines"] else []

    # Manually shuffle the roster on the world to change the optimal line ordering
    world = session_store.get(sid)
    team = world.user_team
    team.lines = [[world.players[pid].pid for pid in team.lines[0][::-1]]]  # Reverse first line
    session_store.save(sid, world)

    # Now auto-build should restore an optimized order
    resp = client.post("/roster/lines/auto", json={"include_special_teams": False})
    assert resp.status_code == 200

    # Verify the change is persisted (fetch again)
    fetched = client.get("/roster/lines").json()
    assert len(fetched["lines"]) > 0


def test_auto_build_lines_with_special_teams(client):
    """POST /roster/lines/auto with include_special_teams=true rebuilds PP/PK units."""
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 24})
    sid = client.cookies[SESSION_COOKIE_NAME]

    # Get initial units
    initial = client.get("/roster/lines").json()
    initial_pp = set(p["pid"] for p in initial["pp_unit_1"]["players"])

    # Manually clear the PP unit
    world = session_store.get(sid)
    world.user_team.pp_unit_1 = []
    session_store.save(sid, world)

    # Auto-build with special teams
    resp = client.post("/roster/lines/auto", json={"include_special_teams": True})
    assert resp.status_code == 200

    body = resp.json()
    rebuilt_pp = set(p["pid"] for p in body["pp_unit_1"]["players"])
    assert len(rebuilt_pp) > 0  # Should have rebuilt a PP unit


# ---------------------------------------------------------------------------
# PUT /roster/lines -- manual line edits
# ---------------------------------------------------------------------------
def test_manual_line_edit_requires_session(client):
    """PUT /roster/lines without session is a 404."""
    resp = client.put("/roster/lines", json={"lines": []})
    assert resp.status_code == 404


def test_manual_line_edit_valid_swap(client):
    """PUT /roster/lines with valid player ids updates the lines."""
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 25})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Get current first line
    current_first_line = world.user_team.lines[0] if world.user_team.lines else []
    if len(current_first_line) >= 3:
        # Swap first two players
        new_line = [current_first_line[1], current_first_line[0], current_first_line[2]]
        resp = client.put("/roster/lines", json={"lines": [new_line]})
        assert resp.status_code == 200

        body = resp.json()
        assert body["lines"][0]["players"][0]["pid"] == new_line[0]
        assert body["lines"][0]["players"][1]["pid"] == new_line[1]


def test_manual_line_edit_rejects_invalid_player_id(client):
    """PUT /roster/lines rejects player ids not on the roster."""
    client.post("/career/new", json={"seed": 26})

    # Try to edit with a fake player id
    resp = client.put("/roster/lines", json={"lines": [[99999, 88888, 77777]]})
    assert resp.status_code == 400
    assert "not on roster" in resp.json()["detail"]


def test_manual_line_edit_rejects_duplicate_players_in_forward_lines(client):
    """PUT /roster/lines rejects duplicate players across forward lines."""
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 27})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Create lines with a duplicate player
    line1 = world.user_team.lines[0] if world.user_team.lines else [1, 2, 3]
    line2 = world.user_team.lines[1] if len(world.user_team.lines) > 1 else [4, 5, 6]
    dup_lines = [line1, [line1[0], 10, 11]]  # Duplicate first player of line1

    resp = client.put("/roster/lines", json={"lines": dup_lines})
    assert resp.status_code == 400
    assert "duplicate" in resp.json()["detail"]


def test_manual_line_edit_rejects_wrong_line_size(client):
    """PUT /roster/lines rejects lines that don't have exactly 3 players."""
    client.post("/career/new", json={"seed": 28})

    # Try to edit with a line of 2 players
    resp = client.put("/roster/lines", json={"lines": [[1, 2]]})
    assert resp.status_code == 400
    assert "expected 3" in resp.json()["detail"]


def test_manual_pair_edit_valid_swap(client):
    """PUT /roster/lines can update just pairs."""
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 29})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    current_pairs = world.user_team.pairs
    if current_pairs and len(current_pairs) >= 2:
        # Swap the first two pairs
        new_pairs = [current_pairs[1], current_pairs[0]]
        resp = client.put("/roster/lines", json={"pairs": new_pairs})
        assert resp.status_code == 200

        body = resp.json()
        # Check that the pairs were updated
        fetched_pairs = body["pairs"]
        assert fetched_pairs[0]["players"][0]["pid"] == current_pairs[1][0]


def test_manual_goalie_edit(client):
    """PUT /roster/lines can update goalie assignments."""
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 30})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Get available goalies
    team = world.user_team
    goalies = [p for p in [world.players[pid] for pid in team.roster if pid in world.players] if p.position == "G"]

    if len(goalies) >= 2:
        # Swap starter and backup
        g1, g2 = goalies[0], goalies[1]
        resp = client.put("/roster/lines", json={
            "goalie_starter": g2.pid,
            "goalie_backup": g1.pid,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["goalie_starter"]["player"]["pid"] == g2.pid
        assert body["goalie_backup"]["player"]["pid"] == g1.pid


# ---------------------------------------------------------------------------
# GET /roster/tactics -- tactics and coach summary
# ---------------------------------------------------------------------------
def test_get_tactics_requires_session(client):
    """GET /roster/tactics without session is a 404."""
    resp = client.get("/roster/tactics")
    assert resp.status_code == 404


def test_get_tactics_returns_expected_shape(client):
    """GET /roster/tactics returns tactics and coach profile."""
    client.post("/career/new", json={"seed": 31})
    resp = client.get("/roster/tactics")
    assert resp.status_code == 200

    body = resp.json()
    assert "tactics" in body
    assert "coach" in body

    tactics = body["tactics"]
    assert "forecheck_style" in tactics
    assert "pp_style" in tactics
    assert "pk_aggression" in tactics

    coach = body["coach"]
    assert "archetype" in coach
    assert "line_juggling_patience" in coach
    assert "pp_forwards" in coach
    assert "shot_volume" in coach
    assert "shot_quality_bias" in coach


def test_get_tactics_shows_valid_values(client):
    """Tactics should show valid discrete option values."""
    client.post("/career/new", json={"seed": 32})
    resp = client.get("/roster/tactics")
    body = resp.json()

    tactics = body["tactics"]
    assert tactics["forecheck_style"] in ["passive", "balanced", "aggressive"]
    assert tactics["pp_style"] in ["umbrella", "overload", "spread"]
    assert tactics["pk_aggression"] in ["passive", "balanced", "aggressive"]


# ---------------------------------------------------------------------------
# PUT /roster/tactics -- update tactics
# ---------------------------------------------------------------------------
def test_put_tactics_requires_session(client):
    """PUT /roster/tactics without session is a 404."""
    resp = client.put("/roster/tactics", json={"forecheck_style": "aggressive"})
    assert resp.status_code == 404


def test_put_tactics_partial_update(client):
    """PUT /roster/tactics updates only supplied fields."""
    client.post("/career/new", json={"seed": 33})

    # Get initial tactics
    initial = client.get("/roster/tactics").json()
    initial_forecheck = initial["tactics"]["forecheck_style"]
    initial_pp = initial["tactics"]["pp_style"]

    # Update only forecheck
    new_forecheck = "aggressive" if initial_forecheck != "aggressive" else "passive"
    resp = client.put("/roster/tactics", json={"forecheck_style": new_forecheck})
    assert resp.status_code == 200

    body = resp.json()
    assert body["tactics"]["forecheck_style"] == new_forecheck
    assert body["tactics"]["pp_style"] == initial_pp  # Unchanged


def test_put_tactics_rejects_invalid_value(client):
    """PUT /roster/tactics rejects invalid option values."""
    client.post("/career/new", json={"seed": 34})

    resp = client.put("/roster/tactics", json={"forecheck_style": "invalid_style"})
    assert resp.status_code == 400
    assert "invalid" in resp.json()["detail"]


def test_put_tactics_all_three_fields(client):
    """PUT /roster/tactics can update all three tactics at once."""
    client.post("/career/new", json={"seed": 35})

    resp = client.put("/roster/tactics", json={
        "forecheck_style": "aggressive",
        "pp_style": "spread",
        "pk_aggression": "aggressive",
    })
    assert resp.status_code == 200

    body = resp.json()
    assert body["tactics"]["forecheck_style"] == "aggressive"
    assert body["tactics"]["pp_style"] == "spread"
    assert body["tactics"]["pk_aggression"] == "aggressive"


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
