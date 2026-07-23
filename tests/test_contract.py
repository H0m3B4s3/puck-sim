"""Tests for pucksim.models.contract — Step 1.5 done-criteria."""
from pucksim.models.contract import Contract, flat_contract


def test_advance_year_drops_year_zero_and_shifts_salaries_and_guarantees():
    c = Contract(
        salaries=[1_000_000, 2_000_000, 3_000_000],
        guaranteed=[True, False, True],
    )
    c.advance_year()
    assert c.salaries == [2_000_000, 3_000_000]
    assert c.guaranteed == [False, True]
    assert c.years_with_team == 1

    c.advance_year()
    assert c.salaries == [3_000_000]
    assert c.guaranteed == [True]
    assert c.years_with_team == 2

    c.advance_year()
    assert c.salaries == []
    assert c.guaranteed == []
    assert c.years_with_team == 3


def test_advance_year_shifts_and_drops_options():
    # Option at index 0 (this year) and index 1 (next year).
    c = Contract(
        salaries=[1_000_000, 2_000_000, 3_000_000],
        guaranteed=[True, True, True],
        options={0: "team", 1: "player"},
    )
    c.advance_year()
    # The index-0 option (for the year that just passed) is gone.
    # The index-1 option shifts down to index 0.
    assert c.options == {0: "player"}
    assert c.option_for_year(0) == "player"
    assert c.option_for_year(1) is None


def test_advance_year_on_expiring_contract_is_a_no_op_safe():
    c = Contract(salaries=[500_000], guaranteed=[True])
    c.advance_year()
    assert c.salaries == []
    assert c.guaranteed == []
    # Calling again on an empty contract should not raise.
    c.advance_year()
    assert c.salaries == []
    assert c.years_with_team == 2


def test_years_remaining_and_is_expiring():
    c = flat_contract(1_000_000, 3)
    assert c.years_remaining == 3
    assert c.is_expiring is False

    c.advance_year()
    c.advance_year()
    assert c.years_remaining == 1
    assert c.is_expiring is True

    c.advance_year()
    assert c.years_remaining == 0
    assert c.is_expiring is True


def test_current_salary_and_total_remaining():
    c = Contract(salaries=[1_000_000, 2_000_000, 3_000_000], guaranteed=[True, True, True])
    assert c.current_salary == 1_000_000
    assert c.total_remaining == 6_000_000

    empty = Contract()
    assert empty.current_salary == 0
    assert empty.total_remaining == 0


def test_to_dict_from_dict_round_trip_with_options_and_mixed_guarantees():
    c = Contract(
        salaries=[750_000, 1_500_000, 2_250_000],
        guaranteed=[True, False, False],
        options={2: "team"},
        no_trade=True,
        signed_year=2025,
        years_with_team=4,
        is_rookie_scale=True,
    )
    d = c.to_dict()
    restored = Contract.from_dict(d)

    assert restored == c
    assert restored.salaries == [750_000, 1_500_000, 2_250_000]
    assert restored.guaranteed == [True, False, False]
    assert restored.options == {2: "team"}
    assert restored.no_trade is True
    assert restored.signed_year == 2025
    assert restored.years_with_team == 4
    assert restored.is_rookie_scale is True

    # Options dict keys must survive the str/int round trip through JSON-like dicts.
    assert all(isinstance(k, int) for k in restored.options)


def test_slide_years_round_trips_and_defaults_to_zero():
    """ELC slide bookkeeping (docs/PROSPECT_DEV_PLAN.md). systems/prospects.py applies the
    rule; Contract only has to remember what it did."""
    fresh = Contract(salaries=[900_000] * 3, guaranteed=[True] * 3, is_rookie_scale=True)
    assert fresh.slide_years == 0

    slid = Contract.from_dict({**fresh.to_dict(), "slide_years": 2})
    assert slid.slide_years == 2
    assert Contract.from_dict(slid.to_dict()).slide_years == 2


def test_from_dict_defaults_slide_years_on_a_pre_slide_rule_save():
    """Saves written before the slide rule existed have no such key."""
    legacy = flat_contract(900_000, 3, is_rookie_scale=True).to_dict()
    del legacy["slide_years"]
    assert Contract.from_dict(legacy).slide_years == 0


def test_advance_year_is_independent_of_slide_years():
    """A slide is the DECISION NOT to call advance_year, taken by systems/prospects.py --
    Contract itself has no slide behavior baked into it, so a contract that has slid before
    still burns a normal year whenever it is advanced."""
    c = flat_contract(900_000, 3, is_rookie_scale=True)
    c.slide_years = 2
    c.advance_year()
    assert c.years_remaining == 2
    assert c.slide_years == 2


def test_to_dict_produces_json_safe_option_keys():
    c = Contract(salaries=[1], guaranteed=[True], options={0: "player"})
    d = c.to_dict()
    assert d["options"] == {"0": "player"}


def test_free_agent_factory_is_empty_contract():
    fa = Contract.free_agent()
    assert fa.salaries == []
    assert fa.guaranteed == []
    assert fa.years_remaining == 0
    assert fa.is_expiring is True


def test_flat_contract_factory_fully_guaranteed_default():
    c = flat_contract(5_000_000, 4)
    assert c.salaries == [5_000_000] * 4
    assert c.guaranteed == [True] * 4
    assert c.years_remaining == 4
    assert c.total_remaining == 20_000_000
    assert c.is_rookie_scale is False
    assert c.options == {}
    assert c.no_trade is False


def test_flat_contract_factory_non_guaranteed_and_rookie_scale():
    c = flat_contract(925_000, 3, guaranteed=False, is_rookie_scale=True, signed_year=2026,
                       years_with_team=0)
    assert c.salaries == [925_000, 925_000, 925_000]
    assert c.guaranteed == [False, False, False]
    assert c.is_rookie_scale is True
    assert c.signed_year == 2026


def test_two_way_flag_round_trips_and_defaults_to_one_way():
    """Two-way contracts (docs/PROSPECT_DEV_PLAN.md follow-up). Default is one-way, the norm
    for a rostered NHL player and the safe default for a save written before the field."""
    one_way = flat_contract(4_000_000, 3)
    assert one_way.two_way is False
    two_way = flat_contract(900_000, 3, is_rookie_scale=True, two_way=True)
    assert two_way.two_way is True

    assert Contract.from_dict(two_way.to_dict()).two_way is True
    legacy = flat_contract(4_000_000, 3).to_dict()
    del legacy["two_way"]
    assert Contract.from_dict(legacy).two_way is False
