"""Tests for pucksim.models.tactics -- Step 1.10 done-criteria."""
from pucksim.models.tactics import SETTINGS, Tactics


def test_default_tactics_use_middle_balanced_option():
    t = Tactics()
    assert t.forecheck_style == "balanced"


def test_cycle_advances_through_all_options_and_wraps_around():
    options = SETTINGS["forecheck_style"]

    t = Tactics()
    t.forecheck_style = options[0]
    visited = [t.forecheck_style]
    for _ in range(len(options)):
        t.cycle("forecheck_style")
        visited.append(t.forecheck_style)

    # Starting from the first option and cycling len(options) times visits every
    # option in order, then wraps back around to the first.
    assert visited == list(options) + [options[0]]


def test_items_returns_field_name_value_pairs():
    t = Tactics()
    assert t.items() == [("forecheck_style", "balanced")]


def test_to_dict_from_dict_round_trip():
    t = Tactics(forecheck_style="aggressive")
    d = t.to_dict()
    assert d == {"forecheck_style": "aggressive"}

    restored = Tactics.from_dict(d)
    assert restored == t


def test_from_dict_invalid_value_falls_back_to_default():
    restored = Tactics.from_dict({"forecheck_style": "not-a-real-option"})
    assert restored.forecheck_style == "balanced"


def test_from_dict_missing_key_falls_back_to_default():
    restored = Tactics.from_dict({})
    assert restored.forecheck_style == "balanced"
