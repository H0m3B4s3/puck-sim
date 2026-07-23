"""Tests for pucksim.systems.prospects -- development tiers and entry-level contracts.

See prospects.py's module docstring and docs/PROSPECT_DEV_PLAN.md. Two things these tests
guard that aren't obvious from the feature description:

- ``is_reserved_prospect`` is the seam five other modules go through to keep developing
  players off the open market, and PR #61 established that leaking them back onto it
  collapses the league's salary economy. Its meaning must not drift.
- The ELC slide is bounded at two slides by the AGE condition alone, with no counter
  enforcing it. That property is easy to break and silent when broken, so it's tested
  directly by running a full career forward.
"""
from __future__ import annotations

import pytest

from pucksim import config
from pucksim.models.contract import Contract, flat_contract
from pucksim.models.player import Player
from pucksim.models import attributes as attr
from pucksim.systems import prospects


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_prospect(pid: int = 1, age: int = 18, origin: str = "chl",
                   overall: int = 55, position: str = "C") -> Player:
    ratings = (attr.ALL_GOALIE_RATINGS if position == "G" else attr.ALL_RATINGS)
    player = Player(
        pid=pid,
        name=f"Prospect {pid}",
        age=age,
        position=position,
        ratings={name: overall for name in ratings},
        contract=Contract.free_agent(),
    )
    player.league_origin = origin
    return player


def developing(player: Player, tier: str, season_year: int = 2030,
                rights_tid=7) -> Player:
    prospects.enter_development(player, tier, season_year, rights_tid=rights_tid)
    return player


# ---------------------------------------------------------------------------
# Tier eligibility -- the two real rules
# ---------------------------------------------------------------------------
def test_major_junior_permanently_forfeits_ncaa_eligibility():
    """DESIGN.md point 11's mutual-exclusivity fork -- the one rule here with no
    basketball analogue. It follows origin, not current tier, because it's permanent."""
    junior = make_prospect(age=18, origin="chl")
    assert prospects.forfeited_ncaa_eligibility(junior)
    assert not prospects.eligible_for_tier(junior, config.DEV_TIER_NCAA)

    college = make_prospect(age=18, origin="ncaa")
    assert not prospects.forfeited_ncaa_eligibility(college)
    assert prospects.eligible_for_tier(college, config.DEV_TIER_NCAA)


def test_a_chl_graduate_in_the_ahl_still_cannot_enrol_in_college():
    """Forfeiture survives leaving junior -- it is not a property of where he is now."""
    player = make_prospect(age=21, origin="chl")
    player.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    developing(player, config.DEV_TIER_AHL)
    assert prospects.eligible_for_tier(player, config.DEV_TIER_AHL)
    assert not prospects.eligible_for_tier(player, config.DEV_TIER_NCAA)


def test_chl_transfer_agreement_bars_junior_players_from_the_ahl_until_twenty():
    """The CHL-NHL transfer agreement: a drafted junior player under 20 goes to the NHL
    or back to junior, with nothing in between. A non-junior player faces no such wait."""
    junior = make_prospect(age=19, origin="chl")
    junior.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    assert not prospects.eligible_for_tier(junior, config.DEV_TIER_AHL)
    assert prospects.eligible_for_tier(junior, config.DEV_TIER_CHL)

    junior.age = 20
    assert prospects.eligible_for_tier(junior, config.DEV_TIER_AHL)
    assert not prospects.eligible_for_tier(junior, config.DEV_TIER_CHL)   # junior ends at 19

    euro = make_prospect(age=19, origin="europe")
    euro.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    assert prospects.eligible_for_tier(euro, config.DEV_TIER_AHL)


def test_the_ahl_requires_a_contract():
    """A professional league needs a professional contract -- this is what makes signing
    an entry-level deal a real decision instead of one a team defers forever."""
    player = make_prospect(age=21, origin="ncaa")
    assert not prospects.eligible_for_tier(player, config.DEV_TIER_AHL)
    player.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    assert prospects.eligible_for_tier(player, config.DEV_TIER_AHL)


