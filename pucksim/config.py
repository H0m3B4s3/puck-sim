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

# Shot-blocking (DEVPLAN.md Step 2.x "impactful ratings"): when an off-goal attempt is split into
# a block vs a harmless miss, a defending skater's `shot_blocking` rating modulates how likely it
# is to be a block, and the resulting block is credited to that skater's box-score `blocks`.
# BLOCK_RATING_PIVOT is the "average" anchor the rating delta is centered on -- deliberately set
# slightly ABOVE the raw league skater mean (~66) because the blocker is chosen weighted by
# shot_blocking, so the expected chosen blocker rates a bit above the population average; centering
# here keeps the league-wide block-vs-miss split near its pre-rating baseline. SLOPE is the
# per-point swing. PROVISIONAL/TUNABLE, same framing as every other first-pass constant here.
BLOCK_RATING_PIVOT = 72.0
BLOCK_RATING_SLOPE = 0.0025
BLOCK_PROB_MIN = 0.08
BLOCK_PROB_MAX = 0.80

# Rebound control (DEVPLAN.md Step 2.x "impactful ratings"): a goalie's `rebound_control` rating
# scales how often a save kicks out a rebound. PIVOT is the "average" anchor (goalie population
# mean ~68); a goalie above it surrenders proportionally fewer rebounds, below it more. SLOPE is
# the per-point swing on the rebound-generation multiplier; MIN_MULT floors it so even a 99 still
# occasionally gives one up. Centered so the league-wide rebound rate stays near the base rate.
REBOUND_CONTROL_PIVOT = 68.0
REBOUND_CONTROL_SLOPE = 0.010
REBOUND_CONTROL_MIN_MULT = 0.35
# A rebound is a genuine high-danger chance: the goalie is out of position and the net is
# open, so a shot off a rebound converts at a distinctly higher rate than a normal shot. This
# bonus is added directly to the attempt's shot-quality term (raising on-goal odds and lowering
# save odds). PROVISIONAL/TUNABLE magnitude.
REBOUND_QUALITY_BONUS = 0.32

# Defender shot-quality suppression (SIM_SYNERGY_PLAN.md Phase 2). Before this, the five on-ice
# defenders barely affected a shot -- resolution pitted shooter skill vs goalie skill, and the
# skaters mattered only via chemistry, the shot-blocker pick, and hits. Now the DEFENDING on-ice
# group's average defensive value (0.7*defensive_awareness + 0.3*checking, see
# ratings.defensive_value) suppresses the attempt's shot-quality term: a strong defensive group
# forces lower-quality looks (tighter gaps, fewer clean lanes), a weak one concedes better ones.
# Centered on DEF_SUPPRESSION_PIVOT (~measured league-average on-ice 3F+2D group value) so an
# AVERAGE defensive group is a no-op and league-wide goals/game is conserved -- the same
# constant-pivot, tune-against-the-sweep approach as BLOCK_RATING_PIVOT / HIT_SEPARATION_PIVOT
# above. Symmetric clamp so an extreme group can't invert or trivialize a chance. PROVISIONAL/
# TUNABLE (verify goals/game against a multi-seed season sweep in Phase 5).
DEF_SUPPRESSION_PIVOT = 69.3     # measured shot-weighted mean of the defending on-ice group's
                                  # def_value in-sim, so an average defense is a no-op and league
                                  # goals/game is conserved. NOT the raw all-skater rating mean
                                  # (~67): shots cluster toward certain defensive alignments, which
                                  # pulls the shot-weighted mean up -- measure, don't assume.
                                  # RE-MEASURED for the archetype-refresh round (was 70.0): the new
                                  # archetype distribution + skew-preserving calibration moved the
                                  # shot-weighted mean to ~69.27, and leaving the pivot above the
                                  # true mean handed every average shot a small free quality bonus.
DEF_SUPPRESSION_SLOPE = 0.004    # shot-quality points removed per defensive-value point above pivot
DEF_SUPPRESSION_MAX = 0.12       # symmetric clamp on the total quality delta (either direction)

