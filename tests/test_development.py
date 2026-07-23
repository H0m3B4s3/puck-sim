"""Tests for pucksim.systems.development -- DEVPLAN.md Step 2.7 done-criteria.

Covers, in order:
  1. The permanent age-based development curve (_overall_delta/_apply_delta/develop_player):
     young players trend upward on average, prime-age players plateau, old players decline --
     and none of it lets ratings escape the legal [25, 99] band.
  2. THE key statistical evidence this step must produce (per DEVPLAN.md's explicit done
     criteria): over many simulated offseasons, a high-gk_consistency goalie's season-to-season
     "form" output shows a MEASURABLY TIGHTER distribution than a low-gk_consistency goalie's,
     AND the long-run average for any given goalie stays centered near their true rating --
     proving the variance is symmetric scatter around an unchanging mean, not a systematic
     upward or downward drift. This directly exercises resample_goalie_form/apply_goalie_form/
     GoalieFormState.
  3. A direct audit that the mechanism can never collapse into a one-sided ceiling (the
     explicit "don't conflate this with no-upweighting" bug this module's docstring warns
     against) -- form must land above FORM_BASELINE roughly as often as below it.
"""
from __future__ import annotations

import statistics

from pucksim import config
from pucksim.models import attributes as attr
from pucksim.models.player import Player
from pucksim.rng import Rng
from pucksim.systems import development as D


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_skater(pid: int = 1, age: int = 25, overall: int = 70, potential: int = None,
                 **overrides) -> Player:
    ratings = {name: overall for name in attr.ALL_RATINGS}
    ratings.update(overrides.pop("ratings_overrides", {}))
    kwargs = dict(
        pid=pid, name=f"Skater {pid}", age=age, position="C",
        ratings=ratings, potential=potential if potential is not None else overall,
    )
    kwargs.update(overrides)
    return Player(**kwargs)


def make_goalie(pid: int = 1, age: int = 27, overall: int = 70, gk_consistency: int = 70,
                 **overrides) -> Player:
    ratings = {name: overall for name in attr.ALL_GOALIE_RATINGS}
    ratings["gk_consistency"] = gk_consistency
    kwargs = dict(
        pid=pid, name=f"Goalie {pid}", age=age, position="G",
        ratings=ratings, potential=overall,
    )
    kwargs.update(overrides)
    return Player(**kwargs)


# ---------------------------------------------------------------------------
# 1. Permanent age-based development curve
# ---------------------------------------------------------------------------
def test_young_player_below_peak_trends_upward_toward_potential():
    rng = Rng(seed=1)
    deltas = []
    for i in range(300):
        p = make_skater(pid=i, age=19, overall=55, potential=85)
        deltas.append(D.develop_player(p, rng))
    assert statistics.mean(deltas) > 0.5   # clearly net-positive on average


def test_prime_age_player_plateaus_near_zero_on_average():
    rng = Rng(seed=2)
    deltas = []
    for i in range(500):
        p = make_skater(pid=i, age=(config.PEAK_AGE_LOW + config.PEAK_AGE_HIGH) // 2,
                         overall=80, potential=80)
        deltas.append(D.develop_player(p, rng))
    # Plateau band: small symmetric noise, no systematic drift either way.
    assert abs(statistics.mean(deltas)) < 1.0


def test_old_player_past_peak_declines_on_average():
    rng = Rng(seed=3)
    deltas = []
    for i in range(300):
        p = make_skater(pid=i, age=36, overall=75, potential=75)
        deltas.append(D.develop_player(p, rng))
    assert statistics.mean(deltas) < -0.5


def test_development_never_pushes_ratings_outside_legal_band():
    rng = Rng(seed=4)
    for i in range(500):
        age = rng.randint(18, 42)
        p = make_skater(pid=i, age=age, overall=rng.randint(25, 99), potential=rng.randint(25, 99))
        D.develop_player(p, rng)
        assert all(config.RATING_MIN <= v <= config.RATING_MAX for v in p.ratings.values())


def test_goalie_develop_player_only_touches_goalie_rating_vocabulary():
    """develop_player on a goalie must never write a skater-only rating key (e.g. 'skating')."""
    rng = Rng(seed=5)
    p = make_goalie(pid=1, age=30, overall=72)
    D.develop_player(p, rng)
    assert set(p.ratings.keys()) == set(attr.ALL_GOALIE_RATINGS)


