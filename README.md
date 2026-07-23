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

## Status (2026-07-22)

All of v1's gameplay systems (DEVPLAN.md Steps 2.1–2.8) are implemented and merged: special
teams/strength states, goalies (hot-hand, rest-based rotation, pull-the-goalie), faceoffs
(three-way tie/winger-recovery model) and in-game injuries, salary cap/trades/free agency, the
entry draft and prospect generation, playoffs with real 3-on-3-OT/shootout resolution and a
selectable playoff officiating mode, awards/legacy/momentum/offseason/development (including
goalie season-to-season form variance), and coach line-juggling AI with a PP/PK tactics board.

The FastAPI + React web app (DEVPLAN.md Steps 2.9/2.10) is also implemented and merged: session/
career management, roster and line/pair/tactics editing, schedule/standings/sim-day controls, box
scores, and cap/trades/free-agency/draft/awards screens, all wired to a hockey-rink-themed UI
(light "Ice" / dark "Arena" toggle). Step 2.11's web-parity round (`docs/PARITY_PLAN.md`) closed
the gaps human testing found — playoffs, offseason, player detail, and a usable trade UI.

Two sim-depth rounds have landed on top of that, both documented in
[docs/SIM_SYNERGY_PLAN.md](docs/SIM_SYNERGY_PLAN.md):

- **Roles, line synergy and defender impact** — every player carries a persisted role; a line's
  role composition (does a creator feed a finisher?) and the on-ice defending group's defensive
  value both shift shot quality. Both are centered so an average line/defense is a no-op, and
  both change *chance quality* rather than any player's rating ceiling.
- **Archetype refresh** — a distinct elite tier modeled on real stars (Crosby/McDavid/Gretzky/
  Ovechkin/Jagr/Bergeron forwards, Orr/Makar/Leetch-Fox/Lidström defensemen), archetype selection
  weighted by target overall so scorers concentrate in the top six and checkers in the bottom
  six, full depth-defenseman vocabulary, and a skew-preserving calibration pass so an archetype's
  signature survives at elite overall instead of being averaged away.

783 backend tests pass; a full 82-game season plus a complete playoff bracket runs cleanly
end-to-end, both headlessly and through the web app. Note the suite takes roughly ten minutes —
several tests sim multiple full seasons back to back. See [DEVPLAN.md](DEVPLAN.md) for the full
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

Open the frontend URL printed by Vite in a browser — **either `http://127.0.0.1:5173` or
`http://localhost:5173` works**. By default the frontend calls the backend through a same-origin
`/api` proxy (configured in `frontend/vite.config.ts`), so the `samesite="lax"` session cookie is
retained no matter which hostname you use. (Previously the frontend called `http://127.0.0.1:8000`
directly, and opening the app at `localhost:5173` made every API call cross-site — the browser
silently dropped the session cookie after `POST /career/new` and the app looped back to "Start New
Career". The proxy removes that footgun.)

To point at a backend on a non-default host/port, set `VITE_API_BASE_URL` (e.g.
`VITE_API_BASE_URL=http://127.0.0.1:9000 npm run dev`) — this overrides the `/api` proxy default.
For a production build served without the dev proxy, set `VITE_API_BASE_URL` to the backend's
absolute URL (ideally same-origin behind a reverse proxy, for the same cookie reason).

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
