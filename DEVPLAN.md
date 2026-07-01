# PuckSim — Development Plan

Translation of [DESIGN.md](DESIGN.md) into an ordered, dispatchable sequence of build steps. Each step is scoped to roughly "one PR's worth" of work — small enough to hand to a single coding agent, big enough to be a coherent unit.

All HoopR file references below were verified directly against `/Users/hank/HoopR/hoopsim/` source (paths, line counts, and class/function signatures accurate as of the planning session on 2026-07-01).

Conventions:
- **Phase**: MVP / v1 / v2+ (per DESIGN.md phasing)
- **Deps**: step numbers that must merge first
- **HoopR ref**: real file(s) to mirror the *pattern* of (not a fork — rewrite the numbers, reuse the shape)
- **Files**: new/modified PuckSim paths (all under `/Users/hank/PuckSim/`)
- **Done**: concrete, checkable exit criteria

---

## PHASE 0 — Repo Scaffolding (blocks everything)

### Step 0.1 — Repo scaffolding: packaging, test config, lint, docs stub
**Deps:** none
**HoopR ref:** `/Users/hank/HoopR/pyproject.toml` (`[build-system]` setuptools>=77.0; `[project]` name/version/description/readme/license/requires-python; `[project.optional-dependencies]` dev=[pytest,httpx] and web=[fastapi,uvicorn]; `[project.scripts]`; `[tool.setuptools.packages.find]`; `[tool.pytest.ini_options] testpaths`); `/Users/hank/HoopR/.gitignore`; `/Users/hank/HoopR/README.md` (structure only).
**Files:**
- `pyproject.toml` — package `pucksim`, `requires-python = ">=3.9"`, minimal core deps (no `rich` — PuckSim is web-first, not TUI-first, a deliberate deviation from HoopR), `dev = ["pytest>=7.0", "httpx>=0.24"]`, `web = ["fastapi>=0.104", "uvicorn[standard]>=0.24"]`, script entry `pucksim-web = "pucksim.web.app:run"` (no TUI entry point), `testpaths = ["tests"]`.
- `.gitignore` (Python + node + `.venv` + `saves/` + `__pycache__` + `frontend/node_modules` + `frontend/dist`)
- `README.md` — stub: name, one-paragraph description, install (`pip install -e ".[dev,web]"`), test command, web run command (placeholder until Step 2.9).
- `pucksim/__init__.py`, `tests/__init__.py`
- Empty package dirs w/ `__init__.py`: `pucksim/models/`, `pucksim/gen/`, `pucksim/sim/`, `pucksim/systems/`, `pucksim/save/`, `pucksim/web/`
- `testkit/` directory (chosen over `scripts/` — signals test infra, not user scripts)
- `docs/` (empty, populated in a later step)
**Done:** `pip install -e ".[dev,web]"` succeeds in a clean venv; `pytest` runs (0 collected OK); `python -c "import pucksim"` succeeds; tree matches DESIGN.md's proposed architecture.

---

## PHASE 1 — MVP (models + sim core, headless only, 5v5 no special teams)

### Step 1.1 — config.py: central tunables file
**Deps:** 0.1
**HoopR ref:** `hoopsim/config.py` (136 lines, flat sectioned constants; `SCHEMA_VERSION`, `SAVE_DIR_NAME`, `RATING_MIN`/`RATING_MAX`, small helper functions living alongside constants).
**Files:** `pucksim/config.py`
**Open items flagged, not resolved here:** concrete rating list (owned by Step 1.4); default standings rule (provisionally "Standard", reversible/config-only).
**Content:** `SCHEMA_VERSION`/`SAVE_DIR_NAME`/`AUTOSAVE_SLOT`; league shape (`NUM_TEAMS=32`, conferences/divisions, roster min/max, `SEASON_GAMES=82`); game structure (3 periods x 20min, 3v3 OT, `SHIFT_SECONDS_TARGET≈45`); **standings rule presets as data** — `STANDINGS_RULES = {"standard": {...}, "retro": {...}, "three_two_one_zero": {...}}`, each with points per outcome + `has_shootout` flag; strength-state constants (5v5/PP/PK/4v4/3v3/5v3) stubbed for later engine use; penalty durations (minor=120s, major=300s, misconduct); aging curve placeholders.
**Done:** `tests/test_config.py` — 3 standings presets exist with correct point totals; rating bounds are 25/99.

