"""Tests for pucksim.systems.cap -- DEVPLAN.md Step 2.4 done-criteria."""
from __future__ import annotations

from pucksim import config
from pucksim.models import attributes as attr
from pucksim.models.contract import flat_contract
from pucksim.models.player import Player
from pucksim.models.team import Team
from pucksim.models.world import World
from pucksim.rng import Rng
from pucksim.systems import cap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _skater_ratings(value: int = 70) -> dict:
    return {name: value for name in attr.ALL_RATINGS}


def make_skater(pid: int, overall: int = 70, age: int = 27, salary: int = 3_000_000,
                 years: int = 3, **overrides) -> Player:
    kwargs = dict(
        pid=pid,
        name=f"Skater {pid}",
        age=age,
        position="C",
        ratings=_skater_ratings(overall),
        contract=flat_contract(salary, years),
    )
    kwargs.update(overrides)
    return Player(**kwargs)


def build_world() -> World:
    world = World(rng=Rng(seed=1))
    team = Team(tid=1, name="Team 1", abbrev="T1", conference="Eastern")
    world.register_team(team)
    return world


def sign(world: World, team: Team, player: Player) -> None:
    world.add_player(player)
    world.sign_player(player.pid, team.tid)


# ---------------------------------------------------------------------------
# payroll / cap_space / over_cap
# ---------------------------------------------------------------------------
def test_payroll_sums_current_salary_of_roster_only():
    world = build_world()
    team = world.team(1)
    sign(world, team, make_skater(1, salary=5_000_000))
    sign(world, team, make_skater(2, salary=3_000_000))
    # A free agent (never signed) must not count.
    world.add_player(make_skater(3, salary=99_000_000, team_id=None))

    assert cap.payroll(world, team) == 8_000_000


def test_cap_space_is_cap_minus_payroll_and_floors_at_zero():
    world = build_world()
    world.salary_cap = 10_000_000
    team = world.team(1)
    sign(world, team, make_skater(1, salary=4_000_000))

    assert cap.cap_space(world, team) == 6_000_000

    sign(world, team, make_skater(2, salary=20_000_000))
    assert cap.payroll(world, team) == 24_000_000
    assert cap.cap_space(world, team) == 0   # floored, never negative


def test_over_cap_true_only_once_payroll_exceeds_cap():
    world = build_world()
    world.salary_cap = 10_000_000
    team = world.team(1)
    sign(world, team, make_skater(1, salary=9_000_000))
    assert cap.over_cap(world, team) is False

    sign(world, team, make_skater(2, salary=2_000_000))
    assert cap.over_cap(world, team) is True


# ---------------------------------------------------------------------------
# max_salary / base_salary_for / market_salary
# ---------------------------------------------------------------------------
def test_max_salary_is_flat_fraction_of_cap():
    assert cap.max_salary(100_000_000) == int(100_000_000 * config.MAX_SALARY_CAP_FRACTION)


def test_base_salary_for_is_monotonic_in_overall():
    values = [cap.base_salary_for(ovr) for ovr in range(config.RATING_MIN, config.RATING_MAX + 1)]
    for a, b in zip(values, values[1:]):
        assert b >= a


def test_base_salary_for_never_below_minimum():
    assert cap.base_salary_for(config.RATING_MIN) == config.MINIMUM_SALARY


def test_market_salary_never_below_minimum_and_never_above_max():
    world_cap = 90_000_000
    low = make_skater(1, overall=25, age=40)
    high = make_skater(2, overall=99, age=27)

    assert cap.market_salary(low, world_cap) >= config.MINIMUM_SALARY
    assert cap.market_salary(high, world_cap) <= cap.max_salary(world_cap)


def test_market_salary_young_high_potential_gets_upside_premium():
    world_cap = 90_000_000
    base_player = make_skater(1, overall=70, age=27, potential=70)
    upside_player = make_skater(2, overall=70, age=21, potential=90)

    assert cap.market_salary(upside_player, world_cap) > cap.market_salary(base_player, world_cap)


def test_market_salary_aging_player_gets_discount():
    world_cap = 90_000_000
    prime = make_skater(1, overall=75, age=28)
    aging = make_skater(2, overall=75, age=36)

    assert cap.market_salary(aging, world_cap) < cap.market_salary(prime, world_cap)


