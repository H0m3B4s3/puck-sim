"""Tests for pucksim.models.team -- Step 1.7 done-criteria."""
from __future__ import annotations

from pucksim.models import attributes as attr
from pucksim.models.contract import flat_contract
from pucksim.models.player import Player
from pucksim.models.team import (
    Team,
    auto_build_lines,
    d_pair_fit_bonus,
    lineup_familiarity_secs,
    pair_key,
    position_fit_score,
    roster_players,
    rotation_pool,
    seed_chemistry,
    team_salary,
)
from pucksim.rng import Rng


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _skater_ratings(value: int = 70) -> dict:
    return {name: value for name in attr.ALL_RATINGS}


def _goalie_ratings(value: int = 70) -> dict:
    return {name: value for name in attr.ALL_GOALIE_RATINGS}


def make_skater(pid: int, position: str, shoots: str = "L", overall: int = 70, **overrides) -> Player:
    kwargs = dict(
        pid=pid,
        name=f"Skater {pid}",
        age=25,
        position=position,
        shoots=shoots,
        ratings=_skater_ratings(overall),
    )
    kwargs.update(overrides)
    return Player(**kwargs)


def make_goalie(pid: int, overall: int = 70, **overrides) -> Player:
    kwargs = dict(
        pid=pid,
        name=f"Goalie {pid}",
        age=27,
        position="G",
        ratings=_goalie_ratings(overall),
    )
    kwargs.update(overrides)
    return Player(**kwargs)


def make_team(**overrides) -> Team:
    kwargs = dict(
        tid=1,
        name="Testers",
        abbrev="TST",
        conference="Eastern",
        division="Atlantic",
    )
    kwargs.update(overrides)
    return Team(**kwargs)


def build_full_roster():
    """12 forwards (4 LW/4 C/4 RW, varied shoots), 6 D (varied shoots), 2 goalies."""
    players: dict = {}
    pid = 1
    for pos in ("LW", "C", "RW"):
        for i in range(4):
            shoots = "L" if i % 2 == 0 else "R"
            p = make_skater(pid, pos, shoots=shoots, overall=65 + i)
            players[pid] = p
            pid += 1
    for i in range(6):
        shoots = "L" if i % 2 == 0 else "R"
        p = make_skater(pid, "D", shoots=shoots, overall=65 + i)
        players[pid] = p
        pid += 1
    g1 = make_goalie(pid, overall=80)
    players[pid] = g1
    goalie_hi_pid = pid
    pid += 1
    g2 = make_goalie(pid, overall=70)
    players[pid] = g2
    goalie_lo_pid = pid

    team = make_team(roster=list(players.keys()))
    return team, players, goalie_hi_pid, goalie_lo_pid


# ---------------------------------------------------------------------------
# auto_build_lines
# ---------------------------------------------------------------------------
def test_auto_build_lines_produces_complete_lines_and_pairs():
    team, players, goalie_hi_pid, goalie_lo_pid = build_full_roster()
    auto_build_lines(team, players)

    assert len(team.lines) == 4
    for line in team.lines:
        assert len(line) == 3

    assert len(team.pairs) == 3
    for pair in team.pairs:
        assert len(pair) == 2

    assert team.goalie_starter == goalie_hi_pid
    assert team.goalie_backup == goalie_lo_pid


def test_auto_build_lines_uses_all_forwards_and_d_exactly_once():
    team, players, _, _ = build_full_roster()
    auto_build_lines(team, players)

    line_ids = [pid for line in team.lines for pid in line]
    assert len(line_ids) == len(set(line_ids)) == 12

    pair_ids = [pid for pair in team.pairs for pid in pair]
    assert len(pair_ids) == len(set(pair_ids)) == 6


# ---------------------------------------------------------------------------
# Plain-list flexibility (DESIGN.md point 1)
# ---------------------------------------------------------------------------
def test_lines_and_pairs_are_plain_lists_splice_no_error():
    team, players, _, _ = build_full_roster()
    auto_build_lines(team, players)

    extra_id = 9999
    # Splicing an arbitrary extra id into a line's underlying list must not
    # raise -- proves lines/pairs are plain List[List[int]], not a Line/Pair
    # class with a fixed schema.
    team.lines[0].append(extra_id)
    assert extra_id in team.lines[0]
    assert len(team.lines[0]) == 4
    assert isinstance(team.lines[0], list)
    assert isinstance(team.lines, list)

    team.pairs[0].append(extra_id)
    assert extra_id in team.pairs[0]
    assert isinstance(team.pairs[0], list)