def test_ncaa_eligibility_runs_out_after_four_seasons():
    player = developing(make_prospect(age=20, origin="ncaa"), config.DEV_TIER_NCAA)
    player.development["tier_seasons"] = config.NCAA_MAX_SEASONS - 1
    assert prospects.eligible_for_tier(player, config.DEV_TIER_NCAA)
    player.development["tier_seasons"] = config.NCAA_MAX_SEASONS
    assert not prospects.eligible_for_tier(player, config.DEV_TIER_NCAA)


def test_tiers_respect_their_age_bands():
    for tier in config.DEV_TIERS:
        lo, hi = prospects.tier_age_band(tier)
        origin = tier if tier != config.DEV_TIER_AHL else "europe"
        over = make_prospect(age=hi + 1, origin=origin)
        over.contract = flat_contract(900_000, 3, is_rookie_scale=True)
        assert not prospects.eligible_for_tier(over, tier), tier
        assert lo <= hi


def test_best_tier_prefers_the_ahl_once_a_player_is_allowed_in_it():
    """Pro development against grown men beats another year dominating juniors."""
    player = make_prospect(age=20, origin="chl")
    player.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    assert prospects.best_tier(player) == config.DEV_TIER_AHL

    unsigned = make_prospect(age=19, origin="chl")
    assert prospects.best_tier(unsigned) == config.DEV_TIER_CHL


def test_best_tier_is_none_when_nowhere_will_take_him():
    """An unsigned junior graduate at 20 has aged out of junior and can't turn pro."""
    stranded = make_prospect(age=20, origin="chl")
    assert prospects.best_tier(stranded) is None


# ---------------------------------------------------------------------------
# The reserved-prospect seam
# ---------------------------------------------------------------------------
def test_a_developing_prospect_is_reserved():
    player = developing(make_prospect(age=18), config.DEV_TIER_CHL, season_year=2030)
    assert prospects.is_reserved_prospect(player, 2030)


def test_a_player_on_an_nhl_roster_is_never_reserved():
    """A top pick who went straight to the league isn't reserved -- he's just a player."""
    player = developing(make_prospect(age=18), config.DEV_TIER_CHL, season_year=2030)
    player.team_id = 3
    assert not prospects.is_reserved_prospect(player, 2030)


def test_a_player_outside_the_development_system_is_never_reserved():
    assert not prospects.is_reserved_prospect(make_prospect(age=27), 2030)


def test_lapsed_draft_rights_open_a_prospect_to_the_whole_league():
    """A team doesn't own a pick forever -- that's what stops it parking a prospect it
    never intends to sign."""
    player = developing(make_prospect(age=18), config.DEV_TIER_CHL, season_year=2030)
    expire = player.development["rights_expire"]
    assert prospects.is_reserved_prospect(player, expire - 1)
    assert not prospects.rights_lapsed(player, expire - 1)
    assert prospects.rights_lapsed(player, expire)
    assert prospects.is_open_to_all(player, expire)
    assert not prospects.is_reserved_prospect(player, expire)


def test_college_rights_run_longer_than_junior_rights():
    """Real asymmetry, and it makes drafting a college kid a different bet."""
    junior = developing(make_prospect(pid=1, age=18, origin="chl"),
                         config.DEV_TIER_CHL, season_year=2030)
    college = developing(make_prospect(pid=2, age=18, origin="ncaa"),
                          config.DEV_TIER_NCAA, season_year=2030)
    assert (college.development["rights_expire"]
            > junior.development["rights_expire"])


def test_an_undrafted_prospect_is_reserved_until_he_reaches_free_agency_age():
    """The undrafted pathway: he keeps developing while too young to be signed, then hits
    the open market -- which is the entire point of giving prospects real age curves."""
    player = make_prospect(age=18, origin="ncaa")
    prospects.enter_development(player, config.DEV_TIER_NCAA, 2030, rights_tid=None)
    assert prospects.is_reserved_prospect(player, 2030)

    player.age = config.UDFA_FREE_AGENT_AGE
    assert prospects.is_open_to_all(player, 2030)
    assert not prospects.is_reserved_prospect(player, 2030)


# ---------------------------------------------------------------------------
# Moving through the system
# ---------------------------------------------------------------------------
def test_advance_counts_seasons_in_the_system_and_in_the_tier():
    player = developing(make_prospect(age=17), config.DEV_TIER_CHL, season_year=2030)
    assert prospects.advance_development(player, 2030) == "stayed"
    assert prospects.seasons_developed(player) == 1
    assert prospects.seasons_in_tier(player) == 1