def test_rookie_salary_is_small_flat_fraction_of_cap_and_grows_with_cap():
    small_cap = 80_000_000
    big_cap = 100_000_000
    assert cap.rookie_salary(small_cap) < cap.rookie_salary(big_cap)
    assert cap.rookie_salary(small_cap) < cap.market_salary(make_skater(1, overall=80), small_cap)


# ---------------------------------------------------------------------------
# trade_value
# ---------------------------------------------------------------------------
def test_trade_value_higher_for_better_player():
    world_cap = 90_000_000
    good = make_skater(1, overall=88, age=26)
    bad = make_skater(2, overall=60, age=26)
    assert cap.trade_value(good, world_cap) > cap.trade_value(bad, world_cap)


def test_trade_value_never_negative():
    world_cap = 90_000_000
    scrub = make_skater(1, overall=25, age=39, salary=15_000_000)  # overpaid + washed
    assert cap.trade_value(scrub, world_cap) >= 0.1


def test_trade_value_rewards_youth_at_equal_overall():
    world_cap = 90_000_000
    young = make_skater(1, overall=80, age=23)
    old = make_skater(2, overall=80, age=34)
    assert cap.trade_value(young, world_cap) > cap.trade_value(old, world_cap)


def test_trade_value_rewards_contract_surplus():
    world_cap = 90_000_000
    cheap = make_skater(1, overall=85, age=27, salary=1_000_000)
    expensive = make_skater(2, overall=85, age=27, salary=15_000_000)
    assert cap.trade_value(cheap, world_cap) > cap.trade_value(expensive, world_cap)


# ---------------------------------------------------------------------------
# trade_matching_ok
# ---------------------------------------------------------------------------
def test_trade_matching_ok_allows_within_space_plus_outgoing_plus_buffer():
    # 0 space, sending out 2M, buffer 3M -> can absorb up to 5M.
    assert cap.trade_matching_ok(space_before=0, outgoing=2_000_000, incoming=5_000_000) is True
    assert cap.trade_matching_ok(space_before=0, outgoing=2_000_000, incoming=5_000_001) is False


def test_trade_matching_ok_true_when_plenty_of_space():
    assert cap.trade_matching_ok(space_before=50_000_000, outgoing=0, incoming=10_000_000) is True


# ---------------------------------------------------------------------------
# can_extend / extend_contract
# ---------------------------------------------------------------------------
def test_can_extend_false_if_player_not_on_roster():
    world = build_world()
    p = make_skater(1)
    world.add_player(p)  # never signed
    ok, _ = cap.can_extend(world.team(1), 1, world)
    assert ok is False


def test_can_extend_false_at_max_contract_length():
    world = build_world()
    team = world.team(1)
    p = make_skater(1, years=config.MAX_CONTRACT_YEARS)
    sign(world, team, p)
    ok, reason = cap.can_extend(team, 1, world)
    assert ok is False
    assert "maximum" in reason.lower()


def test_extend_contract_adds_years_and_updates_salary_within_cap():
    world = build_world()
    world.salary_cap = 90_000_000
    team = world.team(1)
    p = make_skater(1, salary=3_000_000, years=2)
    sign(world, team, p)

    ok, msg = cap.extend_contract(world, team, 1, salary=4_000_000, add_years=2)
    assert ok is True
    assert p.contract.years_remaining == 4
    assert p.contract.salaries == [3_000_000, 3_000_000, 4_000_000, 4_000_000]


def test_extend_contract_rejects_above_max_salary():
    world = build_world()
    world.salary_cap = 10_000_000
    team = world.team(1)
    p = make_skater(1, salary=1_000_000, years=1)
    sign(world, team, p)

    too_rich = cap.max_salary(world.salary_cap) + 1
    ok, reason = cap.extend_contract(world, team, 1, salary=too_rich, add_years=1)
    assert ok is False
    assert "maximum salary" in reason.lower()


def test_extend_contract_rejects_when_no_cap_room():
    world = build_world()
    world.salary_cap = 100_000_000   # max_salary is 20M, well above the salary we're testing
    team = world.team(1)
    p1 = make_skater(1, salary=1_000_000, years=1)
    p2 = make_skater(2, salary=98_000_000, years=3)
    sign(world, team, p1)
    sign(world, team, p2)

    # p1's extension has nowhere to fit once p2 eats nearly the whole cap.
    ok, reason = cap.extend_contract(world, team, 1, salary=5_000_000, add_years=1)
    assert ok is False
    assert "cap space" in reason.lower()


