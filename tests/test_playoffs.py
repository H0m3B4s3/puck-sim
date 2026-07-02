"""Tests for pucksim.sim.playoffs + the playoff officiating/discipline mode -- DEVPLAN.md
Step 2.6 done-criteria.

Covers: bracket seeding/advancement correctness (conference-based top-N, best-of-7 series,
round-by-round advancement to a single champion), playoff OT uses 5-on-5 not 3-on-3 (delegated
to tests/test_ot_shootout.py's dedicated coverage, referenced here only where it matters for
bracket integration), playoff games under "realistic" discipline mode draw measurably fewer
penalties than an equivalent regular-season game (statistical sweep), "regular_season" mode
shows no measurable difference, and World.playoff_discipline_mode round-trips through
to_dict/from_dict.
"""
from __future__ import annotations

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.models.league import Phase, conference_standings
from pucksim.models.world import World
from pucksim.sim import playoffs as PO
from pucksim.sim.boxscore import EVENT_PENALTY
from pucksim.sim.engine import GameSim
from pucksim.sim.season import advance_one_day, generate_schedule, regular_season_complete


def _completed_regular_season(seed: int, games: int = 20, standings_rule: str = "standard") -> World:
    world = build_world(seed=seed)
    world.standings_rule = standings_rule
    world.schedule = generate_schedule(world, target_games=games)
    world.day = 0
    for team in world.teams.values():
        team.reset_record()
    while not regular_season_complete(world):
        advance_one_day(world)
    return world


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------
def test_start_playoffs_seeds_conference_based_top_n():
    world = _completed_regular_season(seed=1)
    PO.start_playoffs(world)

    grouped = conference_standings(world.team_list(), world.schedule, world.standings_rule)
    for conf in config.CONFERENCES:
        expected_top_n = [t.tid for t in grouped[conf][: config.PLAYOFF_TEAMS_PER_CONF]]
        seeded_tids = [tid for tid, seed in world.bracket["seeds"].items()
                      if world.teams[int(tid)].conference == conf]
        assert set(int(t) for t in seeded_tids) == set(expected_top_n)
        # Seed 1 really is the best regular-season team in that conference.
        seed_1_tid = next(int(tid) for tid, seed in world.bracket["seeds"].items() if seed == 1
                          and world.teams[int(tid)].conference == conf)
        assert seed_1_tid == expected_top_n[0]


def test_start_playoffs_builds_correct_first_round_bracket_shape():
    """1v8 / 4v5 / 3v6 / 2v7 within each conference -- the standard seeding shape."""
    world = _completed_regular_season(seed=2)
    PO.start_playoffs(world)

    for conf in config.CONFERENCES:
        conf_series = [s for s in world.bracket["series"] if s["conf"] == conf]
        assert len(conf_series) == 4
        matchup_seed_pairs = set()
        for s in conf_series:
            hi_seed = world.bracket["seeds"][str(s["hi"])]
            lo_seed = world.bracket["seeds"][str(s["lo"])]
            matchup_seed_pairs.add(tuple(sorted((hi_seed, lo_seed))))
        assert matchup_seed_pairs == {(1, 8), (4, 5), (3, 6), (2, 7)}


def test_start_playoffs_sets_phase_to_playoffs():
    world = _completed_regular_season(seed=3)
    PO.start_playoffs(world)
    assert world.phase == Phase.PLAYOFFS


# ---------------------------------------------------------------------------
# Series / round advancement
# ---------------------------------------------------------------------------
def test_series_closes_out_at_four_wins():
    world = _completed_regular_season(seed=4)
    PO.start_playoffs(world)
    s = world.bracket["series"][0]
    PO.play_series_to_completion(world, s)

    assert s["winner"] is not None
    assert max(s["hi_w"], s["lo_w"]) == PO.WINS_NEEDED
    assert min(s["hi_w"], s["lo_w"]) < PO.WINS_NEEDED
    assert s["hi_w"] + s["lo_w"] <= PO.BEST_OF
    assert len(s["games"]) == s["hi_w"] + s["lo_w"]


def test_series_every_game_has_a_decisive_winner():
    """A playoff series game can never come back undecided (real 5-on-5 sudden death continues
    until someone scores) -- verified directly against the actual GameResults, not just the
    series bookkeeping."""
    world = _completed_regular_season(seed=5)
    PO.start_playoffs(world)
    s = world.bracket["series"][0]
    results = PO.play_series_to_completion(world, s)
    assert results
    for result in results:
        assert result.winner is not None
        assert result.went_so is False   # playoffs never shoot out


