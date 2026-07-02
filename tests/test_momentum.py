"""Tests for pucksim.systems.momentum -- DEVPLAN.md Step 2.7 done-criteria (mirrors HoopR's own
test_momentum.py shape: game_score/update_morale/offseason_reset).

Covers:
  - game_score() sane ordering (a great game scores higher than a poor one).
  - update_morale(): winning nudges morale up, losing nudges it down, an injured player drifts
    toward baseline regardless of the result, a healthy scratch (near-zero ice time) sours.
  - Mean reversion keeps morale bounded across many consecutive games (no runaway drift).
  - offseason_reset(): chemistry decays toward cold (capped-then-retained), morale drifts most
    of the way back toward each player's personal baseline.
  - Explicit no-upweighting audit (per this step's constraints): this module never computes or
    applies an in-game realization multiplier itself -- it only ever writes the raw morale int
    that sim/ratings.py's already-capped morale_realization() reads downstream.
"""
from __future__ import annotations

from pucksim.models import attributes as attr
from pucksim.models.player import Player
from pucksim.models.stats import SkaterStatLine
from pucksim.models.team import Team
from pucksim.sim.boxscore import GameResult
from pucksim.systems import momentum as M


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_skater(pid: int, work_ethic: int = 70, morale: int = 70, injury=None) -> Player:
    ratings = {name: 70 for name in attr.ALL_RATINGS}
    ratings["work_ethic"] = work_ethic
    return Player(pid=pid, name=f"Skater {pid}", age=27, position="C", ratings=ratings,
                  morale=morale, injury=injury, team_id=1)


def make_team(tid: int, roster) -> Team:
    t = Team(tid=tid, name=f"Team {tid}", abbrev=f"T{tid}", conference="Eastern")
    for p in roster:
        t.roster.append(p.pid)
    return t


class _FakeWorld:
    """Minimal stand-in exposing just what update_morale/offseason_reset touch."""
    def __init__(self, players, teams):
        self.players = {p.pid: p for p in players}
        self.teams = {t.tid: t for t in teams}


# ---------------------------------------------------------------------------
# game_score
# ---------------------------------------------------------------------------
def test_game_score_rewards_goals_and_assists_over_a_quiet_game():
    great = SkaterStatLine(g=3, a=2, sog=8, hits=2, blocks=1, takeaways=1)
    quiet = SkaterStatLine(g=0, a=0, sog=1, hits=1, blocks=0, takeaways=0)
    assert M.game_score(great) > M.game_score(quiet)


def test_game_score_penalizes_giveaways_and_penalty_minutes():
    clean = SkaterStatLine(g=1, a=1, giveaways=0, pim=0)
    sloppy = SkaterStatLine(g=1, a=1, giveaways=5, pim=10)
    assert M.game_score(clean) > M.game_score(sloppy)


# ---------------------------------------------------------------------------
# update_morale
# ---------------------------------------------------------------------------
def test_winning_nudges_morale_up_losing_nudges_it_down():
    winner = make_skater(1, morale=70)
    loser = make_skater(2, morale=70)
    home = make_team(1, [winner])
    away = make_team(2, [loser])
    world = _FakeWorld([winner, loser], [home, away])

    result = GameResult(home_tid=1, away_tid=2, home_score=4, away_score=1)
    result.skater_box[1] = SkaterStatLine(secs=15 * 60, g=1, a=1)
    result.skater_box[2] = SkaterStatLine(secs=15 * 60, g=0, a=0)

    M.update_morale(world, home, away, result)
    assert winner.morale > 70
    assert loser.morale < 70


def test_tie_game_produces_no_result_signal_either_direction():
    p1 = make_skater(1, morale=70)
    p2 = make_skater(2, morale=70)
    home = make_team(1, [p1])
    away = make_team(2, [p2])
    world = _FakeWorld([p1, p2], [home, away])

    result = GameResult(home_tid=1, away_tid=2, home_score=2, away_score=2)
    result.skater_box[1] = SkaterStatLine(secs=15 * 60)
    result.skater_box[2] = SkaterStatLine(secs=15 * 60)

    M.update_morale(world, home, away, result)
    # Both should land close to baseline (no win/loss signal); only mean-reversion applies.
    assert 68 <= p1.morale <= 72
    assert 68 <= p2.morale <= 72


def test_injured_player_drifts_toward_baseline_regardless_of_result():
    from pucksim.models.player import Injury
    hurt = make_skater(1, morale=90, injury=Injury("knee", 5))
    healthy_opp = make_skater(2, morale=70)
    home = make_team(1, [hurt])
    away = make_team(2, [healthy_opp])
    world = _FakeWorld([hurt, healthy_opp], [home, away])

    result = GameResult(home_tid=1, away_tid=2, home_score=5, away_score=1)  # hurt's team wins big
    result.skater_box[2] = SkaterStatLine(secs=15 * 60)

    M.update_morale(world, home, away, result)
    # An injured player can't have played this game -- morale should move TOWARD baseline (70),
    # not spike up from the big win his team had without him.
    assert hurt.morale < 90


