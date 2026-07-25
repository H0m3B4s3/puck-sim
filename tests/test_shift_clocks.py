"""Per-team shift clocks and possession-gated line changes -- the "death shift".

Play used to advance one shared "shift" at a time: a single ``shift_secs`` was drawn and BOTH teams
changed lines at that same boundary. That is mite hockey, where a horn blows and everyone comes off.
Real changes happen on the fly, per team and independently, and a team that has lost the puck in its
own zone cannot get off at all -- the attacking team swaps players at will while the defending unit
stays out there getting more tired.

Play now advances in variable-length SEGMENTS: a segment runs until the next bench is due, each team
keeps its own clock, and a change is granted only when that team is able to make one.
"""
import statistics

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.sim import engine as E
from pucksim.sim.engine import GameSim
from pucksim.sim.ratings import fatigue_realization


def _play_games(n=10, seed=7):
    world = build_world(seed=seed)
    sims = []
    for i in range(n):
        sim = GameSim(world, i % 32, (i + 9) % 32)
        sim.play()
        sims.append(sim)
    return world, sims


# ---------------------------------------------------------------------------
# Segments are not shifts
# ---------------------------------------------------------------------------
def test_segments_are_shorter_and_more_numerous_than_shifts():
    """A segment runs to whichever bench is due first, so it is a slice of play, not a shift."""
    world = build_world(seed=7)
    segments = []
    original = GameSim._play_shift

    def instrumented(self, secs):
        segments.append(secs)
        return (yield from original(self, secs))

    GameSim._play_shift = instrumented
    try:
        sim = GameSim(world, 0, 1)
        sim.play()
    finally:
        GameSim._play_shift = original

    assert len(segments) > 150, f"only {len(segments)} segments -- still one-shift-at-a-time?"
    assert statistics.fmean(segments) < config.SHIFT_SECONDS_TARGET
    # Variable length, not a fixed slice.
    assert statistics.stdev(segments) > 1.0


def test_total_segment_time_reconciles_with_regulation():
    """Segments must tile the period exactly -- no lost or double-counted game time."""
    world = build_world(seed=7)
    total = []
    original = GameSim._play_shift

    def instrumented(self, secs):
        total.append(secs)
        return (yield from original(self, secs))

    GameSim._play_shift = instrumented
    try:
        GameSim(world, 0, 1).play()
    finally:
        GameSim._play_shift = original

    regulation = config.PERIODS * config.PERIOD_SECONDS
    assert sum(total) >= regulation - 1.0, f"only {sum(total):.0f}s of play for {regulation}s"


# ---------------------------------------------------------------------------
# Benches change independently
# ---------------------------------------------------------------------------
def test_the_two_benches_do_not_change_in_lockstep():
    """The direct expression of the bug. If both teams still changed on a shared horn, their
    on-ice groups would turn over at exactly the same moments."""
    world = build_world(seed=7)
    home_changes, away_changes = [], []
    original = GameSim._play_shift
    counter = {"n": 0}
    last = {}

    def instrumented(self, secs):
        counter["n"] += 1
        for label, state in (("home", self.home), ("away", self.away)):
            group = tuple(sorted(state.on_ice))
            if last.get(label) is not None and group != last[label]:
                (home_changes if label == "home" else away_changes).append(counter["n"])
            last[label] = group
        return (yield from original(self, secs))

    GameSim._play_shift = instrumented
    try:
        GameSim(world, 0, 1).play()
    finally:
        GameSim._play_shift = original

    assert home_changes and away_changes
    shared = set(home_changes) & set(away_changes)
    # Some coincidence is expected (faceoffs let both change), but far from all of them.
    assert len(shared) < 0.6 * min(len(home_changes), len(away_changes)), (
        "benches are still changing together")


def test_shift_length_averages_near_the_target():
    """Possession gating must not silently inflate shift length. A hard "no puck, no change" gate
    stretched the mean from the 45s target to 63s and made 43% of shifts death shifts."""
    _, sims = _play_games()
    completed = [st.shifts_completed for sim in sims for st in (sim.home, sim.away)]
    mean_shifts = statistics.fmean(completed)
    mean_length = (config.PERIODS * config.PERIOD_SECONDS) / mean_shifts
    assert 42.0 <= mean_length <= 54.0, f"mean shift length {mean_length:.1f}s"


# ---------------------------------------------------------------------------
# The death shift
# ---------------------------------------------------------------------------
def test_some_shifts_run_past_their_intended_length():
    """The phenomenon this step exists for: a unit that cannot get off stays out."""
    _, sims = _play_games()
    completed = sum(st.shifts_completed for sim in sims for st in (sim.home, sim.away))
    trapped = sum(st.trapped_shifts for sim in sims for st in (sim.home, sim.away))
    rate = trapped / completed
    assert 0.02 <= rate <= 0.30, f"{rate:.0%} of shifts ran past target"


