# Prospect development round — plan

**Started 2026-07-23.** Delivers DEVPLAN.md Step 3.2 ("NCAA + CHL feeder leagues") in its
*abstract-tier* form, plus the ELC/slide rules and the undrafted/international pathways that
step never scoped.

## What exists today, and why it isn't enough

`pucksim/systems/prospects.py` (88 lines, shipped in PR #61) is a deliberate stand-in. A drafted
player who isn't NHL-ready is *reserved*: unsignable until a development window elapses, staggered
purely by **draft position** (1st overall: 0 seasons, top ten: 1, rest of round one: 2, later
rounds: 3). It is a status, not a place. It has no tiers, no ages, no contracts, no way for a
prospect to develop faster or slower than the schedule his draft slot handed him, and no path into
the league for anyone who wasn't drafted.

Its own module docstring names the gaps: *"no distinction between a prospect in junior vs. the AHL
vs. the NCAA vs. Europe."* That's what this round closes.

The reason it exists at all is economic, and that constraint still binds. Before it shipped, every
draft signed ~150 prospects (median overall 52 against a league median of 67) straight onto NHL
rosters at entry-level prices; within three offseasons 41% of the league was on ELCs and payroll
had fallen from ~94% of the cap to ~65%. **Every change in this round has to leave that guardrail
standing.** Phase 7 re-runs the diagnostic that proved it.

## Scope decision (user, 2026-07-23): abstract tiers, not simulated leagues

CHL / NCAA / AHL / Europe are development **tiers** a prospect occupies. They drive age curves,
growth rate, ELC eligibility, the slide rule, and who may be signed — but there is no schedule, no
game simulation, no standings, and no junior/AHL box score. A prospect gets a synthetic season
stat line each year for flavor, generated from ratings the same way `prospectgen._pre_draft_bio`
already does.

This is not a compromise shape; it's the shape that makes the asks cheap. Everything the user
asked for — somewhere to develop, age curves, CHL-vs-NCAA assignment, ELC years not burning, the
AHL for older prospects, a UDFA/international path — is a function of *which tier and how old*,
not of *what happened in Tuesday's game in Moose Jaw*. Simulating those leagues can be layered on
later (DEVPLAN Step 3.2's original framing) without changing any interface built here.

## Where the state lives

**`Player.development: Optional[Dict]`** — one JSON-native dict, `None` for anyone not in the
development system. Follows the codebase's own established idiom for this exact situation
(`Player.draft`, `Player.pre_draft`, `World.bracket`, `World.history` are all plain dicts owned by
a single module, precisely so they round-trip through `to_dict`/`from_dict` with zero extra
serialization code). `systems/prospects.py` is its sole owner.

```python
{
  "tier": "chl",          # config.DEV_TIERS
  "seasons": 2,           # total seasons developing, all tiers
  "tier_seasons": 2,      # seasons in the CURRENT tier (drives NCAA's 4-year eligibility)
  "rights_tid": 4,        # team holding this player's rights; None = undrafted/open (UDFA track)
  "rights_expire": 2034,  # season year the rights lapse
  "line": {...},          # synthetic season stat line, flavor only
}
```

**No `Team.prospects` list.** Unlike `Team.roster` — which is dual-written with `Player.team_id`
because lineups, chemistry, and per-shift lookups all iterate it — a reserve list has no ordering
or lineup semantics and is never touched inside a game. `prospects.team_prospects(world, tid)`
derives it from `development["rights_tid"]` in one pass over a few hundred players. One source of
truth, no second sync invariant to keep.

**`Contract.slide_years: int = 0`** — how many times this ELC has slid. Additive, defaults to 0 on
old saves.

A prospect keeps `team_id = None` (they are not on the NHL active roster, and `cap.payroll` sums
over `Team.roster`, so a signed prospect's ELC correctly costs no cap space — matching the real
rule that junior/AHL contracts don't count against the NHL cap). They stay in `world.free_agents`
and continue to be filtered out at the five existing consumer sites via `is_reserved_prospect()`,
which is preserved as the seam it already is.

## The tiers

| Tier | Ages | Requires | Notes |
|---|---|---|---|
| `chl` | 16–19 | `league_origin == "chl"` | Hard age-out at 20. **Permanently forfeits NCAA eligibility** (DESIGN.md point 11's mutual-exclusivity fork — the one real structural difference from basketball's overlapping college/G-League routes). |
| `ncaa` | 18–23 | origin not `chl`; max 4 seasons in tier | Slower, steadier growth; four years of eligibility, then a college free agent. |
| `ahl` | 20+ (18+ if not CHL-origin) | **a signed contract** | The pro-development tier, and the answer to "AHL for older prospects." A CHL-origin 18/19-year-old is barred — the real CHL–NHL transfer agreement sends him back to junior or keeps him in the NHL, nothing in between. |
| `europe` | 18+ | `league_origin == "europe"` | Unsigned European draftees develop at home. |

Age-out at `MAX_PROSPECT_AGE`: a player past it leaves the development system entirely and becomes
an ordinary free agent, where `offseason.cull_free_agents` washes him out if he never became an NHL
player. Most late-round picks never play a game; that's correct.

## ELC rules (the "don't burn years" ask)

Modeled on the real CBA, simplified only where the sim has no equivalent concept.

- **Length by signing age**: 18–21 → 3 years, 22–23 → 2, 24 → 1, 25+ → not entry-level at all
  (a normal market contract). Replaces today's flat `config.ROOKIE_CONTRACT_YEARS = 3`.
- **The slide**: a player who is 18 or 19 at the start of a season and plays fewer than
  `ELC_SLIDE_GAMES` (10) NHL games has his ELC **slide** — the year is not consumed, the deal
  extends by a year, `slide_years` ticks. Because age advances one year per offseason, the 18-or-19
  condition self-limits to **two slides**, exactly as the real rule does: sign at 18, slide twice,
  the 3-year deal starts at 20.
- **Where it bites**: `offseason.expire_contracts` today only walks `Team.roster`, so an
  off-roster prospect's contract never advances at all — an accidental *infinite* slide. This round
  makes the slide explicit and bounded, and makes a 20-year-old sitting in the AHL burn a year the
  way he should.

## Pathways in

1. **Drafted** — `make_pick` assigns a tier from age + `league_origin` instead of handing out a
   pick-number window. Rights expire (`PROSPECT_RIGHTS_YEARS`), so sitting on a prospect forever
   isn't free.
2. **Undrafted (UDFA)** — an undrafted prospect no longer just waits to be culled: he gets a tier
   with `rights_tid = None`, keeps developing on his own, and **re-enters the next draft** if still
   age-eligible. Develop past the NHL-ready bar while unclaimed and he's an open free agent any
   team can sign. This is the "undrafted stud" story, and it's the main reason to give prospects
   real age curves rather than a schedule.
3. **International** — each offseason generates a small pool of age 22–27 European pros
   (`league_origin = "europe"`) at real NHL-caliber ability, entering free agency directly. The
   KHL/SHL import path.

## Age curves

`development._overall_delta` currently reads ice time from `Player.season` — a prospect has
`gp == 0`, so **every prospect in the league develops at the same flat 0.6× rate** regardless of
age, tier, or anything else. Tier becomes the ice-time/competition proxy instead:

- Junior at 17–19 is productive; junior at 20 is stagnation (nothing left to learn there).
- NCAA is steady but slower — fewer games, more strength work.
- The AHL at 20–23 is the strongest pro development available.
- Past a tier's age band, growth collapses. Prospects who stall lose potential earlier than the
  current `PEAK_AGE_LOW + 1` convergence allows, so busts actually bust.

Each prospect also gets a synthetic season line per year (`prospectgen.development_season_line`),
generated from his ratings at his tier's real season length and difficulty, so a team can look
at what its 19-year-old did in junior rather than only at a rating moving. Flavor; never read
back into a rule.

All of it stays inside the existing conservation rule (`development.py`: growth's only source is an
unmet gap to potential) and the project's `[[feedback_no_upweighting]]` principle — these are
*rates of approach to an existing ceiling*, never a bonus above a rating.

## Phases

| # | Branch | Contents |
|---|---|---|
| 0 | `prospect-dev-plan` | This document. |
| 1 | `prospect-model-layer` | `Player.development`, `Contract.slide_years`, `config` tier constants, serialization + old-save defaults. |
| 2 | `prospect-tiers-elc` | `systems/prospects.py` rewritten: tier eligibility/assignment, ELC length + slide, rights expiry. `is_reserved_prospect` seam preserved. |
| 3 | `prospect-dev-curves` | Tier- and age-aware development in `systems/development.py`. |
| 4 | `prospect-draft-offseason` | `make_pick` assigns tiers; offseason signs ELCs, promotes the ready, ages out the rest. |
| 5 | `prospect-udfa-intl` | Undrafted pathway + draft re-entry; international FA pool generator. |
| 6 | `prospect-web-ui` | `/roster/prospects` + a Prospects screen; tier/ELC/ETA in the player modal. |
| 7 | `prospect-balance` | 12-season sweep: payroll % of cap, ELC share, per-tier populations, best available FA. |

## Measurements

Method (from PR #61): `offseason.run_offseason()` forward 12 seasons across several seeds,
watching payroll as a % of cap, the share of rostered players on entry-level deals, the
per-tier prospect populations, and the best available free agent.

### Baseline on `main` before Phase 2 (seeds 1 / 7 / 42)

| | season 1 | season 3 | season 6 | season 12 |
|---|---|---|---|---|
| payroll % of cap | 93–96% | 92–97% | 94–97% | 94–95% |
| share of league on ELCs | 3–4% | **0%** | **0%** | **0%** |

The payroll number was healthy and the ELC number was the tell: **the draft fed nothing
into the league.** A reserved prospect's development window expired straight into
`cull_free_agents`, so within two simulated offseasons not one entry-level player was on an
NHL roster, and none ever would be again. The economy looked fine because it had quietly
stopped having a talent pipeline at all.

### After Phase 2 (same seeds)

| | season 1 | season 3 | season 6 | season 12 |
|---|---|---|---|---|
| payroll % of cap | 93–96% | 90–96% | 89–96% | 86–91% |
| share of league on ELCs | 4–5% | 3–6% | 4–6% | 4–6% |
| prospects (CHL / NCAA / AHL / Europe) | 26/24/58/12 | 40/71/204/17 | 38/95/347/43 | 41/79/325/25 |

The pipeline delivers now, and all four tiers stay populated. The AHL holds the largest
share by construction — it spans ages 20–25, against junior's two-year post-draft window and
college's four — which is what "the AHL is for older prospects" looks like in aggregate.

**Known drift at the end of Phase 2:** payroll trended 3–5 points below baseline by season
12 (worst observed seed: 86%). Left untuned on purpose — Phase 3's development curves move
the very quantity being measured, so re-centering first would have been wasted work (the
reasoning PR #59 applied to the archetype round's pivots).

### After Phase 3 (same seeds)

| | season 1 | season 3 | season 6 | season 12 |
|---|---|---|---|---|
| payroll % of cap | 93–96% | 90–96% | 92–97% | 91–97% |
| share of league on ELCs | 4–5% | 4–5% | 5–6% | 5–7% |
| prospects (CHL / NCAA / AHL / Europe) | 23/28/63/8 | 42/69/198/21 | 36/97/307/34 | 41/83/292/31 |

The Phase 2 drift closed on its own, without a tuning pass: payroll now holds **89–97%**,
at or above the pre-round baseline, and the ELC share holds 4–7% instead of collapsing to
zero. The most likely mechanism is the stagnation rule — prospects who stall now lose
ceiling, age out, and get culled, so the pipeline carries fewer permanent occupants and the
free-agent market stays stocked with players teams actually want to buy.

Phase 7 therefore has much less to do than planned. It should confirm these numbers across
more seeds rather than re-center anything.

### After Phase 5 (same seeds)

| | season 1 | season 3 | season 6 | season 12 |
|---|---|---|---|---|
| payroll % of cap | 93–96% | 93–96% | 95–97% | 95–97% |
| share of league on ELCs | 4–5% | 5% | 6–7% | 7–9% |
| prospects (CHL / NCAA / AHL / Europe) | 45/49/18/19 | 89/115/122/35 | 97/187/189/40 | 101/176/168/37 |

The best economy of any configuration measured, baseline included, and the first one where
all four tiers are genuinely populated — junior in particular went from ~35 to ~95, because
draft classes now arrive at the right age (see below).

Ten-season pathway yield, three seeds: **20–50 undrafted players reach NHL rosters**, almost
all European imports, including genuine top-six talent (a 79-, 87- and 76-overall forward
across the three). The undrafted-domestic route delivers 0–1 per decade at the current pool
size; see the trade-off note below.

## Two bugs this phase's own tests caught

Recorded because both were silent and neither was hypothetical:

1. **Every European prospect was being sent to a US college.** The NCAA gate only checked
   "didn't play major junior," so Europeans passed it, and college outranks Europe in the
   preference order for a teenager. Origin now gates college the same way it gates junior.
2. **The AHL swallowed the entire system.** Preferring the closest-to-NHL eligible tier put
   ~85% of all prospects in the AHL the moment their team signed them — college recruits
   never saw a campus. Eligibility and preference are now separate: the AHL is *eligible*
   from 18 for non-junior players but only *preferred* from `AHL_PREFERRED_AGE` (20).

A third, found by diagnostic rather than test: teams were signing ~90% of every draft class
immediately, because "do we believe in him?" was the only test. Signing now also requires a
reason to spend the slot *now* — he's within `ELC_SIGN_READINESS_GAP` of the NHL, or this is
the last offseason before he walks.

Phase 5 added two more, both found by measuring rather than by testing:

4. **Draft classes were generated uniformly across ages 18–21.** Real classes are
   overwhelmingly 18-year-olds, and the uniform draw broke the age curves in two ways at
   once: a prospect drafted at 20 has almost no runway before `PROSPECT_STAGNATION_AGE`
   erodes his ceiling, and he skips junior entirely since the CHL tier ends at 19. Measured
   over ten seasons, undrafted players were leaving the system at a median age of 24 having
   entered college at 20 with their potential already ground down. Junior held ~35 players
   league-wide. Weighted toward 18, it holds ~95 and the economy improved on every metric.
5. **Being open to the market meant being exposed to the cull.** An undrafted 21-year-old
   in the middle of his junior year of college was deleted from the league for not yet being
   finished. A college player isn't a free agent while enrolled — `is_open_to_all` now
   excludes the amateur tiers, so he reaches the market at 22–23 when his eligibility ends,
   which is exactly when real college free agents become worth something.

Phase 6 (the UI) then found a sixth, and it was the most consequential of the round:

6. **Prospects arrived from the generator already under contract.** `playergen` prices a
   contract onto every player it makes, because its main caller (`leaguegen`) is building an
   already-running league where everyone is signed. `prospectgen`'s docstring had claimed
   since Step 2.5 that a prospect has "no team/contract assigned yet" — it just wasn't true.
   The effect was to silently disable the entire entry-level system: `is_elc_eligible`
   refuses a player who is already signed, so **no prospect could ever be given a real ELC,
   nothing ever slid**, and the AHL's "you must be under professional contract to turn pro"
   gate opened for free on an $800k deal nobody agreed to. Measured after one offseason: 77
   teenaged prospects holding one- and two-year minimum contracts with a `signed_year` of 0.
   Only visible because the Prospects screen puts contract state in a column.

Fixing it dropped signed prospects from ~400 to ~85 and made the AHL the smallest tier,
since teams now let most junior graduates walk. `ELC_DEADLINE_GRACE` restores the real
behaviour: at the sign-or-lose-him deadline the bar to spend a contract slot drops, because
the alternative is losing him for nothing. That's what fills an AHL roster — most of whose
players are never going to be NHL regulars.

## The one trade-off left open at the end of the main round

> **Resolved by the follow-up round — see Phase 3 below.** The pool was raised to 260. This
> section is kept as the reasoning that was live when the main round shipped.

The undrafted-domestic (UDFA) route is structurally complete — undrafted players develop,
re-enter the draft while they're still teenagers, and become signable when their eligibility
ends — but at the (then-)current `prospectgen.PROSPECT_POOL_SIZE` (150) it delivers only 0–1 NHL
players per decade, because `_effective_rounds` scales the pick count with the pool, so ~85%
of every class gets drafted at any size below ~260 and the leftovers are the very bottom.

Measured both ways, 12 seasons, three seeds:

| pool | rounds | undrafted/yr | world pop | offseason runtime | ELC share | UDFA NHLers/decade |
|---|---|---|---|---|---|---|
| **150 (kept)** | 4 | ~22 | ~1200 | 1.0x | 5–9% | 0–1 |
| 260 | 7 | ~36 | ~1500 | ~2.0x | 10–14% | ~4 |

Kept at 150 for the main round: the economy is healthiest there, and the *other* non-draft
pathway already puts 20–50 players a decade into the league, so the side door isn't shut. (The
follow-up round then took the 260 option — the deep undrafted market was judged worth the 25%
more world. See Phase 3.)

### Phase 7 — the confirming sweep (8 seeds × 12 seasons)

Phase 3 closed the drift Phase 2 had deferred here, so this phase confirms rather than
re-centers. Bands are min–max across all 8 seeds at each season:

| season | payroll % of cap | ELC share | best FA | prospects | CHL | NCAA | AHL | Europe |
|---|---|---|---|---|---|---|---|---|
| 1 | 93.2–95.8% | 3.2–5.4% | 49–63 | 130–140 | 41–58 | 58–72 | 2–8 | 16–23 |
| 4 | 90.8–97.4% | 5.3–7.1% | 67 | 432–441 | 65–100 | 201–246 | 45–66 | 62–80 |
| 8 | 94.7–96.6% | 6.3–8.4% | 67 | 431–475 | 79–98 | 204–229 | 57–79 | 50–82 |
| 12 | 96.6–97.1% | 6.9–9.8% | 67 | 433–449 | 83–106 | 188–241 | 51–80 | 53–85 |

Every one of PR #61's four diagnostic numbers is healthy and **tighter than the pre-round
baseline**: payroll converges to 96.6–97.1% (baseline drifted 91–97%), the entry-level share
holds 3–10% instead of collapsing to zero, the best available free agent never falls below
66, and world population is stable at 1155–1225. Between 12 and 27 prospects are carrying a
slid entry-level contract at any moment, so the headline mechanic is demonstrably live.

Nothing was re-centered. The sweep's properties are now regression tests in
`test_econ_balance.py` — each one guards a failure that actually occurred during this round
and that left the suite green while it did.

## Done criteria — all met

- ✅ A drafted 18-year-old lands in the CHL or NCAA by origin, develops on a tier-appropriate
  curve, signs an ELC that slides instead of burning, moves to the AHL at 20, and reaches the NHL
  when his rating says he's ready — not when a lookup table says so.
- ✅ An undrafted player can develop his way into the league — by the international route (20–50
  a decade) and, since the Phase 3 follow-up widened the pool to a full seven-round draft, by the
  domestic UDFA route too.
- ✅ Old saves load with `development = None` / `slide_years = 0` and behave exactly as before.
- ✅ Phase 7's sweep holds payroll at 90.8–97.4% across 8 seeds × 12 seasons with no ELC-share
  blowup — PR #61's economy is intact and tighter than before.
- ✅ Full pytest suite green: 919 tests at the end of the main round, up from 832 at its start
  (later 940 after the follow-up round below). (~10–12 minutes — it is not hung.)

## What a future round could pick up

- **Simulate the feeder leagues for real.** The abstract-tier decision was deliberate and
  nothing built here forecloses it: schedules, standings and box scores for the CHL/NCAA/AHL
  would replace `development_season_line`'s synthetic numbers without changing a single
  eligibility rule. Still open.

---

# Follow-up round (2026-07-23)

Three of the four open items above, taken on directly (the feeder-league sim was deferred).
User picked them together; merge-as-you-go.

## Phase 1 — user control over promotion (done)

Auto-promotion still runs for the AI, but the user's team is now excluded (`promote_ready_
prospects(world, exclude_tid=world.user_team_id)` in the web offseason handler), and the
manager makes his own moves:

- `prospects.promote_prospect(world, tid, pid)` — call one signed prospect up. Same three
  gates as the automatic path (rights, contract, roster+cap room), but **no readiness gate** —
  a manager may call up a raw prospect, exactly as a real team can. `promote_ready_prospects`
  now delegates to it, so the automatic and manual paths can't diverge.
- `prospects.demote_player(world, tid, pid)` — send a rostered player down. He keeps his
  contract and costs no cap while off the roster. Gated on still being tier-eligible by age;
  no waiver system yet (deferred to Step 3.1 with the rest of the CBA).
- Endpoints: `POST /roster/prospects/{pid}/call-up`, `POST /roster/{pid}/send-down`. UI: a
  Call Up button on the Prospects screen (gold-bordered when NHL-ready), and a "Send to
  Minors" action in the player modal, shown only when the DTO's `can_send_down` says it's
  legal so it never appears on a veteran.

This is also the phase that gives Phase 2 the send-up/down primitives to attach cap stakes to.

## Phase 2 — two-way contracts (done)

The one-way/two-way split `contract.py` had deferred. The insight that made it meaningful in
an abstract-tier world without simulated minor-league salaries: a player off the NHL roster
already costs $0 cap (he's not on `Team.roster`), so what was *missing* wasn't the two-way
case — it was the one-way **penalty**.

- `Contract.two_way` (defaults to one-way, the norm for a rostered NHL player). ELCs are set
  two-way by rule in `sign_elc` and `freeagency.sign_rookie`.
- `cap.buried_cap_hit(world, team)` sums, over the team's off-roster under-contract **one-way**
  players, `max(0, salary - config.BURY_CAP_SHELTER)`. `cap.payroll` now adds it. So a two-way
  deal buried in the minors frees the whole hit; a one-way deal frees only the sheltered slice,
  which is what makes a bad long-term one-way contract a cap anchor a team can't simply demote
  away.
- The aggregate economy is untouched — the buried hit only bites on a *demotion*, and only the
  user demotes (the headless offseason and the AI never do), so the sweep is unchanged
  (verified: 0 buried hits league-wide after 6 headless seasons, payroll still ~94%).
- UI: the player modal shows one-way/two-way on the bio line, and the Send to Minors affordance
  says whether the move "frees his full cap hit" or leaves `$Xm … on the cap`. Verified live: a
  two-way ELC prospect frees his full hit; a one-way $5.2M veteran would leave $3.25M buried.

## Phase 3 — deeper undrafted market (done)

Raised `PROSPECT_POOL_SIZE` 150 → 260. The reason the domestic UDFA route was thin wasn't
the pool alone — `_effective_rounds` clamps the draft to `pool_size // num_teams` rounds, so
at 150 the draft was only **four rounds** and nearly every credible player was drafted. At 260
the draft runs its full seven rounds (224 picks), leaving ~36 undrafted a year, and the
domestic route now delivers a handful of NHL players per decade instead of ~0–1.

The costs, measured across an 8-seed × 12-season sweep and accepted:

| | at 150 (Phase 7 sweep) | at 260 (this phase) |
|---|---|---|
| payroll % of cap (season 12) | 96.6–97.1% | 96.8–97.1% |
| ELC share (season 12) | 6.9–9.8% | 12.6–16.5% |
| prospects in the system | ~440 | ~730–790 |
| world population | 1155–1225 | ~1450–1520 |
| offseason runtime | 1.0× | ~2.0× |

Payroll is unchanged and the best available free agent still never falls below 67, so the
economy is intact — the cheap ELC players aren't displacing market-priced ones, which is the
whole PR #61 fear. The entry-level share rose to ~12–18%, which is if anything *more* realistic
(real rosters carry a comparable entry-level presence). The two regression guards on that share
in `test_econ_balance.py` were widened from 0.15 to 0.22 accordingly — still a decisive catch on
the 41% blowup they exist to prevent, with headroom above the observed ~18% max.

The whole round is now complete: all three follow-ups the user picked are in, and only the
feeder-league simulation remains open.

## Phase 4 — seed the initial world (done)

A freshly generated league opened with **empty** farm systems and an **empty** free-agent
market — both only filled from the first offseason's draft and cull. Unrealistic (a real
league is always mid-stream) and it left the Prospects screen and the FA board blank on day
one. `gen/leaguegen.build_world` now seeds both, after the rosters exist and last so roster
generation stays byte-identical per seed.

- **Farm systems**, semi-inverse to team strength. Each team gets an AHL group (older 20–24
  prospects signed to two-way ELCs — an actual minor-league roster) and a junior group (18–19
  amateurs in the CHL/NCAA/Europe, unsigned). Quality leans by `FARM_QUALITY_LEAN`: the weakest
  roster's prospects get the biggest target-overall bonus, the strongest a matching penalty,
  linear between — a lean, not a rule, so a contender can still turn up a gem. Measured: the weak
  half's top-5 prospect potential runs 4–7 points above the strong half's across seeds.
- **Free-agent pool**, the depth left on the wire. Bulk is young roster-filler (bottom-six /
  third-pair), with aging middle-six "meh" veterans, a few AAAA/quad-A tweeners, and a couple of
  young-ish third-liners as texture. Capped so nothing is a real top-six talent (observed overall
  48–66, median age 25, ~67% aged ≤27).
- Shared plumbing: the draft's tier-placement logic moved to `prospects.place_in_development`
  (draft and farm-seeding both call it); `generate_prospect` gained `age`/`overall_bonus`;
  `build_world(seed_pools=False)` gives a bare league for unit tests that need empty pools.

Economy unchanged: seeded prospects and free agents are off every NHL roster, so they cost no
cap, and the multi-season steady state is identical to before (payroll ~97%, ELC ~12–18%). The
seeding just makes the world open *warmed up* — ~1130 players at gen instead of ~820 — rather
than empty, converging to the same ~1500 within a few seasons. `build_world` stays ~0.1s.

**Known model limit, flagged not fixed:** genuine career-AHL veterans (27–30-year-old "AAAA"
lifers) can't live *on* an AHL roster, because the development system caps at
`MAX_PROSPECT_AGE = 25`. They're seeded into the FA pool instead (realistic — many are AHL free
agents / PTO bodies), and the seeded AHL runs to age 24. Persisting 27+ players on AHL rosters
would need a targeted rule (a signed AHL player doesn't age out of the system while under
contract) — a small but real change to `advance_development`'s semantics, left for a future
round.
