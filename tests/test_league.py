"""Tests for pucksim.models.league -- Step 1.8 done-criteria."""
from __future__ import annotations

import pytest

from pucksim.config import STANDINGS_RULES
from pucksim.models.league import Game, Phase, conference_standings, points_for_game, standings
from pucksim.models.team import Team


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_team(tid: int, conference: str = "Eastern") -> Team:
    return Team(tid=tid, name=f"Team {tid}", abbrev=f"T{tid}", conference=conference)


def reg_win_game(gid: int, home: int, away: int, day: int = 1) -> Game:
    return Game(gid=gid, day=day, home=home, away=away, home_score=4, away_score=2, played=True)


def ot_win_game(gid: int, home: int, away: int, day: int = 1) -> Game:
    return Game(
        gid=gid, day=day, home=home, away=away, home_score=3, away_score=2,
        played=True, went_ot=True,
    )


def so_win_game(gid: int, home: int, away: int, day: int = 1) -> Game:
    return Game(
        gid=gid, day=day, home=home, away=away, home_score=3, away_score=2,
        played=True, went_ot=True, went_so=True,
    )


def tie_game(gid: int, home: int, away: int, day: int = 1) -> Game:
    return Game(gid=gid, day=day, home=home, away=away, home_score=2, away_score=2, played=True)


# ---------------------------------------------------------------------------
# Phase
# ---------------------------------------------------------------------------
def test_phase_order_contains_all_six_phases():
    expected = {
        "preseason", "regular_season", "playoffs", "draft", "free_agency", "offseason",
    }
    assert set(Phase.ORDER) == expected
    assert len(Phase.ORDER) == 6
    # Order matters: preseason first, regular_season before playoffs, etc.
    assert Phase.ORDER == [
        "preseason", "regular_season", "playoffs", "draft", "free_agency", "offseason",
    ]


def test_phase_labels_has_entry_for_each_phase():
    for phase in Phase.ORDER:
        assert phase in Phase.LABELS
        assert isinstance(Phase.LABELS[phase], str)
        assert Phase.LABELS[phase]


def test_phase_next_advances_and_wraps():
    for i in range(len(Phase.ORDER) - 1):
        assert Phase.next(Phase.ORDER[i]) == Phase.ORDER[i + 1]
    # Wraps from the last phase back to the first.
    assert Phase.next(Phase.ORDER[-1]) == Phase.ORDER[0]


# ---------------------------------------------------------------------------
# Game: winner/loser/is_tie/involves/opponent_of
# ---------------------------------------------------------------------------
def test_game_winner_loser_regulation():
    g = reg_win_game(1, home=10, away=20)
    assert g.winner == 10
    assert g.loser == 20
    assert not g.is_tie


def test_game_winner_loser_away_win():
    g = Game(gid=2, day=1, home=10, away=20, home_score=1, away_score=5, played=True)
    assert g.winner == 20
    assert g.loser == 10


def test_game_unplayed_has_no_winner_loser():
    g = Game(gid=3, day=1, home=10, away=20)
    assert g.winner is None
    assert g.loser is None
    assert not g.is_tie


def test_game_is_tie_only_when_level_and_no_ot_so():
    g = tie_game(4, home=10, away=20)
    assert g.is_tie
    assert g.winner is None
    assert g.loser is None


def test_game_not_a_tie_if_went_ot_even_if_scores_equal_by_construction_error():
    # Scores equal but went_ot=True shouldn't happen in practice (OT implies a
    # decisive extra goal), but is_tie must respect the flags, not just scores.
    g = Game(gid=5, day=1, home=10, away=20, home_score=2, away_score=2, played=True, went_ot=True)
    assert not g.is_tie


def test_game_involves_and_opponent_of():
    g = reg_win_game(6, home=10, away=20)
    assert g.involves(10)
    assert g.involves(20)
    assert not g.involves(30)
    assert g.opponent_of(10) == 20
    assert g.opponent_of(20) == 10


# ---------------------------------------------------------------------------
# Game: to_dict/from_dict round-trip
# ---------------------------------------------------------------------------
def test_game_round_trip_basic():
    g = reg_win_game(7, home=1, away=2)
    d = g.to_dict()
    g2 = Game.from_dict(d)
    assert g2 == g


