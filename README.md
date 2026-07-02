# PuckSim

A text-based, Football-Manager-style NHL franchise simulation — the hockey sibling of [HoopR](https://github.com/), reusing its proven architectural patterns (layered domain model, seedable RNG, JSON saves) while building a hockey-native simulation engine from scratch.

See [DESIGN.md](DESIGN.md) for the full design rationale and [DEVPLAN.md](DEVPLAN.md) for the step-by-step build plan.

## Install

```bash
pip install -e ".[dev,web]"
```

## Run tests

```bash
pytest
```

## Status (2026-07-02)

All of v1's gameplay systems (DEVPLAN.md Steps 2.1–2.8) are implemented and merged: special
teams/strength states, goalies (hot-hand, rest-based rotation, pull-the-goalie), faceoffs
(three-way tie/winger-recovery model) and in-game injuries, salary cap/trades/free agency, the
entry draft and prospect generation, playoffs with real 3-on-3-OT/shootout resolution and a
selectable playoff officiating mode, awards/legacy/momentum/offseason/development (including
goalie season-to-season form variance), and coach line-juggling AI with a PP/PK tactics board.
575 tests pass; a full 82-game season plus a complete playoff bracket runs cleanly end-to-end.

The FastAPI + React web app (Steps 2.9/2.10) has not been started — everything today is exercised
headlessly, via `testkit/run_season.py` or directly against the `pucksim` package. See
[DEVPLAN.md](DEVPLAN.md) for the full step-by-step plan and status notes, including a handful of
known non-blocking loose ends (search that file for "Known" and "not yet wired").

## Run the web app

Not yet available — the FastAPI + React web app is built in Phase 2 (v1) of [DEVPLAN.md](DEVPLAN.md), as a separate future round.

## Headless simulation (dev/test harness)

```bash
# One season, default settings
python testkit/run_season.py --seed 1

# Multiple independent seasons (see the script's own docstring: this replays the same
# rosters N times, it does NOT yet chain through the real offseason/draft/development
# systems between seasons -- those exist in pucksim.systems.offseason but aren't wired
# into this particular script yet)
python testkit/run_season.py --seed 1 --seasons 3

# Full regular season + complete playoff bracket to a champion
python testkit/run_season.py --seed 1 --playoffs

# All standings-rule / playoff-discipline options
python testkit/run_season.py --seed 1 --playoffs --standings-rule three_two_one_zero --playoff-discipline regular_season

python testkit/run_season.py --help   # full option list
```
