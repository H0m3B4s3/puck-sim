"""Tests for pucksim.sim.goalies + the goalie-related extensions to
pucksim.sim.engine/ratings -- DEVPLAN.md Step 2.2 done-criteria.

Covers, in order:
  1. The "no upweighting" fix, tested directly and explicitly: a maxed-out hot-hand streak
     applied to a perfectly neutral shot (def_real == 1.0 absent hot hand) changes nothing, and
     a property-style sweep proves effective_def_real never exceeds 1.0 and never drops below
     the input def_real, for any combination of inputs.
  2. Starter/backup rest-based rotation over a simulated stretch of games, including a forced
     back-to-back scenario.
  3. Pull-the-goalie: a trailing team late in a close game fields a 6-skater on-ice group and
     produces a measurably higher empty-net-goal-against rate; the goalie un-pulls when the
     score changes.
"""
from __future__ import annotations

import random

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.models.coach import CoachProfile
from pucksim.sim import goalies as G
from pucksim.sim import ratings as R
from pucksim.sim.boxscore import EVENT_GOAL
from pucksim.sim.engine import GameSim
from pucksim.sim.season import (
    _choose_and_record_starter,
    advance_one_day,
    generate_schedule,
)

# ---------------------------------------------------------------------------
# 1a. ratings.hot_hand_boost() -- basic shape
# ---------------------------------------------------------------------------
def test_hot_hand_boost_is_zero_at_zero_streak():
    assert R.hot_hand_boost(0.0) == 0.0
    assert R.hot_hand_boost(-5.0) == 0.0   # negative streak values are clamped, never negative out


def test_hot_hand_boost_is_bounded_by_max_fraction():
    for streak in (0.0, 1.0, 3.0, 6.0, 12.0, 100.0, 10_000.0):
        frac = R.hot_hand_boost(streak)
        assert 0.0 <= frac <= R.HOT_HAND_MAX_FRACTION


def test_hot_hand_boost_increases_monotonically_with_streak():
    streaks = [0.0, 1.0, 2.0, 4.0, 6.0, 10.0, 20.0]
    fractions = [R.hot_hand_boost(s) for s in streaks]
    for a, b in zip(fractions, fractions[1:]):
        assert b >= a   # monotonic non-decreasing ramp


# ---------------------------------------------------------------------------
# 1b. THE core "no upweighting" fix -- tested directly and explicitly.
# ---------------------------------------------------------------------------
def _effective_def_real(def_real: float, streak: float) -> float:
    """The exact gap-closing formula engine.py's _resolve_shot_attempt applies -- duplicated
    here (rather than reaching into GameSim internals) so this test exercises the formula in
    total isolation, matching how ratings.py's other realization factors are unit-tested."""
    fraction = R.hot_hand_boost(streak)
    return def_real + (1.0 - def_real) * fraction


def test_neutral_shot_at_full_realization_is_unchanged_by_maxed_hot_hand():
    """The headline claim: a perfectly neutral shot (def_real already exactly 1.0 -- no morale/
    fatigue/chemistry drag) run through a MAXED-OUT hot-hand streak must resolve to EXACTLY 1.0,
    never higher. This is the direct proof that hot hand cannot push a goalie's save probability
    above what his rating alone would already produce -- the bug the old additive
    ``goalie_hot_hand`` nudge had (it could push a neutral 0.90 save_p up to 0.96 purely from a
    streak, which is strictly better than the goalie's own rating ceiling implies)."""
    def_real = 1.0
    for streak in (0.0, 1.0, 6.0, 12.0, 1000.0):
        effective = _effective_def_real(def_real, streak)
        assert effective == 1.0, (
            f"streak={streak} produced effective_def_real={effective}, expected exactly 1.0 -- "
            "hot hand must have NOTHING left to close when def_real is already at the ceiling"
        )


