"""Tests for pucksim.models.draft -- Step 1.10 done-criteria."""
import pytest

from pucksim.models.draft import DraftClass, DraftPick


# -- DraftPick ----------------------------------------------------------------

def test_draft_pick_key_is_stable_regardless_of_owner():
    original = DraftPick(year=2027, round=1, original_tid=3, owner_tid=3)
    traded = DraftPick(year=2027, round=1, original_tid=3, owner_tid=9)
    assert original.key == traded.key == "2027-1-3"


def test_draft_pick_to_dict_from_dict_round_trip():
    pick = DraftPick(year=2026, round=2, original_tid=5, owner_tid=12)
    restored = DraftPick.from_dict(pick.to_dict())
    assert restored == pick
    assert restored.key == pick.key


# -- DraftClass: pick-order advancement ----------------------------------------

def _sample_class() -> DraftClass:
    # 3 teams, 2 rounds -> 6 total picks, flat order.
    order = [1, 2, 3, 3, 2, 1]
    return DraftClass(year=2026, prospect_ids=[100, 101, 102, 103, 104, 105], order=order)


def test_team_on_clock_advances_through_order():
    dc = _sample_class()
    assert dc.team_on_clock() == 1
    dc.record_pick(100, 1)
    assert dc.team_on_clock() == 2
    dc.record_pick(101, 2)
    assert dc.team_on_clock() == 3
    dc.record_pick(102, 3)
    assert dc.team_on_clock() == 3
    dc.record_pick(103, 3)
    assert dc.team_on_clock() == 2
    dc.record_pick(104, 2)
    assert dc.team_on_clock() == 1
    dc.record_pick(105, 1)
    assert dc.complete is True
    assert dc.team_on_clock() is None


def test_record_pick_raises_on_wrong_team_on_clock():
    dc = _sample_class()
    with pytest.raises(ValueError):
        dc.record_pick(100, 2)  # team 1 is on the clock, not team 2


def test_record_pick_raises_on_already_picked_prospect():
    dc = _sample_class()
    dc.record_pick(100, 1)
    with pytest.raises(ValueError):
        dc.record_pick(100, 2)  # prospect 100 already drafted


def test_record_pick_raises_once_draft_is_complete():
    order = [1]
    dc = DraftClass(year=2026, prospect_ids=[100], order=order)
    dc.record_pick(100, 1)
    assert dc.complete is True
    with pytest.raises(ValueError):
        dc.record_pick(999, 1)


def test_remaining_prospects_shrinks_correctly():
    dc = _sample_class()
    assert dc.remaining_prospects() == [100, 101, 102, 103, 104, 105]
    dc.record_pick(100, 1)
    assert dc.remaining_prospects() == [101, 102, 103, 104, 105]
    dc.record_pick(101, 2)
    dc.record_pick(102, 3)
    assert dc.remaining_prospects() == [103, 104, 105]


# -- serialization --------------------------------------------------------------

def test_draft_class_to_dict_from_dict_round_trip():
    dc = _sample_class()
    dc.record_pick(100, 1)
    dc.record_pick(101, 2)

    restored = DraftClass.from_dict(dc.to_dict())

    assert restored.year == dc.year
    assert restored.prospect_ids == dc.prospect_ids
    assert restored.order == dc.order
    assert restored.current_pick == dc.current_pick
    assert restored.picks_made == dc.picks_made
    assert restored.team_on_clock() == dc.team_on_clock()
    assert restored.remaining_prospects() == dc.remaining_prospects()


def test_draft_class_from_dict_defaults_on_missing_fields():
    dc = DraftClass.from_dict({"year": 2030})
    assert dc.year == 2030
    assert dc.prospect_ids == []
    assert dc.order == []
    assert dc.current_pick == 0
    assert dc.picks_made == []
    assert dc.complete is True  # empty order -> immediately complete
    assert dc.team_on_clock() is None
