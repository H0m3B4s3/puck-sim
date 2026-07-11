"""On-ice defender shot-quality suppression (SIM_SYNERGY_PLAN.md Phase 2).

Before this mechanic the five on-ice defenders barely affected a shot -- resolution pitted
shooter skill vs goalie skill, and the skaters mattered only via chemistry, the shot-blocker
pick, and hits. These tests pin the two halves: the ``def_value`` aggregate itself
(deterministic) and its downstream effect that a stronger defending group allows lower opponent
per-shot xG (statistical, generous margin).
"""
from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.models.player import Player
from pucksim.models.team import auto_build_lines
from pucksim.rng import Rng
from pucksim.sim import ratings as R
from pucksim.sim.engine import GameSim


def _skater(pid: int, da: int, checking: int = 60) -> Player:
    return Player(pid=pid, name=f"P{pid}", age=25, position="D",
                  ratings={"defensive_awareness": da, "checking": checking})


def test_defensive_value_formula():
    # 0.7 * defensive_awareness + 0.3 * checking, shot_blocking deliberately excluded.
    p = _skater(1, da=80, checking=50)
    assert R.defensive_value(p) == 0.7 * 80 + 0.3 * 50


def test_cache_def_value_is_group_mean():
    players = [_skater(i, da=da) for i, da in enumerate([60, 70, 80, 90, 50])]
    cache = R.build_on_ice_cache(players)
    expected = sum(R.defensive_value(p) for p in players) / len(players)
    assert cache.def_value == expected


def test_empty_cache_def_value_is_neutral_pivot():
    # A degenerate/empty group must be neutral (no suppression), not accidentally strong/weak.
    assert R.build_on_ice_cache([]).def_value == config.DEF_SUPPRESSION_PIVOT


def _away_xg_per_shot(home_da: int, games: int = 40) -> float:
    w = build_world(Rng(21))
    home, away = list(w.teams)[:2]
    for pid in w.teams[home].roster:
        p = w.players[pid]
        if not p.is_goalie:
            p.ratings["defensive_awareness"] = home_da
    auto_build_lines(w.teams[home], w.players)
    xg = sog = 0.0
    for _ in range(games):
        res = GameSim(w, home, away).play()
        for pid in w.teams[away].roster:
            line = res.skater_line(pid)
            xg += line.xg
            sog += line.sog
    return xg / sog


def test_stronger_defense_lowers_opponent_xg_per_shot():
    """A strong defending group yields lower-xG chances against than a weak one. Generous
    margin (assert >=5% lower; the tuned effect is ~15% for this DA gap) so this guards the
    mechanic without being flaky."""
    weak = _away_xg_per_shot(home_da=40)
    strong = _away_xg_per_shot(home_da=95)
    assert strong < weak * 0.95, (weak, strong)
