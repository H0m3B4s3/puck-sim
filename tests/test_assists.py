"""Who gets credited on a goal, and how often.

Two bugs, one of them the kind that hides in plain sight:

1. The rates were 0.80 primary and 0.55 secondary, giving **1.24 assists per goal** against a real
   NHL ~1.70. A quarter of every playmaker's production simply never existed. Not cosmetic --
   assists are most of a centre's point total, so it flattened the whole points leaderboard and
   made the point leader (85) read low at the same time the goal leader read high.
2. ``OnIceCache.playmaking_weights`` was computed on every line change and **never read**.
   ``_pick_assists`` recomputed its own copy inline, in the ``max(0.5, playmaking - 20)``
   subtract-an-offset form that ``build_on_ice_cache`` had already abandoned for shooting.
"""
import statistics

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.models.player import Player
from pucksim.sim.engine import GameSim
from pucksim.sim.ratings import build_on_ice_cache


def _player(pid, position, playmaking):
    return Player(pid=pid, name=f"P{pid}", age=25, position=position,
                  ratings={"playmaking": playmaking, "shot_accuracy": 60,
                           "shot_power": 60, "offensive_awareness": 60})


# ---------------------------------------------------------------------------
# The weight, and the fact that it is now actually consumed
# ---------------------------------------------------------------------------
def test_playmaking_weight_rises_with_the_rating():
    cache = build_on_ice_cache([_player(1, "C", 40), _player(2, "C", 90)])
    assert cache.playmaking_weights[1] > cache.playmaking_weights[0]


def test_playmaking_weight_uses_the_pivot_slope_form():
    """Same shape as the shot weight -- pivot at the league mean, not an offset off zero."""
    average = _player(1, "C", int(config.ASSIST_WEIGHT_PIVOT))
    cache = build_on_ice_cache([average])
    assert abs(cache.playmaking_weights[0] - 1.0) < 1e-9


def test_a_poor_passer_keeps_a_positive_weight():
    cache = build_on_ice_cache([_player(1, "C", 20)])
    assert cache.playmaking_weights[0] >= config.ASSIST_WEIGHT_MIN > 0


def test_pick_assists_reads_the_cached_weights():
    """The regression guard for bug 2. Zeroing the cache must change who gets credited; if
    _pick_assists ever goes back to recomputing its own weights, this stops being true."""
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    sim._advance_shift_for_all()
    offense = sim.home
    shooter = offense.cache.players[0]
    target = offense.cache.players[1]

    # Give one candidate overwhelming weight and confirm he takes every primary assist. The
    # others keep a sliver rather than zero -- the secondary pool excludes the primary, and an
    # all-zero pool is not a weighted draw at all.
    for i, player in enumerate(offense.cache.players):
        offense.cache.playmaking_weights[i] = 1e4 if player.pid == target.pid else 1e-6
    primaries = {sim._pick_assists(offense, shooter)[0] for _ in range(60)}
    assert primaries <= {target.pid, None}
    assert target.pid in primaries


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------
def test_the_two_rates_compound_to_the_nhl_assists_per_goal():
    """PRIMARY + PRIMARY * SECONDARY is the identity that has to land on ~1.70."""
    expected = (config.PRIMARY_ASSIST_CHANCE
                + config.PRIMARY_ASSIST_CHANCE * config.SECONDARY_ASSIST_CHANCE)
    assert 1.62 <= expected <= 1.76, f"configured assists per goal {expected:.3f}"


def test_measured_assists_per_goal_lands_in_band():
    world = build_world(seed=7)
    goals = assists = 0
    for i in range(30):
        result = GameSim(world, i % 32, (i + 9) % 32).play()
        for line in result.skater_box.values():
            goals += line.g
            assists += line.a
    ratio = assists / goals
    assert 1.55 <= ratio <= 1.85, f"{ratio:.3f} assists per goal"


def test_a_goal_never_carries_more_than_two_assists_or_credits_the_scorer():
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    sim._advance_shift_for_all()
    offense = sim.home
    shooter = offense.cache.players[0]
    for _ in range(200):
        primary, secondary = sim._pick_assists(offense, shooter)
        assert primary != shooter.pid and secondary != shooter.pid
        if secondary is not None:
            assert primary is not None and primary != secondary
        for pid in (primary, secondary):
            assert pid is None or pid in offense.on_ice


def test_some_goals_are_unassisted():
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    sim._advance_shift_for_all()
    offense = sim.home
    shooter = offense.cache.players[0]
    outcomes = [sim._pick_assists(offense, shooter)[0] for _ in range(400)]
    assert any(p is None for p in outcomes), "every goal was assisted"


# ---------------------------------------------------------------------------
# Positional split
# ---------------------------------------------------------------------------
def test_defensemen_are_weighted_down_harder_on_the_primary_than_the_secondary():
    """The asymmetry is the hockey: a defenseman's assist more often comes from the breakout or a
    point shot that generates a rebound (second assists) than from the final pass to the slot."""
    assert config.D_PRIMARY_ASSIST_MULT < config.D_SECONDARY_ASSIST_MULT < 1.0


def test_defensemen_take_a_realistic_share_of_assists():
    """Largely a STRUCTURAL problem, which is why the multipliers are needed at all: the scorer is
    excluded from his own assist pool and forwards score ~83% of goals, so the pool is 2F+2D far
    more often than 3F+1D -- ~45% D on headcount before any rating is consulted."""
    shares = []
    for seed in (7, 3, 11):
        world = build_world(seed=seed)
        d_assists = f_assists = 0
        for i in range(30):
            result = GameSim(world, i % 32, (i + 9) % 32).play()
            for pid, line in result.skater_box.items():
                if world.player(pid).position == "D":
                    d_assists += line.a
                else:
                    f_assists += line.a
        shares.append(d_assists / (d_assists + f_assists))
    mean = statistics.mean(shares)
    assert 0.30 <= mean <= 0.44, f"D share of assists {mean:.1%} across seeds {shares}"


def test_a_high_playmaking_group_out_assists_a_low_one():
    """End to end: the weight has to survive into actual credited assists."""
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    sim._advance_shift_for_all()
    offense = sim.home
    shooter = offense.cache.players[0]
    others = offense.cache.players[1:]
    for i, player in enumerate(offense.cache.players):
        if player.pid == shooter.pid:
            continue
        player.ratings["playmaking"] = 95 if player.pid == others[0].pid else 30
    offense._rebuild_cache()
    counts = {}
    for _ in range(600):
        primary, _secondary = sim._pick_assists(offense, offense.cache.players[0])
        counts[primary] = counts.get(primary, 0) + 1
    best = others[0].pid
    rival = others[1].pid
    assert counts.get(best, 0) > counts.get(rival, 0), counts
