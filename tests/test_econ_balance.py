"""Economy/salary-cap balance tests -- the *aggregate* properties of the generated league.

Distinct from ``test_cap.py`` (which unit-tests ``systems/cap.py``'s functions in
isolation) and ``test_world.py`` (which checks structural world-gen legality): these
tests assert the league's economy is balanced, i.e. that generated rosters actually
consume their cap.

They exist because the economy was previously broken in a way no unit test could catch.
``gen/playergen.py`` priced contracts off a private ``750K + (overall - 60) * 90K``
formula that had nothing to do with ``systems/cap.py``'s market curve, so a freshly
generated league opened with a mean team payroll of $33M against an $82.5M cap -- ~$49M
of space per team, every team, which drains all pressure out of roster building (no trade
needs salary matching, no signing is a real tradeoff, free agency never clears).

Every threshold here is a band, not an exact figure -- the point is to catch the economy
drifting decisively out of realism (a curve retune that halves salaries, a gen change that
stops fitting payroll to the cap), not to freeze a specific tuning in place.
"""
from __future__ import annotations

import statistics

import pytest

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.systems import cap

# A few seeds, not one: these are distributional claims, and a single seed could pass by
# luck. Kept small since build_world() is the expensive part of this module.
SEEDS = (1, 7, 42, 2024)


@pytest.fixture(scope="module")
def worlds():
    return [build_world(seed=seed) for seed in SEEDS]


# ---------------------------------------------------------------------------
# The hard cap
# ---------------------------------------------------------------------------
def test_no_generated_team_is_over_the_cap(worlds):
    """v1's cap is a *hard* cap (systems/cap.py's module docstring): there is no
    over-the-cap exception mechanism, so world gen emitting an over-cap team would put
    the league in a state every downstream system assumes is unreachable."""
    for world in worlds:
        for team in world.teams.values():
            assert not cap.over_cap(world, team), (
                f"{team.name} generated over the cap: "
                f"{cap.payroll(world, team):,} > {world.salary_cap:,}"
            )


def test_every_generated_contract_is_legal(worlds):
    """No generated salary may sit below the league minimum or above the max-AAV ceiling."""
    for world in worlds:
        ceiling = cap.max_salary(world.salary_cap)
        for player in world.players.values():
            for salary in player.contract.salaries:
                assert config.MINIMUM_SALARY <= salary <= ceiling, (
                    f"{player.name} has an illegal salary {salary:,}"
                )


# ---------------------------------------------------------------------------
# Cap pressure -- the actual balance fix
# ---------------------------------------------------------------------------
def test_league_payroll_consumes_most_of_the_cap(worlds):
    """Mean payroll should land near the generation target band, not far below it.

    This is the regression guard for the original bug: the old economy produced ~40% of
    the cap here.
    """
    for world in worlds:
        fractions = [cap.payroll(world, t) / world.salary_cap for t in world.teams.values()]
        mean_fraction = statistics.mean(fractions)
        assert 0.88 <= mean_fraction <= 1.0, (
            f"mean payroll is {mean_fraction:.1%} of the cap; expected a league operating "
            f"near its ceiling"
        )


def test_most_teams_are_tight_against_the_cap(worlds):
    """A clear majority of teams should have only a few million in space -- that scarcity
    is what makes trades need salary matching and signings a real tradeoff."""
    for world in worlds:
        spaces = [cap.cap_space(world, t) for t in world.teams.values()]
        tight = [s for s in spaces if s <= 8_000_000]
        assert len(tight) >= 0.6 * len(spaces), (
            f"only {len(tight)}/{len(spaces)} teams are within $8M of the cap"
        )
        assert statistics.median(spaces) <= 8_000_000


def test_some_teams_carry_real_cap_space(worlds):
    """The flip side: a handful of rebuilding clubs should have room to absorb salary,
    otherwise no cap-dump trade is ever possible and the league is uniformly frozen."""
    for world in worlds:
        roomy = [t for t in world.teams.values()
                 if cap.cap_space(world, t) >= 8_000_000]
        assert roomy, "no team has meaningful cap space; the trade market would be frozen"
        assert len(roomy) <= 0.5 * len(world.teams), (
            "too many teams have big cap space; the league isn't under real cap pressure"
        )