# Offensive line-role synergy (SIM_SYNERGY_PLAN.md Phase 3). The ATTACKING on-ice group's
# line-role synergy (ratings.line_synergy_score, 0..1: does it pair a real creator with a real
# finisher?) raises or lowers the attempt's shot-quality term -- a well-composed line manufactures
# better looks (the one-timer a playmaker feeds a finisher), a lopsided one settles for worse ones.
# Same mechanical class as the PP/rush/rebound/defender quality deltas (a CHANCE-quality effect,
# not a rating-realization multiplier -- no player's rating is ever exceeded, exactly as a power
# play changes chance quality without upweighting anyone). Centered on SYNERGY_PIVOT_SCORE (the
# measured shot-weighted mean synergy of real auto-built lines in-sim) so an average line is a
# no-op and league goals/game is conserved. PROVISIONAL/TUNABLE (verify against the Phase 5 sweep).
SYNERGY_PIVOT_SCORE = 0.70       # measured shot-weighted mean forward-line synergy in-sim.
                                  # RE-MEASURED for the archetype-refresh round (was 0.69): putting
                                  # real finishers/playmakers in the top-six raised the mean to
                                  # ~0.700, so the old pivot was crediting the average line for
                                  # synergy it now has by default.
SYNERGY_QUALITY_SLOPE = 0.22     # shot-quality points added per synergy-score point above pivot
SYNERGY_QUALITY_MAX = 0.09       # symmetric clamp on the total quality delta (either direction)

# Hitting / body checks (DEVPLAN.md Step 2.x "impactful ratings"): the engine had no hit mechanic
# at all and the SkaterStatLine `hits` field was never incremented. Each shot-attempt cycle, the
# checking (defending) team may throw a body check on the puck carrier, and the fore-checking
# (attacking) team may finish a check of its own. Per-cycle probabilities are tuned so a full game
# nets a realistic ~20-25 hits per team. The hitter is chosen weighted by checking+strength.
HIT_CHANCE_DEF_PER_CYCLE = 0.72
HIT_CHANCE_OFF_PER_CYCLE = 0.60
# A more physical on-ice group throws more hits (real physical teams lead the league in hits), so
# the per-cycle hit chance scales with the hitting group's average checking/strength, centered on
# the ~69 rating mean so a league-average team stays at the base rate. Bounded so it stays sane.
HIT_TEAM_PHYSICALITY_SLOPE = 0.006
HIT_TEAM_PHYSICALITY_MIN_MULT = 0.55
HIT_TEAM_PHYSICALITY_MAX_MULT = 1.5
# A defensive body check may SEPARATE the carrier from the puck (a forced turnover) -- this is how
# checking/strength earn a gameplay effect, not just a counting stat. Separation odds come from the
# checker's checking/strength vs the carrier's strength/agility, centered on the ~69 rating mean.
# Kept modest (possession is conserved league-wide, so this shifts who-shoots-next, not total
# scoring). HIT_TURNOVER_FLIP_P is the possession-flip chance after a separating hit (vs the 0.50
# neutral coin flip). PROVISIONAL/TUNABLE.
HIT_SEPARATION_PIVOT = 69.0
HIT_SEPARATION_SLOPE = 0.004
HIT_SEPARATION_BASE = 0.25
HIT_SEPARATION_MIN = 0.05
HIT_SEPARATION_MAX = 0.55
HIT_TURNOVER_FLIP_P = 0.72

# Skating / agility (DEVPLAN.md Step 2.x "impactful ratings"): these were composite-only and never
# touched a live outcome. Now a player's speed (0.5*skating + 0.5*agility) drives two things:
#   1. the rush finishing bonus -- a fast player carrying the puck on the rush is more dangerous,
#      so the rush's save-suppression scales with the shooter's speed (centered on the ~65 mean so
#      an average rush is unchanged); and
#   2. zone entry -- a faster, more agile team is blown offside less often (cleaner entries, more
#      sustained o-zone time), scaling the per-cycle offside chance by the attacking group's speed.
# Both centered on the rating mean so a league-average team is unaffected. PROVISIONAL/TUNABLE.
RUSH_SPEED_PIVOT = 65.0
RUSH_SPEED_SLOPE = 0.0011
RUSH_BONUS_BASE = 0.03
RUSH_BONUS_MIN = 0.0
RUSH_BONUS_MAX = 0.08
OFFSIDE_SPEED_SLOPE = 0.008
OFFSIDE_SPEED_MIN_MULT = 0.45
OFFSIDE_SPEED_MAX_MULT = 1.6

