# Player Ratings: What They Determine

Companion to `DESIGN.md` (which flagged this as a needed pass — see its
"Concrete rating list" open item) and `docs/PARITY_PLAN.md`. This document
inventories every rating in the sim and what it actually does today.

Updated 2026-07-10 after the "impactful ratings" round (PRs #35–#47), which
wired every previously-inert rating into `sim/engine.py`. The old "gap" notes
that used to fill this file are gone — almost all of them are now live mechanics;
the few genuinely-remaining ones are collected in §7.

Scale: all ratings are integers, `RATING_MIN=25` to `RATING_MAX=99`
(`pucksim/config.py`), clamped by `clamp_rating()` (`models/attributes.py`).

Two separate vocabularies live in one flat `Player.ratings: Dict[str, int]`
(`models/player.py`) — skater ratings and goalie ratings never collide because
goalie keys are namespaced (e.g. `gk_puck_handling` vs. the skater
`puck_handling`).

Every live mechanic below is centered on the ~65–70 rating mean and tuned so a
league-average player is unchanged from the pre-round baseline; ratings above the
pivot help, ratings below hurt, and league-wide rates (goals/game, hits/game,
block rate, rebound rate) stay realistic. Coefficients are `PROVISIONAL/TUNABLE`
constants in `config.py`.

---

## 1. Skater ratings

### Physical

**`skating`**
Drives the rush, combined with `agility` as a player's *speed*
(`0.5*skating + 0.5*agility`):
- **Rush finishing** — a shooter's rush save-suppression bonus scales with their
  speed (`_resolve_shot_attempt`, `RUSH_SPEED_PIVOT`/`RUSH_SPEED_SLOPE`,
  `RUSH_BONUS_MIN`/`MAX`): a burner off the entry is more dangerous than a
  plodder, centered on the mean so an average rush is the old flat 0.03.
- **Zone entry** — the attacking group's average speed scales the per-cycle
  offside chance (`_team_speed_mult_for_offside`, `OFFSIDE_SPEED_SLOPE`): a fast,
  agile team is blown offside less often (cleaner entries, more o-zone time).

Also feeds the `physicality` composite (0.15) and declines fastest with age as a
"Physical" rating (`systems/development.py`).

**`agility`**
Same *speed* axis as `skating` (rush finishing + zone entry above). Also resists
a body check: a carrier's `strength`/`agility` is what a checker's
`checking`/`strength` has to beat to separate him (`_hit_separates`). Feeds
`physicality` (0.15) and fast physical aging.

**`strength`**
Drives the hitting mechanic (see `checking` below) as the co-weight of who
throws (and lands) a body check, and resists being separated from the puck
(`_hit_separates`). Feeds `physicality` (0.35, its largest component) and
physical aging.

**`stamina`**
In-game injury risk: `_injury_check` (`sim/engine.py`) computes
`rate = IN_GAME_INJURY_RATE * (1 + (70 - stamina) * INJURY_STAMINA_SLOPE)` per
shift per on-ice player — lower stamina, higher in-game injury chance. Feeds
`intangibles` (0.15) and physical aging.
*Deferred*: `Player.condition` (between-game freshness) and
`config.BASE_INJURY_RATE` remain unread — a between-game durability layer that
needs a schedule with real off-days first (the current schedule is fully
abstracted, every team every day). See §7.

### Offense

**`shot_accuracy`**
The heaviest offensive rating. Drives the shooter's `shot_skill`:
- Main shot resolution (`_resolve_shot_attempt`):
  `shot_skill = 0.5*shot_accuracy + 0.3*shot_power + 0.2*offensive_awareness`.
- Shootout scoring/ranking:
  `0.5*shot_accuracy + 0.3*puck_handling + 0.2*offensive_awareness`.
- On-ice shot-attribution weight (`build_on_ice_cache`, `sim/ratings.py`):
  decides which on-ice skater takes the shot.
- Feeds `scoring` (0.45, the largest single weight in any composite).

**`shot_power`**
Secondary weight (0.3) in the same `shot_skill` formulas and the shot-attribution
cache. Feeds `scoring` (0.35).

**`playmaking`**
Drives assist attribution — `_pick_assists` weights primary and secondary assist
rolls by `max(0.5, playmaking - 20)`. Because a goal's assisters are now also
credited **expected assists (xA)** (§3), higher playmaking indirectly earns more
xA too. Feeds `playmaking_c` (0.5).

**`puck_handling`**
Shootout shooter scoring (0.3) and the faceoff-scrum winger tiebreak
(`_winger_iq_score`, 0.5). Also weights who gets *hit* (the puck carrier is picked
by `puck_handling` in `_pick_hit_target`). Feeds `playmaking_c` (0.35).

**`offensive_awareness`**
The broadest offensive rating — a 0.15–0.25 component of nearly every offensive
formula (`_resolve_shot_attempt` 0.2, shootout 0.2, `_winger_iq_score` 0.25, the
on-ice shot-weight cache 0.25) plus `scoring` (0.20) and `playmaking_c` (0.15).
An "IQ" rating in aging (slower decay).

### Defense

**`checking`**
Drives the **hitting mechanic** (net-new this round). Each shot-attempt cycle
(`_resolve_hits`) the defending team may body-check the puck carrier and the
attacking team may finish a fore-check:
- The hitter is chosen weighted by `checking + strength` (`_pick_hitter`) and
  earns the `hits` stat.
- A more physical on-ice group throws more hits — the per-cycle chance scales
  with the group's average `checking`/`strength` (`_team_physicality_mult`,
  `HIT_TEAM_PHYSICALITY_SLOPE`), so heavy teams lead the league in hits.