### Step 1.2 — rng.py: seedable, save-restorable RNG
**Deps:** 0.1 (parallel with 1.1)
**HoopR ref:** `hoopsim/rng.py` (82 lines — nearly direct port: `class Rng` wrapping `random.Random`; `random()`, `chance(p)`, `randint`, `uniform`, `gauss`, `triangular`, `choice`, `choices`, `weighted_one`, `sample`, `shuffle`; `get_state()`/`set_state()`/`from_state()` returning JSON-serializable `[version, list(internal), gauss_next]`).
**Files:** `pucksim/rng.py`
**Done:** `tests/test_rng.py` — same seed → deterministic draws; `get_state()`/`set_state()` round-trips.

### Step 1.3 — stats.py: skater StatLine + goalie StatLine (two shapes)
**Deps:** 0.1 (parallel with 1.1, 1.2)
**HoopR ref:** `hoopsim/models/stats.py` (105 lines — counters tuple + dataclass-with-derived-properties + `add()`/`reset()`/`to_dict()`/`from_dict()`), but per DESIGN.md point 9 this becomes **two classes**, not one.
**Files:** `pucksim/models/stats.py`
**Content:** `SkaterStatLine` (g/a/sog/pim/hits/blocks/giveaways/takeaways/fo_won/fo_lost + derived points/plus_minus/fo_pct); `GoalieStatLine` (shots_faced/saves/goals_against/shutouts/w-l-otl + derived save_pct/gaa). Decide whether Corsi/Fenwick/xG live as StatLine counters or are computed downstream from the shot-attempt event log (recommend the latter — StatLine holds simple `corsi_for`/`corsi_against` aggregates, authoritative source is the event stream per Step 1.12).
**Done:** `tests/test_stats.py` — derived properties correct on hand-picked counters; both classes round-trip `to_dict()`/`from_dict()`.

### Step 1.4 — attributes.py: rating scale, position groups, archetypes (skaters + goalies)
**Deps:** 0.1 (parallel with 1.1–1.3)
**HoopR ref:** `hoopsim/models/attributes.py` (207 lines — `POSITIONS`, `RATING_GROUPS`, `ALL_RATINGS`, `COMPOSITES`/weighted-blend formula, `POSITION_WEIGHTS` summing to 1.0, `clamp_rating()`, `composite()`/`overall()`, `Archetype` class + `ARCHETYPES`/`RARE_ARCHETYPES` tiers).
**Files:** `pucksim/models/attributes.py`
**First sub-task (open item):** draft the concrete skater vs. goalie rating list (skater: Physical/Offense/Defense/Mental groups — skating/shooting/passing/checking/faceoffs/discipline; goalie: separate smaller set — reflexes/positioning/rebound-control/puck-handling/consistency) before implementing. Treat first version as provisional/tunable, noted in a code comment.
**Content:** `POSITIONS` tuple (coordinate with Step 1.7 on LW/C/RW/D/G vs finer LD/RD split); parallel skater and goalie rating/composite structures — goalies likely need a bespoke "overall" (single-category-dominant, not a blended composite, per DESIGN.md point 4); skater archetypes excluding any fighting/enforcer skew (out of scope per DESIGN.md); rare/unicorn tier for both sides.
**Done:** `tests/test_attributes.py` — `overall()` in [25,99] at each position; position weights sum to 1.0; archetype skews never push ratings outside [25,99].

### Step 1.5 — contract.py: simplified v1 cap/contract model
**Deps:** 0.1 (parallel with 1.1–1.4)
**HoopR ref:** `hoopsim/models/contract.py` (100 lines — mirror almost directly: `salaries`/`guaranteed`/`options`/`no_trade`/`signed_year`/`years_with_team`/`is_rookie_scale`; `advance_year()`, `to_dict()`/`from_dict()`, `flat_contract()` factory).
**Files:** `pucksim/models/contract.py`
**Note:** port HoopR's shape nearly verbatim, drop NBA-specific concepts (Bird rights); keep `is_rookie_scale` as a generic flag driving simplified entry-level pay. Do NOT invent NHL CBA mechanics (arbitration/offer sheets/LTIR/waivers/ELC) — explicitly deferred to v2+ (Step 3.1).
**Done:** `tests/test_contract.py` — `advance_year()` correctly drops/shifts; round-trips; `flat_contract()` factory works.

