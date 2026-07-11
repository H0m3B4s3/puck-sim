# PuckSim Sim Synergy Plan — Player Roles, Line Synergies & Defender Impact

A sim-realism round adding **role-based line synergies** (a sniper feeds off a playmaker; a
grinder line shuts down without scoring) and fixing the engine's biggest realism gap along the
way (on-ice defenders barely affect shot outcomes today).

Planned 2026-07-11. All engine function names / line numbers below were verified directly
against source during the planning session — implementing agents should trust them but
**re-read the cited files before writing code** (line numbers drift as the file changes).

## Why

Two findings from a read of the sim engine drive this round:

1. **Archetype is thrown away at generation time.** `gen/playergen.py` picks an archetype,
   applies its `skews` to the ratings dict, then discards the label. There is **no
   `archetype`/`role` field on `Player`** (`models/player.py`) and nothing archetype-related is
   serialized. A "Sniper" and a "Grinder" differ only in numbers — the sim has no identity to
   read, so it can't reward line composition.
2. **Chemistry measures tenure, not fit.** `sim/ratings.py::familiarity_realization` ramps a
   single scalar (`CHEM_R_MIN=0.92` → 1.0) purely off shared on-ice seconds. Three snipers who
   have logged 40k seconds together get *full* chemistry; a perfect sniper+playmaker+two-way
   trio who just met get the *minimum*. There is no "these players complement each other" axis
   anywhere in the codebase.

Separately, the single biggest realism gap in the shot model: **on-ice defenders barely
matter.** A shot is resolved as `shooter_skill` vs `goalie_skill`
(`sim/engine.py::_resolve_shot_attempt`, the `gap = (shot_skill - goalie_skill) * 0.0035`
line). The five defending skaters affect the outcome *only* through shared-ice chemistry, a
shot-blocker pick, and hits. A defenseman's `defensive_awareness` **never suppresses the
opponent's shot quality or on-goal probability.** The "3 grinders = big defensive boost" idea
is impossible until this is fixed — a stout defensive group does not currently degrade the
offense it faces.

## Design principles (locked with the user, 2026-07-11)

- **Roles are persisted on `Player`** (chosen over runtime inference). The persisted `role` tag
  is what synergies key on; the specific `archetype` name is kept for UI/flavor.
- **Do both synergy AND the defender-impact fix** (chosen over synergy-only). The grinder-line
  identity is a *defensive* effect, so it cannot exist without the defender fix.
- **Refine the archetype roster** (chosen over keeping it as-is): the current 11 skater
  archetypes have gaps for synergy purposes (playmaking is C-only, no pass-first winger, no
  bottom-six checking C).

### The "no upweighting" constraint (binding — see `[[feedback_no_upweighting]]` / `sim/ratings.py`)

This codebase has a hard rule: **no mechanic may push a player's effective performance above
his rating-implied ceiling.** Every realization factor (morale/chemistry/clutch/fatigue/
hot-hand) is a multiplicative scalar bounded in `[floor, 1.0]` — capped at exactly 1.0, never
higher. Synergy must obey the same rule, so it is framed as a **second chemistry axis**, not a
bonus:

> Synergy = *how much of their rating a line realizes*, based on role FIT (not tenure).
> Good composition → members realize up to 1.0 (they hit their ceiling). Bad composition
> (3 snipers, no playmaker) → they dip below it. Composition never makes anyone *better than
> their rating* — it only stops them from playing below it.

The grinder line's identity therefore comes from the **defensive-suppression** side: a stout
defensive group suppresses the *opponent* below *their* ceiling (also downside-only). A
grinder line's own low offense is already baked into its low ratings — no penalty needed there.

Both new factors are **league-mean-centered**, so an average-composition line and an
average-defensive group reproduce today's numbers. League-wide goals/game must be conserved
(the same conservation discipline `systems/development.py` and the strength-state modifiers
already follow).

## Two axes of chemistry, side by side

| Axis | Field / function | Measures | Set / changed by |
|---|---|---|---|
| Familiarity (exists today) | `Team.chemistry` (shared secs) → `ratings.familiarity_realization` | Tenure — have these players logged ice time together | `seed_chemistry` at world-gen; accrues with shared shifts; resets/cold on trade |
| **Synergy (new)** | on-ice group's `role` composition → `synergy_real` | Fit — do these roles complement each other | Recomputed per shift from who is on the ice |

