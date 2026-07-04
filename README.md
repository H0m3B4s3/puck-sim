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

The FastAPI + React web app (DEVPLAN.md Steps 2.9/2.10) is also implemented and merged: session/
career management, roster and line/pair/tactics editing, schedule/standings/sim-day controls, box
scores, and cap/trades/free-agency/draft/awards screens, all wired to a hockey-rink-themed UI
(light "Ice" / dark "Arena" toggle).

654 backend tests pass; a full 82-game season plus a complete playoff bracket runs cleanly
end-to-end, both headlessly and through the web app. See [DEVPLAN.md](DEVPLAN.md) for the full
step-by-step plan and status notes, including a handful of known non-blocking loose ends (search
that file for "Known" and "not yet wired").

## Run the web app

Requires the `web` extra (already included if you ran `pip install -e ".[dev,web]"` above) plus
Node.js/npm for the frontend.

**Quickest path:** `./dev.sh` starts both the backend and frontend together in one terminal
(auto-activates `.venv` if present, installs frontend deps on first run) — press Ctrl+C to stop
both. Equivalent to the two-terminal steps below, done for you.

```bash
# Terminal 1 — backend (FastAPI, default http://127.0.0.1:8000)
pucksim-web
# for auto-reload on code changes during development, use uvicorn directly instead:
# python -m uvicorn pucksim.web.app:app --reload

# Terminal 2 — frontend (Vite dev server, default http://127.0.0.1:5173)
cd frontend
npm install    # first run only
npm run dev
```

Open the frontend URL printed by Vite (usually `http://127.0.0.1:5173`) in a browser. The
frontend talks to the backend at `http://127.0.0.1:8000` by default; point it elsewhere by setting
`VITE_API_BASE_URL` (e.g. `VITE_API_BASE_URL=http://127.0.0.1:9000 npm run dev`) if you're running
the backend on a different port.

Note: the frontend and backend must be reached via the **same hostname** (both `127.0.0.1` or
both `localhost`, not one of each) -- the session cookie is `samesite="lax"`, and browsers treat
`localhost`/`127.0.0.1` as different sites, which silently drops the cookie on cross-site fetches
and breaks the app after `POST /career/new`.

To build a static production bundle instead of running the dev server: `cd frontend && npm run
build` (output in `frontend/dist/`, served by any static file server — the FastAPI backend does
not serve it itself).

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