### Step 1.6 — player.py: Player model (skater + goalie)
**Deps:** 1.3, 1.4, 1.5 (hard blocking — embeds StatLine, ratings dict, Contract)
**HoopR ref:** `hoopsim/models/player.py` (178 lines — `Player` dataclass shape: identity fields, `ratings: Dict[str,int]`, `potential`, `secondary_position`, `contract`, `condition`/`morale`/`injury`, `scout_error`, `pre_draft`/`draft` bio, `season`/`playoffs` stat lines, `career`, `accolades`; `Injury` dataclass; `overall`/`is_free_agent`/`is_injured`/`available`/`rating()`/`scouted_potential()`; full `to_dict()`/`from_dict()`).
**Files:** `pucksim/models/player.py`
**First sub-task (open item):** confirm single `Player` dataclass with position-conditional stat-line type (recommended) vs. separate `Skater`/`Goalie` dataclasses — this affects every downstream consumer, decide before writing serialization.
**Done:** `tests/test_player.py` — construct skater + goalie, `overall` differs sensibly by position, both round-trip serialization (including differing StatLine shape), `Injury`-driven properties behave correctly.

### Step 1.7 — team.py: roster + line/pair on-ice-group data structures
**Deps:** 1.6 (hard blocking)
**HoopR ref:** `hoopsim/models/team.py` (419 lines — `roster: List[int]` (ids only, pure data), `chemistry`/`pair_key()`/`lineup_familiarity_secs()`/`seed_chemistry()`, `roles`/`ROLE_TAGS`, `tactics`, `coach`, win/loss/streak, `dead_money`, roster-helper functions outside the dataclass: `roster_players()`, `team_salary()`, `assign_positions()`, `auto_set_lineup()`, `rotation_pool()`).
**Files:** `pucksim/models/team.py`
**Critical decision (DESIGN.md point 1):** on-ice groups must be plain lists, not hard-coded `Line`/`Pair` classes. Concretely: `Team.lines: List[List[int]]` (4 x 3 ids), `Team.pairs: List[List[int]]` (3 x 2 ids), `Team.goalie_starter`/`Team.goalie_backup: Optional[int]`. Expose `current_forward_line(idx)`/`current_d_pair(idx)` returning plain lists so a future "caught players" pass can splice ids in without a schema change. Reuse HoopR's `pair_key()`/`lineup_familiarity_secs()` directly over whichever 2-5 ids are grouped for a shift. Auto-line-builder mirrors `assign_positions()`'s slot-fill-by-fit algorithm for LW/C/RW/D slots.
**First sub-task:** confirm `POSITIONS` shape from Step 1.4 before writing the line-builder.
**Done:** `tests/test_team.py` — auto-line-builder on a 12F/6D/2G roster produces 4 complete lines + 3 complete pairs + starter/backup goalie; `Team.lines`/`Team.pairs` are plain `List[List[int]]` (test splices an extra id in with no type error, proving the flexibility requirement).

### Step 1.8 — league.py: Phase enum, Game dataclass, standings math (multi-rule)
**Deps:** 1.7
**HoopR ref:** `hoopsim/models/league.py` (100 lines — `Phase` w/ `ORDER`/`LABELS`; `Game` dataclass w/ `gid/day/home/away/scores/played/is_playoff/series_id` + `winner`/`loser`/`involves()`; `_sort_key()`/`standings()`/`conference_standings()`).
**Files:** `pucksim/models/league.py`
**Content:** `Phase` = PRESEASON/REGULAR_SEASON/PLAYOFFS/DRAFT/FREE_AGENCY/OFFSEASON. `Game` extended with `went_ot`/`went_so` flags. Standings math **parameterized by active rule** (Standard/Retro/3-2-1-0), not a single hardcoded win_pct sort: `points_for_game(rule, is_home, result) -> int`, `standings(teams, rule)` sorted by accumulated points with a documented tiebreaker chain (points → wins → goal differential → team id, provisional).
**Done:** `tests/test_league.py` — for each of 3 rules, hand-built games produce exactly the point values from DESIGN.md point 7; Retro rule never produces a shootout-flagged game.

### Step 1.9 — world.py: root aggregate
**Deps:** 1.2, 1.6, 1.7, 1.8 (hard blocking — integration point)
**HoopR ref:** `hoopsim/models/world.py` (267 lines — `rng`, `season_year`/`phase`/`day`, `teams`/`players` dicts, `schedule`, `free_agents`, `new_pid()`/`new_gid()`, `user_team`/`team()`/`player()`, `sign_player()`/`release_player()`/`transfer_player()`, and critically the **multi-league hook fields**: `mode`, `other_teams`, prospect pipeline placeholder; full `to_dict()`/`from_dict()` envelope w/ `schema_version`).
**Files:** `pucksim/models/world.py`
**Content:** `standings_rule: str` lives on World (per-save selection; config.py holds presets). `other_teams`/`recruits`/`pipeline` fields exist now but stay empty in v1 — per DESIGN.md point 11, so Phase 2 (CHL/NCAA) doesn't need a save-migration rewrite. Keep cap fields minimal — one `salary_cap: int`, no apron/luxury-tax complexity (not implied for v1).
**Done:** `tests/test_world.py` — register teams/players, exercise `sign_player()`/`release_player()`/`transfer_player()`, assert roster consistency both sides; `to_dict()`/`from_dict()` round-trips including dormant multi-league fields.