def test_healthy_scratch_sours_relative_to_a_regular_on_the_same_winning_team():
    """Isolates the role-penalty term from the shared result-signal term: same team, same win,
    same margin -- the only difference is ice time -- so any morale gap between the two must
    come from the role (garbage-time) penalty, not the (identical) win signal."""
    scratch = make_skater(1, morale=70)
    starter = make_skater(2, morale=70)
    home = make_team(1, [scratch, starter])
    away = make_team(2, [make_skater(3, morale=70)])
    world = _FakeWorld([scratch, starter, make_skater(3)], [home, away])

    result = GameResult(home_tid=1, away_tid=2, home_score=2, away_score=1)
    # Starter gets a game-in-line-with-expectation for a 70-overall/18-minute night (roughly at
    # _expected_game_score, so the performance term nets close to zero) -- isolates the role
    # axis from the performance axis, which a scoreless "regular" would otherwise conflate.
    result.skater_box[2] = SkaterStatLine(secs=18 * 60, g=1, a=0, sog=3)
    # scratch has no box-score entry at all (didn't play) -- secs defaults to 0 -> role penalty.

    M.update_morale(world, home, away, result)
    # Both are on the winning team with an identical result signal; the scratch's role penalty
    # must leave him strictly lower than the regular who actually played meaningful minutes.
    assert scratch.morale < starter.morale


def test_morale_never_leaves_the_legal_band_over_many_lopsided_games():
    p = make_skater(1, morale=70)
    opp = make_skater(2, morale=70)
    home = make_team(1, [p])
    away = make_team(2, [opp])
    world = _FakeWorld([p, opp], [home, away])

    for _ in range(200):
        result = GameResult(home_tid=1, away_tid=2, home_score=8, away_score=0)
        result.skater_box[1] = SkaterStatLine(secs=20 * 60, g=3, a=2)
        M.update_morale(world, home, away, result)
        assert M.MORALE_MIN <= p.morale <= M.MORALE_MAX


def test_mean_reversion_stabilizes_morale_rather_than_accumulating_forever():
    """A long win streak should push morale up but it must converge/stabilize (mean-reversion),
    not diverge unbounded even before hitting the hard MORALE_MAX clamp."""
    p = make_skater(1, morale=70)
    opp = make_skater(2, morale=70)
    home = make_team(1, [p])
    away = make_team(2, [opp])
    world = _FakeWorld([p, opp], [home, away])

    values = []
    for _ in range(60):
        result = GameResult(home_tid=1, away_tid=2, home_score=5, away_score=1)
        result.skater_box[1] = SkaterStatLine(secs=18 * 60, g=2, a=1)
        M.update_morale(world, home, away, result)
        values.append(p.morale)
    # Should stabilize: the last 10 values shouldn't still be climbing by more than a couple
    # points (proving mean-reversion, not runaway accumulation).
    assert max(values[-10:]) - min(values[-10:]) <= 3


# ---------------------------------------------------------------------------
# offseason_reset
# ---------------------------------------------------------------------------
def test_offseason_reset_decays_chemistry_toward_cold():
    p1, p2 = make_skater(1), make_skater(2)
    team = make_team(1, [p1, p2])
    from pucksim.models.team import pair_key
    team.chemistry[pair_key(1, 2)] = 40_000.0
    world = _FakeWorld([p1, p2], [team])

    M.offseason_reset(world)
    assert team.chemistry[pair_key(1, 2)] == 40_000.0 * M.CHEM_RETENTION


def test_offseason_reset_caps_banked_chemistry_before_retention():
    p1, p2 = make_skater(1), make_skater(2)
    team = make_team(1, [p1, p2])
    from pucksim.models.team import pair_key
    team.chemistry[pair_key(1, 2)] = 999_999.0   # way above CHEM_CARRY_CAP
    world = _FakeWorld([p1, p2], [team])

    M.offseason_reset(world)
    assert team.chemistry[pair_key(1, 2)] == M.CHEM_CARRY_CAP * M.CHEM_RETENTION


def test_offseason_reset_drifts_morale_toward_personal_baseline():
    hot = make_skater(1, work_ethic=70, morale=95)
    cold = make_skater(2, work_ethic=70, morale=30)
    team = make_team(1, [hot, cold])
    world = _FakeWorld([hot, cold], [team])

    M.offseason_reset(world)
    # Both should have moved most of the way back toward 70 (MORALE_OFFSEASON_REVERT fraction).
    assert 95 > hot.morale > 70
    assert 30 < cold.morale < 70


# ---------------------------------------------------------------------------
# No-upweighting audit (explicit, per this step's constraints)
# ---------------------------------------------------------------------------
def test_momentum_module_never_imports_sim_ratings():
    """This module must only ever produce the raw Player.morale int -- never a capped-at-1.0-
    or-otherwise realization multiplier itself (that enforcement lives entirely in
    sim/ratings.py). A real-AST audit (not a docstring text search, which would false-positive
    on this module's own explanatory prose about sim/ratings.py): momentum.py's actual import
    statements must never name sim.ratings, proving there's no duplicated/bypassed enforcement
    path actually wired into this module's code."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(M))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    assert not any("ratings" in name for name in imported_modules)
