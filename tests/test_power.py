"""Tests for sim.power -- team strength / power ratings.

Covers the two reads the module produces: the preseason ``projected_strength``/``strength_stars``
(a no-games-needed roster-talent read, used on the team-selection screen so the user knows how
good a team they're taking over) and the in-season blended ``power_ratings`` (SRS + prior).
"""
from __future__ import annotations

from pucksim.gen.leaguegen import build_world
from pucksim.models.league import Game
from pucksim.sim import power

SEED = 42


# ---------------------------------------------------------------------------
# Preseason projected strength / stars (the team-selection use case)
# ---------------------------------------------------------------------------
def test_projected_strength_available_before_any_games():
    """Strength is a pure roster read -- it must work off a freshly built, 0-games world."""
    world = build_world(seed=SEED)
    strength = power.projected_strength(world)

    assert set(strength) == {t.tid for t in world.team_list()}
    # Every team lands on the familiar overall-ish scale, not a degenerate 0 or a runaway value.
    for val in strength.values():
        assert 40 <= val <= 99


def test_strength_correlates_with_roster_overall():
    """A team's projected strength should track its roster's raw talent: the strongest-by-mean
    roster should not project as one of the league's weakest, and vice versa."""
    world = build_world(seed=SEED)
    strength = power.projected_strength(world)

    def roster_mean(team):
        players = [world.players[pid] for pid in team.roster if pid in world.players]
        return sum(p.overall for p in players) / len(players)

    teams = world.team_list()
    by_roster = sorted(teams, key=roster_mean)
    weakest_roster, strongest_roster = by_roster[0], by_roster[-1]
    assert strength[strongest_roster.tid] > strength[weakest_roster.tid]


def test_strength_stars_span_full_range_and_spread():
    """Rank-based stars must spread 1..5 across a full 32-team league (never all clustered)."""
    world = build_world(seed=SEED)
    stars = power.strength_stars(world)

    assert set(stars) == {t.tid for t in world.team_list()}
    assert min(stars.values()) == 1
    assert max(stars.values()) == 5
    # Genuinely spread, not two lumps at the extremes.
    assert len(set(stars.values())) == 5


def test_stars_are_monotonic_in_strength():
    """A team with more stars must not have a lower projected strength than one with fewer."""
    world = build_world(seed=SEED)
    strength = power.projected_strength(world)
    stars = power.strength_stars(world)

    for a in world.team_list():
        for b in world.team_list():
            if stars[a.tid] > stars[b.tid]:
                assert strength[a.tid] >= strength[b.tid]


def test_goalie_swings_team_strength():
    """A starting goalie is weighted into the read, so swapping in a much better goalie must
    raise the team's projected strength (DESIGN.md point 4: outsized goalie impact)."""
    world = build_world(seed=SEED)
    team = world.team_list()[0]
    before = power.projected_strength(world)[team.tid]

    goalies = [world.players[pid] for pid in team.roster
               if pid in world.players and world.players[pid].position == "G"]
    assert goalies, "expected the generated roster to carry at least one goalie"
    for g in goalies:
        for key in list(g.ratings):
            g.ratings[key] = 99
        g.ratings["reflexes"] = g.ratings["positioning"] = 99

    after = power.projected_strength(world)[team.tid]
    assert after > before


# ---------------------------------------------------------------------------
# In-season power ratings (SRS + prior blend)
# ---------------------------------------------------------------------------
def test_power_ratings_are_league_mean_zero_and_ranked():
    world = build_world(seed=SEED)
    ratings = power.power_ratings(world)

    assert len(ratings) == len(world.team_list())
    # De-meaned: league net rating sums to ~0.
    assert abs(sum(r.power for r in ratings)) < 1e-6
    # Ranked best-first, contiguous 1..N, power monotonically non-increasing.
    assert [r.rank for r in ratings] == list(range(1, len(ratings) + 1))
    for a, b in zip(ratings, ratings[1:]):
        assert a.power >= b.power


def test_power_ratings_reduce_to_prior_with_no_games():
    """With zero games played the blend weight on results is 0, so power == the (de-meaned)
    roster prior exactly."""
    world = build_world(seed=SEED)
    priors = power.roster_priors(world)
    mean = sum(priors.values()) / len(priors)
    pmap = power.power_map(world)
    for tid, prior in priors.items():
        assert pmap[tid].power == prior - mean
        assert pmap[tid].srs == 0.0


def test_srs_rewards_winning():
    """A team that wins every game it plays should end up with a positive SRS."""
    world = build_world(seed=SEED)
    teams = world.team_list()
    winner = teams[0]

    # Fabricate a handful of decisive wins for `winner` against distinct opponents.
    gid = 900000
    for opp in teams[1:6]:
        world.schedule.append(Game(gid=gid, day=1, home=winner.tid, away=opp.tid,
                                    home_score=4, away_score=1, played=True))
        gid += 1

    srs, _ = power.compute_srs(world)
    assert srs[winner.tid] > 0.0


def test_win_pct_projection_monotonic_and_bounded():
    world = build_world(seed=SEED)
    for r in power.power_ratings(world):
        assert 0.0 < r.proj_win_pct < 1.0
    # A better net rating never projects a worse win pct.
    ranked = power.power_ratings(world)
    for a, b in zip(ranked, ranked[1:]):
        assert a.proj_win_pct >= b.proj_win_pct