### Step 1.10 — draft.py, coach.py, tactics.py
**Deps:** 1.4 (otherwise largely independent — can run parallel with 1.6–1.9)
**HoopR ref:** `hoopsim/models/draft.py` (94 lines — `DraftPick`/`DraftClass` w/ `team_on_clock()`/`remaining_prospects()`/`record_pick()`, near-verbatim port); `hoopsim/models/coach.py` (148 lines — `CoachProfile` tendency knobs + `ARCHETYPES` weighted table + `assign_coach()`; hockey knobs: forecheck aggressiveness, PP/PK style, **line-juggling "patience"** per DESIGN.md); `hoopsim/models/tactics.py` (84 lines — `SETTINGS` dict + `Tactics` dataclass w/ `cycle()`/`to_dict()`/`from_dict()`).
**Files:** `pucksim/models/draft.py`, `pucksim/models/coach.py`, `pucksim/models/tactics.py`
**Scope note:** Tactics can be a near-empty stub for MVP (PP/PK styling is v1 work in Step 2.1/2.8) but the file/class must exist now so Team has a stable field type. Coach's "patience" float should be defined now even though nothing consumes it until Step 2.8.
**Done:** `tests/test_draft.py`/`test_coach.py`/`test_tactics.py` — pick-order advancement round-trips; archetype lookup falls back to a default; Tactics round-trips and rejects invalid values.

### Step 1.11 — gen/: procedural player + league generation
**Deps:** 1.4, 1.5, 1.6, 1.7, 1.9 (hard blocking)
**HoopR ref:** `hoopsim/gen/namegen.py` (69 lines), `hoopsim/gen/playergen.py` (139 lines — archetype-driven generate-then-skew-then-calibrate-to-target-overall), `hoopsim/gen/leaguegen.py` (208 lines — `build_world(seed=...)` entry point, `seed_chemistry()` at creation).
**Files:** `pucksim/gen/namegen.py`, `pucksim/gen/playergen.py`, `pucksim/gen/leaguegen.py`
**Content:** `playergen.py` generates both skaters and goalies (goalies rare — ~3/team of ~23); `leaguegen.py`'s `build_world(seed=...)` produces 32 NHL teams (2 conf x 2 div x 8 — real-world league shape, not an invented mechanic) with full rosters, auto-built lines/pairs (calls Step 1.7), assigned coaches (Step 1.10), seeded chemistry.
**Done:** `tests/test_generation.py` — `build_world(seed=42)` produces 32 teams, legal roster sizes, ≥2 goalies, complete lines/pairs per team; same seed → byte-identical rosters twice.

### Step 1.12 — sim/engine.py: shift/event-based resumable generator (5v5 ONLY, MVP scope)
**Deps:** 1.9, 1.11 (hard blocking). **Single-agent step — do not split further**, mirrors why HoopR's engine.py is 1012 lines in one file (the resumable-generator control flow needs one author holding the whole thing in their head).
**HoopR ref:** `hoopsim/sim/engine.py` (1012 lines — `_TeamState` inner class; `GameSim` class; **resumable generator pattern** via `coach_session()` yielding decision-point views, resumed via `.send(orders)`, driven by `play()`'s `next()`/`.send()` loop — build this scaffolding now even with no live-coaching UI yet, per DESIGN.md's note that this pattern will later support "call timeout / pull goalie / set forecheck / juggle lines"; `_SubBreak` marker pattern; `_play_period` loop; fatigue/injury tick functions). `hoopsim/sim/ratings.py` (148 lines — tactic-modifier dicts, `LineupCache`, and the **realization model**: `morale_realization()`/`clutch_realization()`/`familiarity_realization()` — port nearly verbatim, rename rating keys). `hoopsim/sim/boxscore.py` (59 lines — `PBPEvent`, `GameResult` w/ `box: Dict[int, StatLine]` → becomes two dicts `skater_box`/`goalie_box` given the two-shape requirement).
**Files:** `pucksim/sim/engine.py`, `pucksim/sim/boxscore.py`, `pucksim/sim/ratings.py`
**MVP scope constraint:** 5v5 ONLY — no penalty engine, no PP/PK, no goalie-pull, no shootout. Still must: resolve one shift at a time (faceoff → zone entry → shot attempts/rebounds/turnovers → stoppage → line change); track on-ice groups as plain `List[int]`; carry full shot-attempt event context (type, zone, strength-state="5v5" always, rebound/rush flag) per DESIGN.md point 10 so Corsi/Fenwick/xG never need a schema rewrite later; resolve goalie save/goal via shooter-vs-goalie skill gap using the same realization scaling as skaters; resolve faceoffs at period start and after goals (no penalty/icing/offside stoppages yet — those are v1, Step 2.3).
**Note:** OT/shootout (DESIGN.md point 8) is v1 scope, not MVP — MVP needs a clearly-commented provisional tie-break or simple sudden-death placeholder.
**Done:** `tests/test_engine.py` — simulate N games headlessly, box scores reconcile (goals, SOG vs shots_faced); same seed → byte-identical box score; `testkit/run_season.py` (Step 1.14) runs 50+ seeded single games without exception.

