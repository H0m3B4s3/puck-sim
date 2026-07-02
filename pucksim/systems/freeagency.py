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

from pucksim.config import MINIMUM_SALARY, ROOKIE_CONTRACT_YEARS
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
    """Free agents whose tier has opened in the current wave (highest overall first)."""
    wave = getattr(world, "fa_wave", None)
    wave = wave if wave is not None else NUM_FA_WAVES - 1
    pool = [p for p in world.free_agent_players() if natural_wave(p) <= wave]
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
    """Contract length a free agent prefers: younger players bet on term, veterans
    increasingly prefer short deals."""
    if player.age < 28:
        return 4
    if player.age < 32:
        return 2
    return 1


def sign_free_agent(world: World, team: Team, pid: int, salary: int, years: int
                     ) -> Tuple[bool, str]:
    """Sign a free agent to ``team`` at explicit terms, after a cap/roster legality check.

    No willingness/negotiation modeling here (unlike HoopR's ``evaluate_offer`` step) --
    DEVPLAN.md's Done criteria for this step is market-clearing behavior, not a full
    user-negotiation UI; a simple "is this deal legal" gate is a reasonable first pass,
    matching this step's documented scope-limiting judgment calls elsewhere.
    """
    player = world.players.get(pid)
    if player is None or not player.is_free_agent:
        return False, "Player is not a free agent."
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
        salary = wave_market_salary(world, player)
        years = contract_years_for(player)
        candidates = [t for t in ai_teams
                      if len(t.roster) < TARGET_ROSTER and cap.can_sign(world, t, salary)[0]]
        if not candidates:
            continue
        team = max(candidates, key=lambda t: cap.cap_space(world, t))
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
