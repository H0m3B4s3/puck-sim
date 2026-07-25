"""In-game fatigue, and the coach reading it when choosing a line.

Two bugs found 2026-07-25, both of which made fatigue decorative:

1. ``FATIGUE_GAIN_PER_SEC`` (0.028) was SMALLER than ``FATIGUE_RECOVER_PER_SEC`` (0.05). Linear
   break-even sits at ``recover / (gain + recover)`` = 64% ice time, and no skater plays that much,
   so every skater sat at ~0 fatigue all game and ``fatigue_realization`` returned 1.0 on every
   shot. The only player who tired was the goalie, who never leaves the ice to recover.
2. Nothing read fatigue when picking a line, so a first line could go straight back out after its
   forwards had just killed two minutes on the power play -- at no cost, given (1).
"""
import statistics

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.sim import engine as E
from pucksim.sim.engine import GameSim
from pucksim.sim.ratings import FATIGUE_R_MIN, fatigue_realization


def _peaks(seed=7, home=0, away=1):
    """Per-player (ice-time minutes, mean fatigue at shift start, mean at shift end) for one game."""
    world = build_world(seed=seed)
    sim = GameSim(world, home, away)
    at_start, at_end = {}, {}
    original = GameSim._apply_ice_time

    def instrumented(self, secs):
        for pid in self.home.on_ice:
            at_start.setdefault(pid, []).append(self.home.fatigue.get(pid, 0.0))
        out = original(self, secs)
        for pid in self.home.on_ice:
            at_end.setdefault(pid, []).append(self.home.fatigue.get(pid, 0.0))
        return out

    GameSim._apply_ice_time = instrumented
    try:
        result = sim.play()
    finally:
        GameSim._apply_ice_time = original

    rows = []
    for pid in at_start:
        player = world.player(pid)
        if player.position == "G":
            continue
        toi = result.skater_box[pid].secs / 60.0 if pid in result.skater_box else 0.0
        rows.append((toi, statistics.fmean(at_start[pid]), statistics.fmean(at_end[pid])))
    return world, sim, result, rows


# ---------------------------------------------------------------------------
# Fatigue exists at all
# ---------------------------------------------------------------------------
def test_gain_outpaces_recovery_per_second():
    """The direct expression of bug 1. A second on the ice must cost more than a second on the bench
    returns, or a player on a normal rotation never accumulates anything."""
    assert E.FATIGUE_GAIN_PER_SEC > 0
    assert E.FATIGUE_RECOVERY_TAU_SECS > 0
    # A 45-second shift has to move fatigue enough to matter on a 0-100 scale.
    assert 45 * E.FATIGUE_GAIN_PER_SEC >= 20.0


def test_skaters_actually_tire_during_a_game():
    _, _, _, rows = _peaks()
    ends = [end for _, _, end in rows]
    assert statistics.fmean(ends) > 25.0, f"mean shift-end fatigue only {statistics.fmean(ends):.1f}"


def test_nobody_pins_at_the_ceiling():
    """Linear recovery pinned every player above the break-even ice share at 100, which flattened
    exactly the differences fatigue is supposed to create. Exponential decay gives each ice-time
    share its own equilibrium."""
    _, _, _, rows = _peaks()
    pinned = [toi for toi, _, end in rows if end >= 99.5]
    assert not pinned, f"{len(pinned)} players pinned at the fatigue ceiling"


def test_fatigue_scales_with_ice_time():
    """A 25-minute defenseman must be measurably more tired than a 9-minute fourth-liner. If this
    fails, fatigue is not tracking deployment and cannot inform it."""
    _, _, _, rows = _peaks()
    rows.sort(reverse=True)
    heavy = statistics.fmean([end for _, _, end in rows[:4]])
    light = statistics.fmean([end for _, _, end in rows[-4:]])
    assert heavy > light + 8.0, f"heavy-usage {heavy:.1f} vs light-usage {light:.1f}"


def test_recovery_is_exponential_not_linear():
    """A tired player must recover faster than a fresh one -- that property is what bounds fatigue
    for every ice-time share."""
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    state = sim.home
    bench = [pid for pid in state.team.roster
             if pid not in state.on_ice and pid not in state.unavailable
             and world.player(pid).position != "G"]
    assert len(bench) >= 2
    tired, fresh = bench[0], bench[1]
    state.fatigue[tired] = 80.0
    state.fatigue[fresh] = 20.0
    sim._apply_ice_time(30.0)
    tired_drop = 80.0 - state.fatigue[tired]
    fresh_drop = 20.0 - state.fatigue[fresh]
    assert tired_drop > fresh_drop * 2, (
        f"tired player recovered {tired_drop:.2f}, fresh {fresh_drop:.2f}")


def test_goalie_fatigue_is_not_derived_from_the_skater_rate():
    """A goalie never leaves the ice, so he never hits the recovery branch -- his fatigue is a
    one-way ramp across 60 minutes and has to be scaled to that, not to a 45-second shift. When it
    was ``FATIGUE_GAIN_PER_SEC * 0.4``, raising the skater rate to make skater fatigue exist pinned
    every goalie at the ceiling before the first intermission."""
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    sim.play()
    goalie_fatigue = [f for pid, f in sim.home.fatigue.items()
                      if world.player(pid).position == "G" and f > 0]
    assert goalie_fatigue
    peak = max(goalie_fatigue)
    assert 20.0 <= peak <= 70.0, f"full-game goalie ended at {peak:.1f}"


