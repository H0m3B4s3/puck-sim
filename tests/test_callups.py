"""In-season call-ups: teams must always be able to dress a legal lineup.

The bug this system exists to fix was silent. Promotion out of the development tiers only ran
in the offseason, so a team that lost a third skater to injury in November simply played
short for as long as it took him to heal. Over one 82-day season, 13.8% of team-days dressed
fewer than 18 skaters -- some as few as 15 -- and nothing anywhere reported it.

The distribution consequence is the reason it was found: a shortfall concentrates a fixed
amount of ice time onto fewer players. The league used 588 skaters against the NHL's ~830,
which inflated individual scoring totals across the board (docs/DISTRIBUTION_TARGETS.md).
"""
from collections import Counter

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.models.player import Injury
from pucksim.models.team import dressed_lineup
from pucksim.sim import season as S
from pucksim.systems import callups as C
from pucksim.systems import cap, prospects as P


def _skaters(world, tid):
    return [pid for pid in world.team(tid).roster if world.player(pid).position != "G"]


def _injure(world, tid, count, severity="major", games=30):
    """Knock out ``count`` of ``tid``'s skaters. Returns the pids injured."""
    hurt = _skaters(world, tid)[:count]
    for pid in hurt:
        world.player(pid).injury = Injury("knee", games, severity)
    return hurt


# ---------------------------------------------------------------------------
# The trigger
# ---------------------------------------------------------------------------
def _injure_position(world, tid, count, forwards):
    """Knock out ``count`` of ``tid``'s forwards (or defensemen). Returns the pids injured."""
    wanted = (lambda p: p.position != "D") if forwards else (lambda p: p.position == "D")
    hurt = [pid for pid in _skaters(world, tid) if wanted(world.player(pid))][:count]
    for pid in hurt:
        world.player(pid).injury = Injury("knee", 30, "major")
    return hurt


def test_no_callup_while_the_team_can_still_dress_a_legal_lineup():
    """World gen carries 13 forwards and 7 defensemen, so there is exactly one spare at each
    position. One forward down still leaves the twelve a four-line lineup needs, and a team does
    not burn a prospect's development to sit him in the press box."""
    world = build_world(seed=7)
    _injure_position(world, 0, 1, forwards=True)
    before = len(world.team(0).roster)
    assert C.run_callups(world) == []
    assert len(world.team(0).roster) == before


def test_a_second_forward_injury_triggers_a_callup():
    """Eleven forwards cannot ice four lines, so the recall fires even though 19 skaters is well
    clear of the 18-man dress requirement -- the position floor is a trigger in its own right."""
    world = build_world(seed=7)
    _injure_position(world, 0, 2, forwards=True)
    forwards, defense = C._healthy_skaters(world, 0)
    assert len(forwards) + len(defense) >= config.DRESSED_SKATERS_PER_GAME, "total is not short"
    moves = C.run_callups(world)
    assert [tid for tid, _ in moves] == [0]
    assert len(C._healthy_skaters(world, 0)[0]) >= C.FORWARDS_WANTED


def test_a_position_group_below_its_floor_triggers_even_at_full_headcount():
    """The trigger that was missing at first. ``offseason.fill_rosters`` used to produce rosters
    like 17 forwards and 3 defensemen -- twenty skaters, and two and a half defense pairs. A
    total-headcount-only trigger sails straight past that."""
    world = build_world(seed=7)
    _injure_position(world, 0, 2, forwards=False)      # 7 D -> 5, total still 18
    forwards, defense = C._healthy_skaters(world, 0)
    assert len(forwards) + len(defense) >= config.DRESSED_SKATERS_PER_GAME
    assert len(defense) < C.DEFENSE_WANTED
    moves = C.run_callups(world)
    assert moves, "a two-pair defense corps should have drawn a recall"


def test_callups_and_send_downs_do_not_oscillate():
    """A recall for a position shortfall pushes the roster over SKATERS_MAX, so the send-down half
    fires on the same roster. If it were unrestricted it would return the man just recalled and do
    it again forever; restricted to groups with slack, it gives back a forward instead."""
    world = build_world(seed=7)
    _injure_position(world, 0, 2, forwards=False)
    for _day in range(6):
        C.run_daily_roster_moves(world)
    forwards, defense = C._healthy_skaters(world, 0)
    assert len(defense) >= C.DEFENSE_WANTED, f"settled at {len(defense)} defensemen"
    assert len(forwards) + len(defense) <= config.SKATERS_MAX


def test_callup_fills_the_position_group_that_is_actually_short():
    """Calling up a defenseman does not help a team that is down to nine forwards."""
    world = build_world(seed=7)
    forwards = [pid for pid in _skaters(world, 0) if world.player(pid).position != "D"]
    for pid in forwards[:3]:
        world.player(pid).injury = Injury("knee", 30, "major")
    moves = C.run_callups(world)
    assert moves, "a three-forward shortfall should have drawn a recall"
    assert all(world.player(pid).position != "D" for _tid, pid in moves)


