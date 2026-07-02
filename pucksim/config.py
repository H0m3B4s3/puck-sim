"""Central tunables for PuckSim.

Every "magic number" that shapes the feel of the game lives here so balancing is a
single-file exercise. Ratings are on a 25-99 scale. Time constants are in seconds
unless noted otherwise.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Save format
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 1
SAVE_DIR_NAME = "saves"          # created under the current working directory
AUTOSAVE_SLOT = "autosave"

# ---------------------------------------------------------------------------
# League shape
# ---------------------------------------------------------------------------
NUM_TEAMS = 32
CONFERENCES = ("Eastern", "Western")
DIVISIONS_PER_CONFERENCE = 2
TEAMS_PER_CONFERENCE = NUM_TEAMS // len(CONFERENCES)             # 16
TEAMS_PER_DIVISION = TEAMS_PER_CONFERENCE // DIVISIONS_PER_CONFERENCE  # 8

# Roster construction: skaters and goalies are tracked separately since they fill
# structurally different roster slots (forward lines / D-pairs vs. starter+backup).
SKATERS_MIN = 18
SKATERS_MAX = 20
GOALIES_MIN = 2
GOALIES_MAX = 3
ROSTER_MIN = SKATERS_MIN + GOALIES_MIN   # 20
ROSTER_MAX = SKATERS_MAX + GOALIES_MAX   # 23

SEASON_GAMES = 82
PLAYOFF_TEAMS_PER_CONF = 8

# Trades are allowed up to roughly 2/3 of the way through the regular season,
# mirroring the real early-March NHL deadline; scales automatically if season
# length is ever varied.
TRADE_DEADLINE_FRACTION = 0.66

# ---------------------------------------------------------------------------
# Game (match) structure
# ---------------------------------------------------------------------------
PERIODS = 3
PERIOD_MINUTES = 20
PERIOD_SECONDS = PERIOD_MINUTES * 60

# Regular-season overtime: 3-on-3 sudden death, 5 minutes, before a shootout
# (unless the active standings rule skips the shootout entirely — see below).
OT_MINUTES_REGULAR_SEASON = 5
OT_SECONDS_REGULAR_SEASON = OT_MINUTES_REGULAR_SEASON * 60
OT_STRENGTH_REGULAR_SEASON = "3v3"

# Playoff overtime: full 5-on-5 sudden-death periods, same length as regulation,
# repeated until someone scores (no shootout in the playoffs, ever).
OT_MINUTES_PLAYOFFS = PERIOD_MINUTES
OT_SECONDS_PLAYOFFS = OT_MINUTES_PLAYOFFS * 60
OT_STRENGTH_PLAYOFFS = "5v5"

# A sane cap on how many extra playoff sudden-death periods a single game can play before this
# codebase gives up and forces a decision -- real NHL playoff games have gone to a 5th+ OT before
# (the 2020 Stars/Blue Jackets 5-OT game), so this is generous, not a realistic ceiling; it exists
# purely as a defensive guard against a pathological RNG stream producing an effectively-infinite
# game in a headless sim loop (a real broadcast just keeps playing; a script needs a stop
# condition). PROVISIONAL -- picked to comfortably exceed any realistic simulated outcome.
MAX_PLAYOFF_OT_PERIODS = 12

# ---------------------------------------------------------------------------
# Shootout resolution (DEVPLAN.md Step 2.6). A SEPARATE skills-competition resolution model
# (DESIGN.md point 8), not a continuation of normal shift/event simulation -- see
# sim/engine.py's ``_resolve_shootout``. Only reachable for "standard"/"three_two_one_zero"
# regular-season games still level after 3-on-3 OT; playoffs never shoot out (sudden-death 5v5
# continues instead -- see OT_STRENGTH_PLAYOFFS above).
# ---------------------------------------------------------------------------
SHOOTOUT_ROUNDS = 3          # each team gets 3 attempts in the standard round unless already
                              # mathematically decided, then sudden-death alternating attempts.
SHOOTOUT_MAX_SUDDEN_DEATH_ROUNDS = 20   # defensive cap on alternating sudden-death rounds (real
                                        # NHL shootouts have gone 20+ rounds; this is a stop
                                        # condition for a headless sim loop, not a realistic
                                        # ceiling -- see MAX_PLAYOFF_OT_PERIODS's identical framing)

# Baseline probability an average (rating-70) shooter beats an average (rating-70) goalie on a
# single shootout attempt, before any rating-gap adjustment. PROVISIONAL/TUNABLE -- real NHL
# shootout conversion rates run in the low-to-mid 30% range league-wide; this is a plausible
# starting anchor, not fit to real data (none is being fit anywhere else in this codebase either).
SHOOTOUT_BASE_SCORE_PROB = 0.33
# How much a shooter-vs-goalie rating gap moves the score probability away from the baseline,
# per rating point of gap. Small and symmetric (same shape as every other rating-gap-to-
# probability slope in this codebase, e.g. special_teams.py's discipline slope).
SHOOTOUT_RATING_GAP_SLOPE = 0.004

# Target average shift length for line-change pacing; fatigue/recovery modeling
# is built around this, not clock minutes like a basketball rotation.
SHIFT_SECONDS_TARGET = 45

# ---------------------------------------------------------------------------
# Standings rules (DESIGN.md point 7)
# ---------------------------------------------------------------------------
# Not a single hardcoded win/loss scheme like the NBA: this is a user-selectable
# per-league rule. All three presets are defined here as data; `World.standings_rule`
# (a per-save string key into this dict) picks the active one. Values are team
# points awarded for each game outcome from that team's perspective.
#
#   reg_win        - win in regulation
#   ot_win         - win in overtime
#   so_win         - win in a shootout
#   ot_loss        - loss in overtime
#   so_loss        - loss in a shootout
#   reg_loss       - loss in regulation (no OT/SO reached)
#   tie            - game ends level (only reachable under "retro", which has
#                    no shootout and no OT sudden-death resolution requirement)
#   has_shootout   - whether this rule uses a shootout to break OT ties at all
STANDINGS_RULES = {
    # Current real-world NHL scheme.
    "standard": {
        "reg_win": 2,
        "ot_win": 2,
        "so_win": 2,
        "ot_loss": 1,
        "so_loss": 1,
        "reg_loss": 0,
        "tie": None,          # unreachable under this rule
        "has_shootout": True,
    },
    # Pre-2005 NHL style: ties stand, no shootout at all.
    "retro": {
        "reg_win": 2,
        "ot_win": 2,
        "so_win": None,        # unreachable — no shootout under this rule
        "ot_loss": 1,
        "so_loss": None,       # unreachable — no shootout under this rule
        "reg_loss": 0,
        "tie": 1,
        "has_shootout": False,
    },
    # "3-2-1-0" — an analytics-commentator-favorite scheme that rewards
    # regulation wins more heavily than extending the game to OT/SO.
    "three_two_one_zero": {
        "reg_win": 3,
        "ot_win": 2,
        "so_win": 2,
        "ot_loss": 1,
        "so_loss": 1,
        "reg_loss": 0,
        "tie": None,          # unreachable under this rule
        "has_shootout": True,
    },
}

# Provisional default for new leagues. Purely a config-level choice — reversible
# per-save at any time via `World.standings_rule`; does not affect OT/shootout
# simulation itself (see DESIGN.md point 7/8), only how points are tallied.
DEFAULT_STANDINGS_RULE = "standard"

# ---------------------------------------------------------------------------
# Strength states
# ---------------------------------------------------------------------------
# String constants for on-ice strength state. Nothing consumes these yet in the
# MVP engine (Step 1.12 is 5v5-only), but the special-teams layer (v1, Step 2.1)
# and the standings/OT logic above already need a stable vocabulary to refer to.
STRENGTH_5V5 = "5v5"
STRENGTH_PP = "PP"     # power play (man advantage)
STRENGTH_PK = "PK"     # penalty kill (short-handed)
STRENGTH_4V4 = "4v4"
STRENGTH_3V3 = "3v3"   # regular-season OT
STRENGTH_5V3 = "5v3"   # two-man advantage

STRENGTH_STATES = (
    STRENGTH_5V5,
    STRENGTH_PP,
    STRENGTH_PK,
    STRENGTH_4V4,
    STRENGTH_3V3,
    STRENGTH_5V3,
)

# ---------------------------------------------------------------------------
# Penalties
# ---------------------------------------------------------------------------
# Durations in seconds. Misconduct removes the offending player for the stated
# duration but does not put their team on the penalty kill (no strength-state
# change) — it's a discipline/personnel effect only, not a man-advantage event.
MINOR_PENALTY_SECONDS = 2 * 60
MAJOR_PENALTY_SECONDS = 5 * 60
MISCONDUCT_PENALTY_SECONDS = 10 * 60

# ---------------------------------------------------------------------------
# Special teams / penalty engine (DEVPLAN.md Step 2.1)
# ---------------------------------------------------------------------------
# PROVISIONAL, FIRST-PASS TUNABLES -- exact strength-state probability tuning is an
# explicitly-flagged open item (DESIGN.md "Open items" / DEVPLAN.md Step 2.1's own note);
# these are reasonable starting magnitudes, not a tuned model. See
# ``pucksim/sim/special_teams.py`` for the formula these feed into.
#
# Baseline probability that a given shift produces a penalty on a given team, before any
# discipline/coach-aggression adjustment. Roughly calibrated so a full 60-minute regulation
# game (~40 shifts across a whole roster's worth of shift-events, per team) nets a handful of
# penalties per team per game, in the real-hockey ballpark, not exact.
PENALTY_BASE_PROB_PER_SHIFT = 0.018

# How much a below/above-average `discipline` rating (25-99 scale, centered near 70 like every
# other rating) moves the base probability. Lower discipline -> more penalties. Expressed as a
# multiplier delta per rating point away from the 70 "average" anchor.
PENALTY_DISCIPLINE_SLOPE = 0.006

# How much coach `defensive_risk_tolerance` (0-1) and `forecheck_aggression` (0-1) each scale
# the penalty probability, centered so the 0.5 "Balanced" archetype nets to a 1.0x multiplier
# (no change from the discipline-only baseline).
PENALTY_RISK_TOLERANCE_MAX_MULT = 1.5   # defensive_risk_tolerance = 1.0
PENALTY_RISK_TOLERANCE_MIN_MULT = 0.7   # defensive_risk_tolerance = 0.0
PENALTY_FORECHECK_MAX_MULT = 1.3        # forecheck_aggression = 1.0
PENALTY_FORECHECK_MIN_MULT = 0.85       # forecheck_aggression = 0.0

# Penalty-type weighted pick: minors are by far the most common penalty in real hockey: majors
# (fighting/spearing/etc.) and misconducts are rare. Weights, not probabilities (normalized at
# draw time).
PENALTY_TYPE_WEIGHTS = {
    "minor": 92.0,
    "major": 6.0,
    "misconduct": 2.0,
}

# Power-play / penalty-kill on-ice group sizes. A PP unit is a full-strength 5 (the shorthanded
# opponent is down a skater); a PK unit is the shorthanded team's own 4 skaters. 5-on-3 shrinks
# the box-checking team down to 3 -- see STRENGTH_5V3 handling in special_teams.py.
PP_UNIT_SIZE = 5
PK_UNIT_SIZE = 4
PK_UNIT_SIZE_5V3 = 3

# ---------------------------------------------------------------------------
# Playoff officiating/discipline mode (DEVPLAN.md Step 2.6 design note, 2026-07-02)
# ---------------------------------------------------------------------------
# A genuine user-selectable per-save option (mirrors World.standings_rule's own pattern), NOT a
# hardcoded behavior change -- see World.playoff_discipline_mode. Real NHL playoff hockey is
# genuinely officiated/played differently than the regular season (refs "let them play," far
# fewer penalties called); this codebase has no fighting mechanic to suppress (DESIGN.md's
# explicit scope exclusion -- see attributes.py's "Enforcer-Physical" archetype comment), so the
# ONLY mechanical effect of this mode is a multiplicative scaling factor on the existing penalty-
# probability chain (special_teams.penalty_probability_for_shift's new playoff_multiplier param).
#
#   "realistic"      -- (recommended default) playoff games draw meaningfully fewer penalties
#                        than an equivalent regular-season game.
#   "regular_season"  -- playoff games use identical penalty rates to the regular season --
#                        explicitly an equally-legitimate "less realistic but fun" choice, not a
#                        deprecated/lesser option (per the design note).
PLAYOFF_DISCIPLINE_MODE_CHOICES = ("realistic", "regular_season")
DEFAULT_PLAYOFF_DISCIPLINE_MODE = "realistic"

# How much "realistic" mode scales the base per-shift penalty probability during a playoff game
# (a straight multiplier on top of the existing discipline/risk-tolerance/forecheck chain --
# see special_teams.penalty_probability_for_shift). PROVISIONAL/TUNABLE magnitude: no real-NHL
# playoff-vs-regular-season penalty-rate data is being fit here, just a plausible "refs call it
# tighter" effect size, same framing as every other first-pass constant in this codebase. 0.65
# means playoff games draw roughly 2/3 as many penalties as an identical regular-season shift
# under "realistic" mode; "regular_season" mode always passes 1.0 (a no-op) instead.
PLAYOFF_REALISTIC_PENALTY_MULTIPLIER = 0.65

# ---------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------
# The concrete rating list (skater vs. goalie categories) is owned by
# attributes.py (Step 1.4) — config.py only needs the shared scale bounds.
RATING_MIN = 25
RATING_MAX = 99

# ---------------------------------------------------------------------------
# Development & aging
# ---------------------------------------------------------------------------
# First-pass/tuning TODO: DESIGN.md doesn't specify exact ages. These are
# reasonable hockey-realistic placeholders (skaters generally peak a bit
# earlier than basketball players and NHL careers run a bit longer on average
# at the tail end) and should be revisited once real development-curve tuning
# happens against generated/simulated cohorts.
PEAK_AGE_LOW = 24
PEAK_AGE_HIGH = 29
ROOKIE_AGE_RANGE = (18, 21)
RETIREMENT_AGE = 40

# ---------------------------------------------------------------------------
# Injuries
# ---------------------------------------------------------------------------
# Base per-game probability a given rotation player suffers an injury, before
# durability. Placeholder pending real tuning once the sim engine exists.
BASE_INJURY_RATE = 0.012
# Per on-ice-player, per-shift injury chance. A full-game player faces roughly
# 20-25 shifts, so this is deliberately tiny.
IN_GAME_INJURY_RATE = 0.0006

# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
SEASON_START_MONTH = 10          # October
SEASON_START_DAY = 8

# ---------------------------------------------------------------------------
# Multi-league expansion (dormant in Phase 1 — reserved so saves don't break
# later, mirrors HoopR's college-mode hook per DESIGN.md's Phase 2/3 notes)
# ---------------------------------------------------------------------------
LEAGUE_ORIGIN_CHOICES = ("none", "chl", "ncaa", "europe")
DEFAULT_LEAGUE_ORIGIN = "none"

# ---------------------------------------------------------------------------
# Position / handedness fit penalties (DEVPLAN.md Step 1.7, "Position
# flexibility & handedness" amendment, 2026-07-01)
# ---------------------------------------------------------------------------
# A player's `Player.position` (set in Step 1.6) is their PRIMARY slot, but
# team.py's auto-line-builder can slot forwards into any of the 3 forward
# slots (LW/C/RW) and pair D on either side, at a fit-rating cost. These
# penalties are consumed ONLY by team.py's line-builder fit-score function —
# never by attributes.overall(), which stays position-agnostic by design (see
# attributes.py's module docstring / the design discussion this amendment
# references).
#
# PROVISIONAL, FIRST-PASS VALUES — tunable once real line-building/gameplay
# data exists, per DEVPLAN.md's explicit "provisional/tunable" framing.
#
# Position-category penalty: forwards only (D has a single POSITIONS slot,
# so no category cross-assignment is possible -- see attributes.py's POSITIONS
# docstring). Keyed (primary_position, assigned_slot) -> rating-point penalty.
# On-position (primary == assigned slot) is always 0 and is intentionally NOT
# a key here; callers should treat a missing/on-position lookup as 0.
#   wing <-> wing (LW/RW cross-assignment): small penalty -- both wing slots
#     carry similar positional responsibility.
#   C -> wing (center slotted onto a wing): smaller penalty than wing->C --
#     a center is "less defensively intensive" to move off of, per DEVPLAN.md.
#   wing -> C (winger slotted at center): larger penalty -- center carries
#     more defensive/faceoff responsibility than either wing slot.
POSITION_FIT_PENALTY: dict = {
    ("LW", "RW"): 3,
    ("RW", "LW"): 3,
    ("C", "LW"): 2,
    ("C", "RW"): 2,
    ("LW", "C"): 8,
    ("RW", "C"): 8,
}

# Handedness/side fit penalty (Player.shoots "L"|"R", added to player.py in
# this same design pass). Applies independently of the position-category
# penalty above and is smaller than a position-category mismatch.
#
# For FORWARDS: LW is the "left side," RW is the "right side," C has no side.
# A left-shot assigned to RW (or a right-shot assigned to LW) incurs this
# penalty; a center assignment never incurs a handedness penalty regardless
# of the player's shoots value (centers play the middle regardless of hand).
#
# For D PAIRS: this isn't a per-slot penalty but a pair-composition bonus/
# penalty -- see team.py's `d_pair_fit_bonus()`, which treats a same-handed
# pair (both L or both R) as incurring this same penalty magnitude relative
# to an opposite-handed pair (the real-NHL-preferred shape), all else equal.
HANDEDNESS_FIT_PENALTY: int = 2

# ---------------------------------------------------------------------------
# Salary cap / contracts (DEVPLAN.md Step 2.4)
# ---------------------------------------------------------------------------
# v1's simplified cap model (DESIGN.md's explicit HoopR-style single-cap-number
# decision, see models/contract.py's module docstring): one flat cap number, no
# luxury-tax-line/apron/mid-level-exception machinery. This constant used to be a
# `World`-local placeholder (`_DEFAULT_SALARY_CAP` in models/world.py) -- it moves
# here now because Step 2.4's cap-growth mechanism (`systems/cap.py::grow_cap()`)
# needs a stable config-level base to grow *from* each offseason, and every other
# tunable constant in this codebase already lives in config.py, not scattered
# across model modules.
#
# PROVISIONAL, first-pass dollar figure -- a round, real-NHL-scale number (the
# actual 2025-26 NHL cap is in this ballpark); not tuned against any particular
# in-game economy target. Revisit once player-generation salary distributions
# exist to sanity-check against.
SALARY_CAP_BASE = 82_500_000

# Floor salary for any signed contract (entry-level/depth deals never go below
# this). Real NHL has a real minimum ($775K for 2024-25); this is a round
# placeholder in the same ballpark, not the exact CBA figure.
MINIMUM_SALARY = 800_000

# Cap ceiling for a single contract's annual salary, expressed as a fraction of
# the league cap (real NHL's "20% max AAV" rule of thumb -- no player may sign
# for more than 20% of the cap in a single season). Applied in
# `systems/cap.py::max_salary()`.
MAX_SALARY_CAP_FRACTION = 0.20

# Contract length bounds. Real NHL max is 8 years (7 for a sign-and-trade,
# simplified away here); rookie-scale (entry-level) deals are always 3 years
# flat, matching the real ELC's fixed 3-year term regardless of signing age.
MAX_CONTRACT_YEARS = 8
ROOKIE_CONTRACT_YEARS = 3

# Rookie-scale (entry-level) pay is a small flat fraction of the cap, not a
# market-rate salary -- this is what keeps drafted stars cheap for their first
# three years, same shape as the real ELC's flat, modest cap hit regardless of
# how good the rookie turns out to be. PROVISIONAL fraction.
ROOKIE_SALARY_CAP_FRACTION = 0.010   # ~$825K at an $82.5M cap

# Trade salary-matching tolerance (there's no hard NHL retention-percentage/
# matching-band rule to port -- unlike the NBA's "you must take back within X%"
# retention math -- so this is a simplified, generous single-number buffer: a
# team can absorb incoming salary up to its existing cap space plus this flat
# dollar allowance, mirroring how HoopR's `TRADE_MATCH_BUFFER` gives small deals
# breathing room without needing to model retained-salary trades (a real NHL
# mechanic explicitly out of scope for v1 per DESIGN.md's cap-simplicity call).
TRADE_MATCH_BUFFER = 3_000_000

# How much the cap grows per offseason (`systems/cap.py::grow_cap()`), a flat
# rate mirroring real-world NHL cap growth (~a few percent most years, though
# real growth is negotiated and lumpy). PROVISIONAL/tunable.
CAP_GROWTH_RATE = 0.03
