"""The entry draft: order-by-standings, prospect pool, and the pick flow.

Ports the *shape* of HoopR's ``hoopsim/systems/draft_system.py`` (268 lines --
draft-order-by-standing, prospect pool, pick flow) to hockey, concretely
adapted around what already exists in PuckSim vs. what HoopR had to build from
scratch:

- ``pucksim.models.draft.DraftPick``/``DraftClass`` (Step 1.10) already
  implement the pick-order/``team_on_clock()``/``record_pick()`` state
  machine HoopR's own ``draft_system.py`` builds inline -- this module is an
  *engine* driving that existing state machine, not a reimplementation of it.
  In particular ``DraftClass.record_pick()`` already validates the picking
  team against the clock and the prospect against availability (raising
  ``ValueError`` on a mismatch) -- this module leans on that guard rather than
  re-checking the same invariants itself.
- ``pucksim.gen.prospectgen`` (this same step) already generates the prospect
  pool -- this module calls it once per draft year, it doesn't generate
  players itself.
- ``pucksim.systems.freeagency.sign_rookie`` (Step 2.4) already implements
  "sign a player to a flat entry-level contract via ``cap.rookie_salary()``,
  routed through ``World.sign_player``" -- drafted players sign through THAT
  existing path (see ``make_pick`` below), not a new contract-creation
  mechanism. This mirrors HoopR's own ``draft_system.py``, which likewise
  calls a shared rookie-contract helper rather than hand-rolling one.
- ``pucksim.models.player.Player.scouted_potential()``/``scout_error`` (Step
  1.6) already implement the fog-of-war HoopR's ``scouting.py`` layers on top
  of a hidden ``potential`` -- see this module's docstring section below on
  what HoopR's ``scouting.py`` adds that PuckSim intentionally does NOT port.

What HoopR's ``scouting.py`` adds that this step does NOT port, and why:
HoopR's ``scouting.py`` is a *display*-layer module (``PotentialView``,
confidence bands, letter grades, a fog-of-war on/off toggle) that sits between
the engine's raw ``scouted_potential()`` and whatever UI renders a draft
board. DEVPLAN.md's Step 2.5 scope is the draft *engine* (order/pool/pick
flow), not a UI layer -- there is no web/CLI draft-board screen yet for a
confidence-band renderer to serve (Step 2.9/2.10 are still ahead). This
module's own ``prospect_rank()`` (below) uses ``Player.scouted_potential()``
directly, exactly the same underlying fogged signal HoopR's board-sort uses
internally -- so the fog-of-war mechanic itself is fully reused, just without
HoopR's extra display-formatting wrapper, which would be dead code with no UI
consumer yet. A future web-layer step can port ``scouting.py``'s
``PotentialView``/grade-banding pattern verbatim once there's a screen to
render it on.

Draft order (JUDGMENT CALL, DEVPLAN.md explicitly flags this as "not
specified, low-risk default"): inverse standings, straight order, no lottery.
Concretely: reuse ``pucksim.models.league.standings()`` (Step 1.8's existing
rule-parameterized standings function -- the very definition of "how are
teams ordered by performance" already lives there, so this module doesn't
invent a second, competing ordering) over the just-finished regular season's
games, then reverse it (worst record picks first). No weighted-lottery
machinery is added -- HoopR's own draft_system.py *does* have a lottery
(``_weighted_lottery``), but DEVPLAN.md's note for this step is explicit that
a lottery is out of scope unless there's a specific reason to add one; this
module's ``compute_draft_order()`` is deliberately simpler than HoopR's
lottery-weighted equivalent.

Round count / class size (JUDGMENT CALL, not specified by DEVPLAN.md): see
``DRAFT_ROUNDS`` below and ``prospectgen.PROSPECT_POOL_SIZE``.
"""
from __future__ import annotations

from typing import List

from pucksim.config import DEV_TIER_AHL, NHL_READY_OVERALL, UDFA_FREE_AGENT_AGE
from pucksim.gen.prospectgen import generate_prospect_pool
from pucksim.models.draft import DraftClass
from pucksim.models.league import Game, standings
from pucksim.models.player import Player
from pucksim.models.team import auto_build_lines
from pucksim.models.world import World
from pucksim.systems import prospects
from pucksim.systems.freeagency import sign_rookie

