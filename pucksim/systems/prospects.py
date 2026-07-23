"""Development tiers: where a prospect actually is, the rules that put him there, and the
entry-level-contract rules that govern him while he's there.

Replaces the reserved-prospect *status* this module used to be (PR #61) with a *place*.
That earlier version was a deliberate stand-in whose own docstring named the gap it left:
"no distinction between a prospect in junior vs. the AHL vs. the NCAA vs. Europe." A drafted
player was unsignable for N seasons, where N came purely from his draft slot -- a 3rd-overall
bust and a 3rd-overall superstar arrived on exactly the same schedule, and nothing a player
did could move him. See docs/PROSPECT_DEV_PLAN.md for the full round.

WHAT SURVIVES FROM THE OLD MODULE, AND WHY IT MUST
==================================================
The reason a development system exists at all is economic, not cosmetic. Before PR #61 there
was nowhere to put a drafted teenager, so every draft signed ~150 prospects (median overall
52, against a league median of 67) straight onto NHL rosters at entry-level prices. Within
three offseasons 41% of the league was on entry-level deals and payroll had fallen from ~94%
of the cap to ~65% -- the cap pressure the whole economy depends on, gone. Separately, a raw
prospect left in the free-agent pool was deleted by ``offseason.cull_free_agents`` (which
keeps only the top ~80 free agents by CURRENT overall) before he could ever develop, so the
draft fed nothing into the league at all.

``is_reserved_prospect()`` is what fixed both, and it is still the single seam every consumer
goes through -- ``freeagency.fa_wave_pool``/``sign_free_agent``, ``offseason.cull_free_agents``
/``fill_rosters``, and the web free-agency board. Its signature and meaning are deliberately
unchanged ("is this player off-limits to the open market right now?"); only the rule behind it
is new. Do not widen it into "is this player a prospect" -- that question is
``Player.is_prospect``, and conflating the two would put developing players back on the
market.

WHERE A PROSPECT LIVES IN THE DATA MODEL
========================================
``Player.development`` (a plain dict -- see the field's own comment for why) is the whole
record, and this module is its sole owner. A prospect keeps ``team_id = None`` and stays in
``World.free_agents``: he holds no NHL roster spot, and because ``cap.payroll`` sums over
``Team.roster``, a signed prospect's entry-level contract correctly costs his team no cap
space at all -- exactly the real rule that junior and minor-league contracts don't count
against the NHL cap. The team that drafted him is recorded as ``development["rights_tid"]``,
which is the ONLY record of that relationship; there is no ``Team.prospects`` list, because
unlike ``Team.roster`` a reserve list has no ordering or lineup semantics and is never
iterated inside a game, so ``team_prospects()`` deriving it in one pass is cheaper than
maintaining a second sync invariant.

THE FOUR TIERS, AND THE TWO REAL RULES THAT SHAPE THEM
======================================================
``chl`` (Canadian major junior), ``ncaa`` (US college), ``ahl`` (professional development),
``europe``. They are abstract: no schedule, no simulated games, no standings (scope decision
in docs/PROSPECT_DEV_PLAN.md). A tier does exactly two things -- gate who may be assigned
there, and set a development rate (``systems/development.py``).

Two real-world rules do almost all the interesting work, and both hang off
``Player.league_origin``:

1. **The CHL/NCAA fork** (DESIGN.md point 11). Playing major junior permanently forfeits NCAA
   eligibility. This is the one genuinely non-basketball-shaped rule in the whole system --
   HoopR's college/G-League routes overlap freely, hockey's do not.
2. **The CHL-NHL transfer agreement.** A drafted major-junior player under 20 may play in the
   NHL or go back to junior, but not in the AHL. There is no middle option for him, which is
   precisely why a 19-year-old junior star gets nine NHL games and a ticket back to Kitchener
   in real life -- and why ``ELC_SLIDE_GAMES`` exists.

ENTRY-LEVEL CONTRACTS
=====================
Term by signing age (``config.ELC_YEARS_BY_AGE``): three years at 18-21, two at 22-23, one at
24, and at 25 a player is not entry-level at all and signs a normal market deal.

The slide is the user-facing point of the whole thing: a player who is 18 or 19 at the start
of a season and plays fewer than ``config.ELC_SLIDE_GAMES`` NHL games does not burn a contract
year. This is what lets a team sign its top pick immediately without wasting the cheap years
on seasons he spends in junior or college. Because age advances exactly one year per offseason,
the 18-or-19 condition self-limits to two slides -- sign at 18, slide twice, the three-year
deal starts at 20 -- which is exactly the real rule's outcome, with no separate counter needed
to enforce it. ``Contract.slide_years`` records what happened for display and tests; it is not
the mechanism.

Note what the OLD code did here by accident: ``offseason.expire_contracts`` walks
``Team.roster`` only, so an off-roster prospect's contract never advanced at all -- an
unbounded, unintentional slide. ``tick_contract()`` below makes the decision explicit and
bounded, and makes a 20-year-old in the AHL burn a year the way he should.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from pucksim.config import (
    AHL_PREFERRED_AGE,
    DEV_TIER_AGE_BANDS,
    DEV_TIER_AHL,
    DEV_TIER_AHL_MIN_AGE_NON_CHL,
    DEV_TIER_CHL,
    DEV_TIER_EUROPE,
    DEV_TIER_NCAA,
    DEV_TIERS,
    ELC_DEADLINE_GRACE,
    ELC_MAX_AGE,
    ELC_SIGN_READINESS_GAP,
    ELC_SLIDE_GAMES,
    ELC_SLIDE_MAX_AGE,
    ELC_YEARS_BY_AGE,
    MAX_CONTRACTS,
    MAX_PROSPECT_AGE,
    NCAA_MAX_SEASONS,
    NHL_READY_OVERALL,
    PROSPECT_RIGHTS_YEARS,
    PROSPECT_RIGHTS_YEARS_DEFAULT,
    UDFA_FREE_AGENT_AGE,
)
from pucksim.models.contract import flat_contract
from pucksim.models.player import Player
from pucksim.models.world import World


# The tiers a player is IN SCHOOL in, as opposed to playing professionally. The
# distinction matters exactly once, in ``is_open_to_all``: an undrafted player in junior or
# college is not on the market no matter how old he is, because he's still enrolled.
AMATEUR_TIERS = (DEV_TIER_CHL, DEV_TIER_NCAA)


# ---------------------------------------------------------------------------
# Tier eligibility
# ---------------------------------------------------------------------------
def tier_age_band(tier: str) -> Tuple[int, int]:
    """The inclusive (min, max) age band for ``tier`` (``config.DEV_TIER_AGE_BANDS``)."""
    return DEV_TIER_AGE_BANDS[tier]


def forfeited_ncaa_eligibility(player: Player) -> bool:
    """Has this player permanently given up college eligibility by playing major junior?

    DESIGN.md point 11's mutual-exclusivity fork, and the one rule in this module with no
    basketball analogue -- HoopR's college and G-League routes overlap freely. Checked
    against ``league_origin`` (where he came up) rather than his current tier, because the
    forfeiture is permanent: a CHL graduate now in the AHL still can't enrol.
    """
    return player.league_origin == DEV_TIER_CHL


def eligible_for_tier(player: Player, tier: str, age: Optional[int] = None) -> bool:
    """May ``player`` be assigned to ``tier`` right now?

    ``age`` defaults to the player's current age; callers projecting a future assignment
    (e.g. "where does he go next season?") can pass one explicitly rather than mutating
    the player to ask.

    Four gates, in order of how often they bite: the tier's age band, the origin the tier
    requires, the two real-world rules in this module's docstring, and -- for the AHL --
    the requirement that a player be under contract to play professionally at all.
    """
    if tier not in DEV_TIERS:
        return False
    age = player.age if age is None else age
    lo, hi = tier_age_band(tier)

    if tier == DEV_TIER_CHL:
        # Junior is for junior players, and it ends at 19. A 20-year-old drafted junior
        # player turns pro in reality; the CHL's over-age rules mostly serve undrafted
        # players and aren't worth a separate mechanic.
        return player.league_origin == DEV_TIER_CHL and lo <= age <= hi

    if tier == DEV_TIER_NCAA:
        if forfeited_ncaa_eligibility(player):
            return False
        # College is for players on the college track, the same way junior is for junior
        # players. Checking only "didn't play major junior" instead was a real bug: it made
        # every European prospect NCAA-eligible, and since college is preferred over Europe
        # for a teenager, European draftees were being sent to US colleges wholesale.
        if player.league_origin != DEV_TIER_NCAA:
            return False
        if seasons_in_tier(player) >= NCAA_MAX_SEASONS and current_tier(player) == tier:
            return False        # four years of eligibility, exhausted
        return lo <= age <= hi

    if tier == DEV_TIER_AHL:
        # A professional league: you have to be under professional contract to be in it.
        # This is what makes signing an entry-level deal a real decision rather than
        # something a team defers indefinitely.
        if player.contract.years_remaining <= 0:
            return False
        floor = lo if forfeited_ncaa_eligibility(player) else DEV_TIER_AHL_MIN_AGE_NON_CHL
        return floor <= age <= hi

    if tier == DEV_TIER_EUROPE:
        return player.league_origin == DEV_TIER_EUROPE and lo <= age <= hi

    return False


def eligible_tiers(player: Player, age: Optional[int] = None) -> List[str]:
    """Every tier ``player`` could legally be assigned to, in DEV_TIERS order."""
    return [t for t in DEV_TIERS if eligible_for_tier(player, t, age=age)]


def best_tier(player: Player, age: Optional[int] = None) -> Optional[str]:
    """Where this player should develop, or ``None`` if no tier will take him.

    Age decides the preference, and it is the difference between a working system and a
    broken one. THE AHL IS FOR OLDER PROSPECTS. From ``AHL_PREFERRED_AGE`` (20) on, pro
    development against grown men beats another year of dominating juniors, so the AHL wins.
    Before 20, a player belongs in his amateur tier -- an 18-year-old is not helped by being
    the 11th forward on a bus league's fourth line.

    That ordering is load-bearing, not cosmetic. Preferring the AHL at every age (the first
    version of this function) put ~85% of every prospect in the league in the AHL the moment
    his team signed him: college recruits never saw a campus, junior players never played
    junior, and the tier system collapsed into a single undifferentiated bucket. Note the
    AHL stays *eligible* at 18 for non-junior players -- it is simply not *preferred* --
    which is what lets a signed European teenager with no amateur tier left still turn pro.

    ``None`` means he's out of the system -- too old, or unsigned with no amateur tier left
    to return to -- and the caller should retire him to ordinary free agency via
    ``leave_development``.
    """
    age = player.age if age is None else age
    order = ((DEV_TIER_AHL, DEV_TIER_CHL, DEV_TIER_NCAA, DEV_TIER_EUROPE)
             if age >= AHL_PREFERRED_AGE
             else (DEV_TIER_CHL, DEV_TIER_NCAA, DEV_TIER_EUROPE, DEV_TIER_AHL))
    for tier in order:
        if eligible_for_tier(player, tier, age=age):
            return tier
    return None


# ---------------------------------------------------------------------------
# Reading a development record
# ---------------------------------------------------------------------------
def current_tier(player: Player) -> Optional[str]:
    """Which tier this player is developing in, or ``None`` if he isn't."""
    return player.development["tier"] if player.development else None