def test_home_ice_follows_2_2_1_1_1_format():
    """Higher seed hosts games 1, 2, 5, 7; lower seed hosts 3, 4, 6 -- verified via the recorded
    Game objects' home/away fields against the series' own game-id list."""
    world = _completed_regular_season(seed=6)
    PO.start_playoffs(world)
    s = world.bracket["series"][0]
    hi, lo = s["hi"], s["lo"]
    PO.play_series_to_completion(world, s)

    games_by_gid = {g.gid: g for g in world.schedule}
    for i, gid in enumerate(s["games"], start=1):
        game = games_by_gid[gid]
        expected_home = hi if i in PO.HIGH_SEED_HOME_GAMES else lo
        assert game.home == expected_home


def test_run_full_playoffs_reaches_a_single_champion():
    world = _completed_regular_season(seed=7, games=14)
    champ = PO.run_full_playoffs(world)

    assert champ is not None
    assert PO.playoffs_complete(world)
    assert world.bracket["champion"] == champ
    assert world.phase == Phase.DRAFT

    # Round structure: 8 R1 series -> 4 R2 -> 2 CF -> 1 Finals per conference bracket shape,
    # i.e. 8 + 4 + 2 + 1 = 15 total series across both conferences.
    assert len(world.bracket["all_series"]) == 15
    for s in world.bracket["all_series"]:
        assert s["winner"] is not None


def test_run_full_playoffs_finals_pairs_the_two_conference_champions():
    world = _completed_regular_season(seed=8, games=14)
    PO.run_full_playoffs(world)

    finals = [s for s in world.bracket["all_series"] if s["round"] == "Finals"]
    assert len(finals) == 1
    finals_series = finals[0]
    cf_series = [s for s in world.bracket["all_series"] if s["round"] == "CF"]
    cf_winners = {s["winner"] for s in cf_series}
    assert {finals_series["hi"], finals_series["lo"]} == cf_winners


def test_playoff_games_accumulate_into_player_playoffs_stat_line_not_season():
    world = _completed_regular_season(seed=9, games=10)
    # Snapshot season totals before the playoffs run.
    season_goals_before = {pid: p.season.g for pid, p in world.players.items() if not p.is_goalie}

    world2 = world  # same object -- playoffs run on top of the already-completed regular season
    PO.run_full_playoffs(world2)

    season_goals_after = {pid: p.season.g for pid, p in world2.players.items() if not p.is_goalie}
    assert season_goals_before == season_goals_after, (
        "playoff games must not leak into Player.season stat lines"
    )
    total_playoff_goals = sum(p.playoffs.g for p in world2.players.values() if not p.is_goalie)
    assert total_playoff_goals > 0


def test_playoff_games_do_not_affect_regular_season_team_records():
    world = _completed_regular_season(seed=10, games=10)
    records_before = {tid: (t.wins, t.losses, t.ot_losses) for tid, t in world.teams.items()}

    PO.run_full_playoffs(world)

    records_after = {tid: (t.wins, t.losses, t.ot_losses) for tid, t in world.teams.items()}
    assert records_before == records_after


# ---------------------------------------------------------------------------
# Undersized-league fallback (defensive, not a primary path)
# ---------------------------------------------------------------------------
def test_start_playoffs_does_not_crash_on_short_conference():
    """A conference with fewer than PLAYOFF_TEAMS_PER_CONF teams (a tiny test league) should
    still build a legal bracket rather than crashing/index-erroring."""
    world = build_world(seed=11)
    # Trim down to a small league: keep only 6 teams total (3 per conference), well under the
    # normal 16-per-conference/8-playoff-teams shape.
    keep_tids = sorted(world.teams.keys())[:3] + sorted(world.teams.keys())[16:19]
    world.teams = {tid: t for tid, t in world.teams.items() if tid in keep_tids}
    world.schedule = generate_schedule(world, target_games=4)
    world.day = 0
    for team in world.teams.values():
        team.reset_record()
    while not regular_season_complete(world):
        advance_one_day(world)

    PO.start_playoffs(world)   # must not raise
    assert world.bracket is not None
    assert len(world.bracket["series"]) >= 1


# ---------------------------------------------------------------------------
# Playoff officiating/discipline mode
# ---------------------------------------------------------------------------
def _count_penalties(world_seed: int, *, is_playoff: bool, discipline_mode: str, n_games: int) -> int:
    total = 0
    for i in range(n_games):
        world = build_world(seed=world_seed + i)
        world.playoff_discipline_mode = discipline_mode
        tids = sorted(world.teams.keys())
        result = GameSim(world, tids[0], tids[1], is_playoff=is_playoff, collect_pbp=True).play()
        total += sum(1 for e in result.pbp if e.event_type == EVENT_PENALTY)
    return total


