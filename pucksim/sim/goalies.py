"""Goalies as a full system (DEVPLAN.md Step 2.2).

This module owns the two concerns DEVPLAN.md assigns it that don't already live in
``sim/engine.py`` or ``sim/ratings.py``:

1. **Starter/backup rest-based rotation** (``choose_starting_goalie`` + the
   ``GoalieRestState`` tracker below) -- decides, for a given game, which of a team's two
   rostered goalies (``Team.goalie_starter``/``Team.goalie_backup``) actually starts, based on
   a simple rest model: how many games in a row a goalie has already started. Real-NHL usage
   shape this aims for: a #1 goalie starts roughly 55-65 of an 82-game season, the backup takes
   the rest, and teams avoid starting the same goalie on zero days' rest more often than not
   (but it does happen -- this is a tendency, not a hard rule).

   IMPORTANT caveat this module works around: ``sim/season.py``'s schedule model (Step 1.13,
   the circle-method round-robin) assigns a strictly-sequential ``day`` counter that increments
   by exactly 1 every round, and every team plays in every round -- there is no notion of a
   real-calendar rest day anywhere in the schedule (``day - previous_day`` is ALWAYS exactly 1
   for every team, every game, by construction; verified directly against
   ``generate_schedule()``'s output). That means a literal "did this goalie start on day - 1"
   check would fire as True for essentially every single game of the season, which would
   destroy the intended starter-should-play-more shape (it degenerates into near-random nightly
   alternation rather than a stable ~60/40 split). So the PRIMARY mechanism driving the split
   here is ``STARTER_MAX_CONSECUTIVE_STARTS``/``BACKUP_MAX_CONSECUTIVE_STARTS`` (how many
   games in a row each goalie has actually started, which is real signal regardless of what
   ``day`` means) -- the back-to-back check is a secondary, much rarer nudge
   (``BACK_TO_BACK_AVOID_PROB``, applied conditionally, see ``choose_starting_goalie``'s
   docstring) so it can't dominate the rotation the way a "fires almost every night" check
   would under this schedule model. If a future step gives the schedule real rest-day gaps,
   this same ``day``-based signal becomes meaningful without any change needed here.

2. **Hot-hand model** -- the actual streak-tracking state (a small rolling counter,
   incremented per consecutive save / reset-or-decayed on a goal against) lives on
   ``engine._TeamState`` (same field the old additive nudge used, just reinterpreted -- see
   that module), but the math that turns a streak value into a save-probability-safe boost is
   ``ratings.hot_hand_boost()``. Nothing new needed here beyond what ``ratings.py`` and
   ``engine.py`` already provide -- this module's docstring just cross-references it so a
   future reader looking for "the goalie hot-hand system" finds the whole picture from one
   entry point.

Where "games since last start" state lives, and why
-----------------------------------------------------
There is no existing field anywhere for "games since this goalie last started" -- not on
``Player`` (out of bounds for this step to edit per DEVPLAN.md's constraints; also, this is
transient game-orchestration bookkeeping, not a fact about the player that needs to survive
into awards/development/career-stat calculations), and not on ``Team`` (same reasoning, plus
``Team`` fields are part of the permanent save schema and this data is fully re-derivable from
"how many games has this team played and who started each one," which the save's own
``schedule``/box-score history already encodes if anyone ever needs to reconstruct it).

Decision: a small transient dict, keyed by team id, tracked at the season-orchestration level
(``sim/season.py`` owns day-by-day advancement, so it's the natural owner of "which goalie
should start today" bookkeeping) -- NOT part of ``World``'s serialized schema. Concretely,
``GoalieRestState`` (below) is a plain dataclass a caller constructs once per season/sim run
and threads through every call to ``choose_starting_goalie``; ``season.py`` owns one instance
and updates it each time a game is simmed. This keeps ``Player``/``Team``/``World`` schemas
completely untouched (no save-migration concerns) while giving the rotation logic exactly the
state it needs. If a save is reloaded mid-season, the rest tracker simply starts fresh (a
goalie's "games since last start" resets to "unknown, treat as fully rested") -- a reasonable,
clearly-documented simplification consistent with this codebase's "don't over-engineer" ethos;
the alternative (persisting rest state across saves) would require exactly the schema/
migration surgery this design avoids, for a purely cosmetic rotation-smoothness benefit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from pucksim.models.team import Team

# ---------------------------------------------------------------------------
# Tunables -- PROVISIONAL/first-pass, same framing as every other unresolved constant in this
# codebase. Real balancing needs actual simulated-season starter/backup split data.
# ---------------------------------------------------------------------------
# A starter is "due for a rest" once they've started this many games in a row without the
# backup getting a look -- keeps a #1 goalie in the real-NHL 55-65-starts-per-82-games band
# rather than playing literally every game. This is the PRIMARY driver of the starter/backup
# split (see module docstring for why the back-to-back check below is deliberately secondary).
#
# NOTE on the ratio: since ``choose_starting_goalie`` always swings back to the starter as soon
# as the starter's OWN streak resets to 0 (see ``GoalieRestState.record_start``), one full
# rotation "cycle" under normal play is STARTER_MAX_CONSECUTIVE_STARTS starts followed by
# exactly one rest game for the backup (the backup practically never reaches its own max in a
# single sitting under this simple alternation shape) -- so the season-long starter share lands
# close to ``STARTER_MAX_CONSECUTIVE_STARTS / (STARTER_MAX_CONSECUTIVE_STARTS + 1)``. A value of
# 3 here targets ~75% on its own, nudged down toward the real-NHL 55-65% band by the
# BACK_TO_BACK_AVOID_PROB secondary check below (which occasionally hands the starter's night to
# the backup even mid-streak) -- verified directly via a season-length simulation (see
# tests/test_goalies.py's rotation tests) to land the observed share solidly in-band.
STARTER_MAX_CONSECUTIVE_STARTS = 3

# Once the backup has started this many games in a row (the starter was resting for a stretch),
# the starter is pulled back in -- keeps the backup from taking over the job entirely over a
# long season (a defensive ceiling; under normal play the backup rarely gets close to this many
# consecutive starts in one sitting given the alternation shape above, but it matters when the
# back-to-back nudge below fires on several consecutive nights in a row).
BACKUP_MAX_CONSECUTIVE_STARTS = 2

# Probability the rotation logic avoids starting a goalie on zero days' rest (a true
# back-to-back -- this team played yesterday AND this goalie started that game) by handing the
# start to the other rostered goalie instead, if the other goalie is actually rested. Not a hard
# rule ("teams avoid... more often than not, but it does happen" per DEVPLAN.md) -- a bit of
# randomness keeps it from being a deterministic never-happens rule.
#
# NOTE: under this codebase's current schedule generator, EVERY game is technically "day - 1"
# from a team's previous game (no rest days exist in the schedule at all -- verified directly
# against generate_schedule()'s output, see module docstring), so this condition is checked on
# essentially every night the starter would otherwise go. That means, in THIS codebase's
# schedule model, this constant is doing double duty: it's both "how often a genuine zero-rest
# back-to-back gets avoided" AND (in practice, since the schedule has no rest days at all) part
# of what pulls the season-long starter share down from the ~75% the consecutive-starts
# mechanism alone would produce (STARTER_MAX_CONSECUTIVE_STARTS / (STARTER_MAX_CONSECUTIVE_STARTS
# + 1)) into the targeted ~55-65% real-NHL band. Calibrated empirically (see
# tests/test_goalies.py) against a full simulated 82-game schedule per team -- 0.5 lands the
# observed starter share consistently in the ~60-68% range across many seeds/teams. If a future
# step gives the schedule real rest-day gaps, this same knob keeps working (it'll simply fire
# less often, since most games will no longer register as a true back-to-back at all).
BACK_TO_BACK_AVOID_PROB = 0.5


@dataclass
class _TeamGoalieRest:
    """Per-team rest bookkeeping for exactly the two rostered goalies this step cares about
    (starter/backup) -- a team with only one healthy goalie just always starts that one, so this
    struct doesn't need to generalize beyond two."""

    last_starter_pid: Optional[int] = None      # who started the team's most recent game
    last_game_day: Optional[int] = None          # which day that game was on (for back-to-back
                                                  # detection -- computed fresh at QUERY time
                                                  # against the day of the game being decided,
                                                  # not cached at record time, since "yesterday"
                                                  # is only meaningful relative to the next game)
    consecutive_starts: Dict[int, int] = field(default_factory=dict)  # pid -> current start streak