### Step 1.13 — sim/season.py + save/serialize.py + save/store.py
**Deps:** 1.12, 1.9
**HoopR ref:** `hoopsim/sim/season.py` (154 lines — `generate_schedule()` circle-method round-robin (direct sport-agnostic carryover per DESIGN.md), `_apply_result()`/`sim_one()`/`advance_one_day()`/`start_season()`, `_heal_injuries()`); `hoopsim/save/serialize.py` (34 lines — `migrate(data)` hook, `world_to_json()`/`world_from_json()`, `save_world()`/`load_world()`, near-verbatim, sport-agnostic); `hoopsim/save/store.py` (60 lines — `saves_dir()`/`slot_path()`/`list_saves()`/`save_game()`/`load_game()`/`autosave()`/`delete_save()`, near-verbatim).
**Files:** `pucksim/sim/season.py`, `pucksim/save/serialize.py`, `pucksim/save/store.py`
**Note:** a flat circle-method round-robin is correct for MVP/v1 per DESIGN.md's explicit carryover callout — true NHL-weighted divisional scheduling is a v2+ fidelity item, not now.
**Done:** `tests/test_season.py` — balanced schedule (every team plays N games, no double-booking); win totals reconcile; standings ordering correct across all 3 rules. `tests/test_save.py` — byte-identical round-trip; round-trip preserves state after partial season.

### Step 1.14 — testkit/ CLI harness: headless N-game/N-season runner
**Deps:** 1.13
**HoopR ref:** none — net-new (HoopR has no CLI harness; loosely inspired by how `tests/test_season.py` drives a season loop programmatically).
**Files:** `testkit/run_season.py` — accepts `--seed`, `--seasons N`, `--games-per-season N`, `--save-path`; prints standings/top-scorers/notable-injuries summary.
**Done:** `python testkit/run_season.py --seed 1 --seasons 3` completes without exceptions, quickly; same seed → identical printed output.

### MVP dependency waves
1. (parallel, deps: 0.1 only) 1.1, 1.2, 1.3, 1.4, 1.5
2. 1.6 (needs 1.3+1.4+1.5)
3. 1.7 (needs 1.6); 1.10 in parallel (needs 1.4 only)
4. 1.8 (needs 1.7) → 1.9 (needs 1.2+1.6+1.7+1.8)
5. 1.11 (needs 1.9, 1.10)
6. 1.12 (needs 1.9, 1.11) — single agent
7. 1.13 (needs 1.12)
8. 1.14 (needs 1.13)

**MVP exit criteria:** `pytest` green across all of `tests/test_{config,rng,stats,attributes,contract,player,team,league,world,draft,coach,tactics,generation,engine,season,save}.py`; `testkit/run_season.py` runs a full 82-game season for all 32 teams without exception.

---

## PHASE 2 — v1 (special teams, goalies, faceoffs/injuries, cap/trades/FA/draft, playoffs+OT/SO, awards, web app)

Larger units than MVP — each still independently assignable, sized like "one subsystem."

### Step 2.1 — Special teams & strength-state engine extension
**Deps:** 1.12 (extends engine.py in place — owner must be comfortable modifying it, not greenfielding)
**HoopR ref:** `hoopsim/sim/ratings.py`'s tactic-to-modifier dict pattern (`DEF_SCHEME`/`DEF_PRESSURE`) is the structural analog for strength-state modifiers.
**Files:** extends `pucksim/sim/engine.py`, `pucksim/sim/ratings.py`; adds `pucksim/sim/special_teams.py` (penalty engine: minor/major/misconduct probability+duration; strength-state transitions; PP/PK unit config — extends Team with `pp_unit_1/2`, `pk_unit_1/2`).
**Open item:** exact strength-state probability tuning is unresolved — implement the mechanism with clearly-commented provisional constants, not final-tuned numbers.
**Done:** `tests/test_special_teams.py` — forced-penalty games show correct 5v4→5v5 strength-state transitions for the right duration; PP scores at a meaningfully higher rate than 5v5 (sanity check, not exact tuning).

