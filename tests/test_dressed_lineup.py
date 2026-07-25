"""The 20-player game-night dress limit and explicit healthy scratches.

Before this existed the engine had no scratch concept: every rostered player was eligible to be
fielded, so a 22- or 23-man roster effectively dressed all of them. The NHL limit is 20 -- 18
skaters plus 2 goalies -- and everyone else is a healthy scratch.
"""
import pytest

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.models.player import Injury
from pucksim.models.team import dressed_lineup
from pucksim.sim.engine import GameSim

_FORWARDS = ("LW", "C", "RW")




def _players(world, team):
    return {pid: world.player(pid) for pid in team.roster}


def _injure(world, pid, games=5):
    world.player(pid).injury = Injury(description="knee", games_remaining=games)


# ---------------------------------------------------------------------------
# The limit itself
# ---------------------------------------------------------------------------
def test_every_team_dresses_exactly_the_limit():
    world = build_world(seed=7)
    for tid in sorted(world.teams.keys()):
        team = world.team(tid)
        lineup = dressed_lineup(team, _players(world, team))
        dressed = [world.player(pid) for pid in lineup.dressed]
        skaters = [p for p in dressed if p.position != "G"]
        goalies = [p for p in dressed if p.position == "G"]
        assert len(lineup.dressed) == config.DRESSED_PLAYERS_PER_GAME, f"team {tid}"
        assert len(skaters) == config.DRESSED_SKATERS_PER_GAME, f"team {tid}"
        assert len(goalies) == config.DRESSED_GOALIES_PER_GAME, f"team {tid}"
        # Everyone is accounted for exactly once.
        buckets = set(lineup.dressed) | set(lineup.scratched) | set(lineup.injured)
        assert buckets == set(team.roster), f"team {tid} lost or duplicated a player"
        assert not lineup.short_skaters and not lineup.short_goalies


def test_auto_scratches_are_the_weakest_players():
    """With no explicit instruction, the players who sit are the depth ones -- not an arbitrary
    slice of the roster."""
    world = build_world(seed=7)
    team = world.team(0)
    lineup = dressed_lineup(team, _players(world, team))
    assert lineup.scratched, "a 22-man roster must scratch somebody"
    worst_dressed = min(world.player(pid).overall for pid in lineup.dressed
                        if world.player(pid).position != "G")
    for pid in lineup.scratched:
        if world.player(pid).position != "G":
            assert world.player(pid).overall <= worst_dressed


def test_result_is_deterministic():
    """Two equally-rated, equally-slotted players must not swap places between runs, or the same
    seed would stop reproducing the same game."""
    world = build_world(seed=7)
    team = world.team(0)
    players = _players(world, team)
    assert dressed_lineup(team, players).dressed == dressed_lineup(team, players).dressed


# ---------------------------------------------------------------------------
# Explicit scratches
# ---------------------------------------------------------------------------
def test_explicit_scratch_is_honored_even_for_a_star():
    """The user's instruction wins whenever a legal lineup can still be iced without the player --
    including when he is the best player on the team."""
    world = build_world(seed=7)
    team = world.team(0)
    star = max((pid for pid in team.roster if world.player(pid).position != "G"),
               key=lambda pid: world.player(pid).overall)
    team.scratches = [star]
    lineup = dressed_lineup(team, _players(world, team))
    assert star not in lineup.dressed
    assert star in lineup.scratched
    assert not lineup.promoted


def test_explicit_scratches_are_promoted_when_injuries_deplete_the_roster():
    """Auto-promote rather than refusing to sim, and report it. A lineup the user hasn't gotten
    around to fixing must never block a season."""
    world = build_world(seed=7)
    team = world.team(0)
    skaters = [pid for pid in team.roster if world.player(pid).position != "G"]
    team.scratches = list(skaters[:6])
    for pid in skaters[6:11]:
        _injure(world, pid)

    lineup = dressed_lineup(team, _players(world, team))
    assert lineup.promoted, "should have promoted scratches to fill the lineup"
    assert set(lineup.promoted) <= set(team.scratches)
    # The promoted players are the BEST of the ones asked to sit, not an arbitrary pick.
    promoted_ovr = [world.player(pid).overall for pid in lineup.promoted]
    still_sitting = [world.player(pid).overall for pid in lineup.scratched
                     if pid in set(team.scratches)]
    if still_sitting:
        assert min(promoted_ovr) >= max(still_sitting)


def test_injured_players_are_never_counted_as_scratches():
    """The two reasons a player doesn't dress are not interchangeable: a UI that showed an injured
    player as a healthy scratch would be lying, and a returning player must not silently stay out."""
    world = build_world(seed=7)
    team = world.team(0)
    hurt = team.roster[0]
    _injure(world, hurt)
    lineup = dressed_lineup(team, _players(world, team))
    assert hurt in lineup.injured
    assert hurt not in lineup.scratched
    assert hurt not in lineup.dressed


def test_shortfall_is_reported_rather_than_raising():
    """A genuinely depleted roster plays short-handed. Never crash, never refuse."""
    world = build_world(seed=7)
    team = world.team(0)
    for pid in [p for p in team.roster if world.player(p).position != "G"][:6]:
        _injure(world, pid)
    lineup = dressed_lineup(team, _players(world, team))
    assert lineup.short_skaters > 0
    dressed_skaters = sum(1 for pid in lineup.dressed if world.player(pid).position != "G")
    assert dressed_skaters == config.DRESSED_SKATERS_PER_GAME - lineup.short_skaters


