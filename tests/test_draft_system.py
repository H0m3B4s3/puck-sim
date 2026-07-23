"""Tests for pucksim.systems.draft_system + pucksim.gen.prospectgen --
DEVPLAN.md Step 2.5 done-criteria.

``tests/test_draft.py`` (Step 1.10) already covers the model-layer
``DraftPick``/``DraftClass`` state machine (pick-order advancement,
``record_pick`` validation, serialization) -- this file does NOT duplicate
that coverage. It focuses on this step's actual new work: the system-layer
engine that drives ``DraftClass`` (order-by-standings, prospect generation,
the pick flow, entry-level signing via Step 2.4's cap system), per DEVPLAN.md's
explicit Done criteria: "draft order matches inverse standings (straight
order, no lottery); picks recorded correctly via World; drafted players get
entry-level contracts from Step 2.4's cap system (is_rookie_scale=True via
sign_rookie/flat_contract)."
"""
from __future__ import annotations

from pucksim import config
from pucksim.gen import prospectgen
from pucksim.models.contract import flat_contract
from pucksim.models.league import Game, standings
from pucksim.models.player import Player
from pucksim.models.team import Team
from pucksim.models.world import World
from pucksim.rng import Rng
from pucksim.systems import draft_system as ds

SEED = 42


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def build_world_with_teams(n_teams: int = 8, cap_value: int = 90_000_000,
                            roster_headroom: int = 5) -> World:
    """A small World with N empty-ish teams and no prospects yet.

    ``roster_headroom`` pads each team's roster with filler signed players so
    ``ROSTER_MAX`` isn't hit trivially on the very first pick of a test
    (mirrors real-generated-league headroom, see draft_system.py's
    ``make_pick`` docstring on why roster-full is a real, not hypothetical,
    case for this step).
    """
    world = World(rng=Rng(seed=SEED))
    world.salary_cap = cap_value
    world.season_year = 2026
    for tid in range(1, n_teams + 1):
        conf = "Eastern" if tid % 2 == 0 else "Western"
        team = Team(tid=tid, name=f"Team {tid}", abbrev=f"T{tid:02d}", conference=conf)
        world.register_team(team)
        for i in range(roster_headroom):
            filler = Player(
                pid=world.new_pid(),
                name=f"Filler {tid}-{i}",
                age=27,
                position="D",
                ratings={r: 65 for r in prospectgen.SKATER_POSITIONS and ()} or _skater_ratings(),
                contract=flat_contract(1_000_000, 2),
            )
            world.add_player(filler)
            world.sign_player(filler.pid, tid)
    return world


def _skater_ratings(value: int = 65) -> dict:
    from pucksim.models import attributes as attr
    return {name: value for name in attr.ALL_RATINGS}


def _play_fake_season(world: World, seed: int = 99) -> None:
    """Give every team a distinct, deterministic win total so standings() has
    a clean, unambiguous inverse order to check against (no ties, no shared
    point totals -- avoids the standings tiebreaker chain making the
    "expected" order ambiguous for this test)."""
    rng = Rng(seed=seed)
    tids = sorted(world.teams.keys())
    gid = 1
    # Round-robin: each team i wins exactly i games (0-indexed) against a
    # fixed set of opponents, giving every team a distinct points total.
    for i, tid in enumerate(tids):
        wins_for_this_team = i
        for w in range(len(tids) - 1):
            opp = tids[(i + 1 + w) % len(tids)]
            home_score, away_score = (5, 2) if w < wins_for_this_team else (1, 4)
            g = Game(gid=gid, day=gid, home=tid, away=opp,
                     home_score=home_score, away_score=away_score, played=True)
            world.schedule.append(g)
            gid += 1


# ---------------------------------------------------------------------------
# Prospect generation (gen/prospectgen.py)
# ---------------------------------------------------------------------------
def test_generate_prospect_pool_produces_requested_size():
    rng = Rng(seed=SEED)
    counter = iter(range(1, 10_000))
    pool = prospectgen.generate_prospect_pool(rng, lambda: next(counter), size=60)
    assert len(pool) == 60


