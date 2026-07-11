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

Faceoffs, injuries, icing/offside stoppages (DEVPLAN.md Step 2.3): faceoffs now happen at every
stoppage type -- period start, after a goal, a drawn penalty, AND two new stoppage types this
step adds (icing, offside), each rolled for once per shift of continued play per
``FACEOFF_STOPPAGE_*`` constants below -- and the winner now actually GATES the following shift's
starting possession (``_play_shift`` no longer flips a raw 50/50 coin for the starting
offense/defense; it reads the just-resolved faceoff winner instead). Faceoff resolution itself is
a three-way roll (home center clean win / away center clean win / a contested tie), not a two-way
coin flip -- see ``_resolve_faceoff``'s docstring for the full shape, including the winger
secondary roll that breaks a tie. ``_current_center`` no longer assumes LW-C-RW list ordering
(that assumption silently broke for a PP/PK on-ice group, which is ranked by composite score, not
position) -- it now looks up each on-ice player's actual ``position`` field.

In-game injuries (DEVPLAN.md Step 2.3): ``_injury_check`` rolls each on-ice skater, once per
shift, for an in-game injury (``config.IN_GAME_INJURY_RATE``, ported from HoopR's sport-agnostic
shape -- see ``_injury_severity``); an injured player is pulled from their team's rotation pool
for the REST OF THE GAME (``_TeamState.unavailable``) and a fresh on-ice group is rebuilt
immediately. Line/pair construction and the shift rotation pool both route through
``models.team.available_players``-equivalent filtering (``Player.available``) so an injured
player is never iced again once hurt, whether mid-game or (via ``Injury.games_remaining``
persisting on ``Player`` across games) in a future game while still recovering.
``sim/season.py``'s ``advance_one_day`` heals one game's worth of recovery off every active
injury right after the day's games are simmed, per that module's own documented hook point.

Coach line-juggling AI (DEVPLAN.md Step 2.8): ``CoachProfile.line_juggling_patience`` (defined
back in Step 1.10, never consumed until now) finally gets a real consumer -- a patience-gated
forward-line/D-pair reshuffle trigger, checked once per REGULATION intermission (end of every
regulation period, 1 through 3, including the intermission right before OT -- a real one too;
OT/shootout periods themselves are excluded, same ``is_regulation`` gate the goalie-pull
mechanic above uses). This is a genuinely open-ended mechanic DEVPLAN.md deliberately left unspecified
beyond naming the knob and a plausible signal ("on-ice goal differential per combo") -- three
judgment calls made here, each flagged clearly since a future step may want to revisit them:

1. **What "combo" means.** Tracked per SLOT (index into ``team.lines``/``team.pairs`` -- line 0,
   line 1, D-pair 0, etc.), not per exact personnel set. This coincides exactly with tracking by
   personnel for as long as a slot goes unshuffled (nothing else in this codebase reorders
   ``team.lines``/``team.pairs`` mid-game), and a reshuffle deliberately resets the swapped
   slots' tracked diff back to 0.0 anyway (a freshly-assembled combo has no track record yet) --
   so the distinction between "slot" and "personnel" never actually matters in practice. Slot
   tracking is simpler bookkeeping (fixed-size ``Dict[int, float]``, no set-hashing/matching
   logic for a combo that partially changes via an injury backfill) and was chosen for exactly
   that reason -- DEVPLAN.md's own "reasonable first pass, don't over-engineer" framing.
2. **The signal itself: on-ice goal differential per combo, 5v5-only.** ``_update_combo_diff``
   credits/debits the CURRENT line-slot and pair-slot by +/-1.0 whenever a goal is scored while
   the strength state is ``STRENGTH_5V5`` -- gated on 5v5 specifically because during a PP/PK the
   on-ice group is the special-teams unit (``team.pp_unit_1``/``pk_unit_1``), not the normal
   line/pair rotation; crediting/blaming a round-robin slot for a special-teams goal would
   misattribute it to whichever combo happens to be next up, not who was actually on the ice.
   No separate "minimum sample size" gate exists beyond the threshold's own magnitude
   (``COMBO_COLD_GOAL_DIFF_THRESHOLD``) -- an NHL-shaped game only has ~3 goals/team, so
   requiring 2 net unanswered goals against the SAME slot to call it "cold" already implies that
   slot took the ice for a meaningful chunk of the game without answering back, without needing
   separate shift-count bookkeeping.
3. **The reshuffle mechanic: a random single-slot-position swap between two lines/pairs**, not a
   full rebuild. ``_swap_line_slot``/``_swap_pair_slot`` pick one other line/pair at random and
   swap ONE slot position (e.g. the LW) between the cold combo and that other combo -- a
   real-hockey-shaped "the coach broke up a cold line by moving one guy" move, not "the coach
   nuked all 12 forwards and re-drafted from scratch." Deliberately NOT routed through
   ``auto_build_lines``'s fit-score optimizer -- that function is DETERMINISTIC (always produces
   the same best-fit assignment for a given roster), so calling it here would either produce no
   visible change (if it just reproduces the existing best-fit lines) or would silently discard
   the "shake things up, not optimize" intent of a reactive coach's in-game reshuffle.

Reshuffle probability is patience-gated (``LINE_JUGGLE_BASE_RESHUFFLE_CHANCE * (1.0 -
patience)`` -- see ``_maybe_juggle_lines_for_team``): a patience-0.0 coach reshuffles a cold
combo readily (90% per eligible intermission check), a patience-1.0 coach never does (``Rng.
chance`` returns ``False`` outright for a non-positive probability, no draw consumed) --
matching the "LOW patience juggles readily, HIGH patience sticks with lines longer" behavior
``CoachProfile.line_juggling_patience``'s own docstring already promised back in Step 1.10.

This is a LINEUP DECISION, not a realization mechanic (morale/clutch/fatigue/hot-hand) -- the
codebase's "no upweighting" principle (ratings.py's ``hot_hand_boost()`` docstring) constrains
mechanics that could push a player's effective rating above its ceiling; reshuffling WHO plays
together doesn't touch any rating/probability formula, so that principle doesn't apply here.
Nothing from ``models/tactics.py``'s new PP/PK style fields (``pp_style``/``pk_aggression``,
also added this step) feeds into any shot-quality/save-probability computation either -- see
that module's own docstring for why those stay pure data for now, same as ``forecheck_style``
did through the whole MVP.