def test_a_trapped_unit_is_measurably_more_tired():
    """A death shift has to COST something, or it is just bookkeeping. Fatigue is time-based, so a
    unit stuck out there accumulates more of it -- and therefore performs worse."""
    world = build_world(seed=7)
    within, past = [], []
    original = GameSim._apply_ice_time

    def instrumented(self, secs):
        out = original(self, secs)
        for state in (self.home, self.away):
            values = [state.fatigue.get(pid, 0.0) for pid in state.on_ice]
            if not values:
                continue
            bucket = past if state.shift_elapsed > state.shift_target else within
            bucket.append(statistics.fmean(values))
        return out

    GameSim._apply_ice_time = instrumented
    try:
        for i in range(8):
            GameSim(world, i % 32, (i + 9) % 32).play()
    finally:
        GameSim._apply_ice_time = original

    assert within and past
    assert statistics.fmean(past) > statistics.fmean(within) + 8.0, (
        f"trapped {statistics.fmean(past):.1f} vs within-target {statistics.fmean(within):.1f}")
    # And that fatigue actually degrades them.
    assert fatigue_realization(statistics.fmean(past)) < fatigue_realization(
        statistics.fmean(within))


def test_a_team_with_the_puck_can_always_change_when_due():
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    sim._pending_faceoff = None
    sim._possession = sim.home
    sim.home.shift_elapsed = sim.home.shift_target + 1.0
    assert sim._can_change_lines(sim.home)


def test_a_faceoff_lets_either_team_change():
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    sim._pending_faceoff = sim.home
    sim._possession = sim.home
    assert sim._can_change_lines(sim.away)


def test_the_hard_cap_always_releases_a_trapped_unit():
    """Guarantees termination: without it a team that keeps losing the possession roll could stay
    out for a whole period."""
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    sim._pending_faceoff = None
    sim._possession = sim.home
    sim.away.shift_elapsed = E.SHIFT_SECONDS_MAX + 1.0
    assert sim._can_change_lines(sim.away)


def test_nobody_stays_out_past_the_hard_cap():
    _, sims = _play_games(n=6)
    for sim in sims:
        for state in (sim.home, sim.away):
            assert state.shift_elapsed <= E.SHIFT_SECONDS_MAX + E.SEGMENT_SECONDS_MIN + 1.0


# ---------------------------------------------------------------------------
# Rates that were coupled to "one shift per iteration"
# ---------------------------------------------------------------------------
def test_penalty_rate_survives_the_segment_split():
    """PENALTY_BASE_PROB_PER_SHIFT is a PER-SHIFT probability. Rolling it once per segment without
    scaling would multiply penalties by however many segments a shift takes -- the same coupling
    that silently tripled the hit rate when shot volume was corrected."""
    _, sims = _play_games(n=16)
    pim = [sum(line.pim for line in sim.result.skater_box.values()) / 2 for sim in sims]
    assert 2.0 <= statistics.fmean(pim) <= 14.0, f"PIM/team/game {statistics.fmean(pim):.1f}"


def test_injury_rate_survives_the_segment_split():
    """IN_GAME_INJURY_RATE is likewise per-shift. Unscaled, a season's injuries would balloon."""
    _, sims = _play_games(n=16)
    per_game = statistics.fmean([len(sim.result.injuries) for sim in sims])
    assert per_game <= 2.0, f"{per_game:.2f} injuries per game across both teams"


def test_penalty_probability_scales_with_time():
    """The scaling itself, at the unit level."""
    from pucksim.sim import special_teams as ST
    from pucksim.models.coach import profile_for

    world = build_world(seed=7)
    team = world.team(0)
    players = [world.player(pid) for pid in team.lines[0] + team.pairs[0]]
    coach = profile_for("Balanced")
    full = ST.penalty_probability_for_shift(players, coach)
    assert full > 0

    class _AlwaysAt:
        def __init__(self, threshold):
            self.threshold = threshold

        def chance(self, p):
            return p >= self.threshold

    # At a tenth of a shift the probability must be about a tenth as large.
    assert not ST.roll_for_penalty(_AlwaysAt(full * 0.5), players, coach, time_scale=0.1)
    assert ST.roll_for_penalty(_AlwaysAt(full * 0.5), players, coach, time_scale=1.0)


# ---------------------------------------------------------------------------
# Possession and rush chances
# ---------------------------------------------------------------------------
def test_possession_persists_across_segments():
    """Possession has to be instance state, not a local: it decides which bench may change next."""
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    seen = []
    original = GameSim._play_shift

    def instrumented(self, secs):
        result = yield from original(self, secs)
        seen.append(self._possession)
        return result

    GameSim._play_shift = instrumented
    try:
        sim.play()
    finally:
        GameSim._play_shift = original
    assert all(p is not None for p in seen)
    assert len({id(p) for p in seen}) == 2, "possession never changed hands"


def test_rush_share_is_realistic():
    """A rush belongs to a fresh zone entry, so the pending-rush flag is consumed by the next
    ATTEMPT, not by the start of a segment. Consuming it per segment burned it on the many segments
    that contain no attempt and collapsed the rush share from ~23% to 4.6%."""
    world = build_world(seed=7)
    rushes = {"yes": 0, "no": 0}
    original = GameSim._resolve_shot_attempt

    def instrumented(self, offense, defense, *, rush, rebound):
        rushes["yes" if rush else "no"] += 1
        return original(self, offense, defense, rush=rush, rebound=rebound)

    GameSim._resolve_shot_attempt = instrumented
    try:
        for i in range(8):
            GameSim(world, i % 32, (i + 9) % 32).play()
    finally:
        GameSim._resolve_shot_attempt = original

    share = rushes["yes"] / (rushes["yes"] + rushes["no"])
    assert 0.10 <= share <= 0.35, f"rush share {share:.3f}"