def test_realistic_mode_draws_measurably_fewer_playoff_penalties():
    n_games = 30
    regular_season_penalties = _count_penalties(
        200, is_playoff=False, discipline_mode="realistic", n_games=n_games)
    playoff_realistic_penalties = _count_penalties(
        200, is_playoff=True, discipline_mode="realistic", n_games=n_games)

    assert playoff_realistic_penalties < regular_season_penalties
    # Should land in the ballpark of config.PLAYOFF_REALISTIC_PENALTY_MULTIPLIER, not just
    # "any decrease" -- a generous band around the expected ~0.65x to avoid RNG-sweep flakiness.
    ratio = playoff_realistic_penalties / regular_season_penalties
    assert ratio < 0.85


def test_regular_season_discipline_mode_shows_no_measurable_difference():
    n_games = 30
    regular_season_penalties = _count_penalties(
        300, is_playoff=False, discipline_mode="regular_season", n_games=n_games)
    playoff_regseason_mode_penalties = _count_penalties(
        300, is_playoff=True, discipline_mode="regular_season", n_games=n_games)

    # Same underlying penalty model, same multiplier (1.0, a no-op) -- close, not necessarily
    # bit-identical (different is_playoff flag still means a genuinely independent RNG draw
    # sequence per game, e.g. OT shape differs), so compare via a generous ratio band rather than
    # exact equality.
    ratio = playoff_regseason_mode_penalties / regular_season_penalties
    assert 0.7 < ratio < 1.3


def test_playoff_multiplier_default_is_noop_for_regular_season_games():
    from pucksim.sim import special_teams as ST
    from pucksim.models.coach import CoachProfile
    from pucksim.models.player import Player
    from pucksim.models import attributes as attr

    ratings = {name: 70 for name in attr.ALL_RATINGS}
    player = Player(pid=1, name="Test Skater", age=25, position="LW", ratings=ratings)
    coach = CoachProfile(name="Test", weight=1.0)

    p_default = ST.penalty_probability_for_shift([player], coach)
    p_explicit_noop = ST.penalty_probability_for_shift([player], coach, playoff_multiplier=1.0)
    assert p_default == p_explicit_noop

    p_scaled = ST.penalty_probability_for_shift([player], coach, playoff_multiplier=0.5)
    assert p_scaled == p_default * 0.5


def test_gamesim_realistic_mode_uses_configured_multiplier():
    world = build_world(seed=12)
    world.playoff_discipline_mode = "realistic"
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1], is_playoff=True)
    assert sim.playoff_penalty_multiplier == config.PLAYOFF_REALISTIC_PENALTY_MULTIPLIER


def test_gamesim_regular_season_mode_uses_noop_multiplier():
    world = build_world(seed=13)
    world.playoff_discipline_mode = "regular_season"
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1], is_playoff=True)
    assert sim.playoff_penalty_multiplier == 1.0


def test_gamesim_non_playoff_game_always_uses_noop_multiplier():
    world = build_world(seed=14)
    world.playoff_discipline_mode = "realistic"   # should have no effect on a non-playoff game
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1], is_playoff=False)
    assert sim.playoff_penalty_multiplier == 1.0


# ---------------------------------------------------------------------------
# World.playoff_discipline_mode round-trips through to_dict/from_dict
# ---------------------------------------------------------------------------
def test_world_playoff_discipline_mode_defaults_correctly():
    world = build_world(seed=15)
    assert world.playoff_discipline_mode == config.DEFAULT_PLAYOFF_DISCIPLINE_MODE


def test_world_playoff_discipline_mode_round_trips_through_serialization():
    world = build_world(seed=16)
    world.playoff_discipline_mode = "regular_season"
    d = world.to_dict()
    assert d["playoff_discipline_mode"] == "regular_season"

    restored = World.from_dict(d)
    assert restored.playoff_discipline_mode == "regular_season"


def test_world_bracket_round_trips_through_serialization():
    world = _completed_regular_season(seed=17, games=10)
    PO.start_playoffs(world)
    PO.advance_playoff_slate(world)

    d = world.to_dict()
    assert d["bracket"] is not None
    restored = World.from_dict(d)
    assert restored.bracket is not None
    assert restored.bracket["round"] == world.bracket["round"]
    assert len(restored.bracket["all_series"]) == len(world.bracket["all_series"])


def test_world_bracket_defaults_to_none():
    world = build_world(seed=18)
    assert world.bracket is None
    d = world.to_dict()
    assert d["bracket"] is None
    restored = World.from_dict(d)
    assert restored.bracket is None