def test_must_dress_forces_a_player_in():
    """sim/season.py's rest-based rotation can name the backup goalie as tonight's starter.
    Scratching that goalie must not field a goalie who isn't dressed."""
    world = build_world(seed=7)
    team = world.team(0)
    goalies = [pid for pid in team.roster if world.player(pid).position == "G"]
    team.scratches = list(goalies)
    lineup = dressed_lineup(team, _players(world, team), must_dress={goalies[0]})
    assert goalies[0] in lineup.dressed
    assert goalies[0] not in lineup.promoted, "a must_dress player is not an override"


# ---------------------------------------------------------------------------
# The engine honors it
# ---------------------------------------------------------------------------
def test_scratched_players_get_no_ice_time():
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    scratched = set(sim.home.dressed.scratched)
    assert scratched, "expected somebody to be scratched"
    result = sim.play()
    for pid in scratched:
        line = result.skater_box.get(pid)
        assert line is None or line.secs == 0, f"scratched player {pid} played {line.secs}s"


def test_explicitly_scratched_star_does_not_play():
    world = build_world(seed=7)
    team = world.team(0)
    star = max((pid for pid in team.roster if world.player(pid).position != "G"),
               key=lambda pid: world.player(pid).overall)
    team.scratches = [star]
    result = GameSim(world, 0, 1).play()
    line = result.skater_box.get(star)
    assert line is None or line.secs == 0


def test_mid_game_injury_backfills_from_dressed_players_only():
    """With exactly 18 skaters dressed, a mid-game injury must be covered by the other dressed
    skaters -- never by pulling a scratch out of the press box."""
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    scratched = set(sim.home.dressed.scratched)
    result = sim.play()
    played = {pid for pid, line in result.skater_box.items() if line.secs > 0}
    assert not (played & scratched)


def test_starting_goalie_is_always_dressed():
    """Covers the season path's goalie override, which is resolved outside dressed_lineup."""
    world = build_world(seed=7)
    team = world.team(0)
    goalies = [pid for pid in team.roster if world.player(pid).position == "G"]
    team.scratches = list(goalies)
    backup = goalies[-1]
    sim = GameSim(world, 0, 1, home_goalie_id=backup)
    assert sim.home.goalie_id == backup
    assert backup in sim.home.dressed.dressed


@pytest.mark.parametrize("seed", [3, 7, 11])
def test_dress_limit_holds_across_a_played_game(seed):
    """End-to-end: no more than the limit ever records ice time for either team."""
    world = build_world(seed=seed)
    result = GameSim(world, 0, 1).play()
    for tid in (0, 1):
        roster = set(world.team(tid).roster)
        played = {pid for pid, line in result.skater_box.items()
                  if line.secs > 0 and pid in roster}
        goalies = {pid for pid, line in result.goalie_box.items()
                   if line.secs > 0 and pid in roster}
        assert len(played) <= config.DRESSED_SKATERS_PER_GAME, f"team {tid} iced {len(played)}"
        assert len(goalies) <= config.DRESSED_GOALIES_PER_GAME


# ---------------------------------------------------------------------------
# Injury redistributes ice time to the right players
# ---------------------------------------------------------------------------
def _toi_per_game(seed, injure_pid=None, games=6):
    world = build_world(seed=seed)
    team = world.team(0)
    if injure_pid is not None:
        _injure(world, injure_pid, games=40)
    totals = {}
    for i in range(games):
        result = GameSim(world, 0, 1 + i).play()
        for pid, line in result.skater_box.items():
            if pid in team.roster:
                totals[pid] = totals.get(pid, 0) + line.secs / games / 60.0
    return world, team, totals


def test_an_injured_forwards_minutes_go_to_forwards():
    """A first-line centre going down should promote FORWARDS. Replacement used to run through
    _backfill_from_bench, which takes the highest-``overall`` available skater of any position -- so
    an injured centre handed his minutes to defensemen, one of whom went from 25.6 to 32.8 minutes a
    game while the actual forwards barely moved."""
    world, team, before = _toi_per_game(7)
    star = team.lines[0][1]
    assert world.player(star).position in _FORWARDS
    _, _, after = _toi_per_game(7, injure_pid=star)

    assert after.get(star, 0.0) == 0.0
    gains = sorted(((after.get(pid, 0.0) - before.get(pid, 0.0), pid) for pid in team.roster
                    if world.player(pid).position != "G"), reverse=True)
    top_gainers = [pid for _, pid in gains[:3]]
    assert all(world.player(pid).position in _FORWARDS for pid in top_gainers), (
        "a forward's ice time went to defensemen: "
        f"{[(world.player(p).name, world.player(p).position) for p in top_gainers]}")


def test_injury_replacement_does_not_create_a_35_minute_skater():
    """Guards the specific absurdity the old backfill produced."""
    world, team, _ = _toi_per_game(7)
    star = team.lines[0][1]
    _, _, after = _toi_per_game(7, injure_pid=star)
    worst = max(after.values())
    assert worst <= 30.0, f"somebody is playing {worst:.1f} minutes a game"


def test_injury_draws_a_scratch_into_the_lineup():
    """The dress limit means a healthy scratch should be promoted, keeping 18 skaters dressed -- and
    it is part of how a season spreads games across more than the same 18 players."""
    world, team, before = _toi_per_game(7)
    star = team.lines[0][1]
    _, _, after = _toi_per_game(7, injure_pid=star)
    used_before = sum(1 for v in before.values() if v > 0)
    used_after = sum(1 for v in after.values() if v > 0)
    assert used_after >= used_before, f"{used_before} skaters used -> {used_after}"
    promoted = [pid for pid in team.roster
                if before.get(pid, 0.0) == 0.0 and after.get(pid, 0.0) > 0.0]
    assert promoted, "no scratched player was drawn in to replace the injury"