# ---------------------------------------------------------------------------
# Cap-sheet shape
# ---------------------------------------------------------------------------
def test_generated_salaries_track_ability(worlds):
    """Pay should correlate strongly with ability across the league.

    Not a perfect ranking -- negotiation noise, entry-level deals, and the veteran
    discount all deliberately break strict monotonicity -- but the league's high-overall
    players must be paid substantially more than its low-overall ones, or the salary
    curve has come unhooked from ratings the way the old gen formula was.
    """
    for world in worlds:
        rostered = [p for p in world.players.values() if p.team_id is not None]
        elite = [p.contract.current_salary for p in rostered if p.overall >= 80]
        depth = [p.contract.current_salary for p in rostered if p.overall <= 60]
        assert elite and depth
        assert statistics.mean(elite) > 3 * statistics.mean(depth)


def test_rosters_have_both_stars_and_minimum_salary_depth(worlds):
    """A realistic cap sheet is top-heavy: a few large contracts carried by a tail of
    cheap depth. A flat league (everyone paid alike) would satisfy the payroll totals
    above while still being economically uninteresting."""
    for world in worlds:
        for team in world.teams.values():
            salaries = [world.players[pid].contract.current_salary for pid in team.roster]
            assert max(salaries) >= 5_000_000, f"{team.name} has no significant contract"
            cheap = [s for s in salaries if s <= 2_000_000]
            assert cheap, f"{team.name} has no cheap depth"


def test_entry_level_deals_stay_cheap(worlds):
    """Entry-level contracts are cheap *by rule*, not by negotiation, and the payroll fit
    must not scale them -- cost-controlled young talent is the whole point of the ELC."""
    elc_salary = cap.rookie_salary(config.SALARY_CAP_BASE)
    for world in worlds:
        elcs = [p for p in world.players.values() if p.contract.is_rookie_scale]
        assert elcs, "no entry-level contracts were generated"
        for player in elcs:
            assert player.contract.current_salary == elc_salary


def test_contract_expiries_are_staggered(worlds):
    """Generated deals must be at varied points in their life; if they all expired
    together the first offseason would dump the entire league into free agency."""
    for world in worlds:
        remaining = {p.contract.years_remaining for p in world.players.values()
                     if p.team_id is not None}
        assert len(remaining) >= 4, f"contract lengths are not staggered: {remaining}"


# ---------------------------------------------------------------------------
# The economy over time
# ---------------------------------------------------------------------------
# Simulating offseasons is slow, so the multi-season checks share one world.
MULTI_SEASON_YEARS = 8


@pytest.fixture(scope="module")
def aged_world():
    """A league run forward several offseasons, with per-year payroll history.

    Uses ``run_offseason`` (which internally runs the draft, free agency, roster
    enforcement and cap growth) rather than simulating games -- none of the economic
    machinery under test depends on game results, and skipping the games keeps this
    fixture to a few seconds.
    """
    from pucksim.systems import offseason

    world = build_world(seed=7)
    history = []
    for _ in range(MULTI_SEASON_YEARS):
        offseason.run_offseason(world, champion_tid=0)
        history.append({
            "cap": world.salary_cap,
            "payrolls": [cap.payroll(world, t) for t in world.teams.values()],
        })
    return world, history


def test_the_hard_cap_holds_every_season(aged_world):
    """The invariant that matters most: no team is ever over the cap, in any season.

    ``offseason.fill_rosters`` must complete (a team below its roster minimum can't ice a
    legal lineup), so if teams were allowed to spend down to nothing this would sign them
    over the cap -- observed at 27 of 32 teams in one offseason before ``cap.can_sign``
    started reserving room for unfilled mandatory roster spots.
    """
    _, history = aged_world
    for year, snapshot in enumerate(history):
        over = [p for p in snapshot["payrolls"] if p > snapshot["cap"]]
        assert not over, f"season {year}: {len(over)} team(s) over the cap"