Scope constraints this step still does NOT add (do not add scope here -- see DEVPLAN.md's
explicit exclusions for later steps):
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
from pucksim.models.team import Team, available_players, lineup_familiarity_secs
from pucksim.models.world import World
from pucksim.sim import ratings as R
from pucksim.sim import special_teams as ST
from pucksim.sim.boxscore import (
    EVENT_FACEOFF,
    EVENT_GAME_END,
    EVENT_GOAL,
    EVENT_INJURY,
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
from pucksim.systems.development import GoalieFormState, apply_goalie_form

# ---------------------------------------------------------------------------
# Tunables -- PROVISIONAL/first-pass, same framing as every other unresolved constant in this
# codebase (config.py's own development/injury placeholders, gen/leaguegen.py's age/overall
# distributions, etc.). Real balancing needs actual simulated-season data, which doesn't exist
# until this step ships.
# ---------------------------------------------------------------------------
BASE_SHOT_ATTEMPTS_PER_SHIFT = 0.9    # league-average expected shot attempts per shift, per team
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
# In-game injuries (DEVPLAN.md Step 2.3). ``config.IN_GAME_INJURY_RATE`` is the shared
# per-on-ice-player, per-shift base rate (already tuned to a "per shift" cadence, not HoopR's
# "per possession" one -- see config.py's own comment: "a full-game player faces roughly 20-25
# shifts"); everything below is the hockey-specific severity/duration model layered on top,
# ported near-verbatim in SHAPE from HoopR's ``_injury_severity()`` (see that function's
# docstring in hoopsim/sim/engine.py) with hockey-appropriate games-missed bands (an NHL season
# is 82 games, materially longer than an NBA season pass-through would imply, so the bands below
# are hockey's own magnitudes, not a literal copy of HoopR's numbers).
# ---------------------------------------------------------------------------
INJURY_MINOR_P = 0.60      # cumulative probability roll lands in the "minor" band (roughy
                           # "day-to-day", a game or two)
INJURY_MODERATE_P = 0.90   # cumulative through "moderate" (a couple of weeks) -- the remaining
                           # 1.0 - 0.90 tail is "major" (a long-term IR-type absence)
INJURY_MINOR_GAMES = (1, 3)
INJURY_MODERATE_GAMES = (4, 12)
INJURY_MAJOR_GAMES = (15, 45)

# Durability proxy (DEVPLAN.md doesn't define a standalone "durability" skater rating -- see
# attributes.py's ALL_RATINGS; unlike HoopR, which has one). ``stamina`` (Physical group) is the
# closest existing fit conceptually (a wearier/less conditioned player is more injury-prone), so
# it's reused here as the modifier input rather than inventing a new rating this step wasn't
# asked to add. Centered on the same 70 "average" anchor used everywhere else in this codebase.
INJURY_STAMINA_ANCHOR = 70
INJURY_STAMINA_SLOPE = 0.01   # matches HoopR's own durability-modifier slope shape/magnitude

# ---------------------------------------------------------------------------
# Pull-the-goalie / extra-attacker tunables (DEVPLAN.md Step 2.2). The actual trigger thresholds
# (deficit/time-remaining) come from each team's own CoachProfile
# (``goalie_pull_max_deficit``/``goalie_pull_time_threshold_secs``, models/coach.py) -- these are
# just the mechanic-level constants that aren't coach-specific.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Coach line-juggling AI (DEVPLAN.md Step 2.8). See this module's docstring's "Coach
# line-juggling AI" section for the full design rationale/judgment calls; these are just the
# tunable magnitudes.
# ---------------------------------------------------------------------------
COMBO_COLD_GOAL_DIFF_THRESHOLD = -2.0   # a line-slot/pair-slot's accumulated 5v5 on-ice goal
                                        # differential (this game only, reset every game -- no
                                        # cross-game carryover, same framing as fatigue) at or
                                        # below this value is "cold" and becomes reshuffle-
                                        # eligible at the next regulation intermission.
                                        # Provisional/tunable: with an NHL-shaped game averaging
                                        # ~3 goals/team, requiring 2 net unanswered goals against
                                        # the SAME slot is already a real, fairly rare signal, not
                                        # a hair-trigger that reshuffles on the first bad goal.
LINE_JUGGLE_BASE_RESHUFFLE_CHANCE = 0.9   # reshuffle probability for the most reactive
                                          # (line_juggling_patience == 0.0) coach when a combo is
                                          # cold; scaled down linearly to 0 at patience == 1.0
                                          # (see _maybe_juggle_lines_for_team). Not literally
                                          # 100% even for the most reactive coach -- some
                                          # restraint always, matching every other "coach
                                          # tendency modulates a probability, never a certainty"
                                          # pattern elsewhere in this module (goalie-pull,
                                          # penalty probability, etc.).

EMPTY_NET_GOAL_BASE_P = 0.55   # a shot that reaches an empty net (no goalie to resolve a save
                               # against) scores at a high but not-quite-certain rate per
                               # attempt -- misses/blocks still happen even into an empty net.
PULL_RETURN_LEAD_SWING = 1     # if the pulled team's deficit ever WORSENS by this many goals
                               # relative to when they pulled, put the goalie back (a blown pull
                               # attempt shouldn't compound into an even worse empty-net
                               # disaster) -- see _maybe_return_goalie.

# ---------------------------------------------------------------------------
# Faceoff stoppage types (DEVPLAN.md Step 2.3). ``EVENT_FACEOFF``'s new ``stoppage_type`` PBP
# context field is populated with one of these strings so a later step can tell WHY a faceoff
# happened, not just that it happened. "penalty" faceoffs are logged from the same call site
# that already refreshes on-ice groups for a newly-drawn penalty (_draw_penalty) -- a real
# stoppage in real hockey, and this step's own intro note explicitly calls out that a
# penalty-drawn stoppage's faceoff needed Step 2.1's penalty engine to exist first.
# ---------------------------------------------------------------------------
FACEOFF_PERIOD_START = "period_start"
FACEOFF_AFTER_GOAL = "after_goal"
FACEOFF_ICING = "icing"
FACEOFF_OFFSIDE = "offside"
FACEOFF_PENALTY = "penalty"

# Icing/offside stoppage probabilities (DEVPLAN.md: "invent a reasonable small set" framing
# extends to these too -- no real NHL icing/offside-rate data is being fit here, just plausible
# per-shot-attempt-cycle magnitudes). Checked once per shot-attempt interval within a shift (the
# same cadence _play_shift already advances the strength clock at) rather than continuously, so
# a busy shift with more attempts has proportionally more chances to see a stoppage -- a
# reasonable proxy for "more zone-entry/clearing attempts happened this shift."
ICING_CHANCE_PER_ATTEMPT_CYCLE = 0.030   # a clearing attempt sails the length of the ice untouched
OFFSIDE_CHANCE_PER_ATTEMPT_CYCLE = 0.025  # a zone entry is blown offside

# ---------------------------------------------------------------------------
# Faceoff resolution (DEVPLAN.md Step 2.3's "Three-way faceoff resolution" design note). See
# _resolve_faceoff's docstring for the full three-way-roll + winger-tiebreak shape this feeds.
# ---------------------------------------------------------------------------
FACEOFF_WIN_BASE = 0.50               # coin-flip baseline before rating gap / realization
                                       # (unchanged from the old two-way model's baseline --
                                       # this is still the anchor a dead-even center matchup
                                       # centers on before the tie slice is carved out)
FACEOFF_TIE_BASE_P = 0.18             # baseline probability a center-vs-center draw is
                                       # genuinely contested (a scrum) rather than a clean win
                                       # for either side, before any rating-gap adjustment --
                                       # provisional/tunable, same framing as every other
                                       # first-pass constant in this codebase. A larger rating
                                       # gap between the two centers makes a clean win more
                                       # likely and a tie less likely (a mismatched draw is
                                       # less often a genuine 50/50 scrum) -- see
                                       # _resolve_faceoff for the exact shape.
FACEOFF_TIE_GAP_SUPPRESSION = 0.004   # how much a |rating gap| point reduces the tie
                                       # probability below FACEOFF_TIE_BASE_P

# Winger secondary roll (the tie-break path): same realization-scaled gap-to-probability shape
# as the primary center roll (FACEOFF_WIN_BASE/the 0.004 gap coefficient in _resolve_faceoff),
# just over a different rating blend (puck_handling + offensive_awareness/defensive_awareness
# -- DEVPLAN.md's explicit "hockey IQ" proxy, since no standalone rating exists for that).
FACEOFF_WINGER_GAP_COEFFICIENT = 0.004

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


def _shootout_shooter_score(player: Player) -> float:
    """Shooter-selection composite for shootout ordering (DEVPLAN.md Step 2.6): favors
    shot_accuracy/puck_handling/offensive_awareness, the same blend ``_resolve_shot_attempt``'s
    ``shot_skill`` uses for a normal shot attempt (kept identical so shootout shooter ranking is
    consistent with who's actually good at scoring in this engine's own model, not a bespoke
    separate "shootout skill" this codebase doesn't otherwise track)."""
    r = player.ratings
    return (0.5 * r.get("shot_accuracy", 25) + 0.3 * r.get("puck_handling", 25)
            + 0.2 * r.get("offensive_awareness", 25))


def _winger_iq_score(player: Player) -> float:
    """Winger secondary-faceoff-tiebreak composite (DEVPLAN.md Step 2.3's design note): puck
    handling + an offensive/defensive-awareness blend, this codebase's closest existing proxy
    for "hockey IQ" / hands in a scrum (no standalone rating exists for either, per
    ``models/attributes.py``). Both awareness ratings contribute (a winger who reads the play
    offensively AND defensively is better positioned to pounce on a loose puck either way),
    weighted evenly since neither is obviously more relevant to a 50/50 scrum recovery than the
    other."""
    r = player.ratings
    return (0.5 * r.get("puck_handling", 25)
            + 0.25 * r.get("offensive_awareness", 25)
            + 0.25 * r.get("defensive_awareness", 25))


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

        # In-game-injury tracking (DEVPLAN.md Step 2.3). ``unavailable`` starts seeded with
        # anyone ALREADY injured coming into this game -- via team.py's ``available_players()``
        # filter (the same helper DEVPLAN.md's Step 2.3 assignment calls out to confirm/wire in),
        # inverted to the roster ids NOT in that available set, since _TeamState needs a live set
        # it can keep adding to mid-game, not a one-shot list -- so a player still recovering
        # from a previous game's injury is never iced; ``_injury_check`` adds to this set for a
        # freshly-injured player mid-game. Every rotation-pool consumer below (the line/pair
        # round-robin, PP/PK unit selection, the pulled-goalie extra-attacker pick) filters
        # through this set so an unavailable player never gets fielded, whether hurt before
        # puck-drop or mid-shift.
        available_ids = {p.pid for p in available_players(team, self.players)}
        self.unavailable: set = {pid for pid in team.roster if pid not in available_ids}

        # Round-robin rotation pointers into team.lines / team.pairs (MVP: no line-juggling AI,
        # just a fixed deterministic rotation so ice time distributes across the whole roster --
        # DEVPLAN.md's explicit instruction).
        self._line_idx = 0
        self._pair_idx = 0
        self.on_ice: List[int] = []           # 5 (or 6, pulled-goalie) skaters, current shift

        # Line-juggling AI (DEVPLAN.md Step 2.8): the line-slot/pair-slot index actually used
        # THIS shift (snapshotted in ``_next_normal_group`` before the round-robin pointer
        # advances) -- ``_score_goal`` reads these to credit/debit the right slot's on-ice
        # goal-differential tracker. ``line_combo_diff``/``pair_combo_diff`` map slot index ->
        # accumulated 5v5 on-ice goal differential THIS GAME ONLY (reset every game, same as
        # fatigue -- no cross-game carryover model exists for this either). See this module's
        # docstring for why tracking is per-SLOT rather than per-exact-personnel-set.
        self._current_line_idx = 0
        self._current_pair_idx = 0
        self.line_combo_diff: Dict[int, float] = {}
        self.pair_combo_diff: Dict[int, float] = {}
        self.reshuffle_count = 0   # total line/pair slot-swaps performed this game (test hook)
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

        Injury-aware (DEVPLAN.md Step 2.3): any id in ``self.unavailable`` (injured, this game or
        carried in from a previous one) is dropped from the line/pair before it's returned, and
        backfilled from ``rotation_pool``-equivalent bench bodies (any healthy rostered skater not
        already in the group this shift) so an injury never simply shrinks the on-ice group to 4
        -- a real coach fills the hole from the bench, not leaves a gap. ``team.lines``/
        ``team.pairs`` themselves are left untouched (static roster structure owned by
        ``auto_build_lines``, not a per-game mutation target); this is a per-shift read-time
        filter only.
        """
        lines = self.team.lines
        pairs = self.team.pairs
        self._current_line_idx = self._line_idx % len(lines) if lines else 0
        self._current_pair_idx = self._pair_idx % len(pairs) if pairs else 0
        line = lines[self._current_line_idx] if lines else []
        pair = pairs[self._current_pair_idx] if pairs else []
        self._line_idx = (self._line_idx + 1) % max(1, len(lines))
        self._pair_idx = (self._pair_idx + 1) % max(1, len(pairs))

        healthy_line = [pid for pid in line if pid not in self.unavailable]
        healthy_pair = [pid for pid in pair if pid not in self.unavailable]
        group = healthy_line + healthy_pair
        if len(healthy_line) < len(line) or len(healthy_pair) < len(pair):
            group = self._backfill_from_bench(group, len(line) + len(pair))
        return group

    def _backfill_from_bench(self, group: List[int], target_size: int) -> List[int]:
        """Top ``group`` back up to ``target_size`` bodies from any healthy rostered skater not
        already in it (DEVPLAN.md Step 2.3: an injured player's normal-rotation slot must be
        filled from the bench, not left empty). Goalies are never eligible fill-in bodies. Falls
        back to leaving ``group`` short if the whole roster is somehow already accounted for (an
        extreme-injury edge case) -- never crashes, matching this codebase's "thin bench" fallback
        philosophy elsewhere (e.g. ``_with_extra_attacker``)."""
        if len(group) >= target_size:
            return group
        on_ice_set = set(group)
        candidates = [pid for pid in self.team.roster
                      if pid not in on_ice_set and pid not in self.unavailable
                      and pid in self.players and self.players[pid].position != "G"]
        candidates.sort(key=lambda pid: self.players[pid].overall, reverse=True)
        result = list(group)
        for pid in candidates:
            if len(result) >= target_size:
                break
            result.append(pid)
        return result

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

        Injury-aware (DEVPLAN.md Step 2.3): ``self.unavailable`` is folded into the
        ``penalized_ids`` set passed to ``special_teams.on_ice_group_for_state`` -- that function
        already excludes any id in ``penalized_ids`` from BOTH the special-teams unit
        (``team.pp_unit_1``/``pk_unit_1``, which are static rosters that don't themselves know
        about injuries) and its bench-padding fallback, so this is the one seam that keeps an
        injured player off a PP/PK unit too, not just the normal-rotation line/pair path already
        handled in ``_next_normal_group``.
        """
        normal_group = self._normal_group
        state = strength_state or config.STRENGTH_5V5
        excluded_ids = set(penalized_ids or []) | self.unavailable
        if state == config.STRENGTH_5V5:
            self.on_ice = normal_group
        else:
            self.on_ice = ST.on_ice_group_for_state(
                self.team, state, normal_group=normal_group,
                skaters_needed=skaters_needed, penalized_ids=excluded_ids,
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
                      if pid not in on_ice_set and pid != self.goalie_id and pid in self.players
                      and pid not in self.unavailable]
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

    ``is_playoff`` (DEVPLAN.md Step 2.6): selects real OT shape -- regular season plays 3-on-3
    sudden death then (under a ``has_shootout=True`` standings rule) a separate shootout
    resolution model; playoffs play full 5-on-5 sudden-death periods, repeated until someone
    scores, and never shoot out (DESIGN.md point 8's explicit "different OT shape" for
    playoffs). Also gates the "Playoff officiating/discipline mode" design note's
    ``playoff_multiplier`` on the penalty-probability chain -- see ``_check_for_penalties``.
    Defaults to ``False`` (identical behavior to a regular-season game for any existing caller
    that doesn't opt in).
    """

    def __init__(self, world: World, home_tid: int, away_tid: int, *,
                 collect_pbp: bool = False,
                 home_goalie_id: Optional[int] = None,
                 away_goalie_id: Optional[int] = None,
                 is_playoff: bool = False,
                 form_state: Optional[GoalieFormState] = None) -> None:
        self.world = world
        self.rng = world.rng
        self.collect_pbp = collect_pbp
        self.is_playoff = is_playoff
        # Goalie season-form (DEVPLAN.md Step 2.7 / development.py): a per-season, symmetric
        # (may exceed 1.0), multiplicative scalar on each goalie's effective save skill, resampled
        # once per offseason and held for the whole season by the caller's GoalieFormState. None =
        # every goalie plays at their straight rating (baseline 1.0) -- keeps this a strict additive
        # extension for callers (tests, one-off sims) that don't thread a form state through.
        self.form_state = form_state
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

        # Playoff officiating/discipline mode (DEVPLAN.md Step 2.6 design note): resolved ONCE at
        # game construction (not re-checked every shift -- the rule doesn't change mid-game) into
        # a single ready-to-use multiplier passed straight to
        # special_teams.penalty_probability_for_shift on every _check_for_penalties call. Always
        # 1.0 (a no-op) for a non-playoff game or under "regular_season" mode -- see
        # config.PLAYOFF_REALISTIC_PENALTY_MULTIPLIER / World.playoff_discipline_mode.
        self.playoff_penalty_multiplier: float = 1.0
        if is_playoff and world.playoff_discipline_mode == "realistic":
            self.playoff_penalty_multiplier = config.PLAYOFF_REALISTIC_PENALTY_MULTIPLIER

        # Faceoff-gated possession (DEVPLAN.md Step 2.3): the ``_TeamState`` that won the most
        # recently resolved faceoff, consumed by the next ``_play_shift`` call to set that
        # shift's starting offense/defense instead of a raw coin flip -- see _play_shift's
        # docstring. ``None`` only before the very first faceoff of the game is resolved.
        self._pending_faceoff: Optional[_TeamState] = None

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

        # -- real OT/shootout resolution (DEVPLAN.md Step 2.6) -----------------
        # Replaces the MVP engine's provisional placeholder (one extra simplified 5v5 sudden-
        # death period, unresolved ties left as-is). DESIGN.md point 8's two explicit
        # requirements this implements:
        #   1. Regular season: 3-on-3 sudden death -> if still level, a SEPARATE shootout
        #      resolution model (not a continuation of normal shift/event simulation) under a
        #      has_shootout=True standings rule; "retro" skips the shootout and lets an
        #      undecided 3-on-3 period stand as a legitimate tie.
        #   2. Playoffs: full 5-on-5 sudden-death periods instead of 3-on-3, repeated until
        #      someone scores (capped at config.MAX_PLAYOFF_OT_PERIODS as a defensive stop
        #      condition for a headless sim loop -- see that constant's own comment), never a
        #      shootout, ever.
        # is_regulation=False for every OT period below: pull-the-goalie (Step 2.2) is an
        # explicit regulation-only, score-driven mechanic -- it never triggers (or stays active)
        # once the game reaches OT, matching the placeholder's original behavior.
        if self.result.home_score == self.result.away_score:
            self._is_ot = True
            self.result.went_ot = True

            if self.is_playoff:
                self.strength.base_state = config.STRENGTH_5V5
                ot_periods = 0
                while (self.result.home_score == self.result.away_score
                       and ot_periods < config.MAX_PLAYOFF_OT_PERIODS):
                    self.period += 1
                    ot_periods += 1
                    yield from self._play_period(config.OT_SECONDS_PLAYOFFS, sudden_death=True,
                                                  is_regulation=False)
                # A playoff game MUST have a winner (a series can't advance on a tie) -- the
                # ot_periods cap above is a defensive-only stop condition against a pathological
                # RNG stream, not a real NHL possibility (playoff OT genuinely has no shootout,
                # ever). If the cap is somehow hit with the score still level (astronomically
                # unlikely -- see MAX_PLAYOFF_OT_PERIODS's own comment), force a decision via the
                # same shootout resolution model rather than returning an illegal unresolved
                # playoff tie; this is the ONE case a playoff game can reach a shootout-shaped
                # resolution, and it is purely a defensive fallback, not real NHL playoff OT
                # rules (which have no shootout under any circumstance).
                if self.result.home_score == self.result.away_score:
                    self._resolve_shootout()
            else:
                self.strength.base_state = config.STRENGTH_3V3
                self.period += 1
                yield from self._play_period(config.OT_SECONDS_REGULAR_SEASON, sudden_death=True,
                                              is_regulation=False)

                if self.result.home_score == self.result.away_score:
                    rule_table = config.STANDINGS_RULES[self.world.standings_rule]
                    if rule_table["has_shootout"]:
                        self._resolve_shootout()
                    # else ("retro"): an undecided 3-on-3 OT stands as a legitimate tie -- do
                    # NOT invoke the shootout. league.py's Game.is_tie/went_ot handling already
                    # treats this correctly (went_ot=True, went_so=False, level score); see that
                    # module's docstring (fixed during Step 1.13's review) -- nothing here should
                    # regress it.

    # -- shootout resolution (DEVPLAN.md Step 2.6) -----------------------------
    def _resolve_shootout(self) -> None:
        """Resolve a still-level game via a shootout: a SEPARATE skills-competition resolution
        model (DESIGN.md point 8 -- explicitly "not a continuation of normal shift/event
        simulation"), not another sudden-death period run through the normal shot-attempt loop.

        Shape: alternating home/away one-on-one shooter-vs-goalie attempts. Each team gets
        ``config.SHOOTOUT_ROUNDS`` (3) attempts in the "standard round" unless the outcome is
        already mathematically decided before both teams have shot (e.g. up 2-0 after 2 rounds
        with the other team only shooting once left -- real NHL shootout rule: no point
        continuing a decided round). If still level after the standard round, alternating
        sudden-death rounds continue (one attempt each) until someone leads after a full
        exchange, capped at ``config.SHOOTOUT_MAX_SUDDEN_DEATH_ROUNDS`` as a defensive stop
        condition (see that constant's own comment) -- if the cap is somehow hit still level, the
        team with more career-average shootout aptitude... no such stat exists, so this falls
        back to the higher offensive-awareness/shot_accuracy composite shooter available, then a
        coin flip as an absolute last resort (never leaves the game unresolved -- a real NHL
        shootout by definition always ends decisively).

        A shootout goal is recorded directly onto ``self.result.home_score``/``away_score`` (the
        standard "the shootout-winning goal is the deciding goal of the game" convention --
        mirrors how season.py's now-removed MVP placeholder bumped the score by exactly one goal
        for the same reason: Game.winner/loser derive normally from home_score/away_score with no
        separate "decisive winner" side-channel field needed). Individual shootout attempts are
        NOT added to a shooter's regular skater box score (a real NHL shootout goal does not
        count as a regular-season goal in a player's stat line either -- it's tracked as its own
        separate shootout-attempts stat in real scorekeeping, which this codebase does not model
        as a tracked category; out of scope for this step, same "don't invent an untracked stat
        category" restraint DESIGN.md applies elsewhere) -- this function only ever touches the
        final score and ``went_so``.
        """
        self.result.went_so = True
        home_shooters = self._shootout_shooter_order(self.home)
        away_shooters = self._shootout_shooter_order(self.away)
        home_goalie = self.home.goalie()
        away_goalie = self.away.goalie()

        home_goals = 0
        away_goals = 0
        home_idx = 0
        away_idx = 0

        # -- standard round: up to SHOOTOUT_ROUNDS attempts each, alternating home/away,
        # stopping early once the outcome is mathematically decided (real NHL shootout rule).
        for rnd in range(config.SHOOTOUT_ROUNDS):
            if self._shootout_decided(home_goals, away_goals,
                                      config.SHOOTOUT_ROUNDS - rnd, config.SHOOTOUT_ROUNDS - rnd):
                break
            if self._shootout_attempt(home_shooters, home_idx, away_goalie):
                home_goals += 1
            home_idx += 1
            # Mid-round: home has already taken this round's attempt (its remaining count is
            # future rounds only, SHOOTOUT_ROUNDS - rnd - 1), but away has NOT yet taken its
            # attempt this round (its remaining count still includes this round's pending shot,
            # SHOOTOUT_ROUNDS - rnd). Passing (0, SHOOTOUT_ROUNDS - rnd - 1) here was a bug: it
            # underestimated BOTH sides' remaining attempts, which could declare the shootout
            # "decided" and skip away's still-legitimate pending attempt in this round (and any
            # future rounds home was still entitled to) -- confirmed via a scripted-attempt
            # reproduction (home 0-for-2, away 1-for-0-pending after round 1's home miss:
            # wrongly ended the shootout before away ever took its round-1 shot).
            if self._shootout_decided(home_goals, away_goals,
                                      config.SHOOTOUT_ROUNDS - rnd - 1, config.SHOOTOUT_ROUNDS - rnd):
                break
            if self._shootout_attempt(away_shooters, away_idx, home_goalie):
                away_goals += 1
            away_idx += 1

        # -- sudden death: one attempt each, repeated until decided.
        sd_rounds = 0
        while home_goals == away_goals and sd_rounds < config.SHOOTOUT_MAX_SUDDEN_DEATH_ROUNDS:
            sd_rounds += 1
            if self._shootout_attempt(home_shooters, home_idx, away_goalie):
                home_goals += 1
            home_idx += 1
            if self._shootout_attempt(away_shooters, away_idx, home_goalie):
                away_goals += 1
            away_idx += 1

        if home_goals == away_goals:
            # Defensive last resort (see docstring) -- should be vanishingly rare given the
            # sudden-death cap is 20 rounds. Break the tie with a neutral coin flip rather than
            # ever returning an unresolved shootout, which would violate the "a shootout always
            # ends decisively" invariant points_for_game()/Game.is_tie depend on.
            if self.rng.chance(0.5):
                home_goals += 1
            else:
                away_goals += 1

        if home_goals > away_goals:
            self.result.home_score += 1
        else:
            self.result.away_score += 1

        self._log(EVENT_GAME_END, "Shootout decides it")

    @staticmethod
    def _shootout_decided(home_goals: int, away_goals: int,
                          home_remaining: int, away_remaining: int) -> bool:
        """True if the outcome is already mathematically locked in given each side's remaining
        standard-round attempts (real NHL shootout early-stop rule) -- e.g. home leads by more
        goals than away could possibly still score."""
        if home_goals > away_goals + away_remaining:
            return True
        if away_goals > home_goals + home_remaining:
            return True
        return False

    def _shootout_shooter_order(self, state: _TeamState) -> List[Player]:
        """The shooting order for one team's shootout attempts: every eligible (healthy, non-
        goalie) rostered skater, best shot_accuracy/offensive_awareness composite first (a real
        NHL coach sends his best shootout options first) -- DEVPLAN.md doesn't specify a shooter-
        selection model, so this is a reasonable, clearly-provisional default rather than a
        random pick, matching this codebase's "reasonable simple model, not over-engineered"
        framing elsewhere. Falls back to cycling back through the same order if the sudden-death
        phase outlasts the roster (real NHL rule: once every eligible skater has shot once, a
        team may re-use shooters in the same order -- approximated here as "wrap around" rather
        than literally re-implementing the exact re-use-order NHL rule, since the distinction
        has no mechanical consequence for this resolution model)."""
        candidates = [state.players[pid] for pid in state.team.roster
                      if pid in state.players and pid not in state.unavailable
                      and state.players[pid].position != "G"]
        if not candidates:
            return []
        candidates.sort(key=_shootout_shooter_score, reverse=True)
        return candidates

    def _shootout_attempt(self, shooters: List[Player], idx: int,
                          goalie: Optional[Player]) -> bool:
        """Resolve one shootout attempt (a single shooter-vs-goalie skills-competition roll --
        NOT a continuation of the normal shift/shot-attempt loop, per this function's caller's
        docstring). Returns True if the attempt scores.

        Shape mirrors the engine's other realization-scaled gap-to-probability rolls (this
        codebase's "no upweighting" principle -- see ratings.py's hot_hand_boost() docstring and
        this session's own reaffirmed constraint): ``config.SHOOTOUT_BASE_SCORE_PROB`` is the
        neutral (rating-70-vs-rating-70) anchor, nudged by the shooter/goalie rating gap
        (``config.SHOOTOUT_RATING_GAP_SLOPE``) and scaled by the shooter's own morale realization
        (``ratings.morale_realization`` -- the same multiplicative, ceiling-capped-at-1.0 factor
        used everywhere else in this engine; it can only pull the gap back toward neutral, never
        push a shooter's effective conversion rate above what his rating gap alone would produce).
        An empty net (``goalie is None`` -- shouldn't happen in practice, a shootout never occurs
        with a pulled goalie since pulls are regulation-only, but defensive rather than crashing)
        resolves at a fixed high-but-not-certain rate, same shape as ``_resolve_empty_net_shot``.
        """
        if not shooters:
            return False
        shooter = shooters[idx % len(shooters)]
        r = shooter.ratings
        shot_skill = (0.5 * r.get("shot_accuracy", 25) + 0.3 * r.get("puck_handling", 25)
                      + 0.2 * r.get("offensive_awareness", 25))

        if goalie is None:
            return self.rng.chance(EMPTY_NET_GOAL_BASE_P)

        goalie_skill = self._goalie_skill(goalie)

        gap = (shot_skill - goalie_skill) * config.SHOOTOUT_RATING_GAP_SLOPE
        shooter_real = R.morale_realization(shooter.morale)
        score_p = config.SHOOTOUT_BASE_SCORE_PROB + gap * shooter_real
        score_p = max(0.05, min(0.85, score_p))
        return self.rng.chance(score_p)

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
        # Faceoff at the start of every period (DEVPLAN.md Step 2.3: the winner now gates the
        # first shift's starting possession -- see _play_shift's use of self._pending_faceoff).
        self._pending_faceoff = self._log_faceoff(FACEOFF_PERIOD_START)

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
                # Faceoff at center ice restarts play after a goal -- the only other legal
                # faceoff trigger besides period start until DEVPLAN.md Step 2.3 added
                # icing/offside/penalty stoppages (those are now rolled for mid-shift instead,
                # see _play_shift).
                if clock > 0:
                    self._pending_faceoff = self._log_faceoff(FACEOFF_AFTER_GOAL)

        # Regulation ends -- any pulled goalie returns for the next period/OT (a coach doesn't
        # carry an empty net into intermission; see _maybe_return_goalie's time-based fallback).
        if is_regulation:
            for state in (self.home, self.away):
                if state.goalie_pulled:
                    self._return_goalie(state)
            # Coach line-juggling AI (DEVPLAN.md Step 2.8): the intermission is the natural
            # stoppage point a real coach reworks lines at -- checked here (is_regulation-gated,
            # same as the goalie-pull return above) so it fires after every regulation period
            # (including before OT, a real intermission too) but never after an OT/sudden-death
            # period or the shootout placeholder. See this module's docstring for the full design.
            self._maybe_juggle_lines_for_all()

        self._log(EVENT_PERIOD_END, f"End of period {self.period}")

    def _play_shift(self, shift_secs: float):
        """Resolve one shift: check for a drawn penalty, possession from the faceoff/rush, a
        sequence of shot attempts (ticking the strength-state clock and reacting to mid-shift
        strength-state expiry between attempts) until the shift clock elapses, a goal is scored,
        or an icing/offside stoppage cuts the shift short, then apply ice-time/fatigue/injury
        checks and rotate both teams' on-ice groups for next shift. Returns True (via
        StopIteration value on `yield from` callers, or just the return value here) if a goal
        was scored this shift. A generator only insofar as it yields at a goal stoppage (see
        coach_session's docstring) -- for a shift with no goal it never yields.

        Faceoff-gated possession (DEVPLAN.md Step 2.3): the shift's starting offense/defense is
        now read from ``self._pending_faceoff`` (the ``_TeamState`` that just won the faceoff
        that opened this shift -- set by ``_play_period``/``_draw_penalty``/this method's own
        icing/offside handling) instead of a raw ``rng.chance(0.5)`` coin flip. Falls back to a
        neutral coin flip only if no faceoff has been resolved yet (shouldn't happen in normal
        play -- every shift boundary in this engine follows a faceoff -- but defensive rather
        than crashing on an unexpected ``None``).
        """
        self._check_for_penalties()

        if self._pending_faceoff is not None:
            offense, defense = (self._pending_faceoff,
                               self.away if self._pending_faceoff is self.home else self.home)
        else:
            offense, defense = (self.home, self.away) if self.rng.chance(0.5) else (self.away, self.home)
        self._pending_faceoff = None   # consumed -- the NEXT stoppage sets a fresh one

        elapsed = 0.0
        goal_scored = False
        stoppage = False   # set True by an icing/offside mid-shift stoppage -- ends the shift
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

            # Icing/offside stoppage check (DEVPLAN.md Step 2.3): rolled once per attempt cycle,
            # same cadence the strength clock advances at (see this method's docstring / the
            # ICING_CHANCE_PER_ATTEMPT_CYCLE/OFFSIDE_CHANCE_PER_ATTEMPT_CYCLE constants' own
            # comments). A stoppage ends the shift immediately (real hockey: play stops dead) and
            # sets ``self._pending_faceoff`` from the resulting faceoff's winner so the NEXT
            # shift's possession is gated by it, exactly like a period-start/after-goal faceoff.
            stoppage_type = self._roll_for_icing_or_offside()
            if stoppage_type is not None:
                stoppage = True
                self._pending_faceoff = self._log_faceoff(stoppage_type)
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
        self._injury_check()
        # self._pending_faceoff is already correctly set for the NEXT shift by this point: an
        # icing/offside stoppage set it directly (see the loop above), a goal will get one from
        # _play_period's post-goal branch, and a clock-expiry shift with no stoppage leaves it
        # None until the next period/OT boundary's own _log_faceoff call sets it -- no action
        # needed here in any case.
        self._advance_shift_for_all()
        return goal_scored

    def _roll_for_icing_or_offside(self) -> Optional[str]:
        """Roll once for an icing or offside stoppage this attempt cycle (DEVPLAN.md Step 2.3).
        Independent rolls (icing checked first, arbitrarily -- both are rare enough that the
        order has no meaningful effect on the resulting rate of either). Returns the stoppage
        type string if one fires, else ``None``."""
        if self.rng.chance(ICING_CHANCE_PER_ATTEMPT_CYCLE):
            return FACEOFF_ICING
        if self.rng.chance(OFFSIDE_CHANCE_PER_ATTEMPT_CYCLE):
            return FACEOFF_OFFSIDE
        return None

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
        (DEVPLAN.md flags exact tuning as an open item), not a per-attempt penalty check.

        ``self.playoff_penalty_multiplier`` (DEVPLAN.md Step 2.6's "Playoff officiating/
        discipline mode" design note) is threaded straight through to
        ``roll_for_penalty``/``penalty_probability_for_shift`` -- a strict 1.0 no-op for every
        non-playoff game, only < 1.0 for a playoff game under "realistic" mode (see
        ``GameSim.__init__``)."""
        for state in (self.home, self.away):
            on_ice_players = [state.players[pid] for pid in state.on_ice if pid in state.players]
            if ST.roll_for_penalty(self.rng, on_ice_players, state.coach_profile,
                                   playoff_multiplier=self.playoff_penalty_multiplier):
                self._draw_penalty(state, on_ice_players)

    def _draw_penalty(self, offending: _TeamState, on_ice_players: List[Player]) -> None:
        """Register a newly-drawn penalty against ``offending``'s team, log it, rebuild both
        teams' on-ice groups immediately so the rest of THIS shift plays out at the new strength
        state (a penalty stops play in real hockey -- the very next attempt should already
        reflect the man advantage/disadvantage), and roll a fresh faceoff for the stoppage
        (DEVPLAN.md Step 2.3 -- a drawn penalty is a real stoppage, not a play-through event).

        Called from ``_check_for_penalties()`` at the very TOP of ``_play_shift``, before that
        method reads ``self._pending_faceoff`` to decide the shift's starting
        offense/defense -- so setting it here means THIS shift's possession is correctly gated
        by the penalty-stoppage faceoff's winner, not last shift's stale one.
        """
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
        self._pending_faceoff = self._log_faceoff(FACEOFF_PENALTY)

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
    def _log_faceoff(self, stoppage_type: str = FACEOFF_PERIOD_START) -> _TeamState:
        """Resolve a faceoff for the given ``stoppage_type`` (DEVPLAN.md Step 2.3 -- period
        start, after a goal, a drawn penalty, icing, or offside; see the FACEOFF_* constants),
        log it (tallying the binary ``fo_won``/``fo_lost`` box-score fields and the PBP event's
        ``stoppage_type``/``won_off_tie`` context), and return the WINNING ``_TeamState`` so the
        caller (``_play_shift``) can gate the shift's starting possession on it -- this is the
        step that finally makes a faceoff outcome matter beyond box-score flavor (MVP's
        ``_log_faceoff`` explicitly did not gate possession; this version does).

        Delegates the actual three-way-roll/winger-tiebreak resolution to ``_resolve_faceoff``
        (kept separate so that pure resolution logic is testable without also exercising the
        logging/box-score side effects)."""
        winner_state, winner_pid, loser_pid, won_off_tie = self._resolve_faceoff()

        if winner_pid is not None:
            self.result.skater_line(winner_pid).fo_won += 1
        if loser_pid is not None:
            self.result.skater_line(loser_pid).fo_lost += 1

        self._log(EVENT_FACEOFF, "Faceoff", team_id=winner_state.tid if winner_pid else None,
                  player_id=winner_pid, stoppage_type=stoppage_type, won_off_tie=won_off_tie)
        return winner_state

    def _resolve_faceoff(self) -> Tuple[_TeamState, Optional[int], Optional[int], bool]:
        """The three-way faceoff roll (DEVPLAN.md Step 2.3's "Three-way faceoff resolution"
        design note): home center clean win / away center clean win / a contested TIE, resolved
        via a secondary winger roll rather than a plain two-way coin flip.

        Returns ``(winner_state, winner_pid, loser_pid, won_off_tie)``. ``won_off_tie`` is True
        only when the primary center roll landed on the tie slice and the SECONDARY winger roll
        is what actually decided it -- ``fo_won``/``fo_lost`` are credited identically either way
        (the winning CENTER, not a winger, always gets the box-score credit -- see the design
        note: "credited as the faceoff winner... exactly as if their center had won cleanly"),
        this flag exists purely as extra PBP context.

        Shape, mirroring the old two-way model's realization-scaled gap-to-probability pattern
        (``ratings.morale_realization`` scaling the *gap*, never the base rate -- consistent with
        this codebase's "no upweighting" principle: realization can only pull a result back
        toward a 50/50 neutral, never push a probability further from it than the raw rating gap
        alone would):
          1. If either team has no identifiable center on the ice (should be rare -- only a
             thin-bench/heavy-injury edge case), the other team's center wins uncontested; if
             neither has a center, nobody wins/loses anything (skip -- no PBP-worthy event).
          2. Otherwise roll a three-way split: a `home_fo`/`away_fo` rating gap sets a home-clean-
             win probability exactly like the old model, but a TIE slice is carved out of the
             middle first (``FACEOFF_TIE_BASE_P``, shrinking as the rating gap widens -- a
             lopsided matchup is less often a genuine scrum) so the three outcomes partition
             [0, 1] as [0, away_p) / [away_p, away_p + tie_p) / [away_p + tie_p, 1.0].
          3. A tie roll triggers the winger secondary roll (``_resolve_winger_tiebreak``) between
             the two teams' on-ice wingers, same gap-to-probability shape, over a
             puck_handling + offensive_awareness/defensive_awareness blend (DEVPLAN.md's explicit
             "hockey IQ" proxy) -- whichever team wins THAT roll has its CENTER credited as the
             faceoff winner (not the winger -- see the design note).
        """
        home_center = self._current_center(self.home)
        away_center = self._current_center(self.away)

        if home_center is None and away_center is None:
            return self.home, None, None, False
        if home_center is None:
            return self.away, away_center, None, False
        if away_center is None:
            return self.home, home_center, None, False

        home_p = self.home.players[home_center]
        away_p = self.away.players[away_center]
        home_fo = home_p.rating("faceoffs")
        away_fo = away_p.rating("faceoffs")
        rating_gap = home_fo - away_fo

        real = R.morale_realization(home_p.morale)
        win_gap = rating_gap * real * 0.004
        # Carve the tie slice out of the middle, shrinking with |rating_gap| (a lopsided
        # matchup is less often a genuine 50/50 scrum) but never going negative.
        tie_p = max(0.0, FACEOFF_TIE_BASE_P - abs(rating_gap) * FACEOFF_TIE_GAP_SUPPRESSION)
        # Split the remaining (1 - tie_p) probability mass between home/away using the same
        # gap-to-probability shape the old two-way model used, then re-scale so the three
        # outcomes partition [0, 1] exactly (home_p + away_p + tie_p == 1.0).
        home_share = max(0.20, min(0.80, FACEOFF_WIN_BASE + win_gap))
        home_p_final = home_share * (1.0 - tie_p)
        away_p_final = (1.0 - home_share) * (1.0 - tie_p)

        roll = self.rng.random()
        if roll < home_p_final:
            return self.home, home_center, away_center, False
        if roll < home_p_final + away_p_final:
            return self.away, away_center, home_center, False

        # Tie -- resolve via the winger secondary roll (DEVPLAN.md's design note). The winning
        # team's CENTER (not the winger who actually recovered the puck) is credited, since real
        # NHL box scores have no separate "won it off a scrum" faceoff stat.
        tie_winner_state = self._resolve_winger_tiebreak()
        if tie_winner_state is self.home:
            return self.home, home_center, away_center, True
        return self.away, away_center, home_center, True

    def _resolve_winger_tiebreak(self) -> _TeamState:
        """Secondary roll between the two teams' on-ice WINGERS (not centers -- the centers are
        the ones who just tied each other up) to decide who jumps on a loose scrum puck first,
        per DEVPLAN.md's "Three-way faceoff resolution" design note. Weighted by
        ``puck_handling + offensive_awareness``/``defensive_awareness`` (this codebase has no
        standalone "hockey IQ" rating -- the note explicitly names these as the closest existing
        fit), same realization-scaled gap-to-probability shape as the primary center roll (extends
        the existing pattern, not a new mechanic). Falls back to a neutral coin flip if either
        team has no identifiable winger on the ice (thin-bench/PP-PK-unit edge case)."""
        home_wingers = self._current_wingers(self.home)
        away_wingers = self._current_wingers(self.away)
        if not home_wingers or not away_wingers:
            return self.home if self.rng.chance(0.5) else self.away

        home_score = sum(_winger_iq_score(self.home.players[pid]) for pid in home_wingers) / len(home_wingers)
        away_score = sum(_winger_iq_score(self.away.players[pid]) for pid in away_wingers) / len(away_wingers)
        # Realization scalar on the gap (same role the primary roll's home-center
        # morale_realization plays): the home on-ice group's already-computed average morale
        # realization (``OnIceCache.avg_morale_real``, built once per shift) stands in for a
        # bespoke per-winger loop -- same multiplicative, floor-capped shape as every other
        # realization factor in this codebase, just reusing an aggregate that already exists.
        real = self.home.cache.avg_morale_real if self.home.cache is not None else 1.0
        gap = (home_score - away_score) * real * FACEOFF_WINGER_GAP_COEFFICIENT
        home_win_p = max(0.20, min(0.80, FACEOFF_WIN_BASE + gap))
        return self.home if self.rng.chance(home_win_p) else self.away

    @staticmethod
    def _current_center(state: _TeamState) -> Optional[int]:
        """The actual on-ice CENTER for a faceoff, looked up by ``Player.position`` rather than
        assuming index 1 of ``state.on_ice`` (DEVPLAN.md Step 2.3's ``_current_center`` bug fix --
        the old index-based assumption silently broke for a PP/PK on-ice group, which
        ``special_teams.on_ice_group_for_state`` builds ranked by composite score, not
        LW/C/RW position, so index 1 wasn't reliably a center in that case).

        Prefers a rostered "C" among the current on-ice group; if none is on the ice (an
        undersized/all-wing PK unit, or a center-less thin-bench edge case), falls back to the
        first on-ice skater so a faceoff still has SOMEONE to credit rather than silently
        crediting nobody -- matches the old function's "best-effort" framing, just correctly
        position-aware now instead of position-order-assuming."""
        for pid in state.on_ice:
            player = state.players.get(pid)
            if player is not None and player.position == "C":
                return pid
        return state.on_ice[0] if state.on_ice else None

    @staticmethod
    def _current_wingers(state: _TeamState) -> List[int]:
        """The on-ice LW/RW skaters for the winger secondary tiebreak roll (DEVPLAN.md Step
        2.3), looked up by ``Player.position`` -- same position-aware approach as
        ``_current_center`` rather than an index assumption. Returns an empty list (never
        crashes) if no on-ice skater is currently a winger (e.g. a PK unit built entirely from
        D/C by defensive-composite score)."""
        return [pid for pid in state.on_ice
                if state.players.get(pid) is not None and state.players[pid].position in ("LW", "RW")]

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

    def _goalie_skill(self, goalie: Player) -> float:
        """This goalie's effective save skill for the current attempt.

        The raw composite (``0.55*reflexes + 0.45*positioning``) is then scaled by this goalie's
        season "form" multiplier when a ``GoalieFormState`` was threaded in (DEVPLAN.md Step 2.7):
        a hot/cold season shifts the whole save-skill gap symmetrically. ``form_state is None``
        (tests, one-off sims) returns the straight composite, unchanged. Because form is a linear
        scalar, applying it to the composite is identical to applying it to each rating first."""
        gr = goalie.ratings
        skill = 0.55 * gr.get("reflexes", 25) + 0.45 * gr.get("positioning", 25)
        if self.form_state is not None:
            skill = apply_goalie_form(skill, goalie, self.form_state)
        return skill

    def _pick_blocker(self, defense: _TeamState) -> Optional[Player]:
        """Choose which on-ice defending skater is in the shooting lane, weighted by
        ``shot_blocking`` (DEVPLAN.md Step 2.x). Good shot-blockers get in the way more often, so
        they both raise the block chance and collect the resulting ``blocks`` stat. Returns None
        only if the defending team somehow has no on-ice skaters (degenerate, but guarded)."""
        skaters = [defense.players[pid] for pid in defense.on_ice
                   if pid in defense.players and pid != defense.goalie_id]
        if not skaters:
            return None
        weights = [max(1.0, float(p.ratings.get("shot_blocking", 25))) for p in skaters]
        return skaters[_weighted_index(self.rng, weights)]

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
            goalie_skill = self._goalie_skill(goalie)

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
            # low-danger zones (point shots get blocked more in real hockey). A defending skater's
            # shot_blocking rating (DEVPLAN.md Step 2.x) then nudges that split: the skater in the
            # lane is chosen weighted by shot_blocking, and their rating (relative to a league
            # anchor) raises/lowers the block chance and, on a block, earns the box-score credit.
            blocker = self._pick_blocker(defense)
            block_p = 0.30 + (0.20 if zone in ZONES_LOW_DANGER else 0.0)
            if blocker is not None:
                block_p += (blocker.ratings.get("shot_blocking", 25)
                            - config.BLOCK_RATING_PIVOT) * config.BLOCK_RATING_SLOPE
            block_p = max(config.BLOCK_PROB_MIN, min(config.BLOCK_PROB_MAX, block_p))
            blocked = self.rng.chance(block_p)
            outcome = SHOT_OUTCOME_BLOCK if blocked else SHOT_OUTCOME_MISS
            if blocked and blocker is not None:
                self.result.skater_line(blocker.pid).blocks += 1
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

        # Line-juggling AI combo-performance signal (DEVPLAN.md Step 2.8): credit/debit the
        # CURRENT line-slot/pair-slot's on-ice goal differential, 5v5 only -- see this module's
        # docstring for why PP/PK goals don't feed this tracker (the special-teams unit, not the
        # normal line/pair rotation, was actually on the ice).
        if scoring_strength_state == config.STRENGTH_5V5:
            self._update_combo_diff(offense, 1.0)
            self._update_combo_diff(defense, -1.0)

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
        #
        # That ``goalie is None`` check only catches the DEFENDING team's own net being empty
        # (they pulled their goalie and got scored into their empty net). It missed the mirror
        # case: the SCORING team itself has pulled ITS OWN goalie to attack with an extra
        # skater (``offense.goalie_pulled``) while the opponent's goalie is still in net --
        # offense.on_ice is 6 skaters against defense's 5, the same asymmetric-group-size
        # situation as a PP/5v3 goal, and crediting it symmetrically breaks the same net-zero
        # invariant this whole gate exists to protect (confirmed via
        # test_goal_updates_plus_minus_nets_to_zero_when_every_goal_is_5v5: an unassisted,
        # trailing-team, late-third-period goal -- the classic extra-attacker script -- summed
        # to +1 instead of 0 before this fix). Exclude both teams' pulled-goalie state, not just
        # the defending side's, to close the gap symmetrically.
        if (scoring_strength_state not in (config.STRENGTH_PP, config.STRENGTH_5V3)
                and goalie is not None
                and not offense.goalie_pulled
                and not defense.goalie_pulled):
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

    # -- coach line-juggling AI (DEVPLAN.md Step 2.8) --------------------------
    def _update_combo_diff(self, state: _TeamState, delta: float) -> None:
        """Credit/debit ``delta`` to the CURRENT forward-line-slot and D-pair-slot combo
        trackers for ``state`` -- the on-ice-goal-differential-per-combo signal this module's
        docstring describes. Only ever called from ``_score_goal`` for a 5v5 goal (see caller)."""
        if state.team.lines:
            idx = state._current_line_idx
            state.line_combo_diff[idx] = state.line_combo_diff.get(idx, 0.0) + delta
        if state.team.pairs:
            idx = state._current_pair_idx
            state.pair_combo_diff[idx] = state.pair_combo_diff.get(idx, 0.0) + delta

    def _maybe_juggle_lines_for_all(self) -> None:
        """Patience-gated line/pair reshuffle check for BOTH teams, called once per REGULATION
        intermission (see ``_play_period``) -- see this module's docstring for the full design
        rationale/judgment calls behind this mechanic."""
        for state in (self.home, self.away):
            self._maybe_juggle_lines_for_team(state)

    def _maybe_juggle_lines_for_team(self, state: _TeamState) -> None:
        """Check every line-slot/pair-slot combo currently tracked as "cold" (accumulated 5v5
        on-ice goal differential at or below ``COMBO_COLD_GOAL_DIFF_THRESHOLD``) and roll,
        independently per cold slot, whether ``state``'s coach reshuffles it -- probability
        scaled by ``CoachProfile.line_juggling_patience`` (0.0 = readily reshuffles, 1.0 = never
        does; see ``LINE_JUGGLE_BASE_RESHUFFLE_CHANCE``'s own comment for the exact formula).

        Exposed as its own method (rather than inlined into ``_maybe_juggle_lines_for_all``) so
        tests can drive it directly against a forced-cold combo dict without needing to actually
        simulate a losing stretch of real gameplay to reach that state -- the same "drive engine
        internals directly for a controlled scenario" testing pattern this codebase already uses
        for pull-the-goalie (see ``tests/test_goalies.py``).
        """
        patience = max(0.0, min(1.0, state.coach_profile.line_juggling_patience))
        reshuffle_p = LINE_JUGGLE_BASE_RESHUFFLE_CHANCE * (1.0 - patience)
        if reshuffle_p <= 0.0:
            return

        cold_lines = [i for i, diff in state.line_combo_diff.items()
                      if diff <= COMBO_COLD_GOAL_DIFF_THRESHOLD]
        for idx in cold_lines:
            if self.rng.chance(reshuffle_p):
                self._swap_line_slot(state, idx)

        cold_pairs = [i for i, diff in state.pair_combo_diff.items()
                      if diff <= COMBO_COLD_GOAL_DIFF_THRESHOLD]
        for idx in cold_pairs:
            if self.rng.chance(reshuffle_p):
                self._swap_pair_slot(state, idx)

    def _swap_line_slot(self, state: _TeamState, cold_idx: int) -> None:
        """Reshuffle the cold forward line at ``cold_idx``: pick a different line at random and
        swap ONE slot position (LW/C/RW, chosen at random) between the two lines -- a
        real-hockey-shaped "moved one guy to break up a cold line" tweak, not a full rebuild
        (see this module's docstring point 3). Both swapped slots' tracked diff resets to 0.0
        (a freshly-assembled combo has no track record yet). No-op if there's no other line to
        swap with (a one-line roster, an extreme thin-bench edge case)."""
        lines = state.team.lines
        if len(lines) < 2 or cold_idx >= len(lines):
            return
        other_idx = self.rng.choice([i for i in range(len(lines)) if i != cold_idx])
        cold_line, other_line = lines[cold_idx], lines[other_idx]
        if len(cold_line) == 3 and len(other_line) == 3:
            pos = self.rng.choice([0, 1, 2])
            cold_line[pos], other_line[pos] = other_line[pos], cold_line[pos]
        else:
            # A degenerate (short-bench/injury-shrunk) line can't do a same-slot swap --
            # fall back to swapping the two lines' personnel wholesale rather than crashing on
            # a mismatched-length index.
            lines[cold_idx], lines[other_idx] = other_line, cold_line
        state.line_combo_diff[cold_idx] = 0.0
        state.line_combo_diff[other_idx] = 0.0
        state.reshuffle_count += 1

    def _swap_pair_slot(self, state: _TeamState, cold_idx: int) -> None:
        """D-pair analog of ``_swap_line_slot``: swap one D (slot 0 or 1) between the cold pair
        and a randomly chosen other pair, resetting both slots' tracked diff to 0.0."""
        pairs = state.team.pairs
        if len(pairs) < 2 or cold_idx >= len(pairs):
            return
        other_idx = self.rng.choice([i for i in range(len(pairs)) if i != cold_idx])
        cold_pair, other_pair = pairs[cold_idx], pairs[other_idx]
        if len(cold_pair) == 2 and len(other_pair) == 2:
            pos = self.rng.choice([0, 1])
            cold_pair[pos], other_pair[pos] = other_pair[pos], cold_pair[pos]
        else:
            pairs[cold_idx], pairs[other_idx] = other_pair, cold_pair
        state.pair_combo_diff[cold_idx] = 0.0
        state.pair_combo_diff[other_idx] = 0.0
        state.reshuffle_count += 1

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

    # -- in-game injuries (DEVPLAN.md Step 2.3) -------------------------------
    def _injury_check(self) -> None:
        """Roll every currently-on-ice SKATER (both teams) for an in-game injury, once per
        shift -- HoopR's ``_injury_check`` sport-agnostic shape (per-on-court/on-ice-player,
        per-possession/per-shift roll), ported to hockey's shift-based cadence rather than
        basketball's possession-based one (see this module's docstring). Goalies are
        deliberately excluded (matches HoopR's own scope -- that function only ever iterates
        skater-equivalents; a goalie-injury/backup-swap interaction would cross into Step 2.2's
        goalie-rotation territory, out of bounds for this step).

        A freshly-injured player is added to their team's ``unavailable`` set immediately (so
        the very next ``_advance_shift_for_all`` call already routes around them -- see
        ``_TeamState._next_normal_group``/``refresh_on_ice_for_strength_state``) and recorded
        into ``self.result.injuries`` for ``sim/season.py``'s ``_apply_result`` to apply onto
        ``Player.injury`` once the game is over.
        """
        for state in (self.home, self.away):
            for pid in list(state.on_ice):
                player = state.players.get(pid)
                if player is None or pid in state.unavailable:
                    continue
                rate = config.IN_GAME_INJURY_RATE * (1.0 + (INJURY_STAMINA_ANCHOR
                                                            - player.rating("stamina", 70))
                                                      * INJURY_STAMINA_SLOPE)
                if self.rng.chance(max(0.0, rate)):
                    games, severity = self._injury_severity()
                    self.result.injuries.append((pid, games, "in-game injury", severity))
                    state.unavailable.add(pid)
                    self._log(EVENT_INJURY, f"{player.short_name} is injured and leaves the game",
                              team_id=state.tid, player_id=pid)

    def _injury_severity(self) -> Tuple[int, str]:
        """Roll an injury's severity band + games-missed count within that band (DEVPLAN.md
        Step 2.3, hockey-appropriate magnitudes -- see INJURY_MINOR_GAMES/INJURY_MODERATE_GAMES/
        INJURY_MAJOR_GAMES's own comments for why these differ from HoopR's basketball-season
        numbers). Same three-tier cumulative-probability shape as HoopR's ``_injury_severity``:
        most in-game injuries are minor (day-to-day), a minority are moderate (a couple of
        weeks), and a rare tail is major (long-term IR)."""
        roll = self.rng.random()
        if roll < INJURY_MINOR_P:
            lo, hi = INJURY_MINOR_GAMES
            return self.rng.randint(lo, hi), "minor"
        if roll < INJURY_MODERATE_P:
            lo, hi = INJURY_MODERATE_GAMES
            return self.rng.randint(lo, hi), "moderate"
        lo, hi = INJURY_MAJOR_GAMES
        return self.rng.randint(lo, hi), "major"

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
              penalty_duration_secs: Optional[float] = None,
              stoppage_type: Optional[str] = None, won_off_tie: bool = False) -> None:
        if not self.collect_pbp:
            return
        self.result.pbp.append(PBPEvent(
            period=self.period, time_secs=self.game_secs, event_type=event_type,
            description=description, home_score=self.result.home_score,
            away_score=self.result.away_score, team_id=team_id, player_id=player_id,
            penalty_type=penalty_type, penalty_duration_secs=penalty_duration_secs,
            stoppage_type=stoppage_type, won_off_tie=won_off_tie,
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
                   away_goalie_id: Optional[int] = None,
                   is_playoff: bool = False,
                   form_state: Optional[GoalieFormState] = None) -> GameResult:
    """Convenience wrapper: simulate one game and return its result.

    ``home_goalie_id``/``away_goalie_id`` (DEVPLAN.md Step 2.2) pass through to
    ``GameSim``'s same-named constructor overrides -- see that class's docstring. Defaults to
    ``None`` (falls back to each team's ``Team.goalie_starter``), so this is a strict additive
    extension for any existing caller.

    ``is_playoff`` (DEVPLAN.md Step 2.6) pass through to ``GameSim``'s same-named constructor
    override -- selects real 5-on-5 sudden-death playoff OT (vs. regular-season 3-on-3 -> maybe
    shootout) and the playoff officiating/discipline mode's penalty multiplier. Defaults to
    ``False`` (identical behavior to before this step for any existing caller).

    ``form_state`` (DEVPLAN.md Step 2.7) pass through to ``GameSim``: the per-season goalie form
    multipliers. Defaults to ``None`` (every goalie plays at their straight rating), so this too is
    a strict additive extension -- ``sim/season.py``'s ``sim_one`` is the caller that threads the
    live per-World form state in.
    """
    return GameSim(world, home_tid, away_tid, collect_pbp=collect_pbp,
                   home_goalie_id=home_goalie_id, away_goalie_id=away_goalie_id,
                   is_playoff=is_playoff, form_state=form_state).play()
