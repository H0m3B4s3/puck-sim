"""Weighted line/pair deployment (2026-07-24 calibration round).

The engine used to rotate lines in a flat round robin, giving every forward line an identical 25%
of shifts, so a 4th liner played as many minutes as the 1C and every defenseman outplayed every
forward. These tests pin the replacement: a deterministic repeating pattern built from
config.FORWARD_LINE_SHIFT_SHARES / D_PAIR_SHIFT_SHARES.
"""
import collections
import statistics

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.sim.engine import GameSim, build_deployment_pattern

_FORWARD_POSITIONS = ("LW", "C", "RW")


# ---------------------------------------------------------------------------
# build_deployment_pattern: the pure function
# ---------------------------------------------------------------------------
def test_pattern_frequencies_match_the_configured_shares():
    for shares, count in ((config.FORWARD_LINE_SHIFT_SHARES, 4),
                          (config.D_PAIR_SHIFT_SHARES, 3)):
        pattern = build_deployment_pattern(shares, count, config.DEPLOYMENT_PATTERN_LENGTH)
        counts = collections.Counter(pattern)
        for slot, share in enumerate(shares):
            realized = counts[slot] / len(pattern)
            assert abs(realized - share) < 0.02, (
                f"slot {slot} got {realized:.3f} of shifts, configured {share:.3f}")


def test_shares_sum_to_one():
    """A share list that doesn't sum to 1.0 silently rescales every line's ice time."""
    assert abs(sum(config.FORWARD_LINE_SHIFT_SHARES) - 1.0) < 1e-9
    assert abs(sum(config.D_PAIR_SHIFT_SHARES) - 1.0) < 1e-9
    assert len(config.FORWARD_LINE_SHIFT_SHARES) == 4
    assert len(config.D_PAIR_SHIFT_SHARES) == 3


def test_shares_are_strictly_descending():
    """Line 1 must out-play line 2 must out-play line 3... If a future edit accidentally makes two
    shares equal or inverts them, the deployment mechanic silently stops meaning anything."""
    fwd = config.FORWARD_LINE_SHIFT_SHARES
    assert all(fwd[i] > fwd[i + 1] for i in range(len(fwd) - 1)), fwd
    pairs = config.D_PAIR_SHIFT_SHARES
    assert all(pairs[i] > pairs[i + 1] for i in range(len(pairs) - 1)), pairs


def test_pattern_interleaves_rather_than_running_in_blocks():
    """Line 1 should take roughly every third shift, not the first 25 shifts of the period. Without
    interleaving, the whole first period would be the top line and fatigue/rotation would be wrong
    even though the season-long frequencies looked right."""
    pattern = build_deployment_pattern(config.FORWARD_LINE_SHIFT_SHARES, 4,
                                       config.DEPLOYMENT_PATTERN_LENGTH)
    longest_run = 1
    run = 1
    for a, b in zip(pattern, pattern[1:]):
        run = run + 1 if a == b else 1
        longest_run = max(longest_run, run)
    assert longest_run <= 2, f"pattern runs the same line {longest_run} shifts in a row: {pattern}"
    # Every line appears within the first full cycle, not just eventually.
    assert set(pattern[:8]) == {0, 1, 2, 3}


def test_every_unit_gets_shifts():
    """No line may be shut out -- tests/test_engine.py's positive-ice-time guarantee depends on it."""
    for count in (1, 2, 3, 4, 5):
        pattern = build_deployment_pattern(config.FORWARD_LINE_SHIFT_SHARES, count, 80)
        assert set(pattern) == set(range(count)), f"unit_count={count} left a unit with no shifts"


def test_degenerate_inputs_do_not_raise():
    """Roster edge cases (a team with no built lines, a zero-length pattern) must fall back rather
    than crash -- matching this codebase's thin-bench fallback philosophy elsewhere."""
    assert build_deployment_pattern((0.5, 0.5), 0, 80) == (0,)
    assert build_deployment_pattern((0.5, 0.5), 2, 0) == (0,)
    assert set(build_deployment_pattern((0.0, 0.0, 0.0), 3, 30)) == {0, 1, 2}