def test_current_forward_line_and_d_pair_accessors():
    team, players, _, _ = build_full_roster()
    auto_build_lines(team, players)

    line0 = team.current_forward_line(0)
    assert line0 == team.lines[0]
    assert isinstance(line0, list)

    pair0 = team.current_d_pair(0)
    assert pair0 == team.pairs[0]
    assert isinstance(pair0, list)

    # Out-of-range index returns an empty list rather than raising.
    assert team.current_forward_line(99) == []
    assert team.current_d_pair(99) == []


# ---------------------------------------------------------------------------
# position_fit_score
# ---------------------------------------------------------------------------
def test_on_position_scores_higher_than_off_position():
    winger = make_skater(1, "RW", shoots="R", overall=75)
    on_position = position_fit_score(winger, "RW")
    off_position = position_fit_score(winger, "LW")
    assert on_position > off_position


def test_wing_to_center_penalty_strictly_larger_than_others():
    # Use a center-neutral (no handedness penalty at C) comparison: same
    # player's penalty magnitude at each off-position slot.
    rw = make_skater(1, "RW", shoots="R", overall=75)
    center = make_skater(2, "C", shoots="R", overall=75)

    wing_to_wing_penalty = rw.overall - position_fit_score(rw, "LW")
    center_to_wing_penalty = center.overall - position_fit_score(center, "RW")
    wing_to_center_penalty = rw.overall - position_fit_score(rw, "C")

    assert wing_to_center_penalty > wing_to_wing_penalty
    assert wing_to_center_penalty > center_to_wing_penalty


def test_handedness_penalty_applies_to_off_side_wing_only():
    left_shot = make_skater(1, "LW", shoots="L", overall=70)
    right_shot = make_skater(2, "LW", shoots="R", overall=70)

    # Both are natural LW by position, but right_shot is off-hand for LW.
    assert position_fit_score(left_shot, "LW") > position_fit_score(right_shot, "LW")

    # Center assignment: no handedness penalty regardless of shoots.
    left_shot_c = make_skater(3, "C", shoots="L", overall=70)
    right_shot_c = make_skater(4, "C", shoots="R", overall=70)
    assert position_fit_score(left_shot_c, "C") == position_fit_score(right_shot_c, "C")


# ---------------------------------------------------------------------------
# D-pair handedness
# ---------------------------------------------------------------------------
def test_d_pair_fit_bonus_favors_opposite_handed():
    left1 = make_skater(1, "D", shoots="L", overall=70)
    left2 = make_skater(2, "D", shoots="L", overall=70)
    right1 = make_skater(3, "D", shoots="R", overall=70)

    same_handed_bonus = d_pair_fit_bonus(left1, left2)
    opposite_handed_bonus = d_pair_fit_bonus(left1, right1)

    assert opposite_handed_bonus > same_handed_bonus
    assert opposite_handed_bonus == 0
    assert same_handed_bonus < 0


def test_auto_build_lines_prefers_opposite_handed_d_pair():
    # Two L-shot D and one R-shot D, all equal overall -- the pair-builder
    # should pair the R-shot with one of the L-shots (opposite-handed) rather
    # than leaving the two L-shots paired together, since that combination
    # scores higher via d_pair_fit_bonus.
    left1 = make_skater(1, "D", shoots="L", overall=70)
    left2 = make_skater(2, "D", shoots="L", overall=70)
    right1 = make_skater(3, "D", shoots="R", overall=70)
    right2 = make_skater(4, "D", shoots="R", overall=70)

    players = {p.pid: p for p in (left1, left2, right1, right2)}
    team = make_team(roster=list(players.keys()))
    auto_build_lines(team, players)

    assert len(team.pairs) == 2
    for pair in team.pairs:
        shoots_in_pair = {players[pid].shoots for pid in pair}
        assert shoots_in_pair == {"L", "R"}


# ---------------------------------------------------------------------------
# pair_key / lineup_familiarity_secs / seed_chemistry
# ---------------------------------------------------------------------------
def test_pair_key_is_symmetric():
    assert pair_key(3, 7) == pair_key(7, 3)
    assert pair_key(3, 7) == "3,7"


def test_lineup_familiarity_secs_missing_pair_is_zero():
    team = make_team()
    assert lineup_familiarity_secs(team, 1, 2) == 0.0


def test_seed_chemistry_populates_all_roster_pairs():
    team = make_team(roster=[1, 2, 3])
    rng = Rng(seed=42)
    seed_chemistry(team, rng, base=100.0, spread=0.0)

    assert lineup_familiarity_secs(team, 1, 2) == 100.0
    assert lineup_familiarity_secs(team, 2, 1) == 100.0
    assert lineup_familiarity_secs(team, 1, 3) == 100.0
    assert lineup_familiarity_secs(team, 2, 3) == 100.0