def seasons_developed(player: Player) -> int:
    """Total seasons spent developing, across every tier."""
    return player.development["seasons"] if player.development else 0


def seasons_in_tier(player: Player) -> int:
    """Seasons spent in the CURRENT tier -- what runs the NCAA eligibility clock."""
    return player.development["tier_seasons"] if player.development else 0


def rights_holder(player: Player) -> Optional[int]:
    """The tid holding this player's rights, or ``None`` for an undrafted prospect."""
    return player.development.get("rights_tid") if player.development else None


def rights_lapsed(player: Player, season_year: int) -> bool:
    """Have the drafting team's rights run out?

    A team doesn't own a pick forever: two years for a junior player, four for a college
    one (``config.PROSPECT_RIGHTS_YEARS``). When they lapse the player goes back into the
    pool, which is what stops a team from parking a prospect it never intends to sign.
    """
    if not player.development:
        return False
    expire = player.development.get("rights_expire")
    if expire is None:
        return False
    return season_year >= expire


def is_open_to_all(player: Player, season_year: int) -> bool:
    """May ANY team sign this developing player off the open market?

    Two ways in, both real. The drafting team let its rights lapse -- or he was never
    drafted, has reached ``config.UDFA_FREE_AGENT_AGE``, and is no longer in an amateur
    tier. That second path is the undrafted pathway's whole point: an unclaimed player who
    develops into somebody becomes a genuine prize rather than quietly disappearing.

    The amateur clause is what makes it work, and leaving it out was a real leak. Being
    open to the market also means being exposed to ``offseason.cull_free_agents``, which
    keeps only the top ~80 free agents by CURRENT overall -- so without it a promising
    21-year-old was deleted from the league in the middle of his junior year of college,
    for the crime of not yet being finished. A college player is not a free agent while
    he's enrolled; he becomes one when his eligibility runs out, at 22 or 23, which is
    exactly when real college free agents hit the market and exactly the age at which they
    are worth something.
    """
    if not player.development:
        return False
    if rights_lapsed(player, season_year):
        return True
    return (player.development.get("rights_tid") is None
            and player.age >= UDFA_FREE_AGENT_AGE
            and current_tier(player) not in AMATEUR_TIERS)


