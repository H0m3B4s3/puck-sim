"""Game result containers: per-player box scores and a play-by-play log.

Mirrors HoopR's ``hoopsim/sim/boxscore.py`` (59 lines: ``PBPEvent``, ``GameResult`` w/ a single
``box: Dict[int, StatLine]``), with the one structural change DEVPLAN.md Step 1.12 calls out
explicitly: hockey has **two** box-score shapes (DESIGN.md point 9), so ``GameResult`` carries
``skater_box: Dict[int, SkaterStatLine]`` and ``goalie_box: Dict[int, GoalieStatLine]`` as two
separate dicts rather than one combined mapping -- downstream box-score rendering wants to iterate
skaters and goalies separately anyway, so this is the cleanest split, not a compromise.

``PBPEvent`` carries enough structured fields to reconstruct what happened (not just a free-text
description), per DESIGN.md point 10: a shot-attempt event in particular needs ``shot_type``/
``zone``/``strength_state``/``rebound``/``rush`` so a later step can score xG and tally Corsi/
Fenwick as a simple filter over this same event stream, without a schema rewrite. Every event also
carries ``team_id`` and the player id(s) involved (``player_id``, and ``assist_player_id`` for
goals) rather than only a human-readable ``description``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from pucksim.models.stats import GoalieStatLine, SkaterStatLine

# -- event_type vocabulary ----------------------------------------------------
EVENT_FACEOFF = "faceoff"
EVENT_SHOT = "shot"
EVENT_GOAL = "goal"
EVENT_PENALTY = "penalty"
EVENT_INJURY = "injury"          # DEVPLAN.md Step 2.3
EVENT_PERIOD_END = "period_end"
EVENT_GAME_END = "game_end"

# -- shot_type vocabulary (small, reasonable first-pass set) ------------------
SHOT_TYPES = ("wrist", "slap", "one_timer", "backhand", "tip")

# -- shot outcome vocabulary (used by PBPEvent.description / tests) -----------
SHOT_OUTCOME_GOAL = "goal"
SHOT_OUTCOME_SAVE = "save"
SHOT_OUTCOME_MISS = "miss"
SHOT_OUTCOME_BLOCK = "block"


@dataclass
class PBPEvent:
    """One play-by-play entry.

    ``time_secs`` is elapsed game time in seconds since the start of the game (period-independent,
    monotonically increasing across periods/OT) -- documented here since DEVPLAN.md leaves the
    exact convention to the implementer. Use ``period``/``time_secs`` together to reconstruct
    in-period clock if needed (``time_secs - (period - 1) * config.PERIOD_SECONDS``, with the usual
    OT caveats).
    """

    period: int
    time_secs: float
    event_type: str
    description: str = ""

    # -- structured context (optional; populated per event_type) ------------
    home_score: int = 0
    away_score: int = 0
    team_id: Optional[int] = None            # team the event is attributed to (attacking team for
                                              # shots/goals, winning team for faceoffs)
    player_id: Optional[int] = None          # shooter / goal-scorer / faceoff winner
    assist_player_id: Optional[int] = None   # primary assist, goals only
    secondary_assist_player_id: Optional[int] = None
    goalie_id: Optional[int] = None          # opposing goalie facing the shot/goal

    # -- shot-attempt analytics context (DESIGN.md point 10) -----------------
    # Populated for EVENT_SHOT / EVENT_GOAL only; carried at generation time so a later step can
    # score xG and tally Corsi/Fenwick as a plain filter over this event stream.
    shot_type: Optional[str] = None          # one of SHOT_TYPES
    zone: Optional[str] = None               # e.g. "slot", "point", "high_slot", "bad_angle"
    strength_state: Optional[str] = None     # the REAL strength state at the moment of the
                                              # attempt (config.STRENGTH_* -- Step 2.1 made this
                                              # a live value instead of an always-5v5 literal)
    rebound: bool = False
    rush: bool = False
    outcome: Optional[str] = None            # one of the SHOT_OUTCOME_* constants
    xg: float = 0.0                          # this attempt's expected-goals value (0 for a
                                              # blocked/missed attempt that never threatened)
    on_ice_size: int = 0                     # attacking team's on-ice skater count at this attempt
                                              # (4 PK / 5 even / 6 pulled goalie) -- lets Corsi/
                                              # Fenwick box totals reconcile exactly against the
                                              # event stream regardless of strength (DEVPLAN.md
                                              # Step 2.5 "Known latent test bug" fix)

    # -- penalty context (EVENT_PENALTY only, DEVPLAN.md Step 2.1) ------------
    penalty_type: Optional[str] = None       # "minor" | "major" | "misconduct"
    penalty_duration_secs: Optional[float] = None

    # -- faceoff context (EVENT_FACEOFF only, DEVPLAN.md Step 2.3) ------------
    # ``stoppage_type`` records WHY this faceoff happened (see engine.py's FACEOFF_STOPPAGE_*
    # constants: period start, after a goal, icing, offside, or a drawn penalty) -- useful
    # play-by-play flavor and a hook for a future zone/possession-quality model, not itself a
    # tracked box-score stat. ``won_off_tie`` distinguishes a clean center-vs-center win from a
    # three-way-roll tie that was resolved by the wingers' secondary roll (DEVPLAN.md Step 2.3's
    # "Three-way faceoff resolution" design note) -- ``fo_won``/``fo_lost`` stay strictly binary
    # regardless of which path produced the winner; this field is the only place the distinction
    # is recorded, since it's useful future signal (a scrum-then-recovery draw is a believably
    # worse start to a shift than a clean win) but not a real NHL box-score category today.
    stoppage_type: Optional[str] = None
    won_off_tie: bool = False


@dataclass
class GameResult:
    home_tid: int
    away_tid: int
    home_score: int = 0
    away_score: int = 0
    went_ot: bool = False
    went_so: bool = False

    # Two separate box-score shapes (DESIGN.md point 9) -- pid -> stat line.
    skater_box: Dict[int, SkaterStatLine] = field(default_factory=dict)
    goalie_box: Dict[int, GoalieStatLine] = field(default_factory=dict)

    # Play-by-play log. Empty by default (``collect_pbp=False`` at the GameSim level) to keep
    # memory down over many simulated games -- mirrors HoopR's ``GameSim(..., collect_pbp=...)``
    # toggle.
    pbp: List[PBPEvent] = field(default_factory=list)

    # In-game injuries (DEVPLAN.md Step 2.3), collected regardless of ``collect_pbp`` (this is
    # season-persistent state the caller MUST apply, not optional PBP flavor) -- mirrors HoopR's
    # ``GameResult.injuries`` list of ``(pid, games_remaining, description, severity)`` tuples.
    # ``sim/season.py``'s ``_apply_result`` reads this after every game to update
    # ``Player.injury``.
    injuries: List[Tuple[int, int, str, str]] = field(default_factory=list)

    @property
    def winner(self) -> Optional[int]:
        """Winning team id, or ``None`` for an unresolved tie (the provisional MVP OT
        placeholder -- see sim/engine.py -- can leave a game level; Step 2.6's real OT/shootout
        always produces a decision, so this ``None`` case only matters until then)."""
        if self.home_score == self.away_score:
            return None
        return self.home_tid if self.home_score > self.away_score else self.away_tid

    @property
    def loser(self) -> Optional[int]:
        if self.home_score == self.away_score:
            return None
        return self.away_tid if self.home_score > self.away_score else self.home_tid

    # -- per-player line accessors (create-on-first-touch, mirrors HoopR's ``line()``) ----
    def skater_line(self, pid: int) -> SkaterStatLine:
        if pid not in self.skater_box:
            self.skater_box[pid] = SkaterStatLine()
        return self.skater_box[pid]

    def goalie_line(self, pid: int) -> GoalieStatLine:
        if pid not in self.goalie_box:
            self.goalie_box[pid] = GoalieStatLine()
        return self.goalie_box[pid]

    def team_skater_totals(self, pids: List[int]) -> SkaterStatLine:
        total = SkaterStatLine()
        for pid in pids:
            if pid in self.skater_box:
                total.add(self.skater_box[pid])
        return total