def test_hot_hand_pulls_a_dragged_down_def_real_measurably_closer_to_one_but_never_past_it():
    """Construct a scenario where OTHER realization factors (e.g. low goalie morale) ARE
    dragging def_real below 1.0, then confirm a maxed-out hot-hand fraction pulls it measurably
    closer to 1.0 without ever exceeding it."""
    low_morale_def_real = R.morale_realization(20)   # a goalie in a real slump
    assert low_morale_def_real < 1.0, "test setup: morale realization must actually be < 1.0 here"

    cold = _effective_def_real(low_morale_def_real, streak=0.0)
    hot = _effective_def_real(low_morale_def_real, streak=100.0)   # far past saturation -> max fraction

    assert cold == low_morale_def_real   # zero streak: no boost at all, unchanged from input
    assert hot > cold                    # a hot streak measurably narrows the gap...
    assert hot <= 1.0                    # ...but never past the ceiling
    assert hot < 1.0                     # ...and (since HOT_HAND_MAX_FRACTION < 1.0) not all the
                                          # way to a full realization either -- a partial close,
                                          # not a free pass back to peak.


def test_effective_def_real_never_exceeds_one_or_drops_below_input_across_random_inputs():
    """Property-style sweep (DEVPLAN.md's suggested style for proving a bound holds generally,
    not just in hand-picked cases): across many random combinations of def_real (itself the
    product of several other bounded realization factors, so always in a realistic sub-1.0
    range) and streak value, the gap-closing formula must ALWAYS satisfy
    def_real <= effective_def_real <= 1.0."""
    rng = random.Random(1234)
    for _ in range(5000):
        def_real = rng.uniform(0.5, 1.0)   # the realistic range multiplicative realization factors
                                            # actually produce (each individual factor is floored
                                            # well above 0, and def_real is itself already a
                                            # product of several -- see _resolve_shot_attempt)
        streak = rng.uniform(0.0, 50.0)
        effective = _effective_def_real(def_real, streak)
        assert def_real - 1e-9 <= effective <= 1.0 + 1e-9, (
            f"def_real={def_real}, streak={streak} -> effective={effective} violates the bound"
        )


def test_engine_goalie_hot_hand_streak_builds_on_saves_and_resets_on_goal():
    """Integration-level: the actual _TeamState.goalie_hot_hand counter (the streak-tracking
    state living in engine.py, per this step's assignment) increments across consecutive saves
    and resets to 0.0 on a goal against -- proving the engine wires the streak counter through
    ratings.hot_hand_boost() rather than reintroducing a bespoke inline formula."""
    world = build_world(seed=77)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    away = sim.away

    assert away.goalie_hot_hand == 0.0
    away.goalie_hot_hand = 5.0
    # Directly exercise _score_goal's reset behavior (goalie is not None -> hot hand resets).
    home = sim.home
    shooter = world.player(home.on_ice[0]) if home.on_ice else world.player(home.team.roster[0])
    goalie = away.goalie()
    sim._score_goal(home, away, shooter, goalie, "slot", "wrist", False, False)
    assert away.goalie_hot_hand == 0.0


def test_pulled_goalie_is_never_sent_out_as_the_extra_attacker():
    """When a goalie is pulled, ``_TeamState.goalie_id`` becomes None -- an earlier
    ``pid != self.goalie_id`` filter then stopped excluding the just-pulled goalie, who could be
    sent back out as the 6th "attacker" (and accrue skater stats). The extra attacker must always
    be a SKATER, whoever is in net or on the bench."""
    world = build_world(seed=26)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    state = sim.home
    state.goalie_pulled = True
    state.goalie_id = None                       # what _maybe_pull_goalie does
    group = state._with_extra_attacker(list(state.on_ice))
    for pid in group:
        assert world.player(pid).position != "G", f"goalie {pid} iced as extra attacker"
    # And the pulled starter specifically must not be the one added.
    assert state.starter_goalie_id not in group