# ---------------------------------------------------------------------------
# grow_cap
# ---------------------------------------------------------------------------
def test_grow_cap_increases_by_rate():
    world = build_world()
    world.salary_cap = 100_000_000
    cap.grow_cap(world, rate=0.05)
    assert world.salary_cap == 105_000_000


def test_grow_cap_default_rate_uses_config_constant():
    world = build_world()
    world.salary_cap = 100_000_000
    cap.grow_cap(world)
    assert world.salary_cap == int(100_000_000 * (1 + config.CAP_GROWTH_RATE))


def test_grow_cap_is_monotonic_across_repeated_seasons():
    world = build_world()
    world.salary_cap = 80_000_000
    caps = []
    for _ in range(5):
        cap.grow_cap(world)
        caps.append(world.salary_cap)
    for a, b in zip(caps, caps[1:]):
        assert b > a


# ---------------------------------------------------------------------------
# can_sign
# ---------------------------------------------------------------------------
def test_can_sign_false_when_roster_full():
    world = build_world()
    world.salary_cap = 200_000_000  # plenty of room
    team = world.team(1)
    for i in range(config.ROSTER_MAX):
        sign(world, team, make_skater(i + 1, salary=1))
    assert len(team.roster) == config.ROSTER_MAX

    ok, reason = cap.can_sign(world, team, 1_000_000)
    assert ok is False
    assert "full" in reason.lower()


def test_can_sign_false_when_over_cap_space():
    world = build_world()
    world.salary_cap = 5_000_000
    team = world.team(1)
    sign(world, team, make_skater(1, salary=4_000_000))

    ok, reason = cap.can_sign(world, team, 2_000_000)
    assert ok is False
    assert "cap space" in reason.lower()


def test_can_sign_true_within_cap_space_and_roster_room():
    world = build_world()
    world.salary_cap = 80_000_000
    team = world.team(1)
    sign(world, team, make_skater(1, salary=4_000_000))

    ok, _ = cap.can_sign(world, team, 2_000_000)
    assert ok is True


def test_can_sign_reserves_room_to_fill_the_roster_minimum():
    """A team may not spend down past what it needs to ice a legal roster.

    Without this, a team can legally commit every dollar it has while still short of
    ``ROSTER_MIN``, and ``offseason.fill_rosters`` -- which must complete, since a team
    below the minimum can't ice a lineup -- is then forced to sign it over the hard cap.
    """
    world = build_world()
    world.salary_cap = 20_000_000
    team = world.team(1)
    sign(world, team, make_skater(1, salary=4_000_000))

    # 1 player rostered, so 18 more are still required to reach ROSTER_MIN (20) after
    # this signing; that room is held back out of the $16M of raw space.
    reserve = (config.ROSTER_MIN - 2) * config.MINIMUM_SALARY
    assert cap.signing_allowance(world, team) == cap.cap_space(world, team) - reserve

    ok, reason = cap.can_sign(world, team, 2_000_000)
    assert ok is False
    assert "roster minimum" in reason.lower()

    ok, _ = cap.can_sign(world, team, cap.signing_allowance(world, team))
    assert ok is True


def test_signing_allowance_is_plain_cap_space_for_a_full_roster():
    """Once no mandatory spots remain, nothing is held back."""
    world = build_world()
    world.salary_cap = 80_000_000
    team = world.team(1)
    for pid in range(1, config.ROSTER_MIN + 1):
        sign(world, team, make_skater(pid, salary=config.MINIMUM_SALARY))

    assert cap.signing_allowance(world, team) == cap.cap_space(world, team)


def test_can_sign_hard_cap_no_exception_over_the_line():
    """v1's hockey cap is a genuine hard cap -- no minimum-contract/MLE-style exception
    exists to sign over cap space the way HoopR's NBA model allows."""
    world = build_world()
    world.salary_cap = 1_000_000
    team = world.team(1)
    sign(world, team, make_skater(1, salary=1_000_000))  # exactly at the cap

    ok, _ = cap.can_sign(world, team, config.MINIMUM_SALARY)
    assert ok is False