- A defensive check may **separate** the carrier (`_hit_separates`,
  checker `checking`/`strength` vs carrier `strength`/`agility`,
  `HIT_SEPARATION_*`) — a forced turnover, credited as a `takeaway` for the
  checker and a `giveaway` for the carrier, and it biases the ensuing possession
  battle (`HIT_TURNOVER_FLIP_P`).

Also feeds `physicality` (0.35) and `defense` (0.20), and — via `defense` —
PK-unit selection.

**`defensive_awareness`**
The faceoff-scrum tiebreak (`_winger_iq_score`, 0.25) and the `defense` composite
(0.40 — the heaviest weight of any rating in any composite), which drives PK-unit
selection and a defenseman's overall. An "IQ" rating (slow aging).

**`shot_blocking`**
Drives blocked shots. When an off-goal attempt splits block-vs-miss
(`_resolve_shot_attempt`), the defender in the lane is chosen weighted by
`shot_blocking` (`_pick_blocker`), that skater's rating raises/lowers the block
chance (`BLOCK_RATING_PIVOT`/`SLOPE`, clamped `BLOCK_PROB_MIN`/`MAX`), and a block
credits their `blocks` stat — pulled-net (empty-net) blocks included. The pivot
is centered so the league-wide block rate is unchanged. Feeds `defense` (0.25).

**`discipline`**
Governs penalties (`sim/special_teams.py`):
- `penalty_probability_for_shift`: the *worst* on-ice discipline runs through
  `discipline_multiplier() = 1 + (70 - discipline) * PENALTY_DISCIPLINE_SLOPE`,
  clamped `[0.25, 3.0]`.
- `pick_offending_player`: weights the culprit by `max(1.0, 130 - discipline)`.
- Feeds `defense` (0.15) and `intangibles` (0.15).

### Mental

**`faceoffs`**
Directly resolves every faceoff (`_resolve_faceoff`):
`rating_gap = home_fo - away_fo`, scaled by the center's morale realization and a
fixed slope into a home win-share clamped `[0.20, 0.80]` around 0.50, with a
gap-shrinking tie probability on top. Maps 1:1 to `faceoff_c` (1.0), weighted
heavily for centers in `overall()` (0.10 for C vs. 0.01–0.02 for wings/D).

**`composure`**
Now wired. `_is_clutch_situation` (3rd period or OT, score within one goal) gates
`clutch_realization(composure)` into the shooter's `off_real` — in a big spot a
high-composure shooter holds his level (realization → 1.0, no boost) while a
low-composure shooter's finishing dips. Downside-only, capped at 1.0 (never
up-weights); a no-op outside clutch moments. Feeds `intangibles` (0.40) and ages
slowly.

**`work_ethic`**
Outside live shot resolution:
- Offseason development (`_overall_delta`): `growth += (work_ethic - 70) * 0.015`.
- Morale baseline (`_personal_baseline`, `systems/momentum.py`):
  `MORALE_BASELINE + (work_ethic - 70) * 0.15`.
- Feeds `intangibles` (0.30).

---

## 2. Goalie ratings

Namespaced separately (`GOALIE_RATING_GROUPS` / `ALL_GOALIE_RATINGS`,
`models/attributes.py`).

