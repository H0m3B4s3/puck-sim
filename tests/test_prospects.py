"""Tests for pucksim.systems.prospects -- the reserved-prospect development window.

See prospects.py's module docstring: this is v1's minimal stand-in for the missing
junior/AHL system, and it exists for economic reasons as much as realism ones.
"""
from __future__ import annotations

from pucksim import config
from pucksim.models.contract import Contract
from pucksim.models.player import Player
from pucksim.models import attributes as attr
from pucksim.systems import prospects


def make_prospect(pid: int = 1, draft_year: int = 2030, pick: int = 15,
                   age: int = 18, overall: int = 55) -> Player:
    player = Player(
        pid=pid,
        name=f"Prospect {pid}",
        age=age,
        position="C",
        ratings={name: overall for name in attr.ALL_RATINGS},
        contract=Contract.free_agent(),
    )
    player.draft = {"year": draft_year, "round": 1, "pick": pick, "team": "TST"}
    return player


# ---------------------------------------------------------------------------
# The development schedule
# ---------------------------------------------------------------------------
def test_development_window_lengthens_down_the_draft_board():
    """A class arrives in waves: first overall now, top ten next year, rest of round one
    after that, later rounds later still."""
    assert prospects.development_years(1) == 0
    assert prospects.development_years(5) == 1
    assert prospects.development_years(10) == 1
    assert prospects.development_years(20) == 2
    assert prospects.development_years(32) == 2
    assert prospects.development_years(64) == config.PROSPECT_DEVELOPMENT_YEARS_DEFAULT
    assert prospects.development_years(200) == config.PROSPECT_DEVELOPMENT_YEARS_DEFAULT


def test_development_window_is_monotonic():
    """Being picked later can never mean reaching the NHL sooner."""
    windows = [prospects.development_years(pick) for pick in range(1, 250)]
    assert windows == sorted(windows)


# ---------------------------------------------------------------------------
# Reserve status
# ---------------------------------------------------------------------------
def test_first_overall_pick_is_never_reserved():
    player = make_prospect(pick=1, draft_year=2030)
    assert not prospects.is_reserved_prospect(player, 2030)


def test_mid_first_round_pick_is_reserved_then_graduates():
    player = make_prospect(pick=20, draft_year=2030)      # 2-season window
    assert prospects.is_reserved_prospect(player, 2030)
    assert prospects.is_reserved_prospect(player, 2031)
    assert not prospects.is_reserved_prospect(player, 2032)


def test_late_round_pick_waits_longer_than_a_first_rounder():
    early = make_prospect(pid=1, pick=20, draft_year=2030)
    late = make_prospect(pid=2, pick=120, draft_year=2030)
    graduation_year = 2030 + config.PROSPECT_DEVELOPMENT_YEARS_DEFAULT
    assert not prospects.is_reserved_prospect(early, graduation_year - 1)
    assert prospects.is_reserved_prospect(late, graduation_year - 1)
    assert not prospects.is_reserved_prospect(late, graduation_year)


def test_a_rostered_player_is_not_reserved():
    """Reserve status is about being unsigned and developing. A pick who made the NHL is
    just a player, even inside what would have been their window."""
    player = make_prospect(pick=20, draft_year=2030)
    player.team_id = 4
    assert not prospects.is_reserved_prospect(player, 2030)


def test_an_undrafted_player_is_never_reserved():
    """Undrafted free agents are ordinary market participants, not prospects."""
    player = make_prospect(pick=20, draft_year=2030)
    player.draft = None
    assert not prospects.is_reserved_prospect(player, 2030)


def test_a_player_drafted_in_the_future_is_not_reserved():
    """Guards the elapsed >= 0 condition against a malformed/future draft year."""
    player = make_prospect(pick=20, draft_year=2035)
    assert not prospects.is_reserved_prospect(player, 2030)


# ---------------------------------------------------------------------------
# The reserve is enforced against every caller, not just the AI
# ---------------------------------------------------------------------------
def _world_with_team_and_prospect(draft_year: int, pick: int = 20):
    from pucksim.models.team import Team
    from pucksim.models.world import World
    from pucksim.rng import Rng

    world = World(rng=Rng(seed=1))
    world.season_year = draft_year
    team = Team(tid=1, name="Test", abbrev="TST", conference="Eastern")
    world.register_team(team)
    player = make_prospect(pid=500, draft_year=draft_year, pick=pick)
    world.add_player(player)
    return world, team, player


def test_a_user_cannot_sign_a_reserved_prospect():
    """The rule has to bind the human team too. ``run_fa_wave`` filters prospects out of
    its pool, but ``sign_free_agent`` is what a user's request reaches -- without the check
    there, the user could raid developing prospects no AI team is allowed to touch."""
    from pucksim.systems.freeagency import sign_free_agent

    world, team, player = _world_with_team_and_prospect(draft_year=2030)
    ok, reason = sign_free_agent(world, team, player.pid, 1_000_000, 2)

    assert ok is False
    assert "prospect" in reason.lower()
    assert player.team_id is None


def test_a_graduated_prospect_can_be_signed():
    """Once the window closes they're an ordinary free agent."""
    from pucksim.systems.freeagency import sign_free_agent

    world, team, player = _world_with_team_and_prospect(draft_year=2030)
    world.season_year = 2030 + prospects.development_years(20)

    ok, _ = sign_free_agent(world, team, player.pid, 1_000_000, 2)
    assert ok is True
    assert player.team_id == team.tid
