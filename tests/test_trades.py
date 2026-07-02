"""Tests for pucksim.systems.trades -- DEVPLAN.md Step 2.4 done-criteria.

Every trade in these tests goes through ``World.transfer_player`` (via
``trades.execute_trade``/``propose_trade``), never direct ``Team.roster``/
``Player.team_id`` manipulation -- verified indirectly by asserting both sides of a
successful trade land in a mutually consistent state (roster membership AND
``player.team_id`` both flip, which would desync if anything bypassed ``World``'s
transaction methods).
"""
from __future__ import annotations

from pucksim import config
from pucksim.models import attributes as attr
from pucksim.models.contract import flat_contract
from pucksim.models.league import Phase
from pucksim.models.player import Player
from pucksim.models.team import Team
from pucksim.models.world import World
from pucksim.rng import Rng
from pucksim.systems import trades


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _skater_ratings(value: int = 70) -> dict:
    return {name: value for name in attr.ALL_RATINGS}


def make_skater(pid: int, overall: int = 70, age: int = 27, salary: int = 3_000_000,
                 years: int = 2, **overrides) -> Player:
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


def build_two_team_world(cap_value: int = 90_000_000) -> World:
    world = World(rng=Rng(seed=7))
    world.salary_cap = cap_value
    world.phase = Phase.REGULAR_SEASON
    world.day = 1
    a = Team(tid=1, name="Team A", abbrev="AAA", conference="Eastern")
    b = Team(tid=2, name="Team B", abbrev="BBB", conference="Western")
    world.register_team(a)
    world.register_team(b)
    return world


def sign(world: World, team: Team, player: Player) -> None:
    world.add_player(player)
    world.sign_player(player.pid, team.tid)


def fill_roster(world: World, team: Team, n: int, start_pid: int, **kwargs) -> None:
    for i in range(n):
        sign(world, team, make_skater(start_pid + i, **kwargs))


# ---------------------------------------------------------------------------
# validate_trade -- legality
# ---------------------------------------------------------------------------
def test_validate_trade_rejects_empty_offer():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 20, 1)
    fill_roster(world, world.team(2), 20, 100)

    ok, reason = trades.validate_trade(world, trades.TradeOffer(a=1, b=2))
    assert ok is False
    assert "empty" in reason.lower()


def test_validate_trade_rejects_player_not_on_roster():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 20, 1)
    fill_roster(world, world.team(2), 20, 100)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[999])
    ok, reason = trades.validate_trade(world, offer)
    assert ok is False
    assert "not on" in reason.lower()


def test_validate_trade_rejects_no_trade_clause_player():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 20, 1)
    fill_roster(world, world.team(2), 20, 100)
    p = world.player(1)
    p.contract.no_trade = True

    offer = trades.TradeOffer(a=1, b=2, a_sends=[1], b_sends=[100])
    ok, reason = trades.validate_trade(world, offer)
    assert ok is False
    assert "no-trade" in reason.lower()


def test_validate_trade_legal_simple_one_for_one_within_cap():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 20, 1, salary=2_000_000)
    fill_roster(world, world.team(2), 20, 100, salary=2_000_000)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[1], b_sends=[100])
    ok, reason = trades.validate_trade(world, offer)
    assert ok is True


def test_validate_trade_rejects_when_incoming_salary_too_large_to_match():
    world = build_two_team_world(cap_value=20_000_000)
    # Team 1 is already tight against the cap.
    fill_roster(world, world.team(1), 20, 1, salary=990_000)
    fill_roster(world, world.team(2), 20, 100, salary=990_000)
    # Team 2's player 100 has a huge salary team 1 can't absorb.
    world.player(100).contract = flat_contract(15_000_000, 2)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[1], b_sends=[100])
    ok, reason = trades.validate_trade(world, offer)
    assert ok is False
    assert "cannot match salary" in reason.lower()


def test_validate_trade_respects_trade_matching_buffer():
    world = build_two_team_world(cap_value=20_000_000)
    fill_roster(world, world.team(1), 20, 1, salary=990_000)
    fill_roster(world, world.team(2), 20, 100, salary=990_000)
    # Give team 1 exactly TRADE_MATCH_BUFFER of headroom above outgoing salary.
    world.player(100).contract = flat_contract(
        world.player(1).contract.current_salary + config.TRADE_MATCH_BUFFER, 2
    )
    offer = trades.TradeOffer(a=1, b=2, a_sends=[1], b_sends=[100])
    ok, _ = trades.validate_trade(world, offer)
    assert ok is True


