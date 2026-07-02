#!/usr/bin/env python3
"""testkit/run_season.py -- headless N-game/N-season CLI harness (DEVPLAN.md Step 1.14).

Standalone, directly-executable script: ``python testkit/run_season.py [options]``. Not a
pytest suite -- this is the internal "does the sim actually hold together at real scale" tool
DESIGN.md calls out ("A thin CLI/script harness will exist purely for internal testing"). There is
no HoopR precedent for this file (HoopR has no CLI harness); it's loosely modeled on how
``tests/test_season.py`` drives a season loop programmatically (``build_world`` ->
``start_season`` -> repeated ``advance_one_day`` until ``regular_season_complete``).

Running it directly (``python testkit/run_season.py``, not ``python -m testkit.run_season``)
means this file's own directory, not the project root, is what Python puts on ``sys.path[0]``.
That's fine as long as ``pucksim`` is importable some other way -- and it is: ``pucksim`` is
``pip install -e``'d into the active venv (verified directly against this project's
``.venv/lib/python3.9/site-packages``, which carries an editable-install finder that makes
``import pucksim`` work from *any* current working directory, independent of ``sys.path[0]``).
The ``sys.path`` insert below is a defensive fallback only, for the case this script gets copied
somewhere or run with a non-activated/non-editable interpreter -- it costs nothing when the venv
is already set up correctly.

--seasons N -- what this actually means in MVP scope (read this before assuming more):
------------------------------------------------------------------------------------------
PuckSim's MVP has no offseason/draft/free-agency/player-development system yet -- all of that is
v1/Step 2.x scope (DEVPLAN.md Phase 2). Concretely, that means in this script, "simulate N
seasons" does NOT mean a realistic multi-year franchise sim: nobody ages, retires, gets drafted,
signs as a free agent, or changes teams between the N seasons this script runs. What actually
happens for each season after the first is: call ``start_season(world)`` again, which (per
``sim/season.py``) resets every team's win/loss/OT-loss record to 0/0/0 and gives every player a
brand new zeroed season ``StatLine``, then generates a fresh schedule -- and re-run the exact same
32 teams/rosters through another full schedule. ``world.season_year`` is incremented by this
script between seasons (``start_season()`` itself does not touch it) purely as a cosmetic label in
the printed summary header -- it has zero effect on player aging or roster composition, since
nothing in MVP reads ``season_year`` to drive development. Treat multi-season output here as "N
independent replays of the same league, with fresh season-stat/record slates each time," not
franchise progression. Real year-over-year continuity (aging, retirement, draft classes, re-signed
contracts) arrives once v1's offseason systems (Step 2.7) exist.

Also omitted, deliberately: DEVPLAN.md's done-criteria phrase mentions a "notable injuries"
summary section. No injury system exists yet in this codebase (Player.injury / Injury is a data
container only -- see player.py's docstring: "injury-generation logic lands in Step 2.3"), so
there is nothing to report and this script does not invent injury data. Add an injuries section
here once Step 2.3 lands.

Determinism: the whole point of seeding ``build_world(seed=...)`` is that ``python
testkit/run_season.py --seed 1 --seasons 3`` run twice produces byte-identical stdout both times
(explicit MVP done-criteria) -- every draw the sim makes (rosters, game sim, the has_shootout
placeholder tiebreak) comes from the single seeded ``World.rng`` stream, and this script itself
introduces no additional nondeterminism into what gets printed (the only excluded value is the
wall-clock timing line, which is intentionally the last line printed and is not part of the
"identical stdout" contract for the standings/scoring content above it -- see the note at the
bottom of ``main()``).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Dict, List

# Defensive fallback only -- see module docstring. Ensures the project root (this script's
# parent directory) is importable even if `pucksim` somehow isn't already on sys.path (e.g. venv
# not activated, or the editable install metadata is missing for some reason).
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from pucksim import config  # noqa: E402
from pucksim.gen.leaguegen import build_world  # noqa: E402
from pucksim.models.league import conference_standings  # noqa: E402
from pucksim.models.stats import GoalieStatLine, SkaterStatLine  # noqa: E402
from pucksim.models.team import Team  # noqa: E402
from pucksim.models.world import World  # noqa: E402
from pucksim.save.serialize import save_world  # noqa: E402
from pucksim.sim import playoffs as PO  # noqa: E402
from pucksim.sim.season import (  # noqa: E402
    advance_one_day,
    generate_schedule,
    regular_season_complete,
    start_season,
)

# Minimum games played before a goalie is eligible for the "top goalies by save_pct" leaderboard --
# without this, a goalie with a single mop-up appearance and a lucky 100% save_pct would dominate a
# ranking that's supposed to highlight real starters. Provisional/tunable: roughly 10% of a full
# 82-game season is a reasonable "meaningfully sampled" bar; scaled down for short smoke-test runs
# via --games-per-season so this doesn't silently produce an empty goalie leaderboard in tests.
_MIN_GOALIE_GP_FRACTION = 0.10
_MIN_GOALIE_GP_FLOOR = 3

_TOP_SCORERS_COUNT = 10
_TOP_GOALIES_COUNT = 5


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_season.py",
        description=(
            "Headless PuckSim season runner (MVP CLI harness, DEVPLAN.md Step 1.14). Builds a "
            "32-team league and simulates one or more full regular seasons with no UI, printing a "
            "standings/top-scorers/top-goalies summary after each season. "
            "\n\n"
            "IMPORTANT MVP-scope note on --seasons: PuckSim has no offseason/draft/free-agency/"
            "development system yet, so running --seasons N does NOT model a real multi-year "
            "franchise (no aging, no retirement, no roster turnover). It re-runs the SAME 32 "
            "rosters through N independent fresh schedules, resetting records/season stats between "
            "each one via start_season(). Real year-over-year continuity arrives once v1's "
            "offseason systems (DEVPLAN.md Step 2.7) exist."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Seed for the world's RNG (default: random/unseeded). Set this for reproducible runs.",
    )
    parser.add_argument(
        "--seasons", type=int, default=1,
        help="Number of consecutive seasons to simulate (see MVP-scope note above). Default: 1.",
    )
    parser.add_argument(
        "--games-per-season", type=int, default=config.SEASON_GAMES,
        help=(
            f"Target games per team per season (default: config.SEASON_GAMES={config.SEASON_GAMES}). "
            "Lower this for a fast smoke-test run."
        ),
    )
    parser.add_argument(
        "--save-path", type=str, default=None,
        help="If given, save the final world state (after all seasons complete) to this file path.",
    )
    parser.add_argument(
        "--standings-rule",
        choices=sorted(config.STANDINGS_RULES.keys()),
        default=config.DEFAULT_STANDINGS_RULE,
        help=f"Standings points rule to use (default: {config.DEFAULT_STANDINGS_RULE!r}).",
    )
    parser.add_argument(
        "--playoff-discipline",
        choices=list(config.PLAYOFF_DISCIPLINE_MODE_CHOICES),
        default=config.DEFAULT_PLAYOFF_DISCIPLINE_MODE,
        help=(
            "Playoff officiating/discipline mode (DEVPLAN.md Step 2.6): 'realistic' (default) "
            "calls meaningfully fewer penalties in playoff games; 'regular_season' uses identical "
            f"penalty rates to the regular season. Only matters if --playoffs is given "
            f"(default: {config.DEFAULT_PLAYOFF_DISCIPLINE_MODE!r})."
        ),
    )
    parser.add_argument(
        "--playoffs",
        action="store_true",
        help=(
            "After each regular season completes, also simulate the full playoff bracket "
            "(DEVPLAN.md Step 2.6: conference seeding, best-of-7 series, real 5-on-5 sudden-"
            "death OT, no shootout) to a champion and print a bracket summary."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Season-per-run orchestration
# ---------------------------------------------------------------------------
def _start_season_with_override(world: World, games_per_season: int) -> None:
    """Run the equivalent of ``start_season(world)`` but honoring a custom target-games-per-team.

    ``sim.season.start_season()`` does not expose a games-per-season override (its signature is
    ``start_season(world) -> None``, hardcoding ``generate_schedule(world)``'s default
    ``target_games=config.SEASON_GAMES``) -- confirmed by reading season.py directly rather than
    guessing. season.py is out of bounds for this step (constraints), so rather than edit it, this
    inlines the exact few lines ``start_season()`` itself performs, substituting a
    ``generate_schedule(world, target_games=games_per_season)`` call. Kept in lock-step with
    ``sim/season.py::start_season`` -- if that function's reset logic ever changes, this should be
    updated to match.
    """
    if games_per_season == config.SEASON_GAMES:
        start_season(world)
        return

    from pucksim.models.league import Phase

    world.schedule = generate_schedule(world, target_games=games_per_season)
    world.phase = Phase.REGULAR_SEASON
    world.day = 0

    for team in world.teams.values():
        team.reset_record()

    for player in world.players.values():
        player.season = GoalieStatLine() if player.is_goalie else SkaterStatLine()


def _run_one_season(world: World, games_per_season: int) -> None:
    """Run a single season to completion (schedule build through last game played)."""
    _start_season_with_override(world, games_per_season)
    while not regular_season_complete(world):
        advance_one_day(world)


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------
def _print_standings(world: World) -> None:
    print("Standings")
    print("=========")
    grouped = conference_standings(world.team_list(), world.schedule, world.standings_rule)
    for conference in sorted(grouped.keys()):
        print(f"\n-- {conference} Conference --")
        header = f"{'Team':<28}{'Record':<10}{'Pts':>5}"
        print(header)
        print("-" * len(header))
        for team in grouped[conference]:
            pts = _team_points(world, team)
            print(f"{team.name:<28}{team.record_str:<10}{pts:>5}")


def _team_points(world: World, team: Team) -> int:
    """Total standings points for ``team`` under the active rule.

    ``league.standings()``'s accumulator is a private local (``_build_accumulators``/
    ``_Accumulator``), not a public API -- rather than reach into that internal, points are
    recomputed here the same publicly-documented way ``standings()`` itself computes them:
    summing ``points_for_game()`` over every played game the team is involved in. This is the
    cleanly-available public surface (``pucksim.models.league.points_for_game``), not a private
    internal.
    """
    from pucksim.models.league import points_for_game

    return sum(
        points_for_game(world.standings_rule, team.tid, g)
        for g in world.schedule
        if g.played and g.involves(team.tid)
    )


def _print_top_scorers(world: World) -> None:
    skaters = [p for p in world.players.values() if not p.is_goalie]
    skaters.sort(key=lambda p: (p.season.points, p.season.g), reverse=True)
    top = skaters[:_TOP_SCORERS_COUNT]

    print(f"\nTop {_TOP_SCORERS_COUNT} Scorers")
    print("=" * len(f"Top {_TOP_SCORERS_COUNT} Scorers"))
    header = f"{'Name':<24}{'Team':<10}{'Pos':<5}{'G':>4}{'A':>4}{'P':>5}"
    print(header)
    print("-" * len(header))
    for player in top:
        team_abbrev = world.team(player.team_id).abbrev if player.team_id is not None else "FA"
        print(
            f"{player.name:<24}{team_abbrev:<10}{player.position:<5}"
            f"{player.season.g:>4}{player.season.a:>4}{player.season.points:>5}"
        )


def _print_top_goalies(world: World, games_per_season: int) -> None:
    min_gp = max(_MIN_GOALIE_GP_FLOOR, int(round(games_per_season * _MIN_GOALIE_GP_FRACTION)))

    goalies = [
        p for p in world.players.values()
        if p.is_goalie and p.season.gp >= min_gp
    ]
    goalies.sort(key=lambda p: (p.season.save_pct, -p.season.gaa), reverse=True)
    top = goalies[:_TOP_GOALIES_COUNT]

    print(f"\nTop {_TOP_GOALIES_COUNT} Goalies (min {min_gp} GP)")
    print("=" * len(f"Top {_TOP_GOALIES_COUNT} Goalies (min {min_gp} GP)"))
    header = f"{'Name':<24}{'Team':<10}{'GP':>4}{'SV%':>7}{'GAA':>7}{'W':>4}"
    print(header)
    print("-" * len(header))
    for goalie in top:
        team_abbrev = world.team(goalie.team_id).abbrev if goalie.team_id is not None else "FA"
        print(
            f"{goalie.name:<24}{team_abbrev:<10}{goalie.season.gp:>4}"
            f"{goalie.season.save_pct:>7.3f}{goalie.season.gaa:>7.2f}{goalie.season.wins:>4}"
        )
    if not top:
        print("(no goalie met the minimum games-played threshold this season)")


def _print_season_summary(world: World, season_num: int, games_per_season: int) -> None:
    print(f"\n{'#' * 60}")
    print(f"Season {season_num} complete -- season_year={world.season_year}, "
          f"standings_rule={world.standings_rule!r}, games_per_team={games_per_season}")
    print(f"{'#' * 60}\n")
    _print_standings(world)
    _print_top_scorers(world)
    _print_top_goalies(world, games_per_season)


# ---------------------------------------------------------------------------
# Playoff bracket summary (DEVPLAN.md Step 2.6)
# ---------------------------------------------------------------------------
def _print_playoff_bracket(world: World) -> None:
    """Print every series' final result, grouped by round, then the champion. Only meaningful
    after ``PO.run_full_playoffs(world)`` has completed -- called from ``main()`` right after
    that call."""
    print(f"\nPlayoffs (playoff_discipline_mode={world.playoff_discipline_mode!r})")
    print("=========")
    if not world.bracket:
        print("(no bracket -- start_playoffs was never called)")
        return

    by_round: Dict[str, List[dict]] = {}
    for s in world.bracket["all_series"]:
        by_round.setdefault(s["round"], []).append(s)

    for rnd in ("R1", "R2", "CF", "Finals"):
        series_list = by_round.get(rnd)
        if not series_list:
            continue
        print(f"\n-- {PO.ROUND_LABELS.get(rnd, rnd)} --")
        for s in series_list:
            winner_name = world.teams[s["winner"]].abbrev if s["winner"] is not None else "?"
            print(f"  {PO.series_status(world, s)}  (winner: {winner_name})")

    champ_tid = PO.champion(world)
    if champ_tid is not None:
        print(f"\nChampion: {world.teams[champ_tid].name}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main(argv: List[str] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    start_time = time.perf_counter()

    world = build_world(seed=args.seed)
    world.standings_rule = args.standings_rule
    world.playoff_discipline_mode = args.playoff_discipline

    for season_num in range(1, args.seasons + 1):
        if season_num > 1:
            # No offseason/draft/development system exists yet (see module docstring) -- bumping
            # season_year is purely a cosmetic label for the printed summary header, not a driver
            # of any aging/roster-turnover logic.
            world.season_year += 1
        _run_one_season(world, args.games_per_season)
        _print_season_summary(world, season_num, args.games_per_season)

        if args.playoffs:
            # DEVPLAN.md Step 2.6: real playoff bracket simulation, chained directly onto this
            # season's just-finished regular-season standings. No offseason/draft/FA system
            # exists yet (same MVP-scope caveat as --seasons above), so a subsequent season (if
            # any) still just re-runs a fresh schedule for the same 32 rosters -- the playoff
            # bracket itself does not feed back into roster composition for the next season.
            PO.start_playoffs(world)
            PO.run_full_playoffs(world)
            _print_playoff_bracket(world)

    if args.save_path:
        save_world(world, args.save_path)
        print(f"\nSaved final world state to {args.save_path}")

    elapsed = time.perf_counter() - start_time
    print(f"\nTotal elapsed wall-clock time: {elapsed:.2f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
