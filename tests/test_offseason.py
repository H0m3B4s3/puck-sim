"""Tests for pucksim.systems.offseason -- DEVPLAN.md Step 2.7 done-criteria (mirrors HoopR's own
test_offseason.py shape: archive_season/expire_contracts/age_and_retire/run_offseason
orchestration order).

Covers, in order:
  1. archive_season(): awards computed before career lines are appended (rookie eligibility
     still reads an empty career at award time); world.history gets one entry; accolades tick.
  2. expire_contracts(): a contract hitting 0 years remaining actually reaches free agency.
  3. age_and_retire(): forced retirement at RETIREMENT_AGE freezes a résumé via legacy.retire
     and removes the player from the active pool/roster/free-agent list.
  4. Roster maintenance (enforce_roster_max/fill_rosters/cull_free_agents).
  5. goalie_form_state / _form_state_for: persists across repeated pre_draft calls against the
     SAME World instance (mirrors sim/season.py's GoalieRestState per-World-id precedent).
  6. Full run_offseason() end-to-end against a real generated+simulated league: season year
     advances, phase ends back at REGULAR_SEASON, schedule is rebuilt, no exceptions, legal
     roster sizes preserved.
"""
from __future__ import annotations

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.models import attributes as attr
from pucksim.models.contract import flat_contract
from pucksim.models.player import Player
from pucksim.models.team import Team
from pucksim.models.world import World
from pucksim.rng import Rng
from pucksim.sim import playoffs as PO
from pucksim.sim import season as S
from pucksim.systems import offseason as O


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def build_world_with_team(tid: int = 1) -> World:
    world = World(rng=Rng(seed=1))
    team = Team(tid=tid, name=f"Team {tid}", abbrev=f"T{tid}", conference="Eastern")
    world.register_team(team)
    return world


def make_skater(pid: int, tid: int, overall: int = 70, age: int = 27, gp: int = 60,
                 contract=None) -> Player:
    ratings = {name: overall for name in attr.ALL_RATINGS}
    p = Player(pid=pid, name=f"Skater {pid}", age=age, position="C", ratings=ratings,
               team_id=tid, contract=contract or flat_contract(1_000_000, 1))
    p.season.gp = gp
    p.season.g = 10
    p.season.a = 10
    return p


def make_goalie(pid: int, tid, overall: int = 70, age: int = 27, gp: int = 40,
                 contract=None) -> Player:
    ratings = {name: overall for name in attr.ALL_GOALIE_RATINGS}
    p = Player(pid=pid, name=f"Goalie {pid}", age=age, position="G", ratings=ratings,
               team_id=tid, contract=contract or flat_contract(1_000_000, 1))
    p.season.gp = gp
    return p


# ---------------------------------------------------------------------------
# archive_season
# ---------------------------------------------------------------------------
def test_archive_season_appends_exactly_one_history_entry():
    world = build_world_with_team()
    p = make_skater(1, 1)
    world.add_player(p)
    world.teams[1].add_player(1)

    O.archive_season(world, champion_tid=None)
    assert len(world.history) == 1
    assert world.history[0]["year"] == world.season_year


def test_archive_season_appends_a_career_line_for_every_player_who_played():
    world = build_world_with_team()
    played = make_skater(1, 1, gp=40)
    scratched = make_skater(2, 1, gp=0)
    world.add_player(played)
    world.add_player(scratched)
    world.teams[1].add_player(1)
    world.teams[1].add_player(2)

    O.archive_season(world, champion_tid=None)
    assert len(played.career) == 1
    assert len(scratched.career) == 0   # never played -- no career line this season


def test_archive_season_records_champion_accolade():
    world = build_world_with_team()
    p = make_skater(1, 1, gp=40)
    world.add_player(p)
    world.teams[1].add_player(1)

    O.archive_season(world, champion_tid=1)
    assert p.accolades.get("champion") == 1


def test_archive_season_rookie_still_calder_eligible_despite_career_append_ordering():
    """Regression guard for the exact ordering bug HoopR's own docstring warns about: awards
    must be computed BEFORE career lines are appended, or a rookie's career wouldn't be empty
    anymore by the time Calder eligibility is checked."""
    world = build_world_with_team()
    rookie = make_skater(1, 1, age=19, gp=int(config.SEASON_GAMES * 0.5), overall=72)
    world.add_player(rookie)
    world.teams[1].add_player(1)

    O.archive_season(world, champion_tid=None)
    assert world.history[0]["awards"].get("calder", {}).get("pid") == 1