def is_reserved_prospect(player: Player, season_year: int) -> bool:
    """Is this player off-limits to the open free-agent market right now?

    THE seam. Every consumer that asks "can this free agent be signed / should he be
    culled / should he appear on the market" goes through this one function -- see the
    module docstring for the list and for why its meaning must not drift. Three
    conditions: he's in the development system, he isn't already on an NHL roster (a top
    pick who went straight to the league is not reserved, he's just a player), and he is
    not yet open to all comers.

    Note the rights-HOLDING team is not blocked by this: it signs him through
    ``sign_elc`` below, which checks rights directly. This function is about the open
    market, and the market is exactly who should be shut out.
    """
    if player.team_id is not None:
        return False
    if not player.development:
        return False
    return not is_open_to_all(player, season_year)


def reserved_prospects(world: World) -> List[Player]:
    """Every player currently reserved (unsignable on the open market)."""
    return [p for p in world.players.values()
            if is_reserved_prospect(p, world.season_year)]


def developing_players(world: World) -> List[Player]:
    """Every player in the development system, reserved or not."""
    return [p for p in world.players.values() if p.is_prospect]


def team_prospects(world: World, tid: int) -> List[Player]:
    """The reserve list for ``tid``: every prospect whose rights it holds, best first.

    Derived rather than stored -- see the module docstring for why there is no
    ``Team.prospects`` list to keep in sync.
    """
    pool = [p for p in world.players.values()
            if p.is_prospect and p.development.get("rights_tid") == tid]
    return sorted(pool, key=lambda p: (p.potential, p.overall), reverse=True)


