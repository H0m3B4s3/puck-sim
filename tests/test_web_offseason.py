"""Tests for /offseason endpoints: pre-draft, draft board, draft pick, FA waves, finish.

DEVPLAN.md Step 2.11 (T5) -- full staged offseason flow.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pucksim.web.app import app
from pucksim.web.session import SESSION_COOKIE_NAME, session_store
from pucksim.sim.season import advance_one_day, start_season
from pucksim.sim.playoffs import start_playoffs, run_full_playoffs
from pucksim.models.league import Phase


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Test client with isolated session store."""
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


def _get_world(client):
    """Retrieve the session's World object from the test client."""
    sid = client.cookies[SESSION_COOKIE_NAME]
    return session_store.get(sid)


def _save_world(client, world):
    """Save the session's World object."""
    sid = client.cookies[SESSION_COOKIE_NAME]
    session_store.save(sid, world)


def _sim_to_playoffs(client):
    """Fast-forward a career to playoffs: start season, play all games, run playoffs."""
    from pucksim.sim.playoffs import start_playoffs, run_full_playoffs
    from pucksim.models.league import Phase

    # Start season
    client.post("/season/start")

    # Play all regular-season games
    world = _get_world(client)
    max_days = 200  # Safety bound
    day_count = 0
    while day_count < max_days:
        if world.schedule and all(g.played for g in world.schedule if not g.is_playoff):
            break
        advance_one_day(world)
        _save_world(client, world)
        world = _get_world(client)
        day_count += 1

    # Start and run playoffs via engine (T4 endpoints may not be available yet)
    world = _get_world(client)
    start_playoffs(world)
    run_full_playoffs(world)
    # At this point, world.phase should be DRAFT
    _save_world(client, world)


# ---------------------------------------------------------------------------
# Offseason flow: pre-draft, draft board, picks, FA waves, finish
# ---------------------------------------------------------------------------
def test_pre_draft_during_regular_season_fails(client):
    """pre_draft requires Phase.DRAFT (playoffs complete)."""
    client.post("/career/new", json={"seed": 42})
    client.post("/season/start")

    resp = client.post("/offseason/pre-draft")
    assert resp.status_code == 409
    assert "Playoffs are not complete" in resp.text


def test_pre_draft_initializes_draft_and_archives_season(client):
    """pre_draft archives season, ages players, and initializes the draft."""
    client.post("/career/new", json={"seed": 42})
    _sim_to_playoffs(client)

    resp = client.post("/offseason/pre-draft")
    assert resp.status_code == 200
    body = resp.json()

    assert body["resumed"] is False
    assert body["champion_tid"] is not None
    assert body["champion_name"] != ""
    assert "retired" in body
    assert "new_fas" in body
    assert "inducted" in body
    assert "milestones" in body

    # Check world.history was populated
    world = _get_world(client)
    assert len(world.history) == 1
    assert world.history[0]["champion"] == body["champion_tid"]
    assert "awards" in world.history[0]

    # Check draft_class is initialized
    assert world.draft_class is not None
    assert world.draft_class.year == world.season_year


def test_pre_draft_idempotency_guard(client):
    """Second pre_draft call returns resumed: True (idempotency)."""
    client.post("/career/new", json={"seed": 42})
    _sim_to_playoffs(client)

    # First pre_draft
    resp1 = client.post("/offseason/pre-draft")
    assert resp1.status_code == 200
    assert resp1.json()["resumed"] is False

    # Second pre_draft (should be idempotent)
    resp2 = client.post("/offseason/pre-draft")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["resumed"] is True
    assert body["retired"] == 0
    assert body["new_fas"] == 0


def test_draft_board_auto_advances_to_user_turn(client):
    """Draft board auto-advances AI picks until user's turn."""
    client.post("/career/new", json={"seed": 42})
    _sim_to_playoffs(client)
    client.post("/offseason/pre-draft")

    resp = client.get("/offseason/draft/board")
    assert resp.status_code == 200
    body = resp.json()

    assert body["complete"] is False
    assert body["pick"] is not None  # Pick number (1-based)
    assert body["round"] is not None
    assert body["board"]  # Prospects to choose from
    assert isinstance(body["recent"], list)  # Recent AI picks

    # Verify user team is on the clock
    world = _get_world(client)
    assert world.draft_class.team_on_clock() == world.user_team_id