def test_game_round_trip_with_ot_and_so_flags():
    g = so_win_game(8, home=1, away=2)
    d = g.to_dict()
    assert d["went_ot"] is True
    assert d["went_so"] is True
    g2 = Game.from_dict(d)
    assert g2.went_ot is True
    assert g2.went_so is True
    assert g2 == g


def test_game_round_trip_defaults_when_keys_missing():
    d = {"gid": 9, "day": 1, "home": 1, "away": 2}
    g = Game.from_dict(d)
    assert g.went_ot is False
    assert g.went_so is False
    assert g.played is False
    assert g.is_playoff is False
    assert g.series_id is None


# ---------------------------------------------------------------------------
# points_for_game -- for each rule, every outcome type
# ---------------------------------------------------------------------------
ALL_RULES = ["standard", "retro", "three_two_one_zero"]


@pytest.mark.parametrize("rule", ALL_RULES)
def test_points_for_game_regulation_win_loss(rule):
    table = STANDINGS_RULES[rule]
    g = reg_win_game(100, home=1, away=2)
    assert points_for_game(rule, 1, g) == table["reg_win"]
    assert points_for_game(rule, 2, g) == table["reg_loss"]
    # A win always outscores a loss.
    assert table["reg_win"] > table["reg_loss"]


@pytest.mark.parametrize("rule", ALL_RULES)
def test_points_for_game_ot_win_loss(rule):
    table = STANDINGS_RULES[rule]
    g = ot_win_game(101, home=1, away=2)
    assert points_for_game(rule, 1, g) == table["ot_win"]
    assert points_for_game(rule, 2, g) == table["ot_loss"]
    assert table["ot_win"] > table["ot_loss"]


@pytest.mark.parametrize("rule", ["standard", "three_two_one_zero"])
def test_points_for_game_so_win_loss(rule):
    # Retro has no shootout -- tested separately below as a rejection case.
    table = STANDINGS_RULES[rule]
    g = so_win_game(102, home=1, away=2)
    assert points_for_game(rule, 1, g) == table["so_win"]
    assert points_for_game(rule, 2, g) == table["so_loss"]
    assert table["so_win"] > table["so_loss"]


def test_points_for_game_tie_retro_only():
    table = STANDINGS_RULES["retro"]
    g = tie_game(103, home=1, away=2)
    assert points_for_game("retro", 1, g) == table["tie"]
    assert points_for_game("retro", 2, g) == table["tie"]
    # A tie is worth less than a win, more than a loss.
    assert table["reg_win"] > table["tie"] > table["reg_loss"]


@pytest.mark.parametrize("rule", ALL_RULES)
def test_points_for_game_reg_win_beats_ot_win_or_equal(rule):
    # Regulation win should never be worth LESS than an OT/SO win under any
    # preset (3-2-1-0 makes it strictly more; standard/retro make it equal).
    table = STANDINGS_RULES[rule]
    assert table["reg_win"] >= table["ot_win"]


def test_points_for_game_shootout_flag_rejected_under_retro():
    """Retro has has_shootout=False -- a went_so=True game must be rejected here."""
    g = so_win_game(104, home=1, away=2)
    with pytest.raises(ValueError):
        points_for_game("retro", 1, g)
    with pytest.raises(ValueError):
        points_for_game("retro", 2, g)


def test_points_for_game_unplayed_raises():
    g = Game(gid=105, day=1, home=1, away=2)
    with pytest.raises(ValueError):
        points_for_game("standard", 1, g)


def test_points_for_game_team_not_in_game_raises():
    g = reg_win_game(106, home=1, away=2)
    with pytest.raises(ValueError):
        points_for_game("standard", 99, g)