def test_pattern_is_deterministic():
    """Same inputs, same pattern -- deployment must not perturb the seeded RNG stream or vary run
    to run, or identical seeds would stop reproducing identical games."""
    a = build_deployment_pattern(config.FORWARD_LINE_SHIFT_SHARES, 4, 80)
    b = build_deployment_pattern(config.FORWARD_LINE_SHIFT_SHARES, 4, 80)
    assert a == b


# ---------------------------------------------------------------------------
# End to end: ice time actually lands where the shares say
# ---------------------------------------------------------------------------
def _slot_toi_minutes(world, team, result):
    """Mean per-player minutes for each line slot and pair slot, from a single game's box score.

    Measured per GAME rather than per season deliberately: the coach line-juggling AI mutates
    team.lines over a season (~34 reshuffles per team per season), so a player's season total is
    spread across every slot he passed through and the slot-level spread washes out. One game with
    no reshuffle is the clean read on what deployment itself does.
    """
    fwd = []
    for line in team.lines:
        secs = [result.skater_box[p].secs for p in line if p in result.skater_box]
        fwd.append(statistics.fmean(secs) / 60.0 if secs else 0.0)
    dee = []
    for pair in team.pairs:
        secs = [result.skater_box[p].secs for p in pair if p in result.skater_box]
        dee.append(statistics.fmean(secs) / 60.0 if secs else 0.0)
    return fwd, dee


def test_ice_time_is_ordered_by_line_and_pair():
    """The whole point: line 1 out-plays line 2 out-plays line 3 out-plays line 4, and likewise for
    pairs. Before this change all four lines sat at ~16 minutes and all three pairs at ~20."""
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    result = sim.play()
    assert sim.home.reshuffle_count == 0, "seed drifted into a reshuffle; pick another"
    fwd, dee = _slot_toi_minutes(world, world.team(0), result)

    assert all(fwd[i] > fwd[i + 1] for i in range(3)), f"forward TOI not descending: {fwd}"
    assert all(dee[i] > dee[i + 1] for i in range(2)), f"pair TOI not descending: {dee}"
    # A real 1C plays roughly 1.7x a 4C, not 1.0x. Guards against a change that keeps the ordering
    # but flattens the gap back toward the old round robin.
    assert fwd[0] / fwd[3] > 1.4, f"top/bottom forward TOI ratio only {fwd[0] / fwd[3]:.2f}"
    assert dee[0] / dee[2] > 1.2, f"top/bottom pair TOI ratio only {dee[0] / dee[2]:.2f}"


def test_line_one_ice_time_is_in_a_realistic_band():
    """Ordering alone can be satisfied by absurd magnitudes (a 30-minute 1st line, a 2-minute 4th),
    so pin the levels too. NHL: roughly 19 / 16 / 14 / 11 minutes for forward lines, 24 / 20 / 16
    for pairs."""
    world = build_world(seed=7)
    result = GameSim(world, 0, 1).play()
    fwd, dee = _slot_toi_minutes(world, world.team(0), result)
    assert 17.0 <= fwd[0] <= 21.0, f"1st line TOI {fwd[0]:.2f} min"
    assert 9.0 <= fwd[3] <= 13.0, f"4th line TOI {fwd[3]:.2f} min"
    assert 21.0 <= dee[0] <= 26.0, f"1st pair TOI {dee[0]:.2f} min"
    assert 14.0 <= dee[2] <= 18.0, f"3rd pair TOI {dee[2]:.2f} min"


def test_top_forwards_outplay_bottom_forwards_over_a_full_game():
    """Position-aware sanity check that survives line juggling: rank a team's forwards by ice time
    and confirm the top trio genuinely separates from the bottom trio."""
    world = build_world(seed=11)
    result = GameSim(world, 4, 20).play()
    team = world.team(4)
    toi = sorted((result.skater_box[p].secs / 60.0
                  for p in team.roster
                  if p in result.skater_box
                  and world.player(p).position in _FORWARD_POSITIONS),
                 reverse=True)
    assert len(toi) >= 12
    top = statistics.fmean(toi[:3])
    bottom = statistics.fmean(toi[9:12])
    assert top > bottom * 1.4, f"top-3 forwards {top:.2f} min vs bottom-3 {bottom:.2f} min"
