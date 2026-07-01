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