def contracts_held(world: World, tid: int) -> int:
    """Professional contracts committed by ``tid``: NHL roster plus signed prospects.

    What ``config.MAX_CONTRACTS`` bounds. Prospect deals have to be counted here even
    though they cost no cap space precisely BECAUSE they cost no cap space -- nothing else
    in the economy would ever push back on a team signing every prospect it drafted.
    """
    team = world.teams.get(tid)
    roster = len(team.roster) if team else 0
    signed_prospects = sum(1 for p in team_prospects(world, tid)
                           if p.contract.years_remaining > 0)
    return roster + signed_prospects


# ---------------------------------------------------------------------------
# Entering, moving through, and leaving the system
# ---------------------------------------------------------------------------
def rights_years_for(tier: str) -> int:
    """How long a team holds the rights of a player it drafted into ``tier``."""
    return PROSPECT_RIGHTS_YEARS.get(tier, PROSPECT_RIGHTS_YEARS_DEFAULT)


def enter_development(player: Player, tier: str, season_year: int,
                       rights_tid: Optional[int] = None) -> dict:
    """Put ``player`` into ``tier`` and return his new development record.

    Does not validate eligibility -- callers pick the tier via ``best_tier`` (which does),
    and a caller with a specific reason to override shouldn't be second-guessed here.
    ``rights_tid=None`` is the undrafted track: he develops on his own, belonging to
    nobody.

    Seasons already served are CARRIED FORWARD, and only a genuine change of tier restarts
    the tier clock. This matters because a player can enter development more than once: an
    undrafted 18-year-old goes to college on his own, gets re-drafted at 19, and passes
    through here a second time. Resetting his counters there would hand him a fresh
    four-year college eligibility clock every time somebody drafted him -- which is not how
    eligibility works, and measurably wasn't working: undrafted players were leaving the
    system at a median age of 24 having never once exhausted a four-season clock, because
    it kept starting over.
    """
    previous = player.development or {}
    same_tier = previous.get("tier") == tier
    player.development = {
        "tier": tier,
        "seasons": previous.get("seasons", 0),
        "tier_seasons": previous.get("tier_seasons", 0) if same_tier else 0,
        "rights_tid": rights_tid,
        "rights_expire": (season_year + rights_years_for(tier)
                          if rights_tid is not None else None),
        # Seed the season line from his scouting report. ``line`` means "his most recent
        # completed season", and for a player entering the system on draft day that IS his
        # pre-draft year -- so the record is never blank while a team looks at a pick it
        # just made. ``advance_prospects`` overwrites it every offseason after that; a
        # re-entrant already has a real one, which is better than his old scouting report.
        "line": previous.get("line") or (dict(player.pre_draft) if player.pre_draft else {}),
    }
    return player.development


