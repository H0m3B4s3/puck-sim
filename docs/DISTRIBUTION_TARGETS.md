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
| `goals_per_game` | 5.85 – 6.45 | **The invariant.** This was already correct before the calibration round and every change in it had to preserve it. If a fix moves goals/game, the fix is wrong even if its own metric improved. |

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
| `leader_goal_share_pct` | 0.70 – 1.10% | The leader's share of all league goals. Depth-independent: says the same thing whether the league used 640 skaters or 830. |
| `top32_goal_share_pct` | 18 – 24% | NHL ~21%. One elite scorer per team's worth. |
| `top100_goal_share_pct` | 43 – 52% | NHL ~48%. Catches over-concentration in stars — the job the `≥ 20 goals` count used to do, without the depth confound. |

The absolute goal counts (`skaters_ge_50/40/30/20_goals`) were banded until 2026-07-26 and are now
unbanded diagnostics. They are arithmetically confounded by `skaters_with_gp` and were reading the
depth gap a second time; see that date's entry below for the measurement.

### Roster depth

| Metric | Band | Why |
|---|---|---|
| `skaters_with_gp` | 760 – 880 | How many skaters appear in a game at all. NHL ~830 against 32 × 20 = 640 rostered; the balance is call-ups, waiver claims and in-season trades. **Currently fails at ~715 and is xfailed with a named cause** — it is the largest known gap left, and it confounds every absolute count above. |

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

- `skaters_ge_50/40/30/20_goals` — what a player actually sees on a leaderboard, so still printed,
  but confounded by roster depth and therefore read alongside `skaters_with_gp` rather than alone.
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

- **Staggered individual line changes** (as opposed to per-team whole-unit changes) are a deliberate
  follow-up, not an oversight. Real changes send players out a couple at a time so a line drifts
  apart and re-forms. Doing it properly means on-ice groups stop being line+pair concatenations,
  which touches chemistry, line synergy and the PP/PK unit logic — worth its own step once per-team
  clocks are calibrated. **Still open after the 2026-07-26 calibration pass**, which is the point at
  which it becomes actionable: the per-team clocks it was waiting on are now calibrated and banded.
- **Roster depth is short by ~120 skaters** (`skaters_with_gp` ~715 against an NHL ~830) and this is
  the single largest known gap left in the distribution. Call-ups closed roughly half of it
  (588 → 715); the rest needs in-season **trades and waiver claims**, which are deferred to the
  management-metagame backlog. Banded and xfailed rather than softened — see the 2026-07-26 entry.
  Anyone closing this should expect the goal-count diagnostics (≥ 20/30/40/50) to fall by roughly
  15% as a direct consequence, which is the confound that made them unusable as bands.
- **The scoring composite saturates at the 99 rating ceiling.** Ten forwards sit at composite ≥ 95
  and 23 at ≥ 90, so the sim cannot distinguish the league's best finisher from its tenth-best, and
  their goal totals cluster where the NHL's separate. Measured while trying to thin ranks 5–25 and
  failing: no shot-weight lever reaches it, because the compression is in the *input*, not the
  curve. Fixing it means thinning the upper tail of player generation, which touches team strength,
  contracts, trades and awards — a ratings round, not a calibration constant.

### Fixed 2026-07-25 — the shared 45-second horn

Play used to advance one shared "shift" at a time: `_play_period` drew ONE `shift_secs` and
`_play_shift` changed **both** teams' lines at that same boundary. That is mite hockey, where a horn
blows and everyone comes off. Play now advances in variable-length **segments** — a segment runs
until the next bench is due — with each team keeping its own shift clock and a change granted only
when that team is actually able to make one.

Three things this surfaced that are worth remembering:

- **"No puck, no change" is too strict.** The first version gated a change purely on possession, and
  it stretched the mean shift from the 45s target to **63s** with 43% of all shifts running long.
  Not every second without the puck is a defensive-zone lockdown — a team usually clears, or the puck
  goes to neutral ice. `DEFENSIVE_CHANGE_CHANCE` (0.55) restores a 48s mean with an 11% tail of
  genuinely trapped shifts, which is the real distribution: most shifts normal, a right-skewed tail.
