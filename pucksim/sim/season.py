"""Regular-season orchestration: scheduling, result application, and day advancement.

Mirrors HoopR's ``hoopsim/sim/season.py`` (154 lines) shape directly: ``generate_schedule()``
(circle-method round-robin, DESIGN.md's explicit sport-agnostic carryover), ``_apply_result()``/
``sim_one()``/``advance_one_day()``/``start_season()``. No ``_heal_injuries()``-equivalent exists
here -- PuckSim has no injury system yet (that's DEVPLAN.md Step 2.3); a future step that adds one
should hook it into ``advance_one_day()`` right after the day's games are simmed, the same spot
HoopR's own per-day injury-healing tick lives.

Goalie rest-based starter rotation (DEVPLAN.md Step 2.2): ``sim_one()`` is now the per-game hook
that decides which of a team's two rostered goalies actually starts (``sim/goalies.py``'s
``choose_starting_goalie``, backed by a process-local ``GoalieRestState`` tracker -- see
``_rest_state_for``'s docstring for exactly why that tracker lives here, keyed off the ``World``
instance, rather than as a new field on ``Player``/``Team``/``World`` itself) before constructing
the game, rather than letting ``GameSim`` silently default to ``Team.goalie_starter`` every time.

Schedule generation (circle-method round-robin, cycled to reach 82 games):
--------------------------------------------------------------------------
A true single round-robin among ``config.NUM_TEAMS`` (32, even) teams produces exactly
``NUM_TEAMS - 1`` (31) rounds, each a complete pairing of every team against a different
opponent. That's short of ``config.SEASON_GAMES`` (82) per team, and doesn't naturally alternate
home/away across rounds on its own. This implementation:

  1. Builds ONE circle-method round-robin "cycle" of 31 rounds via the standard fixed-team +
     rotating-array algorithm (one team held fixed, the rest rotate one position per round; each
     round pairs position ``i`` with position ``n-1-i``). Within a cycle, home/away is assigned by
     alternating on ``(cycle_parity + round_index)`` so consecutive cycles flip who's "usually
     home" for a given pairing, spreading home/away roughly evenly over repeated cycles rather than
     always favoring the same side.
  2. Repeats full cycles back-to-back (each subsequent cycle re-runs the same rotation from
     scratch, so every cycle is itself a complete legal round-robin, not a resumed rotation) until
     the running per-team game count would meet or exceed ``target_games``. The final partial
     cycle is truncated by only taking as many additional rounds as needed to hit the target
     exactly (so every team lands on exactly ``target_games``, not "some number >= target").
  3. ``day`` is assigned sequentially and globally across cycles (round 0 of cycle 2 continues at
     the next day after cycle 1's last round, not day 0 again), so ``advance_one_day()`` can always
     find "today's" games by a simple ``day == world.day`` scan with no cycle bookkeeping needed
     downstream.

This is deliberately simple (DEVPLAN.md: "keep this reasonably simple, it doesn't need to match
real NHL's divisional-weighted scheduling, v2+ defers that fidelity") -- it does not attempt
divisional/conference weighting, back-to-back avoidance, or travel modeling.

Tie-reconciliation (the core design decision of this step):
-------------------------------------------------------------
The MVP engine (Step 1.12) has a provisional OT placeholder: a game tied after regulation plays
one extra simplified sudden-death period; if STILL tied, the game comes back from
``simulate_game()`` as an **unresolved tie** (``GameResult.winner is None``, ``went_ot=True``,
``went_so=False`` always -- real 3-on-3/shootout resolution is Step 2.6, not built yet).

Separately, standings math (Step 1.8) is rule-parameterized. Under ``"retro"`` a tie is a fully
legal outcome (``points_for_game()`` awards ``rule["tie"]`` to both teams). Under ``"standard"``/
``"three_two_one_zero"`` (``config.STANDINGS_RULES[rule]["has_shootout"] is True``) there is NO
tie point value -- ``points_for_game()`` raises ``ValueError`` if ever called on a tied ``Game``
under those rules, because a real shootout guarantees a decisive winner in real hockey.

``_apply_result()`` reconciles this every time, BEFORE recording the ``Game``, based on
``world.standings_rule``:

  - ``"retro"``: an unresolved tie is legitimate. Record the game with ``played=True``, scores and
    ``went_ot`` exactly as the engine returned them (``went_ot=True`` -- the OT placeholder period
    was played and didn't produce a goal), and ``went_so=False``. ``league.py``'s ``Game.is_tie``
    correctly reads this as a tie (it only requires level scores and no shootout, NOT "no OT" --
    DESIGN.md point 8 confirms regular-season OT is played regardless of standings rule; "retro"
    just skips the shootout that would otherwise follow an undecided OT), so standings math
    handles it correctly via ``rule["tie"]`` with no massaging needed here.
    (2026-07-01 note: an earlier revision of this function forced ``went_ot=False`` here to work
    around a since-fixed bug in ``league.py``'s ``is_tie`` -- see that file's docstring. No longer
    needed.)
  - ``"standard"`` / ``"three_two_one_zero"`` (``has_shootout=True``) AND the engine returned an
    unresolved tie (``result.winner is None``): a decisive winner is manufactured via a clearly
    provisional placeholder tiebreak -- **NOT real shootout simulation** (that's Step 2.6). The
    approach chosen: a light skill-based coin flip, weighted by each team's average roster
    ``overall`` (a team with a stronger roster is proportionally more likely to win the "shootout"
    placeholder, rather than a flat 50/50, which would ignore team strength entirely for a
    decision that in real hockey does correlate somewhat with shooter/goalie talent). The recorded
    score is then bumped by exactly 1 goal for the placeholder-selected winner (e.g. a 3-3 tie
    becomes a 4-3 win) -- this keeps ``Game.winner``/``Game.loser`` derivable the normal way
    (``home_score > away_score``) without needing a separate "decisive winner" side-channel field
    on ``Game``, and reads naturally as a shootout-decided final score. ``went_ot`` is preserved as
    returned by the engine (True, since regulation + the OT placeholder period were both played);
    ``went_so`` is deliberately set True here (unlike the raw engine result, which always reports
    ``went_so=False`` since it has no real shootout) -- this module is the place a decisive
    "extra" goal beyond regulation+OT was manufactured, so it is exactly analogous to a real
    shootout-winning goal for standings/box-score purposes, and ``went_so=True`` is what
    ``points_for_game()`` needs to select the ``so_win``/``so_loss`` column correctly. Every player
    stat line is accumulated from the engine's actual box score (unmodified) -- the placeholder
    only adjusts the final recorded score/outcome flags, never invents a phantom goal-scorer stat
    line.

Invariant this guarantees: every played ``Game`` under a ``has_shootout=True`` rule always has a
decisive ``winner`` by the time ``points_for_game()``/``standings()`` are called on it, so a full
82-game/32-team season never raises mid-run regardless of the active standings rule.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pucksim import config
from pucksim.models.league import Game, Phase
from pucksim.models.stats import GoalieStatLine, SkaterStatLine
from pucksim.models.team import Team
from pucksim.models.world import World
from pucksim.sim.boxscore import GameResult
from pucksim.sim.engine import simulate_game
from pucksim.sim.goalies import GoalieRestState, choose_starting_goalie

# ---------------------------------------------------------------------------
# Goalie rest-state tracking (DEVPLAN.md Step 2.2) -- WHERE THIS STATE LIVES, AND WHY:
#
# "Games since a goalie last started" has no home anywhere in the permanent data model
# (Player/Team/World) -- see sim/goalies.py's module docstring for the full reasoning. It's
# transient game-orchestration bookkeeping this module (the day-by-day season driver) is the
# natural owner of, but every existing caller of sim_one()/advance_one_day() (tests, testkit,
# eventually the web layer) calls them with just ``(world, ...)`` and no extra state argument,
# repeatedly, across an entire season -- threading a new required parameter through every call
# site would be a much larger, non-additive signature change than this step needs.
#
# Compromise: a process-local cache, keyed by ``id(world)`` (NOT the World instance itself --
# World is a plain ``@dataclass`` with a generated ``__eq__``, which makes it unhashable, so a
# WeakKeyDictionary keyed on the instance isn't an option) rather than a new World field. This
# keeps World's schema/save format completely untouched (no migration concerns) while still
# giving the rotation logic continuity across many sequential advance_one_day() calls against
# the same World, which is what a real season loop does. A reloaded save (a new World instance,
# hence a new id()) gets a fresh tracker (goalies treated as fully rested) -- see
# sim/goalies.py's docstring for why that's an acceptable, clearly-documented simplification.
#
# CORRECTNESS NOTE, not just a memory-growth one: the cache value is ``(world, state)``, not just
# ``state`` -- holding a strong reference to ``world`` itself alongside its state is required, not
# optional. ``id()`` is only guaranteed unique among currently-alive objects; if a World were
# garbage-collected and this cache held no reference to it, CPython's allocator could hand that
# same address to a brand-new, entirely unrelated World (team ids collide across saves/leagues,
# e.g. always 0..31), and that new World would silently inherit a stale rest-rotation history that
# has nothing to do with it -- a real, if rare, bug, not a hypothetical one, once anything in this
# process ever holds more than one World at a time (the planned FastAPI web layer, Step 2.9/2.10,
# will keep multiple leagues' Worlds alive concurrently). Keeping ``world`` alive in the cache
# value means an id can never be silently reused out from under an existing entry; the ``is``
# identity check below is a defensive second layer in case that invariant is ever broken by a
# future refactor. The tradeoff this accepts (never evicting old entries, so every World that's
# ever been simmed lives for the rest of the process) is the same one already called out below for
# memory growth -- this just also closes the correctness gap that tradeoff was quietly leaning on.
# ---------------------------------------------------------------------------
_REST_STATE_BY_WORLD_ID: Dict[int, Tuple[World, GoalieRestState]] = {}


def _rest_state_for(world: World) -> GoalieRestState:
    key = id(world)
    entry = _REST_STATE_BY_WORLD_ID.get(key)
    if entry is None or entry[0] is not world:
        entry = (world, GoalieRestState())
        _REST_STATE_BY_WORLD_ID[key] = entry
    return entry[1]


# ---------------------------------------------------------------------------
# Scheduling (circle method: every team plays exactly once per round, cycled
# to reach config.SEASON_GAMES per team).
# ---------------------------------------------------------------------------
def _one_round_robin_cycle(tids: List[int]) -> List[List[tuple]]:
    """Build one complete circle-method round-robin cycle.

    Returns a list of rounds; each round is a list of ``(home, away)`` tuples (home/away not yet
    finalized for alternation -- caller decides which side is home per round/cycle). ``len(tids)``
    must be even. Produces ``len(tids) - 1`` rounds, each a complete pairing of every team.
    """
    n = len(tids)
    fixed, rot = tids[0], tids[1:]
    rounds: List[List[tuple]] = []
    for r in range(n - 1):
        arrangement = [fixed] + rot
        pairs = []
        for i in range(n // 2):
            pairs.append((arrangement[i], arrangement[n - 1 - i]))
        rounds.append(pairs)
        rot = [rot[-1]] + rot[:-1]
    return rounds


def generate_schedule(world: World, rng=None, target_games: int = config.SEASON_GAMES) -> List[Game]:
    """Build a full season schedule reaching ``target_games`` per team.

    Uses a circle-method round-robin as the base generator, repeating full cycles (each cycle a
    complete legal round-robin of ``config.NUM_TEAMS - 1`` rounds) until every team has played
    ``target_games`` games, truncating the final cycle exactly at the target. Home/away alternates
    by cycle parity + round index so repeated matchups roughly balance home/away over multiple
    cycles rather than always favoring one side.

    ``rng`` is accepted for signature symmetry with the rest of the sim layer (season generation
    is currently fully deterministic given ``tids``/``target_games`` -- no random draws are made),
    and reserved for a future pass that might randomize cycle order/bye-week placement.

    Assigns unique ``gid`` values via ``world.new_gid()`` and sequential ``day`` values (globally
    increasing across cycles) so ``advance_one_day()`` can find "today's" games via a simple
    ``day == world.day`` scan.
    """
    tids = sorted(world.teams.keys())
    n = len(tids)
    if n < 2:
        return []
    if n % 2 != 0:
        raise ValueError(f"generate_schedule requires an even number of teams, got {n}")

    base_cycle = _one_round_robin_cycle(tids)

    schedule: List[Game] = []
    games_per_team = 0
    day = 0
    cycle_idx = 0

    while games_per_team < target_games:
        for round_idx, pairs in enumerate(base_cycle):
            if games_per_team >= target_games:
                break
            for a, b in pairs:
                # Alternate home/away by cycle + round parity so repeated cycles balance sides.
                if (cycle_idx + round_idx) % 2 == 0:
                    home, away = a, b
                else:
                    home, away = b, a
                schedule.append(Game(gid=world.new_gid(), day=day, home=home, away=away))
            games_per_team += 1
            day += 1
        cycle_idx += 1

    return schedule


# ---------------------------------------------------------------------------
# Result application -- includes the tie-reconciliation described in the
# module docstring above.
# ---------------------------------------------------------------------------
def _average_overall(team: Team, world: World) -> float:
    """Average ``overall`` across a team's roster -- used only by the provisional placeholder
    tiebreak below. Falls back to a neutral 50.0 if the roster is somehow empty (shouldn't happen
    post-leaguegen, but this must never crash a season run)."""
    ratings = [world.player(pid).overall for pid in team.roster if pid in world.players]
    return sum(ratings) / len(ratings) if ratings else 50.0


def _placeholder_tiebreak_winner(world: World, game: Game) -> int:
    """Provisional MVP-only tiebreak for an unresolved tie under a ``has_shootout=True`` rule.

    NOT real shootout simulation (Step 2.6 owns that). A light skill-based coin flip: each team's
    win probability is nudged away from 50/50 by the gap between the two teams' average roster
    ``overall``, using the same small-gap-to-probability-nudge shape the engine itself uses
    elsewhere (a modest multiplier keeps this from ever becoming near-deterministic purely off
    overall gap, since a real shootout is still mostly chance). Returns the winning team id.
    """
    home_ovr = _average_overall(world.team(game.home), world)
    away_ovr = _average_overall(world.team(game.away), world)
    gap = home_ovr - away_ovr
    home_win_p = max(0.30, min(0.70, 0.5 + gap * 0.01))
    return game.home if world.rng.chance(home_win_p) else game.away


def _apply_result(world: World, game: Game, result: GameResult) -> None:
    """Apply a played game's ``GameResult`` to ``game``, both teams' records, and every involved
    player's season stat line. Performs the has_shootout tie-reconciliation described in this
    module's docstring before recording anything, so the recorded ``Game`` always satisfies
    ``points_for_game()``'s requirements for the active ``world.standings_rule``.
    """
    rule_table = config.STANDINGS_RULES[world.standings_rule]
    unresolved_tie = result.winner is None

    home_score = result.home_score
    away_score = result.away_score
    went_ot = result.went_ot
    went_so = result.went_so   # always False coming out of the MVP engine

    if unresolved_tie and rule_table["has_shootout"]:
        # This rule set cannot legally represent a tie -- manufacture a decisive winner via the
        # provisional placeholder tiebreak (see module docstring). Bump the recorded score by
        # exactly one goal for the selected winner so Game.winner/loser derive normally from
        # home_score/away_score, and flag went_so=True since this is standing in for a real
        # shootout-winning goal.
        winner_tid = _placeholder_tiebreak_winner(world, game)
        if winner_tid == game.home:
            home_score += 1
        else:
            away_score += 1
        went_so = True
    # elif unresolved_tie (a legitimate "retro" tie): went_ot is preserved exactly as the engine
    # returned it (True -- the OT placeholder period was played and didn't produce a goal).
    # Corrected 2026-07-01: an earlier revision of this function forced went_ot=False here to
    # work around what turned out to be a bug in league.py's `Game.is_tie` (which incorrectly
    # required `not went_ot`); that property has since been fixed at the source -- see
    # league.py's docstring -- so no override is needed here. DESIGN.md point 8 confirms regular-
    # season OT is played regardless of standings rule; "retro" just skips the shootout that
    # would otherwise follow an undecided OT, so went_ot=True is the factually correct record
    # for a drawn retro game, not a wrinkle to paper over.
    # else: already a decisive result -- nothing to reconcile.

    game.home_score = home_score
    game.away_score = away_score
    game.played = True
    game.went_ot = went_ot
    game.went_so = went_so

    home_team = world.team(game.home)
    away_team = world.team(game.away)

    if game.is_tie:
        # NOTE: a legitimate retro tie is neither a win, loss, nor OT-loss under Team's simplified
        # 3-bucket record model (see team.py -- there is no "tie" bucket). Rather than misrecord a
        # tie as a loss for both teams (which would corrupt win/loss reconciliation tests), skip
        # Team.record_result() entirely for a tie -- Team's win/loss/ot_loss counters are a
        # simplified display aid (per league.py's module docstring, standings() itself never reads
        # them), so leaving both sides untouched for a tie is the least-wrong option available
        # without extending Team's schema (out of bounds for this step).
        pass
    else:
        home_won = game.home_score > game.away_score
        if home_won:
            home_team.record_result("win", home_score, away_score)
            away_team.record_result("ot_loss" if went_ot or went_so else "loss", away_score, home_score)
        else:
            away_team.record_result("win", away_score, home_score)
            home_team.record_result("ot_loss" if went_ot or went_so else "loss", home_score, away_score)

    # Accumulate every player's game stat line into their season-long StatLine.
    for pid, line in result.skater_box.items():
        player = world.players.get(pid)
        if player is not None and isinstance(player.season, SkaterStatLine):
            player.season.add(line)
    for pid, line in result.goalie_box.items():
        player = world.players.get(pid)
        if player is not None and isinstance(player.season, GoalieStatLine):
            player.season.add(line)


def _choose_and_record_starter(world: World, tid: int, rest_state: GoalieRestState,
                                day: int) -> Optional[int]:
    """Pick this team's starting goalie for a game on ``day`` (DEVPLAN.md Step 2.2's rest-based
    rotation hook) and immediately record the choice into ``rest_state`` so the NEXT game this
    team plays sees an up-to-date consecutive-starts/back-to-back picture. Returns ``None`` if
    the team has no goalie at all rostered (shouldn't happen post-leaguegen, but
    ``choose_starting_goalie``/``GameSim`` both already handle a ``None`` starter gracefully --
    see their own docstrings -- so this never needs to crash a season run)."""
    team = world.team(tid)
    starter_pid = choose_starting_goalie(team, rest_state, day=day, rng=world.rng)
    if starter_pid is not None:
        rest_state.record_start(tid, starter_pid, day)
    return starter_pid


def sim_one(world: World, game: Game) -> GameResult:
    """Simulate and apply a single scheduled game.

    Consumes ``sim/goalies.py``'s rest-based rotation (DEVPLAN.md Step 2.2): before
    constructing the game, decides each team's actual starting goalie for TODAY (which may be
    the backup, per ``choose_starting_goalie``'s tendency model) via this module's
    process-local ``GoalieRestState`` tracker (see ``_rest_state_for``), and passes that choice
    into ``simulate_game`` as an explicit override rather than letting ``GameSim`` silently fall
    back to ``Team.goalie_starter`` every time.
    """
    rest_state = _rest_state_for(world)
    home_goalie_id = _choose_and_record_starter(world, game.home, rest_state, game.day)
    away_goalie_id = _choose_and_record_starter(world, game.away, rest_state, game.day)

    result = simulate_game(world, game.home, game.away,
                           home_goalie_id=home_goalie_id, away_goalie_id=away_goalie_id)
    _apply_result(world, game, result)
    return result


# ---------------------------------------------------------------------------
# Day advancement
# ---------------------------------------------------------------------------
def advance_one_day(world: World) -> List[Game]:
    """Simulate every unplayed game scheduled on ``world.day``, then advance the day counter.

    Returns the list of ``Game`` objects played today. No injury-healing tick exists here (see
    module docstring) -- no injury system exists yet (DEVPLAN.md Step 2.3).
    """
    todays = [g for g in world.schedule if g.day == world.day and not g.played]
    for game in todays:
        sim_one(world, game)
    world.day += 1
    return todays


def regular_season_complete(world: World) -> bool:
    """True once every scheduled game has been played."""
    return all(g.played for g in world.schedule)


def start_season(world: World) -> None:
    """Reset records/stats and build a fresh regular-season schedule."""
    world.schedule = generate_schedule(world)
    world.phase = Phase.REGULAR_SEASON
    world.day = 0

    for team in world.teams.values():
        team.reset_record()

    for player in world.players.values():
        player.season = GoalieStatLine() if player.is_goalie else SkaterStatLine()