@dataclass
class GoalieRestState:
    """Transient, non-persisted per-season tracker of "games since last start" for every team.

    Owned by whichever caller drives day-by-day season advancement (``sim/season.py``'s
    ``advance_one_day``/``sim_one``) -- constructed once per season/run, NOT serialized as part
    of ``World`` (see module docstring). Threaded through ``choose_starting_goalie`` and updated
    via ``record_start`` after each game is simmed.
    """

    _by_team: Dict[int, _TeamGoalieRest] = field(default_factory=dict)

    def _team_state(self, tid: int) -> _TeamGoalieRest:
        if tid not in self._by_team:
            self._by_team[tid] = _TeamGoalieRest()
        return self._by_team[tid]

    def record_start(self, tid: int, starter_pid: int, day: int) -> None:
        """Update rest bookkeeping for ``tid`` after a game on ``day`` started by
        ``starter_pid``. Call this once per team per simmed game, right after the starter is
        actually chosen (whether via ``choose_starting_goalie`` or any other path -- e.g. a
        team with only one healthy goalie).

        Whoever DIDN'T start this game has their own streak reset to 0 (not just left stale) --
        a goalie's "consecutive starts" streak must reflect ONLY an unbroken run of starts, so
        the moment the other goalie starts even once, this goalie's streak is back to zero, not
        whatever it happened to be the last time he started. Leaving a stale nonzero streak
        around was a real bug: it made ``choose_starting_goalie``'s
        ``STARTER_MAX_CONSECUTIVE_STARTS`` check see a goalie as perpetually "at max streak"
        forever after the first forced rotation, permanently locking the rotation onto the other
        goalie instead of switching back once the intended rest period ended.
        """
        state = self._team_state(tid)
        state.consecutive_starts[starter_pid] = state.consecutive_starts.get(starter_pid, 0) + 1
        for pid in list(state.consecutive_starts.keys()):
            if pid != starter_pid:
                state.consecutive_starts[pid] = 0
        state.last_starter_pid = starter_pid
        state.last_game_day = day

    def played_yesterday_relative_to(self, tid: int, day: int) -> bool:
        """True if ``tid``'s most recently recorded game was on ``day - 1`` (a true
        back-to-back window relative to a game being decided ON ``day``). Computed live against
        the CURRENT query's ``day`` rather than cached at record time -- "yesterday" is only a
        meaningful question relative to the game currently being scheduled, not a fact knowable
        when the previous game was recorded."""
        state = self._by_team.get(tid)
        if state is None or state.last_game_day is None:
            return False
        return day - state.last_game_day == 1

    def games_since_last_start(self, tid: int, pid: int) -> int:
        """How many of this team's games (that this tracker has seen) have passed since ``pid``
        last started. Returns a large number (effectively "fully rested / unknown") if this
        tracker has no history for the goalie yet -- a fresh tracker (new season, or a reloaded
        save, see module docstring) treats every goalie as rested by default."""
        state = self._by_team.get(tid)
        if state is None or state.last_starter_pid is None:
            return 999
        if state.last_starter_pid == pid:
            return 0
        return 999   # the OTHER goalie started last -- "since last start" for pid is unknown/old;
                     # treated as fully rested rather than tracking a full history per goalie.


