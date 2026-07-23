"""Free-agent market: tiered wave clearing, market valuation, and signing.

Ports HoopR's ``hoopsim/systems/freeagency.py`` tiered-wave-clearing pattern (top-tier
players' market opens first; each subsequent wave widens the pool and cools the price on
anyone still unsigned) to hockey. The core mechanic is sport-agnostic -- HoopR's own
docstring already frames it generically ("Free agency resolves in waves... the market
cools") -- so this is close to a straight port, adapted to:

- ``pucksim.systems.cap``'s flat market-salary curve (no ``experience``-tiered max, no
  mid-level exception -- see cap.py's module docstring for why).
- Hockey's 23-man active-roster ceiling (``config.ROSTER_MAX``) instead of the NBA's.
- No pick/no-trade-clause interplay to model here (free agents by definition aren't on a
  roster yet, so no-trade clauses are irrelevant to signing).

Signing always goes through ``World.sign_player`` -- this module never mutates
``Team.roster``/``Player.team_id`` directly, matching cap.py/trades.py's same hard
constraint. Because ``World.sign_player`` doesn't itself accept a ``Contract`` (its
signature is ``sign_player(pid, tid) -> None`` -- see models/world.py), every signing
helper here sets ``player.contract`` first and then calls ``sign_player`` to move the
roster/free-agent-list bookkeeping, in that order.
"""
from __future__ import annotations

from typing import List, Tuple

from pucksim.config import MINIMUM_SALARY, ROOKIE_CONTRACT_YEARS, ROSTER_MAX
from pucksim.models.contract import flat_contract
from pucksim.models.player import Player
from pucksim.models.team import Team, auto_build_lines
from pucksim.models.world import World
from pucksim.systems import cap

# ---------------------------------------------------------------------------
# Tiered wave market (DESIGN JUDGMENT CALL: exact tier cutoffs/discount rate are not
# specified by DEVPLAN.md -- ported from HoopR's own provisional values, rescaled to
# attributes.py's 25-99 rating scale instead of HoopR's 0-99 scale).
# ---------------------------------------------------------------------------
# Overall-rating floor that opens each successive wave, high to low. On a 25-99 scale with
# RATING_MIN=25, these bands are meant to read as "true difference-makers" / "everyday
# players" / "depth" / "everyone else", loosely NHL-realistic.
FA_WAVE_THRESHOLDS = [80, 72, 64, 0]
FA_WAVE_NAMES = ["Franchise-caliber targets", "Top-six / top-pair", "Depth & bottom-six", "Fringe & minimums"]
NUM_FA_WAVES = len(FA_WAVE_THRESHOLDS)

WAVE_DISCOUNT = 0.07                 # per-wave price cooling for a still-unsigned tier
MIN_DISCOUNT_FACTOR = 0.6            # a cooling market never drops a player below 60% of value

TARGET_ROSTER = 21                   # AI teams sign toward this size (mid-band of 20-23)

# Headcount is not the only thing an AI team is shopping for -- money is. A team that has
# reached TARGET_ROSTER but is still sitting on real cap space keeps bidding (up to the
# hard ROSTER_MAX) rather than banking the room.
#
# Without this, the league's economy deflates every single offseason: contracts expire,
# teams re-fill to exactly 21 bodies with whatever the wave discount makes cheap, and stop
# -- so payroll ratchets down year over year (measured: ~94% of the cap at world gen
# decaying to ~62% within three offseasons) while the cap itself grows 3% annually under
# `cap.grow_cap()`. The generated league's cap pressure has to be *maintained* by the AI's
# spending behavior, not just set correctly once at world gen.
#
# Expressed as a fraction of the live cap rather than flat dollars so the rule keeps its
# meaning as the cap grows.
AI_SPEND_SPACE_FRACTION = 0.05       # ~$4.1M at an $82.5M cap

# Bidding competition (see `competitive_salary`). Each rival team that could also have
# signed the player lifts the winning bid, up to a ceiling. Without this the market is
# purely one-directional -- every free agent signs at their cooled asking price and league
# payroll can only ever drift down.
BIDDING_PREMIUM_PER_RIVAL = 0.012
MAX_BIDDING_PREMIUM = 1.30


def natural_wave(player: Player) -> int:
    """The wave in which this player's tier first opens, by overall rating."""
    for i, floor in enumerate(FA_WAVE_THRESHOLDS):
        if player.overall >= floor:
            return i
    return NUM_FA_WAVES - 1


def wave_market_salary(world: World, player: Player) -> int:
    """A free agent's asking price, cooled by how many waves their tier has sat unsigned.

    Outside the offseason market (``world.fa_wave is None`` -- there's no
    ``World.fa_wave`` field defined yet in PuckSim's v1 model, see ``start_fa_market``
    below for how this module manages that state without a dedicated World field) this is
    just the player's full market value.
    """
    base = cap.market_salary(player, world.salary_cap)
    wave = getattr(world, "fa_wave", None)
    if wave is None:
        return base
    steps = max(0, wave - natural_wave(player))
    factor = max(MIN_DISCOUNT_FACTOR, 1.0 - WAVE_DISCOUNT * steps)
    return max(MINIMUM_SALARY, int(round(base * factor / 50_000) * 50_000))