# ---------------------------------------------------------------------------
# 2. Goalie season-form variance -- THE key design-note evidence
# ---------------------------------------------------------------------------
N_SEASONS = 4000


def test_high_consistency_goalie_has_tighter_form_spread_than_low_consistency_goalie():
    """Core DEVPLAN.md done-criterion: high gk_consistency -> measurably TIGHTER season-to-
    season output distribution than low gk_consistency, sampled over many simulated offseasons.
    """
    rng = Rng(seed=100)
    high = make_goalie(pid=1, gk_consistency=99)
    low = make_goalie(pid=2, gk_consistency=25)

    high_forms = [D.resample_goalie_form(high, rng) for _ in range(N_SEASONS)]
    low_forms = [D.resample_goalie_form(low, rng) for _ in range(N_SEASONS)]

    high_stdev = statistics.stdev(high_forms)
    low_stdev = statistics.stdev(low_forms)

    # Must be measurably tighter, not just marginally -- assert a real gap, not noise.
    assert high_stdev < low_stdev * 0.5
    # Sanity: spreads should roughly track the documented anchor constants.
    assert abs(high_stdev - D._FORM_SPREAD_AT_MAX_CONSISTENCY) < 0.01
    assert abs(low_stdev - D._FORM_SPREAD_AT_MIN_CONSISTENCY) < 0.01


def test_form_spread_monotonic_in_gk_consistency():
    """Spread should shrink monotonically as gk_consistency rises across the whole scale, not
    just at the two extremes."""
    rng = Rng(seed=101)
    consistencies = [25, 40, 55, 70, 85, 99]
    stdevs = []
    for c in consistencies:
        g = make_goalie(pid=1, gk_consistency=c)
        forms = [D.resample_goalie_form(g, rng) for _ in range(N_SEASONS)]
        stdevs.append(statistics.stdev(forms))
    for a, b in zip(stdevs, stdevs[1:]):
        assert b <= a + 1e-9   # non-increasing as consistency rises


def test_goalie_form_average_stays_centered_near_true_rating_symmetric_scatter():
    """Core DEVPLAN.md done-criterion: the long-run AVERAGE across many seasons for any given
    goalie -- both high and low consistency -- stays centered near FORM_BASELINE (1.0, i.e.
    their true established rating), proving this is symmetric scatter, not systematic drift in
    either direction."""
    rng = Rng(seed=102)
    for consistency in (25, 50, 70, 90, 99):
        g = make_goalie(pid=1, gk_consistency=consistency)
        forms = [D.resample_goalie_form(g, rng) for _ in range(N_SEASONS)]
        mean_form = statistics.mean(forms)
        # Centered on FORM_BASELINE within a small tolerance -- not drifting up or down.
        assert abs(mean_form - D.FORM_BASELINE) < 0.01


def test_goalie_form_is_symmetric_not_a_one_sided_ceiling():
    """Direct audit against this module's own explicit warning: form must land ABOVE
    FORM_BASELINE roughly as often as it lands below -- a one-sided cap (the no-upweighting-
    style bug this docstring explicitly warns against) would show a lopsided above/below split
    instead of ~50/50."""
    rng = Rng(seed=103)
    g = make_goalie(pid=1, gk_consistency=25)   # widest spread -- most sensitive to asymmetry
    forms = [D.resample_goalie_form(g, rng) for _ in range(N_SEASONS)]
    above = sum(1 for f in forms if f > D.FORM_BASELINE)
    below = sum(1 for f in forms if f < D.FORM_BASELINE)
    frac_above = above / (above + below)
    assert 0.45 < frac_above < 0.55


def test_goalie_form_can_exceed_1_0_this_is_not_a_no_upweighting_violation():
    """Explicit regression guard for the exact mistake this module's docstring warns a future
    reader against: form values ABOVE 1.0 (a "breakout" season) must be reachable -- if a future
    change clamps form to FORM_MAX == FORM_BASELINE (i.e. <= 1.0), this test catches it."""
    rng = Rng(seed=104)
    g = make_goalie(pid=1, gk_consistency=25)
    forms = [D.resample_goalie_form(g, rng) for _ in range(2000)]
    assert max(forms) > 1.05
    assert min(forms) < 0.95