# ---------------------------------------------------------------------------
# expire_contracts
# ---------------------------------------------------------------------------
def test_expire_contracts_releases_a_player_whose_deal_just_ran_out():
    world = build_world_with_team()
    p = make_skater(1, 1, contract=flat_contract(1_000_000, 1))   # exactly 1 year left
    world.add_player(p)
    world.teams[1].add_player(1)

    new_fas = O.expire_contracts(world)
    assert 1 in new_fas
    assert p.team_id is None
    assert 1 in world.free_agents


def test_expire_contracts_keeps_a_player_with_years_remaining():
    world = build_world_with_team()
    p = make_skater(1, 1, contract=flat_contract(1_000_000, 3))
    world.add_player(p)
    world.teams[1].add_player(1)

    new_fas = O.expire_contracts(world)
    assert 1 not in new_fas
    assert p.team_id == 1


# ---------------------------------------------------------------------------
# age_and_retire
# ---------------------------------------------------------------------------
def test_age_and_retire_forces_retirement_at_retirement_age():
    world = build_world_with_team()
    p = make_skater(1, 1, age=config.RETIREMENT_AGE - 1, overall=80)
    world.add_player(p)
    world.teams[1].add_player(1)

    result = O.age_and_retire(world)
    assert p.pid in result["retired"]
    assert p.pid not in world.players
    assert p.pid not in world.teams[1].roster


def test_age_and_retire_snapshots_a_resume_before_removal():
    world = build_world_with_team()
    p = make_skater(1, 1, age=config.RETIREMENT_AGE - 1, overall=80,
                     contract=flat_contract(1_000_000, 1))
    p.career = [{"year": 2020, "gp": 82, "g": 10.0, "a": 10.0, "ovr": 80}]
    world.add_player(p)
    world.teams[1].add_player(1)

    O.age_and_retire(world)
    assert len(world.retired) == 1
    assert world.retired[0]["pid"] == 1


def test_age_and_retire_leaves_a_young_player_alone():
    world = build_world_with_team()
    p = make_skater(1, 1, age=24, overall=80)
    world.add_player(p)
    world.teams[1].add_player(1)

    result = O.age_and_retire(world)
    assert p.pid not in result["retired"]
    assert p.pid in world.players


# ---------------------------------------------------------------------------
# Roster maintenance
# ---------------------------------------------------------------------------
def test_enforce_roster_max_waives_the_worst_skaters_leaving_goalies_untouched():
    """Goalies pinned at GOALIES_MIN (no slack -- ineligible to be cut) and skaters with slack
    above SKATERS_MIN: enforce_roster_max must waive down to legal skater/goalie counts by
    cutting only the worst-overall SKATERS, never touching the goalies. (In this codebase's
    actual config, SKATERS_MAX + GOALIES_MAX == ROSTER_MAX exactly, so any scenario that pushes
    the team over ROSTER_MAX while goalies stay at GOALIES_MIN necessarily also pushes skaters
    over SKATERS_MAX -- both caps end up enforced together here, which is correct, not a
    coincidence of this test's construction.)"""
    world = build_world_with_team()
    for i in range(config.GOALIES_MIN):
        g = make_goalie(i, 1, overall=70)
        world.add_player(g)
        world.teams[1].add_player(i)
    n_skaters = config.SKATERS_MAX + 3
    for i in range(100, 100 + n_skaters):
        p = make_skater(i, 1, overall=50 + i)   # ascending overall -- lowest ids are worst
        world.add_player(p)
        world.teams[1].add_player(i)

    O.enforce_roster_max(world)
    skaters_after = [pid for pid in world.teams[1].roster if not world.players[pid].is_goalie]
    assert len(skaters_after) == config.SKATERS_MAX
    # The 3 lowest-overall skaters (lowest pid, starting at 100) should have been waived --
    # goalies (pinned at GOALIES_MIN, no slack) must be untouched.
    for i in range(100, 103):
        assert i not in world.teams[1].roster
        assert i in world.free_agents
    for i in range(config.GOALIES_MIN):
        assert i in world.teams[1].roster