def test_validate_trade_rejects_below_roster_floor():
    world = build_two_team_world()
    # Team 1 at the bare minimum roster size; team 2 sends back nothing.
    fill_roster(world, world.team(1), config.ROSTER_MIN, 1, salary=1_000_000)
    fill_roster(world, world.team(2), 20, 100, salary=1_000_000)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[1])   # 1-for-nothing
    ok, reason = trades.validate_trade(world, offer)
    assert ok is False
    assert "floor" in reason.lower()


def test_validate_trade_rejects_above_roster_max():
    world = build_two_team_world()
    fill_roster(world, world.team(1), config.ROSTER_MAX, 1, salary=1_000_000)
    fill_roster(world, world.team(2), 5, 100, salary=1_000_000)

    # Team 1 gives up nobody but receives 5 players -- blows past ROSTER_MAX.
    offer = trades.TradeOffer(a=1, b=2, b_sends=[100, 101, 102, 103, 104])
    ok, reason = trades.validate_trade(world, offer)
    assert ok is False
    assert "maximum" in reason.lower()


def test_validate_trade_rejects_after_deadline():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 20, 1, salary=1_000_000)
    fill_roster(world, world.team(2), 20, 100, salary=1_000_000)
    world.day = trades.trade_deadline_day(world) + 1

    offer = trades.TradeOffer(a=1, b=2, a_sends=[1], b_sends=[100])
    ok, reason = trades.validate_trade(world, offer)
    assert ok is False
    assert "deadline" in reason.lower()


# ---------------------------------------------------------------------------
# execute_trade / propose_trade -- must route through World's transaction methods
# ---------------------------------------------------------------------------
def test_execute_trade_moves_players_via_world_and_keeps_state_consistent():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 20, 1, salary=2_000_000)
    fill_roster(world, world.team(2), 20, 100, salary=2_000_000)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[1], b_sends=[100])
    ok, msg = trades.propose_trade(world, offer)
    assert ok is True

    # player 1 now on team 2, player 100 now on team 1 -- both sides of the mirror in sync.
    assert world.player(1).team_id == 2
    assert 1 in world.team(2).roster
    assert 1 not in world.team(1).roster

    assert world.player(100).team_id == 1
    assert 100 in world.team(1).roster
    assert 100 not in world.team(2).roster


def test_execute_trade_rebuilds_lineups_for_both_teams():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 20, 1, salary=2_000_000)
    fill_roster(world, world.team(2), 20, 100, salary=2_000_000)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[1], b_sends=[100])
    trades.propose_trade(world, offer)

    # auto_build_lines should have populated some lines/pairs on both sides.
    assert world.team(1).lines or world.team(1).pairs
    assert world.team(2).lines or world.team(2).pairs


def test_propose_trade_rejects_illegal_offer_without_mutating_state():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 20, 1, salary=2_000_000)
    fill_roster(world, world.team(2), 20, 100, salary=2_000_000)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[999])  # illegal: not on roster
    ok, _ = trades.propose_trade(world, offer)
    assert ok is False
    # Nothing should have moved.
    assert 1 in world.team(1).roster
    assert 100 in world.team(2).roster


# ---------------------------------------------------------------------------
# ai_evaluates -- accept/reject threshold
# ---------------------------------------------------------------------------
def test_ai_evaluates_accepts_clearly_favorable_trade():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 19, 1, salary=1_000_000, overall=60)
    fill_roster(world, world.team(2), 19, 100, salary=1_000_000, overall=60)
    # Team 1 gives up a star; team 2 gives up a scrub -- clearly good for team 2 (the AI).
    star = make_skater(500, overall=92, age=25, salary=2_000_000)
    scrub = make_skater(501, overall=45, age=34, salary=1_000_000)
    sign(world, world.team(1), star)
    sign(world, world.team(2), scrub)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[500], b_sends=[501])
    ok, reason = trades.ai_evaluates(world, offer, ai_tid=2)
    assert ok is True