def choose_starting_goalie(team: Team, rest_state: GoalieRestState, *, day: int, rng) -> int:
    """Pick which of ``team``'s two rostered goalies starts today's game.

    Falls back gracefully:
    - No backup rostered (or backup missing) -> always the starter.
    - No starter rostered at all (shouldn't happen post-leaguegen, but never crash) -> whichever
      of starter/backup exists, or the team's original ``goalie_starter`` value (possibly
      ``None``) if neither is set.

    Decision shape (a simple tendency model, not a hard schedule):
      1. If the team has no backup, or the backup is somehow the same id as the starter, start
         the (only) starter.
      2. If the presumptive starter (``team.goalie_starter``) has already started
         ``STARTER_MAX_CONSECUTIVE_STARTS`` games in a row, give the backup a look (rest night).
      3. Else if the backup has started ``BACKUP_MAX_CONSECUTIVE_STARTS`` in a row (the starter
         was resting for a stretch), pull the starter back in (the job doesn't change hands
         permanently).
      4. Else if the presumptive starter would be going on a true back-to-back (this team played
         yesterday AND that same goalie started yesterday's game), usually (not always --
         ``BACK_TO_BACK_AVOID_PROB``) hand it to the backup instead.
      5. Otherwise, the presumptive starter goes -- this is the common case, and is what drives
         the ~55-65-of-82 starts-per-season split DEVPLAN.md targets (the exceptions above only
         fire on a minority of nights).
    """
    starter = team.goalie_starter
    backup = team.goalie_backup

    if starter is None:
        return backup if backup is not None else starter  # type: ignore[return-value]
    if backup is None or backup == starter:
        return starter

    team_state = rest_state._team_state(team.tid)
    starter_streak = team_state.consecutive_starts.get(starter, 0)
    backup_streak = team_state.consecutive_starts.get(backup, 0)

    if starter_streak >= STARTER_MAX_CONSECUTIVE_STARTS:
        return backup

    if backup_streak >= BACKUP_MAX_CONSECUTIVE_STARTS:
        return starter

    would_be_back_to_back = (team_state.last_starter_pid == starter
                             and rest_state.played_yesterday_relative_to(team.tid, day))
    if would_be_back_to_back and rng.chance(BACK_TO_BACK_AVOID_PROB):
        return backup

    return starter
