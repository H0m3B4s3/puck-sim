# League distribution targets

The reference bands PuckSim's simulated seasons are calibrated against, and the reasoning behind
each. The machine-readable copy lives in `testkit/distribution.TARGETS` — **that** is what the
harness prints and what `tests/test_distribution.py` asserts. This document explains it.

Run the report with:

```bash
.venv/bin/python testkit/run_season.py --seed 7 --seasons 1
```

## Why this exists

Discovered 2026-07-24 during playtesting. PuckSim's *team*-level scoring was already correct —
~6.3 goals per game combined, squarely NHL-realistic — while every layer beneath it was not:

| Metric | Measured (seed 7, pre-fix) | NHL |
|---|---|---|
| goals/game, combined | 6.34 | 6.0 – 6.3 |
| SOG / team / game | 13.5 | ~30 |
| league shooting % | 23.3% | ~10% |
| league save % | .767 | ~.905 |
| assists per goal | 1.24 | ~1.70 |
| D share of all goals | 33.7% | ~13% |
| goal leader | **82, by a defenseman** | 50 – 65 |

The sim was running roughly 45% of real shot volume and compensating with a ~2.3x inflated
conversion rate. Goals per game came out right; individual totals did not. Nothing in the codebase
measured any of it, which is precisely why it survived — `run_season.py` printed standings, a
top-10 scorer list, and goalie save percentages, none of which look obviously wrong when the event
budget is half of real and conversion is double.

The lesson generalises, and it is the same one the prospect-development round learned: **every one
of these bugs was silent.** A sim can only be wrong in ways you measure. Add the instrument before
believing the system.

## The bands

Bands are inclusive, expressed per-82-games where the metric is a season total, and sourced from
recent (2022–2024) NHL league-wide rates. They are deliberately bands rather than points: the goal
is "does this look like a hockey league", not "does this reproduce one particular season". Each is
wide enough that ordinary seed-to-seed variance passes and narrow enough that a structural bug
fails.

### Team-level rates

| Metric | Band | Why |
|---|---|---|
| `goals_per_game` | 6.0 – 6.4 | **The invariant.** This was already correct before the calibration round and every change in it had to preserve it. If a fix moves goals/game, the fix is wrong even if its own metric improved. |

### Event budget

| Metric | Band | Why |
|---|---|---|
| `sog_per_team_game` | 28 – 32 | NHL sits at 29–31. This is the headline volume number. |
| `corsi_per_team_game` | 50 – 60 | All shot attempts including blocked and missed. Implies a SOG/Corsi ratio near 0.53, matching the NHL. |
| `pct_team_games_under_15_sog` | 0 – 3% | A *spread* check, not a mean check. Single-digit-shot games were the original playtest complaint, and a mean alone cannot detect them — 27 shots a game can come from consistent 27s or from alternating 9s and 45s. |
| `shooting_pct` | 9.5 – 10.8% | Falls out of the two above plus goals/game; listed separately because it is the number that makes individual goal totals absurd when wrong. |
| `save_pct` | .893 – .908 | The mirror of shooting %. Kept as its own band so a regression shows up on the side it originated. |

### Credit distribution

| Metric | Band | Why |
|---|---|---|
| `assists_per_goal` | 1.62 – 1.76 | NHL ~1.70. Suppressing this deflates every point total and hits playmakers hardest, which distorts who appears on a leaderboard. |
| `d_goal_share_pct` | 11 – 16% | NHL ~13%. Defensemen scoring a third of all goals was the single largest distortion found. |

### Leaderboard shape

Bands are what the *whole distribution* should look like, not just its top. A sim can put the goal
leader in range and still be wrong everywhere else, so the histogram thresholds matter as much as
the leader does.

