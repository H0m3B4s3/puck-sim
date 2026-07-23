"""Tests for pucksim.config — standings rule presets and rating bounds."""
from pucksim import config


def test_all_three_standings_presets_exist():
    assert set(config.STANDINGS_RULES.keys()) == {
        "standard",
        "retro",
        "three_two_one_zero",
    }


def test_default_standings_rule_is_valid_key():
    assert config.DEFAULT_STANDINGS_RULE in config.STANDINGS_RULES
    assert config.DEFAULT_STANDINGS_RULE == "standard"


def test_standard_rule_point_values():
    rule = config.STANDINGS_RULES["standard"]
    assert rule["reg_win"] == 2
    assert rule["ot_win"] == 2
    assert rule["so_win"] == 2
    assert rule["ot_loss"] == 1
    assert rule["so_loss"] == 1
    assert rule["reg_loss"] == 0
    assert rule["has_shootout"] is True
    # A win always outscores an OT/SO loss, which always outscores a regulation loss.
    assert rule["reg_win"] > rule["ot_loss"] > rule["reg_loss"]
    assert rule["ot_win"] > rule["ot_loss"]


def test_retro_rule_point_values_and_no_shootout():
    rule = config.STANDINGS_RULES["retro"]
    assert rule["reg_win"] == 2
    assert rule["ot_win"] == 2
    assert rule["ot_loss"] == 1
    assert rule["reg_loss"] == 0
    assert rule["tie"] == 1
    assert rule["has_shootout"] is False
    # Shootout outcomes are unreachable under retro rules.
    assert rule["so_win"] is None
    assert rule["so_loss"] is None
    # A win outscores a tie, which outscores a loss.
    assert rule["reg_win"] > rule["tie"] > rule["reg_loss"]


def test_three_two_one_zero_rule_point_values():
    rule = config.STANDINGS_RULES["three_two_one_zero"]
    assert rule["reg_win"] == 3
    assert rule["ot_win"] == 2
    assert rule["so_win"] == 2
    assert rule["ot_loss"] == 1
    assert rule["so_loss"] == 1
    assert rule["reg_loss"] == 0
    assert rule["has_shootout"] is True
    # The whole point of this scheme: regulation wins are worth strictly more
    # than wins that required extra time.
    assert rule["reg_win"] > rule["ot_win"]
    assert rule["ot_win"] > rule["ot_loss"] > rule["reg_loss"]


def test_standings_rules_internally_consistent_across_presets():
    # Regardless of rule, a regulation win should never be worth less than an
    # OT/SO win, and any win should never be worth less than any loss/tie.
    for name, rule in config.STANDINGS_RULES.items():
        non_none_losses = [
            v for k, v in rule.items()
            if k in ("ot_loss", "so_loss", "reg_loss", "tie") and v is not None
        ]
        non_none_wins = [
            v for k, v in rule.items()
            if k in ("reg_win", "ot_win", "so_win") and v is not None
        ]
        assert min(non_none_wins) >= max(non_none_losses), name
        assert rule["reg_win"] >= rule["ot_win"], name


def test_rating_bounds():
    assert config.RATING_MIN == 25
    assert config.RATING_MAX == 99
    assert config.RATING_MIN < config.RATING_MAX


# ---------------------------------------------------------------------------
# Development tiers / entry-level contracts (docs/PROSPECT_DEV_PLAN.md)
# ---------------------------------------------------------------------------
def test_every_dev_tier_has_an_age_band():
    """systems/prospects.py indexes DEV_TIER_AGE_BANDS by tier without a fallback -- a
    tier added to DEV_TIERS but not to the bands would raise on assignment."""
    assert set(config.DEV_TIER_AGE_BANDS) == set(config.DEV_TIERS)
    for tier, (lo, hi) in config.DEV_TIER_AGE_BANDS.items():
        assert lo < hi, tier
        assert hi <= config.MAX_PROSPECT_AGE, tier


def test_dev_tiers_are_valid_league_origins_where_they_overlap():
    """Origin and tier share a vocabulary for the three amateur routes (a CHL-origin
    player develops in the CHL tier), so the strings must match exactly."""
    for tier in (config.DEV_TIER_CHL, config.DEV_TIER_NCAA, config.DEV_TIER_EUROPE):
        assert tier in config.LEAGUE_ORIGIN_CHOICES
    # The AHL is the exception on purpose: nobody is *from* the AHL, it's a destination.
    assert config.DEV_TIER_AHL not in config.LEAGUE_ORIGIN_CHOICES