def fa_wave_pool(world: World) -> List[Player]:
    """Free agents whose tier has opened in the current wave (highest overall first).

    Reserved prospects are excluded (``systems/prospects.py``): a player still inside their
    post-draft development window belongs to the team that drafted them and isn't on the
    open market yet. They enter it automatically once the window closes.
    """
    from pucksim.systems.prospects import is_reserved_prospect

    wave = getattr(world, "fa_wave", None)
    wave = wave if wave is not None else NUM_FA_WAVES - 1
    pool = [p for p in world.free_agent_players()
            if natural_wave(p) <= wave and not is_reserved_prospect(p, world.season_year)]
    return sorted(pool, key=lambda p: p.overall, reverse=True)


def start_fa_market(world: World) -> None:
    """Open the tiered offseason free-agent market at the top wave.

    ``fa_wave`` is stored as a plain dynamic attribute on ``World`` rather than a declared
    dataclass field: it's transient run-loop state (only meaningful while
    ``run_free_agency``/``run_fa_wave`` is actively iterating waves in a single offseason
    pass), not persistent league state that needs to survive a save/load round trip --
    unlike ``salary_cap`` or ``standings_rule``, nothing should ever observe a *stale*
    ``fa_wave`` value after the market has closed, so it deliberately isn't part of
    ``World.to_dict``/``from_dict``. ``getattr(world, "fa_wave", None)`` everywhere above
    treats "field absent" and "market closed" identically.
    """
    world.fa_wave = 0


def end_fa_market(world: World) -> None:
    """Close the offseason market; later signings (in-season waiver-style pickups) are at
    full, uncooled price again."""
    world.fa_wave = None


def advance_fa_wave(world: World) -> bool:
    """Move to the next wave. Returns ``True`` if a wave remains, ``False`` once the board
    has fully opened and closed."""
    wave = getattr(world, "fa_wave", None)
    if wave is None:
        return False
    wave += 1
    if wave >= NUM_FA_WAVES:
        end_fa_market(world)
        return False
    world.fa_wave = wave
    return True


def contract_years_for(player: Player) -> int:
    """Contract length a free agent signs for: younger players lock in term, veterans
    increasingly take short deals.

    Lengthened from the original 4/2/1 bands, which were both unrealistic (the real NHL
    averages a bit over three years per contract) and quietly deflationary. Because every
    expiring contract dumps its player onto the open market, short terms meant roughly
    two-thirds of the league re-signed *every single offseason* -- rosters fell to 6-16
    players before free agency opened -- so nearly every contract in the league was
    repeatedly repriced through ``wave_market_salary``'s cooling discount (down to 60% of
    market for anyone left in the late waves). That compounded into a league-wide pay cut
    year over year. Longer terms mean only ~a quarter of the league turns over annually,
    which is both realistic and what keeps the discount a market-clearing mechanism
    instead of a deflationary ratchet.
    """
    if player.age <= 24:
        return 6
    if player.age <= 28:
        return 5
    if player.age <= 31:
        return 3
    if player.age <= 34:
        return 2
    return 1


def sign_free_agent(world: World, team: Team, pid: int, salary: int, years: int
                     ) -> Tuple[bool, str]:
    """Sign a free agent to ``team`` at explicit terms, after a cap/roster legality check.

    No willingness/negotiation modeling here (unlike HoopR's ``evaluate_offer`` step) --
    DEVPLAN.md's Done criteria for this step is market-clearing behavior, not a full
    user-negotiation UI; a simple "is this deal legal" gate is a reasonable first pass,
    matching this step's documented scope-limiting judgment calls elsewhere.

    Enforced here rather than only in the AI loop so the rule is the same for everyone:
    ``run_fa_wave`` skips reserved prospects by filtering ``fa_wave_pool``, but a user (or
    any other caller) reaching this function directly must hit the same wall, or the human
    team gets to raid developing prospects the AI can't touch.
    """
    from pucksim.systems.prospects import is_reserved_prospect

    player = world.players.get(pid)
    if player is None or not player.is_free_agent:
        return False, "Player is not a free agent."
    if is_reserved_prospect(player, world.season_year):
        return False, "Player is a developing prospect and cannot be signed yet."
    if years < 1:
        return False, "Contract must be at least 1 year."
    ok, reason = cap.can_sign(world, team, salary)
    if not ok:
        return False, reason
    player.contract = flat_contract(salary, years, signed_year=world.season_year)
    world.sign_player(pid, team.tid)
    auto_build_lines(team, world.players)
    return True, "Signed."