def test_generated_prospects_are_draft_age_and_unteamed():
    rng = Rng(seed=SEED)
    counter = iter(range(1, 10_000))
    pool = prospectgen.generate_prospect_pool(rng, lambda: next(counter), size=40)
    lo, hi = prospectgen.PROSPECT_AGE_RANGE
    for p in pool:
        assert lo <= p.age <= hi
        assert p.team_id is None
        assert p.is_free_agent


def test_generated_prospects_have_pre_draft_bio_populated():
    rng = Rng(seed=SEED)
    counter = iter(range(1, 10_000))
    pool = prospectgen.generate_prospect_pool(rng, lambda: next(counter), size=40)
    for p in pool:
        assert p.pre_draft is not None
        assert p.pre_draft["gp"] > 0
        if p.is_goalie:
            assert "save_pct" in p.pre_draft
        else:
            assert "pts" in p.pre_draft


def test_generated_prospects_have_a_real_league_origin():
    """DESIGN.md point 11's CHL/NCAA fork, finally live (docs/PROSPECT_DEV_PLAN.md).

    ``league_origin`` was an inert "none" placeholder from Step 1.6 until the prospect
    development round gave it consumers: it decides which development tiers a drafted
    player is eligible for. Every prospect must now carry a real one -- an unrecognized
    or defaulted origin would silently make a player eligible for the wrong tiers.
    """
    rng = Rng(seed=SEED)
    counter = iter(range(1, 10_000))
    pool = prospectgen.generate_prospect_pool(rng, lambda: next(counter), size=120)
    for p in pool:
        assert p.league_origin in config.LEAGUE_ORIGIN_CHOICES
        assert p.league_origin != config.DEFAULT_LEAGUE_ORIGIN, p.pre_draft["level"]

    origins = {p.league_origin for p in pool}
    # A class of this size should contain all three real routes -- if one is missing the
    # tier system would never exercise a whole branch of its eligibility rules.
    assert origins == {"chl", "ncaa", "europe"}


def test_league_origin_always_agrees_with_the_scouting_report_level():
    """A prospect whose bio reads "CHL" has to BE a major-junior player for eligibility
    purposes, or the UI and the rules engine disagree about the same player."""
    rng = Rng(seed=SEED)
    counter = iter(range(1, 10_000))
    pool = prospectgen.generate_prospect_pool(rng, lambda: next(counter), size=120)
    for p in pool:
        assert p.league_origin == prospectgen._ORIGIN_BY_LEVEL[p.pre_draft["level"]]


def test_every_pre_draft_level_maps_to_an_origin():
    """The lookup has no fallback branch worth relying on -- a level added to the weighted
    pool without a mapping would quietly fall back to the inert default."""
    levels = {level for level, _ in prospectgen._PRE_DRAFT_LEVELS}
    assert levels == set(prospectgen._ORIGIN_BY_LEVEL)
    for origin in prospectgen._ORIGIN_BY_LEVEL.values():
        assert origin in config.LEAGUE_ORIGIN_CHOICES


def test_us_amateur_routes_all_land_on_the_college_track():
    """USHL and prep players are college-bound by construction; only the CHL fork is
    mechanically distinct (it forfeits NCAA eligibility and bars the AHL before 20)."""
    assert prospectgen._ORIGIN_BY_LEVEL["USHL"] == "ncaa"
    assert prospectgen._ORIGIN_BY_LEVEL["High School / Prep"] == "ncaa"
    assert prospectgen._ORIGIN_BY_LEVEL["CHL"] == "chl"


def test_prospect_pool_includes_some_goalies():
    rng = Rng(seed=SEED)
    counter = iter(range(1, 10_000))
    pool = prospectgen.generate_prospect_pool(rng, lambda: next(counter), size=100)
    goalies = [p for p in pool if p.is_goalie]
    assert len(goalies) >= 1


def test_same_seed_generates_identical_prospect_pool():
    def _gen():
        rng = Rng(seed=SEED)
        counter = iter(range(1, 10_000))
        return prospectgen.generate_prospect_pool(rng, lambda: next(counter), size=30)

    pool_a = _gen()
    pool_b = _gen()
    assert [p.to_dict() for p in pool_a] == [p.to_dict() for p in pool_b]