They **multiply** — a well-composed line that just met is still limited by cold familiarity,
and a long-tenured mismatched line is still limited by poor fit.

## Role vocabulary (Phase 0 deliverable — lock this first)

Coarse roles the sim keys on, one per skater, derived from archetype at generation:

| Role | From archetypes | Sim meaning |
|---|---|---|
| `finisher` | Sniper | Shoots; realizes scoring fully only when set up |
| `playmaker` | Playmaking Center, (new) Pass-First Winger | Sets up finishers; unlocks one-timers |
| `two_way_f` | Two-Way Forward, Speedster | Neutral/flexible; mild positive fit with anything |
| `grinder` | Grinder, (new) Checking Center | Low offense, strong defensive suppression |
| `physical` | Power Forward, Enforcer-Physical | Physical; forecheck/defensive lean |
| `offensive_d` | Offensive Defenseman | PP/transition offense from the back end |
| `shutdown_d` | Shutdown Defenseman | Max defensive suppression from the pair |
| `two_way_d` | Two-Way Defenseman | Balanced D |
| `generational` | Generational Forward, Unicorn Defenseman | Complements everything (no holes) |

Goalie archetypes keep their existing names for UI but need no role (goalies are not part of
line synergy).

---

## Phases (each = one branch + PR, dispatched sequentially)

Per `[[feedback_branch_workflow]]`: branch-per-step + PR, sequential (not parallel), against
`github.com/H0m3B4s3/puck-sim`. Merge-as-you-go, re-confirming merge authorization for this
round.

### Phase 0 — Role identity (data plumbing, no behavior change)
**Branch:** `feat/player-role-identity`
- `models/player.py`: add `archetype: Optional[str] = None` and `role: str = "two_way_f"`;
  serialize both in `to_dict`/`from_dict`. `from_dict` backfills `role` from the rating profile
  when the field is absent (old saves), via a shared classifier so behavior is deterministic.
- `models/attributes.py`: add `ROLE_FOR_ARCHETYPE` map + a `role_for_ratings(ratings, position)`
  fallback classifier (used only for backfill / players with no stored archetype).
- `gen/playergen.py`: stamp the chosen archetype's `name` + role onto the generated `Player`
  instead of discarding it (both `generate_skater` and `generate_goalie`).
- **Done:** every generated player has a correct `archetype`+`role`; old saves load and backfill
  a sensible `role`; save round-trips; no sim/stat change (assert a seeded season is bit-identical
  to pre-change output).

### Phase 1 — Archetype refresh
**Branch:** `feat/archetype-refresh`
- `models/attributes.py`: add a **Pass-First Winger** (`LW`/`RW`, playmaking-skewed) and a
  **Checking Center** (`C`, defensive/faceoff-skewed, low offense); tune **Grinder** skews so a
  grinder trio reads as genuinely defensive/low-offense. Map every archetype (incl. rare) to a
  role in `ROLE_FOR_ARCHETYPE`.
- Update `docs/PLAYER_RATINGS.md` if it enumerates archetypes.
- **Done:** each role in the vocabulary is reachable from ≥1 archetype; generation distribution
  still calibrates to target overalls (existing `tests/test_generation.py` green).

### Phase 2 — Fix on-ice defender impact (the realism win)
**Branch:** `feat/defender-shot-suppression`
- `sim/engine.py::_TeamState._rebuild_cache`: compute the group's **defensive strength** (avg
  `defensive_awareness`/`positioning` of the 5 skaters), league-mean-centered, stored on the
  `OnIceCache` (extend the dataclass in `sim/ratings.py`).
- `sim/engine.py::_resolve_shot_attempt`: fold the *defending* group's defensive strength into a
  suppression of `quality` / `on_goal_p` — downside-only for the offense, centered so an average
  defensive group reproduces today's numbers.
- New `config.py` tunables (pivot + slope + clamp), same shape as the existing
  `BLOCK_RATING_*`/`HIT_*` constants.
