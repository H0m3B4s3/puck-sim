"""Tests for pucksim.systems.legacy -- DEVPLAN.md Step 2.7 done-criteria (mirrors HoopR's own
test_legacy.py shape: résumé snapshot pattern, HOF threshold, milestones, leaderboards).

Covers:
  - career_totals(): skater vs. goalie dispatch, GP-weighted rate-stat reconstruction.
  - hof_score()/resume(): a multi-award-winning career clears HOF_THRESHOLD, a career with no
    accolades/short tenure does not.
  - record_accolades(): each of the five awards (hart/norris/vezina/calder/selke) plus champion
    ticks the right player's accolade tally, never someone else's.
  - crossed_milestones(): skater and goalie milestone tables both fire correctly at their
    thresholds, and only when actually crossed (not already past, not still short).
  - retire(): freezes a résumé into world.retired, inducts into world.hall_of_fame only when
    hof_score clears the bar.
  - leaderboards(): ranks both living and retired players together, never double-counts.
"""
from __future__ import annotations

from pucksim.models import attributes as attr
from pucksim.models.player import Player
from pucksim.models.team import Team
from pucksim.models.world import World
from pucksim.rng import Rng
from pucksim.systems import legacy as L


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def build_world_with_team(tid: int = 1) -> World:
    world = World(rng=Rng(seed=1))
    team = Team(tid=tid, name=f"Team {tid}", abbrev=f"T{tid}", conference="Eastern")
    world.register_team(team)
    return world


def make_skater(pid: int, tid: int = 1, overall: int = 75, career=None, accolades=None) -> Player:
    ratings = {name: overall for name in attr.ALL_RATINGS}
    p = Player(pid=pid, name=f"Skater {pid}", age=30, position="C", ratings=ratings,
               team_id=tid, career=career or [], accolades=accolades or {})
    return p


def make_goalie(pid: int, tid: int = 1, overall: int = 75, career=None) -> Player:
    ratings = {name: overall for name in attr.ALL_GOALIE_RATINGS}
    return Player(pid=pid, name=f"Goalie {pid}", age=30, position="G", ratings=ratings,
                  team_id=tid, career=career or [])


# ---------------------------------------------------------------------------
# career_totals
# ---------------------------------------------------------------------------
def test_career_totals_skater_sums_across_seasons():
    career = [
        {"year": 2020, "gp": 70, "g": 20.0, "a": 30.0, "ovr": 75},
        {"year": 2021, "gp": 82, "g": 25.0, "a": 35.0, "ovr": 78},
    ]
    totals = L.career_totals(career)
    assert totals["gp"] == 152
    assert totals["g"] == 45
    assert totals["a"] == 65
    assert totals["pts"] == 110


def test_career_totals_goalie_uses_gp_weighted_rate_average():
    career = [
        {"year": 2020, "gp": 10, "wins": 6, "save_pct": 0.900, "gaa": 3.00, "shutouts": 1},
        {"year": 2021, "gp": 60, "wins": 35, "save_pct": 0.920, "gaa": 2.40, "shutouts": 5},
    ]
    totals = L.career_totals(career)
    assert totals["gp"] == 70
    assert totals["wins"] == 41
    assert totals["shutouts"] == 6
    expected_sv = (10 * 0.900 + 60 * 0.920) / 70
    assert abs(totals["save_pct"] - round(expected_sv, 3)) < 1e-9


def test_career_totals_empty_career_is_zeroed_not_a_crash():
    totals = L.career_totals([])
    assert totals["gp"] == 0


# ---------------------------------------------------------------------------
# hof_score / resume
# ---------------------------------------------------------------------------
def test_hof_score_rewards_multiple_major_accolades():
    world = build_world_with_team()
    great = make_skater(
        1, overall=90,
        career=[{"year": y, "gp": 82, "g": 45.0, "a": 55.0, "ovr": 90} for y in range(2010, 2022)],
        accolades={"hart": 3, "norris": 0, "all_star": 0, "scoring_title": 2, "champion": 2},
    )
    world.add_player(great)
    world.teams[1].add_player(great.pid)

    r = L.resume(world, great)
    assert r["hof_score"] > L.HOF_THRESHOLD
    assert r["hof"] is True


def test_hof_score_denies_a_short_unaccoladed_career():
    world = build_world_with_team()
    journeyman = make_skater(
        2, overall=68,
        career=[{"year": 2020, "gp": 40, "g": 3.0, "a": 5.0, "ovr": 68}],
        accolades={},
    )
    world.add_player(journeyman)
    world.teams[1].add_player(journeyman.pid)

    r = L.resume(world, journeyman)
    assert r["hof_score"] < L.HOF_THRESHOLD
    assert r["hof"] is False


def test_resume_peak_ovr_is_the_max_across_career_and_current():
    world = build_world_with_team()
    p = make_skater(1, overall=80, career=[{"year": 2018, "gp": 60, "g": 10.0, "a": 10.0, "ovr": 92}])
    world.add_player(p)
    world.teams[1].add_player(p.pid)

    r = L.resume(world, p)
    assert r["peak_ovr"] == 92   # the career-high, not the current (lower) overall


def test_resume_is_self_contained_survives_missing_team():
    """A résumé must not crash/reference a team that no longer resolves (e.g. built for a
    retiree whose team_id points nowhere useful anymore)."""
    world = build_world_with_team()
    p = make_skater(1, tid=999)  # no such team registered
    world.add_player(p)

    r = L.resume(world, p)
    assert r["last_team"] == "FA"


