# PuckSim Web Parity Plan — Step 2.11 series

Bringing the PuckSim web app to feature parity with the HoopR reference web app
(`/Users/hank/HoopR`), closing DEVPLAN's v1 exit criteria: *"a complete season (regular
season + playoffs + draft + FA + offseason) playable end-to-end via FastAPI+React."*

Planned 2026-07-03. All engine function names below were verified directly against source
during the planning session — implementing agents should trust them but re-read the cited
files before writing code.

## Why

Human testing of the v1 web app (2026-07-03) surfaced that the browser experience is a
dead end even though the engine (Steps 2.1–2.8) simulates the full franchise year:

1. **No path from regular season to postseason.** `POST /season/advance-day` never checks
   for season completion and nothing ever calls `sim/playoffs.py::start_playoffs` — after
   game 82 the Sim Day button increments the day counter forever.
2. **No player detail anywhere.** No `/players/{pid}` endpoint; ratings, season/career
   stats, and bio are never sent to the frontend; no name is clickable.
3. **Trades require typing raw player IDs** into free-text inputs, and no endpoint exposes
   any roster other than the user's own — the receive side is literally undiscoverable.
4. Assorted usability gaps vs. HoopR: one-day-at-a-time simming (82 clicks/season), no
   leaders, no history/awards archive, user-team-only schedule, results only console.log'd.

The engine already has everything: playoffs, offseason, draft, FA waves, awards, legacy/HoF.
**This round is surfacing, not building** — thin HTTP triggers plus screens, borrowing
HoopR's proven patterns (phase-aware nav, PlayerModal, checkbox trade builder, staged
offseason wizard).

## Scope decisions (locked with the user, 2026-07-03)

- Core loop + flagged gaps. Full multi-season loop in the browser: regular season →
  manual "Start Playoffs" → bracket sim → full offseason wizard (pre-draft → interactive
  draft room → tiered FA waves → finish) → next season.
- Player detail = HoopR-style **modal**, names clickable everywhere **including box
  scores** (exceeding HoopR).
- **Deferred** (see backlog at bottom): live in-game coaching, fog-of-war, trade
  block/solicit/AI offer inbox, power rankings, draft-pick trading, extend/waive.
- Tasks are **full-stack per feature**, one branch + PR each, against
  `github.com/H0m3B4s3/puck-sim`.

## How to dispatch

Each task section below is self-contained: branch name, files owned, exact endpoint/DTO/
component specs, HoopR reference reading, and Done criteria. Implementing agents make **no
design decisions** — where a spec says "field list", transcribe it verbatim.

| Wave | Tasks | Parallel? | Notes |
|---|---|---|---|
| 1 | T1–T5 | Yes (5-way) | Backend only. File-disjoint except one `import` + one `include_router` line each in `pucksim/web/app.py` — merge in order T1→T2→T3→T4→T5, rebasing; the conflict is two adjacent lines. |
| 2 | T6 → T7 | No (sequential) | Frontend foundation. T6 needs all Wave-1 DTO shapes merged; T7 needs T6's modal mount + T2's endpoint. |
| 3 | T8–T12 | Yes (5-way) | Feature screens. Each owns only its listed `screens/*.tsx` files. |

**Collision rules (binding):**
- `pucksim/web/serializers.py` — touched ONLY by T1.
- New Pydantic DTOs live in their own router module (existing precedent: `GameDTO` in
  `routers/season.py`), keeping Wave-1 tasks file-disjoint.
- `pucksim/web/routers/transactions.py` — touched ONLY by T5 (backend) and, on the
  frontend, `screens/Transactions.tsx` by T7 then T11 (sequential across waves).
- `frontend/src/api.ts`, `App.tsx`, `ui.tsx`, `index.css` — touched ONLY by T6 and then
  **frozen for Wave 3** (T6 pre-stages every client method, nav entry, prop, and CSS class
  the Wave-3 screens need).
- Every task: branch from latest `main`; Done includes `pytest tests/` green (backend) or
  `npm run build` clean (frontend).

## Binding design decisions (D1–D8)

**D1 — Summary DTO flags (owned by T1).** Extend `WorldSummaryDTO` in
`pucksim/web/serializers.py`:
- `regular_season_complete: bool = False` — computed as
  `world.phase != Phase.PRESEASON and bool(world.schedule) and all(g.played for g in world.schedule if not g.is_playoff)`.
  Do **not** reuse `sim.season.regular_season_complete()` bare: it returns `True` on an
  empty preseason schedule (`all([]) == True`). The phase guard means the flag *stays
  true* through playoffs/draft/FA until `start_season()` regenerates the schedule —
  exactly HoopR's behavior (its Playoffs tab persists through the offseason so the final
  bracket stays visible).