def test_seed_chemistry_with_spread_is_deterministic_by_seed():
    team_a = make_team(roster=[1, 2, 3, 4])
    seed_chemistry(team_a, Rng(seed=99), base=10.0, spread=5.0)

    team_b = make_team(roster=[1, 2, 3, 4])
    seed_chemistry(team_b, Rng(seed=99), base=10.0, spread=5.0)

    assert team_a.chemistry == team_b.chemistry


# ---------------------------------------------------------------------------
# team_salary
# ---------------------------------------------------------------------------
def test_team_salary_sums_current_salaries():
    p1 = make_skater(1, "C", overall=75, contract=flat_contract(1_000_000, 2))
    p2 = make_skater(2, "LW", overall=70, contract=flat_contract(2_500_000, 3))
    g1 = make_goalie(3, overall=80, contract=flat_contract(4_000_000, 1))

    players = {1: p1, 2: p2, 3: g1}
    team = make_team(roster=[1, 2, 3])

    assert team_salary(team, players) == 1_000_000 + 2_500_000 + 4_000_000


def test_team_salary_ignores_ids_not_in_players_mapping():
    p1 = make_skater(1, "C", contract=flat_contract(500_000, 1))
    players = {1: p1}
    team = make_team(roster=[1, 999])
    assert team_salary(team, players) == 500_000


def test_roster_players_helper():
    p1 = make_skater(1, "C")
    p2 = make_skater(2, "LW")
    players = {1: p1, 2: p2}
    team = make_team(roster=[1, 2, 999])
    result = roster_players(team, players)
    assert result == [p1, p2]


# ---------------------------------------------------------------------------
# rotation_pool
# ---------------------------------------------------------------------------
def test_rotation_pool_excludes_active_players():
    team, players, goalie_hi_pid, goalie_lo_pid = build_full_roster()
    auto_build_lines(team, players)

    pool = rotation_pool(team, players)
    active_ids = set()
    for line in team.lines:
        active_ids.update(line)
    for pair in team.pairs:
        active_ids.update(pair)
    active_ids.add(goalie_hi_pid)
    active_ids.add(goalie_lo_pid)

    assert set(pool) == set(team.roster) - active_ids
    assert not (set(pool) & active_ids)


# ---------------------------------------------------------------------------
# to_dict() / from_dict() round trip
# ---------------------------------------------------------------------------
def test_team_round_trip():
    team, players, goalie_hi_pid, goalie_lo_pid = build_full_roster()
    auto_build_lines(team, players)
    seed_chemistry(team, Rng(seed=1), base=50.0)
    team.wins = 10
    team.losses = 5
    team.ot_losses = 2
    team.streak = -3

    d = team.to_dict()
    restored = Team.from_dict(d)

    assert restored.tid == team.tid
    assert restored.name == team.name
    assert restored.abbrev == team.abbrev
    assert restored.conference == team.conference
    assert restored.division == team.division
    assert restored.roster == team.roster
    assert restored.lines == team.lines
    assert restored.pairs == team.pairs
    assert restored.goalie_starter == goalie_hi_pid
    assert restored.goalie_backup == goalie_lo_pid
    assert restored.chemistry == {k: round(v, 1) for k, v in team.chemistry.items()}
    assert restored.wins == 10
    assert restored.losses == 5
    assert restored.ot_losses == 2
    assert restored.streak == -3

    # Lines/pairs remain plain lists after round-trip too.
    assert isinstance(restored.lines, list)
    assert isinstance(restored.lines[0], list)
    restored.lines[0].append(12345)
    assert 12345 in restored.lines[0]


def test_team_round_trip_with_none_tactics_and_coach():
    team = make_team()
    d = team.to_dict()
    assert d["tactics"] is None
    assert d["coach"] is None
    restored = Team.from_dict(d)
    assert restored.tactics is None
    assert restored.coach is None


# ---------------------------------------------------------------------------
# record_result / streak tracking
# ---------------------------------------------------------------------------
def test_record_result_win_streak():
    team = make_team()
    team.record_result("win")
    team.record_result("win")
    assert team.wins == 2
    assert team.streak == 2
    assert team.streak_str == "W2"


def test_record_result_loss_streak():
    team = make_team()
    team.record_result("loss")
    team.record_result("ot_loss")
    assert team.losses == 1
    assert team.ot_losses == 1
    assert team.streak == -2
    assert team.streak_str == "L2"


def test_reset_record():
    team = make_team()
    team.record_result("win")
    team.reset_record()
    assert team.wins == 0
    assert team.streak == 0