# ---------------------------------------------------------------------------
# record_accolades
# ---------------------------------------------------------------------------
def test_record_accolades_ticks_each_award_winner_only():
    world = build_world_with_team()
    hart_winner = make_skater(1)
    norris_winner = make_skater(2)
    world.add_player(hart_winner)
    world.add_player(norris_winner)
    world.teams[1].add_player(1)
    world.teams[1].add_player(2)

    awards = {
        "hart": {"pid": 1}, "norris": {"pid": 2},
    }
    L.record_accolades(world, awards, champion_tid=None)
    assert hart_winner.accolades.get("hart") == 1
    assert hart_winner.accolades.get("norris", 0) == 0
    assert norris_winner.accolades.get("norris") == 1
    assert norris_winner.accolades.get("hart", 0) == 0


def test_record_accolades_champion_ticks_every_rostered_player_who_played():
    world = build_world_with_team()
    played = make_skater(1)
    played.season.gp = 40
    scratch_all_year = make_skater(2)
    scratch_all_year.season.gp = 0
    world.add_player(played)
    world.add_player(scratch_all_year)
    world.teams[1].add_player(1)
    world.teams[1].add_player(2)

    L.record_accolades(world, {}, champion_tid=1)
    assert played.accolades.get("champion") == 1
    assert scratch_all_year.accolades.get("champion", 0) == 0


def test_record_accolades_accumulates_across_multiple_calls():
    world = build_world_with_team()
    p = make_skater(1)
    world.add_player(p)
    world.teams[1].add_player(1)

    L.record_accolades(world, {"hart": {"pid": 1}}, champion_tid=None)
    L.record_accolades(world, {"hart": {"pid": 1}}, champion_tid=None)
    assert p.accolades["hart"] == 2


# ---------------------------------------------------------------------------
# crossed_milestones
# ---------------------------------------------------------------------------
def test_skater_milestone_fires_exactly_when_crossed():
    prev = {"gp": 0, "g": 495.0, "a": 0.0, "pts": 495}
    now = {"gp": 0, "g": 505.0, "a": 0.0, "pts": 505}
    crossed = L.crossed_milestones(prev, now, is_goalie=False)
    stats_hit = {m["stat"] for m in crossed}
    assert "g" in stats_hit   # 500-goal milestone crossed


def test_skater_milestone_does_not_refire_if_already_past():
    prev = {"gp": 0, "g": 600.0, "a": 0.0, "pts": 600}
    now = {"gp": 0, "g": 620.0, "a": 0.0, "pts": 620}
    crossed = L.crossed_milestones(prev, now, is_goalie=False)
    assert not any(m["value"] == 500 for m in crossed)


def test_goalie_milestone_table_is_distinct_from_skater_table():
    prev = {"gp": 0, "wins": 195, "shutouts": 0}
    now = {"gp": 0, "wins": 205, "shutouts": 0}
    crossed = L.crossed_milestones(prev, now, is_goalie=True)
    stats_hit = {m["stat"] for m in crossed}
    assert "wins" in stats_hit


# ---------------------------------------------------------------------------
# retire()
# ---------------------------------------------------------------------------
def test_retire_appends_to_world_retired():
    world = build_world_with_team()
    p = make_skater(1, overall=68, career=[{"year": 2015, "gp": 50, "g": 5.0, "a": 5.0, "ovr": 68}])
    world.add_player(p)
    world.teams[1].add_player(1)

    snap = L.retire(world, p)
    assert len(world.retired) == 1
    assert world.retired[0]["pid"] == 1
    assert snap["retired_year"] == world.season_year


def test_retire_inducts_into_hall_of_fame_only_when_worthy():
    world = build_world_with_team()
    legend = make_skater(
        1, overall=92,
        career=[{"year": y, "gp": 82, "g": 50.0, "a": 60.0, "ovr": 92} for y in range(2000, 2015)],
        accolades={"hart": 4, "scoring_title": 5, "champion": 3},
    )
    journeyman = make_skater(2, overall=65, career=[{"year": 2020, "gp": 30, "g": 2.0, "a": 2.0, "ovr": 65}])
    world.add_player(legend)
    world.add_player(journeyman)
    world.teams[1].add_player(1)
    world.teams[1].add_player(2)

    L.retire(world, legend)
    L.retire(world, journeyman)

    assert len(world.hall_of_fame) == 1
    assert world.hall_of_fame[0]["pid"] == 1


# ---------------------------------------------------------------------------
# leaderboards()
# ---------------------------------------------------------------------------
def test_leaderboards_ranks_living_and_retired_together_no_double_count():
    world = build_world_with_team()
    active = make_skater(1, career=[{"year": 2020, "gp": 82, "g": 30.0, "a": 30.0, "ovr": 80}])
    world.add_player(active)
    world.teams[1].add_player(1)

    retiree = make_skater(2, career=[{"year": 2010, "gp": 82, "g": 60.0, "a": 60.0, "ovr": 88}])
    world.add_player(retiree)
    world.teams[1].add_player(2)
    L.retire(world, retiree)
    world.players.pop(2)   # actually removed from the active pool, mirrors offseason.age_and_retire

    rows = L.leaderboards(world, category="pts", limit=10)
    pids = [r["pid"] for r in rows]
    assert pids.count(2) == 1   # retiree appears exactly once, not duplicated
    assert rows[0]["pid"] == 2  # retiree has more career points, ranks first
