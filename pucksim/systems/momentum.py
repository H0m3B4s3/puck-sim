"""Season momentum: how a player's morale moves game to game, and the team's form read.

Structural precedent: HoopR's ``hoopsim/systems/momentum.py`` (111 lines: ``update_morale()``/
``offseason_reset()``/``game_score()``) -- this module ports that generic, sport-agnostic
framework shape directly, swapping basketball's per-game production inputs for hockey's
(goals/assists/blocks/takeaways instead of points/rebounds/steals/blocks).

Morale is the *form* input to the in-game realization model (``sim/ratings.py``'s
``morale_realization()``): confidence a player carries across games, ALREADY capped downstream
(in ``ratings.py``, not here) so it only ever lets a player reach his ceiling -- never exceed
it (see that module's own "no upweighting" comments; ``morale_realization()`` returns exactly
1.0 for any morale >= 70, and only ever discounts BELOW 1.0 for morale under 70 -- it can never
push realization above 1.0 no matter how high morale climbs). This module only produces the raw
``Player.morale`` int (0-100, neutral 70) that feeds that already-capped downstream function --
it never itself computes or caps a realization multiplier, so there is nothing here that could
violate the no-upweighting principle; that enforcement point already lives entirely in
``sim/ratings.py`` and this module must not duplicate or bypass it.

Morale is driven mostly by **winning** (a winning locker room plays loose, a losing one tightens
up), modulated by a player's **own game** versus what a player of his caliber/role should
produce, and by his **role** (a healthy, available player who barely plays sours). Every game it
also mean-reverts toward a personal baseline, so streaks and slumps fade instead of running away
-- this keeps morale a bounded, self-correcting signal rather than a runaway accumulator.

NOTE on scope, since DEVPLAN.md's constraints flag this explicitly: this module governs SEASON-
LEVEL morale carryover (game-to-game and offseason-to-offseason) -- it has no interaction
whatsoever with the DETERMINISTIC in-game realization math itself (clutch/hot-hand/morale-
scaling live entirely in ``sim/ratings.py``/``sim/goalies.py``, both out of this step's scope
per DEVPLAN.md). This module is audited against the no-upweighting principle in this step's
report specifically because it's the piece of "realization-adjacent" code this step DOES touch
-- see the paragraph above for why it's clean (it only ever writes the raw ``morale`` int that
an already-existing, already-capped downstream function reads).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pucksim.models.stats import SkaterStatLine

if TYPE_CHECKING:                                  # avoid import cycles at runtime
    from pucksim.models.world import World
    from pucksim.sim.boxscore import GameResult

# -- tunables ----------------------------------------------------------------
# PROVISIONAL/TUNABLE magnitudes -- mirrors HoopR's own values/shape (that system's tuning is
# itself provisional there too); no hockey-specific morale-swing data exists to fit against yet.
MORALE_BASELINE = 70           # neutral form (= full realization under sim/ratings.py's scale)
MEAN_REVERT = 0.12             # fraction of the gap to baseline closed each game
W_RESULT = 2.4                 # winning is the dominant driver of confidence
W_PERF = 1.3                   # individual game vs. expectation for a player of his caliber
W_ROLE = 1.0                   # role satisfaction (ice time); a healthy DNP-equivalent sours
MAX_GAME_DELTA = 6.0           # cap on a single game's swing before reversion
MORALE_MIN, MORALE_MAX = 20, 99
ROTATION_MIN_SECS = 8 * 60.0   # ice time at/above which a player feels like a regular
GARBAGE_MIN_SECS = 2 * 60.0    # ice time below which it was a healthy-scratch-adjacent token shift

# Offseason carryover (mirrors HoopR's chemistry-rust + morale-drift pattern exactly, ported to
# Team.chemistry's pair_key()-keyed dict, same underlying shape Step 1.7 already built).
CHEM_CARRY_CAP = 60_000.0      # cap banked pair-time so it stays bounded and decay can bite
CHEM_RETENTION = 0.70          # fraction of (capped) shared time retained into the next season
MORALE_OFFSEASON_REVERT = 0.6  # fraction of the gap to baseline closed over the offseason


def game_score(s: SkaterStatLine) -> float:
    """One number for how good a single skater's game-line was (hockey-shaped analog of
    HoopR's Hollinger game score -- goals/assists weighted heaviest, physical/possession
    counters as secondary positive signal, giveaways as the lone negative)."""
    return (2.0 * s.g + 1.2 * s.a + 0.15 * s.sog
            + 0.3 * s.hits + 0.4 * s.blocks + 0.3 * s.takeaways
            - 0.3 * s.giveaways - 0.1 * s.pim)


def _result_signal(won: bool, margin: int) -> float:
    """+1 for a win, -1 for a loss, nudged up to +-0.5 more by the margin."""
    sign = 1.0 if won else -1.0
    return sign * (1.0 + min(0.5, margin / 4.0))    # hockey margins are small (goals, not points)


def _expected_game_score(overall: int, secs: float) -> float:
    """A rough bar for a player's production this game given his caliber and ice time.

    Coefficient derivation (PROVISIONAL/TUNABLE, shown explicitly per this codebase's
    convention rather than eyeballed): a league-AVERAGE (70-overall) skater's "unremarkable but
    fine" 18-minute night (a helper, no goal, one assist, a couple of shots/hits/blocks/
    takeaways, one giveaway) scores roughly ``game_score() ~= 2.2`` on this module's own scale
    -- verified directly by plugging a representative "typical" SkaterStatLine into
    ``game_score()``. The expectation bar should land close to THAT for a 70-overall player at
    18 minutes, not some unrelated arbitrary number, or every average performance would read as
    a below-expectation "bad game" and drag morale down every single night regardless of
    result. Solving ``(70 - 62) * 18 * c ~= 2.2`` gives ``c ~= 0.0153`` -- used directly rather
    than rounded further, since a coarser round number (e.g. 0.015) shifts the target bar by
    more than this derivation's own precision warrants.
    """
    return max(0.0, (overall - 62) * (secs / 60.0) * 0.0153)


def _personal_baseline(work_ethic: int) -> float:
    """High-character players settle a touch higher and steadier; low ones a touch lower."""
    return MORALE_BASELINE + (work_ethic - 70) * 0.15


def _new_morale(morale: int, delta: float, baseline: float) -> int:
    morale = morale + max(-MAX_GAME_DELTA, min(MAX_GAME_DELTA, delta))
    morale += (baseline - morale) * MEAN_REVERT          # mean-revert toward the personal baseline
    return int(round(max(MORALE_MIN, min(MORALE_MAX, morale))))


def update_morale(world: "World", home, away, result: "GameResult") -> None:
    """Update every rostered player's morale from one finished game.

    Healthy players feel the result, their own game, and their role; injured/unavailable
    players (who couldn't affect this game) simply drift toward their baseline. Goalies use the
    same result/role signal as skaters but skip the skater-specific ``game_score`` performance
    term (goalie in-game quality is better read from ``GoalieStatLine``, which this function
    intentionally keeps simple by not double-modeling here -- goalie performance-driven morale
    is a reasonable future refinement, not required for this step's award/legacy/offseason
    integration to work end-to-end).
    """
    home_won = result.home_score > result.away_score
    is_tie = result.home_score == result.away_score
    margin = abs(result.home_score - result.away_score)
    for team, won in ((home, not is_tie and home_won), (away, not is_tie and not home_won)):
        for pid in team.roster:
            p = world.players.get(pid)
            if p is None:
                continue
            baseline = _personal_baseline(p.ratings.get("work_ethic", 70))
            if p.is_injured:                              # not his game to influence
                p.morale = _new_morale(p.morale, 0.0, baseline)
                continue

            line = result.skater_box.get(pid) if not p.is_goalie else result.goalie_box.get(pid)
            secs = float(getattr(line, "secs", 0)) if line is not None else 0.0

            delta = W_RESULT * _result_signal(won, margin) if not is_tie else 0.0
            if secs < GARBAGE_MIN_SECS:                    # healthy but barely (or never) played
                delta += W_ROLE * -0.6
            elif secs < ROTATION_MIN_SECS:
                delta += W_ROLE * -0.15
            if isinstance(line, SkaterStatLine) and secs >= GARBAGE_MIN_SECS:
                exp = _expected_game_score(p.overall, secs)
                perf = max(-1.0, min(1.0, (game_score(line) - exp) / 4.0))
                delta += W_PERF * perf
            p.morale = _new_morale(p.morale, delta, baseline)


def offseason_reset(world: "World") -> None:
    """Carry chemistry and morale across the offseason (called between seasons, never before
    the season being closed out has already had ``update_morale`` applied to every game).

    Chemistry decays toward cold for thin pairings while established cores (banked well past
    the gelled threshold) survive; morale drifts most of the way back to each player's personal
    baseline -- a fresh season brings optimism, though last year's slump or swagger lingers a
    touch, exactly mirroring HoopR's own offseason carryover shape.
    """
    for team in world.teams.values():
        team.chemistry = {k: min(CHEM_CARRY_CAP, v) * CHEM_RETENTION
                          for k, v in team.chemistry.items()}
    for p in world.players.values():
        baseline = _personal_baseline(p.ratings.get("work_ethic", 70))
        p.morale = int(round(p.morale + (baseline - p.morale) * MORALE_OFFSEASON_REVERT))