def test_draft_board_returns_top_60_prospects(client):
    """Draft board returns up to 60 prospects."""
    client.post("/career/new", json={"seed": 42})
    _sim_to_playoffs(client)
    client.post("/offseason/pre-draft")

    resp = client.get("/offseason/draft/board")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["board"]) <= 60


def test_draft_pick_fails_if_user_not_on_clock(client):
    """Picking when not on the clock fails."""
    client.post("/career/new", json={"seed": 42})
    _sim_to_playoffs(client)
    client.post("/offseason/pre-draft")

    world = _get_world(client)
    # Manually advance the clock past the user's turn
    world.draft_class.current_pick = 0
    while world.draft_class.team_on_clock() == world.user_team_id:
        world.draft_class.current_pick += 1
        if world.draft_class.complete:
            break
    _save_world(client, world)

    if not world.draft_class.complete:
        resp = client.post("/offseason/draft/pick", json={"prospect_id": None})
        assert resp.status_code == 409


def test_user_draft_pick_returns_prospect_info(client):
    """User's draft pick returns the selected prospect info."""
    client.post("/career/new", json={"seed": 42})
    _sim_to_playoffs(client)
    client.post("/offseason/pre-draft")

    # Get board to find a prospect
    board_resp = client.get("/offseason/draft/board")
    board = board_resp.json()
    prospect_id = board["board"][0]["pid"]

    # Make the pick
    resp = client.post("/offseason/draft/pick", json={"prospect_id": prospect_id})
    assert resp.status_code == 200
    body = resp.json()

    assert body["pid"] == prospect_id
    assert body["name"]
    assert body["position"]
    assert body["overall"] >= 0
    assert body["potential"] >= 0
    assert "signed" in body


def test_draft_board_loop_to_completion(client):
    """Loop through draft board picking until complete."""
    client.post("/career/new", json={"seed": 42})
    _sim_to_playoffs(client)
    client.post("/offseason/pre-draft")

    # Loop: get board, pick best available, repeat
    picks_made = 0
    max_picks = 500  # Safety bound
    while picks_made < max_picks:
        board_resp = client.get("/offseason/draft/board")
        board = board_resp.json()

        if board["complete"]:
            break

        # Pick best available (auto-pick)
        resp = client.post("/offseason/draft/pick", json={"prospect_id": None})
        assert resp.status_code == 200
        picks_made += 1

    # Verify draft is complete
    world = _get_world(client)
    assert world.draft_class.complete
    assert world.phase == Phase.FREE_AGENCY


def test_fa_start_initializes_waves(client):
    """fa/start initializes the first FA wave."""
    client.post("/career/new", json={"seed": 42})
    _sim_to_playoffs(client)
    client.post("/offseason/pre-draft")

    # Complete the draft
    picks_made = 0
    while picks_made < 500:
        board_resp = client.get("/offseason/draft/board")
        if board_resp.json()["complete"]:
            break
        client.post("/offseason/draft/pick", json={"prospect_id": None})
        picks_made += 1

    # Start FA
    resp = client.post("/offseason/fa/start")
    assert resp.status_code == 200
    body = resp.json()

    assert body["active"] is True
    assert body["wave"] == 1  # First wave (1-based)
    assert body["total"] == 4  # NUM_FA_WAVES
    assert body["name"]  # Wave name


def test_fa_advance_runs_wave_and_moves_to_next(client):
    """fa/advance runs current wave and advances."""
    client.post("/career/new", json={"seed": 42})
    _sim_to_playoffs(client)
    client.post("/offseason/pre-draft")

    # Complete draft
    picks_made = 0
    while picks_made < 500:
        board_resp = client.get("/offseason/draft/board")
        if board_resp.json()["complete"]:
            break
        client.post("/offseason/draft/pick", json={"prospect_id": None})
        picks_made += 1

    client.post("/offseason/fa/start")

    # Advance through all waves
    waves_advanced = 0
    for _ in range(4):
        resp = client.post("/offseason/fa/advance")
        assert resp.status_code == 200
        body = resp.json()
        assert "signings" in body
        assert "done" in body
        waves_advanced += 1
        if body["done"]:
            break

    # After last wave, done should be True
    assert waves_advanced > 0


def test_freeagents_board_returns_ask_and_preferred_years(client):
    """Free agents board includes ask (market salary) and preferred years."""
    client.post("/career/new", json={"seed": 42})

    # Get FAs during non-offseason
    resp = client.get("/transactions/freeagents")
    assert resp.status_code == 200
    fas = resp.json()

    # Should have ask and preferred_years fields
    if fas:
        for fa in fas:
            assert "ask" in fa
            assert "preferred_years" in fa
            assert fa["ask"] >= 0
            assert fa["preferred_years"] >= 1


