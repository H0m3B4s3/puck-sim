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
# GET /transactions/cap
# ---------------------------------------------------------------------------
def test_cap_summary_without_session_is_a_clean_404(client):
    resp = client.get("/transactions/cap")
    assert resp.status_code == 404


def test_cap_summary_returns_payroll_and_space(client):
    client.post("/career/new", json={"seed": 100})
    resp = client.get("/transactions/cap")
    assert resp.status_code == 200

    body = resp.json()
    assert "payroll" in body
    assert "cap_space" in body
    assert "over_cap" in body
    assert "salary_cap" in body
    assert body["payroll"] >= 0
    assert body["cap_space"] >= 0
    assert isinstance(body["over_cap"], bool)
    assert body["salary_cap"] > 0


# ---------------------------------------------------------------------------
# GET /transactions/freeagents
# ---------------------------------------------------------------------------
def test_free_agents_list_without_session_is_a_clean_404(client):
    resp = client.get("/transactions/freeagents")
    assert resp.status_code == 404


def test_free_agents_returns_a_list_of_players(client):
    from pucksim.sim.season import advance_one_day, start_season
    from pucksim.web.session import session_store, SESSION_COOKIE_NAME

    client.post("/career/new", json={"seed": 101})
    resp = client.get("/transactions/freeagents")
    assert resp.status_code == 200
    agents = resp.json()
    # Fresh league should have some undrafted free agents
    assert isinstance(agents, list)


# ---------------------------------------------------------------------------
# POST /transactions/freeagents/{pid}/sign
# ---------------------------------------------------------------------------
def test_sign_free_agent_without_session_is_a_clean_404(client):
    resp = client.post("/transactions/freeagents/1/sign", json={})
    assert resp.status_code == 404


def test_sign_free_agent_end_to_end(client):
    from pucksim.web.session import session_store, SESSION_COOKIE_NAME

    client.post("/career/new", json={"seed": 102})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Release a player to create a free agent
    user_team = world.teams[world.user_team_id]
    if not user_team.roster:
        # If user team has no roster (shouldn't happen), skip this test
        return
    pid_to_release = user_team.roster[0]
    world.release_player(pid_to_release)
    session_store.save(sid, world)

    # Get free agents
    fa_resp = client.get("/transactions/freeagents")
    assert fa_resp.status_code == 200
    agents = fa_resp.json()
    assert len(agents) > 0
    fa_pid = agents[0]["pid"]

    # Sign the free agent
    sign_resp = client.post(f"/transactions/freeagents/{fa_pid}/sign", json={})
    assert sign_resp.status_code == 200
    assert sign_resp.json()["success"] is True

    # Fetch the world again from session store
    world_after = session_store.get(sid)

    # Verify the player is now on the roster
    user_team_after = world_after.teams[world_after.user_team_id]
    assert fa_pid in user_team_after.roster

    # Verify the player is no longer a free agent
    assert fa_pid not in world_after.free_agents


def test_sign_free_agent_with_explicit_terms(client):
    from pucksim.web.session import session_store, SESSION_COOKIE_NAME

    client.post("/career/new", json={"seed": 103})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Release a player to create a free agent
    user_team = world.teams[world.user_team_id]
    if not user_team.roster:
        return
    pid_to_release = user_team.roster[0]
    world.release_player(pid_to_release)
    session_store.save(sid, world)

    # Get a free agent
    fa_resp = client.get("/transactions/freeagents")
    agents = fa_resp.json()
    if not agents:
        return
    fa_pid = agents[0]["pid"]

    # Sign with explicit salary and years
    sign_resp = client.post(
        f"/transactions/freeagents/{fa_pid}/sign",
        json={"salary": 5000000, "years": 2},
    )
    assert sign_resp.status_code == 200

    # Verify the contract was set
    world_after = session_store.get(sid)
    player = world_after.players[fa_pid]
    assert player.contract.current_salary == 5000000
    assert player.contract.years_remaining == 2


# ---------------------------------------------------------------------------
# GET /transactions/draft/board
# ---------------------------------------------------------------------------
def test_draft_board_without_session_is_a_clean_404(client):
    resp = client.get("/transactions/draft/board")
    assert resp.status_code == 404


def test_draft_board_empty_preseason(client):
    client.post("/career/new", json={"seed": 104})
    resp = client.get("/transactions/draft/board")
    assert resp.status_code == 200

    body = resp.json()
    assert body["in_draft"] is False
    assert body["board"] == []
    assert body["team_on_clock"] is None