- `offseason_stage: Optional[str] = None` — **derived, no new World field** (HoopR
  precedent: `hoopsim/web/serializers.py:86-104`):

  ```python
  def _offseason_stage(world):
      if world.phase == Phase.DRAFT:
          if world.draft_class is None: return "pre_draft"
          if world.draft_class.complete: return "free_agency"
          return "draft"
      if world.phase == Phase.FREE_AGENCY: return "free_agency"
      return None
  ```

  (The engine auto-sets `Phase.DRAFT` when the Finals complete — `sim/playoffs.py::
  _build_next_round` — so `"pre_draft"` appears automatically once a champion is crowned.)
- `trade_deadline_day: Optional[int]`, `trade_deadline_passed: bool` — via existing
  `pucksim.systems.trades.trade_deadline_day/trade_deadline_passed` (lazy import inside
  `world_summary`, matching the `cap_summary` precedent).

**D2 — FA wave state.** Keep `world.fa_wave` as the dynamic attribute `freeagency.py`
already uses (`getattr(world, "fa_wave", None)`). The session store holds *live World
objects in memory* (`web/session.py`), so `fa_wave` survives across requests. It is NOT in
`World.to_dict()`, so a save/load mid-free-agency loses the wave; `/offseason/fa/start` is
idempotent, so a reloaded save resumes at wave 0. Acceptable — document in the endpoint
docstring.

**D3 — Sim-week is a backend loop** (`POST /season/advance-week`, body `{days: 1-14}`):
one HTTP round-trip, one autosave point, mirrors HoopR `POST /api/sim/week`
(`hoopsim/web/app.py:454-469`). A frontend loop was rejected (N round trips, N saves,
partial-failure states).

**D4 — Phase-aware nav in the hand-rolled router.** `NavRail`
(`frontend/src/ui.tsx`) changes from hardcoded `navItems` to an `items: {label, path}[]`
prop. `App.tsx` computes the list: base items + `{Playoffs, /playoffs}` when
`world.phase === "playoffs" || world.regular_season_complete`, + `{Offseason, /offseason}`
when `["draft","free_agency"].includes(world.phase)` (HoopR `App.tsx:252-265`). New
screens are ordinary `frontend/src/screens/*.tsx` files added as `case` branches in
`App.tsx::renderScreen()` — **no router library**.

**D5 — PlayerModal threading.** HoopR's exact pattern, no context provider: `App.tsx`
holds `const [openPid, setOpenPid] = useState<number | null>(null)`, passes
`onPlayer={setOpenPid}` as a prop to every screen, renders
`{openPid != null && <PlayerModal pid={openPid} onClose={() => setOpenPid(null)} />}` once
at the root (HoopR `App.tsx:242, 373-375`).

**D6 — Awards archival needs no new recording.** `offseason.archive_season()` (called by
`pre_draft`) already appends `{year, champion, champion_name, standings, awards}` to
`world.history` and ticks accolades/HoF via `legacy.record_accolades`/`legacy.retire`. The
web layer just (a) actually *calls* `pre_draft` (T5) and (b) reads
`world.history`/`hall_of_fame`/`legacy.leaderboards` (T3). The existing live-computed
`GET /transactions/awards` stays as the in-season "awards race" view.

**D7 — Trade panel.** New dedicated screen `frontend/src/screens/Trade.tsx` with its own
"Trades" nav entry; the free-text comma-separated section is **deleted** from
`Transactions.tsx` (T11). New backend endpoints `POST /transactions/trades/validate` and
`/execute` (T5) mirror HoopR `app.py:593-615`; the old `/trades/propose` stays untouched
for back-compat.

**D8 — Leaders live in the web layer.** Current-season leaders are presentation logic;
HoopR puts `leaders_view` in its web serializers, not the engine. Follow suit: implement
inside the new `routers/league.py` (T3). The **only engine addition in the whole round**
is `next_game_for_team(world, tid)` in `pucksim/sim/season.py` (T1).

---

## Wave 1 — Backend

### T1 — Summary flags + sim-control endpoints

**Branch:** `feat/summary-flags-sim-controls`
**Files:** `pucksim/web/serializers.py`, `pucksim/sim/season.py`,
`pucksim/web/routers/season.py`, `tests/test_web_sim.py` (new).
**HoopR reading:** `hoopsim/web/app.py:408-482` (sim/game + sim/week),
`hoopsim/web/serializers.py:86-147` (`_offseason_stage`, `world_summary`).

1. `serializers.py`: extend `WorldSummaryDTO` + `world_summary()` per **D1**. Add a
   module-level helper `def season_over(world) -> bool` implementing the guarded
   expression (import `Phase` from `pucksim.models.league`); both `world_summary` and
   `routers/season.py` use it.
2. `sim/season.py`: add

   ```python
   def next_game_for_team(world: World, tid: int) -> Optional[Game]:
       candidates = [g for g in world.schedule if not g.played and g.involves(tid)]
       return min(candidates, key=lambda g: (g.day, g.gid)) if candidates else None
   ```