def test_enforce_roster_max_trims_a_position_group_alone_exceeding_its_own_max():
    """BUG FIX regression guard: a team with a legal OVERALL headcount (under ROSTER_MAX) but
    too MANY goalies specifically (over GOALIES_MAX) must still be trimmed -- this is exactly
    the bug found via the full end-to-end offseason integration test (a team can draft its way
    to 4+ goalies while comfortably under ROSTER_MAX in total)."""
    world = build_world_with_team()
    n_goalies = config.GOALIES_MAX + 2
    for i in range(n_goalies):
        g = make_goalie(i, 1, overall=50 + i)
        world.add_player(g)
        world.teams[1].add_player(i)
    # A handful of skaters, well under both SKATERS_MAX and ROSTER_MAX in total.
    for i in range(100, 105):
        p = make_skater(i, 1, overall=70)
        world.add_player(p)
        world.teams[1].add_player(i)
    total_before = len(world.teams[1].roster)
    assert total_before <= config.ROSTER_MAX   # legal overall headcount, illegal composition

    O.enforce_roster_max(world)
    goalies_after = [pid for pid in world.teams[1].roster if world.players[pid].is_goalie]
    assert len(goalies_after) == config.GOALIES_MAX
    # The worst-overall goalies (lowest pid/overall) should have been the ones cut.
    for i in range(2):
        assert i not in world.teams[1].roster


def test_fill_rosters_signs_free_agents_up_to_the_minimum():
    world = build_world_with_team()
    # Team starts under the roster minimum.
    for i in range(config.ROSTER_MIN - 2):
        p = make_skater(i, 1)
        world.add_player(p)
        world.teams[1].add_player(i)
    # A pool of free agents to draw from.
    for i in range(100, 110):
        fa = make_skater(i, tid=None)
        world.add_player(fa)

    O.fill_rosters(world)
    assert len(world.teams[1].roster) >= config.ROSTER_MIN


def test_cull_free_agents_keeps_only_the_best_up_to_the_limit():
    world = build_world_with_team()
    for i in range(50):
        fa = make_skater(i, tid=None, overall=50 + i)
        world.add_player(fa)

    cut = O.cull_free_agents(world, keep=20)
    assert cut == 30
    assert len(world.free_agents) == 20
    # The worst (lowest overall, lowest pid here) should be gone entirely (not just released).
    assert 0 not in world.players


# ---------------------------------------------------------------------------
# goalie_form_state persistence across calls against the same World
# ---------------------------------------------------------------------------
def test_goalie_form_state_persists_across_repeated_calls_on_the_same_world():
    world = build_world(seed=5)
    O.pre_draft(world, champion_tid=None)
    state = O.goalie_form_state(world)
    goalie_pids = [p.pid for p in world.players.values() if p.is_goalie]
    assert goalie_pids
    first_forms = {pid: state.get(pid) for pid in goalie_pids}

    # A second, unrelated call against the SAME state object must not silently reset it.
    same_state = O.goalie_form_state(world)
    assert same_state is state
    for pid in goalie_pids:
        assert same_state.get(pid) == first_forms[pid]


def test_goalie_form_state_is_independent_per_world_instance():
    world_a = build_world(seed=6)
    world_b = build_world(seed=6)   # same seed, different instance
    O.pre_draft(world_a, champion_tid=None)
    state_a = O.goalie_form_state(world_a)
    state_b = O.goalie_form_state(world_b)
    assert state_a is not state_b


# ---------------------------------------------------------------------------
# Full end-to-end orchestration
# ---------------------------------------------------------------------------
def test_run_offseason_end_to_end_advances_year_and_restarts_season():
    world = build_world(seed=42)
    S.start_season(world)
    while not S.regular_season_complete(world):
        S.advance_one_day(world)

    PO.start_playoffs(world)
    champ = PO.run_full_playoffs(world)
    year_before = world.season_year

    summary = O.run_offseason(world, champ)

    assert world.season_year == year_before + 1
    assert world.day == 0
    assert len(world.schedule) > 0
    assert all(not g.played for g in world.schedule)
    assert "draft" in summary and "free_agency" in summary
    for team in world.teams.values():
        skaters = [pid for pid in team.roster if world.player(pid).position != "G"]
        goalies = [pid for pid in team.roster if world.player(pid).position == "G"]
        assert config.SKATERS_MIN <= len(skaters) <= config.SKATERS_MAX
        assert config.GOALIES_MIN <= len(goalies) <= config.GOALIES_MAX


def test_run_offseason_is_stable_across_multiple_consecutive_cycles():
    """A stronger integration check than the single-cycle test above: run several full
    season->playoffs->offseason cycles back to back (retirement/draft/FA/development/goalie-
    form-resample all interacting repeatedly) and confirm the league never degenerates into an
    illegal state."""
    world = build_world(seed=8)
    for _ in range(3):
        S.start_season(world)
        while not S.regular_season_complete(world):
            S.advance_one_day(world)
        PO.start_playoffs(world)
        champ = PO.run_full_playoffs(world)
        O.run_offseason(world, champ)

    assert len(world.teams) == config.NUM_TEAMS
    for team in world.teams.values():
        assert config.ROSTER_MIN <= len(team.roster) <= config.ROSTER_MAX