# Goalie puck-handling (DEVPLAN.md Step 2.x): a puck-moving goalie plays the puck behind the net /
# cuts off dump-ins, occasionally killing an opponent's rush before it starts. A one-sided benefit
# above the goalie-population mean (a poor puck-handler simply doesn't help, he doesn't hurt), kept
# modest. PROVISIONAL/TUNABLE.
GK_PUCKHANDLING_PIVOT = 67.0
GK_PUCKHANDLING_RUSH_KILL_SLOPE = 0.006
GK_PUCKHANDLING_RUSH_KILL_MAX = 0.25

# NOTE (condition/durability, DEVPLAN.md Step 2.x): Player.condition-based between-game durability
# was scoped here but deliberately NOT wired -- the season schedule is fully abstracted (every team
# plays every day, no rest days), so a "played -> drain, rest -> recover" model can neither hold a
# stable value nor create any inter-team variation. It needs a schedule with real off-days first;
# deferred rather than shipping an inert/degenerate mechanic. config.BASE_INJURY_RATE stays unused
# for the same reason (it presumes a between-game injury cadence that this schedule doesn't model).

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

# ---------------------------------------------------------------------------
# Prospect development (`systems/prospects.py`)
# ---------------------------------------------------------------------------
# How many seasons a drafted player spends developing before they may sign an NHL
# contract, by where they were picked. v1 has no AHL/junior league to place them in, so
# this is a *status* rather than a place -- see systems/prospects.py's module docstring for
# why the missing minor leagues were an economic problem and not just a missing feature.
#
# The staggered shape mirrors how a real draft class actually reaches the NHL: the first
# overall pick usually plays immediately; the rest of the top ten mostly arrive a year
# later; the balance of the first round the year after that; and later-round picks spend
# three-plus years in junior, the AHL, the NCAA, or Europe, with many never arriving at
# all. Read as (last pick number in the band, seasons of development required); anything
# past the final band uses PROSPECT_DEVELOPMENT_YEARS_DEFAULT.
#
# Economically this is what stops cheap entry-level teenagers from displacing
# market-priced NHL players, which is what collapsed league payroll before it existed.
PROSPECT_DEVELOPMENT_YEARS_BY_PICK = (
    (1, 0),      # first overall: NHL-ready now (still subject to a rating check)
    (10, 1),     # rest of the top ten: mostly arrive the following season
    (32, 2),     # remainder of round one
)
PROSPECT_DEVELOPMENT_YEARS_DEFAULT = 3   # round two and later

# ---------------------------------------------------------------------------
# Development tiers (`systems/prospects.py`, docs/PROSPECT_DEV_PLAN.md)
# ---------------------------------------------------------------------------
# Where a prospect actually IS while developing, replacing the pick-number window above
# with a place + an age. These are abstract tiers, not simulated leagues: no schedule, no
# games, no standings (scope decision recorded in docs/PROSPECT_DEV_PLAN.md). What a tier
# does is gate eligibility (who may be assigned there) and set a development rate.
DEV_TIER_CHL = "chl"          # Canadian major junior (OHL/QMJHL/WHL)
DEV_TIER_NCAA = "ncaa"        # US college hockey
DEV_TIER_AHL = "ahl"          # the professional development league
DEV_TIER_EUROPE = "europe"    # European pro/junior
DEV_TIERS = (DEV_TIER_CHL, DEV_TIER_NCAA, DEV_TIER_AHL, DEV_TIER_EUROPE)

# Age bands per tier, inclusive on both ends: (min_age, max_age).
#
# CHL tops out at 19 because a 20-year-old drafted junior player turns pro in reality --
# the CHL's over-age rules exist mainly for undrafted players and are not worth modeling
# separately here. NCAA runs to 23 (four years of eligibility starting as late as 20).
# AHL's floor of 20 is the CHL-origin floor; see DEV_TIER_AHL_MIN_AGE_NON_CHL for why a
# non-junior player can get there two years earlier.
DEV_TIER_AGE_BANDS = {
    DEV_TIER_CHL: (16, 19),
    DEV_TIER_NCAA: (18, 23),
    DEV_TIER_AHL: (20, 25),
    DEV_TIER_EUROPE: (18, 25),
}

# The real CHL-NHL transfer agreement: a drafted major-junior player under 20 may play in
# the NHL or go back to junior, but NOT in the AHL. A player who came up any other way
# (NCAA, Europe, US junior) has no such restriction and can turn pro at 18. This single
# rule is the main reason `league_origin` has to be populated for real rather than left at
# the inert "none" default it has carried since Step 1.6.
DEV_TIER_AHL_MIN_AGE_NON_CHL = 18

