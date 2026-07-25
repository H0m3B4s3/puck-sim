"""In-season roster maintenance: emergency call-ups from the farm, and returns.

WHAT WAS BROKEN
===============
Promotion out of the development tiers only ever ran in the OFFSEASON
(``prospects.promote_ready_prospects``). Nothing existed to move a body in November. Teams
carry 20 skaters and dress 18, so a team could absorb exactly two injuries; past that it
simply played short. Measured over one 82-day regular season (seed 7, 32 teams):

    dressed-skater counts, team-days:  18 -> 2261    17 -> 270    16 -> 74    15 -> 19
    13.8% of team-days were played with fewer than 18 skaters, some as low as 15.

That is a silent bug with two distinct costs. The obvious one is that games were being
played 5-on-5 by teams that did not have five lines' worth of bodies. The subtler one drove
this round: ``DressedLineup`` shortfalls concentrate a fixed amount of ice time onto fewer
players, which inflates individual totals league-wide. The league finished a season having
used 588 skaters against the NHL's ~830, and the top of the goal-scoring distribution ran
hot largely because of it -- see docs/DISTRIBUTION_TARGETS.md.

THE TRIGGERS ARE STATELESS, AND THAT IS DELIBERATE
==================================================
There is no "this player is on a call-up" flag anywhere. Both directions are decided purely
from the roster as it stands right now:

    call up   when healthy skaters <  config.DRESSED_SKATERS_PER_GAME  (18)
    send down when healthy skaters >  config.SKATERS_MAX               (20)

A team is only ever ABOVE ``SKATERS_MAX`` because a call-up put it there and the injured man
has since healed, so the second rule returns exactly the players the first rule added,
without persisting anything. That matters more than it looks: a flag would have to survive
save/load, trades, waivers and the offseason, and any path that dropped it would strand a
player on an NHL roster forever. A rule that reads the current roster cannot desynchronize
from it. It also means a save written before this system existed self-corrects the first
time a day is advanced.

The send-down picks the lowest-overall development-eligible skater rather than "whoever was
called up". Those are virtually always the same player -- he is in the AHL precisely because
he is the worst man in the organization -- and where they differ, keeping the better player
is what a real team does anyway.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from pucksim import config
from pucksim.models.world import World
from pucksim.systems import prospects as P

# How many skaters a full lineup wants at each position group: four forward lines and three
# defense pairs. Derived from the same lineup shape ``models/team.py`` builds, so a team is
# judged short at the group that is actually short rather than on headcount alone -- calling
# up a defenseman does not help a team that is down to nine forwards.
FORWARDS_WANTED = 12
DEFENSE_WANTED = 6

# A ceiling on churn per team per day. A team hit by a bus needs several bodies, but an
# unbounded loop would empty a farm system into an NHL roster in one evening if some future
# eligibility bug ever made every candidate look valid.
MAX_CALLUPS_PER_TEAM_PER_DAY = 4


def _healthy_skaters(world: World, tid: int) -> Tuple[List[int], List[int]]:
    """``(forward_pids, defense_pids)`` for the skaters on ``tid`` who can actually play."""
    forwards: List[int] = []
    defense: List[int] = []
    for pid in world.teams[tid].roster:
        player = world.players.get(pid)
        if player is None or player.position == "G" or player.injury is not None:
            continue
        (defense if player.position == "D" else forwards).append(pid)
    return forwards, defense


def _position_needed(forwards: List[int], defense: List[int]) -> Optional[str]:
    """Which position group to call up for, or ``None`` if the team can dress a legal lineup.

    Total headcount is the gate (a team with 13 forwards and 5 defensemen can still dress 18
    and play, if awkwardly), but WHICH group is short decides who gets the call.
    """
    if len(forwards) + len(defense) >= config.DRESSED_SKATERS_PER_GAME:
        return None
    if len(defense) < DEFENSE_WANTED:
        return "D"
    if len(forwards) < FORWARDS_WANTED:
        return "F"
    # Both groups are nominally full yet the total is still short -- only reachable if the
    # lineup constants are ever retuned so 12+6 no longer sums to the dressed count. Take a
    # forward, the position a lineup carries more of.
    return "F"


def _best_candidate(world: World, tid: int, position_group: str) -> Optional[int]:
    """The best signed prospect ``tid`` could recall for ``position_group``, if any.

    Only signed prospects are eligible, exactly as in ``promote_prospect``: an unsigned
    draft pick playing junior is not a body an NHL team can summon on a Tuesday. Best-first
    by overall, because a team dealing with injuries plays its best available man.
    """
    best_pid: Optional[int] = None
    best_overall = -1
    for player in P.team_prospects(world, tid):
        if player.position == "G" or player.injury is not None:
            continue
        if player.contract.years_remaining <= 0:
            continue
        is_defense = player.position == "D"
        if is_defense != (position_group == "D"):
            continue
        if player.overall > best_overall:
            best_pid, best_overall = player.pid, player.overall
    return best_pid


def run_callups(world: World, exclude_tid: Optional[int] = None) -> List[Tuple[int, int]]:
    """Recall bodies for every team that cannot dress a legal lineup. Returns ``(tid, pid)``.

    ``exclude_tid`` keeps a team out of the automation, matching
    ``prospects.promote_ready_prospects`` -- the user's team is left alone so a manager makes
    his own call-ups, and is warned by the roster screen instead.

    A team whose farm has nobody at the position it needs is left short. That is the correct
    outcome, not a failure to handle: the sim already plays such a game short-handed
    (``DressedLineup.short_skaters``), and inventing a player to fill the hole would hide a
    genuinely depleted organization.
    """
    moves: List[Tuple[int, int]] = []
    for team in world.team_list():
        if team.tid == exclude_tid:
            continue
        for _ in range(MAX_CALLUPS_PER_TEAM_PER_DAY):
            forwards, defense = _healthy_skaters(world, team.tid)
            need = _position_needed(forwards, defense)
            if need is None:
                break
            pid = _best_candidate(world, team.tid, need)
            if pid is None:
                # Nobody at the position the team wants. Take a body from the other group
                # rather than dressing 17 -- measured, this is not a rare corner: five teams
                # finished a season with zero signed defense prospects, and a forward playing
                # an emergency shift on the blue line is a real thing that happens. Dressing
                # a full complement out of position beats dressing short.
                pid = _best_candidate(world, team.tid, "F" if need == "D" else "D")
            if pid is None:
                break
            ok, _reason = P.promote_prospect(world, team.tid, pid, emergency=True)
            if not ok:
                break
            moves.append((team.tid, pid))
    return moves


def run_send_downs(world: World, exclude_tid: Optional[int] = None) -> List[Tuple[int, int]]:
    """Return recalled players to the minors once the roster is whole again.

    Fires only while a team carries more than ``config.SKATERS_MAX`` HEALTHY skaters, which
    is a state only a call-up can produce (see this module's docstring). Stops as soon as the
    roster is legal, so a team that is over the limit for any other reason -- a trade, an
    offseason signing -- gives back exactly the excess and no more.

    A player who is no longer development-eligible (too old for the AHL) has nowhere to go
    and is skipped rather than released; ``demote_player`` refuses him and this loop moves on
    to the next-worst candidate.
    """
    moves: List[Tuple[int, int]] = []
    for team in world.team_list():
        if team.tid == exclude_tid:
            continue
        for _ in range(MAX_CALLUPS_PER_TEAM_PER_DAY):
            forwards, defense = _healthy_skaters(world, team.tid)
            if len(forwards) + len(defense) <= config.SKATERS_MAX:
                break
            # Worst first: send down the man a real team would send down.
            candidates = sorted(forwards + defense, key=lambda p: world.players[p].overall)
            for pid in candidates:
                if P.best_tier(world.players[pid]) is None:
                    continue
                ok, _reason = P.demote_player(world, team.tid, pid)
                if ok:
                    moves.append((team.tid, pid))
                    break
            else:
                break   # nobody on this roster can legally be sent down
    return moves


def run_daily_roster_moves(world: World,
                           exclude_tid: Optional[int] = None) -> Tuple[List[Tuple[int, int]],
                                                                      List[Tuple[int, int]]]:
    """One day's roster maintenance: returns first, then call-ups. ``(sent_down, called_up)``.

    Order matters. Returning healed-over players first frees the roster spots and cap room
    that a call-up elsewhere on the same roster may need, so a team that has one man come
    back and another go down on the same day does one swap rather than sitting over the
    limit until the next day.
    """
    sent_down = run_send_downs(world, exclude_tid=exclude_tid)
    called_up = run_callups(world, exclude_tid=exclude_tid)
    return sent_down, called_up