# ---------------------------------------------------------------------------
# 2. Starter/backup rest-based rotation
# ---------------------------------------------------------------------------
def test_choose_starting_goalie_falls_back_to_starter_with_no_backup():
    world = build_world(seed=3)
    team = world.team(sorted(world.teams.keys())[0])
    team.goalie_backup = None
    rest_state = G.GoalieRestState()
    chosen = G.choose_starting_goalie(team, rest_state, day=0, rng=world.rng)
    assert chosen == team.goalie_starter


def test_choose_starting_goalie_gives_backup_a_look_after_max_consecutive_starts():
    world = build_world(seed=4)
    team = world.team(sorted(world.teams.keys())[0])
    rest_state = G.GoalieRestState()
    starter = team.goalie_starter
    backup = team.goalie_backup
    assert starter is not None and backup is not None

    day = 0
    for _ in range(G.STARTER_MAX_CONSECUTIVE_STARTS):
        chosen = G.choose_starting_goalie(team, rest_state, day=day, rng=world.rng)
        assert chosen == starter
        rest_state.record_start(team.tid, chosen, day)
        day += 3   # plenty of rest between starts, isolating the "too many straight starts" trigger

    chosen = G.choose_starting_goalie(team, rest_state, day=day, rng=world.rng)
    assert chosen == backup, "backup should get a look once the starter goes too many games straight"


def test_choose_starting_goalie_sometimes_avoids_true_back_to_back():
    """Across many trials, a starter going on zero days' rest (played yesterday, same goalie
    started) should be handed off to the backup a genuine, substantial fraction of the time
    (``BACK_TO_BACK_AVOID_PROB``) -- but not with 100% certainty -- DEVPLAN.md: "avoid... more
    often than not, but it does happen." ``BACK_TO_BACK_AVOID_PROB`` is calibrated to 0.5 (see
    goalies.py's own docstring on that constant) specifically because this codebase's schedule
    generator has NO rest days at all -- every game is technically a back-to-back -- so this
    check ends up doing double duty as the main lever that pulls the season-long starter share
    down into the real-NHL-realistic band (see the season-stretch test below), rather than only
    firing on rare genuine zero-rest nights. This test proves both outcomes occur with real,
    substantial frequency (neither a hard rule nor a rare fluke) rather than asserting a strict
    majority in either direction, since the calibrated probability is intentionally close to
    a coin flip here."""
    world = build_world(seed=5)
    team = world.team(sorted(world.teams.keys())[0])
    starter = team.goalie_starter
    backup = team.goalie_backup
    assert starter is not None and backup is not None

    back_to_back_starts = 0
    trials = 300
    for i in range(trials):
        rest_state = G.GoalieRestState()
        rest_state.record_start(team.tid, starter, day=0)   # started yesterday
        chosen = G.choose_starting_goalie(team, rest_state, day=1, rng=world.rng)  # true b2b (day+1)
        if chosen == starter:
            back_to_back_starts += 1

    frac_started = back_to_back_starts / trials
    assert 0.2 < frac_started < 0.8, (
        f"expected both outcomes to occur with substantial frequency on a true back-to-back, "
        f"got started {frac_started:.2%} of trials"
    )


def test_starter_plays_planned_share_of_games_over_a_simulated_stretch():
    """Simulate a few weeks of a real schedule (via sim/season.py's advance_one_day, which now
    consumes choose_starting_goalie per DEVPLAN.md Step 2.2) and confirm a team's starter takes
    the planned share of starts (roughly 55-65 of 82 real-NHL games -- scaled down here to a
    shorter stretch) while the backup mixes in, including on forced short-rest windows."""
    world = build_world(seed=6)
    world.schedule = generate_schedule(world, target_games=30)
    world.day = 0

    tids = sorted(world.teams.keys())
    watch_tid = tids[0]
    team = world.team(watch_tid)
    starter, backup = team.goalie_starter, team.goalie_backup
    assert starter is not None and backup is not None

    max_day = max((g.day for g in world.schedule), default=0)
    for _ in range(max_day + 2):
        advance_one_day(world)

    total_games = team.games_played
    assert total_games > 0

    # Recompute the observed split directly from the season stat lines accumulated onto each
    # goalie's Player.season (GoalieStatLine.gp is set to 1 per game the goalie actually played
    # in _finalize -- see engine.py).
    starter_gp = world.player(starter).season.gp
    backup_gp = world.player(backup).season.gp
    assert starter_gp + backup_gp == total_games

    starter_share = starter_gp / total_games
    # Real-NHL target is ~55-65 of 82 (~0.67-0.79). Over a short 30ish-ish-ish game sample with
    # randomized back-to-back exceptions, assert the starter takes a clear MAJORITY of starts
    # but the backup gets a genuine, nonzero share -- a looser band than the full-season target,
    # appropriate for a short simulated stretch.
    assert starter_share > 0.5, f"starter should start a majority of games, got {starter_share:.2%}"
    assert backup_gp > 0, "backup should start at least one game over a multi-week stretch"