def test_a_defense_shortfall_draws_a_defenseman():
    world = build_world(seed=7)
    # Pick a team that actually has a blueliner to recall -- plenty of farms have none, which
    # is what test_a_forward_covers_a_defense_shortfall_... covers instead.
    tid = next(t.tid for t in world.team_list()
               if any(p.position == "D" and p.contract.years_remaining > 0
                      for p in P.team_prospects(world, t.tid)))
    defense = [pid for pid in _skaters(world, tid) if world.player(pid).position == "D"]
    for pid in defense[:3]:
        world.player(pid).injury = Injury("knee", 30, "major")
    moves = C.run_callups(world)
    assert moves
    assert any(world.player(pid).position == "D" for _tid, pid in moves)


def test_an_empty_farm_leaves_the_team_short_rather_than_inventing_a_player():
    """A genuinely depleted organization should show as depleted, not be papered over."""
    world = build_world(seed=7)
    for player in P.team_prospects(world, 0):
        player.development = None            # empty the whole system
    _injure(world, 0, 4)
    assert C.run_callups(world) == []


def test_a_forward_covers_a_defense_shortfall_when_the_farm_has_no_defensemen():
    """Measured: five teams finished a season with zero signed defense prospects. Dressing a
    full complement out of position beats dressing 17."""
    world = build_world(seed=7)
    for player in P.team_prospects(world, 0):
        if player.position == "D":
            player.development = None
    defense = [pid for pid in _skaters(world, 0) if world.player(pid).position == "D"]
    for pid in defense[:3]:
        world.player(pid).injury = Injury("knee", 30, "major")
    moves = C.run_callups(world)
    assert moves, "should have taken a forward rather than dressing short"
    forwards, blue = C._healthy_skaters(world, 0)
    assert len(forwards) + len(blue) >= config.DRESSED_SKATERS_PER_GAME


def test_unsigned_prospects_are_not_eligible():
    """An unsigned draft pick playing junior is not a body an NHL team can summon."""
    world = build_world(seed=7)
    for player in P.team_prospects(world, 0):
        player.contract.salaries = []        # years_remaining is derived from this
    _injure(world, 0, 4)
    assert C.run_callups(world) == []


def test_the_best_available_prospect_gets_the_call():
    world = build_world(seed=7)
    eligible = [p for p in P.team_prospects(world, 0)
                if p.position not in ("G", "D") and p.contract.years_remaining > 0]
    best = max(eligible, key=lambda p: p.overall)
    forwards = [pid for pid in _skaters(world, 0) if world.player(pid).position != "D"]
    for pid in forwards[:3]:
        world.player(pid).injury = Injury("knee", 30, "major")
    moves = C.run_callups(world)
    assert best.pid in [pid for _tid, pid in moves]


def test_callups_are_bounded_per_team_per_day():
    world = build_world(seed=7)
    for pid in _skaters(world, 0):
        world.player(pid).injury = Injury("knee", 30, "major")   # everyone
    moves = C.run_callups(world)
    assert len(moves) <= C.MAX_CALLUPS_PER_TEAM_PER_DAY


def test_exclude_tid_leaves_a_team_to_its_manager():
    world = build_world(seed=7)
    _injure(world, 0, 4)
    assert C.run_callups(world, exclude_tid=0) == []


# ---------------------------------------------------------------------------
# The return trip
# ---------------------------------------------------------------------------
def test_a_healed_roster_sends_the_extra_body_back_down():
    world = build_world(seed=7)
    hurt = _injure(world, 0, 3)
    C.run_callups(world)
    recalled = len(world.team(0).roster)
    for pid in hurt:                              # everyone heals
        world.player(pid).injury = None
    sent = C.run_send_downs(world)
    assert sent, "roster should have given the extra body back"
    assert len(world.team(0).roster) < recalled
    forwards, defense = C._healthy_skaters(world, 0)
    assert len(forwards) + len(defense) <= config.SKATERS_MAX


def test_nothing_is_sent_down_while_the_roster_is_still_legal():
    """A team at or under the skater maximum is whole. Do not churn it."""
    world = build_world(seed=7)
    assert C.run_send_downs(world) == []


def test_a_returned_player_is_a_prospect_again_and_keeps_his_contract():
    """He goes back to developing with his team still holding him -- not waived, and not paid
    off the NHL cap while he's down there."""
    world = build_world(seed=7)
    hurt = _injure(world, 0, 3)
    recalled = C.run_callups(world)
    assert not world.player(recalled[0][1]).is_prospect     # on the NHL roster now
    for injured in hurt:
        world.player(injured).injury = None
    sent = C.run_send_downs(world)
    assert sent
    for _tid, pid in sent:
        player = world.player(pid)
        assert player.is_prospect
        assert player.contract.years_remaining > 0
        assert P.rights_holder(player) == 0
        assert pid not in world.team(0).roster


def test_the_worst_player_is_the_one_sent_down():
    world = build_world(seed=7)
    hurt = _injure(world, 0, 3)
    C.run_callups(world)
    for pid in hurt:
        world.player(pid).injury = None
    healthy = C._healthy_skaters(world, 0)
    worst = min(healthy[0] + healthy[1],
                key=lambda p: world.player(p).overall)
    sent = C.run_send_downs(world)
    assert worst in [pid for _tid, pid in sent]


