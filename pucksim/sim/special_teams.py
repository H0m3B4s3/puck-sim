"""Special teams & strength-state engine extension (DEVPLAN.md Step 2.1).

This module is the penalty engine + strength-state state machine that ``sim/engine.py``
drives every shift. It owns three concerns, kept separate from ``engine.py``'s control flow
the same way ``ratings.py`` keeps tactic-modifier math separate (a testable, rebalance-able
unit rather than logic tangled into the shift loop):

1. **Penalty probability** (``penalty_probability_for_shift`` / ``roll_for_penalty``) -- a
   clearly-commented PROVISIONAL first-pass model (DEVPLAN.md explicitly flags exact
   strength-state probability tuning as an open item, not a design-time decision). Scales a
   league-average per-shift baseline by the offending player's ``discipline`` rating and the
   offending team's coach ``defensive_risk_tolerance`` / ``forecheck_aggression``.
2. **Penalty type** (``roll_penalty_type``) -- weighted random minor/major/misconduct pick,
   heavily weighted toward minors (real hockey: the vast majority of penalties are minors).
3. **Strength-state state machine** (``StrengthStateMachine``) -- tracks active penalty
   timers (which team is short, which player(s) are in the box, how much time remains),
   derives the current ``config.STRENGTH_*`` state from those timers, handles overlapping
   penalties (a second minor drawn during an existing PK extends shorthanded time / can
   create a 5-on-3), and implements the real-NHL "a non-fighting minor penalty ends early if
   the penalized team is scored on while shorthanded" rule.

PP/PK unit selection (which on-ice group a team fields once strength state isn't 5v5) is
also here (``on_ice_group_for_state``) since it's a direct consequence of the state machine's
current state -- ``engine.py`` calls it once per shift alongside ``rotate_on_ice()``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from pucksim import config
from pucksim.models.coach import CoachProfile
from pucksim.models.player import Player
from pucksim.models.team import Team

# ---------------------------------------------------------------------------
# Penalty probability -- PROVISIONAL/FIRST-PASS MODEL.
#
# Same framing as every other unresolved constant in this codebase: a reasonable starting
# shape, not a tuned model. Real balancing needs actual simulated-season penalty-rate data,
# which doesn't exist until this step ships (DEVPLAN.md's own open-item note).
#
# Formula (see penalty_probability_for_shift):
#   p = PENALTY_BASE_PROB_PER_SHIFT
#       * discipline_multiplier(worst on-ice discipline rating)
#       * risk_tolerance_multiplier(coach.defensive_risk_tolerance)
#       * forecheck_multiplier(coach.forecheck_aggression)
#
# Discipline: lower discipline -> more penalties. Centered on the 70 "average NHL regular"
# rating anchor used everywhere else in this codebase (ratings.py's realization constants,
# leaguegen's target-overall distribution). A rating 29 points below average (rating 41, a
# real outlier) roughly doubles the base rate; a rating 29 points above (99, elite discipline)
# roughly halves it -- reasonable starting magnitudes only.
# ---------------------------------------------------------------------------
_DISCIPLINE_ANCHOR = 70


def discipline_multiplier(discipline_rating: int) -> float:
    """Lower discipline -> higher penalty probability. 1.0x at the 70 "average" anchor."""
    delta = _DISCIPLINE_ANCHOR - discipline_rating  # positive delta = below-average discipline
    mult = 1.0 + delta * config.PENALTY_DISCIPLINE_SLOPE
    return max(0.25, min(3.0, mult))


def risk_tolerance_multiplier(defensive_risk_tolerance: float) -> float:
    """Higher defensive_risk_tolerance (aggressive pinching/gap control) -> more penalties.

    Linear interpolation between PENALTY_RISK_TOLERANCE_MIN_MULT (0.0) and
    PENALTY_RISK_TOLERANCE_MAX_MULT (1.0), anchored so 0.5 "Balanced" nets to 1.0x.
    """
    t = max(0.0, min(1.0, defensive_risk_tolerance))
    lo, hi = config.PENALTY_RISK_TOLERANCE_MIN_MULT, config.PENALTY_RISK_TOLERANCE_MAX_MULT
    return lo + (hi - lo) * t


def forecheck_multiplier(forecheck_aggression: float) -> float:
    """Higher forecheck_aggression -> more penalties (aggressive forechecking draws more
    interference/hooking/holding calls). Same anchored-linear shape as risk_tolerance above."""
    t = max(0.0, min(1.0, forecheck_aggression))
    lo, hi = config.PENALTY_FORECHECK_MIN_MULT, config.PENALTY_FORECHECK_MAX_MULT
    return lo + (hi - lo) * t


def penalty_probability_for_shift(on_ice_players: List[Player],
                                   coach_profile: CoachProfile) -> float:
    """Probability the offending team's on-ice group draws a penalty this shift.

    Uses the LOWEST discipline rating among the on-ice group (the most-likely offender sets
    the floor -- a shift with one undisciplined player is meaningfully more penalty-prone than
    its average would suggest, since real penalties are drawn by individuals, not team
    averages) scaled by the team's coach tendencies. Returns a probability in [0, 1].
    """
    if not on_ice_players:
        return 0.0
    worst_discipline = min(p.rating("discipline", config.RATING_MIN) for p in on_ice_players)
    p = (config.PENALTY_BASE_PROB_PER_SHIFT
         * discipline_multiplier(worst_discipline)
         * risk_tolerance_multiplier(coach_profile.defensive_risk_tolerance)
         * forecheck_multiplier(coach_profile.forecheck_aggression))
    return max(0.0, min(1.0, p))


def roll_for_penalty(rng, on_ice_players: List[Player], coach_profile: CoachProfile) -> bool:
    """Convenience wrapper: roll the rng against penalty_probability_for_shift's result."""
    return rng.chance(penalty_probability_for_shift(on_ice_players, coach_profile))