def test_a_signed_junior_player_moves_up_to_the_ahl_at_twenty():
    """The 'AHL for older prospects' path, end to end."""
    player = developing(make_prospect(age=19, origin="chl"), config.DEV_TIER_CHL,
                         season_year=2030)
    player.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    player.age = 20                                  # aged by development.develop_all
    assert prospects.advance_development(player, 2030) == "moved_up"
    assert prospects.current_tier(player) == config.DEV_TIER_AHL
    assert prospects.seasons_in_tier(player) == 0    # tier clock restarts
    assert prospects.seasons_developed(player) == 1  # career clock does not


def test_an_unsigned_junior_graduate_turns_pro_into_free_agency():
    """No tier will take him, but he isn't old -- he goes on the open market, and gets
    culled by offseason.cull_free_agents if he never became anybody."""
    player = developing(make_prospect(age=19, origin="chl"), config.DEV_TIER_CHL,
                         season_year=2030)
    player.age = 20
    assert prospects.advance_development(player, 2030) == "turned_pro"
    assert player.development is None
    assert not prospects.is_reserved_prospect(player, 2030)


def test_a_college_player_who_exhausts_eligibility_becomes_a_free_agent():
    """The college-free-agent pathway."""
    player = developing(make_prospect(age=22, origin="ncaa"), config.DEV_TIER_NCAA,
                         season_year=2030)
    player.development["tier_seasons"] = config.NCAA_MAX_SEASONS - 1
    player.age = 23
    assert prospects.advance_development(player, 2030) == "turned_pro"
    assert player.development is None


def test_a_prospect_ages_out_of_the_system_entirely():
    player = developing(make_prospect(age=config.MAX_PROSPECT_AGE, origin="europe"),
                         config.DEV_TIER_EUROPE, season_year=2030)
    player.age += 1
    assert prospects.advance_development(player, 2030) == "aged_out"
    assert player.development is None


def test_advance_reports_lapsed_rights_and_clears_them():
    player = developing(make_prospect(age=18, origin="ncaa"), config.DEV_TIER_NCAA,
                         season_year=2030)
    expire = player.development["rights_expire"]
    player.age = 19
    assert prospects.advance_development(player, expire) == "rights_lapsed"
    assert player.development is not None
    assert prospects.rights_holder(player) is None


# ---------------------------------------------------------------------------
# Entry-level contracts
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("age,years", [(18, 3), (21, 3), (22, 2), (23, 2), (24, 1), (25, 0)])
def test_elc_term_follows_the_real_cba_schedule(age, years):
    assert prospects.elc_years_for_age(age) == years


def test_elc_eligibility_ends_at_the_max_age():
    assert prospects.is_elc_eligible(make_prospect(age=config.ELC_MAX_AGE))
    assert not prospects.is_elc_eligible(make_prospect(age=config.ELC_MAX_AGE + 1))


def test_a_player_already_under_contract_cannot_sign_another_elc():
    player = make_prospect(age=19)
    player.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    assert not prospects.is_elc_eligible(player)


def test_a_teenager_who_stays_out_of_the_nhl_slides_instead_of_burning():
    """The headline rule: signing your 18-year-old first-rounder doesn't waste the deal."""
    player = make_prospect(age=18)
    player.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    assert prospects.tick_contract(player) == "slid"
    assert player.contract.years_remaining == 3
    assert player.contract.slide_years == 1


def test_a_teenager_who_plays_ten_nhl_games_burns_the_year():
    """The tenth game is the most consequential number on a 19-year-old's calendar."""
    player = make_prospect(age=19)
    player.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    player.season.gp = config.ELC_SLIDE_GAMES - 1
    assert prospects.can_slide(player)
    player.season.gp = config.ELC_SLIDE_GAMES
    assert not prospects.can_slide(player)
    assert prospects.tick_contract(player) == "burned"
    assert player.contract.years_remaining == 2


def test_a_twenty_year_old_burns_a_year_even_in_the_ahl():
    player = make_prospect(age=20)
    player.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    assert prospects.tick_contract(player) == "burned"
    assert player.contract.years_remaining == 2


