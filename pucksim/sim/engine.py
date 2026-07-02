"""Shift/event-based game simulation (DEVPLAN.md Step 2.1 extends MVP's 5v5-only scope).

The engine resolves one shift at a time: faceoff (period start / after a goal only -- no
icing/offside stoppages yet, that's Step 2.3) -> zone entry -> a sequence of shot
attempts/rebounds/turnovers -> a stoppage (goal, or a drawn penalty) or the shift clock running
out -> line change. Skaters and the goalie tire as shifts accumulate; the realization model
(``pucksim.sim.ratings``: morale x chemistry x composure) scales the skill *gap* between
opposing ratings on every shot attempt, the same mechanism HoopR uses for shot/defense
resolution. Coach ``shot_volume``/``shot_quality_bias`` (models/coach.py's ``CoachProfile``)
modulate a team's shot-attempt frequency/quality for their shifts on offense.

Strength state (DEVPLAN.md Step 2.1): every shift now rolls for a drawn penalty (per team, via
``pucksim.sim.special_teams``'s provisional discipline/coach-aggression-scaled probability
model) and ticks any already-active penalty timers. The engine tracks strength state as real,
shared game state -- ``self.strength`` (a ``special_teams.StrengthStateMachine``) -- rather than
the MVP's hardcoded ``config.STRENGTH_5V5`` literal on every logged shot. Both teams' on-ice
groups are rebuilt from the correct pool (normal line/pair rotation at 5v5, PP/PK unit
otherwise -- ``special_teams.on_ice_group_for_state``) whenever the strength state changes
(a penalty drawn, or a penalty expiring mid-shift). The real-NHL "a shorthanded goal ends a
non-fighting minor penalty early" rule is implemented in ``_score_goal``.

Goalies as a full system (DEVPLAN.md Step 2.2): ``GameSim`` accepts optional
``home_goalie_id``/``away_goalie_id`` overrides so a caller (``sim/season.py``'s rest-based
rotation, via ``sim/goalies.py``'s ``choose_starting_goalie``) can start the backup instead of
``Team.goalie_starter`` for a given game -- see ``_TeamState.__init__``. Two goalie-specific
mechanics live here:

- **Hot hand** (``_TeamState.goalie_hot_hand``, a small rolling streak counter incremented per
  consecutive save and reset on a goal against) is read through
  ``ratings.hot_hand_boost(streak) -> fraction`` and applied ONLY via a gap-closing rescale of
  ``def_real`` (``effective_def_real = def_real + (1.0 - def_real) * fraction``) -- see
  ``_resolve_shot_attempt`` and ``ratings.py``'s "no upweighting" docstring for why this
  replaced an earlier additive nudge that could push a save probability above what a goalie's
  rating alone would ever produce.
- **Pull the goalie** (``_maybe_pull_goalie``/``_maybe_return_goalie``, checked once per shift):
  when a team is trailing by at most ``coach_profile.goalie_pull_max_deficit`` goals with at
  most ``coach_profile.goalie_pull_time_threshold_secs`` left in REGULATION (never during the
  OT placeholder -- an empty-net pull is a score-driven regulation decision), that team's
  goalie is pulled for a 6th skater on their own offensive on-ice group; the opponent then faces
  an empty net (``_resolve_shot_attempt`` already handled ``goalie is None`` defensively before
  this step -- pulling makes that path a real, common occurrence instead of a never-hit guard).
  The goalie returns immediately if the trailing team ties/takes the lead, if the deficit grows
  past the threshold again, or at the period buzzer.

Mirrors HoopR's ``hoopsim/sim/engine.py`` control-flow shape directly: a ``_TeamState`` inner
class tracking on-ice personnel/fatigue/ice-time, a ``GameSim`` class, and the resumable-generator
pattern (``coach_session()`` yields a decision-point view at every natural stoppage -- here, after
every goal -- resumable via ``.send(orders)``; ``play()`` drives it synchronously via a bare
``next()``/``.send(None)`` loop). No live-coaching consumer exists yet (that's a later web-layer
feature per DESIGN.md), but the scaffolding is built now so that consumer never needs an engine
rewrite -- it will plug in by supplying real orders through the same generator seam.

Scope constraints this step still does NOT add (do not add scope here -- see DEVPLAN.md's
explicit exclusions for later steps):
- Faceoffs still only at period start and immediately after a goal -- penalty-stoppage
  faceoffs (i.e. actually gating post-penalty possession on a fresh faceoff rather than the
  shift loop's existing random-attacker-flip abstraction) are Step 2.3 scope; this step's
  penalty engine changes strength state and on-ice personnel, not the faceoff/stoppage model.
- OT is still a clearly-commented provisional placeholder (simplified 5v5 sudden death, one
  extra period, unresolved ties left as ``went_ot=True`` with no shootout) -- real 3-on-3/
  shootout resolution is Step 2.6. Penalties CAN still be drawn during this OT placeholder
  (the penalty engine doesn't gate on period type), which is a reasonable simplification given
  real 3-on-3 OT is Step 2.6 scope anyway. Goalie-pull is explicitly regulation-only (see above)
  so it does not interact with this placeholder.
- Fatigue still resets every game; it never persists across games (still no cross-game fatigue
  carryover model -- out of scope for this step too).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pucksim import config
from pucksim.models.coach import Coach, CoachProfile
from pucksim.models.player import Player
from pucksim.models.team import Team, lineup_familiarity_secs
from pucksim.models.world import World
from pucksim.sim import ratings as R
from pucksim.sim import special_teams as ST
from pucksim.sim.boxscore import (
    EVENT_FACEOFF,
    EVENT_GAME_END,
    EVENT_GOAL,
    EVENT_PENALTY,
    EVENT_PERIOD_END,
    EVENT_SHOT,
    SHOT_OUTCOME_BLOCK,
    SHOT_OUTCOME_GOAL,
    SHOT_OUTCOME_MISS,
    SHOT_OUTCOME_SAVE,
    SHOT_TYPES,
    GameResult,
    PBPEvent,
)

# ---------------------------------------------------------------------------
# Tunables -- PROVISIONAL/first-pass, same framing as every other unresolved constant in this
# codebase (config.py's own development/injury placeholders, gen/leaguegen.py's age/overall
# distributions, etc.). Real balancing needs actual simulated-season data, which doesn't exist
# until this step ships.
# ---------------------------------------------------------------------------
BASE_SHOT_ATTEMPTS_PER_SHIFT = 0.9    # league-average expected shot attempts per shift, per team
FACEOFF_WIN_BASE = 0.50               # coin-flip baseline before rating gap / realization
FATIGUE_GAIN_PER_SEC = 0.028          # fatigue points gained per second of shift ice time
FATIGUE_RECOVER_PER_SEC = 0.05        # fatigue points recovered per second on the bench

# Goalie "hot hand" streak-tracking cadence (DEVPLAN.md Step 2.2). ``goalie_hot_hand`` is a
# small rolling counter (see _TeamState), NOT a probability/fraction itself -- it's fed through
# ``ratings.hot_hand_boost()`` to get a bounded [0, HOT_HAND_MAX_FRACTION] fraction, which then
# closes part of the gap between def_real and 1.0 (see _resolve_shot_attempt). This replaced an
# earlier additive nudge applied directly to save_p -- see ratings.py's "no upweighting" note on
# hot_hand_boost() for exactly why that was a bug, not a design choice, and must not come back.
GOAL_HOT_HAND_STREAK_INCREMENT = 1.0   # streak credit gained per consecutive save
GOAL_HOT_HAND_STREAK_MAX = 12.0        # streak counter ceiling (well past hot_hand_boost's own
                                        # saturation point, just a sanity bound on the counter)

REBOUND_CHANCE_BASE = 0.22            # probability an unconverted on-goal shot produces a rebound
SHIFT_SECONDS_JITTER = 8.0            # +/- gaussian spread around config.SHIFT_SECONDS_TARGET

# ---------------------------------------------------------------------------
# Pull-the-goalie / extra-attacker tunables (DEVPLAN.md Step 2.2). The actual trigger thresholds
# (deficit/time-remaining) come from each team's own CoachProfile
# (``goalie_pull_max_deficit``/``goalie_pull_time_threshold_secs``, models/coach.py) -- these are
# just the mechanic-level constants that aren't coach-specific.
# ---------------------------------------------------------------------------
EMPTY_NET_GOAL_BASE_P = 0.55   # a shot that reaches an empty net (no goalie to resolve a save
                               # against) scores at a high but not-quite-certain rate per
                               # attempt -- misses/blocks still happen even into an empty net.
PULL_RETURN_LEAD_SWING = 1     # if the pulled team's deficit ever WORSENS by this many goals
                               # relative to when they pulled, put the goalie back (a blown pull
                               # attempt shouldn't compound into an even worse empty-net
                               # disaster) -- see _maybe_return_goalie.

# Zone/shot-type pools (DEVPLAN.md: "invent a reasonable small set"). Zone strings double as a
# coarse shot-quality signal: danger zones first, low-danger zones last.
ZONES_HIGH_DANGER = ("slot", "crease")
ZONES_MID_DANGER = ("high_slot", "circle")
ZONES_LOW_DANGER = ("point", "bad_angle")
ALL_ZONES = ZONES_HIGH_DANGER + ZONES_MID_DANGER + ZONES_LOW_DANGER

_ZONE_QUALITY = {
    "slot": 0.90, "crease": 0.95,
    "high_slot": 0.60, "circle": 0.55,
    "point": 0.20, "bad_angle": 0.15,
}
_SHOT_TYPE_QUALITY = {
    "one_timer": 0.75, "tip": 0.80, "wrist": 0.55, "backhand": 0.45, "slap": 0.35,
}


def _weighted_index(rng, weights: List[float]) -> int:
    return rng.choices(range(len(weights)), weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# _TeamState -- one side's in-game personnel/fatigue/ice-time bookkeeping.
# ---------------------------------------------------------------------------
class _TeamState:
    """Mirrors HoopR's ``_TeamState``: per-team in-game state that doesn't belong on the shared
    ``Team``/``Player`` models (those are season-persistent; this is scoped to one game).
    """

    def __init__(self, world: World, team: Team, is_home: bool, *,
                 starter_override: Optional[int] = None) -> None:
        self.team = team
        self.tid = team.tid
        self.abbrev = team.abbrev
        self.is_home = is_home
        self.players: Dict[int, Player] = {pid: world.player(pid) for pid in team.roster}

        # Round-robin rotation pointers into team.lines / team.pairs (MVP: no line-juggling AI,
        # just a fixed deterministic rotation so ice time distributes across the whole roster --
        # DEVPLAN.md's explicit instruction).
        self._line_idx = 0
        self._pair_idx = 0
        self.on_ice: List[int] = []           # 5 (or 6, pulled-goalie) skaters, current shift
        self._normal_group: List[int] = []    # this shift's normal-rotation group, cached so
                                               # mid-shift strength-state changes can rebuild
                                               # on_ice without re-advancing the round-robin
                                               # pointer (see advance_shift's docstring)

        # Starting goalie: defaults to Team.goalie_starter, but a caller (sim/season.py's
        # rest-based rotation, via sim/goalies.py's choose_starting_goalie) can override this to
        # start the backup instead for a given game (DEVPLAN.md Step 2.2). ``starter_goalie_id``
        # remembers the ORIGINAL starting goalie for this game (never changes once play begins)
        # so pull/un-pull logic always restores the right goalie, independent of which one was
        # actually chosen to start.
        self.starter_goalie_id: Optional[int] = (
            starter_override if starter_override is not None else team.goalie_starter
        )
        self.goalie_id: Optional[int] = self.starter_goalie_id

        # Fatigue (0..100, resets every game -- persistence across games is out of this step's
        # scope; rest-based starter ROTATION is handled at the season-orchestration level, see
        # sim/goalies.py, but in-game fatigue itself still doesn't carry across games).
        self.fatigue: Dict[int, float] = {pid: 0.0 for pid in team.roster}
        self.shift_count: Dict[int, int] = {pid: 0 for pid in team.roster}

        # Live coach profile, reconstructed once at game start (models/coach.py's documented
        # pattern: Team.coach is a serialized dict, not a live CoachProfile).
        self.coach_profile: CoachProfile = self._resolve_coach_profile(team)

        self.cache: Optional[R.OnIceCache] = None

        # Goalie "hot hand": a small rolling streak counter, mean-reverting (built up by
        # consecutive saves, reset by a goal against), reset at game start. Reinterpreted in
        # this step (DEVPLAN.md Step 2.2) from a direct additive save_p nudge into a streak value
        # consumed exclusively through ratings.hot_hand_boost()'s gap-closing fraction -- see
        # this module's docstring and ratings.py's "no upweighting" note. Never applied to the
        # OTHER team's goalie -- each team's own goalie has independent streak state.
        self.goalie_hot_hand: float = 0.0

        # Pull-the-goalie state (DEVPLAN.md Step 2.2). ``goalie_pulled`` is this team's own
        # current pulled/not-pulled status; ``pulled_at_deficit`` remembers the goal deficit at
        # the moment of pulling so _maybe_return_goalie can detect "the deficit got WORSE since
        # we pulled" (see PULL_RETURN_LEAD_SWING) without re-deriving it from scratch.
        self.goalie_pulled: bool = False
        self.pulled_at_deficit: Optional[int] = None

    @staticmethod
    def _resolve_coach_profile(team: Team) -> CoachProfile:
        """Reconstruct the team's live CoachProfile from its serialized dict (models/coach.py:
        ``Coach.from_dict(team.coach).profile``). Falls back to BALANCED for a team with no coach
        assigned yet (shouldn't happen post-leaguegen, but defensive per coach.py's own
        never-crash-on-bad-data philosophy)."""
        if team.coach is None:
            return Coach.from_dict({"cid": team.tid, "archetype": "Balanced"}).profile
        return Coach.from_dict(team.coach).profile

    # -- on-ice group assembly ------------------------------------------------
    def _next_normal_group(self) -> List[int]:
        """Round-robin to the next forward line + D pair (line 0->1->2->3->0.., pair
        0->1->2->0..): the normal-rotation on-ice group, ignoring strength state. Plain
        ``List[int]`` built by concatenating a forward line + a D pair (DESIGN.md point 1 --
        never a hard Line/Pair object). Advances the rotation pointers as a side effect --
        called exactly once per real shift boundary (``advance_shift``, below); mid-shift
        strength-state changes must reuse ``self._normal_group`` via
        ``refresh_on_ice_for_strength_state`` instead of calling this again, or the round-robin
        pointer would skip an extra line/pair every time a penalty is drawn or expires mid-shift
        (a real bug this split specifically guards against).
        """
        lines = self.team.lines
        pairs = self.team.pairs
        line = lines[self._line_idx % len(lines)] if lines else []
        pair = pairs[self._pair_idx % len(pairs)] if pairs else []
        group = list(line) + list(pair)
        self._line_idx = (self._line_idx + 1) % max(1, len(lines))
        self._pair_idx = (self._pair_idx + 1) % max(1, len(pairs))
        return group

    def advance_shift(self, strength_state: Optional[str] = None,
                       skaters_needed: int = 5, penalized_ids: Optional[List[int]] = None) -> None:
        """Advance the normal round-robin rotation to the NEXT line/pair and set the on-ice
        group for the upcoming shift. Call this exactly once per real shift boundary (game
        start, and once at the end of every ``_play_shift``) -- NOT for a mid-shift
        strength-state change (a penalty drawn or expiring); use
        ``refresh_on_ice_for_strength_state`` for that instead, which reuses this shift's
        already-advanced normal group rather than pulling a new one.

        At ``STRENGTH_5V5`` (the default, ``strength_state=None`` behaves identically to the
        MVP's original 5v5-only behavior) the on-ice group IS the next normal-rotation group.
        At a PP/PK/5v3 strength state, the normal rotation still advances underneath (so ice
        time keeps distributing fairly across the whole roster once strength returns to even),
        but the actual on-ice group for THIS shift is swapped to the team's PP/PK unit via
        ``special_teams.on_ice_group_for_state`` -- see that function's docstring for the
        fallback behavior when a unit is undersized/missing.
        """
        self._normal_group = self._next_normal_group()
        self.refresh_on_ice_for_strength_state(strength_state, skaters_needed, penalized_ids)

    def refresh_on_ice_for_strength_state(self, strength_state: Optional[str] = None,
                                           skaters_needed: int = 5,
                                           penalized_ids: Optional[List[int]] = None) -> None:
        """Rebuild the on-ice group for the CURRENT shift's strength state, reusing this shift's
        already-computed normal-rotation group (``self._normal_group``) rather than advancing
        the round-robin pointer again. Safe to call any number of times within a single shift
        (a penalty drawn, then expiring, then another drawn, etc.) without distorting the
        normal-rotation cadence.

        Pull-the-goalie (DEVPLAN.md Step 2.2): if ``self.goalie_pulled`` is set, this team fields
        one extra skater beyond the normal ``skaters_needed`` count for their OWN offensive
        on-ice group -- a 6th body (the "extra attacker") spliced onto the end of the on-ice
        list. This is exactly the "on-ice group is a plain list, not a hard-coded Line/Pair
        object" flexibility DESIGN.md's Step 1.7 called out: a 6-skater group needs no schema
        change, just one more id appended to the same ``List[int]`` every other consumer already
        expects. The extra skater is the best-fit forward not already on the ice this shift
        (falls back to any rostered skater not already included, never crashes on a thin bench).
        """
        normal_group = self._normal_group
        state = strength_state or config.STRENGTH_5V5
        if state == config.STRENGTH_5V5:
            self.on_ice = normal_group
        else:
            self.on_ice = ST.on_ice_group_for_state(
                self.team, state, normal_group=normal_group,
                skaters_needed=skaters_needed, penalized_ids=penalized_ids,
            )
        if self.goalie_pulled:
            self.on_ice = self._with_extra_attacker(self.on_ice)
        for pid in self.on_ice:
            self.shift_count[pid] = self.shift_count.get(pid, 0) + 1
        self._rebuild_cache()

    def _with_extra_attacker(self, group: List[int]) -> List[int]:
        """Append one extra skater to ``group`` for a pulled-goalie 6-attacker shift (DEVPLAN.md
        Step 2.2). Prefers the highest-``overall`` skater on the roster not already in ``group``
        (a coach sends out the best available extra body, not a random one); falls back to
        leaving ``group`` unchanged if literally every rostered skater is already on the ice
        (an extreme-injury/thin-bench edge case -- never crash, just field 5 instead of 6)."""
        on_ice_set = set(group)
        candidates = [pid for pid in self.team.roster
                      if pid not in on_ice_set and pid != self.goalie_id and pid in self.players]
        if not candidates:
            return group
        extra = max(candidates, key=lambda pid: self.players[pid].overall)
        return list(group) + [extra]

    def _rebuild_cache(self) -> None:
        on_ice_players = [self.players[pid] for pid in self.on_ice if pid in self.players]
        # Familiarity realization over the on-ice group's average pairwise shared ice time
        # (team.py's lineup_familiarity_secs / pair_key, exactly as team.py documents for this
        # purpose).
        secs_list = []
        for i in range(len(self.on_ice)):
            for j in range(i + 1, len(self.on_ice)):
                secs_list.append(lineup_familiarity_secs(self.team, self.on_ice[i], self.on_ice[j]))
        avg_secs = sum(secs_list) / len(secs_list) if secs_list else 0.0
        chem_real = R.familiarity_realization(avg_secs)
        self.cache = R.build_on_ice_cache(on_ice_players, chem_real=chem_real)

    def goalie(self) -> Optional[Player]:
        return self.players.get(self.goalie_id) if self.goalie_id is not None else None

    def avg_fatigue(self) -> float:
        if not self.on_ice:
            return 0.0
        return sum(self.fatigue.get(pid, 0.0) for pid in self.on_ice) / len(self.on_ice)


# ---------------------------------------------------------------------------
# GameSim
# ---------------------------------------------------------------------------
class GameSim:
    """Simulates one game between two teams drawn from ``world``.

    Usage: ``GameSim(world, home_tid, away_tid).play()`` for headless simulation (this step's
    actual use case). The resumable ``coach_session()`` generator is exposed for a future
    live-coaching consumer (web layer, not built yet) -- ``play()`` is just a synchronous driver
    over it with no real decisions made.

    ``home_goalie_id``/``away_goalie_id`` (DEVPLAN.md Step 2.2): optional per-game starter
    overrides. ``_TeamState.__init__`` previously always read ``team.goalie_starter`` directly;
    a caller that has already decided (via ``sim/goalies.py``'s rest-based
    ``choose_starting_goalie``) that the BACKUP should start this particular game passes that
    pid here instead. Defaults to ``None`` (falls back to ``team.goalie_starter``, i.e. identical
    behavior to before this step for any caller that doesn't opt in).
    """

    def __init__(self, world: World, home_tid: int, away_tid: int, *,
                 collect_pbp: bool = False,
                 home_goalie_id: Optional[int] = None,
                 away_goalie_id: Optional[int] = None) -> None:
        self.world = world
        self.rng = world.rng
        self.collect_pbp = collect_pbp
        self.home = _TeamState(world, world.team(home_tid), is_home=True,
                               starter_override=home_goalie_id)
        self.away = _TeamState(world, world.team(away_tid), is_home=False,
                               starter_override=away_goalie_id)
        self.result = GameResult(home_tid=home_tid, away_tid=away_tid)
        self.period = 1
        self.game_secs = 0.0     # elapsed game time, monotonically increasing across periods/OT
        self._is_ot = False

        # Strength-state state machine (DEVPLAN.md Step 2.1): shared game state, not per-team --
        # both teams are always in the same state, just from opposite perspectives (see
        # special_teams.StrengthStateMachine's docstring).
        self.strength = ST.StrengthStateMachine(home_tid=home_tid, away_tid=away_tid)

    # -- public API -----------------------------------------------------------
    def play(self) -> GameResult:
        """Play the whole game, driving the resumable generator to completion with no real
        decisions (headless simulation). Mirrors HoopR's ``play()``: a bare ``next()``/
        ``.send(None)`` loop that ignores every yielded decision-point view."""
        driver = self.coach_session()
        try:
            next(driver)
            while True:
                driver.send(None)
        except StopIteration:
            pass
        self._finalize()
        return self.result

    def coach_session(self):
        """A generator driving the game that suspends at every natural stoppage point (currently:
        immediately after a goal is scored). Pump it with ``next()``/``gen.send(orders)``; each
        yielded value is a lightweight decision-point view (currently just ``self`` -- there is no
        real decision to make yet, since penalties/goalie-pull/line-juggling are all later steps).
        ``orders`` sent back in are accepted but ignored for now. This is the exact seam a future
        live-coaching feature (call timeout / pull goalie / set forecheck / juggle lines, per
        DESIGN.md) will resume through without an engine rewrite.
        """
        self._advance_shift_for_all()

        for p in range(1, config.PERIODS + 1):
            self.period = p
            yield from self._play_period(config.PERIOD_SECONDS, is_regulation=True)

        # -- provisional OT placeholder -----------------------------------
        # DEVPLAN.md: MVP needs "a clearly-commented provisional tie-break or simple sudden-death
        # placeholder" since real OT (3-on-3) / shootout resolution is v1 scope (Step 2.6). This
        # runs ONE extra simplified period using the same 5v5 shift logic (not 3-on-3 -- that
        # strength state doesn't exist until Step 2.1) until either team scores or the period time
        # runs out, in which case the game is left as an unresolved tie with went_ot=True and
        # went_so always False (shootouts don't exist yet). Real NHL OT/SO resolution replaces this
        # whole block in Step 2.6. is_regulation=False here: pull-the-goalie (Step 2.2) is an
        # explicit regulation-only, score-driven mechanic -- it never triggers (or stays active)
        # once the game reaches this placeholder period.
        if self.result.home_score == self.result.away_score:
            self._is_ot = True
            self.result.went_ot = True
            self.period += 1
            yield from self._play_period(config.OT_SECONDS_REGULAR_SEASON, sudden_death=True,
                                          is_regulation=False)

    # -- period / shift loop ---------------------------------------------------
    def _play_period(self, length_secs: float, sudden_death: bool = False, is_regulation: bool = True):
        """Run shifts until ``length_secs`` of clock has elapsed (or, in sudden death, until a goal
        is scored). A generator: yields a decision-point view immediately after any goal.

        ``is_regulation`` (DEVPLAN.md Step 2.2): pull-the-goalie is a regulation-only mechanic
        (see ``_maybe_pull_goalie``) -- the provisional OT placeholder passes ``False`` so a
        goalie is never pulled/kept-pulled once the game reaches the (still-provisional, Step
        2.6 territory) OT period.
        """
        clock = length_secs
        # Faceoff at the start of every period (MVP scope: faceoffs only at period start / after a
        # goal -- no icing/offside/penalty stoppages yet, that's Step 2.3).
        self._log_faceoff()

        while clock > 0:
            shift_secs = max(15.0, self.rng.gauss(config.SHIFT_SECONDS_TARGET, SHIFT_SECONDS_JITTER))
            shift_secs = min(shift_secs, clock)
            if is_regulation:
                self._update_goalie_pulls(clock)
            goal_scored = yield from self._play_shift(shift_secs)
            clock -= shift_secs
            self.game_secs += shift_secs
            if goal_scored:
                if sudden_death:
                    clock = 0.0   # sudden death ends immediately on a goal
                    break
                # A goal just changed the score state -- re-check goalie-pull status right away
                # (DEVPLAN.md Step 2.2: "un-pull if the trailing team scores") rather than waiting
                # for next shift's regular _update_goalie_pulls check, so a team that ties/takes
                # the lead doesn't play even one extra shift 6-on-5 by mistake.
                if is_regulation:
                    self._update_goalie_pulls(clock)
                # Faceoff at center ice restarts play after a goal (MVP scope: the only other
                # legal faceoff trigger besides period start).
                if clock > 0:
                    self._log_faceoff()

        # Regulation ends -- any pulled goalie returns for the next period/OT (a coach doesn't
        # carry an empty net into intermission; see _maybe_return_goalie's time-based fallback).
        if is_regulation:
            for state in (self.home, self.away):
                if state.goalie_pulled:
                    self._return_goalie(state)

        self._log(EVENT_PERIOD_END, f"End of period {self.period}")

    def _play_shift(self, shift_secs: float):
        """Resolve one shift: check for a drawn penalty, possession from the faceoff/rush, a
        sequence of shot attempts (ticking the strength-state clock and reacting to mid-shift
        strength-state expiry between attempts) until the shift clock elapses or a goal is
        scored, then apply ice-time/fatigue and rotate both teams' on-ice groups for next shift.
        Returns True (via StopIteration value on `yield from` callers, or just the return value
        here) if a goal was scored this shift. A generator only insofar as it yields at a goal
        stoppage (see coach_session's docstring) -- for a shift with no goal it never yields."""
        self._check_for_penalties()

        offense, defense = (self.home, self.away) if self.rng.chance(0.5) else (self.away, self.home)

        elapsed = 0.0
        goal_scored = False
        rush = True       # the first shot attempt of a shift is off the initial entry
        rebound = False   # set True for the attempt immediately following an unconverted on-goal shot
        while elapsed < shift_secs:
            attempt_gap = self._shot_attempt_interval(offense)
            elapsed += attempt_gap
            if elapsed >= shift_secs:
                break

            # Advance the strength-state clock by the interval that just elapsed (penalty
            # timers tick in real game-seconds, independent of shot-attempt cadence) and react
            # if a penalty expired mid-shift -- on-ice groups need rebuilding immediately so the
            # very next attempt reflects the correct personnel/strength state.
            if self._advance_penalty_clock(attempt_gap):
                offense, defense = self._reorient_after_strength_change(offense, defense)

            outcome = self._resolve_shot_attempt(offense, defense, rush=rush, rebound=rebound)
            rush = False
            rebound = False
            if outcome == SHOT_OUTCOME_GOAL:
                goal_scored = True
                yield self._decision_view()
                break
            if outcome == "rebound":
                # Same team keeps the puck for an immediate extra look (DEVPLAN.md's rebound flag
                # requirement) -- no possession flip, next attempt is flagged as a rebound.
                rebound = True
                continue
            # Otherwise possession may flip for the remainder of the shift (a turnover-ish flow
            # abstraction -- MVP doesn't model discrete turnovers/zone-entries as separate events,
            # per this step's scope).
            if self.rng.chance(0.5):
                offense, defense = defense, offense

        self._apply_ice_time(shift_secs)
        self._advance_shift_for_all()
        return goal_scored

    def _shot_attempt_interval(self, offense: _TeamState) -> float:
        """Seconds until the next shot attempt, scaled by the offense's coach shot_volume AND
        the offense's current strength state (a PP boosts attempt volume, a PK suppresses it --
        DEVPLAN.md Step 2.1)."""
        mult = R.shot_volume_multiplier(offense.coach_profile.shot_volume)
        state_mult = R.strength_state_shot_volume_multiplier(self.strength.state_for(offense.tid))
        mean_interval = config.SHIFT_SECONDS_TARGET / (BASE_SHOT_ATTEMPTS_PER_SHIFT * mult * state_mult)
        return max(2.0, self.rng.gauss(mean_interval, mean_interval * 0.35))

    # -- pull the goalie / extra attacker (DEVPLAN.md Step 2.2) ------------------
    def _update_goalie_pulls(self, secs_remaining_in_period: float) -> None:
        """Checked once per shift (regulation periods only -- see ``_play_period``'s
        ``is_regulation`` gate): decide whether either team should pull its goalie for an extra
        attacker, or bring an already-pulled goalie back.

        Only the LAST period of regulation matters for a real empty-net pull (no NHL coach pulls
        the goalie in the first period down a goal), so this is a no-op outside that period --
        cheap to check unconditionally every shift rather than threading a separate "are we in
        the third" flag through the caller.
        """
        if self.period != config.PERIODS:
            return
        for state, other in ((self.home, self.away), (self.away, self.home)):
            if state.goalie_pulled:
                self._maybe_return_goalie(state, other, secs_remaining_in_period)
            else:
                self._maybe_pull_goalie(state, other, secs_remaining_in_period)

    def _deficit_for(self, state: _TeamState, other: _TeamState) -> int:
        """How many goals ``state`` currently trails by (0 if tied or leading) -- the "deficit"
        DEVPLAN.md's coach thresholds are expressed against."""
        my_score = self.result.home_score if state.is_home else self.result.away_score
        their_score = self.result.away_score if state.is_home else self.result.home_score
        return max(0, their_score - my_score)

    def _maybe_pull_goalie(self, state: _TeamState, other: _TeamState,
                           secs_remaining: float) -> None:
        """Pull ``state``'s goalie for a 6th attacker if they're trailing by no more than their
        own coach's ``goalie_pull_max_deficit`` with no more than
        ``goalie_pull_time_threshold_secs`` left in regulation (DEVPLAN.md Step 2.2, consuming
        ``CoachProfile`` fields that were defined back in Step 1.10 but unconsumed until now).
        A team that's tied or leading never pulls (deficit of 0 doesn't clear the "trailing"
        bar -- pulling the goalie only ever makes sense when behind)."""
        deficit = self._deficit_for(state, other)
        if deficit <= 0:
            return
        profile = state.coach_profile
        if (deficit <= profile.goalie_pull_max_deficit
                and secs_remaining <= profile.goalie_pull_time_threshold_secs):
            state.goalie_pulled = True
            state.pulled_at_deficit = deficit
            # goalie_id -> None: for shot-facing purposes this team's net is now empty (see
            # _resolve_shot_attempt's already-existing `goalie is None` handling, extended by
            # this step to resolve sensibly -- an empty net, not a crash). The player is not
            # removed from the roster/box score; ``starter_goalie_id`` retains who to restore on
            # an un-pull (see _return_goalie).
            state.goalie_id = None
            self._refresh_on_ice_for_all()

    def _maybe_return_goalie(self, state: _TeamState, other: _TeamState,
                             secs_remaining: float) -> None:
        """Return an already-pulled goalie if the situation that justified pulling him has
        resolved: the trailing team tied/took the lead (deficit <= 0), the deficit got
        meaningfully WORSE than when he was pulled (a blown extra-attacker gamble -- keep
        piling on an empty net rarely helps once the other team padded the lead further, see
        ``PULL_RETURN_LEAD_SWING``), or the period is basically over (a very-end-of-period
        fallback, since ``_play_period`` also force-returns any pulled goalie at the buzzer)."""
        deficit = self._deficit_for(state, other)
        if deficit <= 0:
            self._return_goalie(state)
            return
        pulled_at = state.pulled_at_deficit if state.pulled_at_deficit is not None else deficit
        if deficit - pulled_at >= PULL_RETURN_LEAD_SWING:
            self._return_goalie(state)
            return
        if secs_remaining <= 1.0:
            self._return_goalie(state)

    def _return_goalie(self, state: _TeamState) -> None:
        """Put ``state``'s original starting goalie back in net and rebuild on-ice groups so the
        6-skater extra-attacker group reverts to a normal 5 immediately."""
        state.goalie_pulled = False
        state.pulled_at_deficit = None
        state.goalie_id = state.starter_goalie_id
        self._refresh_on_ice_for_all()

    # -- penalties / strength state ---------------------------------------------
    def _check_for_penalties(self) -> None:
        """Roll both teams' current on-ice group for a drawn penalty at the start of a shift
        (special_teams.roll_for_penalty, scaled by discipline + coach aggression). At most one
        penalty per team per shift is checked here -- a simple, clearly-provisional cadence
        (DEVPLAN.md flags exact tuning as an open item), not a per-attempt penalty check."""
        for state in (self.home, self.away):
            on_ice_players = [state.players[pid] for pid in state.on_ice if pid in state.players]
            if ST.roll_for_penalty(self.rng, on_ice_players, state.coach_profile):
                self._draw_penalty(state, on_ice_players)

    def _draw_penalty(self, offending: _TeamState, on_ice_players: List[Player]) -> None:
        """Register a newly-drawn penalty against ``offending``'s team, log it, and rebuild both
        teams' on-ice groups immediately so the rest of THIS shift plays out at the new strength
        state (a penalty stops play in real hockey -- the very next attempt should already
        reflect the man advantage/disadvantage)."""
        penalty_type = ST.roll_penalty_type(self.rng)
        offender = ST.pick_offending_player(self.rng, on_ice_players)
        offender_pid = offender.pid if offender is not None else None

        self.strength.add_penalty(offending.tid, offender_pid, penalty_type)
        duration = ST.penalty_duration_secs(penalty_type)

        if offender_pid is not None:
            self.result.skater_line(offender_pid).pim += int(duration // 60)

        self._log(EVENT_PENALTY, f"Penalty ({penalty_type}) on team {offending.tid}",
                  team_id=offending.tid, player_id=offender_pid,
                  penalty_type=penalty_type, penalty_duration_secs=duration)

        # Mid-shift strength-state change -- refresh (not advance) both teams' on-ice groups so
        # the rest of THIS shift reflects the new strength state without skipping a line/pair in
        # the normal round-robin rotation (see _TeamState.advance_shift's docstring).
        self._refresh_on_ice_for_all()

    def _advance_penalty_clock(self, elapsed_secs: float) -> bool:
        """Tick the strength-state machine's active penalty timers by ``elapsed_secs``. Returns
        True if the strength state actually changed (a penalty expired) so the caller knows to
        rebuild on-ice groups before the next shot attempt."""
        before = (self.strength.state_for(self.home.tid), self.strength.state_for(self.away.tid))
        self.strength.tick(elapsed_secs)
        after = (self.strength.state_for(self.home.tid), self.strength.state_for(self.away.tid))
        if before != after:
            self._refresh_on_ice_for_all()
            return True
        return False

    def _advance_shift_for_all(self) -> None:
        """Advance BOTH teams' normal round-robin rotation to the next line/pair and set the
        on-ice group for the upcoming shift. Call this exactly once per real shift boundary
        (game start, and once at the end of every ``_play_shift``) -- see
        ``_TeamState.advance_shift``'s docstring for why this must not be called mid-shift."""
        for state in (self.home, self.away):
            game_state = self.strength.state_for(state.tid)
            skaters = self.strength.skaters_on_ice_for(state.tid)
            penalized = self.strength.penalized_player_ids(state.tid)
            state.advance_shift(strength_state=game_state, skaters_needed=skaters,
                                penalized_ids=penalized)

    def _refresh_on_ice_for_all(self) -> None:
        """Rebuild both teams' on-ice groups from the CURRENT strength state without advancing
        the round-robin rotation (PP/PK unit vs. normal rotation, with the correct skater count
        per side -- config.PP_UNIT_SIZE/PK_UNIT_SIZE/PK_UNIT_SIZE_5V3). Safe to call any number
        of times mid-shift (a penalty drawn, then expiring, etc.)."""
        for state in (self.home, self.away):
            game_state = self.strength.state_for(state.tid)
            skaters = self.strength.skaters_on_ice_for(state.tid)
            penalized = self.strength.penalized_player_ids(state.tid)
            state.refresh_on_ice_for_strength_state(strength_state=game_state, skaters_needed=skaters,
                                                    penalized_ids=penalized)

    def _reorient_after_strength_change(self, offense: _TeamState,
                                         defense: _TeamState) -> Tuple[_TeamState, _TeamState]:
        """After on-ice groups are rebuilt mid-shift (a penalty expired), offense/defense still
        refer to the same ``_TeamState`` objects (home/away don't change identity), so no
        reassignment is actually needed -- this exists as a named seam so the intent is
        explicit at the call site and a future richer "who has the puck" model has an obvious
        hook rather than silently relying on object identity."""
        return offense, defense

    # -- faceoffs ---------------------------------------------------------------
    def _log_faceoff(self) -> None:
        """Resolve a faceoff between the two current on-ice centers (contested by `faceoffs`
        rating, realization-scaled coin flip) purely for box-score/PBP bookkeeping -- MVP doesn't
        gate subsequent possession on the faceoff winner (the shift loop already randomizes the
        starting attacker), but every faceoff still needs to be logged and tallied per DEVPLAN.md's
        "faceoffs are contested... determining puck possession for the shift's start" requirement."""
        home_center = self._current_center(self.home)
        away_center = self._current_center(self.away)
        winner_state, winner_pid, loser_pid = self.home, home_center, away_center
        if home_center is not None and away_center is not None:
            home_p = self.home.players[home_center]
            away_p = self.away.players[away_center]
            home_fo = home_p.rating("faceoffs")
            away_fo = away_p.rating("faceoffs")
            real = R.morale_realization(home_p.morale)
            gap = (home_fo - away_fo) * real * 0.004
            home_win_p = max(0.20, min(0.80, FACEOFF_WIN_BASE + gap))
            if self.rng.chance(home_win_p):
                winner_state, winner_pid, loser_pid = self.home, home_center, away_center
            else:
                winner_state, winner_pid, loser_pid = self.away, away_center, home_center
        elif away_center is not None:
            winner_state, winner_pid, loser_pid = self.away, away_center, home_center

        if winner_pid is not None:
            self.result.skater_line(winner_pid).fo_won += 1
        if loser_pid is not None:
            self.result.skater_line(loser_pid).fo_lost += 1

        self._log(EVENT_FACEOFF, "Faceoff", team_id=winner_state.tid if winner_pid else None,
                  player_id=winner_pid)

    @staticmethod
    def _current_center(state: _TeamState) -> Optional[int]:
        """Best-effort "center" for a faceoff: the middle slot (index 1) of the current forward
        line if available, else None. On-ice group stays a plain list (DESIGN.md point 1); this
        just reads index 1 by the line-builder's LW/C/RW convention (team.py's
        _build_forward_lines) rather than encoding any position metadata on the group itself."""
        if len(state.on_ice) >= 2:
            return state.on_ice[1]
        return state.on_ice[0] if state.on_ice else None

    # -- shot resolution ----------------------------------------------------
    def _pick_zone_and_shot_type(self, offense: _TeamState) -> Tuple[str, str]:
        """Pick a zone + shot type for this attempt, skewed by the offense's coach
        shot_quality_bias (higher bias -> more likely to land in a high-danger zone / a
        high-percentage shot type) AND by the offense's current strength state (a PP creates
        meaningfully better looks; a PK's own offense is stuck with lower-quality desperation
        looks -- DEVPLAN.md Step 2.1's strength-state shot modifiers)."""
        bias = (R.shot_quality_bias_delta(offense.coach_profile.shot_quality_bias)
                + R.strength_state_shot_quality_delta(self.strength.state_for(offense.tid)))
        zone_weights = [max(0.05, _ZONE_QUALITY[z] + bias) for z in ALL_ZONES]
        zone = ALL_ZONES[_weighted_index(self.rng, zone_weights)]
        type_weights = [max(0.05, _SHOT_TYPE_QUALITY[t] + bias) for t in SHOT_TYPES]
        shot_type = SHOT_TYPES[_weighted_index(self.rng, type_weights)]
        return zone, shot_type

    def _pick_shooter(self, offense: _TeamState) -> Player:
        cache = offense.cache
        idx = _weighted_index(self.rng, cache.shot_weights)
        return cache.players[idx]

    def _resolve_shot_attempt(self, offense: _TeamState, defense: _TeamState, *,
                               rush: bool, rebound: bool) -> str:
        """Resolve one shot attempt end to end: pick shooter/zone/shot-type, run shooter-vs-goalie
        skill gap through the realization model, log the PBPEvent (with full analytics context),
        update box-score counters (SOG/shots_faced/Corsi/Fenwick as a filter over this same event,
        goals/assists/plus_minus on a goal), and return one of "goal"/"save"/"miss"/"block"/
        "rebound".

        ``defense.goalie_id is None`` now means a genuinely EMPTY NET (DEVPLAN.md Step 2.2's
        pull-the-goalie mechanic, ``_maybe_pull_goalie``) rather than an unreachable data-quality
        guard -- an on-goal attempt against an empty net resolves via ``_resolve_empty_net_shot``
        (near-certain goal, but still not literally 100%: misses/blocks still happen) instead of
        being forced to "miss" outright, which is what an earlier revision of this method did
        (a leftover MVP-era defensive guard from before an empty net was ever a real, reachable
        game state)."""
        if not offense.on_ice or not defense.on_ice:
            return SHOT_OUTCOME_MISS

        shooter = self._pick_shooter(offense)
        goalie = defense.goalie()
        zone, shot_type = self._pick_zone_and_shot_type(offense)

        r = shooter.ratings
        shot_skill = (0.5 * r.get("shot_accuracy", 25) + 0.3 * r.get("shot_power", 25)
                      + 0.2 * r.get("offensive_awareness", 25))
        goalie_skill = 25.0
        if goalie is not None:
            gr = goalie.ratings
            goalie_skill = 0.55 * gr.get("reflexes", 25) + 0.45 * gr.get("positioning", 25)

        # Realization scaling: morale x chemistry x composure, same mechanism for both sides
        # (ratings.py's ported HoopR model). Fatigue realization additionally dampens the
        # shooter's effective skill for their remaining shifts this game.
        off_real = (R.morale_realization(shooter.morale) * offense.cache.chem_real
                    * R.fatigue_realization(offense.fatigue.get(shooter.pid, 0.0)))
        def_real = defense.cache.chem_real * defense.cache.avg_morale_real
        if goalie is not None:
            def_real *= R.morale_realization(goalie.morale)
            def_real *= R.fatigue_realization(defense.fatigue.get(goalie.pid, 0.0))
            # Goalie "hot hand" (DEVPLAN.md Step 2.2): a bounded fraction (ratings.hot_hand_boost,
            # driven by this goalie's own consecutive-save streak) closes PART of the gap between
            # def_real and 1.0 -- it can only pull realization UP toward the ceiling, never past
            # it, and never pulls it down (that's morale/fatigue/chemistry's job above). This
            # REPLACES an earlier additive nudge that was applied directly to save_p below,
            # bypassing def_real entirely -- see ratings.py's hot_hand_boost() docstring for why
            # that was a genuine "players can exceed their rating" violation, not a design choice.
            hot_hand_fraction = R.hot_hand_boost(defense.goalie_hot_hand)
            def_real = def_real + (1.0 - def_real) * hot_hand_fraction

        gap = (shot_skill - goalie_skill) * 0.0035
        # Small zone/shot-type quality bonus feeds directly into the on-goal/quality of the
        # attempt, not just selection -- a high-danger attempt that does get through is more likely
        # to beat the goalie. The offense's current strength state (DEVPLAN.md Step 2.1) also
        # feeds DIRECTLY into this same quality term (not just into zone/shot-type selection bias
        # via _pick_zone_and_shot_type) -- a man advantage creates genuinely better looks even
        # after a zone/shot-type is already picked (more time/space to get the shot away
        # cleanly), so a PP's quality edge needs to be a direct, reliable effect on scoring rate,
        # not only an indirect one filtered through selection odds.
        strength_quality_delta = R.strength_state_shot_quality_delta(self.strength.state_for(offense.tid))
        quality = max(0.05, min(0.98,
                      0.5 * _ZONE_QUALITY[zone] + 0.5 * _SHOT_TYPE_QUALITY[shot_type]
                      + strength_quality_delta))
        rush_bonus = 0.03 if rush else 0.0

        # -- on-goal (not blocked/missed) probability -----------------------
        on_goal_p = max(0.35, min(0.92, 0.55 + (quality - 0.5) * 0.5 + gap * off_real))
        on_goal = self.rng.chance(on_goal_p)

        if not on_goal:
            # Blocked or wide -- split roughly evenly, weighted slightly toward "miss" for
            # high-danger zones (less time for a shot-blocker to get across) and toward "block" for
            # low-danger zones (point shots get blocked more in real hockey).
            block_p = 0.30 + (0.20 if zone in ZONES_LOW_DANGER else 0.0)
            blocked = self.rng.chance(block_p)
            outcome = SHOT_OUTCOME_BLOCK if blocked else SHOT_OUTCOME_MISS
            self._log_shot(offense, defense, shooter, goalie, zone, shot_type, rush, rebound,
                          outcome)
            self._apply_corsi_fenwick(offense, defense, blocked=blocked)
            return outcome

        # Attempt reached the goalie (or an empty net): charge SOG, then resolve save/goal --
        # shots_faced is a goalie-box-score stat, so it only accrues when there's actually a
        # goalie in net to face it (an empty-net attempt has no goalie to charge shots_faced to).
        self.result.skater_line(shooter.pid).sog += 1
        if goalie is not None:
            self.result.goalie_line(goalie.pid).shots_faced += 1
        else:
            return self._resolve_empty_net_shot(offense, defense, shooter, zone, shot_type,
                                                rush, rebound)

        save_p = max(0.55, min(0.97, 0.90 - (quality - 0.5) * 0.35 - rush_bonus - gap * off_real))
        # def_real scales the goalie's realized share of their save probability edge over a
        # neutral 0.90 baseline, mirroring HoopR's shooter/defender gap-parity approach. Hot hand
        # is already folded into def_real above -- do NOT add it again here (see this method's
        # docstring / ratings.hot_hand_boost's "no upweighting" note).
        save_p = max(0.55, min(0.97, 0.90 + (save_p - 0.90) * def_real))
        saved = self.rng.chance(save_p)

        if saved:
            self.result.goalie_line(goalie.pid).saves += 1
            defense.goalie_hot_hand = min(GOAL_HOT_HAND_STREAK_MAX,
                                          defense.goalie_hot_hand + GOAL_HOT_HAND_STREAK_INCREMENT)
            self._log_shot(offense, defense, shooter, goalie, zone, shot_type, rush, rebound,
                          SHOT_OUTCOME_SAVE)
            self._apply_corsi_fenwick(offense, defense, blocked=False)
            if self.rng.chance(REBOUND_CHANCE_BASE):
                return "rebound"
            return SHOT_OUTCOME_SAVE

        # -- goal ------------------------------------------------------------
        self._apply_corsi_fenwick(offense, defense, blocked=False)
        self._score_goal(offense, defense, shooter, goalie, zone, shot_type, rush, rebound)
        return SHOT_OUTCOME_GOAL

    def _resolve_empty_net_shot(self, offense: _TeamState, defense: _TeamState, shooter: Player,
                                 zone: str, shot_type: str, rush: bool, rebound: bool) -> str:
        """Resolve an on-goal attempt against a pulled (empty) net (DEVPLAN.md Step 2.2). No
        goalie to run a skill-gap save check against, so this isn't a degenerate case of the
        normal save-probability formula -- it's its own simple, high-but-not-certain scoring
        roll (``EMPTY_NET_GOAL_BASE_P``, nudged slightly by shot quality): real empty-net attempts
        do still sail wide or get blocked by a backchecking skater often enough that "always a
        goal" would be unrealistic. No goalie box-score line exists to credit a save to (there is
        no goalie in net), so a non-goal outcome here is scored as a miss/block exactly like a
        normal shot that never reached the goalie."""
        goal_p = max(0.30, min(0.85, EMPTY_NET_GOAL_BASE_P + (_ZONE_QUALITY[zone] - 0.5) * 0.3))
        if self.rng.chance(goal_p):
            self._apply_corsi_fenwick(offense, defense, blocked=False)
            self._score_goal(offense, defense, shooter, None, zone, shot_type, rush, rebound)
            return SHOT_OUTCOME_GOAL

        blocked = self.rng.chance(0.35)
        outcome = SHOT_OUTCOME_BLOCK if blocked else SHOT_OUTCOME_MISS
        self._log_shot(offense, defense, shooter, None, zone, shot_type, rush, rebound, outcome)
        self._apply_corsi_fenwick(offense, defense, blocked=blocked)
        return outcome

    def _apply_corsi_fenwick(self, offense: _TeamState, defense: _TeamState, *,
                              blocked: bool) -> None:
        """Tally Corsi/Fenwick as a simple filter over the shot-attempt event stream (DESIGN.md
        point 10's explicit requirement -- not a separate bolted-on pass): every attempt counts
        toward Corsi; only unblocked attempts count toward Fenwick. Applied to every on-ice skater
        on both teams (for/against symmetry)."""
        for pid in offense.on_ice:
            line = self.result.skater_line(pid)
            line.corsi_for += 1
            if not blocked:
                line.fenwick_for += 1
        for pid in defense.on_ice:
            line = self.result.skater_line(pid)
            line.corsi_against += 1
            if not blocked:
                line.fenwick_against += 1

    def _score_goal(self, offense: _TeamState, defense: _TeamState, shooter: Player,
                     goalie: Optional[Player], zone: str, shot_type: str, rush: bool,
                     rebound: bool) -> None:
        if offense.is_home:
            self.result.home_score += 1
        else:
            self.result.away_score += 1

        self.result.skater_line(shooter.pid).g += 1

        assist_pid, secondary_pid = self._pick_assists(offense, shooter)
        if assist_pid is not None:
            self.result.skater_line(assist_pid).a += 1
        if secondary_pid is not None:
            self.result.skater_line(secondary_pid).a += 1

        # Capture the strength state BEFORE any early-penalty-release reversion below, so both
        # the plus/minus gating and the logged goal event reflect the state the goal was
        # actually scored under (see _log_shot's docstring).
        scoring_strength_state = self.strength.state_for(offense.tid)

        # Real-NHL plus/minus rule: a power-play goal is NOT credited to plus/minus at all (for
        # the scoring team's skaters OR the shorthanded team's skaters) -- only even-strength
        # (5v5/4v4/3v3) and shorthanded-goals-for count. On-ice group sizes differ during PP/PK
        # (5 vs 4, or 5 vs 3 on a 5-on-3), so crediting every on-ice skater symmetrically would
        # never net to zero league-wide during special teams anyway -- gating on strength state
        # is both the real-hockey-accurate rule AND what keeps the league-wide net at zero.
        # DEVPLAN.md Step 2.2 extends this same real-NHL exclusion to an EMPTY-NET goal
        # (``goalie is None``): real NHL scorekeeping never credits/debits plus/minus for a
        # goal scored on a pulled goalie either (same "special situation, doesn't count" logic
        # as a PP goal) -- also keeps the league-wide net-zero invariant intact for a 6-on-5
        # situation, which (like PP/5v3) has asymmetric on-ice group sizes.
        if scoring_strength_state not in (config.STRENGTH_PP, config.STRENGTH_5V3) and goalie is not None:
            for pid in offense.on_ice:
                self.result.skater_line(pid).plus_minus += 1
            for pid in defense.on_ice:
                self.result.skater_line(pid).plus_minus -= 1

        if goalie is not None:
            self.result.goalie_line(goalie.pid).goals_against += 1
            defense.goalie_hot_hand = 0.0   # a goal resets any hot-hand nudge
        # else: an empty-net goal (goalie is None -- the defending team pulled theirs) is not
        # charged as goals_against to anyone -- there is no goalie in net to charge it to, matching
        # real-NHL scorekeeping (an ENG never counts against a goalie's save percentage/GAA).

        # Real-NHL rule (DEVPLAN.md Step 2.1, explicitly not an open design question): a
        # non-fighting MINOR penalty ends immediately if the penalized team is scored on while
        # shorthanded. If the team on defense here (the team that just conceded) is currently
        # serving a power-play-triggering minor, release the soonest-to-expire one and rebuild
        # both teams' on-ice groups so the very next shift already reflects the reverted
        # strength state. Majors/misconducts are untouched (they run their full duration
        # regardless of goals against).
        if self.strength.end_one_penalty_early(defense.tid):
            self._refresh_on_ice_for_all()

        self._log_shot(offense, defense, shooter, goalie, zone, shot_type, rush, rebound,
                      SHOT_OUTCOME_GOAL, assist_pid=assist_pid, secondary_pid=secondary_pid,
                      strength_state=scoring_strength_state)

    def _pick_assists(self, offense: _TeamState, shooter: Player) -> Tuple[Optional[int], Optional[int]]:
        """Weighted (not deterministic-always-best) pick of a primary + optional secondary
        assist from the rest of the on-ice skaters, favoring higher playmaking."""
        others = [pid for pid in offense.on_ice if pid != shooter.pid]
        if not others:
            return None, None
        weights = [max(0.5, offense.players[pid].rating("playmaking") - 20) for pid in others]
        # ~80% of goals get a primary assist (real-hockey-ish base rate for MVP).
        if not self.rng.chance(0.80):
            return None, None
        idx = _weighted_index(self.rng, weights)
        primary = others[idx]
        remaining = [pid for pid in others if pid != primary]
        if not remaining or not self.rng.chance(0.55):
            return primary, None
        remaining_weights = [max(0.5, offense.players[pid].rating("playmaking") - 20)
                            for pid in remaining]
        secondary = remaining[_weighted_index(self.rng, remaining_weights)]
        return primary, secondary

    # -- ice time & fatigue ---------------------------------------------------
    def _apply_ice_time(self, shift_secs: float) -> None:
        """Credit this shift's seconds to every player who was actually on the ice: the 5 rotating
        skaters accrue ``SkaterStatLine.secs`` + fatigue, and the starting goalie -- who plays every
        shift regardless of the skater rotation, per real hockey -- separately accrues
        ``GoalieStatLine.secs`` (goalies aren't part of ``state.on_ice``, the 5-skater rotation
        group, so they need their own branch rather than sharing the skater loop below)."""
        for state in (self.home, self.away):
            on_ice_set = set(state.on_ice)
            for pid in state.players:
                if pid == state.goalie_id:
                    continue   # goalie ice time/fatigue handled separately below
                if pid in on_ice_set:
                    self.result.skater_line(pid).secs += int(round(shift_secs))
                    state.fatigue[pid] = min(100.0, state.fatigue.get(pid, 0.0)
                                             + shift_secs * FATIGUE_GAIN_PER_SEC)
                else:
                    state.fatigue[pid] = max(0.0, state.fatigue.get(pid, 0.0)
                                             - shift_secs * FATIGUE_RECOVER_PER_SEC)
            if state.goalie_id is not None:
                self.result.goalie_line(state.goalie_id).secs += int(round(shift_secs))
                state.fatigue[state.goalie_id] = min(
                    100.0, state.fatigue.get(state.goalie_id, 0.0)
                    + shift_secs * FATIGUE_GAIN_PER_SEC * 0.4)   # goalies tire slower than skaters

    # -- decision-point view (resumable generator scaffolding) ---------------
    def _decision_view(self) -> "GameSim":
        """The object yielded at a stoppage. Currently just ``self`` -- there's no real
        decision-making consumer yet (penalties/goalie-pull/line-juggling are all later steps), so
        a richer dedicated view type isn't warranted until a real consumer defines what it needs.
        Exposing ``self`` keeps the seam trivially extensible: a future consumer can read
        ``self.result``/``self.home``/``self.away``/``self.period``/``self.game_secs`` directly."""
        return self

    # -- logging ----------------------------------------------------------------
    def _log(self, event_type: str, description: str, *, team_id: Optional[int] = None,
              player_id: Optional[int] = None, penalty_type: Optional[str] = None,
              penalty_duration_secs: Optional[float] = None) -> None:
        if not self.collect_pbp:
            return
        self.result.pbp.append(PBPEvent(
            period=self.period, time_secs=self.game_secs, event_type=event_type,
            description=description, home_score=self.result.home_score,
            away_score=self.result.away_score, team_id=team_id, player_id=player_id,
            penalty_type=penalty_type, penalty_duration_secs=penalty_duration_secs,
        ))

    def _log_shot(self, offense: _TeamState, defense: _TeamState, shooter: Player,
                  goalie: Optional[Player], zone: str, shot_type: str, rush: bool,
                  rebound: bool, outcome: str, *, assist_pid: Optional[int] = None,
                  secondary_pid: Optional[int] = None,
                  strength_state: Optional[str] = None) -> None:
        if not self.collect_pbp:
            return
        event_type = EVENT_GOAL if outcome == SHOT_OUTCOME_GOAL else EVENT_SHOT
        desc = f"{shooter.short_name} {shot_type} shot from the {zone} -- {outcome}"
        # The REAL current strength state from the offense's perspective (DEVPLAN.md Step 2.1 --
        # this used to be a hardcoded config.STRENGTH_5V5 literal on every logged shot). Callers
        # scoring a goal that ends a penalty early (see _score_goal) must pass the strength
        # state captured BEFORE that reversion, so the event reflects the state the goal was
        # actually scored under (e.g. a shorthanded goal still logs as the scoring team's PP,
        # not the post-reversion 5v5 the game reverts to immediately after).
        state = strength_state if strength_state is not None else self.strength.state_for(offense.tid)
        self.result.pbp.append(PBPEvent(
            period=self.period, time_secs=self.game_secs, event_type=event_type,
            description=desc, home_score=self.result.home_score, away_score=self.result.away_score,
            team_id=offense.tid, player_id=shooter.pid, assist_player_id=assist_pid,
            secondary_assist_player_id=secondary_pid,
            goalie_id=goalie.pid if goalie is not None else None,
            shot_type=shot_type, zone=zone, strength_state=state,
            rebound=rebound, rush=rush, outcome=outcome,
        ))

    # -- finalize ---------------------------------------------------------------
    def _finalize(self) -> None:
        """Fill in gp/gs and W/L/OTL bookkeeping once the final score is known."""
        for state in (self.home, self.away):
            for pid in state.team.roster:
                if pid in self.result.skater_box:
                    self.result.skater_box[pid].gp = 1
                if pid in self.result.goalie_box:
                    self.result.goalie_box[pid].gp = 1

        # Unresolved tie (provisional OT placeholder ran out with the score still level -- see
        # coach_session()'s OT block): no decisive winner/loser exists, so W/L/OTL bookkeeping is
        # skipped entirely rather than guessing a winner. Real OT/shootout resolution (Step 2.6)
        # always produces a decision, so this branch only matters for this step's placeholder.
        is_unresolved_tie = self.result.home_score == self.result.away_score
        if not is_unresolved_tie:
            home_won = self.result.home_score > self.result.away_score
            for state, won in ((self.home, home_won), (self.away, not home_won)):
                gid = state.goalie_id
                if gid is not None and gid in self.result.goalie_box:
                    line = self.result.goalie_box[gid]
                    if won:
                        line.wins += 1
                    elif self.result.went_ot:
                        line.otl += 1
                    else:
                        line.losses += 1
                    if line.goals_against == 0 and line.secs > 0:
                        line.shutouts += 1

        self._log(EVENT_GAME_END, "Final")


def simulate_game(world: World, home_tid: int, away_tid: int, *,
                   collect_pbp: bool = False,
                   home_goalie_id: Optional[int] = None,
                   away_goalie_id: Optional[int] = None) -> GameResult:
    """Convenience wrapper: simulate one game and return its result.

    ``home_goalie_id``/``away_goalie_id`` (DEVPLAN.md Step 2.2) pass through to
    ``GameSim``'s same-named constructor overrides -- see that class's docstring. Defaults to
    ``None`` (falls back to each team's ``Team.goalie_starter``), so this is a strict additive
    extension for any existing caller.
    """
    return GameSim(world, home_tid, away_tid, collect_pbp=collect_pbp,
                   home_goalie_id=home_goalie_id, away_goalie_id=away_goalie_id).play()