def test_ai_evaluates_rejects_clearly_unfavorable_trade():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 19, 1, salary=1_000_000, overall=60)
    fill_roster(world, world.team(2), 19, 100, salary=1_000_000, overall=60)
    star = make_skater(500, overall=92, age=25, salary=2_000_000)
    scrub = make_skater(501, overall=45, age=34, salary=1_000_000)
    sign(world, world.team(1), star)
    sign(world, world.team(2), scrub)

    # From team 1's perspective this trade is bad (giving up the star for a scrub).
    offer = trades.TradeOffer(a=1, b=2, a_sends=[500], b_sends=[501])
    ok, reason = trades.ai_evaluates(world, offer, ai_tid=1)
    assert ok is False


def test_ai_evaluates_exactly_even_trade_is_a_near_miss_not_a_flat_reject():
    """An exactly value-neutral trade (v_in == v_out) sits just below AI_ACCEPT_RATIO
    (which requires the incoming side to be *at least* 3% richer) -- per the documented
    threshold this is the "we'd want a bit more" near-miss band, not a "too lopsided"
    flat rejection. Distinguishing the two matters for a future negotiation UI even
    though both currently just return False."""
    world = build_two_team_world()
    fill_roster(world, world.team(1), 19, 1, salary=1_000_000, overall=60)
    fill_roster(world, world.team(2), 19, 100, salary=1_000_000, overall=60)
    p_a = make_skater(500, overall=75, age=27, salary=3_000_000)
    p_b = make_skater(501, overall=75, age=27, salary=3_000_000)
    sign(world, world.team(1), p_a)
    sign(world, world.team(2), p_b)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[500], b_sends=[501])
    ok_a, reason_a = trades.ai_evaluates(world, offer, ai_tid=1)
    assert ok_a is False
    assert "bit more" in reason_a.lower()


def test_ai_evaluates_slightly_favorable_trade_is_accepted():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 19, 1, salary=1_000_000, overall=60)
    fill_roster(world, world.team(2), 19, 100, salary=1_000_000, overall=60)
    # Team 2's return is a clearly better/younger player than what it gives up.
    p_a = make_skater(500, overall=80, age=25, salary=3_000_000)
    p_b = make_skater(501, overall=75, age=27, salary=3_000_000)
    sign(world, world.team(1), p_a)
    sign(world, world.team(2), p_b)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[500], b_sends=[501])
    ok_b, _ = trades.ai_evaluates(world, offer, ai_tid=2)
    assert ok_b is True


def test_ai_evaluates_rejects_illegal_trade_before_valuing_it():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 20, 1, salary=2_000_000)
    fill_roster(world, world.team(2), 20, 100, salary=2_000_000)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[999])  # illegal
    ok, reason = trades.ai_evaluates(world, offer, ai_tid=2)
    assert ok is False


def test_ai_evaluates_unknown_team_returns_false():
    world = build_two_team_world()
    fill_roster(world, world.team(1), 20, 1, salary=2_000_000)
    fill_roster(world, world.team(2), 20, 100, salary=2_000_000)

    offer = trades.TradeOffer(a=1, b=2, a_sends=[1], b_sends=[100])
    ok, reason = trades.ai_evaluates(world, offer, ai_tid=999)
    assert ok is False


# ---------------------------------------------------------------------------
# trade_deadline_day / trade_deadline_passed
# ---------------------------------------------------------------------------
def test_trade_deadline_day_is_fraction_of_season_games():
    world = build_two_team_world()
    expected = round(config.TRADE_DEADLINE_FRACTION * config.SEASON_GAMES)
    assert trades.trade_deadline_day(world) == expected


def test_trade_deadline_passed_false_before_and_true_after():
    world = build_two_team_world()
    deadline = trades.trade_deadline_day(world)

    world.day = deadline
    assert trades.trade_deadline_passed(world) is False

    world.day = deadline + 1
    assert trades.trade_deadline_passed(world) is True


def test_trade_deadline_passed_false_outside_regular_season():
    world = build_two_team_world()
    world.phase = Phase.OFFSEASON
    world.day = trades.trade_deadline_day(world) + 100
    assert trades.trade_deadline_passed(world) is False