# NCAA eligibility is four seasons. A player who exhausts it without being signed becomes
# a college free agent -- one of this round's two undrafted pathways.
NCAA_MAX_SEASONS = 4

# Past this age a player leaves the development system entirely and becomes an ordinary
# free agent, where `offseason.cull_free_agents` washes him out if he never became an NHL
# player. Most late-round picks never play a game; that is the correct outcome, not a leak.
MAX_PROSPECT_AGE = 25

# How good a player has to be before an NHL roster spot is the right place for him. The
# gate exists for economic reasons as much as realism: without it, every draft signed ~150
# prospects (median overall ~52 against a league median of ~67) straight onto NHL rosters at
# entry-level prices, displacing market-priced players until 41% of the league was on ELCs
# and payroll had collapsed from ~94% of the cap to ~65% (PR #61). Set just above the
# league's median regular.
#
# Lives in config rather than in `systems/draft_system.py` (where it started, as
# DRAFT_NHL_READY_OVERALL) now that promotion out of the development tiers asks the same
# question the draft does -- a prospect graduates when his rating says he belongs, so both
# call sites have to be reading the same number.
NHL_READY_OVERALL = 68

# An undrafted player is nobody's property forever. Real NHL: a North American amateur who
# goes unpicked keeps re-entering the draft until he ages out, at which point he becomes an
# unrestricted free agent any team may sign. That age-out is what makes the undrafted
# pathway a real pathway rather than a dead end -- develop past NHL_READY_OVERALL without
# being claimed and you hit the open market as a genuine prize.
UDFA_FREE_AGENT_AGE = 20

# The real CBA's 50-contract limit: a team may have at most this many players under
# professional contract (NHL roster + signed prospects) at once. Without it, entry-level
# deals are free -- they cost no cap space while the player is off-roster (see
# `systems/prospects.py`) -- so a team could sign every prospect it drafted forever and
# hoard the entire talent pipeline at zero cost.
MAX_CONTRACTS = 50

# How long a team holds a drafted player's rights before he returns to the pool. Real NHL
# is two years for major-junior players and four for college players (a team can keep NCAA
# rights until the August after graduation) -- that asymmetry is real, and it makes drafting
# a college kid a genuinely different bet from drafting a junior one. Keyed by the tier the
# player was assigned at the draft; anything unlisted uses the default.
PROSPECT_RIGHTS_YEARS = {
    DEV_TIER_CHL: 2,
    DEV_TIER_NCAA: 4,
    DEV_TIER_EUROPE: 4,
    DEV_TIER_AHL: 3,
}
PROSPECT_RIGHTS_YEARS_DEFAULT = 3

# Contract length bounds. Real NHL max is 8 years (7 for a sign-and-trade,
# simplified away here); rookie-scale (entry-level) deals are always 3 years
# flat, matching the real ELC's fixed 3-year term regardless of signing age.
MAX_CONTRACT_YEARS = 8
ROOKIE_CONTRACT_YEARS = 3

# ---------------------------------------------------------------------------
# Entry-level contracts (`systems/prospects.py`, docs/PROSPECT_DEV_PLAN.md)
# ---------------------------------------------------------------------------
# ELC term by the player's age when he signs, read as (max_age, years). The real CBA's
# schedule exactly: 18-21 gets three years, 22-23 two, 24 one, and 25+ isn't entry-level at
# all -- that player signs a normal market contract. Anything past the final band means
# "not ELC-eligible" (see ELC_MAX_AGE).
ELC_YEARS_BY_AGE = (
    (21, 3),
    (23, 2),
    (24, 1),
)
ELC_MAX_AGE = 24        # 25 and older: a market contract, not entry level

# The slide rule, and the whole reason a drafted teenager can be signed early without
# wasting the deal. A player who is 18 or 19 at the start of a season and plays fewer than
# ELC_SLIDE_GAMES NHL games that season does not burn a contract year: the deal slides
# forward intact.
#
# ELC_SLIDE_MAX_AGE = 19 is what bounds this at two slides without a separate counter --
# age advances exactly one year per offseason, so 18 -> 19 -> 20 can slide twice and no
# more, which is precisely the real rule's outcome (sign at 18, slide twice, the three-year
# deal starts at 20). `Contract.slide_years` records what happened for display and tests;
# it is not what enforces the limit.
ELC_SLIDE_MAX_AGE = 19
ELC_SLIDE_GAMES = 10

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