# ---------------------------------------------------------------------------
# Draft order (worst-first, straight, no lottery)
# ---------------------------------------------------------------------------
def test_draft_order_matches_inverse_standings():
    world = build_world_with_teams(n_teams=8)
    _play_fake_season(world)

    order = ds.compute_draft_order(world)

    ranked_best_first = standings(world.team_list(), world.schedule, world.standings_rule)
    expected_worst_first = [t.tid for t in reversed(ranked_best_first)]
    assert order == expected_worst_first


def test_draft_order_is_straight_no_lottery_reweighting():
    """The literal worst team is always slot 0 -- no probabilistic lottery
    reordering (DEVPLAN.md's explicit "straight order, no lottery" default)."""
    world = build_world_with_teams(n_teams=8)
    _play_fake_season(world)
    order = ds.compute_draft_order(world)
    worst_team = min(world.team_list(),
                      key=lambda t: standings(world.team_list(), world.schedule,
                                               world.standings_rule).index(t))
    # Recompute directly: the last-ranked team in standings() must be order[0].
    ranked_best_first = standings(world.team_list(), world.schedule, world.standings_rule)
    assert order[0] == ranked_best_first[-1].tid


def test_setup_draft_repeats_round1_order_every_round_straight():
    world = build_world_with_teams(n_teams=8)
    _play_fake_season(world)
    dc = ds.setup_draft(world, rounds=3)
    n = len(world.teams)
    round1 = dc.order[:n]
    round2 = dc.order[n:2 * n]
    round3 = dc.order[2 * n:3 * n]
    assert round1 == round2 == round3
    assert dc.total_picks == n * 3


# ---------------------------------------------------------------------------
# Pick flow + World integration
# ---------------------------------------------------------------------------
def test_setup_draft_registers_prospects_on_world():
    world = build_world_with_teams(n_teams=8)
    _play_fake_season(world)
    dc = ds.setup_draft(world, rounds=2, pool_size=40)
    assert len(dc.prospect_ids) == 40
    for pid in dc.prospect_ids:
        assert pid in world.players
        assert world.players[pid].team_id is None


def _make_nhl_ready(player: Player) -> None:
    """Raise a prospect's ratings until they clear ``DRAFT_NHL_READY_OVERALL``.

    Generated prospects are usually well below NHL caliber (pool median overall ~52), so a
    test that needs the immediate-entry path has to build the rare prospect who's actually
    ready rather than relying on whatever the pool happened to produce.
    """
    for name in player.ratings:
        player.ratings[name] = 90
    assert player.overall >= ds.DRAFT_NHL_READY_OVERALL


def _make_raw(player: Player) -> None:
    """Drop a prospect's ratings well below ``DRAFT_NHL_READY_OVERALL``.

    The mirror of ``_make_nhl_ready``, and needed for the same reason: the pool's median
    overall (~52) is comfortably raw, but individual prospects near the top of a small
    generated board can land right on the bar, so a test about the not-ready path has to
    build that player rather than hope for him.
    """
    for name in player.ratings:
        player.ratings[name] = 45
    assert player.overall < ds.DRAFT_NHL_READY_OVERALL


def test_make_pick_records_via_world_and_draft_class():
    """The pick itself is always recorded, whether or not the player signs -- draft rights
    and roster occupancy are separate facts (see make_pick's docstring)."""
    world = build_world_with_teams(n_teams=4, roster_headroom=2)
    _play_fake_season(world)
    dc = ds.setup_draft(world, rounds=1, pool_size=20)

    on_clock = dc.team_on_clock()
    pid = ds.best_available(world)
    ds.make_pick(world, pid)

    assert (pid, on_clock) in dc.picks_made
    assert world.player(pid).draft["team"] == world.teams[on_clock].abbrev


def test_nhl_ready_first_overall_pick_signs_immediately():
    """A first-overall pick who is genuinely NHL-caliber goes straight onto the roster."""
    world = build_world_with_teams(n_teams=4, roster_headroom=2)
    _play_fake_season(world)
    dc = ds.setup_draft(world, rounds=1, pool_size=20)

    on_clock = dc.team_on_clock()
    pid = ds.best_available(world)
    _make_nhl_ready(world.player(pid))
    signed = ds.make_pick(world, pid)

    assert signed is True
    player = world.player(pid)
    assert player.team_id == on_clock
    assert pid in world.teams[on_clock].roster
    assert pid not in world.free_agents


