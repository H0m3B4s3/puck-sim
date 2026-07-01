"""Tests for pucksim.models.stats: SkaterStatLine and GoalieStatLine."""
from pucksim.models.stats import GoalieStatLine, SkaterStatLine


# -- SkaterStatLine -----------------------------------------------------------

def test_skater_points_derived():
    line = SkaterStatLine(g=10, a=15)
    assert line.points == 25


def test_skater_fo_pct():
    line = SkaterStatLine(fo_won=9, fo_lost=3)
    assert line.fo_pct == 0.75


def test_skater_fo_pct_zero_division_guard():
    line = SkaterStatLine(fo_won=0, fo_lost=0)
    assert line.fo_pct == 0.0


def test_skater_default_counters_are_zero():
    line = SkaterStatLine()
    assert line.gp == 0
    assert line.points == 0
    assert line.corsi_for == 0
    assert line.corsi_against == 0
    assert line.fenwick_for == 0
    assert line.fenwick_against == 0


def test_skater_plus_minus_is_plain_counter():
    line = SkaterStatLine(plus_minus=-3)
    assert line.plus_minus == -3


def test_skater_to_dict_from_dict_round_trip():
    line = SkaterStatLine(
        gp=1, gs=1, secs=1200, g=2, a=3, sog=6, pim=2,
        hits=4, blocks=1, giveaways=1, takeaways=2,
        fo_won=8, fo_lost=4, plus_minus=1,
        corsi_for=20, corsi_against=15, fenwick_for=17, fenwick_against=12,
    )
    d = line.to_dict()
    restored = SkaterStatLine.from_dict(d)
    assert restored == line
    assert restored.points == 5
    assert restored.fo_pct == d["fo_won"] / (d["fo_won"] + d["fo_lost"])


def test_skater_from_dict_ignores_unknown_keys():
    d = SkaterStatLine(g=1).to_dict()
    d["not_a_real_field"] = 999
    restored = SkaterStatLine.from_dict(d)
    assert restored.g == 1
    assert not hasattr(restored, "not_a_real_field")


def test_skater_add_accumulates_counters():
    game1 = SkaterStatLine(gp=1, g=1, a=2, sog=4, fo_won=5, fo_lost=3, corsi_for=10)
    game2 = SkaterStatLine(gp=1, g=2, a=0, sog=3, fo_won=2, fo_lost=6, corsi_for=8)
    season = SkaterStatLine()
    season.add(game1)
    season.add(game2)
    assert season.gp == 2
    assert season.g == 3
    assert season.a == 2
    assert season.sog == 7
    assert season.fo_won == 7
    assert season.fo_lost == 9
    assert season.corsi_for == 18
    assert season.points == 5


def test_skater_reset_zeroes_all_counters():
    line = SkaterStatLine(gp=5, g=10, a=8, corsi_for=50, plus_minus=7)
    line.reset()
    for value in line.to_dict().values():
        assert value == 0


# -- GoalieStatLine -------------------------------------------------------------

def test_goalie_save_pct():
    line = GoalieStatLine(shots_faced=32, saves=30)
    assert line.save_pct == 0.9375


def test_goalie_save_pct_zero_division_guard():
    line = GoalieStatLine(shots_faced=0, saves=0)
    assert line.save_pct == 0.0


def test_goalie_gaa():
    # 3 goals against over one full 60-minute game (3600 seconds) -> GAA 3.0
    line = GoalieStatLine(goals_against=3, secs=3600)
    assert line.gaa == 3.0


def test_goalie_gaa_zero_division_guard():
    line = GoalieStatLine(goals_against=0, secs=0)
    assert line.gaa == 0.0


def test_goalie_shutouts_is_plain_counter():
    line = GoalieStatLine(goals_against=0, shutouts=1)
    assert line.shutouts == 1


def test_goalie_to_dict_from_dict_round_trip():
    line = GoalieStatLine(
        gp=1, gs=1, secs=3600, shots_faced=28, saves=27,
        goals_against=1, wins=1, losses=0, otl=0, shutouts=0,
    )
    d = line.to_dict()
    restored = GoalieStatLine.from_dict(d)
    assert restored == line
    assert restored.save_pct == d["saves"] / d["shots_faced"]


def test_goalie_from_dict_ignores_unknown_keys():
    d = GoalieStatLine(saves=10).to_dict()
    d["some_future_field"] = 42
    restored = GoalieStatLine.from_dict(d)
    assert restored.saves == 10
    assert not hasattr(restored, "some_future_field")


def test_goalie_add_accumulates_counters():
    game1 = GoalieStatLine(gp=1, gs=1, secs=3600, shots_faced=30, saves=28, goals_against=2, wins=1)
    game2 = GoalieStatLine(gp=1, gs=1, secs=3600, shots_faced=25, saves=25, goals_against=0, wins=1, shutouts=1)
    season = GoalieStatLine()
    season.add(game1)
    season.add(game2)
    assert season.gp == 2
    assert season.shots_faced == 55
    assert season.saves == 53
    assert season.goals_against == 2
    assert season.wins == 2
    assert season.shutouts == 1
    assert round(season.save_pct, 4) == round(53 / 55, 4)


def test_goalie_reset_zeroes_all_counters():
    line = GoalieStatLine(gp=10, shots_faced=300, saves=280, wins=6, shutouts=2)
    line.reset()
    for value in line.to_dict().values():
        assert value == 0
