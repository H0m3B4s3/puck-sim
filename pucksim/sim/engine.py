"""Shift/event-based game simulation (5v5 ONLY, MVP scope -- DEVPLAN.md Step 1.12).

The engine resolves one shift at a time: faceoff (period start / after a goal only -- no
penalty/icing/offside stoppages yet, that's Step 2.3) -> zone entry -> a sequence of shot
attempts/rebounds/turnovers -> a stoppage (goal) or the shift clock running out -> line change.
Skaters and the goalie tire as shifts accumulate; the realization model (``pucksim.sim.ratings``:
morale x chemistry x composure) scales the skill *gap* between opposing ratings on every shot
attempt, the same mechanism HoopR uses for shot/defense resolution. Coach ``shot_volume``/
``shot_quality_bias`` (models/coach.py's ``CoachProfile``) modulate a team's shot-attempt
frequency/quality for their shifts on offense -- the first place these two knobs actually get
consumed, per coach.py's own docstring.

Mirrors HoopR's ``hoopsim/sim/engine.py`` control-flow shape directly: a ``_TeamState`` inner
class tracking on-ice personnel/fatigue/ice-time, a ``GameSim`` class, and the resumable-generator
pattern (``coach_session()`` yields a decision-point view at every natural stoppage -- here, after
every goal -- resumable via ``.send(orders)``; ``play()`` drives it synchronously via a bare
``next()``/``.send(None)`` loop). No live-coaching consumer exists yet (that's a later web-layer
feature per DESIGN.md), but the scaffolding is built now so that consumer never needs an engine
rewrite -- it will plug in by supplying real orders through the same generator seam.

MVP scope constraints (do not add scope here -- see DEVPLAN.md's explicit exclusions):
- 5v5 only. No penalty engine, no PP/PK, no goalie-pull, no shootout.
- Faceoffs only at period start and immediately after a goal.
- OT is a clearly-commented provisional placeholder (simplified 5v5 sudden death, one extra
  period, unresolved ties left as ``went_ot=True`` with no shootout) -- real 3-on-3/shootout
  resolution is Step 2.6.
- Fatigue resets every game; it never persists across games in this step (Step 2.2 territory).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pucksim import config
from pucksim.models.coach import Coach, CoachProfile
from pucksim.models.player import Player
from pucksim.models.team import Team, lineup_familiarity_secs
from pucksim.models.world import World
from pucksim.sim import ratings as R
from pucksim.sim.boxscore import (
    EVENT_FACEOFF,
    EVENT_GAME_END,
    EVENT_GOAL,
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
GOAL_HOT_HAND_NUDGE = 0.015           # small goalie "hot hand" bump per consecutive save, capped
GOAL_HOT_HAND_MAX = 0.06
REBOUND_CHANCE_BASE = 0.22            # probability an unconverted on-goal shot produces a rebound
SHIFT_SECONDS_JITTER = 8.0            # +/- gaussian spread around config.SHIFT_SECONDS_TARGET

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

    def __init__(self, world: World, team: Team, is_home: bool) -> None:
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
        self.on_ice: List[int] = []           # 5 skaters, current shift (3F + 2D)
        self.goalie_id: Optional[int] = team.goalie_starter

        # Fatigue (0..100, resets every game -- persistence across games is Step 2.2 scope).
        self.fatigue: Dict[int, float] = {pid: 0.0 for pid in team.roster}
        self.shift_count: Dict[int, int] = {pid: 0 for pid in team.roster}

        # Live coach profile, reconstructed once at game start (models/coach.py's documented
        # pattern: Team.coach is a serialized dict, not a live CoachProfile).
        self.coach_profile: CoachProfile = self._resolve_coach_profile(team)

        self.cache: Optional[R.OnIceCache] = None

        # Goalie "hot hand": a small rolling nudge, mean-reverting, reset at game start (simple
        # fit per DEVPLAN.md -- "you may add a simple goalie hot hand nudge if it's a clean fit").
        self.goalie_hot_hand: float = 0.0

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
    def rotate_on_ice(self) -> None:
        """Round-robin to the next forward line + D pair (line 0->1->2->3->0.., pair 0->1->2->0..)
        and rebuild the on-ice skater group + its ratings cache. On-ice group is a plain
        ``List[int]`` built by concatenating a forward line + a D pair (DESIGN.md point 1 -- never
        a hard Line/Pair object)."""
        lines = self.team.lines
        pairs = self.team.pairs
        line = lines[self._line_idx % len(lines)] if lines else []
        pair = pairs[self._pair_idx % len(pairs)] if pairs else []
        self.on_ice = list(line) + list(pair)
        self._line_idx = (self._line_idx + 1) % max(1, len(lines))
        self._pair_idx = (self._pair_idx + 1) % max(1, len(pairs))
        for pid in self.on_ice:
            self.shift_count[pid] = self.shift_count.get(pid, 0) + 1
        self._rebuild_cache()

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
    """Simulates one 5v5-only game between two teams drawn from ``world``.

    Usage: ``GameSim(world, home_tid, away_tid).play()`` for headless simulation (this step's
    actual use case). The resumable ``coach_session()`` generator is exposed for a future
    live-coaching consumer (web layer, not built yet) -- ``play()`` is just a synchronous driver
    over it with no real decisions made.
    """

    def __init__(self, world: World, home_tid: int, away_tid: int, *,
                 collect_pbp: bool = False) -> None:
        self.world = world
        self.rng = world.rng
        self.collect_pbp = collect_pbp
        self.home = _TeamState(world, world.team(home_tid), is_home=True)
        self.away = _TeamState(world, world.team(away_tid), is_home=False)
        self.result = GameResult(home_tid=home_tid, away_tid=away_tid)
        self.period = 1
        self.game_secs = 0.0     # elapsed game time, monotonically increasing across periods/OT
        self._is_ot = False

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
        for state in (self.home, self.away):
            state.rotate_on_ice()

        for p in range(1, config.PERIODS + 1):
            self.period = p
            yield from self._play_period(config.PERIOD_SECONDS)

        # -- provisional OT placeholder -----------------------------------
        # DEVPLAN.md: MVP needs "a clearly-commented provisional tie-break or simple sudden-death
        # placeholder" since real OT (3-on-3) / shootout resolution is v1 scope (Step 2.6). This
        # runs ONE extra simplified period using the same 5v5 shift logic (not 3-on-3 -- that
        # strength state doesn't exist until Step 2.1) until either team scores or the period time
        # runs out, in which case the game is left as an unresolved tie with went_ot=True and
        # went_so always False (shootouts don't exist yet). Real NHL OT/SO resolution replaces this
        # whole block in Step 2.6.
        if self.result.home_score == self.result.away_score:
            self._is_ot = True
            self.result.went_ot = True
            self.period += 1
            yield from self._play_period(config.OT_SECONDS_REGULAR_SEASON, sudden_death=True)

    # -- period / shift loop ---------------------------------------------------
    def _play_period(self, length_secs: float, sudden_death: bool = False):
        """Run shifts until ``length_secs`` of clock has elapsed (or, in sudden death, until a goal
        is scored). A generator: yields a decision-point view immediately after any goal."""
        clock = length_secs
        # Faceoff at the start of every period (MVP scope: faceoffs only at period start / after a
        # goal -- no icing/offside/penalty stoppages yet, that's Step 2.3).
        self._log_faceoff()

        while clock > 0:
            shift_secs = max(15.0, self.rng.gauss(config.SHIFT_SECONDS_TARGET, SHIFT_SECONDS_JITTER))
            shift_secs = min(shift_secs, clock)
            goal_scored = yield from self._play_shift(shift_secs)
            clock -= shift_secs
            self.game_secs += shift_secs
            if goal_scored:
                if sudden_death:
                    clock = 0.0   # sudden death ends immediately on a goal
                    break
                # Faceoff at center ice restarts play after a goal (MVP scope: the only other
                # legal faceoff trigger besides period start).
                if clock > 0:
                    self._log_faceoff()

        self._log(EVENT_PERIOD_END, f"End of period {self.period}")

    def _play_shift(self, shift_secs: float):
        """Resolve one shift: possession from the faceoff/rush, a sequence of shot attempts until
        the shift clock elapses or a goal is scored, then apply ice-time/fatigue and rotate both
        teams' on-ice groups for next shift. Returns True (via StopIteration value on `yield from`
        callers, or just the return value here) if a goal was scored this shift. A generator only
        insofar as it yields at a goal stoppage (see coach_session's docstring) -- for a shift with
        no goal it never yields."""
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
        for state in (self.home, self.away):
            state.rotate_on_ice()
        return goal_scored

    def _shot_attempt_interval(self, offense: _TeamState) -> float:
        """Seconds until the next shot attempt, scaled by the offense's coach shot_volume."""
        mult = R.shot_volume_multiplier(offense.coach_profile.shot_volume)
        mean_interval = config.SHIFT_SECONDS_TARGET / (BASE_SHOT_ATTEMPTS_PER_SHIFT * mult)
        return max(2.0, self.rng.gauss(mean_interval, mean_interval * 0.35))

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
        high-percentage shot type)."""
        bias = R.shot_quality_bias_delta(offense.coach_profile.shot_quality_bias)
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
        "rebound"."""
        if not offense.on_ice or not defense.on_ice or defense.goalie_id is None:
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

        gap = (shot_skill - goalie_skill) * 0.0035
        # Small zone/shot-type quality bonus feeds directly into the on-goal/quality of the
        # attempt, not just selection -- a high-danger attempt that does get through is more likely
        # to beat the goalie.
        quality = 0.5 * _ZONE_QUALITY[zone] + 0.5 * _SHOT_TYPE_QUALITY[shot_type]
        rush_bonus = 0.03 if rush else 0.0

        goalie_hot_hand = defense.goalie_hot_hand if goalie is not None else 0.0

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

        # Attempt reached the goalie: charge SOG + shots_faced, then resolve save vs. goal.
        self.result.skater_line(shooter.pid).sog += 1
        if goalie is not None:
            self.result.goalie_line(goalie.pid).shots_faced += 1

        save_p = max(0.55, min(0.97, 0.90 - (quality - 0.5) * 0.35 - rush_bonus
                                - gap * off_real + goalie_hot_hand))
        # def_real scales the goalie's realized share of their save probability edge over a
        # neutral 0.90 baseline, mirroring HoopR's shooter/defender gap-parity approach.
        save_p = max(0.55, min(0.97, 0.90 + (save_p - 0.90) * def_real))
        saved = self.rng.chance(save_p)

        if saved:
            if goalie is not None:
                self.result.goalie_line(goalie.pid).saves += 1
                defense.goalie_hot_hand = min(GOAL_HOT_HAND_MAX,
                                              defense.goalie_hot_hand + GOAL_HOT_HAND_NUDGE)
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

        for pid in offense.on_ice:
            self.result.skater_line(pid).plus_minus += 1
        for pid in defense.on_ice:
            self.result.skater_line(pid).plus_minus -= 1

        if goalie is not None:
            self.result.goalie_line(goalie.pid).goals_against += 1
            defense.goalie_hot_hand = 0.0   # a goal resets any hot-hand nudge

        self._log_shot(offense, defense, shooter, goalie, zone, shot_type, rush, rebound,
                      SHOT_OUTCOME_GOAL, assist_pid=assist_pid, secondary_pid=secondary_pid)

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
              player_id: Optional[int] = None) -> None:
        if not self.collect_pbp:
            return
        self.result.pbp.append(PBPEvent(
            period=self.period, time_secs=self.game_secs, event_type=event_type,
            description=description, home_score=self.result.home_score,
            away_score=self.result.away_score, team_id=team_id, player_id=player_id,
        ))

    def _log_shot(self, offense: _TeamState, defense: _TeamState, shooter: Player,
                  goalie: Optional[Player], zone: str, shot_type: str, rush: bool,
                  rebound: bool, outcome: str, *, assist_pid: Optional[int] = None,
                  secondary_pid: Optional[int] = None) -> None:
        if not self.collect_pbp:
            return
        event_type = EVENT_GOAL if outcome == SHOT_OUTCOME_GOAL else EVENT_SHOT
        desc = f"{shooter.short_name} {shot_type} shot from the {zone} -- {outcome}"
        self.result.pbp.append(PBPEvent(
            period=self.period, time_secs=self.game_secs, event_type=event_type,
            description=desc, home_score=self.result.home_score, away_score=self.result.away_score,
            team_id=offense.tid, player_id=shooter.pid, assist_player_id=assist_pid,
            secondary_assist_player_id=secondary_pid,
            goalie_id=goalie.pid if goalie is not None else None,
            shot_type=shot_type, zone=zone, strength_state=config.STRENGTH_5V5,
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
                   collect_pbp: bool = False) -> GameResult:
    """Convenience wrapper: simulate one game and return its result."""
    return GameSim(world, home_tid, away_tid, collect_pbp=collect_pbp).play()