# ---------------------------------------------------------------------------
# Cap and roster legality
# ---------------------------------------------------------------------------
def test_injury_relief_covers_a_long_term_absence_but_not_a_knock():
    world = build_world(seed=7)
    team = world.team(0)
    assert cap.injury_relief(world, team) == 0
    pid = _skaters(world, 0)[0]
    world.player(pid).injury = Injury("bruise", 2, "minor")
    assert cap.injury_relief(world, team) == 0, "a two-game knock is what scratches are for"
    world.player(pid).injury = Injury("knee", 30, "major")
    assert cap.injury_relief(world, team) == world.player(pid).contract.current_salary


def test_relief_is_keyed_to_severity_not_to_games_remaining():
    """Relief keyed to a counting-down clock would silently expire in the last week of a long
    absence and flip a legal roster illegal with nothing having happened."""
    world = build_world(seed=7)
    team = world.team(0)
    pid = _skaters(world, 0)[0]
    world.player(pid).injury = Injury("knee", 30, "major")
    full = cap.injury_relief(world, team)
    world.player(pid).injury.games_remaining = 1
    assert cap.injury_relief(world, team) == full


def test_an_emergency_recall_waives_the_roster_ceiling_but_not_the_cap():
    world = build_world(seed=7)
    team = world.team(0)
    while len(team.roster) < config.ROSTER_MAX:   # sit exactly at the 23-man ceiling
        spare = next(p for p in P.team_prospects(world, 0) if p.contract.years_remaining > 0)
        world.sign_player(spare.pid, 0)
    candidate = next(p for p in P.team_prospects(world, 0) if p.contract.years_remaining > 0)
    ok, _ = P.promote_prospect(world, 0, candidate.pid)
    assert not ok, "the 23-man ceiling should block an ordinary call-up"
    # No cap room, no recall -- even in an emergency.
    world.salary_cap = cap.payroll(world, team)
    ok, reason = P.promote_prospect(world, 0, candidate.pid, emergency=True)
    assert not ok and "cap" in reason.lower(), reason


def test_a_full_season_never_dresses_short_and_never_breaks_the_cap():
    """The end-to-end claim. Before this system: 363 of 2624 team-days (13.8%) short."""
    world = build_world(seed=7)
    S.start_season(world)
    counts = Counter()
    while not S.regular_season_complete(world):
        C.run_daily_roster_moves(world)      # idempotent; advance_one_day runs it too
        for team in world.team_list():
            dressed = dressed_lineup(team, world.players)
            counts[sum(1 for pid in dressed.dressed_set
                       if world.player(pid).position != "G")] += 1
        S.advance_one_day(world)
    short = sum(v for k, v in counts.items() if k < config.DRESSED_SKATERS_PER_GAME)
    assert short == 0, f"team-days dressing short: {dict(sorted(counts.items()))}"
    assert not any(cap.over_cap(world, t) for t in world.team_list())


def test_the_playoffs_neither_dress_short_nor_freeze_every_injury():
    """The postseason was the worse half of this bug. ``advance_playoff_slate`` ran no roster
    maintenance AND never healed anybody, so a man hurt in game 1 of round 1 was out for the
    whole playoffs however minor the knock. Measured before the fix: 42% of playoff team-games
    dressed fewer than 18 skaters, one as few as 11."""
    from pucksim.sim import playoffs as PO

    world = build_world(seed=7)
    S.start_season(world)
    while not S.regular_season_complete(world):
        S.advance_one_day(world)
    PO.start_playoffs(world)
    counts = Counter()
    healed = False
    while PO.active_series(world) and world.bracket.get("champion") is None:
        C.run_daily_roster_moves(world)     # idempotent; the slate runs it too
        hurt_before = {pid for pid, p in world.players.items() if p.injury is not None}
        for series in PO.active_series(world):
            for tid in (series["hi"], series["lo"]):
                dressed = dressed_lineup(world.team(tid), world.players)
                counts[sum(1 for pid in dressed.dressed_set
                           if world.player(pid).position != "G")] += 1
        PO.advance_playoff_slate(world)
        hurt_after = {pid for pid, p in world.players.items() if p.injury is not None}
        healed = healed or bool(hurt_before - hurt_after)
    short = sum(v for k, v in counts.items() if k < config.DRESSED_SKATERS_PER_GAME)
    assert short == 0, f"playoff team-games dressing short: {dict(sorted(counts.items()))}"
    assert healed, "no injury healed across an entire postseason"


def test_the_season_uses_far_more_skaters_than_the_base_rosters_hold():
    """32 teams x 20 rostered skaters = 640. Anything above that is a call-up who played."""
    world = build_world(seed=7)
    S.start_season(world)
    while not S.regular_season_complete(world):
        S.advance_one_day(world)
    played = {pid for result in world.game_results.values() for pid in result["skater_box"]}
    assert len(played) > 660, f"only {len(played)} skaters appeared all season"