# ---------------------------------------------------------------------------
# standings() sorting: points -> wins -> goal diff -> team id
# ---------------------------------------------------------------------------
def test_standings_sorts_by_points_desc_standard_rule():
    t1 = make_team(1)
    t2 = make_team(2)
    t3 = make_team(3)
    games = [
        # Team 1: reg win (2 pts), team 2: reg loss (0 pts)
        reg_win_game(1, home=1, away=2, day=1),
        # Team 3: ot loss (1 pt) vs team 2 win... let's make team3 a clear middle.
        Game(gid=2, day=2, home=3, away=2, home_score=2, away_score=3, played=True, went_ot=True),
    ]
    # Team1: 2 pts (reg win). Team2: 0 (reg loss) + 2 (ot win) = 2 pts.
    # Team3: 1 pt (ot loss).
    ordered = standings([t1, t2, t3], games, "standard")
    ids = [t.tid for t in ordered]
    # team1 and team2 tie on points (2 each); team3 last with 1 point.
    assert ids[2] == 3
    assert set(ids[:2]) == {1, 2}


def test_standings_goal_diff_tiebreak_after_equal_points_and_wins():
    t1 = make_team(1)
    t2 = make_team(2)
    # Both teams get exactly one regulation win (2 pts, 1 win each) against a
    # third team, but with different goal differentials.
    t3 = make_team(3)
    games = [
        Game(gid=1, day=1, home=1, away=3, home_score=6, away_score=1, played=True),  # t1 GD +5
        Game(gid=2, day=1, home=2, away=3, home_score=3, away_score=2, played=True),  # t2 GD +1
        # t3 needs no extra games; it will simply have fewer points.
    ]
    ordered = standings([t1, t2, t3], games, "standard")
    ids = [t.tid for t in ordered]
    # t1 (2 pts, +5 GD) should rank above t2 (2 pts, +1 GD); t3 last (0 pts).
    assert ids == [1, 2, 3]


def test_standings_team_id_final_tiebreak():
    t2 = make_team(2)
    t1 = make_team(1)
    # No games played at all -- everyone ties on points/wins/GD (all zero).
    ordered = standings([t2, t1], [], "standard")
    assert [t.tid for t in ordered] == [1, 2]


def test_standings_retro_rule_ties_affect_points():
    t1 = make_team(1)
    t2 = make_team(2)
    t3 = make_team(3)
    games = [
        tie_game(1, home=1, away=2, day=1),  # both get 1 pt (retro tie)
        reg_win_game(2, home=3, away=1, day=2),  # t3 gets 2 pts, t1 gets 0
    ]
    # t1: 1 (tie) + 0 (loss) = 1 pt
    # t2: 1 (tie) = 1 pt
    # t3: 2 (win) = 2 pts
    ordered = standings([t1, t2, t3], games, "retro")
    assert ordered[0].tid == 3
    # t1 and t2 tie at 1 point each with 0 wins each; goal diff decides.
    # t1: GD = (2-2) + (1-3) = -2 ; t2: GD = (2-2) = 0 -> t2 ranks above t1.
    assert [t.tid for t in ordered[1:]] == [2, 1]


def test_standings_three_two_one_zero_rule_rewards_regulation_wins():
    t1 = make_team(1)
    t2 = make_team(2)
    games = [
        reg_win_game(1, home=1, away=2, day=1),  # t1: 3 pts (reg win), t2: 0
    ]
    ordered = standings([t1, t2], games, "three_two_one_zero")
    assert ordered[0].tid == 1
    assert ordered[1].tid == 2


def test_standings_ignores_unplayed_games():
    t1 = make_team(1)
    t2 = make_team(2)
    games = [
        Game(gid=1, day=1, home=1, away=2, home_score=5, away_score=0, played=False),
    ]
    ordered = standings([t1, t2], games, "standard")
    # No played games -> tie on everything -> tid tiebreak.
    assert [t.tid for t in ordered] == [1, 2]


# ---------------------------------------------------------------------------
# conference_standings
# ---------------------------------------------------------------------------
def test_conference_standings_groups_by_conference():
    t1 = make_team(1, conference="Eastern")
    t2 = make_team(2, conference="Western")
    t3 = make_team(3, conference="Eastern")
    games = [
        reg_win_game(1, home=1, away=3, day=1),
    ]
    grouped = conference_standings([t1, t2, t3], games, "standard")
    assert set(grouped.keys()) == {"Eastern", "Western"}
    assert [t.tid for t in grouped["Eastern"]] == [1, 3]
    assert [t.tid for t in grouped["Western"]] == [2]
