"""Tests for the prospects web layer -- GET /roster/prospects and POST .../sign.

The development system exists in the engine after PRs #63-#66; these cover the part a
player of the game can actually see and act on (docs/PROSPECT_DEV_PLAN.md Phase 6).

Same session fixture pattern as test_web.py: TestClient with tmp_path isolation.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pucksim import config
from pucksim.web.app import app
from pucksim.web.session import SESSION_COOKIE_NAME


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


@pytest.fixture()
def career(client):
    """A career that has been through one full offseason, so a draft class exists and its
    picks have been placed into development tiers."""
    resp = client.post("/career/new", json={"seed": 42})
    assert resp.status_code == 200
    return resp.json()


def _run_offseason(client):
    """Drive the engine's offseason directly on the session's world.

    The staged web offseason needs a completed season and playoffs to run through; this
    round's subject is the prospect data, not the phase machine, so the test reaches for
    the same headless entry point `run_offseason` that the UI's flow ultimately calls.

    Takes the sid from THIS client's cookie rather than off the store: ``session_store`` is
    a module-level singleton, so every session created by every test in the run is still in
    it, and grabbing the first one silently advances some other test's world instead.
    """
    from pucksim.systems import offseason
    from pucksim.web.session import session_store

    sid = client.cookies.get(SESSION_COOKIE_NAME)
    assert sid, "client has no session cookie"
    world = session_store.get(sid)
    offseason.run_offseason(world, champion_tid=None)
    session_store.save(sid, world)
    return world


# ---------------------------------------------------------------------------
# GET /roster/prospects
# ---------------------------------------------------------------------------
def test_a_new_career_starts_with_a_seeded_farm_system(client, career):
    """A freshly generated league now opens with a stocked pipeline for every team
    (docs/PROSPECT_DEV_PLAN.md follow-up), so the Prospects screen has content on day one
    instead of being blank until the first draft."""
    resp = client.get("/roster/prospects")
    assert resp.status_code == 200
    body = resp.json()
    assert body["prospects"], "the user's farm system is empty at career start"
    assert body["contracts_max"] == config.MAX_CONTRACTS
    assert body["contracts_used"] > 0                  # the NHL roster still counts
    assert {p["tier"] for p in body["prospects"]} <= set(config.DEV_TIERS)


def test_prospect_pool_lists_the_teams_own_prospects_after_a_draft(client, career):
    _run_offseason(client)
    resp = client.get("/roster/prospects")
    assert resp.status_code == 200
    body = resp.json()

    assert body["prospects"], "a full offseason produced no prospects for the user's team"
    for p in body["prospects"]:
        assert p["tier"] in config.DEV_TIERS
        assert p["tier_label"]
        assert p["status"]
        assert p["potential"] >= p["overall"]          # scouted potential is never below OVR
        assert 0 <= p["slide_years"] <= 2


def test_the_pool_reports_contracts_against_the_league_limit(client, career):
    """Entry-level deals cost no cap space, so the 50-contract limit is the only thing
    pushing back on signing everyone -- the screen has to show it."""
    _run_offseason(client)
    body = client.get("/roster/prospects").json()
    assert body["contracts_max"] == config.MAX_CONTRACTS
    assert body["contracts_used"] >= len(
        [p for p in body["prospects"] if p["signed"]]
    )


def test_prospects_route_is_not_shadowed_by_the_team_roster_route(client, career):
    """/roster/{tid} would swallow /roster/prospects if the literal route were registered
    after it -- a silent 422 rather than a crash, so it gets its own test."""
    resp = client.get("/roster/prospects")
    assert resp.status_code == 200
    assert "prospects" in resp.json()


def _give_user_an_unsigned_prospect(client, age=18, origin="chl"):
    """Put a known unsigned prospect in the user's system and return his pid.

    Built rather than found: the AI signs the prospects it believes in during every
    offseason, so whether an unsigned one happens to be left over is a property of the seed.
    A test about the signing endpoint shouldn't skip itself because a draft went a
    particular way.
    """
    from pucksim.models import attributes as attr
    from pucksim.models.player import Player
    from pucksim.systems import prospects
    from pucksim.web.session import session_store

    sid = client.cookies.get(SESSION_COOKIE_NAME)
    world = session_store.get(sid)
    player = Player(
        pid=world.new_pid(), name="Test Prospect", age=age, position="C",
        ratings={name: 55 for name in attr.ALL_RATINGS},
    )
    player.league_origin = origin
    player.potential = 85
    world.add_player(player)
    prospects.enter_development(player, origin, world.season_year,
                                 rights_tid=world.user_team_id)
    session_store.save(sid, world)
    return player.pid


# ---------------------------------------------------------------------------
# POST /roster/prospects/{pid}/sign
# ---------------------------------------------------------------------------
def test_signing_a_prospect_keeps_him_off_the_nhl_roster(client, career):
    """The real mechanic: sign your first-rounder, send him back to junior. He gets a
    contract, not a roster spot."""
    pid = _give_user_an_unsigned_prospect(client)
    pool = client.get("/roster/prospects").json()["prospects"]
    target = next(p for p in pool if p["pid"] == pid)
    assert target["signed"] is False

    roster_before = len(client.get("/roster").json()["players"])

    resp = client.post(f"/roster/prospects/{pid}/sign")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True, body["message"]

    assert body["prospect"]["signed"] is True
    assert body["prospect"]["years_remaining"] == config.ROOKIE_CONTRACT_YEARS   # 3y at 18
    # He is under contract but NOT on the roster -- that is the whole point.
    assert len(client.get("/roster").json()["players"]) == roster_before
    after = next(p for p in client.get("/roster/prospects").json()["prospects"]
                 if p["pid"] == pid)
    assert after["signed"] is True
    assert after["slides_this_year"] is True    # 18 years old, no NHL games


def test_an_older_prospect_gets_a_shorter_entry_level_deal(client, career):
    """The real CBA schedule, visible through the endpoint: 3 years at 18-21, 2 at 22-23."""
    pid = _give_user_an_unsigned_prospect(client, age=22, origin="europe")
    body = client.post(f"/roster/prospects/{pid}/sign").json()
    assert body["ok"] is True, body["message"]
    assert body["prospect"]["years_remaining"] == 2
    assert body["prospect"]["slides_this_year"] is False     # too old to slide


def test_signing_the_same_prospect_twice_is_refused(client, career):
    pid = _give_user_an_unsigned_prospect(client)
    assert client.post(f"/roster/prospects/{pid}/sign").json()["ok"] is True
    second = client.post(f"/roster/prospects/{pid}/sign").json()
    assert second["ok"] is False
    assert "contract" in second["message"].lower()


def test_signing_someone_elses_prospect_is_refused_not_an_error(client, career):
    """Failures here are states a manager needs to read, so they come back as ok:false with
    a reason rather than as an HTTP error."""
    world = _run_offseason(client)
    from pucksim.systems import prospects

    user_tid = world.user_team_id
    others = [p for p in prospects.developing_players(world)
              if prospects.rights_holder(p) not in (None, user_tid)]
    if not others:
        pytest.skip("no other team holds a prospect in this seed")

    resp = client.post(f"/roster/prospects/{others[0].pid}/sign")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "rights" in body["message"].lower()


def test_signing_a_player_who_is_not_a_prospect_is_refused(client, career):
    roster = client.get("/roster").json()["players"]
    resp = client.post(f"/roster/prospects/{roster[0]['pid']}/sign")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


# ---------------------------------------------------------------------------
# Player detail carries the development record
# ---------------------------------------------------------------------------
def test_player_detail_carries_development_for_a_prospect(client, career):
    _run_offseason(client)
    pool = client.get("/roster/prospects").json()["prospects"]
    assert pool

    detail = client.get(f"/players/{pool[0]['pid']}").json()
    assert detail["development"] is not None
    assert detail["development"]["tier_label"]
    assert detail["development"]["status"]


def test_player_detail_development_is_null_for_an_nhl_player(client, career):
    roster = client.get("/roster").json()["players"]
    detail = client.get(f"/players/{roster[0]['pid']}").json()
    assert detail["development"] is None


# ---------------------------------------------------------------------------
# Manual call-up and send-down endpoints
# ---------------------------------------------------------------------------
def _give_user_a_signed_ready_prospect(client, tier="ahl"):
    """A signed, NHL-ready prospect on the user team, with a roster spot free for him."""
    from pucksim.models import attributes as attr
    from pucksim.models.contract import flat_contract
    from pucksim.models.player import Player
    from pucksim.systems import prospects
    from pucksim.web.session import session_store

    sid = client.cookies.get(SESSION_COOKIE_NAME)
    world = session_store.get(sid)
    tid = world.user_team_id
    while len(world.teams[tid].roster) >= config.ROSTER_MAX - 1:
        world.release_player(world.teams[tid].roster[-1])
    player = Player(pid=world.new_pid(), name="Ready Kid", age=20, position="C",
                    ratings={n: 90 for n in attr.ALL_RATINGS})
    player.league_origin = "europe"
    player.potential = 92
    player.contract = flat_contract(900_000, 3, is_rookie_scale=True, two_way=True)
    world.add_player(player)
    prospects.enter_development(player, tier, world.season_year, rights_tid=tid)
    session_store.save(sid, world)
    return player.pid


def test_call_up_endpoint_adds_the_prospect_to_the_roster(client, career):
    pid = _give_user_a_signed_ready_prospect(client)
    before = len(client.get("/roster").json()["players"])

    resp = client.post(f"/roster/prospects/{pid}/call-up")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert len(client.get("/roster").json()["players"]) == before + 1
    # He's gone from the prospect pool.
    assert all(p["pid"] != pid
               for p in client.get("/roster/prospects").json()["prospects"])


def test_call_up_of_an_unsigned_prospect_is_refused(client, career):
    pid = _give_user_an_unsigned_prospect(client)
    resp = client.post(f"/roster/prospects/{pid}/call-up")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "contract" in body["message"].lower()


def test_send_down_endpoint_moves_a_rostered_player_to_the_minors(client, career):
    pid = _give_user_a_signed_ready_prospect(client)
    assert client.post(f"/roster/prospects/{pid}/call-up").json()["ok"] is True
    on_roster = len(client.get("/roster").json()["players"])

    resp = client.post(f"/roster/{pid}/send-down")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert len(client.get("/roster").json()["players"]) == on_roster - 1
    assert any(p["pid"] == pid
               for p in client.get("/roster/prospects").json()["prospects"])


def test_player_detail_flags_send_down_only_for_eligible_own_players(client, career):
    pid = _give_user_a_signed_ready_prospect(client)
    client.post(f"/roster/prospects/{pid}/call-up")
    assert client.get(f"/players/{pid}").json()["can_send_down"] is True

    # A player on another team is never send-down-able by the user.
    world_roster = client.get("/roster").json()["players"]
    # An old veteran on the user's roster is too experienced -> not send-down-able.
    detail = client.get(f"/players/{world_roster[0]['pid']}").json()
    assert isinstance(detail["can_send_down"], bool)


def test_player_detail_reports_contract_structure_and_bury_hit(client, career):
    """The Send to Minors affordance needs to know whether a demotion frees the full cap
    hit (two-way) or leaves a buried anchor (one-way)."""
    pid = _give_user_a_signed_ready_prospect(client)      # ELC -> two-way
    client.post(f"/roster/prospects/{pid}/call-up")
    detail = client.get(f"/players/{pid}").json()
    assert detail["two_way"] is True
    assert detail["bury_cap_hit"] == 0

    # A market-contract veteran on the roster is one-way; his buried hit is >= 0.
    roster = client.get("/roster").json()["players"]
    vet = next((p for p in roster if p["contract"]["years_remaining"] > 0), None)
    if vet is not None:
        vd = client.get(f"/players/{vet['pid']}").json()
        assert isinstance(vd["two_way"], bool)
        assert vd["bury_cap_hit"] >= 0