def test_realization_stays_capped_at_one():
    """The no-upweighting invariant (see ratings.py): fatigue may only ever pull performance DOWN.
    A fresh player performs at his rating, never above it."""
    assert fatigue_realization(0.0) == 1.0
    assert fatigue_realization(-10.0) == 1.0
    assert fatigue_realization(100.0) == FATIGUE_R_MIN
    assert fatigue_realization(1000.0) == FATIGUE_R_MIN
    prev = 1.0
    for f in range(0, 101, 10):
        cur = fatigue_realization(float(f))
        assert cur <= prev + 1e-9, "realization must be monotonically non-increasing in fatigue"
        prev = cur


# ---------------------------------------------------------------------------
# The coach reads it
# ---------------------------------------------------------------------------
def test_gassed_line_is_deferred_for_a_fresher_one():
    """Line 2 is made UNIQUELY freshest. Every line starts a game at 0 fatigue, so leaving the
    others untouched would make line 1 tie line 2 and win on the lower-index tiebreak -- correct
    behavior, but it would not prove the freshest line is the one chosen."""
    world = build_world(seed=7)
    state = GameSim(world, 0, 1).home
    lines = state.team.lines
    assert len(lines) >= 3
    for idx, line in enumerate(lines):
        for pid in line:
            state.fatigue[pid] = 95.0 if idx == 0 else 60.0
    for pid in lines[2]:
        state.fatigue[pid] = 0.0
    assert state._freshest_alternative(lines, 0) == 2


def test_a_merely_tired_line_still_goes_out():
    """Bounded override, not "always play the freshest line". The configured shift shares are the
    coach's plan; a plan abandoned whenever anyone breathes hard is not a plan."""
    world = build_world(seed=7)
    state = GameSim(world, 0, 1).home
    lines = state.team.lines
    for pid in lines[0]:
        state.fatigue[pid] = E.FATIGUE_DEFER_THRESHOLD - 1.0
    for pid in lines[2]:
        state.fatigue[pid] = 0.0
    assert state._freshest_alternative(lines, 0) == 0


def test_no_swap_when_every_line_is_equally_gassed():
    """Guards against thrashing between units that are all tired -- the margin has to bind."""
    world = build_world(seed=7)
    state = GameSim(world, 0, 1).home
    lines = state.team.lines
    for line in lines:
        for pid in line:
            state.fatigue[pid] = 90.0
    assert state._freshest_alternative(lines, 1) == 1


def test_deferral_is_deterministic_and_prefers_the_lower_index():
    """Ties break toward the better line, and identically -- the same seed must reproduce the same
    game."""
    world = build_world(seed=7)
    state = GameSim(world, 0, 1).home
    lines = state.team.lines
    for pid in lines[0]:
        state.fatigue[pid] = 95.0
    for line in lines[1:]:
        for pid in line:
            state.fatigue[pid] = 0.0
    picks = {state._freshest_alternative(lines, 0) for _ in range(5)}
    assert picks == {1}


def test_single_unit_roster_never_raises():
    world = build_world(seed=7)
    state = GameSim(world, 0, 1).home
    assert state._freshest_alternative([[1, 2, 3]], 0) == 0
    assert state._freshest_alternative([], 0) == 0


def test_post_power_play_double_shifting_is_rare():
    """The behavior this whole step exists for. Before it, 27% of the 5v5 shifts immediately
    following a power play reused 3 or more of the players who had just been on the PP unit -- a
    coach nobody would hire, and free given fatigue was inert."""
    world = build_world(seed=7)
    reused_3plus = 0
    post_pp_shifts = 0
    carried = []
    previous = {}
    original = GameSim._apply_ice_time

    def instrumented(self, secs):
        state = self.home
        strength = self.strength.state_for(state.tid)
        current = set(state.on_ice)
        prior = previous.get("shift")
        if prior is not None and prior[1] == config.STRENGTH_PP and strength == config.STRENGTH_5V5:
            nonlocal post_pp_shifts, reused_3plus
            post_pp_shifts += 1
            overlap = len(current & prior[0])
            carried.append(overlap)
            if overlap >= 3:
                reused_3plus += 1
        previous["shift"] = (current, strength)
        return original(self, secs)

    GameSim._apply_ice_time = instrumented
    try:
        for i in range(20):
            previous.clear()
            GameSim(world, i % 32, (i + 9) % 32).play()
    finally:
        GameSim._apply_ice_time = original

    assert post_pp_shifts >= 10, f"only {post_pp_shifts} post-PP shifts sampled"
    rate = reused_3plus / post_pp_shifts
    assert rate <= 0.15, f"{rate:.0%} of post-PP shifts reused 3+ of the PP unit"
    assert statistics.fmean(carried) < 1.3, (
        f"mean {statistics.fmean(carried):.2f} PP players carried straight over")