| Metric | Band | Why |
|---|---|---|
| `goal_leader` | 50 – 66 | Modern NHL high is ~65 (Ovechkin 65, McDavid 64). |
| `point_leader` | 100 – 135 | Modern NHL leaders run 100–135. |
| `skaters_ge_50_goals` | 0 – 6 | Some seasons have none. |
| `skaters_ge_40_goals` | 6 – 18 | |
| `skaters_ge_30_goals` | 28 – 48 | |
| `skaters_ge_20_goals` | 90 – 125 | The depth-scoring check — the band that catches over-concentration in stars. |

### Deployment

| Metric | Band | Why |
|---|---|---|
| `toi_f1_min` | 18 – 20 | |
| `toi_f4_min` | 10 – 12 | A 1C should play roughly 1.8x a 4C. Before this round every forward line played ~15 minutes. |
| `toi_d1_min` | 23 – 25 | |
| `toi_d3_min` | 15 – 17 | |

**Tiers are assigned by ranking, not by reading the line chart.** A team's top 3 forwards by
per-game ice time are "F1", the next 3 "F2", and so on; top 2 defensemen are "D1". Since every
roster carries 13 forwards and 7 defensemen, the four forward tiers and three pair tiers cover
exactly the top 12 F and top 6 D — the dressed lineup, which is the same convention the NHL figures
above are drawn from, with the 13th forward and 7th defenseman as the scratches.

Reading `Team.lines` directly looks more accurate and is wrong over a full season: the coach
line-juggling AI mutates it as the year goes (measured ~34 reshuffles per team per season, with 31
of 32 teams having changed their lines inside the first 20 days). Attributing a player's whole-season
ice time to whichever slot he occupies in game 82 averages his time across every slot he passed
through, which compresses the measured spread toward flat and hides precisely what the metric
exists to detect. The first cut of this metric did read the line chart and reported a 1.17x
top-to-bottom forward ratio while the deployment pattern was in fact producing 1.72x.

For the clean read on deployment itself, `tests/test_deployment.py` measures a single game with no
reshuffle, where slot semantics are unambiguous.

### Unbanded diagnostics

Printed for context, never asserted:

- `median_skater_goals` — depends heavily on how many 13th forwards a league carries.
- `top_shooter_shot_share_pct` — **the key diagnostic for *why* the goal leader is where he is.** A
  leader taking 22% of his team's shots is a shooter-selection problem; one taking 13% with an
  absurd conversion rate is a save-percentage problem. Measured at 24.6% pre-fix against an NHL
  ~13.5%.
- `sog_stdev_per_team_game` — the raw spread behind `pct_team_games_under_15_sog`.

## Known gaps not yet banded

Found during calibration, real but not yet worth a target band:

- **Block/miss split of non-on-goal attempts.** ~18% of shot attempts are blocked and ~29% miss,
  against a real-NHL split closer to 25% blocked / 22% missed. Driven by `block_p` in
  `engine.py::_resolve_shot_attempt`. Affects the `blocks` box-score stat only — it touches no
  shots-on-goal, goal, or save-percentage metric, since both outcomes are equally "not on goal".
  `tests/test_shot_blocking.py` asserts the block *share of attempts* (volume-independent) rather
  than a per-game count, so this stays visible without coupling the test to shot volume.
- **Rush share.** ~23% of attempts carry the rush bonus, which is in the real range, but rush is
  currently a property of "first attempt of a shift" rather than of an actual zone entry. The rate
  is right; the mechanism is a proxy.
- **Stoppage-driven counting stats are all low**: ~18 faceoffs per game (NHL ~57), ~3 giveaways and
  ~3 takeaways per team (NHL ~10 and ~7), ~5 PIM per team (NHL ~8). These are *pre-existing* and
  were not introduced by the shot-volume correction — the engine models possession as a coin-flip
  abstraction over shot-attempt cycles with no discrete turnover, whistle, goalie-freeze or
  offensive-zone-faceoff events, so there is simply nothing for most real stoppages to come from.
  Closing this properly is a feature (a real stoppage model), not a constant to retune, so no band
  is claimed for them yet.

