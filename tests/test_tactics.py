"""Tests for pucksim.models.tactics -- Step 1.10 done-criteria, extended for Step 2.8's
PP/PK style fields (``pp_style``/``pk_aggression``)."""
from pucksim.models.tactics import SETTINGS, Tactics


def test_default_tactics_use_middle_balanced_option():
    t = Tactics()
    assert t.forecheck_style == "balanced"


def test_default_pp_style_and_pk_aggression_are_valid_settings():
    t = Tactics()
    assert t.pp_style in SETTINGS["pp_style"]
    assert t.pk_aggression in SETTINGS["pk_aggression"]


def test_cycle_advances_pp_style_and_wraps_around():
    options = SETTINGS["pp_style"]
    t = Tactics()
    t.pp_style = options[0]
    visited = [t.pp_style]
    for _ in range(len(options)):
        t.cycle("pp_style")
        visited.append(t.pp_style)
    assert visited == list(options) + [options[0]]


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
    # DEVPLAN.md Step 2.8 added pp_style/pk_aggression alongside the original
    # forecheck_style -- items() reflects all of SETTINGS, in SETTINGS order.
    t = Tactics()
    assert t.items() == [
        ("forecheck_style", "balanced"),
        ("pp_style", "overload"),
        ("pk_aggression", "balanced"),
    ]


def test_to_dict_from_dict_round_trip():
    t = Tactics(forecheck_style="aggressive", pp_style="spread", pk_aggression="passive")
    d = t.to_dict()
    assert d == {"forecheck_style": "aggressive", "pp_style": "spread",
                "pk_aggression": "passive"}

    restored = Tactics.from_dict(d)
    assert restored == t


def test_from_dict_invalid_value_falls_back_to_default():
    restored = Tactics.from_dict({"forecheck_style": "not-a-real-option"})
    assert restored.forecheck_style == "balanced"


def test_from_dict_missing_key_falls_back_to_default():
    restored = Tactics.from_dict({})
    assert restored.forecheck_style == "balanced"