def leave_development(player: Player) -> None:
    """Take ``player`` out of the development system.

    He becomes an ordinary free agent: signable by anyone, and -- if he never became an
    NHL player -- washed out of the league by ``offseason.cull_free_agents`` like any
    other unwanted free agent. Both outcomes are correct. Most late-round picks never
    play a game.
    """
    player.development = None




# What ``advance_development`` reports, in descending order of significance. When more
# than one applies the earliest in this tuple wins -- a player who ages out doesn't also
# need his lapsed rights reported, since he belongs to nobody either way.
ADVANCE_OUTCOMES = ("aged_out", "turned_pro", "rights_lapsed", "moved_up", "stayed")


def advance_development(player: Player, season_year: int) -> str:
    """Tick one offseason for a developing player. Returns one of ``ADVANCE_OUTCOMES``.

    - ``aged_out``      -- past ``config.MAX_PROSPECT_AGE``; out of the system.
    - ``turned_pro``    -- still young enough, but no tier will take him: he's exhausted
                           NCAA eligibility, or he's an unsigned junior player who turned
                           20 and can't go to the AHL without a contract. Out of the
                           system, and onto the open market -- this is the college-free-
                           agent pathway, and it is a real outcome, not a failure.
    - ``rights_lapsed`` -- still developing, but no longer anyone's property.
    - ``moved_up``      -- changed tier; in practice junior or college to the AHL, which
                           is where an older prospect belongs.
    - ``stayed``        -- another season where he is.

    Call once per offseason per prospect, AFTER ``development.develop_all`` has aged him:
    his NEW age is what decides where he goes next.
    """
    if not player.development:
        return "stayed"

    record = player.development
    record["seasons"] += 1
    record["tier_seasons"] += 1

    if player.age > MAX_PROSPECT_AGE:
        leave_development(player)
        return "aged_out"

    tier = best_tier(player)
    if tier is None:
        leave_development(player)
        return "turned_pro"

    moved = tier != record["tier"]
    if moved:
        record["tier"] = tier
        record["tier_seasons"] = 0

    if rights_lapsed(player, season_year):
        record["rights_tid"] = None
        record["rights_expire"] = None
        return "rights_lapsed"
    return "moved_up" if moved else "stayed"


# ---------------------------------------------------------------------------
# Entry-level contracts
# ---------------------------------------------------------------------------
def elc_years_for_age(age: int) -> int:
    """Term of an entry-level deal signed at ``age``; 0 if he's too old to sign one.

    ``config.ELC_YEARS_BY_AGE``, which is the real CBA schedule: three years at 18-21, two
    at 22-23, one at 24, and nothing at 25+ -- that player signs a market contract like
    anyone else.
    """
    for max_age, years in ELC_YEARS_BY_AGE:
        if age <= max_age:
            return years
    return 0