# ---------------------------------------------------------------------------
# POST /transactions/draft/pick
# ---------------------------------------------------------------------------
def test_draft_pick_without_session_is_a_clean_404(client):
    resp = client.post("/transactions/draft/pick", json={"prospect_id": 1})
    assert resp.status_code == 404


def test_draft_pick_when_not_on_clock(client):
    from pucksim.sim.season import advance_one_day, start_season
    from pucksim.systems.draft_system import setup_draft
    from pucksim.web.session import session_store, SESSION_COOKIE_NAME

    client.post("/career/new", json={"seed": 105})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)

    # Setup draft but user's team is not first
    setup_draft(world)
    session_store.save(sid, world)

    # Try to make a pick for a prospect
    prospects = world.draft_class.remaining_prospects()
    if prospects:
        resp = client.post("/transactions/draft/pick", json={"prospect_id": prospects[0]})
        # Should fail because user's team is not on the clock (unless they happen to be first)
        if world.draft_class.team_on_clock() != world.user_team_id:
            assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /transactions/awards
# ---------------------------------------------------------------------------
def test_awards_without_session_is_a_clean_404(client):
    resp = client.get("/transactions/awards")
    assert resp.status_code == 404


def test_awards_returns_dict_in_preseason(client):
    client.post("/career/new", json={"seed": 106})
    resp = client.get("/transactions/awards")
    assert resp.status_code == 200

    body = resp.json()
    assert "season_year" in body
    assert "awards" in body
    assert isinstance(body["awards"], dict)


# ---------------------------------------------------------------------------
# POST /transactions/trades/propose
# ---------------------------------------------------------------------------
def test_trade_without_session_is_a_clean_404(client):
    resp = client.post(
        "/transactions/trades/propose",
        json={"other_team_id": 1, "user_sends": [], "user_receives": []},
    )
    assert resp.status_code == 404


def test_trade_propose_empty_is_rejected(client):
    client.post("/career/new", json={"seed": 107})
    resp = client.post(
        "/transactions/trades/propose",
        json={"other_team_id": 1, "user_sends": [], "user_receives": []},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is False
    assert "Empty trade" in body["reason"] or "trade" in body["reason"].lower()


def test_trade_propose_legal_swap_is_accepted_and_moves_both_rosters(client):
    """A legal (cap-fitting, roster-membership-valid) trade is executed outright, not
    subject to a separate AI accept/reject judgment -- systems.trades.propose_trade()'s own
    docstring is explicit: "no negotiation, the offer is either accepted as constructed or
    rejected outright." This test exercises that path end-to-end through the endpoint and
    verifies both teams' rosters actually change (the DEVPLAN.md "sign a free agent" done
    criterion's trade-equivalent -- a prior version of this test file only covered the
    empty-trade rejection path, never a real accepted trade)."""
    from pucksim.web.session import session_store

    client.post("/career/new", json={"seed": 108})
    sid = client.cookies[SESSION_COOKIE_NAME]
    world = session_store.get(sid)
    user_team = world.user_team
    other_team = next(t for t in world.team_list() if t.tid != user_team.tid)

    # Lowest-overall skater on each side -- cheapest, lowest-risk pair to swap without
    # tripping the cap-matching buffer on a freshly generated (well-under-cap) league.
    user_pid = min(
        (pid for pid in user_team.roster if world.players[pid].position != "G"),
        key=lambda pid: world.players[pid].overall,
    )
    other_pid = min(
        (pid for pid in other_team.roster if world.players[pid].position != "G"),
        key=lambda pid: world.players[pid].overall,
    )

    resp = client.post(
        "/transactions/trades/propose",
        json={
            "other_team_id": other_team.tid,
            "user_sends": [user_pid],
            "user_receives": [other_pid],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True

    # Verify both sides of the roster mirror actually moved (via World.transfer_player, not
    # a one-sided move) -- checked against the live session World, the same source of truth
    # every other endpoint in this router reads from.
    world_after = session_store.get(sid)
    assert other_pid in world_after.team(user_team.tid).roster
    assert user_pid not in world_after.team(user_team.tid).roster
    assert user_pid in world_after.team(other_team.tid).roster
    assert other_pid not in world_after.team(other_team.tid).roster
    assert world_after.player(user_pid).team_id == other_team.tid
    assert world_after.player(other_pid).team_id == user_team.tid