def test_goalie_form_is_bounded_within_documented_clamp():
    rng = Rng(seed=105)
    for consistency in (25, 60, 99):
        g = make_goalie(pid=1, gk_consistency=consistency)
        for _ in range(2000):
            form = D.resample_goalie_form(g, rng)
            assert D.FORM_MIN <= form <= D.FORM_MAX


def test_goalie_form_does_not_permanently_mutate_ratings():
    """Resampling form must never touch the goalie's true ratings dict -- a bust/breakout
    season is temporary, per this module's central design constraint."""
    rng = Rng(seed=106)
    g = make_goalie(pid=1, gk_consistency=40)
    before = dict(g.ratings)
    for _ in range(500):
        D.resample_goalie_form(g, rng)
    assert g.ratings == before


# ---------------------------------------------------------------------------
# GoalieFormState / apply_goalie_form / resample_all_goalie_form
# ---------------------------------------------------------------------------
def test_goalie_form_state_defaults_to_baseline_for_unresampled_goalie():
    state = D.GoalieFormState()
    assert state.get(pid=999) == D.FORM_BASELINE


def test_apply_goalie_form_scales_rating_by_current_form():
    state = D.GoalieFormState()
    g = make_goalie(pid=7, gk_consistency=70)
    state.form[7] = 1.10
    assert D.apply_goalie_form(80.0, g, state) == 88.0


def test_apply_goalie_form_can_scale_above_the_raw_rating_value():
    """Direct proof apply_goalie_form is not artificially capped at the input value -- a
    breakout-season form (>1.0) must be able to scale a rating UP, not just down."""
    state = D.GoalieFormState()
    g = make_goalie(pid=7, gk_consistency=70)
    state.form[7] = 1.20
    scaled = D.apply_goalie_form(80.0, g, state)
    assert scaled > 80.0


def test_resample_all_goalie_form_only_touches_goalies():
    from pucksim.gen.leaguegen import build_world
    world = build_world(seed=9)
    state = D.GoalieFormState()
    D.resample_all_goalie_form(world, state)
    goalie_pids = {p.pid for p in world.players.values() if p.is_goalie}
    assert set(state.form.keys()) == goalie_pids
    for pid in goalie_pids:
        assert D.FORM_MIN <= state.form[pid] <= D.FORM_MAX


def test_develop_all_with_form_state_resamples_every_goalie():
    from pucksim.gen.leaguegen import build_world
    world = build_world(seed=11)
    state = D.GoalieFormState()
    D.develop_all(world, form_state=state)
    goalie_pids = {p.pid for p in world.players.values() if p.is_goalie}
    assert set(state.form.keys()) == goalie_pids


def test_develop_all_without_form_state_is_a_pure_no_op_for_form():
    """develop_all(world) with no form_state must still develop everyone (permanent aging)
    but must not require/construct any goalie-form machinery -- callers that don't care about
    the goalie-form mechanic can omit it entirely."""
    from pucksim.gen.leaguegen import build_world
    world = build_world(seed=12)
    before_overalls = {pid: p.overall for pid, p in world.players.items()}
    D.develop_all(world)   # no form_state passed
    after_overalls = {pid: p.overall for pid, p in world.players.items()}
    assert before_overalls != after_overalls   # aging still happened


# ---------------------------------------------------------------------------
# 4. Tier-aware opportunity (docs/PROSPECT_DEV_PLAN.md Phase 3)
# ---------------------------------------------------------------------------
def _in_tier(player: Player, tier: str, tier_seasons: int = 1) -> Player:
    player.development = {"tier": tier, "seasons": tier_seasons,
                          "tier_seasons": tier_seasons, "rights_tid": 1,
                          "rights_expire": 9999, "line": {}}
    return player


def test_a_prospects_opportunity_comes_from_his_tier_not_his_empty_stat_line():
    """THE bug this phase fixes. A prospect never plays an NHL game, so the ice-time
    formula divides into a zero and hands every prospect in the league the same flat 0.6 --
    age, tier, role and ice time all irrelevant. Four carefully specified tiers behaving
    identically is a silent failure, so it's asserted directly."""
    factors = {tier: D._opportunity_factor(_in_tier(make_skater(age=19), tier))
               for tier in config.DEV_TIERS}
    assert len(set(factors.values())) > 1, f"every tier develops identically: {factors}"
    assert factors[config.DEV_TIER_AHL] > factors[config.DEV_TIER_NCAA]
    assert factors[config.DEV_TIER_CHL] > factors[config.DEV_TIER_NCAA]