**`reflexes`**
The dominant term in a goalie's in-game skill. `goalie_skill = 0.55*reflexes +
0.45*positioning` (`_goalie_skill`, used by both regular save math and the
shootout) is compared against the shooter's `shot_skill` to produce on-goal and
save probabilities (§3). This composite is now scaled by the goalie's season form
(§4) when a form state is threaded in. Weight 0.35 in `overall()`.

**`positioning`**
Second term in `goalie_skill` (0.45). Weight 0.30 in `overall()`.

**`rebound_control`**
Now wired. Scales how often a save kicks out a rebound
(`REBOUND_CONTROL_PIVOT`/`SLOPE`, floored by `REBOUND_CONTROL_MIN_MULT`): an elite
goalie smothers pucks and surrenders far fewer rebounds, a poor one gives them up.
Centered on the goalie mean so the league-wide rebound rate is preserved. (Paired
with this round's rebound rework: a rebound is now an immediate extra look —
`MAX_REBOUND_CHAIN` — and a rebound shot is high-danger, converting well above a
normal shot via `REBOUND_QUALITY_BONUS`.) Weight 0.15 in `overall()`.

**`gk_puck_handling`**
Now wired. A puck-moving goalie sometimes plays the puck and cuts off a zone entry
before the rush develops (`_goalie_negates_rush`,
`GK_PUCKHANDLING_PIVOT`/`RUSH_KILL_SLOPE`/`MAX`), so an elite puck-handler faces
materially fewer rush chances. One-sided above the pivot (a poor handler simply
doesn't help). Weight 0.10 in `overall()`.

**`gk_consistency`**
Drives the season "form" variance mechanic (§4) — tight spread for consistent
goalies, wide for volatile ones — which is now applied to live goalie skill.
Weight 0.10 in `overall()`.

Goalies have **no intermediate composite layer** — `overall()` is a single flat
weighted average across the five ratings above.

---

## 3. Shot resolution, xG/xA

Core formula (`_resolve_shot_attempt`, duplicated for shootouts):

```
shot_skill   = 0.5*shot_accuracy + 0.3*shot_power + 0.2*offensive_awareness   (shooter)
goalie_skill = (0.55*reflexes + 0.45*positioning) * season_form               (goalie)
gap          = (shot_skill - goalie_skill) * 0.0035
quality      = zone/shot-type danger + strength-state delta + rebound bonus
rush_bonus   = speed-scaled on a rush (0 otherwise)
```

`gap` feeds both:
- **On-goal probability**: `clamp(0.35, 0.92, 0.55 + (quality-0.5)*0.5 + gap*off_real)`
- **Save probability**: `clamp(0.55, 0.97, 0.90 - (quality-0.5)*0.35 - rush_bonus - gap*off_real)`,
  then rescaled around 0.90 by the goalie's `def_real`.

`off_real` (shooter) and `def_real` (goalie) are the realization multipliers from
§4 — capped at 1.0, only ever shrinking the gap, never inflating a player above
their base rating.

**Expected goals / assists (xG/xA)** — every shot on goal carries an xG value:
the goal probability a league-*average* goalie would concede on a chance of that
quality (`_expected_goals`, skill-independent by design — it reuses the
save-probability shape with a neutral zero skill gap, so summed over a team's
shots it tracks the team's actual goals, ~1.08× over a season sample). Credited to
the shooter (`xg`) and charged to the goalie facing it (`xga`); a goal's assisters
earn the chance they set up as `xA`. Surfaced on the stat lines, serializers, and
the Box Score.

The counting stats `hits`, `blocks`, `takeaways`, `giveaways` (previously always
zero) are now incremented by the mechanics in §1.

---

## 4. Realization / variance mechanics

All defined in `sim/ratings.py` as multiplicative scalars in `[floor, 1.0]` that
scale the *skill gap* between two competing ratings — never the base rating
itself. The project's core rule: realization can make a player sustain their
rating under good conditions, but never exceed it.

| Mechanic | Formula | Floor | Wired into `engine.py`? |
|---|---|---|---|
| `morale_realization(morale)` | `max(0.85, min(1.0, 1.0 + (morale-70)*0.0024))` | 0.85 | Yes |
| `clutch_realization(composure)` | `max(0.93, min(1.0, 0.97 + (composure-70)*0.0011))` | 0.93 | **Yes** — gated to clutch situations (`_is_clutch_situation`) |
| `familiarity_realization(shared_secs)` | linear ramp 0.92 → 1.0 over 40,000s shared ice time | 0.92 | Yes |
| `fatigue_realization(fatigue)` | `max(0.90, 1.0 - fatigue*0.10/100)` | 0.90 | Yes |
| `hot_hand_boost(streak)` | gap-closing: `def_real + (1-def_real)*fraction`, `fraction ≤ 0.5` | n/a (bounded ≤1.0) | Yes |

**Deliberate exception — goalie season "form"**: `systems/development.py`'s
`resample_goalie_form` / `apply_goalie_form` is a *symmetric*, season-level
variance multiplier (`FORM_MIN=0.60` to `FORM_MAX=1.40`, baseline 1.0) driven by
`gk_consistency` — tight spread for consistent goalies, wide for volatile ones.
Unlike the realization mechanics above it **may** push a goalie above their base
rating for a season (a believable "breakout year"), by design. It is now applied
to live goalie skill: `simulate_game` threads a per-World `GoalieFormState`
(owned/resampled by `systems/offseason.py`) through to `_goalie_skill`, which
scales the `reflexes`/`positioning` composite by that season's form.

---

## 5. Composite ratings

`models/attributes.py`, via `composite()`/`all_composites()`:

```
scoring       = 0.35*shot_power + 0.45*shot_accuracy + 0.20*offensive_awareness
playmaking_c  = 0.50*playmaking + 0.35*puck_handling + 0.15*offensive_awareness
physicality   = 0.35*strength + 0.35*checking + 0.15*skating + 0.15*agility
defense       = 0.40*defensive_awareness + 0.25*shot_blocking + 0.20*checking + 0.15*discipline
faceoff_c     = 1.00*faceoffs
intangibles   = 0.40*composure + 0.30*work_ethic + 0.15*discipline + 0.15*stamina
```

**`overall`** (skaters) is a per-position weighted blend of the six composites
(`POSITION_WEIGHTS`) — e.g. wings weight `scoring` 0.32, centers weight
`faceoff_c` 0.10, defensemen weight `defense` 0.35. **`overall`** (goalies) is the
flat `GOALIE_WEIGHTS` average from §2.

Composites and `overall` never feed live shot/save/faceoff formulas directly —
they drive **roster and team decisions**: line/pair fit, goalie starter/backup,
D-pair ranking, PP/PK unit selection (§6), in-game injury/bench replacement (picks
highest available `overall`), and contract/draft/free-agency/legacy valuation. The
web roster also surfaces a per-player composite "key ratings" peek
(OFF/PLY/DEF/PHY for skaters, REF/POS/REB/HND for goalies).

---

## 6. Position and special-teams effects

- **Faceoffs** — centers take faceoffs in-game (`_current_center`) and are the one
  position where `faceoff_c` meaningfully moves `overall`.
- **Power play** unit selection (`models/team.py`) ranks by
  `0.55*scoring + 0.45*playmaking_c`; **penalty kill** ranks by the `defense`
  composite. The web roster's auto-build now fills the PP1/PK1 units and displays
  them (read-only).
- **Strength-state shot modifiers** (`sim/ratings.py`): PP gives ~1.6× shot volume
  and +0.22 quality; PK ~0.55× volume and −0.18 quality — team-strength effects,
  not player ratings, layered onto whoever's on the ice.
- **Penalty drawing** scales off `discipline` (§1) plus coach tendencies
  (`defensive_risk_tolerance`, `forecheck_aggression`) and an optional playoff
  penalty-rate dampener.

---

## 7. Remaining gaps

Everything the previous version of this file listed as unwired is now live. What
remains:

1. **`Player.condition` / `config.BASE_INJURY_RATE`** — a between-game
   fatigue/durability layer, deliberately deferred: the season schedule is fully
   abstracted (every team plays every day, no rest days), so a played→drain /
   rest→recover model can't hold a stable value or create inter-team variation. It
   needs a schedule with real off-days first.
2. **xA is a simplified model** — because the engine attributes assisters only on
   goals, xA accrues to a goal's assisters (the xG of the chance they set up)
   rather than to the passer on every dangerous shot. A full xA would need
   shot-level passer attribution.
3. **PP/PK unit *editing*** — the units are auto-built and displayed but not
   hand-editable; that needs a backend PUT that accepts special-teams units (the
   current `/roster/lines` PUT handles only lines/pairs/goalies). Not a rating gap.
4. **Hitting/turnover realism** — the hit and takeaway/giveaway mechanics are a
   tuned first pass (calibrated to ~20 hits/team/game and stable scoring); the
   possession-flip effect is intentionally small.