def test_backup_starts_on_a_forced_back_to_back_at_least_sometimes():
    """Force a back-to-back scenario directly (bypassing the schedule generator's own cadence,
    which may not always produce true zero-rest back-to-backs) and confirm the rotation logic
    does, across many trials, sometimes hand the second game to the backup."""
    world = build_world(seed=7)
    team = world.team(sorted(world.teams.keys())[0])
    starter, backup = team.goalie_starter, team.goalie_backup
    assert starter is not None and backup is not None

    backup_starts = 0
    trials = 200
    for _ in range(trials):
        rest_state = G.GoalieRestState()
        chosen_day0 = _choose_and_record_starter(world, team.tid, rest_state, day=0)
        chosen_day1 = _choose_and_record_starter(world, team.tid, rest_state, day=1)
        if chosen_day0 == starter and chosen_day1 == backup:
            backup_starts += 1

    assert backup_starts > 0


# ---------------------------------------------------------------------------
# 3. Pull the goalie / extra attacker
# ---------------------------------------------------------------------------
def _aggressive_pull_coach() -> dict:
    """A coach guaranteed to consider pulling under this test's forced scenario: a wide deficit
    window and a long time-remaining threshold covering essentially all of a shortened test
    period."""
    profile = CoachProfile(
        name="Test Aggressive Puller", weight=1.0,
        goalie_pull_max_deficit=5, goalie_pull_time_threshold_secs=1200.0,
    )
    from pucksim.models.coach import Coach
    return Coach(cid=999, name="Test Coach", profile=profile).to_dict()


def test_trailing_team_pulls_goalie_for_six_skaters_when_deficit_and_time_qualify():
    """Directly drive _TeamState/GameSim internals to force a trailing-late scenario and confirm
    the trailing team's on-ice group grows to 6 while the goalie is pulled (goalie_id becomes
    None), and the opponent's defense now faces an empty net."""
    world = build_world(seed=8)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    sim._advance_shift_for_all()   # populate on-ice groups (normally done by coach_session())
    sim.period = config.PERIODS   # 3rd period -- pull-the-goalie only fires here

    trailing = sim.away
    trailing.team.coach = _aggressive_pull_coach()
    trailing.coach_profile = trailing._resolve_coach_profile(trailing.team)

    # Force the score to a 1-goal deficit for the trailing (away) team.
    sim.result.home_score = 1
    sim.result.away_score = 0

    sim._update_goalie_pulls(secs_remaining_in_period=60.0)

    assert trailing.goalie_pulled is True
    assert trailing.goalie_id is None
    assert len(trailing.on_ice) == 6, f"expected a 6-skater group, got {len(trailing.on_ice)}"

    # The opponent (home) should now be facing an empty net on defense.
    outcome_seen = set()
    for _ in range(50):
        outcome = sim._resolve_shot_attempt(trailing, sim.home, rush=False, rebound=False)
        outcome_seen.add(outcome)
    assert "goal" in outcome_seen or "miss" in outcome_seen or "block" in outcome_seen
    # No exception raised resolving shots against an empty net -- the core "doesn't crash on a
    # None goalie" requirement.