def sign_rookie(world: World, team: Team, pid: int, years: int = None) -> Tuple[bool, str]:
    """Sign an undrafted/drafted rookie to a flat entry-level (rookie-scale) contract.

    Uses ``cap.rookie_salary()`` (a small flat fraction of the cap) rather than
    ``wave_market_salary`` -- entry-level deals are cheap by rule, not by market
    negotiation (see cap.py's module docstring). ``years`` defaults to
    ``config.ROOKIE_CONTRACT_YEARS`` (the real ELC's fixed 3-year term).
    """
    player = world.players.get(pid)
    if player is None or not player.is_free_agent:
        return False, "Player is not a free agent."
    years = years or ROOKIE_CONTRACT_YEARS
    salary = cap.rookie_salary(world.salary_cap)
    ok, reason = cap.can_sign(world, team, salary)
    if not ok:
        return False, reason
    player.contract = flat_contract(salary, years, is_rookie_scale=True,
                                     signed_year=world.season_year)
    world.sign_player(pid, team.tid)
    auto_build_lines(team, world.players)
    return True, "Signed to an entry-level contract."


# ---------------------------------------------------------------------------
# AI-driven market clearing
# ---------------------------------------------------------------------------
def wants_to_sign(world: World, team: Team) -> bool:
    """Is this AI team still shopping?

    Two reasons a team keeps bidding: it needs bodies (under ``TARGET_ROSTER``), or it has
    real money left to spend (see ``AI_SPEND_SPACE_FRACTION``) and a roster spot to put a
    player in. Cap legality is checked separately by ``cap.can_sign`` -- this is the
    *appetite* question, not the *legality* one.
    """
    if len(team.roster) >= ROSTER_MAX:
        return False
    if len(team.roster) < TARGET_ROSTER:
        return True
    return cap.cap_space(world, team) >= world.salary_cap * AI_SPEND_SPACE_FRACTION


def competitive_salary(world: World, team: Team, asking: int, bidders: int) -> int:
    """What the winning team actually pays, given how many rivals were also in on the player.

    ``wave_market_salary`` is the player's *asking* price, and paying exactly that models a
    market with no competition in it -- every free agent signs for their cooled ask and no
    team ever has to outbid anyone. That is a poor model of real free agency (a good player
    with twenty suitors gets bid up, not discounted) and it's economically one-directional:
    it can only ever move league payroll down, which is a large part of why teams finished
    each offseason still sitting on cap space they had no way to spend.

    So a contested signing carries a premium that scales with the number of teams able to
    make the offer, capped by ``MAX_BIDDING_PREMIUM``. The premium is bounded by the league
    max salary and by ``cap.signing_allowance`` -- not raw cap space, which would let a
    bidding war eat the room the team must keep back to fill its roster minimum -- so it
    can never turn a legal signing into an illegal one.
    """
    if bidders <= 1:
        return asking
    premium = min(MAX_BIDDING_PREMIUM, 1.0 + BIDDING_PREMIUM_PER_RIVAL * (bidders - 1))
    salary = int(round(asking * premium / 50_000) * 50_000)
    salary = min(salary, cap.max_salary(world.salary_cap), cap.signing_allowance(world, team))
    return max(asking, salary)


def run_fa_wave(world: World, exclude_tid: int = None) -> dict:
    """AI teams bid on the tier open in the current wave, within their own cap space.

    One pass over the current wave's pool: each player goes to whichever eligible AI team
    (roster under target size, enough cap space) has the *most* cap space, a simple
    "richest bidder wins" allocation rule that avoids any per-team preference modeling
    (not specified by DEVPLAN.md) while still guaranteeing the pool clears deterministically
    given the RNG-free ordering (sorted by overall, so stars sign first, same as HoopR).
    ``exclude_tid`` optionally keeps one team (e.g. a human-controlled team) out of the AI
    auto-sign loop.
    """
    ai_teams = [t for t in world.team_list() if t.tid != exclude_tid]
    signings = 0
    for player in fa_wave_pool(world):
        asking = wave_market_salary(world, player)
        years = contract_years_for(player)
        candidates = [t for t in ai_teams
                      if wants_to_sign(world, t) and cap.can_sign(world, t, asking)[0]]
        if not candidates:
            continue
        team = max(candidates, key=lambda t: cap.cap_space(world, t))
        salary = competitive_salary(world, team, asking, len(candidates))
        player.contract = flat_contract(salary, years, signed_year=world.season_year)
        world.sign_player(player.pid, team.tid)
        signings += 1
    for t in ai_teams:
        auto_build_lines(t, world.players)
    return {"signings": signings}


def run_free_agency(world: World, exclude_tid: int = None, max_waves: int = NUM_FA_WAVES
                     ) -> dict:
    """Headless: AI teams work the whole tiered market, wave by wave, until it clears.

    Bounded by ``max_waves`` (defaults to the full ``NUM_FA_WAVES``) as a hard stop -- since
    ``advance_fa_wave`` always terminates on its own once ``fa_wave >= NUM_FA_WAVES``, this
    bound can never actually bind in normal operation, but it's cheap insurance against the
    market "stalling" (DEVPLAN.md's explicit done-criteria concern: "FA waves clear the
    market... market doesn't stall/infinite-loop") in case a future change to
    ``advance_fa_wave`` ever breaks that guarantee.
    """
    start_fa_market(world)
    signings = 0
    waves_run = 0
    while waves_run < max_waves:
        signings += run_fa_wave(world, exclude_tid=exclude_tid)["signings"]
        waves_run += 1
        if not advance_fa_wave(world):
            break
    end_fa_market(world)
    return {"signings": signings, "waves_run": waves_run}