# ---------------------------------------------------------------------------
# Salary curve (`systems/cap.py::base_salary_for()`)
# ---------------------------------------------------------------------------
# Breakpoints of the league's ability->pay curve, as (overall, annual salary at
# an $82.5M cap) pairs on attributes.py's 25-99 rating scale, linearly
# interpolated between points and flat outside the ends. Salaries scale with the
# live cap (see `base_salary_for()`), so the curve keeps its shape as the cap
# grows each offseason.
#
# CALIBRATED, not guessed: the curve is fitted so that applying it to
# leaguegen's actual generated rating/age distribution (a ~N(66, 10) overall
# spread over a 22-man roster) produces a mean team payroll of ~95% of the cap
# -- i.e. real NHL cap pressure, where a team's roster genuinely consumes its
# cap and adding a star means shedding salary. The resulting per-team shape is
# roughly 1 player above $9M, 2-3 in the $6-9M band, 5 in $4-6M, 7 in $2-4M,
# and 7 at or near the minimum, which matches a real NHL cap sheet's silhouette.
#
# Convexity is the point: pay rises much faster than ability at the top (a
# 90-overall is ~3x a 70-overall's rating percentile but ~3x their salary too),
# which is what makes star contracts a genuine roster-building tradeoff rather
# than a rounding error.
SALARY_CURVE = (
    (45, 800_000),
    (50, 875_000),
    (55, 1_050_000),
    (60, 1_600_000),
    (65, 2_600_000),
    (70, 4_000_000),
    (75, 5_600_000),
    (80, 7_400_000),
    (85, 9_400_000),
    (90, 11_500_000),
    (95, 13_600_000),
    (99, 15_200_000),
)

# The cap the SALARY_CURVE dollar figures above are quoted at. `base_salary_for()`
# scales the curve by (live cap / this) so a growing cap lifts salaries with it
# rather than silently making every contract cheaper in cap-percentage terms.
SALARY_CURVE_REFERENCE_CAP = SALARY_CAP_BASE

# Aging adjustments applied on top of the curve in `systems/cap.py::market_salary()`.
# Teams pay a premium for young players whose scouted potential outruns their
# current ability, and get a discount on players past the NHL aging curve's cliff.
YOUNG_UPSIDE_PREMIUM = 1.12
VETERAN_DISCOUNT_AGE = 34
VETERAN_DISCOUNT = 0.80

# ---------------------------------------------------------------------------
# World-generation payroll targets (`gen/leaguegen.py`)
# ---------------------------------------------------------------------------
# A freshly generated league represents an *already-running* NHL, where teams
# have spent years accumulating contracts and sit right up against the cap --
# not an expansion league with $50M of open space. After building a roster,
# leaguegen fits that roster's generated contracts to a per-team payroll target
# drawn uniformly from this band (as a fraction of the cap), so the league opens
# with realistic cap pressure and a realistic *spread*: contenders pressed to the
# ceiling, rebuilding clubs carrying real space.
#
# The band's top stops short of 1.0 so every team opens cap-legal with at least a
# little room to make a move, and its bottom keeps a normal team inside ~$6M of the
# ceiling -- real NHL teams operate pressed right up against the cap, not $20M under it.
GEN_PAYROLL_FRACTION_MIN = 0.93
GEN_PAYROLL_FRACTION_MAX = 0.995

# Roughly a fifth of the league is mid-teardown at any time and carries real space to
# absorb salary in a trade. Those teams draw from this lower band instead. Note the cap
# is *hard* in v1 (see systems/cap.py) -- no team ever generates above it; the spread is
# entirely about how much room teams have underneath, not about who's over.
GEN_REBUILDING_TEAM_SHARE = 0.20
GEN_REBUILDING_PAYROLL_FRACTION_MIN = 0.78
GEN_REBUILDING_PAYROLL_FRACTION_MAX = 0.92

# Contract-negotiation noise at world gen: a generated deal lands within this
# multiplicative band of the player's market value (some teams overpaid, some got
# a bargain), before the payroll fit above scales the roster onto its target.
GEN_SALARY_NOISE_MIN = 0.88
GEN_SALARY_NOISE_MAX = 1.18