def pick_offending_player(rng, on_ice_players: List[Player]) -> Optional[Player]:
    """Pick which on-ice player is credited with a drawn penalty, weighted toward the least
    disciplined skaters (inverse of discipline rating) -- a simple, clearly-provisional model
    consistent with the rest of this module's framing."""
    if not on_ice_players:
        return None
    weights = [max(1.0, 130 - p.rating("discipline", config.RATING_MIN)) for p in on_ice_players]
    return rng.choices(on_ice_players, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Penalty type -- weighted random pick, minors overwhelmingly the most common (real hockey).
# ---------------------------------------------------------------------------
PENALTY_MINOR = "minor"
PENALTY_MAJOR = "major"
PENALTY_MISCONDUCT = "misconduct"

_PENALTY_DURATIONS = {
    PENALTY_MINOR: config.MINOR_PENALTY_SECONDS,
    PENALTY_MAJOR: config.MAJOR_PENALTY_SECONDS,
    PENALTY_MISCONDUCT: config.MISCONDUCT_PENALTY_SECONDS,
}


def penalty_duration_secs(penalty_type: str) -> float:
    return _PENALTY_DURATIONS.get(penalty_type, config.MINOR_PENALTY_SECONDS)


def roll_penalty_type(rng) -> str:
    """Weighted random minor/major/misconduct pick, per config.PENALTY_TYPE_WEIGHTS."""
    types = list(config.PENALTY_TYPE_WEIGHTS.keys())
    weights = list(config.PENALTY_TYPE_WEIGHTS.values())
    return rng.choices(types, weights=weights, k=1)[0]


# ---------------------------------------------------------------------------
# Strength-state state machine
# ---------------------------------------------------------------------------
@dataclass
class _PenaltyTimer:
    """One active penalty: the offending team, the penalized player, remaining seconds, and
    whether it's a "PP-ending" type (a minor -- majors/misconducts do NOT end early on a
    shorthanded goal, per real NHL rules; misconducts don't even create a man advantage at
    all, see below)."""

    team_tid: int
    player_id: Optional[int]
    penalty_type: str
    remaining_secs: float
    counts_toward_strength: bool   # False for misconducts -- box time only, no PP for the other side


@dataclass
class StrengthStateMachine:
    """Tracks every currently-active penalty for both teams and derives the current strength
    state from them. One instance per game, shared between both ``_TeamState``s (strength
    state is genuinely shared game state -- both teams are always in the same state, just
    viewed from opposite perspectives, exactly as DEVPLAN.md's assignment describes).

    ``home_tid``/``away_tid`` identify the two sides so ``state_for(tid)`` can answer "is this
    team currently on the PP, the PK, or at a neutral strength" from either team's perspective.
    """

    home_tid: int
    away_tid: int
    _timers: List[_PenaltyTimer] = field(default_factory=list)

    # -- mutation -----------------------------------------------------------
    def add_penalty(self, team_tid: int, player_id: Optional[int], penalty_type: str) -> _PenaltyTimer:
        """Register a newly-drawn penalty against ``team_tid`` (the offending team)."""
        counts = penalty_type != PENALTY_MISCONDUCT
        timer = _PenaltyTimer(
            team_tid=team_tid, player_id=player_id, penalty_type=penalty_type,
            remaining_secs=penalty_duration_secs(penalty_type),
            counts_toward_strength=counts,
        )
        self._timers.append(timer)
        return timer

    def tick(self, elapsed_secs: float) -> None:
        """Advance every active timer by ``elapsed_secs`` and drop any that have expired."""
        for timer in self._timers:
            timer.remaining_secs -= elapsed_secs
        self._timers = [t for t in self._timers if t.remaining_secs > 1e-9]

    def end_one_penalty_early(self, team_tid: int) -> bool:
        """Implements the real-NHL rule: a non-fighting MINOR penalty ends immediately if the
        penalized (shorthanded) team is scored on while the penalty is active. Ends the
        soonest-to-expire eligible minor for ``team_tid`` that still counts toward strength
        (majors/misconducts never end early -- a 5-minute major runs its full duration
        regardless of goals against, and misconducts don't affect strength state at all).
        Returns True if a penalty was actually ended.
        """
        eligible = [t for t in self._timers
                    if t.team_tid == team_tid and t.penalty_type == PENALTY_MINOR
                    and t.counts_toward_strength]
        if not eligible:
            return False
        # End the one closest to expiring (real referees release the first penalty to
        # complete its minimum time when a shorthanded goal is scored during overlapping
        # penalties -- a simple, reasonable approximation of that rule).
        soonest = min(eligible, key=lambda t: t.remaining_secs)
        self._timers.remove(soonest)
        return True

    # -- queries --------------------------------------------------------------
    def active_penalty_count(self, team_tid: int) -> int:
        """Number of active strength-affecting penalties currently charged against
        ``team_tid`` (misconducts excluded -- they don't count toward the strength state)."""
        return sum(1 for t in self._timers if t.team_tid == team_tid and t.counts_toward_strength)

    def is_5v5(self) -> bool:
        return self.active_penalty_count(self.home_tid) == 0 and self.active_penalty_count(self.away_tid) == 0

    def state_for(self, tid: int) -> str:
        """Current strength state from ``tid``'s own perspective: STRENGTH_PP if the other
        team is short, STRENGTH_PK if this team is short, STRENGTH_5V3 for a double
        disadvantage, STRENGTH_5V5 otherwise. Handles the simple/common cases; exotic overlaps
        beyond 5v3 (e.g. simultaneous penalties both ways) collapse to the closest reasonable
        state rather than modeling every possible NHL rulebook edge case (DEVPLAN.md: "don't
        over-engineer exotic edge cases, a reasonable simple model is fine").
        """
        other_tid = self.away_tid if tid == self.home_tid else self.home_tid
        own_penalties = self.active_penalty_count(tid)
        other_penalties = self.active_penalty_count(other_tid)

        if own_penalties == 0 and other_penalties == 0:
            return config.STRENGTH_5V5
        if own_penalties > 0 and other_penalties == 0:
            # This team is shorthanded. Cap the modeled disadvantage at a 5-on-3 (never worse
            # in real hockey -- a 3rd simultaneous minor is served consecutively, not
            # concurrently) per the "don't over-engineer" instruction.
            return config.STRENGTH_5V3 if own_penalties >= 2 else config.STRENGTH_PK
        if other_penalties > 0 and own_penalties == 0:
            return config.STRENGTH_PP
        # Offsetting penalties both ways (rare) -- simplest reasonable collapse: treat as even
        # strength for shot-generation purposes rather than modeling 4-on-4 offsetting minors
        # as a distinct state machine branch.
        return config.STRENGTH_4V4

    def skaters_on_ice_for(self, tid: int) -> int:
        """How many skaters ``tid`` fields right now, given the current strength state.

        Bug fix (DEVPLAN.md Step 2.3, found while reworking faceoff/injury on-ice-group logic
        in this same territory): STRENGTH_4V4 previously fell through to the ``return 5``
        default below, which is wrong on its face (a "4v4" state fielding 5-a-side) and had a
        real, demonstrable consequence -- ``special_teams.on_ice_group_for_state`` would ask for
        5 skaters at 4v4, but the offending team's own penalized player is excluded from its
        ``normal_group`` (only 5 bodies to begin with) with no bench to pad from in that
        function's fallback loop, so one side would silently end up with 4 on-ice skaters while
        the other had 5 -- breaking the plus/minus net-zero invariant on any goal scored during
        that mismatched 4v4 shift (a pre-existing bug, not something this step's faceoff/injury
        changes introduced, but exposed more often once this step's injury-aware backfill
        started producing more frequent size-mismatch scenarios generally). Fixed at the source:
        4v4 now correctly asks for 4 skaters per side, matching the state's own name.
        """
        state = self.state_for(tid)
        if state == config.STRENGTH_PP:
            return config.PP_UNIT_SIZE
        if state == config.STRENGTH_PK:
            return config.PK_UNIT_SIZE
        if state == config.STRENGTH_5V3:
            # 5v3: the team taking two minors drops to 3, per config.PK_UNIT_SIZE_5V3.
            if self.active_penalty_count(tid) >= 2:
                return config.PK_UNIT_SIZE_5V3
            return config.PP_UNIT_SIZE
        if state == config.STRENGTH_4V4:
            return 4   # offsetting penalties both ways -- 4 skaters per side, not 5.
        return 5   # 5v5 -- 5 skaters per side.

    def penalized_player_ids(self, tid: int) -> List[int]:
        """Player ids currently serving time in the box for ``tid`` (any penalty type,
        including misconducts -- a misconducted player is still off the ice even though his
        team isn't shorthanded)."""
        return [t.player_id for t in self._timers if t.team_tid == tid and t.player_id is not None]


# ---------------------------------------------------------------------------
# PP/PK unit selection -- which on-ice group a team fields given the current strength state.
# ---------------------------------------------------------------------------
def on_ice_group_for_state(team: Team, state: str, *, normal_group: List[int],
                            skaters_needed: int, penalized_ids: Optional[List[int]] = None) -> List[int]:
    """Pick the on-ice skater group appropriate for the team's current strength state.

    - STRENGTH_PP: the team's top power-play unit (``team.pp_unit_1``), truncated/padded to
      ``skaters_needed`` (5, the full-strength side of the man advantage).
    - STRENGTH_PK: the team's top penalty-kill unit (``team.pk_unit_1``), truncated/padded to
      ``skaters_needed`` (4, or 3 on a 5-on-3).
    - Otherwise (5v5/4v4/3v3 etc.): the normal rotation group passed in by the caller
      (engine.py's existing line/pair round-robin), unchanged -- this function only overrides
      group selection for PP/PK states.

    Falls back to the normal rotation group (trimmed/padded) if the requested special-teams
    unit is empty/undersized (e.g. auto_build_special_teams_units was never called, or an
    injury-depleted roster) rather than returning an empty on-ice group -- never crash on a
    missing unit, per this module's "reasonable simple model" framing.
    """
    penalized = set(penalized_ids or [])

    if state == config.STRENGTH_PP and team.pp_unit_1:
        group = [pid for pid in team.pp_unit_1 if pid not in penalized]
    elif state in (config.STRENGTH_PK, config.STRENGTH_5V3) and team.pk_unit_1:
        group = [pid for pid in team.pk_unit_1 if pid not in penalized]
    else:
        group = [pid for pid in normal_group if pid not in penalized]

    if len(group) < skaters_needed:
        # Pad from the normal rotation group (skipping duplicates/penalized players) so the
        # on-ice group is never short a body just because a special-teams unit is undersized.
        for pid in normal_group:
            if pid not in group and pid not in penalized:
                group.append(pid)
            if len(group) >= skaters_needed:
                break

    return group[:skaters_needed]