def is_elc_eligible(player: Player) -> bool:
    """May this player sign an entry-level contract at all?

    Age is the only real gate (``config.ELC_MAX_AGE``); a player already under contract
    obviously can't sign a new one on top of it.
    """
    return player.age <= ELC_MAX_AGE and player.contract.years_remaining <= 0


def can_slide(player: Player) -> bool:
    """Does this player's entry-level deal slide instead of burning a year this offseason?

    The real rule: 18 or 19 at the start of the season, and fewer than
    ``config.ELC_SLIDE_GAMES`` NHL games played in it. Note the games test is what makes
    a nine-game NHL look-see free for a junior player, and a tenth game expensive -- the
    single most consequential number on the real NHL's calendar for a 19-year-old.

    Requires an actual entry-level contract: a veteran's deal has nothing to slide, and a
    player with no contract has nothing to slide either.
    """
    if not player.contract.is_rookie_scale or player.contract.years_remaining <= 0:
        return False
    if player.age > ELC_SLIDE_MAX_AGE:
        return False
    games = player.season.gp if player.season else 0
    return games < ELC_SLIDE_GAMES


def tick_contract(player: Player) -> str:
    """Advance (or slide) one entry-level year for a player who is NOT on an NHL roster.

    Returns ``"slid"`` or ``"burned"``. This is the function the whole "guys in junior
    don't burn years" ask comes down to.

    Exists because ``offseason.expire_contracts`` only walks ``Team.roster``: before this,
    an off-roster prospect's contract never advanced at all, which was an unbounded and
    entirely accidental slide. Now the decision is explicit -- an 18- or 19-year-old in
    junior or college slides, and a 20-year-old in the AHL burns a year the way he should.

    Rostered NHL players are ``expire_contracts``'s business, not this function's; calling
    it for one would double-advance his deal.
    """
    if can_slide(player):
        player.contract.slide_years += 1
        return "slid"
    player.contract.advance_year()
    return "burned"


def sign_elc(world: World, tid: int, pid: int) -> Tuple[bool, str]:
    """Sign a prospect whose rights ``tid`` holds to an entry-level contract.

    The player does NOT join the NHL roster: he stays exactly where he is developing, now
    under contract. That is the real mechanic this round exists to model -- a team signs
    its 18-year-old first-rounder, sends him back to junior, and the deal slides rather
    than burning (see ``tick_contract``). Promotion to the roster is a separate decision,
    made when his rating says he belongs (``systems/offseason.py``).

    Signing is also what unlocks the AHL: ``eligible_for_tier`` requires a contract to
    play professionally, so an unsigned 20-year-old junior graduate has nowhere left to
    go. That tension -- sign him and use a contract slot, or lose him -- is the point.
    """
    from pucksim.systems import cap

    player = world.players.get(pid)
    if player is None:
        return False, "No such player."
    if not player.is_prospect:
        return False, "Player is not a developing prospect."
    if rights_holder(player) != tid:
        return False, "Your team does not hold this player's rights."
    if player.contract.years_remaining > 0:
        return False, "Player is already under contract."
    years = elc_years_for_age(player.age)
    if years <= 0:
        return False, "Player is too old for an entry-level contract."
    if contracts_held(world, tid) >= MAX_CONTRACTS:
        return False, f"Roster is at the {MAX_CONTRACTS}-contract limit."

    player.contract = flat_contract(
        cap.rookie_salary(world.salary_cap), years,
        is_rookie_scale=True, signed_year=world.season_year,
    )
    return True, f"Signed to a {years}-year entry-level contract."


# ---------------------------------------------------------------------------
# The offseason development cycle
# ---------------------------------------------------------------------------
def tick_prospect_contracts(world: World) -> dict:
    """Slide or burn one entry-level year for every off-roster prospect under contract.

    ORDERING MATTERS, and it's the one genuinely subtle thing in this module. This must run
    BEFORE ``offseason.age_and_retire`` increments everyone's age, because the slide rule
    asks how old the player was at the START of the season that just finished. Ticking
    after aging would read a 19-year-old as 20 and burn a year the real rule protects.

    Returns ``{"slid": int, "burned": int}``.
    """
    slid = burned = 0
    for player in world.players.values():
        if not player.is_prospect or player.contract.years_remaining <= 0:
            continue
        if tick_contract(player) == "slid":
            slid += 1
        else:
            burned += 1
    return {"slid": slid, "burned": burned}