def test_the_first_season_in_the_ahl_is_an_adjustment_year():
    rookie = D._opportunity_factor(_in_tier(make_skater(age=20), config.DEV_TIER_AHL,
                                             tier_seasons=0))
    settled = D._opportunity_factor(_in_tier(make_skater(age=21), config.DEV_TIER_AHL,
                                              tier_seasons=1))
    assert rookie < settled
    assert rookie == config.TIER_DEVELOPMENT[config.DEV_TIER_AHL] * config.TIER_FIRST_SEASON_PENALTY


def test_a_rostered_player_is_still_scored_on_ice_time():
    """The NHL branch is HoopR's own rule and must survive untouched: a young player buried
    in a limited role develops slower than one getting real minutes."""
    buried = make_skater(age=20)
    buried.season.gp, buried.season.secs = 20, 20 * 6 * 60      # 6 min/game
    workhorse = make_skater(age=20)
    workhorse.season.gp, workhorse.season.secs = 82, 82 * 19 * 60
    assert D._opportunity_factor(buried) < D._opportunity_factor(workhorse)
    assert not buried.is_prospect


def test_tier_opportunity_shares_the_scale_with_nhl_ice_time():
    """Prospects and young NHL regulars are scored on one 0.6-1.4 band, so a tier factor
    can be compared against an ice-time factor without a second calibration."""
    for tier in config.DEV_TIERS:
        f = D._opportunity_factor(_in_tier(make_skater(age=19), tier))
        assert 0.6 <= f <= 1.4, (tier, f)


def test_playing_in_a_better_tier_produces_more_growth_over_a_career():
    """The end-to-end consequence: the same player develops further in the AHL than in
    college, which is what makes the tier assignment a decision worth caring about."""
    def grow(tier, seed):
        rng = Rng(seed=seed)
        player = _in_tier(make_skater(age=19, overall=55, potential=85), tier)
        for _ in range(4):
            D.develop_player(player, rng)
            player.age += 1
            player.development["tier_seasons"] += 1
        return player.overall

    pro = statistics.mean(grow(config.DEV_TIER_AHL, s) for s in range(40))
    college = statistics.mean(grow(config.DEV_TIER_NCAA, s) for s in range(40))
    assert pro > college


# ---------------------------------------------------------------------------
# 5. Busts busting (potential erosion)
# ---------------------------------------------------------------------------
def test_a_stalled_prospect_loses_potential():
    """Before this, the convergence rule only started at PEAK_AGE_LOW + 1 (25), so a
    19-year-old with 85 potential kept every point of it until he was 25 and no prospect
    ever stopped being one who might still make it."""
    rng = Rng(seed=4)
    player = _in_tier(make_skater(age=config.PROSPECT_STAGNATION_AGE, overall=50,
                                   potential=85), config.DEV_TIER_NCAA)
    assert D._is_stagnating(player)
    before = player.potential
    D.develop_player(player, rng)
    assert player.potential < before


def test_a_prospect_who_reached_nhl_caliber_is_not_stagnating():
    player = _in_tier(make_skater(age=22, overall=config.NHL_READY_OVERALL, potential=85),
                       config.DEV_TIER_AHL)
    assert not D._is_stagnating(player)


def test_a_young_prospect_keeps_his_ceiling():
    """Erosion starts at PROSPECT_STAGNATION_AGE -- an 18-year-old is not a bust yet."""
    player = _in_tier(make_skater(age=config.PROSPECT_STAGNATION_AGE - 1, overall=50,
                                   potential=85), config.DEV_TIER_CHL)
    assert not D._is_stagnating(player)


def test_stagnation_never_drops_potential_below_current_overall():
    """Downward-only, and floored at overall, so it can't disturb the league-wide
    conservation _overall_delta depends on."""
    rng = Rng(seed=9)
    player = _in_tier(make_skater(age=23, overall=60, potential=61), config.DEV_TIER_AHL)
    for _ in range(10):
        D.develop_player(player, rng)
    assert player.potential >= player.overall


def test_a_player_outside_the_development_system_never_stagnates():
    """An undrafted 22-year-old free agent isn't in anyone's system to stall in."""
    player = make_skater(age=22, overall=50, potential=85)
    assert not player.is_prospect
    assert not D._is_stagnating(player)