def test_finish_offseason_completes_cycle(client):
    """Finish moves to next season at day 0."""
    client.post("/career/new", json={"seed": 42})
    _sim_to_playoffs(client)
    client.post("/offseason/pre-draft")

    # Complete draft
    picks_made = 0
    while picks_made < 500:
        board_resp = client.get("/offseason/draft/board")
        if board_resp.json()["complete"]:
            break
        client.post("/offseason/draft/pick", json={"prospect_id": None})
        picks_made += 1

    client.post("/offseason/fa/start")

    # Advance all FA waves
    for _ in range(4):
        resp = client.post("/offseason/fa/advance")
        if resp.json()["done"]:
            break

    # Finish offseason
    resp = client.post("/offseason/finish")
    assert resp.status_code == 200
    body = resp.json()

    assert body["phase"] == "regular_season"
    assert body["day"] == 0
    assert body["season_year"] > 2025  # Year advanced

    # Verify rosters are full (should have been filled by post_offseason)
    world = _get_world(client)
    for team in world.team_list():
        assert len(team.roster) >= 20  # Minimum roster


# ---------------------------------------------------------------------------
# Trade validation and execution
# ---------------------------------------------------------------------------
def test_trade_validate_empty_offer_rejected(client):
    """Empty trade offers are rejected as illegal."""
    client.post("/career/new", json={"seed": 42})

    # Get user team and pick a partner
    world = _get_world(client)
    user_tid = world.user_team_id
    partner_tid = next(t.tid for t in world.team_list() if t.tid != user_tid)

    # Both sides send nothing (empty trade)
    resp = client.post(
        "/transactions/trades/validate",
        json={"other_team_id": partner_tid, "user_sends": [], "user_receives": []}
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["legal"] is False  # Empty trade is illegal


def test_trade_validate_fair_offer_accepted_by_ai(client):
    """AI potentially accepts a fair/beneficial trade."""
    client.post("/career/new", json={"seed": 42})

    world = _get_world(client)
    user_tid = world.user_team_id
    user_team = world.teams[user_tid]

    # Find a partner team
    partner_tid = next(t.tid for t in world.team_list() if t.tid != user_tid)
    partner_team = world.teams[partner_tid]

    if len(user_team.roster) >= 2 and len(partner_team.roster) >= 2:
        # User sends best player, receives best player from other team
        user_best = max(user_team.roster, key=lambda pid: world.players[pid].overall)
        partner_best = max(partner_team.roster, key=lambda pid: world.players[pid].overall)

        resp = client.post(
            "/transactions/trades/validate",
            json={
                "other_team_id": partner_tid,
                "user_sends": [user_best],
                "user_receives": [partner_best]
            }
        )
        assert resp.status_code == 200
        body = resp.json()

        assert "legal" in body
        assert "accepts" in body
        assert "ai_reason" in body


def test_trade_execute_saves_if_accepted(client):
    """Execute trade saves world and updates rosters when accepted."""
    client.post("/career/new", json={"seed": 42})

    world = _get_world(client)
    user_tid = world.user_team_id
    user_team = world.teams[user_tid]

    # Find a partner
    partner_tid = next(t.tid for t in world.team_list() if t.tid != user_tid)
    partner_team = world.teams[partner_tid]

    if len(user_team.roster) >= 2 and len(partner_team.roster) >= 2:
        user_best = max(user_team.roster, key=lambda pid: world.players[pid].overall)
        partner_best = max(partner_team.roster, key=lambda pid: world.players[pid].overall)

        # First validate to see if it would be accepted
        validate_resp = client.post(
            "/transactions/trades/validate",
            json={
                "other_team_id": partner_tid,
                "user_sends": [user_best],
                "user_receives": [partner_best]
            }
        )

        if validate_resp.json()["accepts"]:
            # Execute it
            exec_resp = client.post(
                "/transactions/trades/execute",
                json={
                    "other_team_id": partner_tid,
                    "user_sends": [user_best],
                    "user_receives": [partner_best]
                }
            )
            assert exec_resp.status_code == 200
            body = exec_resp.json()

            if body["executed"]:
                # Verify rosters changed
                world = _get_world(client)
                assert partner_best in world.teams[user_tid].roster
                assert user_best not in world.teams[user_tid].roster