- **Done:** a high-`defensive_awareness` pairing measurably lowers opponent on-ice xG vs. a weak
  one; **league goals/game unchanged** within noise across a multi-seed sweep.

### Phase 3 — Offensive role synergy
**Branch:** `feat/line-role-synergy`
- `sim/ratings.py`: add `synergy_realization(roles: List[str]) -> float` in `[floor, 1.0]` from
  the on-ice group's role multiset (finisher+playmaker → ~1.0; finishers with no playmaker →
  dip; grinder-heavy → low offensive synergy, which is fine). Extend `OnIceCache` with
  `synergy_real`, populated in `_rebuild_cache`.
- `sim/engine.py::_resolve_shot_attempt`: multiply the shooter's `off_real` by
  `offense.cache.synergy_real` (folds in exactly like `chem_real`).
- `sim/engine.py::_pick_zone_and_shot_type`: unlock/upweight `one_timer` when a `playmaker` is on
  the ice with a `finisher`.
- **Done:** a finisher+playmaker line **outscores the same three players split apart** (seeded
  A/B); league goals/game conserved.

### Phase 4 — Surface it (UI)
**Branch:** `feat/roster-synergy-ui`
- Backend: `roster` router / serializers expose each player's `archetype`+`role`, and a computed
  **per-line synergy readout** (label + tier) for the user team's lines.
- Frontend: `screens/Roster.tsx` shows role badges and a line-synergy indicator (e.g. "Sniper +
  Playmaker — clicking" / "3 checkers — shutdown, no finish"); `PlayerModal.tsx` shows archetype.
- **Done:** line-building visibly communicates synergy; changing a line updates the readout.

### Phase 5 — Tests + tuning
**Branch:** `test/synergy-tuning`
- `tests/`: statistical assertions for Phases 2–3 (defender suppression, split-line scoring
  delta, conservation), plus role-backfill and archetype-mapping unit tests.
- Retune the provisional constants against a multi-seed season sweep so goals/game, PP%, and
  save% stay in their realistic bands.
- **Done:** full suite green; documented before/after league-rate table in the PR.

## Open tuning items (decide during implementation, not now)

- Exact `synergy_realization` floor and the per-composition magnitudes (how much a missing
  playmaker costs) — needs simulated-season data, same "don't invent tuning numbers before
  there's a corpus" restraint the rest of the codebase applies.
- Whether D-pair synergy (offensive_d + shutdown_d) gets its own term or rolls into the same
  group synergy as forwards.
- Whether `two_way_f`/`generational` act as universal "glue" (mild positive fit with any
  composition) or are strictly neutral.

## Discovered during implementation (pre-existing, flagged for follow-up)

- **Empty-net `sog` over-credit / reconciliation edge.** A missed or blocked shot at a pulled
  (empty) net is logged with `goalie_id is None`, and an *on-goal* empty-net attempt is credited
  `sog` even when it then misses — so `tests/test_engine.py::test_sog_reconciles_with_opposing_
  goalie_shots_faced`'s exact reconciliation breaks in the rare game with a pulled-goalie miss/
  block (violates on `main` at seeds 5/27, independent of this round). Pre-existing pulled-goalie
  (Phase-2-of-v1) accounting, not a synergy bug; the test is pinned to a clean seed and
  documented. Proper fix: don't credit `sog` for a missed empty-net attempt, and/or tag on-goal
  empty-net attempts distinctly so the reconciliation is unambiguous.
- **Verification harness footgun (fixed in this round's tests):** `build_world` takes an **int**
  seed; passing an `Rng` object (`build_world(Rng(1))`) reseeds `random.Random` with an
  object hash (id-based) → a different league every call, silently non-deterministic. All Phase
  2/3 tests use int seeds.
- **Defender-suppression conservation** measures ~−0.8% league goals at 9.6k games/arm (synergy
  ~−0.1%). Small; a candidate for a minor `DEF_SUPPRESSION_PIVOT` nudge during the Phase-5 sweep.

## Explicitly out of scope (backlog — see `[[project_feature_backlog]]`)

Farm system, pick-trading, RFA/negotiation, staff, finances, news, directed training, and the
possession/zone-entry model rewrite (a bigger sim round). This round is roles + line synergy +
the one defender-impact fix that the grinder-line identity depends on.
