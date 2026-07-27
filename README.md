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

The suite is large enough (1130+ tests) that `pytest-xdist` (a dev dependency) is worth using for
day-to-day iteration: `pytest -n auto` runs it in parallel across available cores, cutting a
~20-minute serial run to well under 5 minutes. Both give the same result; use plain `pytest` when
you want deterministic single-process output (e.g. debugging a specific failure).

## Status (2026-07-23)

All of v1's gameplay systems (DEVPLAN.md Steps 2.1–2.8) are implemented and merged: special
teams/strength states, goalies (hot-hand, rest-based rotation, pull-the-goalie), faceoffs
(three-way tie/winger-recovery model) and in-game injuries, salary cap/trades/free agency, the
entry draft and prospect generation, playoffs with real 3-on-3-OT/shootout resolution and a
selectable playoff officiating mode, awards/legacy/momentum/offseason/development (including
goalie season-to-season form variance), and coach line-juggling AI with a PP/PK tactics board.

The FastAPI + React web app (DEVPLAN.md Steps 2.9/2.10) is also implemented and merged: session/
career management, roster and line/pair/tactics editing, schedule/standings/sim-day controls, box
scores, and cap/trades/free-agency/draft/prospects/awards screens, all wired to a hockey-rink-themed UI
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

An economy round then rebalanced the salary cap, which had no teeth: world gen opened every team
roughly $49M under an $82.5M cap because contracts were priced off a formula unrelated to the cap
system's own market curve. Salaries now follow a curve calibrated against the real generated
rating distribution, and each generated roster is fitted onto a payroll target — so a league opens
at ~94% of the cap with most teams pressed to the ceiling, a few rebuilders holding real space,
and nobody over the hard cap.

Sustaining that across seasons exposed a bigger gap: drafted players had nowhere to develop, and
the stand-in built for the economy round turned out to be hiding something worse. The **prospect
development round** ([docs/PROSPECT_DEV_PLAN.md](docs/PROSPECT_DEV_PLAN.md)) replaced it with a
real system:

- **Four development tiers** — major junior, NCAA, the AHL and Europe — with the real eligibility
  rules that make them different from each other. Playing major junior permanently forfeits
  college eligibility, and the CHL–NHL transfer agreement bars a drafted junior player under 20
  from the AHL: he goes to the NHL or back to Kitchener, with nothing in between. The AHL is
  where older prospects go, and it needs an actual contract to enter.
- **NHL-shaped entry-level contracts.** Three years at 18–21, two at 22–23, one at 24 — and the
  slide rule, so signing your 18-year-old first-rounder and sending him back to junior doesn't
  waste the cheap years. It bounds itself at two slides exactly as the real one does.
- **Age curves that matter.** Where a prospect plays now sets how fast he develops, and a prospect
  who stalls starts losing ceiling at 21, so busts actually bust.
- **Two ways into the league besides the draft**: undrafted players keep developing and re-enter
  the next draft, and a handful of European pros arrive each summer already finished.
- **A Prospects screen** showing each team's system by tier, with the slide state and the
  sign-him-or-lose-him deadline called out — the decisions, not just the ratings.

The measurement that mattered: before this round the share of the league on entry-level deals fell
to **0% within two simulated offseasons**. The draft fed nothing into the NHL, ever, and payroll
looked healthy the whole time because the economy had quietly stopped having a talent pipeline. It
now holds a healthy entry-level presence across 8 seeds × 12 seasons, with payroll at 91–97% of
the cap and all four tiers populated.

A short follow-up round then added the manager-facing half: **call up** a signed prospect or
**send** a rostered player down to the minors, **two-way contracts** (a bad one-way deal buried in
the minors still counts a sheltered slice against the cap, so it's a real anchor), and a deeper
draft class so undrafted players can develop their way into the league.

A playtest calibration round then rebuilt the numbers underneath all of it. Team-level scoring had
always been NHL-realistic while every layer beneath it was not: the sim ran ~45% of real shot volume
and compensated with a ~2.3x inflated conversion rate, so goals per game came out right and
individual totals were absurd — an 82-goal defenseman, single-digit-shot games, a quarter of all
assists simply missing. Six systems turned out to be **inert or inverted rather than mistuned**, and
every one was silent: power-play units were never built for any team, zone selection was weighted
*by danger* so the crease was the commonest shot location, no skater could accumulate fatigue, and
both teams changed lines on a shared horn. See
[docs/DISTRIBUTION_TARGETS.md](docs/DISTRIBUTION_TARGETS.md) — that round's real deliverable is the
instrument, not the constants.

A UI/feedback round then acted on direct playtest notes rather than a new systems pass. Line editing
moved off the roster screen onto its own tab, with each slot now showing a player's rating alongside
his position. The roster screen gained sortable Ratings/Season Stats/Contract tabs instead of one
fixed column set. The draft board and both free-agency screens are filterable by position, age,
potential and archetype, sharing one filter hook rather than three copies of the same logic. A new
League Stats screen lists every player in the league — sortable, searchable by name — where
previously the only current-season view capped every category at the top 10. Rare "generational
talent" archetypes now carry a ⭐ wherever a player's name appears. And free agency itself changed:
teams now try to re-sign their own pending free agents before the market opens, weighted so stars
are retained far more often than fringe players, instead of every expiring contract hitting the
open market unconditionally regardless of quality — the fix required a shared per-team cap-space
pool (a naive per-player check let several simultaneous re-signings each look affordable while
collectively over-committing) and closed a separate, previously-latent gap where late-offseason
roster-minimum fills had no cap check of their own at all.

1130 backend tests pass (plus one deliberate `xfail`, a documented roster-depth gap); a full 82-game
season plus a complete playoff bracket runs cleanly end-to-end, both headlessly and through the web
app. **The suite takes roughly twenty minutes single-threaded** — several tests sim multiple full
seasons back to back — or well under five with `pytest -n auto` (see "Run tests" above). See
[DEVPLAN.md](DEVPLAN.md) for the full step-by-step plan and status notes, including a handful of
known non-blocking loose ends (search that file for "Known" and "not yet wired").

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

Every run prints a **league distribution report** after the standings and scoring leaders: shot
volume, shooting/save percentage, assists per goal, the defense share of scoring, leaderboard
concentration and ice time by deployment slot, each against its target band with a PASS/FAIL marker.
The bands live in `testkit/distribution.py` and the reasoning behind every one — including the fixes
that produced them and the first diagnoses that were wrong — is in
[docs/DISTRIBUTION_TARGETS.md](docs/DISTRIBUTION_TARGETS.md).

**Read that document before changing any calibration constant.** It also records the two standing
rules the round left behind: any constant expressed *per shot-attempt cycle* is coupled to shot
volume and gets silently rescaled when volume changes, and a band is never widened to make a failing
run pass — moving one requires the reasoning in the same commit. `tests/test_distribution.py` locks
the whole table in, asserting the mean across the four seeds the bands were calibrated against.