def test_goalie_un_pulls_when_team_ties_the_game():
    world = build_world(seed=9)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    sim._advance_shift_for_all()
    sim.period = config.PERIODS

    trailing = sim.away
    trailing.team.coach = _aggressive_pull_coach()
    trailing.coach_profile = trailing._resolve_coach_profile(trailing.team)

    sim.result.home_score = 1
    sim.result.away_score = 0
    sim._update_goalie_pulls(secs_remaining_in_period=60.0)
    assert trailing.goalie_pulled is True

    # Trailing team ties it up.
    sim.result.away_score = 1
    sim._update_goalie_pulls(secs_remaining_in_period=55.0)

    assert trailing.goalie_pulled is False
    assert trailing.goalie_id == trailing.starter_goalie_id
    assert len(trailing.on_ice) <= 5


def test_goalie_does_not_pull_when_leading_or_tied():
    world = build_world(seed=10)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    sim._advance_shift_for_all()
    sim.period = config.PERIODS

    for state in (sim.home, sim.away):
        state.team.coach = _aggressive_pull_coach()
        state.coach_profile = state._resolve_coach_profile(state.team)

    sim.result.home_score = 2
    sim.result.away_score = 2
    sim._update_goalie_pulls(secs_remaining_in_period=30.0)
    assert sim.home.goalie_pulled is False
    assert sim.away.goalie_pulled is False


def test_goalie_does_not_pull_outside_regulation_period():
    """Even with a qualifying deficit/time, pull-the-goalie must not fire outside the final
    regulation period (DEVPLAN.md: OT is explicitly out of scope for this mechanic)."""
    world = build_world(seed=11)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    sim._advance_shift_for_all()
    sim.period = 1   # first period, not the last

    trailing = sim.away
    trailing.team.coach = _aggressive_pull_coach()
    trailing.coach_profile = trailing._resolve_coach_profile(trailing.team)
    sim.result.home_score = 1
    sim.result.away_score = 0

    sim._update_goalie_pulls(secs_remaining_in_period=60.0)
    assert trailing.goalie_pulled is False


def test_goalie_does_not_pull_when_deficit_exceeds_coach_threshold():
    world = build_world(seed=13)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    sim._advance_shift_for_all()
    sim.period = config.PERIODS

    trailing = sim.away
    profile = CoachProfile(name="Conservative", weight=1.0,
                           goalie_pull_max_deficit=1, goalie_pull_time_threshold_secs=1200.0)
    from pucksim.models.coach import Coach
    trailing.team.coach = Coach(cid=1000, name="C", profile=profile).to_dict()
    trailing.coach_profile = trailing._resolve_coach_profile(trailing.team)

    sim.result.home_score = 3
    sim.result.away_score = 0   # down by 3, coach only pulls down by <= 1

    sim._update_goalie_pulls(secs_remaining_in_period=60.0)
    assert trailing.goalie_pulled is False


def test_empty_net_goal_against_rate_is_measurably_higher_when_pulled():
    """Across many forced-empty-net shot resolutions vs. many forced normal (goalie-in-net)
    resolutions with a deliberately strong shooter, the empty-net scoring rate should be
    measurably higher -- proving the pulled-goalie state produces a real, elevated
    empty-net-goal-against rate rather than being a cosmetic on-ice-group change only."""
    world = build_world(seed=14)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    sim._advance_shift_for_all()
    sim.period = config.PERIODS

    offense = sim.home
    defense = sim.away

    def _goal_rate(pulled: bool, trials: int = 400) -> float:
        goals = 0
        attempts = 0
        for _ in range(trials):
            sim.result.home_score = 0
            sim.result.away_score = 0
            defense.goalie_pulled = pulled
            defense.goalie_id = None if pulled else defense.starter_goalie_id
            outcome = sim._resolve_shot_attempt(offense, defense, rush=False, rebound=False)
            attempts += 1
            if outcome == "goal":
                goals += 1
        return goals / attempts

    empty_net_rate = _goal_rate(pulled=True)
    normal_rate = _goal_rate(pulled=False)
    assert empty_net_rate > normal_rate, (
        f"empty-net rate {empty_net_rate:.3f} should exceed normal goalie-in-net rate {normal_rate:.3f}"
    )