def advance_prospects(world: World) -> dict:
    """Move every prospect one season through the system. Counts by outcome.

    Runs AFTER ``offseason.age_and_retire`` -- the opposite of
    ``tick_prospect_contracts`` above, and for the mirror-image reason: where a player goes
    next is decided by how old he is NOW, not by how old he was last season.

    Also refreshes each surviving prospect's synthetic season line, so a team can look at
    what its 19-year-old actually did in junior this year rather than only that his overall
    moved. Flavor, never read back into any rule.
    """
    from pucksim.gen.prospectgen import development_season_line

    counts = {outcome: 0 for outcome in ADVANCE_OUTCOMES}
    for player in list(world.players.values()):
        if not player.is_prospect:
            continue
        counts[advance_development(player, world.season_year)] += 1
        if player.development is not None:
            player.development["line"] = development_season_line(
                world.rng, player, player.development["tier"])
    return counts


def sign_or_lose_him(player: Player) -> bool:
    """Is this the last offseason before ``player`` leaves the system unsigned?

    Asked by projecting next season: if no tier will take him a year from now as an
    unsigned player, then either his team signs him -- which unlocks the AHL -- or he turns
    pro on his own and it gets nothing. This is the real deadline every junior graduate and
    every senior faces, expressed as a query rather than as a hardcoded date.
    """
    return best_tier(player, age=player.age + 1) is None


def should_sign(world: World, player: Player) -> bool:
    """Would an AI team commit a contract slot to this prospect?

    Two questions, and both have to pass. First: do we think he'll be an NHL player at all?
    Scouted potential is the right signal because it's the FOGGED one
    (``Player.scouted_potential``) -- a team bets on the player it believes it drafted, and
    sometimes that belief is wrong, which is what ``scout_error`` exists for. Second: is
    there a reason to spend the contract slot NOW, rather than leaving him in school? Yes
    if he's within striking distance of the NHL (``config.ELC_SIGN_READINESS_GAP``), or if
    this is the last chance before he walks (``sign_or_lose_him``).

    That second test is what stops teams signing every prospect they draft the day after
    the draft -- the first version of this rule had no such test, and 90% of every draft
    class was under contract within a year, which in turn dumped all of them into the AHL.
    Real teams sign a pick when he's ready to turn pro or when the deadline forces it, and
    let the rest develop unsigned.
    """
    if player.overall >= NHL_READY_OVERALL - ELC_SIGN_READINESS_GAP:
        return player.scouted_potential() >= NHL_READY_OVERALL
    # At the deadline the alternative is losing him for nothing, so the bar to spend a slot
    # drops (``config.ELC_DEADLINE_GRACE``). Real teams take that flyer, and it is what
    # fills an AHL roster: most of the players on one are not going to be NHL regulars.
    # Without the lower bar the AHL was the SMALLEST tier in the league, because every
    # junior graduate his team merely liked walked away at 20.
    if not sign_or_lose_him(player):
        return False
    return player.scouted_potential() >= NHL_READY_OVERALL - ELC_DEADLINE_GRACE


def sign_eligible_prospects(world: World, exclude_tid: Optional[int] = None) -> int:
    """AI teams sign the prospects they believe in to entry-level deals. Returns signings.

    Best prospects first, so a team that runs out of contract slots spends them on the
    players it rates highest. ``exclude_tid`` keeps a human-controlled team out of the
    automation.
    """
    signed = 0
    for team in world.team_list():
        if team.tid == exclude_tid:
            continue
        for player in team_prospects(world, team.tid):
            if player.contract.years_remaining > 0 or not is_elc_eligible(player):
                continue
            if not should_sign(world, player):
                continue
            ok, _reason = sign_elc(world, team.tid, player.pid)
            if ok:
                signed += 1
    return signed