def test_cap_pressure_does_not_decay_over_seasons(aged_world):
    """Payroll must track the growing cap, not drift away from it.

    The original economy failed exactly here: even after world gen was fixed, league
    payroll fell from ~94% of the cap to ~62% within three offseasons as entry-level
    draftees displaced paid players, short contracts repriced everyone through the free
    agency discount every year, and the cap grew 3% annually underneath it all. A
    world-gen-only fix would pass every other test in this module and still leave the game
    with no cap pressure by the time a user finished their second season.
    """
    _, history = aged_world
    for year, snapshot in enumerate(history):
        fraction = statistics.mean(snapshot["payrolls"]) / snapshot["cap"]
        assert 0.85 <= fraction <= 1.0, (
            f"season {year}: mean payroll is {fraction:.1%} of the cap"
        )


def test_rosters_stay_legal_over_seasons(aged_world):
    """Cap pressure must not squeeze teams into illegal rosters."""
    world, _ = aged_world
    for team in world.teams.values():
        assert config.ROSTER_MIN <= len(team.roster) <= config.ROSTER_MAX
        goalies = [pid for pid in team.roster if world.players[pid].is_goalie]
        assert config.GOALIES_MIN <= len(goalies) <= config.GOALIES_MAX


def test_entry_level_players_do_not_take_over_the_league(aged_world):
    """The share of rostered players on entry-level deals must stay realistic.

    This is the regression guard for the missing-minor-leagues bug: with no reserve list,
    every draft signed ~150 sub-replacement teenagers straight onto NHL rosters, reaching
    41% of all rostered players on entry-level contracts and gutting league payroll.
    """
    world, _ = aged_world
    rostered = [p for p in world.players.values() if p.team_id is not None]
    elc_share = sum(1 for p in rostered if p.contract.is_rookie_scale) / len(rostered)
    assert elc_share <= 0.15, f"{elc_share:.0%} of the league is on entry-level deals"


def test_the_talent_pipeline_keeps_supplying_the_league(aged_world):
    """Prospects must survive to develop, and the free-agent market must stay stocked.

    Culling free agents by current overall used to delete every drafted teenager before
    they developed, so the draft fed nothing into the league: the best available free agent
    decayed to a 58 overall while teams sat on tens of millions they had nothing to spend
    on.
    """
    from pucksim.systems.prospects import reserved_prospects

    world, _ = aged_world
    assert reserved_prospects(world), "no prospects are developing; the draft feeds nothing"
    free_agents = [world.players[pid] for pid in world.free_agents]
    assert free_agents
    assert max(p.overall for p in free_agents) >= 65, (
        "the free-agent market has no real NHL talent in it"
    )


# ---------------------------------------------------------------------------
# The salary curve itself
# ---------------------------------------------------------------------------
def test_salary_curve_is_monotonic_in_overall():
    previous = 0
    for ovr in range(25, 100):
        salary = cap.base_salary_for(ovr)
        assert salary >= previous, f"salary curve dips at overall {ovr}"
        previous = salary


def test_salary_curve_scales_with_the_cap():
    """The curve is quoted at a reference cap and scaled to the live one, so a contract's
    size *as a share of the cap* is stable as the cap grows -- without this, `grow_cap()`
    would quietly deflate every salary into irrelevance over a long career."""
    base = config.SALARY_CURVE_REFERENCE_CAP
    for ovr in (60, 75, 90):
        at_base = cap.base_salary_for(ovr, base)
        at_double = cap.base_salary_for(ovr, base * 2)
        assert at_double == pytest.approx(at_base * 2, rel=0.01)


def test_curve_prices_a_full_roster_near_the_cap():
    """The curve's calibration claim, checked directly: an average NHL roster priced
    straight off the curve should consume most of a cap, not half of it."""
    roster_size = 22
    # A rough stand-in for a real team's rating spread: one star, a top six, and depth.
    overalls = [88, 84, 81, 79, 77, 75, 74, 72, 71, 70, 69, 68,
                67, 66, 65, 64, 62, 61, 59, 57, 55, 52]
    assert len(overalls) == roster_size
    total = sum(cap.base_salary_for(ovr) for ovr in overalls)
    fraction = total / config.SALARY_CAP_BASE
    assert 0.85 <= fraction <= 1.15, (
        f"a representative roster prices at {fraction:.0%} of the cap"
    )
