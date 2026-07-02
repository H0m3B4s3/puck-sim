"""Playoff bracket: seeding, best-of-7 series simulation, and round advancement (DEVPLAN.md
Step 2.6).

Bracket state is stored on ``world.bracket`` as a JSON-native ``dict`` so it serializes with the
save (see ``models/world.py``'s docstring) -- ports the *shape* of HoopR's ``hoopsim/sim/
playoffs.py`` (257 lines: bracket-as-dict-on-world, best-of-7 series, round advancement), NOT a
verbatim copy: this is a different sport with a different bracket size and no play-in mechanic.

Seeding (DEVPLAN.md's explicit "not specified, low-risk default" open item): conference-based
top-N, matching real NHL (each conference's top ``config.PLAYOFF_TEAMS_PER_CONF`` teams by
regular-season standings, 1-through-8, no wild-card/division realignment nuance) and mirroring
HoopR's own top-N-by-conference pattern. Unlike HoopR (which has a 6-seed-auto + 4-team play-in
for seeds 7/8, an NBA-specific mechanic with no NHL analog), PuckSim seeds straight 1-8 in each
conference with no play-in round -- real NHL playoffs have never used a play-in tournament, so
porting HoopR's play-in machinery here would be inventing scope DEVPLAN.md never asked for.
Seeding reads ``models/league.py``'s existing ``conference_standings()`` (Step 1.8/1.9's
standings math) rather than inventing a second ranking mechanism, per DEVPLAN.md's explicit
instruction.

Bracket shape: 1v8 / 4v5 / 3v6 / 2v7 within each conference (the standard "avoid a rematch of the
top 2 seeds until the final round" seeding pattern), same pairing shape HoopR uses for its own
post-play-in round of 8. Conference champions meet in the Finals à la real NHL (Stanley Cup
Final is the two conference champions, not a single league-wide bracket collapsed earlier).

Playoff OT/shootout resolution and the playoff officiating/discipline mode itself live in
``sim/engine.py`` (``GameSim(..., is_playoff=True)``) and ``sim/season.py`` (``sim_one(...,
is_playoff=True)``) -- this module's only job is bracket/series bookkeeping around calling those,
exactly matching DESIGN.md's "web calls the same engine functions as the CLI" principle (there is
no separate playoff-only simulation path; a playoff game is simulated by the exact same
``sim_one``/``simulate_game`` machinery as a regular-season game, just with ``is_playoff=True``
threaded through).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pucksim import config
from pucksim.models.league import Game, Phase, conference_standings
from pucksim.models.world import World
from pucksim.sim.boxscore import GameResult
from pucksim.sim.season import sim_one

BEST_OF = 7
WINS_NEEDED = BEST_OF // 2 + 1            # 4
# 2-2-1-1-1 format: the higher seed hosts games 1, 2, 5, 7 of a best-of-7.
HIGH_SEED_HOME_GAMES = {1, 2, 5, 7}

ROUND_LABELS = {
    "R1": "First Round", "R2": "Conference Semifinals", "CF": "Conference Finals",
    "Finals": "Stanley Cup Final", "done": "Complete",
}
NEXT_ROUND = {"R1": "R2", "R2": "CF", "CF": "Finals", "Finals": "done"}


def _new_series(hi: int, lo: int, conf: str, rnd: str) -> dict:
    return {"sid": f"{rnd}-{hi}-{lo}", "conf": conf, "round": rnd,
            "hi": hi, "lo": lo, "hi_w": 0, "lo_w": 0, "winner": None, "games": []}


# ---------------------------------------------------------------------------
# Start of playoffs: seeding
# ---------------------------------------------------------------------------
def start_playoffs(world: World) -> None:
    """Seed the bracket from the just-finished regular season's standings and build the first
    round's series. Conference-based top-N (see module docstring); a conference with fewer than
    ``config.PLAYOFF_TEAMS_PER_CONF`` teams (a short/test league) simply takes however many it
    has -- never crashes on an undersized league, matching this codebase's "reasonable simple
    model, don't over-engineer edge cases" framing elsewhere (e.g.
    ``special_teams.on_ice_group_for_state``'s undersized-unit fallback).
    """
    grouped = conference_standings(world.team_list(), world.schedule, world.standings_rule)
    seeds: Dict[int, int] = {}
    series: List[dict] = []

    for conf in config.CONFERENCES:
        ordered = grouped.get(conf, [])
        top_n = ordered[: config.PLAYOFF_TEAMS_PER_CONF]
        for i, team in enumerate(top_n, start=1):
            seeds[team.tid] = i

        s = [t.tid for t in top_n]
        if len(s) == config.PLAYOFF_TEAMS_PER_CONF:
            # Standard 1v8 / 4v5 / 3v6 / 2v7 bracket (index 0 == seed 1 .. index 7 == seed 8).
            pairings = ((0, 7), (3, 4), (2, 5), (1, 6))
        else:
            # Undersized conference (short/test league) -- pair top-vs-bottom by seed order as a
            # reasonable fallback rather than hardcoding the 8-team bracket shape.
            pairings = [(i, len(s) - 1 - i) for i in range(len(s) // 2)]

        for hi_idx, lo_idx in pairings:
            if hi_idx >= len(s) or lo_idx >= len(s) or hi_idx == lo_idx:
                continue
            series.append(_new_series(s[hi_idx], s[lo_idx], conf, "R1"))

    world.bracket = {
        "round": "R1", "series": series, "all_series": list(series),
        "seeds": {str(k): v for k, v in seeds.items()},
        "champion": None,
    }
    world.phase = Phase.PLAYOFFS


# ---------------------------------------------------------------------------
# Slate advancement
# ---------------------------------------------------------------------------
def active_series(world: World) -> List[dict]:
    if not world.bracket:
        return []
    return [s for s in world.bracket["series"] if s["winner"] is None]


def series_status(world: World, s: dict) -> str:
    hi_abbr = world.teams[s["hi"]].abbrev
    lo_abbr = world.teams[s["lo"]].abbrev
    return f"{hi_abbr} {s['hi_w']}-{s['lo_w']} {lo_abbr}"


def _series_next_home_away(s: dict) -> Tuple[int, int]:
    game_no = s["hi_w"] + s["lo_w"] + 1
    if game_no in HIGH_SEED_HOME_GAMES:
        return s["hi"], s["lo"]
    return s["lo"], s["hi"]


def _record_series_game(s: dict, home: int, away: int, result: GameResult) -> None:
    """Tally a finished series game: bump the winner's win count and close the series out once
    either side reaches ``WINS_NEEDED`` (4). ``result.winner`` is guaranteed non-None for a
    playoff game (real 5-on-5 sudden death continues until decided -- see
    ``sim/engine.py``'s ``coach_session`` -- a playoff series can never advance on a tied game)."""
    winner = home if result.home_score > result.away_score else away
    if winner == s["hi"]:
        s["hi_w"] += 1
    else:
        s["lo_w"] += 1
    if s["hi_w"] >= WINS_NEEDED:
        s["winner"] = s["hi"]
    elif s["lo_w"] >= WINS_NEEDED:
        s["winner"] = s["lo"]


def advance_playoff_slate(world: World) -> List[Tuple[dict, GameResult]]:
    """Play the next game of every currently-undecided series in the active round (a "slate" --
    one game per still-live series), then build the next round if every series in the current
    round just finished. Headless-simulation entry point (mirrors HoopR's
    ``advance_playoff_slate`` shape, minus the ``watch_user``/live-coaching parameters, which
    have no consumer yet in this codebase -- see ``sim/engine.py``'s module docstring on the
    live-coaching seam existing but not being wired to anything yet).

    Returns the list of ``(series_dict, GameResult)`` pairs played this slate.
    """
    results: List[Tuple[dict, GameResult]] = []
    for s in active_series(world):
        home, away = _series_next_home_away(s)
        game = Game(gid=world.new_gid(), day=world.day, home=home, away=away,
                    is_playoff=True, series_id=s["sid"])
        world.schedule.append(game)
        result = sim_one(world, game, is_playoff=True)
        s["games"].append(game.gid)
        _record_series_game(s, home, away, result)
        results.append((s, result))

    world.day += 1
    if not active_series(world):
        _build_next_round(world)
    return results


def play_series_to_completion(world: World, s: dict) -> List[GameResult]:
    """Play out a single series (one call site's worth of games) until it has a winner --
    convenience helper for a headless full-bracket run (``testkit/run_season.py``'s playoff
    extension) that doesn't need slate-by-slate control. Does NOT advance any OTHER series in
    the bracket and does NOT build the next round -- callers driving a full bracket should use
    ``advance_playoff_slate`` (which plays every active series together) instead; this exists for
    the narrower case of finishing one already-isolated series."""
    results: List[GameResult] = []
    while s["winner"] is None:
        home, away = _series_next_home_away(s)
        game = Game(gid=world.new_gid(), day=world.day, home=home, away=away,
                    is_playoff=True, series_id=s["sid"])
        world.schedule.append(game)
        result = sim_one(world, game, is_playoff=True)
        s["games"].append(game.gid)
        _record_series_game(s, home, away, result)
        results.append(result)
        world.day += 1
    return results


def _seed(world: World, tid: int) -> int:
    return world.bracket["seeds"].get(str(tid), 99)


def _build_next_round(world: World) -> None:
    """Advance the bracket to the next round once every series in the current round has a
    winner, pairing winners by seed (lower combined seed number hosts more games -- the standard
    "keep the higher remaining seed at home longer" bracket convention) within each conference,
    or -- for the Finals -- pairing the two conference champions directly (real NHL: the Stanley
    Cup Final is always East champion vs. West champion, never a single collapsed league-wide
    bracket). Sets ``world.bracket["champion"]``/advances ``world.phase`` to ``Phase.DRAFT`` once
    the Finals themselves are decided (mirrors the real NHL calendar: the entry draft follows the
    playoffs)."""
    bracket = world.bracket
    current = bracket["round"]
    nxt = NEXT_ROUND[current]
    finished = [s for s in bracket["series"] if s["round"] == current]

    if nxt == "done":
        bracket["champion"] = finished[0]["winner"]
        bracket["round"] = "done"
        bracket["series"] = []
        world.phase = Phase.DRAFT
        return

    new_series: List[dict] = []
    if nxt == "Finals":
        champs = {s["conf"]: s["winner"] for s in finished}
        confs = list(config.CONFERENCES)
        a, b = champs[confs[0]], champs[confs[1]]
        # Home-ice in the Final goes to whichever conference champion carried the better
        # regular-season seed (real NHL uses a full points-based comparison across conferences;
        # this codebase's own per-conference seed number, already computed at bracket-build time,
        # is a reasonable stand-in -- DEVPLAN.md doesn't specify Final home-ice tiebreaking, so
        # this is a low-risk default, same framing as the seeding choice above).
        hi, lo = (a, b) if _seed(world, a) <= _seed(world, b) else (b, a)
        new_series.append(_new_series(hi, lo, "Finals", "Finals"))
    else:
        for conf in config.CONFERENCES:
            conf_series = [s for s in finished if s["conf"] == conf]
            winners = [s["winner"] for s in conf_series]
            for i in range(0, len(winners), 2):
                if i + 1 >= len(winners):
                    continue
                a, b = winners[i], winners[i + 1]
                hi, lo = (a, b) if _seed(world, a) <= _seed(world, b) else (b, a)
                new_series.append(_new_series(hi, lo, conf, nxt))

    bracket["round"] = nxt
    bracket["series"] = new_series
    bracket["all_series"].extend(new_series)


def playoffs_complete(world: World) -> bool:
    return bool(world.bracket) and world.bracket.get("champion") is not None


def champion(world: World) -> Optional[int]:
    return world.bracket.get("champion") if world.bracket else None


def run_full_playoffs(world: World) -> int:
    """Headless convenience: run ``advance_playoff_slate`` until the bracket is fully decided,
    starting from whatever round ``world.bracket`` is currently in (``start_playoffs`` must
    already have been called). Returns the champion team id. Used by
    ``testkit/run_season.py``'s playoff extension and this step's own tests for a full-bracket
    smoke run -- production/web-layer callers driving a live-coached user team would instead use
    ``advance_playoff_slate`` slate-by-slate (this function's loop shape) directly, so a future
    live-coaching consumer can interleave user decisions between slates.
    """
    if world.bracket is None:
        start_playoffs(world)
    guard = 0
    # Defensive iteration cap: a full bracket is at most 4 rounds x up to 7 games each, so this
    # is generous, not a realistic ceiling -- purely a stop condition against an unexpected
    # infinite loop (bracket bookkeeping bug) in a headless script, same framing as
    # config.MAX_PLAYOFF_OT_PERIODS.
    guard_limit = 4 * BEST_OF + 8
    while not playoffs_complete(world) and guard < guard_limit:
        advance_playoff_slate(world)
        guard += 1
    return champion(world)
