"""Trade construction, cap-legality validation, AI evaluation, and execution.

Ports HoopR's ``hoopsim/systems/trades.py`` ``TradeOffer`` + AI accept/reject pattern to
hockey. Scoped down from HoopR's full feature set for this step, on purpose:

- **Players only, no draft-pick trading.** HoopR's ``TradeOffer`` carries both player ids
  and future-pick keys (NBA trade culture revolves heavily around pick-swapping). PuckSim's
  draft-pick system (``DraftPick``/``DraftClass``) is a separate, not-yet-built step
  (DEVPLAN.md Step 2.5, dispatched after this one) -- ``pick_value()``/pick-carrying trade
  legs are deliberately NOT built here to avoid designing around a pick-ownership API
  (``world.find_pick`` etc.) that doesn't exist yet. Extending ``TradeOffer`` with pick legs
  once Step 2.5 lands is a natural, additive follow-up, not a rewrite (the dataclass and
  ``execute_trade`` are both structured so a ``picks`` field could be bolted on later).
- **No AI-initiated offer inbox / trade-block persistence.** HoopR's trades.py also
  maintains a whole "the league proactively brings the user offers" subsystem
  (``world.trade_offers``, ``world.offer_cooldowns``, ``Team.block_list``, cooldown/expiry
  bookkeeping). None of those World/Team fields exist on PuckSim yet, and DEVPLAN.md's Step
  2.4 Done-criteria only asks for "trade salary-matching legality... AI accept/reject
  behaves per your documented threshold" -- this file builds exactly that (offer
  construction + legality + AI evaluation + execution), not the surrounding UI-facing
  inbox/cooldown machinery, which is a reasonable later addition once there's a web/CLI
  surface (Step 2.9+) that actually needs to display it.

Every roster change below goes through ``World.transfer_player`` (never direct
``Team.roster``/``Player.team_id`` mutation) -- this is DEVPLAN.md's single most important
constraint for this step.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from pucksim.config import ROSTER_MAX, ROSTER_MIN, TRADE_DEADLINE_FRACTION, SEASON_GAMES
from pucksim.models.league import Phase
from pucksim.models.team import Team, auto_build_lines, roster_players
from pucksim.models.world import World
from pucksim.systems import cap

# AI accept/reject threshold (DESIGN JUDGMENT CALL, not specified by DEVPLAN.md): a trade is
# accepted if the value coming back to the AI is within a symmetric band around the value it
# sends out. This directly mirrors HoopR's own trades.py threshold shape (>=1.03x accepts,
# <0.97x band is a near-miss "want more" rejection, further off is a flat "too lopsided"
# rejection) -- ported verbatim as a reasonable first pass rather than inventing a new
# threshold model, since HoopR's own value is itself provisional/tuned-by-feel there too.
AI_ACCEPT_RATIO = 1.03            # AI accepts if value_in >= value_out * this
AI_NEAR_MISS_RATIO = 0.97         # below AI_ACCEPT_RATIO but >= this: "close, but not quite"


def trade_deadline_day(world: World) -> int:
    """The last day on which trades are allowed, ~2/3 through the regular season
    (``config.TRADE_DEADLINE_FRACTION``), mirroring the real early-March NHL deadline.

    Derives "games per team this season" from the live schedule when one exists (a season
    can be run with a non-default ``--games-per-season``, see testkit/run_season.py), falling
    back to ``config.SEASON_GAMES`` before a schedule has been generated.
    """
    games_per_team = SEASON_GAMES
    if world.schedule and world.teams:
        games_per_team = round(2 * len(world.schedule) / len(world.teams))
    return round(TRADE_DEADLINE_FRACTION * games_per_team)


def trade_deadline_passed(world: World) -> bool:
    """True once the regular-season trade deadline is behind us."""
    return world.phase == Phase.REGULAR_SEASON and world.day > trade_deadline_day(world)


@dataclass
class TradeOffer:
    """A proposed player-for-player trade between two teams.

    ``a``/``b`` are team ids; ``a_sends``/``b_sends`` are the player ids each side gives up
    (so ``b`` *receives* ``a_sends`` and vice versa). No pick legs yet -- see module
    docstring.
    """
    a: int
    b: int
    a_sends: List[int] = field(default_factory=list)
    b_sends: List[int] = field(default_factory=list)


def _salary(world: World, pids: List[int]) -> int:
    return sum(world.players[pid].contract.current_salary for pid in pids)


def validate_trade(world: World, offer: TradeOffer) -> Tuple[bool, str]:
    """Cap, roster-membership, roster-size, and no-trade-clause legality checks.

    Does NOT execute anything -- pure validation, safe to call speculatively (e.g. while an
    AI is assembling candidate packages) without mutating World state.
    """
    if trade_deadline_passed(world):
        return False, "The trade deadline has passed."
    if offer.a not in world.teams or offer.b not in world.teams:
        return False, "Unknown team in trade offer."
    a, b = world.teams[offer.a], world.teams[offer.b]
    if not (offer.a_sends or offer.b_sends):
        return False, "Empty trade."
    if any(pid not in a.roster for pid in offer.a_sends):
        return False, f"A player is not on {a.abbrev}'s roster."
    if any(pid not in b.roster for pid in offer.b_sends):
        return False, f"A player is not on {b.abbrev}'s roster."
    if any(world.players[pid].contract.no_trade for pid in offer.a_sends + offer.b_sends):
        return False, "A player in this trade has a no-trade clause."

    # A sends out_a and receives in_a (== what B sends); B is the mirror.
    out_a, in_a = _salary(world, offer.a_sends), _salary(world, offer.b_sends)
    out_b, in_b = in_a, out_a
    space_a, space_b = cap.cap_space(world, a), cap.cap_space(world, b)
    if not cap.trade_matching_ok(space_a, out_a, in_a):
        return False, f"{a.abbrev} cannot match salary (incoming too large)."
    if not cap.trade_matching_ok(space_b, out_b, in_b):
        return False, f"{b.abbrev} cannot match salary (incoming too large)."

    size_a = len(a.roster) - len(offer.a_sends) + len(offer.b_sends)
    size_b = len(b.roster) - len(offer.b_sends) + len(offer.a_sends)
    for team, size in ((a, size_a), (b, size_b)):
        if size > ROSTER_MAX:
            return False, f"{team.abbrev} would exceed the 23-man roster maximum."
        if size < ROSTER_MIN:
            return False, f"{team.abbrev} would fall below the {ROSTER_MIN}-man roster floor."
    return True, "Trade is legal."


def execute_trade(world: World, offer: TradeOffer) -> None:
    """Perform a validated trade. Callers should call ``validate_trade`` first --
    this function does not re-check legality, only moves players and rebuilds lineups.

    All roster movement goes through ``World.transfer_player`` (never direct
    ``Team.roster``/``Player.team_id`` mutation), per this step's hard constraint.
    """
    a, b = world.teams[offer.a], world.teams[offer.b]
    for pid in list(offer.a_sends):
        world.transfer_player(pid, b.tid)
    for pid in list(offer.b_sends):
        world.transfer_player(pid, a.tid)
    auto_build_lines(a, world.players)
    auto_build_lines(b, world.players)


def propose_trade(world: World, offer: TradeOffer) -> Tuple[bool, str]:
    """Validate and, if legal, immediately execute a trade (the user-initiated path --
    no negotiation, the offer is either accepted as constructed or rejected outright)."""
    ok, reason = validate_trade(world, offer)
    if not ok:
        return False, reason
    execute_trade(world, offer)
    return True, "Trade completed."


# ---------------------------------------------------------------------------
# AI evaluation
# ---------------------------------------------------------------------------
def ai_evaluates(world: World, offer: TradeOffer, ai_tid: int) -> Tuple[bool, str]:
    """Decide whether the AI-controlled team ``ai_tid`` (one side of ``offer``) accepts.

    Threshold logic (see ``AI_ACCEPT_RATIO``/``AI_NEAR_MISS_RATIO`` above): accepts if the
    trade-value coming back is worth at least ``AI_ACCEPT_RATIO`` times what it sends out;
    a near-miss band gives a softer rejection message; further off is a flat decline.
    Cap/roster legality is checked first since a value-favorable trade that's illegal is
    still a rejection.
    """
    legal, reason = validate_trade(world, offer)
    if not legal:
        return False, reason
    if ai_tid == offer.a:
        in_pids, out_pids = offer.b_sends, offer.a_sends
    elif ai_tid == offer.b:
        in_pids, out_pids = offer.a_sends, offer.b_sends
    else:
        return False, "That team is not part of this offer."

    cap_val = world.salary_cap
    v_in = sum(cap.trade_value(world.players[pid], cap_val) for pid in in_pids)
    v_out = sum(cap.trade_value(world.players[pid], cap_val) for pid in out_pids)
    if v_out <= 0:
        return True, "We're happy to take that off your hands."
    if v_in >= v_out * AI_ACCEPT_RATIO:
        return True, "The deal improves our team."
    if v_in >= v_out * AI_NEAR_MISS_RATIO:
        return False, "We'd want a bit more value to do this."
    return False, "That's too lopsided for us."
