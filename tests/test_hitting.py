"""Coverage for the hitting mechanic (DEVPLAN.md Step 2.x "impactful ratings").

Before this step the engine had NO hit mechanic and the hits/takeaways/giveaways stat fields were
never incremented -- checking and strength touched nothing in live play. This step adds body
checks each shot-attempt cycle, credited by checking+strength, with a defensive check able to
SEPARATE the carrier (a forced turnover -> takeaway/giveaway). Guarantees pinned here:
  * hits land at a realistic NHL rate and physical teams throw more of them;
  * a heavy-checking team forces materially more takeaways (checking's gameplay teeth);
  * every forced turnover reconciles (one takeaway <-> one giveaway); and
  * adding all this doesn't distort league scoring.
"""
from __future__ import annotations

from pucksim.gen.leaguegen import build_world
from pucksim.sim.engine import GameSim


def _team_skater_pids(world, tid) -> set[int]:
    return {p.pid for p in world.players.values() if p.team_id == tid and not p.is_goalie}


def _pin_team_physicality(world, tid, value: int) -> set[int]:
    pids = _team_skater_pids(world, tid)
    for pid in pids:
        world.players[pid].ratings["checking"] = value
        world.players[pid].ratings["strength"] = value
    return pids


def test_hits_land_at_a_realistic_rate():
    total_hits = 0
    n = 60
    for seed in range(n):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        result = GameSim(world, tids[0], tids[1]).play()
        total_hits += sum(line.hits for line in result.skater_box.values())
    per_team = total_hits / n / 2
    assert 14.0 <= per_team <= 30.0, f"hits/team/game {per_team:.1f} outside realistic band"


def test_physical_teams_record_more_hits():
    def team_hits(value: int) -> int:
        total = 0
        for g in range(30):
            world = build_world(seed=200 + g)
            tids = sorted(world.teams.keys())
            pids = _pin_team_physicality(world, tids[1], value)
            result = GameSim(world, tids[0], tids[1]).play()
            total += sum(l.hits for pid, l in result.skater_box.items() if pid in pids)
        return total
    assert team_hits(99) > team_hits(25)


def test_heavy_checking_forces_more_takeaways():
    """The gameplay teeth of checking/strength: a wall of heavy checkers strips the puck (forced
    turnovers) far more often than a soft team does."""
    def team_takeaways(value: int) -> int:
        total = 0
        for g in range(30):
            world = build_world(seed=400 + g)
            tids = sorted(world.teams.keys())
            pids = _pin_team_physicality(world, tids[1], value)
            result = GameSim(world, tids[0], tids[1]).play()
            total += sum(l.takeaways for pid, l in result.skater_box.items() if pid in pids)
        return total
    assert team_takeaways(99) > team_takeaways(25) * 3


def test_every_takeaway_reconciles_with_a_giveaway():
    """A forced turnover is one team's takeaway and the other's giveaway -- league totals match."""
    for seed in range(30):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        result = GameSim(world, tids[0], tids[1]).play()
        takeaways = sum(l.takeaways for l in result.skater_box.values())
        giveaways = sum(l.giveaways for l in result.skater_box.values())
        assert takeaways == giveaways


def test_scoring_stays_realistic_with_hitting_on():
    """Calibration guardrail: the hit/turnover mechanic must not distort league scoring."""
    total_goals = 0
    n = 120
    for seed in range(n):
        world = build_world(seed=seed)
        tids = sorted(world.teams.keys())
        result = GameSim(world, tids[0], tids[1]).play()
        total_goals += result.home_score + result.away_score
    per_game = total_goals / n
    assert 4.6 <= per_game <= 6.6, f"goals/game drifted to {per_game:.2f}"
