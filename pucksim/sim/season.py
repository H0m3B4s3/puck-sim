"""Regular-season orchestration: scheduling, result application, and day advancement.

Mirrors HoopR's ``hoopsim/sim/season.py`` (154 lines) shape directly: ``generate_schedule()``
(circle-method round-robin, DESIGN.md's explicit sport-agnostic carryover), ``_apply_result()``/
``sim_one()``/``advance_one_day()``/``start_season()``.

Injuries (DEVPLAN.md Step 2.3): ``_apply_result()`` now applies every in-game injury
``sim/engine.py``'s ``GameResult.injuries`` collected (ONLY upgrading -- never downgrading -- an
existing injury, mirroring HoopR's own "the worse of the two" comparison, since a player already
out longer for an earlier knock shouldn't have that shortened by a lesser injury sustained before
he's even healed). ``_heal_injuries()`` (this step's addition, hooked into ``advance_one_day()``
right after the day's games are simmed -- exactly the spot this module's own docstring previously
flagged as the intended hook point, and the same spot HoopR's per-day injury-healing tick lives)
ticks ``games_remaining`` down by one for every active injury and clears it once healed.

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

Tie-reconciliation (DEVPLAN.md Step 2.6 replaced this step's original design):
-------------------------------------------------------------------------------
The MVP engine (Step 1.12) had a provisional OT placeholder that could leave a game as an
**unresolved tie** (``GameResult.winner is None``); this module used to paper over that with a
"MVP-era placeholder tiebreak" (a skill-weighted coin flip, ``_placeholder_tiebreak_winner``,
manufacturing a decisive winner + bumping the score by one goal whenever a ``has_shootout=True``
rule saw an unresolved tie come back from the engine).

DEVPLAN.md Step 2.6 replaced the engine's OT placeholder with REAL resolution
(``sim/engine.py``'s ``GameSim.coach_session``/``_resolve_shootout``): regular season now plays
3-on-3 sudden death, then (under a ``has_shootout=True`` standings rule) a real separate
shootout-simulation model; under "retro" an undecided 3-on-3 period stands as a legitimate tie.
Playoffs play full 5-on-5 sudden death instead, repeated until decided, never a shootout. The
practical consequence: the engine itself now ALWAYS returns a decisive ``winner`` for a
``has_shootout=True`` game (``result.winner is not None``) -- there is no longer anything for a
season-level placeholder to reconcile on that path, so ``_placeholder_tiebreak_winner`` and its
call site were REMOVED here (not left disabled/unused -- DEVPLAN.md's explicit instruction: don't
leave two competing tie-resolution mechanisms coexisting once the engine makes the season-level
one obsolete).

``_apply_result()``'s remaining job on this front is much simpler than before: standings math
(Step 1.8) is still rule-parameterized (``"retro"`` legally allows a tie via ``rule["tie"]``;
``"standard"``/``"three_two_one_zero"`` have no tie point value and raise via
``points_for_game()`` if ever handed one), but since the engine no longer PRODUCES an unresolved
tie under a ``has_shootout=True`` rule, this function simply records whatever the engine already
decided (score, ``went_ot``, ``went_so``) with no massaging.

Defensive fallback, not a second competing mechanism (read this before assuming a gap): it is
*theoretically* possible for ``_apply_result()`` to be called directly (as several tests in
``tests/test_season.py`` do, by hand-constructing a ``GameResult`` with ``winner=None``) or for a
future bug to somehow produce an unresolved tie under a ``has_shootout=True`` rule despite the
engine's own invariant. Rather than silently mis-record such a game (which would corrupt
``points_for_game()``'s assumptions and crash standings()), ``_apply_result()`` still raises a
loud ``AssertionError`` if it ever sees ``result.winner is None`` under a ``has_shootout=True``
rule -- a defensive integrity check, not a resurrected tiebreak mechanism (it manufactures
nothing; it just refuses to silently record an illegal game state). Under normal operation
(any game that actually went through ``sim/engine.py``'s real OT/shootout resolution) this
assertion can never fire.

Invariant this guarantees: every played ``Game`` under a ``has_shootout=True`` rule always has a
decisive ``winner`` by the time ``points_for_game()``/``standings()`` are called on it (now
guaranteed by the ENGINE, not by this module), so a full 82-game/32-team season never raises
mid-run regardless of the active standings rule.

Playoff games (DEVPLAN.md Step 2.6): ``_apply_result()`` takes an ``is_playoff`` flag (default
``False``, a strict additive extension for every existing regular-season call site). A playoff
game's stat lines accumulate into ``Player.playoffs`` instead of ``Player.season`` (mirrors
HoopR's own season-vs-playoffs stat-line split) and never touches ``Team``'s regular-season
win/loss/ot_loss counters or standings-relevant bookkeeping -- series win/loss is tracked
separately by ``sim/playoffs.py``'s bracket state, not ``Team.record_result()``.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pucksim import config
from pucksim.models.league import Game, Phase
from pucksim.models.player import Injury
from pucksim.models.stats import GoalieStatLine, SkaterStatLine
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
# Result application (DEVPLAN.md Step 2.6 removed the MVP-era placeholder tiebreak that used to
# live here -- see module docstring's "Tie-reconciliation" section for the full history/why).
# ---------------------------------------------------------------------------
def _apply_result(world: World, game: Game, result: GameResult, *, is_playoff: bool = False) -> None:
    """Apply a played game's ``GameResult`` to ``game``, both teams' records, and every involved
    player's stat line. Records exactly what the engine decided (score, ``went_ot``, ``went_so``)
    -- Step 2.6 made the engine itself always resolve a ``has_shootout=True`` game decisively
    (real 3-on-3 OT -> real shootout simulation, see ``sim/engine.py``), so there is no longer
    anything for this function to manufacture; see the module docstring's "defensive fallback"
    paragraph for why an ``AssertionError`` guard remains here instead of silent trust.

    ``is_playoff`` (DEVPLAN.md Step 2.6, default ``False`` -- additive for every existing
    regular-season call site): routes player stat-line accumulation into ``Player.playoffs``
    instead of ``Player.season``, and skips ``Team.record_result()`` entirely (playoff series
    win/loss is tracked by ``sim/playoffs.py``'s bracket state, not the regular-season
    win/loss/ot_loss counters -- crediting a playoff result into those would corrupt regular-
    season standings/record-reconciliation invariants elsewhere in this codebase).
    """
    rule_table = config.STANDINGS_RULES[world.standings_rule]
    unresolved_tie = result.winner is None

    if unresolved_tie and rule_table["has_shootout"]:
        # See module docstring's "defensive fallback, not a second competing mechanism"
        # paragraph -- this should be unreachable for any game that actually went through
        # sim/engine.py's real OT/shootout resolution. Raising loudly here (rather than silently
        # manufacturing a winner, which is exactly the now-removed placeholder's job) surfaces a
        # real bug immediately instead of letting a malformed Game reach points_for_game(), which
        # would raise its own less-informative ValueError deeper in standings math.
        raise AssertionError(
            f"_apply_result got an unresolved tie (gid={game.gid}) under a has_shootout=True "
            f"rule ({world.standings_rule!r}) -- sim/engine.py's real OT/shootout resolution "
            "should never produce this; this is a defensive integrity check, not a resurrected "
            "tiebreak mechanism (see season.py's module docstring)."
        )
    # else: either a decisive result, or a legitimate "retro" tie (went_ot preserved exactly as
    # the engine returned it -- see league.py's Game.is_tie docstring for why went_ot=True is the
    # factually correct record for a drawn retro game, not a wrinkle to paper over).

    game.home_score = result.home_score
    game.away_score = result.away_score
    game.played = True
    game.is_playoff = is_playoff
    game.went_ot = result.went_ot
    game.went_so = result.went_so

    home_team = world.team(game.home)
    away_team = world.team(game.away)

    if is_playoff:
        # Playoff series win/loss bookkeeping belongs to sim/playoffs.py's bracket state, not
        # Team's regular-season record counters -- see this function's docstring.
        pass
    elif game.is_tie:
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
        went_ot, went_so = result.went_ot, result.went_so
        if home_won:
            home_team.record_result("win", game.home_score, game.away_score)
            away_team.record_result("ot_loss" if went_ot or went_so else "loss",
                                    game.away_score, game.home_score)
        else:
            away_team.record_result("win", game.away_score, game.home_score)
            home_team.record_result("ot_loss" if went_ot or went_so else "loss",
                                    game.home_score, game.away_score)

    # Accumulate every player's game stat line into their season-long or playoffs StatLine
    # (DEVPLAN.md Step 2.6: is_playoff routes into Player.playoffs instead of Player.season,
    # mirroring HoopR's own season-vs-playoffs stat-line split).
    for pid, line in result.skater_box.items():
        player = world.players.get(pid)
        if player is None:
            continue
        target = player.playoffs if is_playoff else player.season
        if isinstance(target, SkaterStatLine):
            target.add(line)
    for pid, line in result.goalie_box.items():
        player = world.players.get(pid)
        if player is None:
            continue
        target = player.playoffs if is_playoff else player.season
        if isinstance(target, GoalieStatLine):
            target.add(line)

    # Apply in-game injuries (DEVPLAN.md Step 2.3) -- only UPGRADE an existing injury, never
    # shorten one, mirroring HoopR's own "games > player.injury.games_remaining" comparison: a
    # player already out for a longer-remaining injury shouldn't have that clock reset by a
    # lesser knock (this only matters in the rare case a player who's somehow still marked
    # injured suffers a second in-game injury -- shouldn't happen given engine.py's
    # unavailable-filtering, but a defensive comparison here costs nothing).
    for pid, games, desc, severity in result.injuries:
        player = world.players.get(pid)
        if player is None:
            continue
        if player.injury is None or games > player.injury.games_remaining:
            player.injury = Injury(desc, games, severity)


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


def sim_one(world: World, game: Game, *, is_playoff: bool = False) -> GameResult:
    """Simulate and apply a single scheduled game.

    Consumes ``sim/goalies.py``'s rest-based rotation (DEVPLAN.md Step 2.2): before
    constructing the game, decides each team's actual starting goalie for TODAY (which may be
    the backup, per ``choose_starting_goalie``'s tendency model) via this module's
    process-local ``GoalieRestState`` tracker (see ``_rest_state_for``), and passes that choice
    into ``simulate_game`` as an explicit override rather than letting ``GameSim`` silently fall
    back to ``Team.goalie_starter`` every time.

    ``is_playoff`` (DEVPLAN.md Step 2.6, default ``False``): passes through to ``simulate_game``
    (real 5-on-5 sudden-death OT + the playoff officiating/discipline mode's penalty multiplier)
    and ``_apply_result`` (playoff stat-line/record routing -- see that function's docstring).
    ``sim/playoffs.py`` is the caller that passes ``is_playoff=True``; every regular-season call
    site (``advance_one_day`` below) is unaffected by this addition.
    """
    rest_state = _rest_state_for(world)
    home_goalie_id = _choose_and_record_starter(world, game.home, rest_state, game.day)
    away_goalie_id = _choose_and_record_starter(world, game.away, rest_state, game.day)

    result = simulate_game(world, game.home, game.away,
                           home_goalie_id=home_goalie_id, away_goalie_id=away_goalie_id,
                           is_playoff=is_playoff)
    _apply_result(world, game, result, is_playoff=is_playoff)
    return result


# ---------------------------------------------------------------------------
# Injury healing (DEVPLAN.md Step 2.3)
# ---------------------------------------------------------------------------
def _heal_injuries(world: World) -> None:
    """Tick every active injury's ``games_remaining`` down by one calendar day's worth of
    recovery, clearing it once healed. Near-verbatim port of HoopR's ``_heal_injuries`` (see
    that function in hoopsim/sim/season.py) -- one day of recovery per call, so this must be
    called exactly once per day advanced (see ``advance_one_day``, its sole caller), same as
    HoopR's own per-day cadence.
    """
    for player in world.players.values():
        if player.injury is not None:
            player.injury.games_remaining -= 1
            if player.injury.games_remaining <= 0:
                player.injury = None


# ---------------------------------------------------------------------------
# Day advancement
# ---------------------------------------------------------------------------
def advance_one_day(world: World) -> List[Game]:
    """Simulate every unplayed game scheduled on ``world.day``, heal one day's worth of injury
    recovery, then advance the day counter.

    Returns the list of ``Game`` objects played today. ``_heal_injuries`` (DEVPLAN.md Step 2.3)
    runs AFTER the day's games are simmed -- exactly the hook point this module's docstring
    previously flagged as the intended spot for it -- so a player injured in today's own game
    doesn't have his very first day of absence double-counted (a fresh injury only starts
    healing from the NEXT day's tick onward, not the day it happened).

    DEVPLAN.md Step 2.9b-ii: populate ``world.game_results`` with box-score data for each
    played game so ``GET /season/games/{gid}/boxscore`` can retrieve them later.
    """
    todays = [g for g in world.schedule if g.day == world.day and not g.played]
    for game in todays:
        result = sim_one(world, game)
        # Persist box score for later retrieval (Step 2.9b-ii)
        world.game_results[game.gid] = {
            'home_score': result.home_score,
            'away_score': result.away_score,
            'went_ot': result.went_ot,
            'went_so': result.went_so,
            'skater_box': {pid: line.to_dict() for pid, line in result.skater_box.items()},
            'goalie_box': {pid: line.to_dict() for pid, line in result.goalie_box.items()},
        }
    _heal_injuries(world)
    world.day += 1
    return todays


def regular_season_complete(world: World) -> bool:
    """True once every scheduled game has been played."""
    return all(g.played for g in world.schedule)


def next_game_for_team(world: World, tid: int) -> Optional[Game]:
    """Return the next unplayed game involving ``tid``, ordered by (day, gid).

    Returns ``None`` if the team has no remaining unplayed games.
    """
    candidates = [g for g in world.schedule if not g.played and g.involves(tid)]
    return min(candidates, key=lambda g: (g.day, g.gid)) if candidates else None


def start_season(world: World) -> None:
    """Reset records/stats and build a fresh regular-season schedule."""
    world.schedule = generate_schedule(world)
    world.phase = Phase.REGULAR_SEASON
    world.day = 0

    for team in world.teams.values():
        team.reset_record()

    for player in world.players.values():
        player.season = GoalieStatLine() if player.is_goalie else SkaterStatLine()