def test_a_pick_who_is_not_nhl_ready_goes_to_a_development_tier():
    """A raw pick keeps his draft rights but stays off the active roster to develop
    (systems/prospects.py) -- he costs no cap space and takes no roster spot. This is what
    stops entry-level teenagers from displacing paid NHL players and collapsing league
    payroll (PR #61)."""
    from pucksim.systems.prospects import current_tier, is_reserved_prospect

    world = build_world_with_teams(n_teams=4, roster_headroom=2)
    _play_fake_season(world)
    dc = ds.setup_draft(world, rounds=2, pool_size=20)

    ds.make_pick(world, ds.best_available(world))       # pick 1
    pid = ds.best_available(world)
    player = world.player(pid)
    _make_raw(player)                                   # a normal, unfinished prospect
    signed = ds.make_pick(world, pid)                   # pick 2

    assert signed is False
    assert player.team_id is None
    assert pid in world.free_agents
    assert is_reserved_prospect(player, world.season_year)
    assert current_tier(player) in config.DEV_TIERS
    assert (pid, dc.picks_made[1][1]) in dc.picks_made


def test_readiness_not_draft_slot_decides_who_reaches_the_nhl():
    """The rule this round replaced keyed arrival on pick number, so a third-overall bust
    and a third-overall superstar reached the NHL on the same timetable. Now an NHL-caliber
    player signs whenever he's taken, and a raw one develops however early he's taken."""
    world = build_world_with_teams(n_teams=4, roster_headroom=2)
    _play_fake_season(world)
    ds.setup_draft(world, rounds=2, pool_size=20)

    ds.make_pick(world, ds.best_available(world))       # pick 1, whoever he is
    late_pid = ds.best_available(world)
    _make_nhl_ready(world.player(late_pid))             # ready, and taken late
    assert ds.make_pick(world, late_pid) is True
    assert world.player(late_pid).team_id is not None


def test_a_prospect_placed_in_a_tier_lands_where_his_background_says_he_should():
    """Origin drives the assignment: junior players go to junior, college recruits to the
    NCAA, Europeans to Europe -- the CHL/NCAA fork made real (DESIGN.md point 11)."""
    from pucksim.systems import prospects

    world = build_world_with_teams(n_teams=4, roster_headroom=2)
    _play_fake_season(world)
    ds.setup_draft(world, rounds=4, pool_size=60)
    ds.auto_complete_draft(world)

    placed = [p for p in world.players.values() if p.is_prospect]
    assert placed, "a whole draft placed nobody into development"
    for p in placed:
        tier = prospects.current_tier(p)
        if tier == config.DEV_TIER_AHL:
            # The overage path: signed on draft day to unlock the professional tier.
            assert p.contract.years_remaining > 0
        else:
            assert tier == p.league_origin
        assert prospects.rights_holder(p) is not None


def test_drafted_player_gets_entry_level_rookie_scale_contract():
    """DEVPLAN.md's core Done criterion: drafted players sign via Step 2.4's
    existing sign_rookie() path -- is_rookie_scale=True, flat salary."""
    world = build_world_with_teams(n_teams=4, roster_headroom=2)
    _play_fake_season(world)
    ds.setup_draft(world, rounds=1, pool_size=20)

    pid = ds.best_available(world)
    _make_nhl_ready(world.player(pid))
    ds.make_pick(world, pid)
    player = world.player(pid)

    assert player.contract.is_rookie_scale is True
    assert len(player.contract.salaries) == config.ROOKIE_CONTRACT_YEARS
    assert len(set(player.contract.salaries)) == 1          # flat contract
    assert player.contract.salaries[0] > 0