def promote_prospect(world: World, tid: int, pid: int) -> Tuple[bool, str]:
    """Call one signed prospect up onto ``tid``'s NHL roster. Returns ``(ok, reason)``.

    The user-facing half of graduation: what ``promote_ready_prospects`` does automatically
    for the AI, a manager does deliberately for one player through here. Three gates, the
    same three the automatic path checks -- the team holds his rights, he's under contract
    (nobody joins an NHL roster without one, and being under contract is also what makes his
    cap hit real), and the team has the roster spot and cap room. Nothing about being
    NHL-*ready* is enforced: a manager may call up a raw prospect if he wants to, exactly as
    a real team can, and eat the roster spot and the bad hockey that follows.

    ``World.sign_player`` clears the development record (its documented single choke point
    for "reaching an NHL roster ends development"), so a promoted player is a player, not a
    prospect, the instant this returns True.
    """
    from pucksim.models.team import auto_build_lines
    from pucksim.systems import cap

    player = world.players.get(pid)
    if player is None or not player.is_prospect:
        return False, "Player is not a developing prospect."
    if rights_holder(player) != tid:
        return False, "Your team does not hold this player's rights."
    if player.contract.years_remaining <= 0:
        return False, "Sign him to an entry-level contract before calling him up."
    team = world.teams[tid]
    ok, reason = cap.can_sign(world, team, player.contract.current_salary)
    if not ok:
        return False, reason
    world.sign_player(pid, tid)
    auto_build_lines(team, world.players)
    return True, f"{player.name} called up to the NHL roster."


def demote_player(world: World, tid: int, pid: int) -> Tuple[bool, str]:
    """Send one rostered player down to the minors. Returns ``(ok, reason)``.

    The reverse of ``promote_prospect``, and the move two-way contracts will eventually give
    a cap consequence (docs/PROSPECT_DEV_PLAN.md). He comes off the active roster and back
    into a development tier with his team holding the rights, so he keeps his contract and
    costs no cap space while he's down (``cap.payroll`` sums over ``Team.roster``, which he's
    no longer on) -- the same reason a prospect's entry-level deal is free.

    Gated on still being development-eligible: ``best_tier`` has to place him somewhere,
    which for a signed player means the AHL up to its age ceiling. A veteran past that age
    has nowhere to be sent and stays on the roster. NOTE this v1 has no waiver system (a real
    NHL send-down of a non-exempt player must clear waivers first -- deferred with the rest
    of the CBA to DEVPLAN Step 3.1), so any eligible player can be sent down freely here.
    """
    from pucksim.models.team import auto_build_lines

    player = world.players.get(pid)
    if player is None or player.team_id != tid:
        return False, "Player is not on your roster."
    if player.contract.years_remaining <= 0:
        return False, "Player has no contract to carry to the minors."
    tier = best_tier(player)
    if tier is None:
        return False, f"{player.name} is too experienced for the minors."
    team = world.teams[tid]
    world.release_player(pid)          # off the roster, team_id=None, into free_agents
    enter_development(player, tier, world.season_year, rights_tid=tid)
    auto_build_lines(team, world.players)
    return True, f"{player.name} sent down to the {tier.upper()}."


def promote_ready_prospects(world: World, exclude_tid: Optional[int] = None) -> List[int]:
    """Graduate every prospect whose rating says he belongs in the NHL. Returns their pids.

    The automatic, all-teams counterpart to ``promote_prospect`` -- run once per offseason so
    the AI fills its own holes from its own system before shopping the market. A prospect is
    promoted when three things line up: he's cleared ``config.NHL_READY_OVERALL``, he's under
    contract, and his team has the roster spot and cap room. Best first, so the scarce roster
    spots go to the best players.

    Falling short of any of those is not a failure -- he simply develops another season.
    That is the pressure valve that keeps this from re-creating the problem the whole system
    exists to prevent: promotion is gated on being GOOD, not on having waited long enough, so
    a flood of cheap sub-replacement teenagers can never reach NHL rosters however many of
    them a team drafts.

    ``exclude_tid`` keeps a team out of the automation -- passed the user's team by the web
    offseason so a manager makes his own call-ups (via ``promote_prospect``) rather than
    having the engine reach onto his roster for him.
    """
    promoted: List[int] = []
    for team in world.team_list():
        if team.tid == exclude_tid:
            continue
        for player in team_prospects(world, team.tid):
            if player.overall < NHL_READY_OVERALL:
                continue
            ok, _reason = promote_prospect(world, team.tid, player.pid)
            if ok:
                promoted.append(player.pid)
    return promoted