- **A rush belongs to a zone entry, not to a clock boundary.** The pending-rush flag was first
  consumed at the start of each segment, but most segments contain no shot attempt at all, so the
  flag was burned on empty ones and the rush share collapsed from ~23% to **4.6%**. It is now
  consumed by the first *attempt* after possession turns over.
- **Both per-shift hazard rates had to become time-proportional.** `PENALTY_BASE_PROB_PER_SHIFT` and
  `IN_GAME_INJURY_RATE` are per-*shift*; rolling them once per segment unscaled would have multiplied
  both by however many segments a shift takes. Verified after: PIM/team/game 5.4 against 5.2 before
  the change. This is the third time this coupling has bitten in one round (hits, blocks, now these).

The death shift now costs something real, which is the whole point: a unit past its intended shift
length carries **21 more fatigue points** than one within it (65.6 vs 44.6, realization 0.934 vs
0.955), so being pinned in your own zone measurably degrades you.

### Fixed 2026-07-25 — recorded because the failure mode recurs

**In-game fatigue was inert for skaters and was never an input to deployment.** Two separate bugs:

- `FATIGUE_GAIN_PER_SEC = 0.028` against `FATIGUE_RECOVER_PER_SEC = 0.05`. Linear break-even sits at
  `recover / (gain + recover)` = **64% ice time**, and no skater plays that much — a first-pair
  defenseman plays ~40%. So every skater sat at ~0 fatigue all game and `fatigue_realization`
  returned 1.0 on essentially every shot. The one player who did tire was the *goalie*, who never
  leaves the ice and therefore never reaches the recovery branch.
- Nothing read fatigue when choosing a line, so a first line could go straight back out after its
  forwards had just killed two minutes on the power play. Measured: **27% of the 5v5 shifts
  immediately following a power play reused 3 or more of the players who had just been on the PP
  unit**, at no cost given the above.

The fix that matters beyond the constants: **recovery had to become exponential.** Linear recovery
cannot satisfy both requirements at once — tuned so a 45-second shift moves fatigue enough to
matter, break-even lands near 23%, and *every* player above that share accumulates without bound and
pins at the 100 ceiling. That flattens exactly the differences fatigue exists to create. Decaying a
fraction of current fatigue per second gives each ice-time share its own equilibrium, and is better
physiology besides. Measured after:

| | TOI | fatigue at shift start | at shift end | realization at end |
|---|---|---|---|---|
| 1st-pair D | 25.7 | 29.3 | 67.9 | 0.932 |
| 1st-line W | 20.6 | 19.6 | 58.0 | 0.942 |
| 4th-line F | 9.1 | 1.2 | 42.0 | 0.958 |
| goalie | 60 | — | 39.6 | — |

Nobody pinned; post-PP reuse of 3+ PP players fell to 7%; the fatigue override fires on 7.3% of line
selections, so the configured shift shares remain the coach's plan.

The goalie rate also had to be **decoupled** from the skater rate (it was `FATIGUE_GAIN_PER_SEC *
0.4`). Goalies never recover in-game, so their fatigue is a one-way ramp scaled to 60 minutes, not to
a 45-second shift — raising the skater rate 10x to make skater fatigue exist would otherwise have
pinned every goalie before the first intermission.

**A rule this round learned the hard way:** any constant expressed *per shot-attempt cycle* is
coupled to shot volume, and correcting volume rescales all of them silently. Hits were tuned at
~22 per team per game and became 65 without a single line of the hit code changing. When touching
volume again, audit every `*_PER_CYCLE` / `*_PER_ATTEMPT_*` constant, and prefer asserting such
rates as a *share of attempts* rather than a count per game (see `tests/test_shot_blocking.py`).

### Fixed 2026-07-25 — teams were playing short, and it inflated everything

**There was no in-season call-up.** Promotion out of the development tiers ran only in the
offseason (`prospects.promote_ready_prospects`), so a team that lost a third skater to injury in
November played short until he healed. Teams carry 20 skaters and dress 18, so exactly two injuries
were absorbable. Measured over one 82-day regular season, seed 7:

| dressed skaters | 15 | 16 | 17 | 18 |
|---|---|---|---|---|
| team-days | 19 | 74 | 270 | 2261 |

**13.8% of team-days dressed fewer than 18 skaters.** Nothing reported it — the sim plays such a
game short-handed by design (`DressedLineup.short_skaters`) rather than refusing to sim it, so the
only visible symptom was in the distribution.

That symptom is the reason this belongs in this document rather than in a roster-management round: a
shortfall concentrates a fixed amount of ice time onto fewer players, and it was the largest single
contributor to the goal histogram running hot. `systems/callups.py` closed it, and both the depth and
the top of the distribution moved a long way:

| | before | after | reference |
|---|---|---|---|
| team-days dressing < 18 skaters | 13.8% | **0%** | 0% |
| skaters with GP > 0 | 588 | **706** | NHL ~830 |
| goal leader | 93 | **55** | 50–66 |
| leader's share of team SOG | 17.7% | **12.95%** | ~13.5% |

Three things worth remembering:

- **The triggers are stateless on purpose.** Call up below 18 healthy skaters, send down above
  `SKATERS_MAX`. A team is only ever above `SKATERS_MAX` because a call-up put it there, so the
  second rule returns exactly what the first added with nothing persisted. A "this player is on a
  call-up" flag would have to survive save/load, trades and the offseason, and any path that dropped
  it would strand a player on an NHL roster forever. It also means old saves self-correct on the
  first day advanced.
- **A recall has to be able to break the 23-man ceiling, and must not break the cap.** Injured
  players stay on `Team.roster`, so a team with three men hurt sits at the ceiling with twenty
  healthy bodies. Waiving the ceiling alone put two teams over the cap by up to $2.6M — the exact
  class of hard-cap leak `cap.can_sign` was hardened against. The fix is the real rule:
  `cap.injury_relief` (LTIR) gives such a team room equal to its long-term absences, after which 0
  teams finish over. Relief is keyed to `Injury.severity`, not `games_remaining`, because a
  counting-down clock would silently expire in the last week of a long absence and flip a legal
  roster illegal with nothing having happened.
- **The farm is thinner than expected at defense.** Five teams finished a season with zero signed
  defense prospects, so a defense shortfall falls back to recalling a forward. Dressing a full
  complement out of position beats dressing 17.
- **The postseason was the worse half.** `advance_playoff_slate` ran no roster maintenance *and*
  never called `_heal_injuries` at all, so a man hurt in game 1 of round 1 was out for the entire
  playoffs however minor the knock, with nobody able to replace him. Two months of attrition with no
  healing and no reinforcements compounds every round: **42% of playoff team-games dressed fewer
  than 18 skaters, one as few as 11**, against 13.8% of regular-season team-days. Both hooks now run
  around each slate exactly as they do around each regular-season day; playoff games now dress 18
  every time. Worth noting the missing heal was a *pre-existing* bug that this measurement found
  rather than one the call-up work introduced.

The residual gap to the NHL's ~830 skaters is trades, waiver churn and 23-man rosters rotating three
healthy scratches rather than two — real, but a management-metagame feature rather than a constant.

### Fixed 2026-07-25 — a quarter of all assists never existed

Primary 0.80 and secondary 0.55 compound to **1.24 assists per goal** against a real ~1.70. Assists
are most of a centre's point total, so this flattened the entire points leaderboard and was why the
point leader read *low* (85) at the same time the goal leader read *high*. Set from the real
unassisted-goal rate (~8% of goals): 0.92 and 0.85 compound to 1.70. Measured 1.69; the point leader
moved to 103.

`OnIceCache.playmaking_weights` was computed on every line change and **never read** —
`_pick_assists` recomputed its own copy inline, in the `max(0.5, playmaking - 20)` form that
`build_on_ice_cache` had already abandoned for shooting. Now consumed, in pivot/slope form.