def test_make_pick_populates_draft_bio():
    world = build_world_with_teams(n_teams=4, roster_headroom=2)
    _play_fake_season(world)
    dc = ds.setup_draft(world, rounds=1, pool_size=20)
    on_clock = dc.team_on_clock()
    pid = ds.best_available(world)
    ds.make_pick(world, pid)
    player = world.player(pid)
    assert player.draft is not None
    assert player.draft["year"] == world.season_year
    assert player.draft["round"] == 1
    assert player.draft["pick"] == 1
    assert player.draft["team"] == world.teams[on_clock].abbrev


def test_make_pick_rejects_illegal_pick_via_draft_class_guard():
    """make_pick leans on DraftClass.record_pick()'s existing validation --
    an already-picked or unavailable prospect still raises ValueError."""
    import pytest
    world = build_world_with_teams(n_teams=4, roster_headroom=2)
    _play_fake_season(world)
    dc = ds.setup_draft(world, rounds=1, pool_size=20)
    pid = ds.best_available(world)
    ds.make_pick(world, pid)
    with pytest.raises(ValueError):
        ds.make_pick(world, pid)   # already drafted


def test_auto_complete_draft_finishes_every_pick():
    world = build_world_with_teams(n_teams=6, roster_headroom=3)
    _play_fake_season(world)
    dc = ds.setup_draft(world, rounds=2, pool_size=40)
    result = ds.auto_complete_draft(world)
    assert dc.complete
    assert result["picks_made"] == dc.total_picks == 12
    # Every team drafted exactly 2 (one per round, straight order).
    picks_by_team = {}
    for _pid, tid in dc.picks_made:
        picks_by_team[tid] = picks_by_team.get(tid, 0) + 1
    assert all(count == 2 for count in picks_by_team.values())


def test_full_roster_gracefully_leaves_drafted_player_unsigned_not_crashed():
    """Real, not hypothetical, v1 edge case (see draft_system.py's make_pick
    docstring): a team with a full 23-man roster can still draft a player
    (draft rights recorded) even though there's no room to sign them yet --
    this must not raise or corrupt DraftClass state."""
    world = build_world_with_teams(n_teams=2, roster_headroom=config.ROSTER_MAX)
    _play_fake_season(world)
    dc = ds.setup_draft(world, rounds=1, pool_size=10)

    pid = ds.best_available(world)
    on_clock_before = dc.team_on_clock()
    signed = ds.make_pick(world, pid)

    assert signed is False
    player = world.player(pid)
    assert player.team_id is None            # never joined the roster
    assert player.is_free_agent
    assert player.draft is not None           # draft rights still recorded
    assert player.draft["team"] == world.teams[on_clock_before].abbrev
    assert (pid, on_clock_before) in dc.picks_made
    assert dc.team_on_clock() != on_clock_before or dc.complete  # clock advanced


def test_run_draft_headless_end_to_end():
    world = build_world_with_teams(n_teams=8, roster_headroom=1)
    _play_fake_season(world)
    result = ds.run_draft(world, rounds=2, pool_size=60)

    assert result["picks_made"] == result["total_picks"]
    assert world.draft_class.complete
    assert result["signed"] <= result["picks_made"]
    assert result["undrafted"] == 60 - result["picks_made"]


def test_effective_rounds_clamps_when_pool_too_small():
    """8 teams * 5 requested rounds = 40 picks, but a 24-player pool can only
    support 3 full rounds (24 // 8) -- setup_draft must clamp instead of
    running DraftClass.record_pick() out of prospects mid-draft."""
    world = build_world_with_teams(n_teams=8, roster_headroom=1)
    _play_fake_season(world)
    dc = ds.setup_draft(world, rounds=5, pool_size=24)
    assert dc.total_picks == 24        # 3 effective rounds * 8 teams, not 40
    result = ds.auto_complete_draft(world)
    assert dc.complete
    assert result["picks_made"] == 24


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def test_same_seed_produces_identical_draft_outcome():
    def _run():
        world = build_world_with_teams(n_teams=6, roster_headroom=2)
        _play_fake_season(world)
        ds.run_draft(world, rounds=2, pool_size=30)
        return [(pid, tid, world.players[pid].contract.is_rookie_scale)
                for pid, tid in world.draft_class.picks_made]

    assert _run() == _run()