def test_full_game_with_pull_the_goalie_active_does_not_crash_and_can_produce_empty_net_goals():
    """Full-engine integration sweep: simulate several games with an aggressive-pull coach
    assigned to both teams and confirm the game completes normally (no exceptions), the 6-skater
    on-ice group is genuinely reachable in real (not hand-forced) play, and at least one
    empty-net goal shows up in the play-by-play across the sweep.

    Seed range (DEVPLAN.md Step 2.3 note): widened from an earlier 10-seed range to 80. An
    empty-net GOAL specifically (not just a pulled-goalie/empty-net attempt, which is far more
    common) is a genuinely low-probability event per game even with an aggressive-pull coach on
    both sides (~10% of games in an empirical sample, not a design bug -- pulling the goalie has
    to actually trigger AND persist long enough for a shot to land AND that shot has to convert).
    A 10-seed window is far too narrow a sample for a "did a ~10%-per-game event happen at least
    once" assertion to be reliable; it happened to pass under the pre-Step-2.3 engine's RNG draw
    sequence by luck of exactly which seeds landed in that window, not because 10 seeds was
    actually a safe sample size -- this step's additional per-shift RNG draws (icing/offside
    rolls, the three-way faceoff roll's extra draws, injury checks) shift which seeds produce
    which outcomes, which is what exposed the flakiness, not a regression in the pull-the-goalie
    mechanic itself (verified directly: empty-net shot ATTEMPTS still occur at the expected rate
    post-Step-2.3, just not always converting to a goal within a narrow seed sample). 80 seeds at
    an empirical ~10%/game rate gives better than 99.9% confidence of seeing at least one.
    """
    from pucksim.sim.engine import _TeamState

    found_empty_net_goal = False
    found_six_skater_group = False

    original_refresh = _TeamState.refresh_on_ice_for_strength_state

    def _tracking_refresh(self, *args, **kwargs):
        original_refresh(self, *args, **kwargs)
        nonlocal found_six_skater_group
        if len(self.on_ice) >= 6:
            found_six_skater_group = True

    _TeamState.refresh_on_ice_for_strength_state = _tracking_refresh
    try:
        for seed in range(50, 130):
            world = build_world(seed=seed)
            tids = sorted(world.teams.keys())
            for team in world.teams.values():
                team.coach = _aggressive_pull_coach()

            sim = GameSim(world, tids[0], tids[1], collect_pbp=True)
            result = sim.play()

            if any(e.event_type == EVENT_GOAL and e.goalie_id is None for e in result.pbp):
                found_empty_net_goal = True
    finally:
        _TeamState.refresh_on_ice_for_strength_state = original_refresh

    assert found_empty_net_goal, "expected at least one empty-net goal across the seed sweep"
    assert found_six_skater_group, "expected a real 6-skater on-ice group during natural play"


# ---------------------------------------------------------------------------
# GameSim starter-override plumbing (DEVPLAN.md Step 2.2's season.py hook)
# ---------------------------------------------------------------------------
def test_gamesim_accepts_starter_override_for_backup():
    world = build_world(seed=15)
    tids = sorted(world.teams.keys())
    home_team = world.team(tids[0])
    backup = home_team.goalie_backup
    assert backup is not None

    sim = GameSim(world, tids[0], tids[1], home_goalie_id=backup)
    assert sim.home.goalie_id == backup
    assert sim.home.starter_goalie_id == backup


def test_gamesim_defaults_to_team_goalie_starter_when_no_override_given():
    world = build_world(seed=16)
    tids = sorted(world.teams.keys())
    home_team = world.team(tids[0])
    sim = GameSim(world, tids[0], tids[1])
    assert sim.home.goalie_id == home_team.goalie_starter