**The D-assist share is mostly structural, and the first fix for it made it worse.** The scorer is
excluded from his own assist pool and forwards score ~83% of goals, so the pool is 2F+2D far more
often than 3F+1D — about 45% D on headcount before any rating is consulted. Weighting the *primary*
assist alone (on the theory that leaving the secondary untouched expressed the real asymmetry) moved
D from 42.3% to **48.2%**: raising the rates had shifted the mix toward secondaries, 35% → 46% of all
assists, so a primary-only lever was pulling on the shrinking half. Expressing the asymmetry as a
*ratio* between two multipliers (0.60 primary, 0.80 secondary) instead of a multiplier and a zero
controls the total while keeping the shape. Now ~35–44% across seeds against a real ~36%.

The general lesson, which has now cost time twice this round: when a rate change moves the *mix*
between two channels, a lever attached to only one of them changes strength as a side effect.

**Two latent bugs surfaced by the RNG churn**, neither related to assists — both worth recording
because the mechanism ("a stream shift changed which branch a game took, and the branch was wrong")
will recur:

- **A pulled goalie recovered like a resting skater.** `_apply_ice_time` skips the goalie by
  matching `state.goalie_id`, which is `None` while he is pulled — so the pulled goalie stopped
  being skipped and fell into the skater *rest* branch, decaying at the skater recovery constant.
  A 60-second pull shed **39.6 fatigue down to 11.7**, handing a team that pulled its goalie a
  materially fresher one for overtime. Now matched on `starter_goalie_id` as well.
- **`test_engine`'s goalie-goals-against invariant did not account for the shootout decider.** A
  shootout win awards a goal in the final score charged to nobody's save percentage, exactly like
  an empty-net goal — which that test already handled. Correct behavior, incomplete assertion; it
  only ever passed because seed 12 had not previously gone to a shootout.

**And one more underpowered test**, the same failure mode as `test_clutch.py` earlier in this round:
`test_post_power_play_double_shifting_is_rare` sampled ~15 post-PP shifts from 20 games and asserted
a rate against a 15% threshold. At a true rate of 9.0% (measured over 233 samples) a 15-sample
estimate clears that threshold about one run in twenty, and duly did on a change that merely shifted
the RNG stream. Now sampled over 200 games. **Assert rates on samples big enough to carry them** —
widening the band would have hidden the real 9%.

### Fixed 2026-07-26 — the name pool read as a current NHL roster

Not a distribution metric, but the third of the three playtest reports this round addressed, and it
records a rule worth keeping.

223 first / 289 last names in two flat tuples, drawn independently, against 700+ players per league.
Now 792 first / 2632 last across 12 nationality pools — **205,000+ coherent combinations** — with
nationality drawn *first* so both halves of a name come from the same pool. The old independent
draws produced men called "Miro Gagnon" and "Jean-Sebastien Ovechkin"; a league now reads
"Heikki Ojala", "Jesper Bergsten", "Manuel Schreiber".

**The purge rule is distinctiveness, not overlap**, and that distinction is the whole point. The old
pools carried an explicit block commented "recognizable hockey name seed set" — McDavid, Crosby,
Draisaitl, Ovechkin, Pastrnak, Selanne, Chara — which is what made generated teams look like a
shuffled real NHL. All of those are gone. What is deliberately *not* attempted is eliminating all
overlap with real NHL surnames, because that goal is incoherent: the common surnames of every hockey
nation have someone in the league, and removing every one of them leaves pools of nothing but rare
names, which reads *more* artificial. A name is out if it reads as a reference to one specific real
person (`McDavid`, `Kaprizov`, `Lemieux`, and also `Coolidge`, `Kafka`, `Earnhardt`); it stays if it
reads as an ordinary name someone real happens to have (`Smith`, `Tremblay`, `Roy`, `Novak`).

Applying that rule caught a mistake in the first pass: the five most common Swedish surnames
(Andersson, Johansson, Karlsson, Nilsson, Eriksson) had all been dropped along with the marquee
names, which is exactly the over-correction the rule exists to prevent. Restored, with a test that
now fails if someone "fixes" them out again.

Two determinism choices worth knowing about:

