"""Tests for pucksim.systems.freeagency -- DEVPLAN.md Step 2.4 done-criteria.

Focus per DEVPLAN.md's Done criteria: "FA waves clear the market -- players get signed,
market doesn't stall/infinite-loop." Also exercises direct signing helpers
(``sign_free_agent``/``sign_rookie``), all of which must route through
``World.sign_player`` (never direct roster/``team_id`` mutation).
"""
from __future__ import annotations

from pucksim import config
from pucksim.models import attributes as attr
from pucksim.models.contract import flat_contract
from pucksim.models.player import Player
from pucksim.models.team import Team
from pucksim.models.world import World
from pucksim.rng import Rng
from pucksim.systems import freeagency as fa


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _skater_ratings(value: int = 70) -> dict:
    return {name: value for name in attr.ALL_RATINGS}


def make_free_agent(pid: int, overall: int = 70, age: int = 27, **overrides) -> Player:
    kwargs = dict(
        pid=pid,
        name=f"FA {pid}",
        age=age,
        position="C",
        ratings=_skater_ratings(overall),
        team_id=None,
        contract=flat_contract(0, 0),  # free agent: no active contract
    )
    kwargs.update(overrides)
    return Player(**kwargs)


def build_world_with_teams(n_teams: int = 32, cap_value: int = 90_000_000) -> World:
    world = World(rng=Rng(seed=3))
    world.salary_cap = cap_value
    world.season_year = 2026
    for tid in range(1, n_teams + 1):
        team = Team(tid=tid, name=f"Team {tid}", abbrev=f"T{tid}", conference="Eastern")
        world.register_team(team)
    return world


def add_free_agents(world: World, n: int, start_pid: int = 1, **kwargs) -> None:
    for i in range(n):
        p = make_free_agent(start_pid + i, **kwargs)
        world.add_player(p)


# ---------------------------------------------------------------------------
# natural_wave / fa_wave_pool
# ---------------------------------------------------------------------------
def test_natural_wave_higher_overall_opens_earlier():
    star = make_free_agent(1, overall=85)
    depth = make_free_agent(2, overall=40)
    assert fa.natural_wave(star) < fa.natural_wave(depth)


def test_fa_wave_pool_without_active_market_returns_everyone():
    world = build_world_with_teams(n_teams=2)
    add_free_agents(world, 5, overall=50)
    add_free_agents(world, 3, start_pid=100, overall=85)

    pool = fa.fa_wave_pool(world)
    assert len(pool) == 8
    # Sorted highest overall first.
    assert pool[0].overall >= pool[-1].overall


def test_fa_wave_pool_at_wave_zero_only_includes_top_tier():
    world = build_world_with_teams(n_teams=2)
    add_free_agents(world, 3, overall=85)     # wave 0
    add_free_agents(world, 3, start_pid=100, overall=50)  # later wave
    fa.start_fa_market(world)

    pool = fa.fa_wave_pool(world)
    assert all(p.overall == 85 for p in pool)


# ---------------------------------------------------------------------------
# start_fa_market / advance_fa_wave / end_fa_market
# ---------------------------------------------------------------------------
def test_start_and_end_fa_market_toggles_wave_state():
    world = build_world_with_teams(n_teams=2)
    assert getattr(world, "fa_wave", None) is None

    fa.start_fa_market(world)
    assert world.fa_wave == 0

    fa.end_fa_market(world)
    assert world.fa_wave is None


def test_advance_fa_wave_terminates_after_num_waves():
    world = build_world_with_teams(n_teams=2)
    fa.start_fa_market(world)
    steps = 0
    while fa.advance_fa_wave(world):
        steps += 1
        assert steps <= fa.NUM_FA_WAVES + 1   # guard against an infinite loop in the test itself
    assert world.fa_wave is None


def test_advance_fa_wave_false_when_market_not_open():
    world = build_world_with_teams(n_teams=2)
    assert fa.advance_fa_wave(world) is False


# ---------------------------------------------------------------------------
# wave_market_salary -- cooling
# ---------------------------------------------------------------------------
def test_wave_market_salary_cools_as_waves_pass_without_signing():
    world = build_world_with_teams(n_teams=2)
    depth_player = make_free_agent(1, overall=50)   # opens in a late wave
    world.add_player(depth_player)

    fa.start_fa_market(world)
    price_wave0 = fa.wave_market_salary(world, depth_player)

    world.fa_wave = fa.NUM_FA_WAVES - 1   # jump to the final wave without signing
    price_final_wave = fa.wave_market_salary(world, depth_player)

    assert price_final_wave <= price_wave0


def test_wave_market_salary_never_drops_below_minimum_discount_factor():
    world = build_world_with_teams(n_teams=2)
    player = make_free_agent(1, overall=90)
    world.add_player(player)
    from pucksim.systems import cap as cap_module
    full_value = cap_module.market_salary(player, world.salary_cap)

    world.fa_wave = fa.NUM_FA_WAVES - 1
    cooled = fa.wave_market_salary(world, player)
    assert cooled >= int(full_value * fa.MIN_DISCOUNT_FACTOR * 0.99)  # small rounding slack