def test_junior_ages_out_before_the_ahl_floor_for_junior_players():
    """The CHL-NHL transfer agreement, expressed as two constants: a junior player is
    barred from the AHL until 20, and junior itself ends at 19 -- so the handoff is exact,
    with neither a gap year nor an overlap."""
    _, chl_max = config.DEV_TIER_AGE_BANDS[config.DEV_TIER_CHL]
    ahl_min, _ = config.DEV_TIER_AGE_BANDS[config.DEV_TIER_AHL]
    assert chl_max + 1 == ahl_min
    # A non-junior player faces no such wait and can turn pro at 18.
    assert config.DEV_TIER_AHL_MIN_AGE_NON_CHL < ahl_min


def test_elc_term_schedule_shortens_with_age_and_ends_at_the_max_age():
    """The real CBA schedule: 3 years at 18-21, 2 at 22-23, 1 at 24, none at 25+."""
    bands = config.ELC_YEARS_BY_AGE
    ages = [age for age, _ in bands]
    years = [yrs for _, yrs in bands]
    assert ages == sorted(ages)
    assert years == sorted(years, reverse=True)     # older signing -> shorter deal
    assert ages[-1] == config.ELC_MAX_AGE
    assert years[-1] >= 1
    assert years[0] == config.ROOKIE_CONTRACT_YEARS


def test_slide_rule_bounds_itself_at_two_slides():
    """Age advances one year per offseason, so an 18-year-old can satisfy the 18-or-19
    slide condition exactly twice. No separate counter enforces this -- see config's
    ELC_SLIDE_MAX_AGE comment -- so the constants themselves have to hold that property."""
    youngest_signing = config.ROOKIE_AGE_RANGE[0]
    assert config.ELC_SLIDE_MAX_AGE - youngest_signing + 1 == 2
    assert config.ELC_SLIDE_GAMES > 0
    assert config.ELC_SLIDE_GAMES < config.SEASON_GAMES


def test_ncaa_eligibility_fits_inside_its_age_band():
    """Four seasons of eligibility have to be servable within the tier's own age band, or
    a college player would age out mid-degree."""
    lo, hi = config.DEV_TIER_AGE_BANDS[config.DEV_TIER_NCAA]
    assert hi - lo + 1 >= config.NCAA_MAX_SEASONS


def test_draft_rights_outlast_the_tier_they_were_granted_for():
    """A team must hold rights long enough for the player to actually develop -- college
    rights run four years precisely because an NCAA career does."""
    assert (config.PROSPECT_RIGHTS_YEARS[config.DEV_TIER_NCAA]
            >= config.NCAA_MAX_SEASONS)
    assert (config.PROSPECT_RIGHTS_YEARS[config.DEV_TIER_NCAA]
            > config.PROSPECT_RIGHTS_YEARS[config.DEV_TIER_CHL])
    for tier in config.DEV_TIERS:
        assert config.PROSPECT_RIGHTS_YEARS.get(
            tier, config.PROSPECT_RIGHTS_YEARS_DEFAULT) >= 1


def test_nhl_ready_bar_is_shared_by_the_draft_and_the_development_tiers():
    """A graduation bar looser than the draft's would let the tiers leak sub-replacement
    players into the NHL -- the exact economic failure the gate exists to prevent (PR #61)."""
    from pucksim.systems import draft_system
    assert draft_system.DRAFT_NHL_READY_OVERALL == config.NHL_READY_OVERALL
    assert config.RATING_MIN < config.NHL_READY_OVERALL < config.RATING_MAX


def test_undrafted_players_reach_free_agency_before_they_age_out_of_development():
    """An undrafted player has to have a window in which he is BOTH still developing and
    signable, or the UDFA pathway is a dead end rather than a pathway."""
    assert config.UDFA_FREE_AGENT_AGE < config.MAX_PROSPECT_AGE
    assert config.UDFA_FREE_AGENT_AGE > config.ROOKIE_AGE_RANGE[0]


def test_contract_limit_leaves_real_room_for_prospects():
    """The 50-contract limit is what stops free (off-cap) entry-level deals from letting a
    team hoard the pipeline -- but it has to leave meaningful headroom above a full NHL
    roster or it would bind on the active roster instead of on prospect hoarding."""
    assert config.MAX_CONTRACTS > config.ROSTER_MAX
    assert config.MAX_CONTRACTS - config.ROSTER_MAX >= 20