- **First-line forward ice time runs ~4 minutes high** (24.05 vs an 18–20 band). The other three TOI
  tiers pass. The cause is almost entirely **special-teams double duty**: the same elite two-way
  forwards land on PP1 *and* PK1, because `_pk_defensive_value` ranks by a `defense` composite that a
  good two-way star tops. With PP1 taking 65% of ~5.2 power-play minutes and PK1 55% of ~5.2
  penalty-kill minutes, a forward on both collects ~6.3 minutes of special-teams time where a real
  first-liner gets ~3 on the power play and almost none on the kill. Excluding PP1 forwards from PK1
  selection is worth roughly 2.9 minutes.

  A correction worth recording, because the first diagnosis was wrong: the 20-player dress limit was
  expected to help here and does the opposite. It raised F1 from 23.65 to 24.05. Dressing 12 forwards
  instead of 13 means the same ~183 forward-minutes per game are shared by fewer players, so every
  tier rises. That is arithmetically inevitable and correct — the dress limit is right for other
  reasons (see `dressed_lineup`), just not this one.

  The upside of the limit is that the arithmetic is now clean and the bands are directly reachable:
  with exactly 12 forwards dressed, the four tier means must sum to ~61 minutes, and the NHL
  reference (19 + 16 + 14 + 11) sums to 60.

  A second-order effect once the overlap is fixed: `FORWARD_LINE_SHIFT_SHARES` is applied on *every*
  shift, but on a power-play or penalty-kill shift the chosen line doesn't actually play — the unit
  does. So a line's realized even-strength time is its share of the ~66 even-strength shifts, not of
  all ~80. Any share retuning has to account for that rather than assuming share × 61 minutes.

- **In-game fatigue is inert for skaters, and is never an input to deployment.** Two separate
  problems found 2026-07-25:
  - `FATIGUE_GAIN_PER_SEC = 0.028` against `FATIGUE_RECOVER_PER_SEC = 0.05`. Break-even is
    `0.028·f = 0.05·(1−f)`, i.e. a player only accumulates fatigue if he is on the ice for **more
    than 64% of the game**. No skater is — a first-pair defenseman plays ~40%. So every skater sits
    at ~0 fatigue all game and `fatigue_realization` returns 1.0 on essentially every shot. The
    peak of 40 measured in a game belongs to a *goalie*, who never leaves the ice and therefore
    never recovers. For a four-line rotation at 25% ice time, equilibrium needs
    `gain = 3 × recover`; the ratio is currently inverted at `gain = 0.56 × recover`.
  - Even with real fatigue, nothing reads it when choosing a line. `build_deployment_pattern` is a
    fixed allocation, so a first-line forward who just played two minutes of power play can be sent
    straight back out for a 5v5 shift. There is no cost to double-shifting and no way for a coach to
    say "line 1 is gassed, roll line 3."

  Both are prerequisites for the per-team/possession-gated shift model: a "death shift" where the
  defending team cannot change has no consequence at all if being stuck out there does not tire
  anyone.

**A rule this round learned the hard way:** any constant expressed *per shot-attempt cycle* is
coupled to shot volume, and correcting volume rescales all of them silently. Hits were tuned at
~22 per team per game and became 65 without a single line of the hit code changing. When touching
volume again, audit every `*_PER_CYCLE` / `*_PER_ATTEMPT_*` constant, and prefer asserting such
rates as a *share of attempts* rather than a count per game (see `tests/test_shot_blocking.py`).

## Changing a band

These bands are **not** placeholders in the sense the engine's first-pass tuning constants are.
Moving one is a deliberate statement about what this sim is trying to be. If you move a band, record
the reasoning here in the same commit. Do not quietly widen a band to make a failing run pass —
that converts the instrument back into decoration, which is the state that let an 82-goal defenseman
reach production in the first place.