# ---------------------------------------------------------------------------
# sign_free_agent / sign_rookie -- must route through World.sign_player
# ---------------------------------------------------------------------------
def test_sign_free_agent_moves_player_via_world_and_sets_contract():
    world = build_world_with_teams(n_teams=1)
    p = make_free_agent(1, overall=70)
    world.add_player(p)
    team = world.team(1)

    ok, msg = fa.sign_free_agent(world, team, 1, salary=2_000_000, years=3)
    assert ok is True
    assert world.player(1).team_id == 1
    assert 1 in team.roster
    assert 1 not in world.free_agents
    assert world.player(1).contract.current_salary == 2_000_000
    assert world.player(1).contract.years_remaining == 3


def test_sign_free_agent_rejects_when_not_a_free_agent():
    world = build_world_with_teams(n_teams=2)
    p = make_free_agent(1, overall=70, team_id=1)
    world.add_player(p)
    world.team(1).add_player(1)

    ok, reason = fa.sign_free_agent(world, world.team(2), 1, salary=1_000_000, years=1)
    assert ok is False
    assert "free agent" in reason.lower()


def test_sign_free_agent_rejects_when_cap_exceeded():
    world = build_world_with_teams(n_teams=1, cap_value=1_000_000)
    p = make_free_agent(1, overall=70)
    world.add_player(p)
    team = world.team(1)

    ok, reason = fa.sign_free_agent(world, team, 1, salary=5_000_000, years=1)
    assert ok is False


def test_sign_rookie_uses_flat_entry_level_salary_and_rookie_scale_flag():
    world = build_world_with_teams(n_teams=1)
    prospect = make_free_agent(1, overall=55, age=19)
    world.add_player(prospect)
    team = world.team(1)

    from pucksim.systems import cap as cap_module

    ok, msg = fa.sign_rookie(world, team, 1)
    assert ok is True
    contract = world.player(1).contract
    assert contract.is_rookie_scale is True
    assert contract.years_remaining == config.ROOKIE_CONTRACT_YEARS
    assert contract.current_salary == cap_module.rookie_salary(world.salary_cap)
    assert 1 in team.roster


# ---------------------------------------------------------------------------
# run_fa_wave / run_free_agency -- market clearing, no stall
# ---------------------------------------------------------------------------
def test_run_fa_wave_signs_players_within_the_open_tier():
    world = build_world_with_teams(n_teams=32)
    add_free_agents(world, 10, overall=85)   # wave-0 caliber

    result = fa.run_fa_wave(world)   # world.fa_wave is None -> treated as "everyone open"
    assert result["signings"] > 0
    signed = [p for p in world.players.values() if not p.is_free_agent]
    assert len(signed) == result["signings"]


def test_run_free_agency_clears_a_realistic_market_without_stalling():
    world = build_world_with_teams(n_teams=32)
    # A broad spread of talent, more than enough to fill out every roster if the market clears.
    add_free_agents(world, 20, start_pid=1, overall=88)     # stars
    add_free_agents(world, 60, start_pid=100, overall=74)   # everyday players
    add_free_agents(world, 100, start_pid=300, overall=55)  # depth

    result = fa.run_free_agency(world)

    assert result["signings"] > 0
    assert result["waves_run"] <= fa.NUM_FA_WAVES
    # The market actually closed (fa_wave reset to None), not left dangling mid-wave.
    assert getattr(world, "fa_wave", None) is None
    # Every signed player is properly on a roster and mirrored via team_id.
    for team in world.team_list():
        for pid in team.roster:
            assert world.player(pid).team_id == team.tid


def test_run_free_agency_does_not_infinite_loop_with_oversized_pool():
    """A free-agent pool far larger than the league can absorb must still terminate --
    the market simply leaves the excess unsigned rather than looping forever."""
    world = build_world_with_teams(n_teams=4)
    add_free_agents(world, 500, overall=50)   # way more than 4 teams' worth of roster spots

    result = fa.run_free_agency(world)
    assert result["waves_run"] <= fa.NUM_FA_WAVES
    # Some players necessarily remain unsigned (roster capacity is finite).
    assert len(world.free_agent_players()) > 0


def test_run_free_agency_respects_roster_and_cap_ceilings():
    world = build_world_with_teams(n_teams=2, cap_value=90_000_000)
    add_free_agents(world, 60, overall=80)   # expensive-ish talent, oversubscribed

    fa.run_free_agency(world)

    for team in world.team_list():
        assert len(team.roster) <= config.ROSTER_MAX
        from pucksim.systems import cap as cap_module
        assert cap_module.payroll(world, team) <= world.salary_cap


def test_run_free_agency_can_exclude_a_team_eg_the_user():
    world = build_world_with_teams(n_teams=4)
    add_free_agents(world, 40, overall=75)

    fa.run_free_agency(world, exclude_tid=1)

    assert world.team(1).roster == []