# ---------------------------------------------------------------------------
# Synthetic development stat lines (docs/PROSPECT_DEV_PLAN.md Phase 3)
# ---------------------------------------------------------------------------
def test_development_season_line_is_shaped_by_the_tier():
    """A prospect's season should be something you can look at, not just a rating ticking
    up in the dark."""
    rng = Rng(seed=SEED)
    counter = iter(range(1, 10_000))
    player = prospectgen.generate_prospect(next(counter), rng)
    line = prospectgen.development_season_line(rng, player, config.DEV_TIER_CHL)
    assert line["level"] == "CHL"
    assert 0 < line["gp"] <= prospectgen.TIER_STAT_LINE["chl"][1]
    assert ("pts" in line) or ("save_pct" in line)


def test_the_ahl_is_a_harder_league_to_score_in_than_junior():
    """The single most recognizable fact about the step up to pro: a junior scoring star's
    point totals collapse in the AHL."""
    rng = Rng(seed=SEED)
    counter = iter(range(1, 10_000))
    skater = next(p for p in prospectgen.generate_prospect_pool(
        rng, lambda: next(counter), size=40) if not p.is_goalie)

    def per_game(tier):
        totals = []
        for _ in range(30):
            line = prospectgen.development_season_line(rng, skater, tier)
            totals.append(line["pts"] / line["gp"])
        return sum(totals) / len(totals)

    assert per_game(config.DEV_TIER_AHL) < per_game(config.DEV_TIER_CHL)


def test_every_tier_has_a_stat_line_shape():
    """development_season_line falls back silently on an unknown tier, so a tier added
    without a shape would produce plausible-looking nonsense rather than an error."""
    assert set(prospectgen.TIER_STAT_LINE) == set(config.DEV_TIERS)
    for _label, games, difficulty in prospectgen.TIER_STAT_LINE.values():
        assert games > 0
        assert 0 < difficulty <= 1.0


def test_a_goalie_line_gets_goalie_stats_at_every_tier():
    rng = Rng(seed=SEED)
    counter = iter(range(1, 10_000))
    goalie = prospectgen.generate_prospect(next(counter), rng, position="G")
    for tier in config.DEV_TIERS:
        line = prospectgen.development_season_line(rng, goalie, tier)
        assert "save_pct" in line and "gaa" in line
        assert 0.87 <= line["save_pct"] <= 0.945


def test_prospects_carry_a_season_line_after_an_offseason():
    from pucksim.gen.leaguegen import build_world
    from pucksim.systems import offseason, prospects

    world = build_world(3)
    offseason.run_offseason(world, champion_tid=None)
    offseason.run_offseason(world, champion_tid=None)

    lines = [p.development["line"] for p in prospects.developing_players(world)]
    assert lines and all(line.get("gp", 0) > 0 for line in lines)


def test_draft_age_distribution_is_weighted_toward_eighteen():
    """A real class is overwhelmingly 18-year-olds. Drawing uniformly across the eligible
    band quietly broke the development system: a prospect drafted at 20 has almost no
    runway before PROSPECT_STAGNATION_AGE starts eroding his ceiling, and he skips junior
    entirely since the CHL tier ends at 19."""
    rng = Rng(seed=SEED)
    counter = iter(range(1, 10_000))
    pool = prospectgen.generate_prospect_pool(rng, lambda: next(counter), size=400)
    ages = [p.age for p in pool]
    lo, hi = prospectgen.PROSPECT_AGE_RANGE
    assert min(ages) >= lo and max(ages) <= hi
    share_18 = sum(1 for a in ages if a == lo) / len(ages)
    assert 0.6 < share_18 < 0.85, share_18
    # Older prospects still exist -- they're the ones the league already passed over.
    assert any(a >= lo + 2 for a in ages)


def test_prospect_age_weights_cover_the_eligible_band():
    weighted = {age for age, _ in prospectgen._PROSPECT_AGE_WEIGHTS}
    lo, hi = prospectgen.PROSPECT_AGE_RANGE
    assert weighted == set(range(lo, hi + 1))
    weights = [w for _, w in prospectgen._PROSPECT_AGE_WEIGHTS]
    assert weights == sorted(weights, reverse=True)      # younger is always likelier
    assert abs(sum(weights) - 1.0) < 1e-9
