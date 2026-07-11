"""Coverage for xG / xA (DESIGN.md point 10, DEVPLAN.md Step 2.x).

The shot-attempt event stream always carried the danger context (zone/shot-type/strength/rush/
rebound) but no xG value was ever produced. Now every shot on goal carries an expected-goals value
credited to the shooter (xg) and the goalie facing it (xga), and a goal's assisters earn the chance
they set up as xA. Guarantees pinned here:
  * xG is a good (roughly unbiased) model -- league-wide summed xG tracks actual goals;
  * a shooter's xg only accrues on his shots on goal, and a goalie's xga on shots he faced;
  * xA accrues to assisters; and
  * every shot on goal's event carries a positive xG.
"""
from __future__ import annotations

from pucksim.gen.leaguegen import build_world
from pucksim.sim.boxscore import EVENT_GOAL, EVENT_SHOT, SHOT_OUTCOME_SAVE
from pucksim.sim.engine import GameSim


def test_league_wide_xg_tracks_actual_goals():
    """A good xG model is roughly unbiased: summed xG across the league should land within ~20%
    of actual goals (they won't match exactly -- real goalies + realization stop a touch more than
    the neutral-average baseline xG assumes)."""
    total_goals = total_xg = total_xga = 0.0
    n = 60
    for seed in range(n):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        result = GameSim(world, tids[0], tids[1]).play()
        total_goals += result.home_score + result.away_score
        total_xg += sum(l.xg for l in result.skater_box.values())
        total_xga += sum(l.xga for l in result.goalie_box.values())
    assert total_goals > 0
    assert 0.8 <= total_xg / total_goals <= 1.25, f"xG/goals ratio {total_xg / total_goals:.2f}"
    # xGA (goalie-charged) tracks xG (shooter-credited) closely -- both count the same shots on
    # goal, differing only by empty-net attempts (which have xg but no goalie to charge xga to).
    assert total_xga <= total_xg
    assert total_xga >= total_xg * 0.9


def test_every_shot_on_goal_event_carries_positive_xg():
    """Each save/goal event (a shot that reached the net) must carry a positive xG; a
    blocked/missed attempt that never threatened carries none."""
    world = build_world(seed=3)
    tids = sorted(world.teams.keys())
    result = GameSim(world, tids[0], tids[1], collect_pbp=True).play()
    on_goal = [e for e in result.pbp
               if (e.event_type == EVENT_GOAL) or (e.event_type == EVENT_SHOT and e.outcome == SHOT_OUTCOME_SAVE)]
    assert on_goal, "expected at least some shots on goal"
    assert all(e.xg > 0 for e in on_goal)


def test_shooter_xg_reconciles_with_on_goal_events():
    """A team's summed shooter xg equals the summed xG of that team's own shots on goal (saves +
    goals) plus its empty-net attempts -- xg is credited exactly once per shot on goal."""
    world = build_world(seed=8)
    tids = sorted(world.teams.keys())
    home = tids[0]
    result = GameSim(world, home, tids[1], collect_pbp=True).play()
    home_team = world.team(home)
    box_xg = sum(result.skater_box[pid].xg for pid in home_team.roster
                 if pid in result.skater_box)
    # Every logged shot event for the home team that carries xg > 0 is a shot on goal (or empty
    # net); missed/blocked attempts carry xg == 0.
    event_xg = sum(e.xg for e in result.pbp
                   if e.event_type in (EVENT_SHOT, EVENT_GOAL) and e.team_id == home)
    assert abs(box_xg - event_xg) < 1e-6, f"box xg {box_xg} != event xg {event_xg}"


def test_assisters_earn_expected_assists():
    """xA accrues to goal assisters across a season sample -- a team that scores assisted goals
    records positive league-wide xA."""
    total_xa = 0.0
    for seed in range(20):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        result = GameSim(world, tids[0], tids[1]).play()
        total_xa += sum(l.xa for l in result.skater_box.values())
    assert total_xa > 0