3. `routers/season.py`:
   - `AdvanceDayResponse` gains `season_complete: bool` (from `season_over(world)`).
   - `POST /season/advance-week` — request `AdvanceWeekRequest {days: int = 7}` (clamp
     1–14); 400 unless `world.phase == Phase.REGULAR_SEASON`. Loop `days` times: break if
     `season_over(world)`; `games = advance_one_day(world)` (already persists box scores);
     accumulate. One `session_store.save(sid, world)` at the end. Response
     `AdvanceWeekResponse {day: int, phase: str, days_advanced: int, games_played: [...],
     user_games: [...], season_complete: bool}` — `user_games` is the subset where
     `g.involves(world.user_team_id)`.
   - `POST /season/sim-to-next-game` — no body; 400 unless REGULAR_SEASON.
     `target = next_game_for_team(world, world.user_team_id)`. If `target is None`: loop
     `advance_one_day` until `season_over(world)`, return `played=False`. Else loop until
     `target.played` (guard: at most `target.day - world.day + 2` iterations). Save once.
     Response `{played: bool, gid, day, phase, home, away, home_score, away_score,
     went_ot, went_so, season_complete}` (Optionals when `played=False`).

**Done:** `tests/test_web_sim.py` (session fixture pattern from `tests/test_web.py`):
(a) fresh career → `GET /career` has `regular_season_complete == False`,
`offseason_stage == None`; (b) `POST /season/advance-week {"days":3}` after
`/season/start` returns `days_advanced == 3`, `day == 3`, non-empty `games_played`;
(c) advance-week in preseason → 400; (d) sim-to-next-game returns `played == True` with
the user team in home/away and the game marked played in `GET /season/schedule`;
(e) sim to completion and assert `season_complete` flips true and the career summary shows
`regular_season_complete: true`. Full `pytest tests/` green.

### T2 — Player detail + any-team roster endpoints

**Branch:** `feat/player-detail-endpoint`
**Files:** `pucksim/web/routers/players.py` (new), `pucksim/web/routers/roster.py`,
`pucksim/web/app.py` (mount), `tests/test_web_players.py` (new).
**HoopR reading:** `hoopsim/web/app.py:320-326`, `hoopsim/web/serializers.py:312-360`
(`player_detail`, `legacy_resume_view`).

- `GET /players/{pid}` (new router, prefix `/players`). 404 for unknown pid. Response
  `PlayerDetailDTO` (defined in `players.py`):

  ```
  pid:int, name:str, age:int, position:str, secondary_position:Optional[str], shoots:str,
  is_goalie:bool, overall:int, potential:int          # p.scouted_potential()
  team_id:Optional[int], team_abbrev:str ("FA" if none), team_name:str ("" if none),
  team_color:str (team.primary_color; "#9aa0a6" if none),
  salary:int, years_remaining:int, morale:int,
  injury:Optional[str] (description), injury_games:int (0 if healthy),
  draft:Optional[dict]                                # raw p.draft: year/round/pick/team
  season_stats:dict   # skater: {gp,g,a,pts,ppg,sog,hits,blocks,pim,plus_minus,fo_pct}
                      # goalie: {gp,wins,losses,otl,save_pct,gaa,shutouts,shots_faced,saves}
                      # round: ppg 2dp, save_pct 3dp, gaa 2dp
  playoff_stats:Optional[dict]                        # same shape from p.playoffs; None when absent or gp==0
  rating_groups:Dict[str, List[dict]]                 # {group: [{key,label,value}]} from
                      # attributes.RATING_GROUPS (skaters) / GOALIE_RATING_GROUPS (goalies);
                      # label = key with "gk_" prefix stripped, "_"→" ", title-cased
  career:List[dict]                                   # raw p.career passthrough
  legacy:Optional[dict]  # from legacy.resume(world, p): {seasons, peak_ovr, totals,
                      #   accolades:[{key,label,count}] (labels from legacy.ACCOLADE_LABELS,
                      #   sorted by ACCOLADE_WEIGHTS desc), hof_score, hof};
                      #   None when p.career is empty
  ```