# Real NHL drafts run 7 rounds. Nothing in DEVPLAN.md pins an exact round
# count for v1; 7 is the obvious low-risk default (matches the real league
# this sim is modeled on, and comfortably fits inside
# prospectgen.PROSPECT_POOL_SIZE = 150 for a 32-team league: 7 * 32 = 224
# picks would actually exceed the pool, so see _effective_rounds() below for
# how a too-small pool degrades gracefully rather than crashing).
# PROVISIONAL/TUNABLE, flagged as a judgment call in this step's report.
DRAFT_ROUNDS = 7

# Which picks go straight to the NHL is now decided by the player, not by his draft slot.
# A pick who is already NHL-caliber (``DRAFT_NHL_READY_OVERALL``) signs an entry-level deal
# and takes a roster spot; everyone else is recorded in full (draft rights, provenance bio,
# ``picks_made``) and placed into a development tier by ``systems/prospects.py``, where he
# stays until his rating says he belongs in the league.
#
# This replaced a fixed schedule keyed on pick number (first overall arrived immediately,
# the top ten a year later, and so on). That schedule was a stand-in for a development
# system that didn't exist yet, and its cost was that a third-overall bust and a
# third-overall superstar reached the NHL on exactly the same timetable, with nothing
# either of them did able to change it.

# Even the first-overall pick has to actually be NHL-caliber to take a roster spot; a weak
# draft class's top pick doesn't automatically belong in the league.
#
# Now an alias for config.NHL_READY_OVERALL rather than its own number: promotion out of a
# development tier asks exactly the same question this does ("does his rating say he belongs
# in the league?"), and the two must never be able to drift apart -- a graduation bar looser
# than the draft's would let the tiers leak sub-replacement players into the NHL, which is
# the economic failure this gate exists to prevent. Kept under the old name for this
# module's existing callers and tests.
DRAFT_NHL_READY_OVERALL = NHL_READY_OVERALL