### Step 2.2 — Goalies as full system
**Deps:** 1.12, 1.7
**HoopR ref:** `hoopsim/sim/ratings.py`'s realization functions extend directly to a goalie hot-hand factor (same multiplicative, mean-reverting shape).
**Files:** adds `pucksim/sim/goalies.py`; modifies `pucksim/sim/engine.py`, `pucksim/sim/season.py` (rest-day rotation, mirrors `_heal_injuries()`'s per-day-tick placement).
**Content:** starter selection per game (rest-based rotation — no HoopR precedent), hot-hand rolling-performance multiplier, pull-the-goalie trigger (score/time threshold, same trigger-pattern shape as line-juggling in Step 2.8).
**Done:** `tests/test_goalies.py` — starter plays planned game share with backup mixed on back-to-backs; pulled-goalie scenario shows extra-attacker on-ice group and higher empty-net-against rate.

### Step 2.3 — Faceoffs, penalty engine detail, injuries system
**Deps:** 2.1
**HoopR ref:** injury system (`config.BASE_INJURY_RATE`/`IN_GAME_INJURY_RATE`, `Player.injury`, `_injury_check()`/`_injury_severity()`, `season._heal_injuries()`) is a near-verbatim sport-agnostic port per DESIGN.md.
**Files:** modifies `pucksim/sim/engine.py` (post-stoppage faceoffs for icing/offside/penalty, extending period-start-only from 1.12), `pucksim/models/player.py`'s `Injury`.
**Done:** `tests/test_faceoffs.py` — win probability monotonic in center rating gap. `tests/test_injuries.py` — injury rates within a sane band over a season; injured players excluded from lineup selection until healed.

### Step 2.4 — systems/cap.py, systems/trades.py, systems/freeagency.py
**Deps:** 1.5, 1.9 (parallel with 2.1–2.3 — doesn't need engine work)
**HoopR ref:** `hoopsim/systems/cap.py` (186 lines — `payroll()`/`cap_space()`/`over_cap()`/`market_salary()`/`trade_value()`/`can_extend()`/`grow_cap()`/`can_sign()`); `hoopsim/systems/trades.py` (464 lines — `TradeOffer` + AI accept/reject threshold); `hoopsim/systems/freeagency.py` (233 lines — tiered-market-clearing wave pattern).
**Files:** `pucksim/systems/cap.py`, `pucksim/systems/trades.py`, `pucksim/systems/freeagency.py`
**Done:** `tests/test_cap.py`/`test_trades.py`/`test_freeagency.py` — cap math correctness, trade salary-matching legality, AI accept/reject behaves per documented threshold, FA waves clear the market.

### Step 2.5 — systems/draft_system.py, gen/ prospect generation extension
**Deps:** 1.11, 1.10 (parallel with 2.4)
**HoopR ref:** `hoopsim/systems/draft_system.py` (268 lines — draft-order-by-standing, prospect pool, pick flow); `hoopsim/systems/scouting.py` (108 lines — fog-of-war `scout_error`, already stubbed on Player).
**Files:** `pucksim/systems/draft_system.py`; extends `pucksim/gen/playergen.py`
**Open item:** per DESIGN.md point 11, add a `league_origin: str` field on generated prospects (always "none"/generic in v1) as a cheap forward-compatibility hook for the CHL/NCAA eligibility fork in Phase 2 (Step 3.2).
**Done:** `tests/test_draft_class.py` — draft order matches inverse standings (straight order, no lottery — not specified, low-risk default); picks recorded correctly; drafted players get entry-level contracts from Step 2.4's cap system.

### Step 2.6 — sim/playoffs.py + OT/shootout resolution
**Deps:** 1.8, 2.1, 2.2
**HoopR ref:** `hoopsim/sim/playoffs.py` (257 lines — bracket-as-dict-on-world, best-of-7 series, round advancement).
**Files:** `pucksim/sim/playoffs.py`; adds OT/shootout to `pucksim/sim/engine.py` — regular season 3v3 sudden death → shootout (separate skills-competition resolution, not a continuation of normal play), Retro-rule games skip shootout and end in a tie.
**Open item:** playoff seeding structure not specified — default to conference-based top-N (matches real NHL, matches HoopR's own pattern), flagged as a low-risk default.
**Done:** `tests/test_playoffs.py` — bracket advancement correct. `tests/test_ot_shootout.py` — Standard/3-2-1-0 games resolve via 3v3 OT → shootout correctly awarding points per Step 1.8's tables; Retro games never invoke shootout and can end level.

### Step 2.7 — systems/awards.py, legacy.py, momentum.py, offseason.py, development.py
**Deps:** 1.13, 1.6
**HoopR ref:** `hoopsim/systems/awards.py` (108 lines — `compute_awards()`, swap MVP/DPOY/ROY/MIP/All-League for Hart/Norris/Vezina/Calder/Selke); `hoopsim/systems/momentum.py` (111 lines — `update_morale()`/`offseason_reset()`/`game_score()`, generic-framework carryover); `hoopsim/systems/legacy.py` (186 lines — HOF resume-snapshot pattern); `hoopsim/systems/development.py` (73 lines — age curve, `_overall_delta()`); `hoopsim/systems/offseason.py` (178 lines — `archive_season()` orchestration order: awards → career archival → development).
**Files:** `pucksim/systems/{awards,legacy,momentum,offseason,development}.py`
**Done:** `tests/test_awards.py` — award eligibility gating sensible; `tests/test_momentum.py`/`test_offseason.py`/`test_legacy.py` mirror HoopR's test shapes.

### Step 2.8 — Coach line-juggling AI + tactics extension
**Deps:** 2.1, 1.10
**HoopR ref:** no direct analog (DESIGN.md explicitly calls this hockey-specific); closest precedent is `CoachProfile`'s tendency-knob pattern for "patience," and engine.py's crunch-time lineup-reselection trigger shape (`_is_crunch()`/`choose_lineup()`).
**Files:** extends `pucksim/models/coach.py` (patience, already stubbed), `pucksim/sim/engine.py` (reshuffle trigger), `pucksim/models/tactics.py` (forecheck/PP/PK style options).
**Done:** `tests/test_coach_line_juggling.py` — low-patience coach reshuffles more readily than high-patience coach in a controlled same-seed scenario.

### Step 2.9 — FastAPI backend
**Deps:** 1.13 (scaffold-only sub-step can start here); most of 2.1–2.8 (for gameplay endpoints). Recommend splitting: **2.9a** session plumbing + save/load + new-career (deps: 1.13 only), **2.9b** gameplay endpoints (deps: 2.9a + whichever of 2.1–2.7 backs each endpoint).
**HoopR ref:** `hoopsim/web/app.py` (1082 lines, ~81 endpoints — cookie-based session-id pattern, `_world(sid)`/`_user_team(world)` DI helpers, Pydantic request models per action; stated principle: "each route calls the same engine functions the CLI does" — PuckSim mirrors this exactly against `testkit`); `hoopsim/web/session.py` (57 lines — `SessionStore` dict-of-sid-to-World-with-a-lock, near-verbatim); `hoopsim/web/serializers.py` (769 lines — DTO-per-domain-object pattern).
**Files:** `pucksim/web/app.py`, `pucksim/web/session.py`, `pucksim/web/serializers.py`
**Open item, must decide first:** resumable-generator-over-HTTP vs. simpler synchronous session pattern. **Recommendation: simpler** — endpoints call `simulate_game()`/`advance_one_day()` synchronously and return a finished result; defer the generator-over-HTTP pattern until a live-coaching UI feature is actually scoped (v1-late or v2+).
**Done:** `tests/test_web.py` (httpx test client) — new-career, advance-day, standings, save/load, at least one system endpoint (sign a free agent) all work end-to-end.

### Step 2.10 — React/TypeScript frontend scaffold + core screens
**Deps:** 2.9 (scaffold-only work can start once endpoint shapes are agreed, in parallel with 2.9's implementation)
**HoopR ref:** `HoopR/frontend/` shape — `package.json` deps (`@tanstack/react-query`, `@tanstack/react-table`, `react`/`react-dom`, dev: `vite`/`typescript`/`oxlint`/`@vitejs/plugin-react`), file layout (`src/App.tsx`, `src/api.ts`, `src/theme.tsx`, `src/ui.tsx`, `src/main.tsx`).
**Files:** `frontend/` — scaffold + roster/lines editor (reflecting Step 1.7's flexible on-ice-group lists), standings table (3 rule variants selectable), box score view (skater/goalie two-shape tables), schedule/sim-day controls.
**Note:** substantial step — recommend re-splitting into 3-4 screen-sized sub-tasks once backend shapes are locked.
**Done:** `npm run build` succeeds; `npm run dev` app can create a career, view roster/lines, advance a day, view a box score against a running backend.

### v1 dependency structure
- Parallel group A (deps: MVP only): 2.4, 2.5
- Sequential spine: 2.1 → 2.2 → 2.3 → 2.6 (2.6 also needs 2.2)
- Parallel with spine once 2.1 lands: 2.8
- 2.7 most naturally sequenced after 2.1–2.3 (real stat categories to compute over), though could start earlier
- Web: 2.9 after enough systems exist to expose; 2.10 after 2.9's shapes stabilize

**v1 exit criteria:** full pytest suite green; a complete season (regular season + playoffs + draft + FA + offseason) playable end-to-end via FastAPI+React for a user-controlled team, with save/load working throughout.

---

## PHASE 3 — v2+ (kept at design-doc-level granularity — re-plan once v1 ships and tuning feedback exists)

### Step 3.1 — NHL CBA fidelity pass
**Deps:** 2.4 (extends, doesn't greenfield)
**HoopR ref:** `hoopsim/systems/cap.py`'s soft-cap/tax/exception pattern is the structural precedent for the *mechanism* of adding cap wrinkles.
**Files:** extends `pucksim/systems/cap.py`, `pucksim/models/contract.py`; adds `pucksim/systems/waivers.py` (or similar).
**Done:** arbitration/offer sheets/LTIR/waivers/ELC each have dedicated tests; v1 saves migrate cleanly via the `schema_version` hook from Step 1.13.

### Step 3.2 — Phase 2 league expansion: NCAA + CHL feeder leagues
**Deps:** 2.5, World's dormant `other_teams`/`recruits`/`pipeline` fields (Step 1.9)
**HoopR ref:** `hoopsim/systems/college_offseason.py`, `recruiting.py`, `collegefin.py`, `hoopsim/gen/collegegen.py`, `hoopsim/sim/college_tourney.py` — HoopR's own dual-league pattern is the strongest, most literal pattern-reuse opportunity in the whole plan.
**Files:** `pucksim/systems/junior_offseason.py`/`ncaa_offseason.py`, `pucksim/gen/juniorgen.py`/`ncaagen.py`, extends `draft_system.py`.
**Done:** CHL/NCAA mutual-exclusivity fork enforced via `league_origin` (Step 2.5); prospects flow from both feeders into the NHL draft class; v1 saves load cleanly with `other_teams`/`recruits` empty until opted in.

### Step 3.3 — Phase 3 league expansion: European pro + junior leagues
**Deps:** 3.2
**Files:** `pucksim/systems/europe_offseason.py`, `pucksim/gen/europegen.py`.
**Done:** European junior/pro leagues generate draft-eligible import prospects into the same NHL draft pipeline, no schema rewrite.

---

## Cross-cutting open items (flagged per-step above, consolidated for visibility)

1. Concrete skater vs. goalie rating list — Step 1.4's first sub-task.
2. Exact strength-state probability tuning — Step 2.1, provisional values, iterate post-launch.
3. Resumable-generator-over-HTTP vs. simpler web session pattern — Step 2.9, recommend simpler for now.
4. xG model weighting — Step 1.12 establishes event-context shape only; real tuning pass scheduled once a large simulated shot corpus exists (v1-late/v2-early).
5. Default standings rule for new leagues — "Standard," reversible/config-only (Step 1.1).
6. `scripts/` vs `testkit/` naming — decided: `testkit/` (Step 0.1).
7. Single `Player` dataclass vs. `Skater`/`Goalie` split — Step 1.6's first sub-task; recommend single dataclass.
8. Playoff seeding (conference vs. league-wide) and draft order (straight vs. lottery) — both defaulted to the real-NHL-shaped choice (Steps 2.5/2.6), provisional.

## Critical HoopR reference files (highest-value to read before implementing)

- `hoopsim/sim/engine.py` — resumable-generator pattern, `_TeamState`, realization-scaled resolution, fatigue/injury ticks. Template for the largest/most novel MVP step (1.12).
- `hoopsim/models/world.py` — root-aggregate pattern (seedable RNG, dormant multi-league fields, full serialization envelope). Must mirror to keep Phase 2/3 expansion schema-compatible from day one.
- `hoopsim/models/team.py` — roster/chemistry/rotation-helper pattern reshaped into PuckSim's flexible line/pair lists — the single biggest structural deviation from HoopR in the models layer.
- `pyproject.toml` — packaging/test-config template, the hard prerequisite for every other step.
- `hoopsim/web/app.py` — FastAPI route/session/serializer pattern, "web calls the same engine functions as the CLI" principle.
