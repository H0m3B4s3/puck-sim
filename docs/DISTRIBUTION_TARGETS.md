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

### Unbanded diagnostics

Printed for context, never asserted:

- `median_skater_goals` — depends heavily on how many 13th forwards a league carries.
- `top_shooter_shot_share_pct` — **the key diagnostic for *why* the goal leader is where he is.** A
  leader taking 22% of his team's shots is a shooter-selection problem; one taking 13% with an
  absurd conversion rate is a save-percentage problem. Measured at 24.6% pre-fix against an NHL
  ~13.5%.
- `sog_stdev_per_team_game` — the raw spread behind `pct_team_games_under_15_sog`.

## Changing a band

These bands are **not** placeholders in the sense the engine's first-pass tuning constants are.
Moving one is a deliberate statement about what this sim is trying to be. If you move a band, record
the reasoning here in the same commit. Do not quietly widen a band to make a failing run pass —
that converts the instrument back into decoration, which is the state that let an 82-goal defenseman
reach production in the first place.