def _effective_rounds(num_teams: int, pool_size: int, requested_rounds: int) -> int:
    """Clamp the round count so the draft never asks for more picks than the pool has.

    Not a normal-path concern at the default sizes (32 teams * 7 rounds = 224
    > prospectgen's default 150-player pool -- see DRAFT_ROUNDS's comment
    above for why 150 was still chosen as the default pool size: it's plenty
    deep for however many rounds a given league actually runs, and this
    clamp is what keeps a smaller/custom pool from ever crashing
    ``DraftClass.record_pick()`` by running the order past the last
    available prospect). Always returns at least 1 (a degenerate 0-round
    draft would make ``team_on_clock()`` immediately ``None``, which is
    legal but pointless).
    """
    if num_teams <= 0:
        return 0
    max_rounds = max(1, pool_size // num_teams)
    return max(1, min(requested_rounds, max_rounds))


def compute_draft_order(world: World, games: List[Game] = None) -> List[int]:
    """Original-team slot order for round 1: worst-record-first, straight (no lottery).

    ``games`` defaults to ``world.schedule`` (the just-finished regular
    season). Ties broken exactly as ``league.standings()`` breaks them
    (points -> wins -> goal differential -> team id) -- reusing that
    function's tiebreak chain rather than inventing a second one here.
    """
    games = world.schedule if games is None else games
    teams = world.team_list()
    ranked_best_first = standings(teams, games, world.standings_rule)
    worst_first = list(reversed(ranked_best_first))
    return [t.tid for t in worst_first]


def setup_draft(world: World, rounds: int = DRAFT_ROUNDS,
                 pool_size: int = None) -> DraftClass:
    """Build a new ``DraftClass`` for ``world.season_year``: generate the prospect
    pool, compute the flat pick order (round 1 order repeated for every round --
    "straight order, no lottery" per this module's docstring; the *same*
    worst-first sequence applies to every round, matching the real NHL's
    non-lottery rounds 2-7), and register it on ``world.draft_class``.

    Prospects are generated and registered into ``world.players``
    (``World.add_player`` -- never constructed loose) but are NOT yet on any
    roster; they surface in ``world.free_agents`` too (``add_player``'s
    documented behavior for a ``team_id=None`` player), which is harmless --
    a still-undrafted prospect genuinely *is* a free agent in the data model
    until ``make_pick``/``sign_undrafted_to_free_agency`` resolves them one
    way or the other.
    """
    num_teams = len(world.teams)
    size = pool_size if pool_size is not None else _default_pool_size()

    pool = generate_prospect_pool(world.rng, world.new_pid, size=size)
    for p in pool:
        world.add_player(p)
    pool_ids = [p.pid for p in pool] + reentry_candidates(world)

    effective_rounds = _effective_rounds(num_teams, len(pool_ids), rounds)
    round1_order = compute_draft_order(world)
    order = round1_order * effective_rounds

    dc = DraftClass(
        year=world.season_year,
        prospect_ids=pool_ids,
        order=order,
    )
    world.draft_class = dc
    return dc


def reentry_candidates(world: World) -> List[int]:
    """Undrafted holdovers who go back on the board this year, best first.

    Real NHL re-entry: an 18-year-old who goes unpicked is eligible again at 19, and again
    at 20 if he's still around. A player who spent that year developing rather than
    disappearing can genuinely have played his way onto the board -- which is the point of
    ``undrafted_to_free_agency`` placing him in a tier instead of leaving him to be culled.

    The cutoff is ``config.UDFA_FREE_AGENT_AGE``, the same constant that decides when an
    unclaimed player becomes signable by anyone. That's deliberate: the two rules are one
    rule seen from opposite sides. Below it he's re-drafted, at it he's a free agent, and
    there is no gap where he is neither.
    """
    holdovers = [p for p in world.players.values()
                 if p.is_prospect
                 and prospects.rights_holder(p) is None
                 and p.age < UDFA_FREE_AGENT_AGE]
    return [p.pid for p in sorted(holdovers, key=prospect_rank, reverse=True)]


def _default_pool_size() -> int:
    # Deferred import avoids a hard module-load-order dependency: prospectgen's
    # PROSPECT_POOL_SIZE is the single source of truth, this is just plumbing
    # setup_draft()'s default through to it without duplicating the number.
    from pucksim.gen.prospectgen import PROSPECT_POOL_SIZE
    return PROSPECT_POOL_SIZE


# ---------------------------------------------------------------------------
# Board ranking
# ---------------------------------------------------------------------------
def prospect_rank(player: Player) -> float:
    """A scout's-eye ranking signal: blends current ability with fogged upside.

    Same fog-of-war signal HoopR's board-sort uses (``scouted_potential()``,
    which is never more optimistic than a scout could plausibly know -- see
    ``Player.scouted_potential()``'s own docstring), blended with current
    ``overall`` so a more polished, closer-to-NHL-ready prospect can
    reasonably out-rank a rawer higher-ceiling one, matching real draft-board
    behavior (teams don't purely draft on ceiling). Weighting (45% current /
    55% potential) mirrors HoopR's own ``prospect_rank()`` weighting exactly
    -- ported, not reinvented, since nothing hockey-specific should change
    this particular tradeoff.
    """
    return 0.45 * player.overall + 0.55 * player.scouted_potential()


def draft_board(world: World) -> List[Player]:
    """Remaining undrafted prospects, ranked best-to-worst by ``prospect_rank()``."""
    dc = world.draft_class
    if dc is None:
        return []
    remaining = [world.players[pid] for pid in dc.remaining_prospects()]
    return sorted(remaining, key=prospect_rank, reverse=True)


def best_available(world: World) -> int:
    """The pid of the top-ranked remaining prospect on the board."""
    board = draft_board(world)
    if not board:
        raise ValueError("no prospects remain in the draft class")
    return board[0].pid


# ---------------------------------------------------------------------------
# Pick flow
# ---------------------------------------------------------------------------
def make_pick(world: World, prospect_id: int) -> bool:
    """Record one pick for whichever team is currently on the clock, and sign the
    drafted player to an entry-level contract if roster space allows.

    Deliberately does NOT take a ``team_id`` parameter -- the drafting team is
    always read from ``DraftClass.team_on_clock()`` itself (single source of
    truth), so a caller can never accidentally record a pick "for" the wrong
    team; ``DraftClass.record_pick()`` would reject a mismatched team_id
    anyway, but reading the clock here instead of trusting a caller-supplied
    id avoids ever constructing that mismatch in the first place.

    Pick order: ``dc.record_pick()`` first -- this both advances the clock and
    is the strict legality guard (raises ``ValueError`` if the prospect isn't
    actually available), before any roster mutation happens. THEN the
    entry-level signing attempt via ``freeagency.sign_rookie`` (Step 2.4's
    existing path -- ``cap.rookie_salary()``, ``is_rookie_scale=True``, routed
    through ``World.sign_player``, never a direct ``Team.roster``/
    ``Player.team_id`` mutation).

    Two facts are recorded here, and they are separate: the PICK (draft rights,
    ``DraftClass.picks_made``, the player's ``draft`` provenance bio) always
    succeeds, because "did team X draft prospect Y" doesn't depend on roster
    mechanics at all. Where the player then GOES is the second, independent
    question, and there are three answers:

    - Already NHL-caliber (``DRAFT_NHL_READY_OVERALL``) and the team has room:
      he signs an entry-level deal and takes a roster spot. Returns ``True``.
    - Anyone else: ``_assign_to_development`` places him in a feeder tier (see
      ``systems/prospects.py``). He keeps his draft rights, costs no cap space,
      takes no roster spot, and develops until his rating says he belongs.
    - Nowhere will take him -- too old for the development system, or an
      overage junior pick his team couldn't sign: he stays an ordinary free
      agent with his draft bio recorded.

    Roster-full is therefore not an error and never was, but it is no longer
    the awkward case it used to be either. ``leaguegen.build_world`` fills every
    team to 22/23, so a team drafting seven players a year -- completely
    normal -- would blow past ``config.ROSTER_MAX`` if every pick tried to sign
    immediately. Real hockey resolves that by keeping draftees in junior,
    college, or the AHL for years, and as of the prospect development round
    (docs/PROSPECT_DEV_PLAN.md) so does this. An NHL-ready pick who finds the
    roster full simply develops for a year instead of being lost.

    Returns ``True`` only when the player landed on the active roster.
    """
    dc = world.draft_class
    if dc is None:
        raise ValueError("no active draft class on this World")

    tid = dc.team_on_clock()
    dc.record_pick(prospect_id, tid)   # raises ValueError on an illegal pick

    player = world.players[prospect_id]
    team = world.teams[tid]

    # Draft provenance bio (round/pick/team) -- pick number is 1-based
    # (dc.current_pick was already advanced by record_pick() above, so the
    # pick just made is dc.current_pick, not current_pick + 1). Recorded
    # regardless of whether the entry-level signing below succeeds -- draft
    # rights and roster occupancy are separate facts, see docstring above.
    pick_number = dc.current_pick
    round_no = _round_for_pick(dc, pick_number)
    player.draft = {
        "year": dc.year,
        "round": round_no,
        "pick": pick_number,
        "team": team.abbrev,
    }

    if player.overall >= DRAFT_NHL_READY_OVERALL:
        ok, _reason = sign_rookie(world, team, prospect_id)
        if ok:
            return True
        # Roster full or no cap room: he's good enough for the league but there's nowhere
        # to put him today. Fall through and develop him instead of losing him.

    _assign_to_development(world, player, tid)
    return False


def _assign_to_development(world: World, player: Player, tid: int) -> None:
    """Place a just-drafted player into whichever development tier will take him.

    Most picks go straight where they came from -- an 18-year-old junior player back to
    junior, a college recruit to the NCAA. The interesting case is the overage pick: a
    20-or-21-year-old major-junior player has aged out of junior and, under the CHL-NHL
    transfer agreement, can only turn pro if he is actually under contract. So if no tier
    will take him unsigned, the drafting team signs him to an entry-level deal on the spot
    and stashes him in the AHL -- which is exactly what real teams do with their overage
    picks, and why the AHL is where older prospects belong.

    A player no tier will take even after that (too old for the system entirely) simply
    stays an ordinary free agent with his draft rights recorded. The pick still counts;
    he's just not a prospect.
    """
    tier = prospects.best_tier(player)
    if tier is not None:
        prospects.enter_development(player, tier, world.season_year, rights_tid=tid)
        return

    if not prospects.is_elc_eligible(player):
        return
    # The overage case. Record the rights first (``sign_elc`` checks them), sign, and keep
    # him only if the contract actually did unlock the professional tier.
    prospects.enter_development(player, DEV_TIER_AHL, world.season_year, rights_tid=tid)
    ok, _reason = prospects.sign_elc(world, tid, player.pid)
    if not (ok and prospects.eligible_for_tier(player, DEV_TIER_AHL)):
        prospects.leave_development(player)


def _round_for_pick(dc: DraftClass, pick_number_1_based: int) -> int:
    """Which round a 1-based pick number falls in, given this class's flat ``order``.

    ``order`` is built as ``round1_order * effective_rounds`` (see
    ``setup_draft``) -- every round is the same length (one pick per team,
    straight order, no lottery/no pick-trading-driven length changes yet), so
    the round is just integer division by that per-round length.
    """
    teams_per_round = len(set(dc.order)) if dc.order else 1
    return (pick_number_1_based - 1) // max(1, teams_per_round) + 1


def ai_pick(world: World) -> int:
    """AI team on the clock takes the best available prospect. Returns the drafted pid.

    Draft rights are always recorded even if the entry-level signing that
    ``make_pick`` attempts can't go through right away (e.g. a full 23-man
    active roster -- see ``make_pick``'s docstring) -- this function doesn't
    surface that distinction to the caller (``run_draft``'s summary dict
    does, via a separate signed/unsigned count), it just always advances the
    clock by one pick.
    """
    pid = best_available(world)
    make_pick(world, pid)
    return pid


def auto_complete_draft(world: World) -> dict:
    """Run every remaining pick via ``ai_pick`` until the draft class is complete.

    Returns ``{"picks_made": int, "signed": int}`` -- ``picks_made`` is every
    recorded selection, ``signed`` is the subset that also landed an
    entry-level contract on the active roster (see ``make_pick``'s docstring
    for why those two counts can legitimately differ in v1's no-reserve-list
    data model). No human-controlled-team carve-out here (unlike
    ``freeagency.run_fa_wave``'s ``exclude_tid``) -- DEVPLAN.md's Step 2.5
    scope is the draft engine itself; a UI layer letting a human team override
    a single pick before resuming ``auto_complete_draft`` on the rest is a
    natural later addition (Step 2.9+) that doesn't require changing this
    function's shape, just calling ``make_pick`` directly for the human pick
    and this loop for the rest.
    """
    dc = world.draft_class
    if dc is None:
        raise ValueError("no active draft class on this World")
    picks_made = 0
    signed = 0
    while not dc.complete:
        pid = best_available(world)
        if make_pick(world, pid):
            signed += 1
        picks_made += 1
    return {"picks_made": picks_made, "signed": signed}


def undrafted_to_free_agency(world: World) -> int:
    """Resolve everyone the draft class didn't use. Returns how many there were.

    Going unpicked is no longer a dead end. An undrafted player who is still young enough
    keeps developing -- in junior, in college, wherever his background puts him -- with
    ``rights_tid=None``, meaning nobody owns him. Two things can happen from there, and
    both are real:

    - He is still draft-eligible next June, and ``setup_draft`` puts him back on the board
      (real NHL re-entry: a passed-over 18-year-old gets another chance at 19).
    - He reaches ``config.UDFA_FREE_AGENT_AGE`` still unclaimed, at which point
      ``prospects.is_open_to_all`` opens him to the entire league and any team can sign him
      off the free-agent market.

    That second path is the undrafted-free-agent story, and it is the main reason prospects
    needed real age curves rather than a fixed schedule: a player nobody wanted at 18 can
    develop his way into being worth something at 20, and there's now a mechanism for a
    team to actually get him. Before this, every undrafted player simply sat in the
    free-agent pool until ``offseason.cull_free_agents`` deleted him for being raw.

    A player too old for any tier stays an ordinary free agent, exactly as before.

    ``World.add_player`` already put every prospect into ``world.free_agents`` at generation
    time (see ``setup_draft``), and developing prospects deliberately stay there -- so
    nothing needs moving between pools here. This also rebuilds lines for any team whose
    roster changed during the draft (a no-op if none did).
    """
    dc = world.draft_class
    if dc is None:
        return 0
    undrafted = dc.remaining_prospects()
    for pid in undrafted:
        player = world.players.get(pid)
        if player is None or player.is_prospect or player.team_id is not None:
            continue
        tier = prospects.best_tier(player)
        if tier is not None:
            prospects.enter_development(player, tier, world.season_year, rights_tid=None)
    for team in world.team_list():
        auto_build_lines(team, world.players)
    return len(undrafted)


def run_draft(world: World, rounds: int = DRAFT_ROUNDS, pool_size: int = None) -> dict:
    """Headless: build the class, auto-run every pick, resolve the undrafted leftovers.

    Mirrors ``freeagency.run_free_agency``'s "headless orchestration" shape
    (build market/class -> clear it -> report a summary dict) for consistency
    across this codebase's systems modules.
    """
    dc = setup_draft(world, rounds=rounds, pool_size=pool_size)
    total_picks = dc.total_picks
    result = auto_complete_draft(world)
    undrafted = undrafted_to_free_agency(world)
    return {
        "picks_made": result["picks_made"],
        "signed": result["signed"],
        "total_picks": total_picks,
        "undrafted": undrafted,
    }
