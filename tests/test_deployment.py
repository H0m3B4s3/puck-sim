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
def _slot_toi_minutes(seeds=(3, 7, 11, 19, 23, 29)):
    """Mean per-player minutes for each line slot and pair slot, averaged over several games.

    Measured by SLOT (reading ``team.lines``/``team.pairs``) rather than by ranking ice time, which is
    what makes this the clean read on deployment itself -- and per game rather than per season,
    because the coach line-juggling AI mutates the chart over a season (~34 reshuffles per team) and
    a player's season total would be smeared across every slot he passed through.

    Averaged over several games because a single game is no longer a low-variance sample. It was when
    deployment was a deterministic pattern on a fixed 45-second shared shift; it is not now that
    shifts are per-team and variable, changes are possession-gated (a pinned unit stays out), and a
    gassed line gets deferred for a fresher one. All three are genuinely stochastic, and in a single
    game they can even inverse two adjacent slots -- which is realistic (real coaches shorten benches
    and lines get stuck) but useless to assert against.
    """
    fwd_totals = [[] for _ in range(4)]
    dee_totals = [[] for _ in range(3)]
    for seed in seeds:
        world = build_world(seed=seed)
        result = GameSim(world, 0, 1).play()
        team = world.team(0)
        for idx, line in enumerate(team.lines[:4]):
            secs = [result.skater_box[p].secs for p in line if p in result.skater_box]
            if secs:
                fwd_totals[idx].append(statistics.fmean(secs) / 60.0)
        for idx, pair in enumerate(team.pairs[:3]):
            secs = [result.skater_box[p].secs for p in pair if p in result.skater_box]
            if secs:
                dee_totals[idx].append(statistics.fmean(secs) / 60.0)
    fwd = [statistics.fmean(v) if v else 0.0 for v in fwd_totals]
    dee = [statistics.fmean(v) if v else 0.0 for v in dee_totals]
    return fwd, dee


def test_ice_time_is_ordered_by_line_and_pair():
    """The whole point: line 1 out-plays line 2 out-plays line 3 out-plays line 4, and likewise for
    pairs. Before this change all four lines sat at ~16 minutes and all three pairs at ~20."""
    fwd, dee = _slot_toi_minutes()
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
    fwd, dee = _slot_toi_minutes()
    assert 17.0 <= fwd[0] <= 21.0, f"1st line TOI {fwd[0]:.2f} min"
    assert 8.5 <= fwd[3] <= 13.0, f"4th line TOI {fwd[3]:.2f} min"
    assert 21.0 <= dee[0] <= 26.0, f"1st pair TOI {dee[0]:.2f} min"
    assert 13.0 <= dee[2] <= 18.0, f"3rd pair TOI {dee[2]:.2f} min"


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