- Draws use `pool[int(rng.random() * len(pool))]`, not `rng.choice(pool)`. `random.choice` consumes
  a variable number of bits by sequence length, so under it adding a *single name* shifted the whole
  downstream RNG stream — ratings, ages, everything, since they share one `Rng`. Future name
  additions are now stream-neutral. This round's restructuring shifts old seeds regardless; that is
  a one-time cost paid to stop paying it.
- `World.used_player_names` is derived, maintained in `add_player` (the single seam every generator
  funnels through) and **rebuilt on load rather than serialized**, so it cannot drift out of sync
  with `players` the way a persisted copy could, and old saves get a correct one free. Duplicate
  full names in a generated league: 0, from 3.

### Fixed 2026-07-26 — a team finished an offseason with three defensemen

Found by the name-pool change, which shifted the RNG stream and moved which roster a seed produced.
After one simulated offseason a team held **17 forwards and 3 defensemen** — twenty skaters, a legal
headcount, and only two defense pairs (the second of them a single player). It surfaced as a
four-man power-play unit; had it not, three defensemen would have played roughly forty minutes each
for a season.

`offseason.fill_rosters` was position-aware for goalies versus skaters and its docstring explained
exactly why — "filling by *just add the best available free agent regardless of position* would
never notice, since skater free agents vastly outnumber goalie free agents". The same sentence is
true one level down: forward free agents outnumber defense free agents about two to one, so a team
that lost blueliners got refilled with forwards. `config.FORWARDS_MIN`/`DEFENSEMEN_MIN` now gate
`fill_rosters` and `enforce_roster_max` the same way `GOALIES_MIN` does. Every team now finishes an
offseason with 6–10 defensemen.

**`systems/callups.py` had the identical gap**, written three steps earlier in this same round: it
triggered on total headcount only, so 15 forwards and 5 defensemen — twenty healthy skaters — looked
perfectly fine to it. A position group below its own floor is now a trigger in its own right. That
required fixing the send-down half too: a recall for a position shortfall pushes the roster over
`SKATERS_MAX`, and an unrestricted send-down would hand back the man just recalled and do it again
the next day forever. Restricted to groups with slack above their floor, it gives back a forward and
settles.

The lesson is not "check positions" but something narrower and more useful: **when a rule protects a
whole by a minimum, check whether the whole has parts that need their own.** Goalies-vs-skaters was
already understood here; forwards-vs-defensemen is the same shape and was missed in three separate
places.

The first version of the `fill_rosters` half was itself wrong, and instructively so. `fill_rosters`
only ever *adds*, and `enforce_roster_max` runs immediately before it — so a team sitting at twenty
skaters with five defensemen had a hole it could not fill by adding, and filling anyway put three
teams one over `ROSTER_MAX` (which in turn broke the hard cap, since the extra bodies carry salary).
A position floor on a full roster is a **swap**, not an addition: waive the worst surplus forward,
sign the defenseman, exactly as a real GM does. Verified stable over three consecutive simulated
seasons — every team legal, no short special-teams units, no cap breaches.

**A fourth underpowered test**, same failure mode as the three before it:
`test_defensemen_take_a_realistic_share_of_shots_and_convert_far_worse` sampled 10 games — about 155
defense shots on goal — and asserted a conversion ratio. At a true 6.5% that estimate swings across
5–9% run to run, and it duly read 9.0% on a change that only moved the RNG stream. At 150 games
(~2200 D shots) it reads 6.5% and the ratio is a stable 0.70. Four times in one round is a pattern
worth stating plainly: **a rate assertion needs a sample sized for the rate, and the fix is always
more samples, never a wider band.**

### 2026-07-26 — the joint calibration pass, and a band change with its reasoning

The round's closing step. Calibrated against **four seeds (3/7/11/19), not one** — single-seed tuning
is what produced the step-5 mistake, where the goal leader swung 66/89/72 across three adjacent
slope values on the same seed.

Two constants moved, both measured into place rather than derived:

- `SAVE_PROB_ANCHOR`, to bring goals/game back to the middle of its band (four seeds had drifted to
  a 5.65 mean, with one at 5.31).