def test_only_entry_level_deals_slide():
    veteran = make_prospect(age=19)
    veteran.contract = flat_contract(4_000_000, 3, is_rookie_scale=False)
    assert not prospects.can_slide(veteran)
    assert prospects.tick_contract(veteran) == "burned"


def test_the_slide_bounds_itself_at_two_without_a_counter():
    """The property config.ELC_SLIDE_MAX_AGE is really enforcing. Signed at 18 and never
    called up, the deal slides at 18 and 19 and then starts for real at 20 -- so the
    three cheap years land at 20/21/22, exactly as the real rule produces."""
    player = make_prospect(age=18)
    player.contract = flat_contract(900_000, 3, is_rookie_scale=True)

    outcomes = []
    for _ in range(5):
        outcomes.append(prospects.tick_contract(player))
        player.age += 1

    assert outcomes == ["slid", "slid", "burned", "burned", "burned"]
    assert player.contract.slide_years == 2
    assert player.contract.years_remaining == 0


# ---------------------------------------------------------------------------
# Where the AHL sits -- eligibility vs. preference
# ---------------------------------------------------------------------------
def test_the_ahl_is_for_older_prospects_not_all_signed_ones():
    """Eligibility and preference are separate knobs on purpose. A signed 18-year-old
    European IS AHL-eligible, but belongs in his amateur tier anyway -- preferring the AHL
    at every age put ~85% of every prospect in the league there the moment his team signed
    him, and the four tiers collapsed into one bucket."""
    young = make_prospect(age=18, origin="europe")
    young.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    assert prospects.eligible_for_tier(young, config.DEV_TIER_AHL)
    assert prospects.best_tier(young) == config.DEV_TIER_EUROPE

    older = make_prospect(age=config.AHL_PREFERRED_AGE, origin="europe")
    older.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    assert prospects.best_tier(older) == config.DEV_TIER_AHL


def test_a_signed_college_player_stays_in_college_until_he_is_old_enough():
    young = make_prospect(age=19, origin="ncaa")
    young.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    assert prospects.best_tier(young) == config.DEV_TIER_NCAA


# ---------------------------------------------------------------------------
# Who a team signs, and when
# ---------------------------------------------------------------------------
def test_a_team_does_not_sign_a_prospect_it_does_not_believe_in():
    """Scouted potential -- the FOGGED signal -- is what a team bets on."""
    player = developing(make_prospect(age=18, origin="ncaa", overall=40),
                         config.DEV_TIER_NCAA)
    player.potential = config.NHL_READY_OVERALL - 10
    assert not prospects.should_sign(None, player)


def test_a_team_signs_a_prospect_who_is_nearly_ready():
    player = developing(
        make_prospect(age=19, origin="ncaa",
                       overall=config.NHL_READY_OVERALL - config.ELC_SIGN_READINESS_GAP),
        config.DEV_TIER_NCAA)
    player.potential = 85
    assert prospects.should_sign(None, player)


def test_a_team_signs_at_the_deadline_rather_than_lose_him():
    """A 19-year-old junior player has no tier left next season unless he's under
    contract, so this is the last offseason his team can keep him."""
    player = developing(make_prospect(age=19, origin="chl", overall=50),
                         config.DEV_TIER_CHL)
    player.potential = 85
    assert prospects.sign_or_lose_him(player)
    assert prospects.should_sign(None, player)


def test_a_young_prospect_with_time_left_is_left_in_school():
    """The test that stops teams signing an entire draft class the day after the draft."""
    player = developing(make_prospect(age=18, origin="ncaa", overall=45),
                         config.DEV_TIER_NCAA)
    player.potential = 85
    assert not prospects.sign_or_lose_him(player)
    assert not prospects.should_sign(None, player)


# ---------------------------------------------------------------------------
# The offseason cycle, end to end
# ---------------------------------------------------------------------------
def _world_with_a_prospect(age=18, origin="chl", overall=55, potential=85, signed=True):
    from pucksim.gen.leaguegen import build_world

    world = build_world(11)
    tid = world.team_list()[0].tid
    player = make_prospect(pid=world.new_pid(), age=age, origin=origin, overall=overall)
    player.potential = potential
    if signed:
        player.contract = flat_contract(900_000, 3, is_rookie_scale=True)
    world.add_player(player)
    prospects.enter_development(player, prospects.best_tier(player) or config.DEV_TIER_CHL,
                                 world.season_year, rights_tid=tid)
    return world, player, tid


