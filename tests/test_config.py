"""Tests for pucksim.config — standings rule presets and rating bounds."""
from pucksim import config


def test_all_three_standings_presets_exist():
    assert set(config.STANDINGS_RULES.keys()) == {
        "standard",
        "retro",
        "three_two_one_zero",
    }


def test_default_standings_rule_is_valid_key():
    assert config.DEFAULT_STANDINGS_RULE in config.STANDINGS_RULES
    assert config.DEFAULT_STANDINGS_RULE == "standard"


def test_standard_rule_point_values():
    rule = config.STANDINGS_RULES["standard"]
    assert rule["reg_win"] == 2
    assert rule["ot_win"] == 2
    assert rule["so_win"] == 2
    assert rule["ot_loss"] == 1
    assert rule["so_loss"] == 1
    assert rule["reg_loss"] == 0
    assert rule["has_shootout"] is True
    # A win always outscores an OT/SO loss, which always outscores a regulation loss.
    assert rule["reg_win"] > rule["ot_loss"] > rule["reg_loss"]
    assert rule["ot_win"] > rule["ot_loss"]


def test_retro_rule_point_values_and_no_shootout():
    rule = config.STANDINGS_RULES["retro"]
    assert rule["reg_win"] == 2
    assert rule["ot_win"] == 2
    assert rule["ot_loss"] == 1
    assert rule["reg_loss"] == 0
    assert rule["tie"] == 1
    assert rule["has_shootout"] is False
    # Shootout outcomes are unreachable under retro rules.
    assert rule["so_win"] is None
    assert rule["so_loss"] is None
    # A win outscores a tie, which outscores a loss.
    assert rule["reg_win"] > rule["tie"] > rule["reg_loss"]


def test_three_two_one_zero_rule_point_values():
    rule = config.STANDINGS_RULES["three_two_one_zero"]
    assert rule["reg_win"] == 3
    assert rule["ot_win"] == 2
    assert rule["so_win"] == 2
    assert rule["ot_loss"] == 1
    assert rule["so_loss"] == 1
    assert rule["reg_loss"] == 0
    assert rule["has_shootout"] is True
    # The whole point of this scheme: regulation wins are worth strictly more
    # than wins that required extra time.
    assert rule["reg_win"] > rule["ot_win"]
    assert rule["ot_win"] > rule["ot_loss"] > rule["reg_loss"]


def test_standings_rules_internally_consistent_across_presets():
    # Regardless of rule, a regulation win should never be worth less than an
    # OT/SO win, and any win should never be worth less than any loss/tie.
    for name, rule in config.STANDINGS_RULES.items():
        non_none_losses = [
            v for k, v in rule.items()
            if k in ("ot_loss", "so_loss", "reg_loss", "tie") and v is not None
        ]
        non_none_wins = [
            v for k, v in rule.items()
            if k in ("reg_win", "ot_win", "so_win") and v is not None
        ]
        assert min(non_none_wins) >= max(non_none_losses), name
        assert rule["reg_win"] >= rule["ot_win"], name


def test_rating_bounds():
    assert config.RATING_MIN == 25
    assert config.RATING_MAX == 99
    assert config.RATING_MIN < config.RATING_MAX