- `GET /roster/{tid}` — added at the **end** of `routers/roster.py` (after the literal
  `/lines`, `/tactics` routes so those keep matching first), `response_model=RosterDTO`,
  404 on unknown tid, works for **any** team (no fog-of-war in this round's scope).

**Done:** tests: skater detail has skater `season_stats` keys and the four skater rating
groups; goalie detail has goalie keys and the Goaltending group; unknown pid → 404; a free
agent has `team_abbrev == "FA"`; `GET /roster/{other_tid}` returns that team's players;
`GET /roster/lines` still works. Full `pytest tests/` green.

### T3 — League records: leaders, history, Hall of Fame, all-time leaderboards

**Branch:** `feat/league-records-endpoints`
**Files:** `pucksim/web/routers/league.py` (new, prefix `/league`), `pucksim/web/app.py`
(mount), `tests/test_web_league.py` (new).
**HoopR reading:** `hoopsim/web/app.py:255-291`,
`hoopsim/web/serializers.py:250-283, 363-400, 466-499`. Also port the sort logic from
`testkit/run_season.py::_print_top_scorers/_print_top_goalies`.

- `GET /league/leaders` → `{categories: [{stat, label, leaders: [{pid, name, position,
  team_id, team_abbrev, team_color, value}]}]}`. Six categories, top 10 each:
  skaters (non-goalies, `p.season.gp >= max(1, world.day // 4)`): `pts` "Points",
  `g` "Goals", `a` "Assists" (int values); goalies (`gp >= max(2, world.day // 4)`):
  `save_pct` "Save %" (desc, 3dp), `gaa` "GAA" (**ascending**, 2dp), `wins` "Wins".
- `GET /league/history` → `{seasons: [...]}`, most recent first (reversed
  `world.history`): `{year, champion_tid, champion_name, champion_abbrev, champion_color,
  awards: {hart|norris|vezina|calder|selke: entry}}` — each stored award entry is already
  self-contained (pid/name/team/position/gp/stats); enrich with `team_color` from live
  `world.teams.get(entry["tid"])` (default `"#9aa0a6"`).
- `GET /league/hall-of-fame` → `{members: [...]}` — `world.hall_of_fame` sorted
  `hof_score` desc, each snapshot flattened to `{pid, name, position, seasons, peak_ovr,
  last_team, first_year, last_year, draft, active: pid in world.players, totals,
  accolades: [{key,label,count}], hof_score, hof, induction_year}`.
- `GET /league/leaderboards?category=pts` → `{category, categories, rows}` via
  `legacy.leaderboards(world, category, limit=25)`; validate against
  `legacy.LEADERBOARD_CATEGORIES` (`("pts","g","a","gp","wins","shutouts")`) → 400
  otherwise; rows already carry `active`.

**Done:** tests: leaders on a fresh started world returns 6 categories with ≤10 rows
without erroring at 0 GP; after simulating days (drive `advance_one_day` directly on the
session World, per `test_web.py` precedent), pts leaders non-empty and sorted desc;
history is `[]` on a fresh world; drive one archived season via
`offseason.pre_draft(world, None)` directly, then `/league/history` returns one entry with
`year` and the awards dict; leaderboards rejects `category=bogus` with 400.

### T4 — Playoffs endpoints

**Branch:** `feat/playoffs-endpoints`
**Files:** `pucksim/web/routers/playoffs.py` (new, prefix `/playoffs`),
`pucksim/web/app.py` (mount), `tests/test_web_playoffs.py` (new).
**HoopR reading:** `hoopsim/web/app.py:488-555` (`/api/playoffs`, `/start`, `/advance`,
`_playoff_slate_out`).

Shared response `PlayoffsStateDTO`:

```
in_playoffs: bool          # phase == PLAYOFFS
can_start: bool            # phase == REGULAR_SEASON and schedule non-empty and
                           #   all non-playoff games played and world.bracket is None
                           #   (compute inline — do NOT import T1's helper; keeps Wave 1 independent)
bracket: Optional[dict]    # raw world.bracket — JSON-native by design
complete: bool             # playoffs.playoffs_complete(world)
champion_tid/champion_name/champion_abbrev/champion_color: Optional
round: Optional[str], round_label: Optional[str]   # playoffs.ROUND_LABELS[bracket["round"]]
```

- `GET /playoffs` → state. Bracket is returned whenever `world.bracket` is not None —
  **including post-champion in DRAFT phase** (supersedes the phase-gated
  `GET /season/playoffs/bracket`, which stays untouched for back-compat).
- `POST /playoffs/start` → 400 unless `can_start`; `playoffs.start_playoffs(world)`;
  save; return state.
- `POST /playoffs/advance` → 400 unless `world.phase == Phase.PLAYOFFS and world.bracket
  and not playoffs.playoffs_complete(world)`.
  `results = playoffs.advance_playoff_slate(world)` (returns
  `List[Tuple[series_dict, GameResult]]`; `GameResult` carries
  `home_tid/away_tid/home_score/away_score/went_ot/went_so`); save; return all state
  fields + `slate: [{sid, round, status (playoffs.series_status(world, s)), home_tid,
  away_tid, home_abbrev, away_abbrev, home_score, away_score, went_ot, went_so}]`.
  **The engine auto-sets `Phase.DRAFT` when the Finals resolve — never set phase in the
  router.**

**Done:** tests: start mid-regular-season → 400; play out the schedule via direct engine
loop on the session World, then `GET /playoffs` shows `can_start: true`;
`POST /playoffs/start` → `len(bracket["series"]) == 8`, phase `"playoffs"`; repeated
advance (bounded loop ≤ 40) reaches `complete: true` with non-null `champion_tid`, phase
`"draft"`, slate rows carrying abbrevs/scores; advance after completion → 400;
`GET /playoffs` after completion still returns the full bracket + champion.

### T5 — Offseason wizard + trade validate/execute + wave-aware FA board

**Branch:** `feat/offseason-and-trades-endpoints`
**Files:** `pucksim/web/routers/offseason.py` (new, prefix `/offseason`),
`pucksim/web/routers/transactions.py`, `pucksim/web/app.py` (mount),
`tests/test_web_offseason.py` (new), `tests/test_web_full_loop.py` (new).
**HoopR reading:** `hoopsim/web/app.py:593-615` (trade validate/execute), `825-952`
(offseason wizard endpoints).

Offseason endpoints (DTOs in `offseason.py`):

- `POST /offseason/pre-draft` — if `world.draft_class is not None`: return
  `{resumed: True, ...zeros}` (**idempotency guard — `pre_draft` ages/retires/expires and
  must never run twice**). Else 409 unless `world.phase == Phase.DRAFT` ("Playoffs are not
  complete."). Then: `champ = playoffs.champion(world)`;
  `summary = offseason.pre_draft(world, champ)`; `draft_system.setup_draft(world)`; save.
  Response `{resumed: bool, retired: int, new_fas: int, inducted: List[dict],
  milestones: List[dict], champion_tid: Optional[int], champion_name: str,
  awards: Optional[dict]}` — awards from `world.history[-1]["awards"]` if history exists.
  (`pre_draft` returns `{"new_fas","retired","inducted","milestones"}`.)
- `GET /offseason/draft/board` — 409 if `world.draft_class is None`. Auto-advance loop:
  `while not dc.complete and dc.team_on_clock() != world.user_team_id:` capture
  `pick_no = dc.current_pick + 1` (**`current_pick` is 0-based** — an index into `order`,
  unlike HoopR) and the on-clock tid, `pid = draft_system.ai_pick(world)`, append
  `{pick, team_abbrev, name, position, overall}` to `recent`. If `dc.complete`:
  `draft_system.undrafted_to_free_agency(world)`; `offseason.enforce_roster_max(world)`;
  `world.phase = Phase.FREE_AGENCY`; save; return
  `{complete: True, recent, board: [], pick: None, round: None}`. Else save; return
  `{complete: false, pick: dc.current_pick + 1,
  round: (pick - 1) // len(world.teams) + 1, recent,
  board: [{pid,name,position,age,overall,potential}]}` — board from
  `draft_system.draft_board(world)[:60]` with `potential = p.scouted_potential()`.
- `POST /offseason/draft/pick` body `{prospect_id: Optional[int] = None}` — 409 if no
  class or complete; 409 if `dc.team_on_clock() != world.user_team_id`.
  `pid = prospect_id or draft_system.best_available(world)`;
  `signed = draft_system.make_pick(world, pid)` (ValueError → 400);
  `pick_number = dc.current_pick` (post-call — `record_pick` already advanced it); save.
  Response `{pick, pid, name, position, overall, potential, signed}`.
- `POST /offseason/fa/start` — 400 unless `world.phase == Phase.FREE_AGENCY`.
  `offseason.enforce_roster_max(world)`; if `getattr(world, "fa_wave", None) is None:
  freeagency.start_fa_market(world)`; save. Response `{active: bool,
  wave: world.fa_wave + 1, total: freeagency.NUM_FA_WAVES,
  name: freeagency.FA_WAVE_NAMES[world.fa_wave]}`.
- `POST /offseason/fa/advance` — 400 unless FREE_AGENCY; start the market first if
  `fa_wave` is None. `result = freeagency.run_fa_wave(world,
  exclude_tid=world.user_team_id)` (**exclude the user — the AI must never sign players
  onto the user's roster**); `more = freeagency.advance_fa_wave(world)`; save. Response
  `{signings: int, done: not more, next: FAWaveDTO}`.
- `POST /offseason/finish` — 400 unless FREE_AGENCY. `offseason.post_offseason(world)`
  (fills rosters, culls FAs, grows cap, `season_year += 1`, clears `draft_class`,
  `start_season` → REGULAR_SEASON day 0); save; return `world_summary(world)`.

`transactions.py` changes:

- `POST /transactions/trades/validate` — body = existing `TradeOfferRequest
  {other_team_id, user_sends, user_receives}` → build `trades.TradeOffer(a=user_tid,
  b=other, a_sends=user_sends, b_sends=user_receives)`;
  `legal, why = trades.validate_trade(world, offer)`;
  `accepts, ai_why = trades.ai_evaluates(world, offer, body.other_team_id) if legal else
  (False, "Trade is not legal.")`. Response `{legal, legal_reason, accepts, ai_reason}`.
  **Pure read — no save.**
- `POST /transactions/trades/execute` — same body → validate (illegal → 400 with reason);
  `ai_evaluates`; if not accepts → `{executed: False, reason: ai_why}`; else
  `trades.execute_trade(world, offer)`; save; `{executed: True, reason: "Trade
  completed."}`. Keep `/trades/propose` untouched.
- `GET /transactions/freeagents` — response rows gain
  `ask: int (freeagency.wave_market_salary(world, p))` and
  `preferred_years: int (freeagency.contract_years_for(p))`; pool from
  `freeagency.fa_wave_pool(world)` when `getattr(world,'fa_wave',None) is not None`, else
  the current sorted-by-overall list.

**Done:** `tests/test_web_offseason.py`: pre-draft during regular season → 409; drive a
world to `Phase.DRAFT` (call `playoffs.start_playoffs` + `run_full_playoffs` directly on
the session World), then pre-draft returns retired/new_fas counts and `world.history` has
one entry; second pre-draft call → `resumed: True`; draft board auto-advances to the user
on the clock (`pick` set, board non-empty); pick when not on clock → 409; the user's pick
returns `signed` and advances; loop board+pick to completion → `complete: True` and the
career summary shows `offseason_stage == "free_agency"`; fa/start returns wave 1/4
"Franchise-caliber targets"; fa/advance ×4 ends `done: True`; finish → summary
`season_year` +1, phase `regular_season`, day 0. Trade tests: lopsided offer →
`legal: True, accepts: False` with reason; empty offer → `legal: False`; a fair swap
executes and both rosters change via `GET /roster` / `GET /roster/{tid}`.
`tests/test_web_full_loop.py`: one slow end-to-end test driving new career →
season/start → advance-week loop until `regular_season_complete` → playoffs start/advance
loop → pre-draft → board/pick loop → FA waves → finish → assert second season at
regular_season/day 0 with `history` length 1. **This test IS DEVPLAN's v1 exit criteria.**

---

## Wave 2 — Frontend foundation (sequential)

### T6 — API client, shell, nav, toasts, sim controls, stubs

**Branch:** `feat/frontend-foundation`
**Files:** `frontend/src/api.ts`, `frontend/src/ui.tsx`, `frontend/src/App.tsx`,
`frontend/src/index.css`, `frontend/src/PlayerModal.tsx` (new stub),
`frontend/src/screens/{Playoffs,Offseason,Leaders,History,Trade}.tsx` (new stubs).
**HoopR reading:** `frontend/src/App.tsx:230-378` (Hub/nav), `487-590` (PlayPanel sim
controls), `frontend/src/ui.tsx` (whole file).

After this task, `api.ts`/`App.tsx`/`ui.tsx`/`index.css` are **frozen for Wave 3**.

- **api.ts**: interfaces mirror every Wave-1 DTO field list verbatim. `WorldSummary` +=
  `regular_season_complete`, `offseason_stage`, `trade_deadline_day`,
  `trade_deadline_passed`. Methods: `advanceWeek(days = 7)`, `simToNextGame()`,
  `getPlayer(pid)`, `getTeamRoster(tid)`, `getLeaders()`, `getHistory()`,
  `getHallOfFame()`, `getLeaderboards(category)`, `getPlayoffs()`, `startPlayoffs()`,
  `advancePlayoffs()`, `preDraft()`, `offseasonDraftBoard()`,
  `offseasonDraftPick(prospectId: number | null)`, `faStart()`, `faAdvance()`,
  `finishOffseason()`, `validateTrade(body)`, `executeTrade(body)`; `FreeAgentRow` type
  gains `ask`/`preferred_years`.
- **ui.tsx**: port HoopR's `Modal` (ui.tsx:99-121), `useToast` (140-148), `Pill`
  (132-138). `NavRail` → `items` prop (D4). `ScoreboardBar` gains props `onSimWeek`,
  `onSimToNextGame`, `simControlsEnabled: boolean`, `phaseHint?: string` — renders three
  buttons (Sim Day primary, Sim Week, Next Game) when enabled, else the `phaseHint` as a
  Pill.
- **App.tsx**: nav per D4 (base: Home, Roster, Standings, Schedule, Box Score, Leaders,
  Trades, Transactions, History; conditional: Playoffs, Offseason). `useToast` mounted;
  `openPid` per D5; `boxScoreGid: number | null` state +
  `onViewBoxScore(gid)` → sets gid and navigates to `/box-score` (`BoxScore.tsx` gains an
  optional `initialGid` prop seeding its selection via `useEffect`). Mutations
  `advanceWeek`/`simToNextGame`: on success invalidate `["career"]`, `["schedule"]`,
  `["standings"]`, toast `"Simulated {n} games — day {day}"`, and when `season_complete`:
  toast `"Regular season complete — start the playoffs from the Playoffs tab."` (replaces
  the `console.log` in `showSimDayResults`). Sim controls enabled only when phase is
  preseason/regular_season **and not** `regular_season_complete`; `phaseHint` otherwise
  ("Playoffs — use the Playoffs tab" / "Offseason — use the Offseason tab" / "Regular
  season complete"). Five stub screens rendered as new `case` branches; **every screen
  (existing + new) receives props `{world, onPlayer, toast}`** (existing screens: add the
  optional props without using them yet — keep diffs minimal).
- **PlayerModal.tsx stub**: `useQuery(["player", pid], () => api.getPlayer(pid))`
  rendering name/position/overall in a `Modal` — T7 fleshes out the body.
- **index.css**: pre-stage ALL new classes (Wave 3 may not touch this file): `.toast`,
  `.modalBg/.modal/.modalHead/.modalBody`,
  `.bracketCols/.bracketCol/.roundName/.seriesCard(.active)/.seedRow(.win,.mine)/.seed/.abbr/.wins/.champ`,
  `.awardCard`, `.accoladeChip/.legacyBox/.legacyAccolades`,
  `.ratingGroup/.ratingRow/.ratingBar/.ratingFill`, `.statRow`,
  `.tradeGrid/.verdict/.deadline(.soon,.passed)`, `.leadersGrid`, `.waveBanner`,
  `.recentPicks`. Follow the existing Panel/btn design tokens.

**Done:** `npm run build` clean; browser smoke: new career → no Playoffs/Offseason tabs;
Sim Day/Week/Next Game work with toasts; stub screens render placeholders; nothing
crashes.

### T7 — PlayerModal + clickable names on existing screens

**Branch:** `feat/player-modal`
**Files:** `frontend/src/PlayerModal.tsx`, `frontend/src/screens/Roster.tsx`,
`frontend/src/screens/BoxScore.tsx`, `frontend/src/screens/Transactions.tsx`.
**HoopR reading:** `frontend/src/App.tsx:3594-3693` (PlayerModal).

Full card: header name colored by overall, `POS · OVR n · POT n`; bio line (age, shoots,
`$salary × Ny`, injury in red); provenance line (`Drafted {year} · Round {r}, Pick {p}
({team})` or "Undrafted"); stat tiles — skater GP/G/A/PTS/PPG/+−, goalie GP/W/SV%/GAA/SO;
playoff tile row when `playoff_stats` present; legacy box when `legacy` non-null
(seasons, totals line, accolade chips `{count}× {label}`, HoF badge); per-season career
table (year, team, gp, g/a/ppg or wins/sv%/gaa, ovr); rating groups as labeled progress
bars — **bar width `((value − 25) / 74) * 100` clamped 0–100** (PuckSim ratings are
25–99, not HoopR's scale).

Clickable names: `Roster.tsx` name cell → `onPlayer?.(row.pid)`; `BoxScore.tsx` skater
and goalie name cells (both teams — exceeds HoopR); `Transactions.tsx` FA table names
(also adopt the new `FreeAgentRow` type and render an Ask column).

**Done (browser):** roster name opens the modal with grouped rating bars; a goalie shows
the Goaltending group + goalie tiles; box-score names on both teams open it; FA rows show
Ask and open it; Escape/backdrop/✕ close it. `npm run build` clean.

---

## Wave 3 — Feature screens (parallel; each task owns only its screen files)

### T8 — Playoffs screen

**Branch:** `feat/playoffs-screen` — **Files:** `frontend/src/screens/Playoffs.tsx` only.
**HoopR reading:** `frontend/src/App.tsx:2630-2721` (PlayoffsPanel), `2732-2817`
(Bracket/SeriesCard).

`useQuery(["playoffs"], api.getPlayoffs)` + standings query for a
`tid → {abbrev, primary_color, name}` map. When `can_start`: "Start Playoffs" button →
`api.startPlayoffs()` → toast + invalidate `["playoffs"], ["career"]`. In playoffs & not
complete: "Sim Slate" → `api.advancePlayoffs()` → render slate `status` rows, invalidate.
Bracket: 4 round columns (First Round / Conference Semifinals / Conference Finals /
Stanley Cup Final) from `bracket.all_series` grouped by `round`; SeriesCards show seed
(`bracket.seeds[String(tid)]`), color dot, abbrev, series win count; winner bold, user
team highlighted, active round outlined. Champion banner + toast
"🏆 {champion_name} win the Stanley Cup — begin the offseason from the Offseason tab."

**Done (browser):** tab appears on season completion; start → 8/4/2/1 series over
successive slates; champion banner; Offseason tab appears (phase flips to draft); the
final bracket persists on the Playoffs tab afterward.

### T9 — Offseason wizard screen

**Branch:** `feat/offseason-screen` — **Files:** `frontend/src/screens/Offseason.tsx` only.
**HoopR reading:** `frontend/src/App.tsx:2984-3156` (OffseasonPanel), `3248-3338`
(OffseasonFA).

Staged off `world.offseason_stage`:
- `null` → "The offseason hasn't started" card.
- `"pre_draft"` → intro + "Begin Offseason" → `api.preDraft()`; toasts: retirements/FA
  counts, award winner ("🏆 {name} wins the Hart — see History"), each HoF induction, each
  milestone. Invalidate `["career"]`, load board.
- `"draft"` → draft room: board on mount; `Pick #{pick} (Round {round})` header,
  recent-AI-picks ticker, "Auto-pick best available" (`offseasonDraftPick(null)`), board
  table (Rank/Name/Pos/Age/OVR/POT/Draft button); reload board after each pick; on
  `complete` → invalidate `["career"]` (stage flips server-side), toast "Draft complete —
  free agency opens."
- `"free_agency"` → `api.faStart()` on mount; wave banner `Wave {i}/{total} — {name}`;
  roster count (`{n}/23`) + cap space; FA table (Ask/Years/Sign →
  `api.signFreeAgent(pid)`); "Done with this wave → let rival GMs bid" →
  `api.faAdvance()` → toast `Rival GMs signed {signings}`; when `done`: "Finish Offseason
  → Start {year+1} Season" → `api.finishOffseason()` → invalidate ALL queries → toast
  "Season underway!".

**Done (browser):** champion → next season fully in the browser; leaving and returning
mid-draft resumes correctly (stage is server-derived); user's roster stays legal.

### T10 — Leaders + History screens

**Branch:** `feat/leaders-history-screens` — **Files:** `frontend/src/screens/Leaders.tsx`,
`frontend/src/screens/History.tsx` only.
**HoopR reading:** `frontend/src/App.tsx:1171-1202` (Leaders), `1239-1424` (History).

Leaders: `.leadersGrid` of 6 category Panels, each a top-10 table (rank, clickable name,
colored team abbrev, value). History: three-segment toggle Seasons | Hall of Fame |
Records — Seasons: per-year Panels, champion line, AwardCards for Hart/Norris/Vezina/
Calder/Selke (name, team, stat line: skater `G/A/PTS`, goalie `W/SV%/GAA`; clickable);
Hall of Fame: table (name, pos, years, seasons, peak OVR, totals, accolade summary, HoF
score), name clickable **only when `active`** (retired pids 404 on `/players/{pid}`);
Records: category `<select>` + all-time table with an active/retired pill.

**Done (browser):** after one archived season all three segments populate; clean empty
states ("No seasons archived yet") on a fresh career.

### T11 — Trade screen rebuild

**Branch:** `feat/trade-screen` — **Files:** `frontend/src/screens/Trade.tsx` (new) +
`frontend/src/screens/Transactions.tsx` (deletions only).
**HoopR reading:** `frontend/src/App.tsx:2171-2336` (TradePanel), `2484-2530` (PickList).

Port TradePanel minus pick legs/block/solicit: deadline banner from
`world.trade_deadline_day/passed` ("⏳ Trade deadline in {n} days" / "🔒 deadline
passed" + disabled buttons); partner `<select>` (standings minus user team); two checkbox
PickList panels — "You send" from `api.getRoster()`, "You receive" from
`api.getTeamRoster(partner)`; rows: checkbox, clickable name, pos, age, OVR, salary;
running salary totals per side. "Check Trade" → `api.validateTrade(...)` → verdict line
`"{Legal|Illegal}: {legal_reason}. {AI accepts. | AI declines: {ai_reason}}"`. "Execute"
(disabled when empty/past deadline) → `api.executeTrade(...)` → executed ? toast + clear
selections + refetch both rosters + invalidate `["roster"], ["standings"]` : toast reason.
In `Transactions.tsx`: **delete** the free-text trade section AND the draft-board section
(the draft now lives in the Offseason wizard); keep cap summary + FA board.

**Done (browser):** lopsided offer declined with reason; fair offer executes and both
rosters visibly change; deadline-passed disables actions; zero free-text pid inputs remain
anywhere in the app.

### T12 — Schedule + Standings upgrades

**Branch:** `feat/schedule-standings-upgrades` — **Files:**
`frontend/src/screens/Schedule.tsx` + `frontend/src/screens/Standings.tsx` only.

Schedule: "My Team | Around the League" segmented toggle. My Team keeps the current list
+ per-unplayed-game "Sim" button (existing `POST /season/games/{gid}/sim`) and a "Box
Score" button on played games → `onViewBoxScore(gid)` (prop wired in T6). Around the
League: day picker (default `world.day - 1`, bounded 0..max scheduled day) listing every
game that day with scores + OT/SO tags + Box Score links. Standings: rows grouped into
two conference Panels with division sub-headers (sorted by points within group); seed
column 1–8 per conference; visual playoff cutline under seed 8
(`config.PLAYOFF_TEAMS_PER_CONF = 8`); user-row highlight kept; replace the raw
`JSON.stringify` bracket `<pre>` with a link/hint to the Playoffs tab.

**Done (browser):** yesterday's league-wide scores visible; simming one game from
Schedule updates its row and the standings; the cutline renders under seed 8 in each
conference.

---

## Deferred backlog (explicitly out of scope this round)

- **Live in-game coaching** (HoopR's crunch-time bench control) — requires the
  resumable-generator-over-HTTP session pattern PuckSim's web layer deliberately skipped
  (DEVPLAN Step 2.9 open item #3). Its own round.
- **Scouting fog-of-war** display layer (potential bands/grades + global toggle).
- **Trade block, solicit-offers, AI-initiated offer inbox** (HoopR SolicitPanel/OffersPanel).
- **Power rankings** (SRS + talent prior).
- **Draft-pick trading** — engine gap, deferred to DEVPLAN Step 3.1.
- **Contract extend/waive** endpoints + UI (dead-money handling).
- **URL router / deep links** (both apps use state-based navigation today).
- **Team-color WCAG contrast engine** (HoopR `theme.tsx::readable()`).