def test_tick_prospect_contracts_slides_teenagers_and_burns_everyone_else():
    world, teen, _ = _world_with_a_prospect(age=18)
    assert prospects.tick_prospect_contracts(world)["slid"] == 1
    assert teen.contract.years_remaining == 3

    world, adult, _ = _world_with_a_prospect(age=21, origin="europe")
    assert prospects.tick_prospect_contracts(world)["burned"] == 1
    assert adult.contract.years_remaining == 2


def test_tick_prospect_contracts_ignores_unsigned_prospects():
    world, player, _ = _world_with_a_prospect(age=18, signed=False)
    assert prospects.tick_prospect_contracts(world) == {"slid": 0, "burned": 0}


def test_advance_prospects_reports_one_outcome_per_prospect():
    world, player, _ = _world_with_a_prospect(age=18)
    counts = prospects.advance_prospects(world)
    assert sum(counts.values()) == 1
    assert set(counts) == set(prospects.ADVANCE_OUTCOMES)


def test_promotion_requires_a_contract_however_good_he_is():
    """Nobody joins an NHL roster without one."""
    world, player, tid = _world_with_a_prospect(age=20, origin="europe", signed=False,
                                                 overall=90)
    assert player.overall >= config.NHL_READY_OVERALL
    assert prospects.promote_ready_prospects(world) == []
    assert player.is_prospect


def test_a_ready_signed_prospect_graduates_onto_the_roster():
    world, player, tid = _world_with_a_prospect(age=20, origin="europe", overall=90)
    # Make room: leaguegen fills rosters to 22/23.
    while len(world.teams[tid].roster) >= config.ROSTER_MAX - 1:
        world.release_player(world.teams[tid].roster[-1])

    assert prospects.promote_ready_prospects(world) == [player.pid]
    assert player.team_id == tid
    assert player.pid in world.teams[tid].roster
    assert not player.is_prospect            # he's a player now, not a prospect
    assert player.pid not in world.free_agents


def test_a_prospect_short_of_the_bar_is_not_promoted():
    """Promotion is gated on being GOOD, not on having waited long enough -- which is what
    stops a flood of cheap sub-replacement teenagers reaching NHL rosters however many of
    them a team drafts (PR #61)."""
    world, player, _ = _world_with_a_prospect(age=20, origin="europe",
                                               overall=config.NHL_READY_OVERALL - 1)
    assert prospects.promote_ready_prospects(world) == []
    assert player.is_prospect


def test_a_full_offseason_puts_a_draft_class_into_the_tiers():
    """The integration this whole phase is for: draft -> tiers -> ELCs -> the NHL."""
    from pucksim.gen.leaguegen import build_world
    from pucksim.systems import offseason

    world = build_world(3)
    summary = offseason.run_offseason(world, champion_tid=None)

    placed = [p for p in world.players.values() if p.is_prospect]
    assert placed, "a whole draft placed nobody into a development tier"
    tiers = {prospects.current_tier(p) for p in placed}
    assert tiers <= set(config.DEV_TIERS)
    assert len(tiers) >= 2, f"every prospect landed in the same tier: {tiers}"
    assert summary["development"]
    assert all(prospects.rights_holder(p) is not None for p in placed)


def test_prospects_survive_several_offseasons_and_reach_the_nhl():
    """The pipeline has to actually deliver. Before this round it delivered nothing: the
    share of the league on entry-level deals fell to 0% within two simulated offseasons,
    because a reserved prospect's window expired straight into the free-agent cull."""
    from pucksim.gen.leaguegen import build_world
    from pucksim.systems import offseason

    world = build_world(3)
    for _ in range(5):
        offseason.run_offseason(world, champion_tid=None)

    rostered = [p for p in world.players.values() if p.team_id is not None]
    on_elc = [p for p in rostered if p.contract.is_rookie_scale]
    assert on_elc, "no entry-level player reached an NHL roster in five seasons"
    assert prospects.developing_players(world), "the development tiers emptied out"