- The defenseman zone/shot-type frequency tables, pushed further to the perimeter. D were converting
  at **6.5% against a real ~4.5%** while their share of shot *attempts* was already right (~27% vs
  ~26%). A conversion gap with correct volume is a shot-**quality** statement, so it belongs in the
  frequency mix — which keeps xG coherent per position — not in a penalty on D shots. Mean D shot
  quality 0.420 → 0.389. D share of goals 18.0% → ~15%.

#### The goal-count bands were measuring the wrong thing, and are now shares

**This is a band change, so here is the reasoning, as this document requires.**

`skaters_ge_50/40/30/20_goals` failed on every seed and no shape lever could fix them. Sweeping the
shot-weight slope **up** made them worse (≥40 rose 21.8 → 24.3, because it separates good shooters
from bad ones, not #1 from #10). Sweeping it **down** bought the top tiers only by dumping goals into
≥20. That is the signature of a metric that is not measuring what you think it is.

It wasn't. The counts are arithmetically confounded by how many skaters played:

| | ours | NHL |
|---|---|---|
| total goals | ~7800 | ~8000 |
| skaters who played | 706 | ~830 |
| **goals per skater** | **11.0** | **9.6** |

Apply that 15% difference to our own measured rank curve — 60/51/47/37/29/22 at ranks
1/5/10/25/50/100 — and it becomes 51/43/40/31/25/19, which puts **every count inside the bands they
were failing**. The rank curve itself already matches the NHL closely from rank 50 down. The counts
were reading the depth gap a second time, in a place where it looked like a shape problem.

So concentration is now banded on **depth-independent shares** — the leader's, the top 32's and the
top 100's share of league goals — which measure the same property without the confound, and which
were *already correct* when the counts were failing badly (top 32 at 20.7% vs a real 21%, top 100 at
47.1% vs 48%). That discrepancy is what exposed the problem in the first place.

The counts are still printed, as unbanded diagnostics. They are what a player sees on a leaderboard,
and they are read alongside `skaters_with_gp`, not instead of it.

#### Depth is now its own banded metric, and it fails

`skaters_with_gp` is banded at the NHL reference (760–880) and measures ~715. **It is left failing,
as an xfail with a named cause, rather than softened to match.** 32 × 20 rostered skaters is 640; the
balance is call-ups — which this round added, moving 588 → 715 — plus in-season **trades and waiver
claims**, which are deliberately deferred to the management-metagame backlog. The sim cannot reach
the NHL figure until those exist.

That is the whole point of the re-expression: one honest failure, in the place where the deficiency
actually is, replacing four symptoms of it scattered across the leaderboard block. If a later round
adds trades and depth rises, the xfail reports XPASS and asks to be promoted back.

#### The lock, and a fifth sample-size lesson

`tests/test_distribution.py` runs the same four seeds the bands were calibrated against and asserts
the **mean**, printing per-seed values on failure so "one odd league" is distinguishable from "the
calibration moved". The first version measured one season and failed three bands the four-seed mean
passes comfortably (seed 7 reads D goal share 17.5 against a 15.7 mean, and a 71-goal leader against
65). That is the fifth time in this round a test asserted a statistic on a sample too small to carry
it, and the fifth time the fix was more samples rather than a wider band.

A sixth, in the same pass: `test_an_injured_forwards_minutes_go_to_forwards` asserted that the top
three beneficiaries of an injury are all forwards. Some defense gain is *correct*, not leakage — an
injured first-line forward is also a power-play forward, and his unit's minutes genuinely pass to
the defensemen on it. Measured across five seeds, forwards take 77–88% of the redistribution and the
top gainer is a forward every time. Now asserted as that share.

The pattern across all six is one thing: **an assertion about a rate, a share or a ranking needs to
be phrased over the population that actually carries it.** Four were fixed by widening the sample,
two by measuring the aggregate property instead of a fragile instance of it. None by moving a band.

## Changing a band

These bands are **not** placeholders in the sense the engine's first-pass tuning constants are.
Moving one is a deliberate statement about what this sim is trying to be. If you move a band, record
the reasoning here in the same commit. Do not quietly widen a band to make a failing run pass —
that converts the instrument back into decoration, which is the state that let an 82-goal defenseman
reach production in the first place.
