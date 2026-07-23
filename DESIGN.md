# PuckSim — NHL Franchise Simulation: Design Document

## Context

[HoopR](file:///Users/hank/HoopR) is a working, well-tested basketball franchise sim (NBA + college), ~20K LOC, with a proven architecture: layered Python domain model, possession-by-possession game engine, and both a Rich terminal UI and a FastAPI/React web layer. The goal is a hockey equivalent — **PuckSim** — starting with NHL only, but architected so it can later grow to American college / Canadian major junior, and eventually European pro & junior leagues, the same way HoopR grew from NBA-only into NBA + college.

This document is the output of a planning conversation, not an implementation. Nothing gets built until this is reviewed and a follow-up session kicks off actual coding.

## Decisions made in this planning session

- **Codebase**: Fresh, standalone repo (`PuckSim`, package `pucksim`). Not a fork of HoopR, not a shared library — HoopR's *patterns* get reused, not its code. The two sports diverge enough at the engine level (lines/shifts/special-teams/goalies vs. 5-on-court possessions) that sharing an engine would mean fighting basketball-shaped assumptions. A shared "generic franchise sim" library was considered and rejected for v1 — worth revisiting only if a third sport ever gets added.
- **Stack**: Python backend for all domain/sim logic (proven fit — HoopR already demonstrates it), **FastAPI + React/TypeScript web UI as the primary interface from day one** — not TUI-first like HoopR's actual build order. You rarely touch a terminal, so the browser app is the real product from the start, not an afterthought bolted on later. A thin CLI/script harness will exist purely for internal testing (headless season simulation, pytest) — never a user-facing surface.
- **Deployment**: Local single-user app, same operating model as HoopR today — `pip install -e .`, local dev server, JSON save files on disk. No accounts, auth, or database. Revisit only if you ever want to share it with other people.
- **v1 cap/contract fidelity**: Simplified, HoopR-style model (single cap number, basic contract terms, trades, FA). Real NHL CBA detail — arbitration, offer sheets, LTIR cap relief, waivers, one-way/two-way entry-level contracts — deferred to a later pass once the core loop works.
- **Fighting/enforcers**: Out of scope for v1. Revisit as an optional flavor system later if desired.

## What carries over directly from HoopR

These are sport-agnostic patterns validated by a working codebase — reuse the *shape*, rewrite the *numbers*:

- **Layered architecture**: `models` (pure data, no logic) → `sim`/`systems` (game logic, rules) → `web` (rendering). Strict one-way imports keep the engine UI-agnostic and unit-testable without spinning up a server.
- **World as single root aggregate**: one object holds all league state (teams, players, schedule, RNG). A single seedable RNG lives in `World` so any save reproduces identical sim results.
- **25–99 rating scale + archetypes**: position-specific templates with signature strengths/weaknesses (HoopR's "Floor General," "Rim Protector," etc.) instead of pure random noise per rating. Directly portable to hockey positions.
- **Age-based development curves**: growth phase (young) → plateau (peak) → decline (veteran), with a fuzzed "potential" ceiling (scout error) driving fog-of-war on prospects.
- **Realization model**: morale × chemistry × clutch as multiplicative factors that scale the *skill gap* between opposing ratings, not the base rate. Clean, sport-agnostic way to make players play up or down without ever exceeding their ratings.
- **Season phase machine**: preseason → regular season → playoffs → draft → free agency → offseason, with a circle-method round-robin schedule generator.
- **Draft / free-agency waves / trade value formula**: tiered market clearing (top free agents sign first, market cools per wave), age/upside/contract-surplus-adjusted trade valuation, AI accept/reject thresholds. All sport-agnostic scaffolding.
- **Injuries, awards, legacy/Hall of Fame**: generic frameworks (severity + duration; end-of-season award computation; career milestone tracking) that just need hockey's award names (Hart, Norris, Vezina, Calder, Selke) and stat thresholds swapped in.
- **JSON save files with schema versioning + migration hook**: no database needed for a local single-user app; matches the "keep it simple" deployment decision above.
- **Multi-league `World` fields**: HoopR's `mode` flag + secondary team pool (`other_teams`) + prospect pipeline is *exactly* the shape needed for the future CHL/NCAA/Europe phases — this pattern should be designed into `World` from the start even though only NHL is populated in v1.
- **Coach archetypes**: bundles of default tactics + rotation shape + in-game behavior weights, portable concept (forecheck aggressiveness, PP/PK style, etc. instead of pace/motion-vs-iso). Extend this pattern with a hockey-specific behavior HoopR doesn't need: a coach "juggling the lines" — reshuffling forward line/D-pair combinations mid-game or between games when the team is trailing or the current combinations are running cold, distinct from simple substitution logic. Coach archetype should carry a "patience" parameter governing how quickly/aggressively it reaches for the blender.

## What's fundamentally different for hockey (net-new systems)

| # | System | Why it's not a basketball port |
|---|--------|--------------------------------|
| 1 | **Line-based lineups** | Forward lines (LW-C-RW × 4) + D-pairs (× 3) + goalie, not a flat 5-man rotation. Line chemistry/combos are a bigger strategic lever than basketball's individual minutes targets. **v1 assumption**: lines/pairs change as atomic 3F/2D units. The on-ice-group data structure should still be modeled as a flexible list of players (not a hard-coded `Line` object) so a later pass can represent players "caught" on the ice for an extended shift, or mixed groups left over when a PP/PK unit has to revert to 5v5 mid-shift, without a data model rewrite. |
| 2 | **Shift-based ice time** | ~45s shifts with on-the-fly and stoppage changes, not quarter-length minutes. Fatigue/recovery needs to model shift length and shift-count, not MPG. |
| 3 | **Special teams & strength states** | 5v5, 5v4/PP, 4v5/PK, 4v4, 3v3(OT), 5v3 — an entire penalty/strength-state layer with zero basketball analog. Needs a penalty engine (minor/major/misconduct) and separate PP/PK unit configuration. |
| 4 | **Goalies** | A single-player position with outsized game impact (closer to a starting pitcher than any basketball role). Separate rating category, starter/backup rotation, hot-hand/fatigue, and the "pull the goalie" late-game mechanic. |
| 5 | **Faceoffs** | Discrete contested event (by center rating) after every stoppage and to start every period — no basketball equivalent beyond the opening tip. |
| 6 | **Continuous flow, not discrete possessions** | HoopR simulates ~100 clean possessions/game. Hockey needs an event model built on zone entries/exits, shot attempts (on-goal/missed/blocked), rebounds, and takeaways/giveaways instead. |
| 7 | **Standings points system** | Not simple win/loss like the NBA — and unlike most HoopR config values, this should be a **user-selectable league rule** (`config.py` toggle), not a single hardcoded scheme: (a) **Standard** — 2 pts regulation/OT/SO win, 1 pt OT/SO loss, 0 pts regulation loss (current real-world NHL); (b) **Retro** — 2 pts win, 1 pt tie, 0 pts loss, no shootout at all (ties stand, pre-2005 NHL style); (c) **3-2-1-0** — 3 pts regulation win, 2 pts OT/SO win, 1 pt OT/SO loss, 0 pts regulation loss (a scheme advanced-stats/analytics commentators often propose to reward regulation wins more). All three affect standings math only, not the OT/shootout simulation itself except that Retro skips the shootout entirely. |
| 8 | **OT / shootout** | Regular season: 3-on-3 sudden death → shootout (a separate skills-competition resolution model, not a continuation of normal play), unless Retro standings rules are selected (see above), in which case games can end in ties. Playoffs: full 5v5 sudden-death periods instead. Two different mechanics HoopR has no analog for. |
| 9 | **Two box-score shapes** | Skaters (G/A/P/+-/PIM/SOG/hits/blocks/FO%) vs. goalies (GAA/SV%/shutouts) are structurally different, unlike basketball's one StatLine shape for everyone. |
| 10 | **Advanced/analytics stats** | Hockey has a strong "advanced stats" culture that basketball's box score doesn't need to replicate: **Corsi** (all shot attempts for/against, typically 5v5) and **Fenwick** (unblocked shot attempts for/against) as shot-attempt-differential possession proxies, plus **xG/xA** (expected goals/assists — a per-shot scoring probability model based on shot type, location, strength state, and rebound/rush context, summed per player/team). This requires the shot-attempt event in the sim engine to carry enough context (type, zone, strength state, rebound flag) to score an xG value at generation time, not just resolve make/miss. |
| 11 | **Feeder-league eligibility fork** (future-phase concern, flag now) | Canadian major junior (CHL) players forfeit NCAA eligibility by playing major junior — the two paths are mutually exclusive, unlike basketball's overlapping college/G-League routes. Doesn't block v1, but the prospect-pipeline data model should leave room for this fork before Phase 2 (NCAA/CHL) is designed in earnest. |

## Proposed architecture

```
PuckSim/
├── pucksim/
│   ├── config.py            # All tunables, one file (HoopR pattern)
│   ├── rng.py                # Seedable, save-restorable RNG
│   ├── models/                # Pure data layer
│   │   ├── player.py          # Skater/goalie attributes, stats, injury
│   │   ├── team.py            # Roster, lines, pairs, cap
│   │   ├── world.py            # Root aggregate + multi-league hooks
│   │   ├── attributes.py      # Ratings, archetypes, composites
│   │   ├── contract.py        # Simplified v1 cap/contract terms
│   │   ├── league.py          # Game/Phase/Schedule
│   │   ├── draft.py, stats.py, coach.py, tactics.py
│   ├── gen/                    # Procedural generation (players, names, league)
│   ├── sim/                    # Game simulation engine
│   │   ├── engine.py            # Shift/event-based simulator (resumable generator)
│   │   ├── special_teams.py     # PP/PK/strength-state logic
│   │   ├── goalies.py            # Goalie performance model
│   │   ├── boxscore.py, season.py, playoffs.py, ratings.py
│   ├── systems/                 # Cap, trades, free agency, draft, development,
│   │                             # offseason, injuries, awards, legacy, momentum
│   ├── save/                    # JSON serialize + versioned migration
│   └── web/                     # FastAPI app — the primary interface
├── frontend/                    # React + TypeScript + Vite SPA (primary UX)
├── scripts/ or testkit/         # CLI harness — headless sim runs, debugging only
├── tests/                       # pytest, mirroring HoopR's coverage areas
└── docs/                        # ENGINE_BREAKDOWN.md, ARCHETYPES.md equivalents
```

Key deviation from HoopR's actual build order: HoopR shipped Rich-terminal-first and added FastAPI/React later as a mirror. PuckSim inverts that — **web is the primary target from the start**, and the CLI is a developer tool, not a product surface. The `sim`/`systems`/`models` layers stay identical in spirit either way (engine never imports UI), so this doesn't change the core architecture, only which renderer gets built first.

## Simulation engine design

Recommend a **shift/event-based resumable generator**, the hockey analog of HoopR's possession generator:

- Game is simulated as a sequence of **shifts** (not possessions). Each shift resolves a sequence of events: faceoff → zone entry attempts → shot attempts/rebounds/turnovers → possible stoppage (goal, penalty, icing, offside) → line change.
- **On-ice group representation**: model the on-ice unit as a plain list of player IDs (5 skaters + goalie), not a hard `Line`/`Pair` object. v1 always populates it by sending out an intact 3F+2D line/pair together, but keeping the underlying representation unit-agnostic means a later pass can produce genuinely mixed groups (a player "caught" for an extra-long shift, or the leftover mix when a PP unit has to revert to 5v5 mid-shift) without changing how the rest of the engine consumes on-ice state.
- **Strength state** (5v5, PP, PK, OT) is tracked as game state that gates which events are possible and re-weights probabilities (like HoopR's tactical modifiers, but driven by penalty state instead of user tactic choice).
- **Penalty engine**: per-shift penalty probability (by discipline/aggression rating and tactic), minor (2 min) vs. major (5 min) vs. misconduct, drives strength-state transitions.
- **Goalie resolution**: every shot attempt run through shooter-skill vs. goalie-skill gap (same "realization" scaling as HoopR: morale × chemistry × clutch, plus a goalie-specific hot-hand factor) to decide save/goal/rebound.
- **Shot-attempt event carries analytics context**: type (wrist/slap/one-timer/etc.), zone/location, strength state, and a rebound/rush flag get attached at generation time so xG can be scored per attempt and Corsi/Fenwick can be tallied as a simple filter over the same event stream, rather than bolted on as a separate stats pass.
- **Line-juggling as a coach-AI trigger**: coach archetype's "patience" parameter watches score state / line effectiveness (e.g. on-ice goal differential per combo) and can trigger a reshuffle of forward lines/D-pairs between periods or during a stoppage — a new coach behavior HoopR's substitution-only logic doesn't need.
- Same resumable-generator trick HoopR uses for live coaching (`yield` a decision point, resume with orders) — applies naturally to a "call a timeout / pull the goalie / set forecheck / juggle lines" live-coaching interface later, keyed to stoppages instead of crunch-time possessions.

## Multi-league expansion (future phases, not v1 — design hooks only)

Mirror HoopR's `World.mode` + secondary team pool + pipeline pattern:

- **Phase 2**: NCAA + Canadian major junior (CHL — OHL/WHL/QMJHL) as feeder leagues into the NHL draft. Needs the eligibility-fork noted above (major junior vs. NCAA are mutually exclusive paths for a prospect) baked into the prospect data model before this phase starts.
- **Phase 3**: European pro (KHL/SHL/Liiga-style leagues) and European junior leagues, plus draft-eligible European imports.
- None of this needs to be built now — it needs `World` and the draft/prospect pipeline shaped so these leagues can be added as new team pools later without a schema rewrite, exactly how HoopR's college mode bolted onto its NBA-only original design.

**v1 stand-in — reserved prospects (`systems/prospects.py`).** Having *no* development tier at all turned out not to be a neutral omission but an economic bug: with nowhere to send a draftee, every pick either took an NHL roster spot immediately at an entry-level cap hit (~150 sub-replacement teenagers a year, reaching 41% of all rostered players on entry-level deals and collapsing league payroll from ~94% of the cap to ~62% within three seasons) or was deleted outright by the free-agent cull, leaving the draft feeding nothing into the league. So v1 carries a minimal reserve *status*: a drafted player who isn't NHL-ready keeps developing, is protected from the cull, and can't be signed until a development window — staggered by draft position, so a class trickles in over several seasons — elapses. It is deliberately not a league: no minor-league team, roster, schedule, stats, no junior/AHL/NCAA/Europe distinction, and no midseason call-up. Phase 2/3 replace the status with real feeder leagues; until then it's what keeps the draft → development → NHL pipeline (and therefore the salary cap's pressure) intact.

## Does Python still make sense?

Yes, for the domain/sim logic — nothing changes that conclusion. The part of the original question that actually needed rethinking was the *interface*, not the *language*: HoopR is terminal-first, and the terminal is rarely used day-to-day. That's now resolved by making the FastAPI + React web app the primary interface from day one rather than porting HoopR's TUI-first build order. Python remains the right call for the engine itself because:

- HoopR already proves the pattern at this exact scope (dataclasses, JSON saves, possession/shift-level simulation) with no performance ceiling in sight — a hockey game has more event types per game (shifts, faceoffs, shot attempts, penalties) but is still orders of magnitude below where Python's speed would matter.
- FastAPI (Python) + React/TypeScript (frontend) is a completely standard, proven split — the backend language and the "is there a browser UI" question are independent decisions.
- There's already a working mental model and reusable instincts from building HoopR in Python; switching languages would mean re-deriving patterns (dataclass modeling, generator-based resumable simulation, JSON serialization) that already work, for no functional gain.

## Phasing plan

1. **MVP**: `models` + `sim` core only — player/team/world data model, shift-based game engine (5v5 only, no special teams yet), season schedule + standings with NHL points system, basic box scores. Validated via pytest + a CLI script that simulates N games/seasons headlessly. No UI yet.
2. **v1**: Add special teams (PP/PK/strength states), goalies as a full system, faceoffs, injuries, simplified draft/free agency/trades/cap, playoffs + OT/shootout, awards. Stand up the FastAPI + React web app as the primary way to actually play a season.
3. **v2+**: NHL CBA fidelity pass (arbitration, offer sheets, LTIR, waivers, ELC structure), then Phase 2/3 league expansion (NCAA/CHL, then Europe).

## Open items for the next working session

- Concrete rating list for skaters vs. goalies (analogous to HoopR's `attributes.py` — needs its own pass, not decided here).
- Exact strength-state probability tuning — will need iteration once the engine exists, not a design-time decision.
- Whether the web app should be built with the same "resumable generator over HTTP" session pattern HoopR uses, or something simpler given no live-coaching feature in MVP.
- xG model weighting (how much shot type/location/strength-state/rebound context each contribute to expected-goal value) needs actual tuning once real shot-attempt data exists from the sim — design says *what* context to capture, not the exact formula.
- Default standings rule (Standard/Retro/3-2-1-0) for new leagues — should have a sensible default even though it's user-selectable.
