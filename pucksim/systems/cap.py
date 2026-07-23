"""Salary-cap math: payroll, cap space, market/rookie salary, and trade asset value.

Ports the *shape* of HoopR's ``hoopsim/systems/cap.py`` (payroll/cap_space/over_cap/
market_salary/trade_value/can_extend/grow_cap/can_sign) to hockey's simpler v1 cap model.
Real deviations from HoopR, all driven by DESIGN.md's explicit "simplified cap" decision
and by structural differences between the two sports:

- No luxury tax / apron / mid-level exception. NHL's real cap is a genuine hard cap (no
  soft-cap over-the-cap re-signing exception the way the NBA has Bird rights) -- v1 keeps
  that hard-cap simplicity: a team may never sign/acquire a contract that pushes it over
  ``world.salary_cap`` except via the trade salary-matching allowance below, which mirrors
  a real trade's ability to send matching money back rather than being an exception at all.
- Roster-size legality uses hockey's real 20/23 NHL active-roster band
  (``config.ROSTER_MIN``/``ROSTER_MAX``, already defined in Step 1.1's config.py, unused
  until this step) instead of the NBA's 12-15 band. No two-way/AHL-affiliate reserve-list
  split exists yet in v1 -- ``Team.roster`` *is* the active roster; a taxi-squad/reserve-list
  distinction is real-NHL-CBA detail explicitly deferred to DEVPLAN.md Step 3.1 alongside
  waivers/arbitration/LTIR (see ``models/contract.py``'s module docstring).
- No ``experience``-tiered max-salary scale (HoopR's ``MAX_SALARY_TIERS`` keys off
  ``Player.experience``, a field that does not exist on PuckSim's ``Player`` -- see
  ``models/player.py``). v1's max salary is instead a flat fraction of the cap
  (``config.MAX_SALARY_CAP_FRACTION``, the real NHL's informal "no contract above ~20% of
  the cap" ceiling), independent of career length.
- Rookie-scale (entry-level) contracts get their own flat, cheap formula
  (``rookie_salary()``) rather than running through ``market_salary()`` -- this is what
  keeps a drafted 99-potential prospect from instantly commanding a market-rate contract
  the way a same-rated veteran free agent would, mirroring the real ELC's fixed, modest cap
  hit regardless of the player's eventual output. ``Contract.is_rookie_scale`` (Step 1.5)
  is the flag that routes a player through this path instead of ``market_salary()`` --
  consumed by Step 2.5's draft system when it signs draftees.

Ratings note: PuckSim's ``overall`` is on attributes.py's 25-99 scale (not HoopR's 0-99),
so ``base_salary_for()``'s breakpoints are hockey-native numbers, not a straight port of
HoopR's dollar curve. Those breakpoints live in ``config.SALARY_CURVE`` and are *fitted*
to leaguegen's generated rating distribution so a full roster consumes ~95% of the cap
(real NHL cap pressure) rather than being eyeballed dollar bands -- see that constant's
comment, and ``gen/leaguegen.py``'s payroll-fit pass which lands each generated team on a
realistic share of the cap.
"""
from __future__ import annotations

from typing import Tuple

from pucksim.config import (BURY_CAP_SHELTER, CAP_GROWTH_RATE, MAX_CONTRACT_YEARS,
                             MAX_SALARY_CAP_FRACTION, MINIMUM_SALARY, ROSTER_MAX, ROSTER_MIN,
                             ROOKIE_SALARY_CAP_FRACTION, SALARY_CURVE, SALARY_CURVE_REFERENCE_CAP,
                             TRADE_MATCH_BUFFER, VETERAN_DISCOUNT, VETERAN_DISCOUNT_AGE,
                             YOUNG_UPSIDE_PREMIUM)
from pucksim.models.player import Player
from pucksim.models.team import Team, team_salary
from pucksim.models.world import World


# ---------------------------------------------------------------------------
# Payroll / cap space
# ---------------------------------------------------------------------------
def buried_cap_hit(world: World, team: Team) -> int:
    """Cap charged by ``team``'s ONE-WAY contracts buried in the minors.

    A player a team sent down (``systems/prospects.demote_player``) is off the active roster,
    so ``team_salary`` no longer counts him. For a two-way contract that's the end of it -- it
    pays a minor-league salary down there and shelters the whole cap hit. A one-way contract
    is different: it pays the same salary in the minors, so the real cap only shelters a fixed
    slice of it (``config.BURY_CAP_SHELTER``) and the rest stays on the team's books. That is
    exactly why a bad long-term one-way deal is a cap anchor a team can't just demote away --
    and, now that the user can demote players, the reason signing depth to two-way deals is a
    real choice.

    Sums ``max(0, salary - BURY_CAP_SHELTER)`` over every off-roster, under-contract,
    one-way player whose rights this team holds. Cheap one-way deals bury fully (they fall
    below the shelter); expensive ones leave most of their salary charged.
    """
    from pucksim.systems.prospects import team_prospects

    total = 0
    for player in team_prospects(world, team.tid):
        contract = player.contract
        if contract.years_remaining <= 0 or contract.two_way:
            continue
        total += max(0, contract.current_salary - BURY_CAP_SHELTER)
    return total


def payroll(world: World, team: Team) -> int:
    """Team's current total salary counting toward the cap.

    The active roster (``team_salary``) plus any buried one-way contracts the team has in the
    minors (``buried_cap_hit``) -- see that function for why a demoted one-way player still
    costs cap space while a two-way one doesn't.
    """
    return team_salary(team, world.players) + buried_cap_hit(world, team)


def cap_space(world: World, team: Team) -> int:
    """Room remaining under the cap, floored at 0 (never negative)."""
    return max(0, world.salary_cap - payroll(world, team))


def over_cap(world: World, team: Team) -> bool:
    """True if the team's payroll already exceeds the cap (only reachable via a signing/
    trade-matching edge case -- normal signings are blocked by ``can_sign`` before this
    can happen, but a team can still legally land here e.g. rounding or a future waiver
    claim that ignores space, so this stays a real, checkable query rather than an
    assumed-impossible invariant)."""
    return payroll(world, team) > world.salary_cap


# ---------------------------------------------------------------------------
# Salary valuation
# ---------------------------------------------------------------------------
def max_salary(cap: int) -> int:
    """The richest single-season salary any contract may carry: a flat fraction of the
    live cap (real NHL's informal ~20%-of-cap ceiling), independent of career length
    since PuckSim's ``Player`` has no ``experience`` field to tier off of."""
    return int(cap * MAX_SALARY_CAP_FRACTION)


def base_salary_for(ovr: int, cap: int = SALARY_CURVE_REFERENCE_CAP) -> int:
    """Deterministic 'fair' annual salary for a given overall (no noise), on attributes.py's
    25-99 rating scale.

    Linear interpolation over ``config.SALARY_CURVE``'s breakpoints, flat outside the ends,
    scaled by ``cap / config.SALARY_CURVE_REFERENCE_CAP`` so the curve holds its shape *in
    cap percentage terms* as the cap grows each offseason (a $9M contract at an $82.5M cap
    is the same roster commitment as a $9.9M one after a decade of ``grow_cap()``; without
    this scaling every existing salary would quietly deflate into irrelevance).

    The curve is calibrated against leaguegen's real generated rating distribution rather
    than eyeballed -- see ``config.SALARY_CURVE``'s comment for the fit and the resulting
    per-team cap-sheet shape.
    """
    points = SALARY_CURVE
    if ovr <= points[0][0]:
        base = float(points[0][1])
    elif ovr >= points[-1][0]:
        base = float(points[-1][1])
    else:
        # Guaranteed to find a bracketing segment: the two branches above already
        # excluded everything outside the curve's endpoints.
        x0, y0 = next((p for p in reversed(points) if p[0] <= ovr))
        x1, y1 = next((p for p in points if p[0] > ovr))
        base = y0 + (y1 - y0) * (ovr - x0) / (x1 - x0)
    base *= cap / SALARY_CURVE_REFERENCE_CAP
    return max(MINIMUM_SALARY, int(base))


def market_salary(player: Player, cap: int) -> int:
    """Estimated annual salary a free agent would command in the open market.

    Rookie-scale players never reach this path in practice (they sign via
    ``rookie_salary()``), but this function doesn't special-case ``is_rookie_scale`` itself
    -- it's a pure "what would this player's ability alone command" estimate, useful for
    trade-value comparisons regardless of what contract they're actually on.
    """
    base = base_salary_for(player.overall, cap)
    if player.age <= 23 and player.scouted_potential() > player.overall + 4:
        base *= YOUNG_UPSIDE_PREMIUM   # teams pay for projection, not just today
    if player.age >= VETERAN_DISCOUNT_AGE:
        base *= VETERAN_DISCOUNT       # aging-curve discount
    base = min(base, max_salary(cap))
    return max(MINIMUM_SALARY, int(round(base / 50_000) * 50_000))


def rookie_salary(cap: int) -> int:
    """Flat entry-level salary: a small fraction of the live cap, same for every rookie-scale
    signing regardless of draft slot or rating (mirrors the real ELC's fixed, modest cap hit --
    see module docstring). Grows automatically as the cap grows via ``grow_cap()``."""
    return max(MINIMUM_SALARY, int(round(cap * ROOKIE_SALARY_CAP_FRACTION / 50_000) * 50_000))


def trade_value(player: Player, cap: int) -> float:
    """Unitless asset value blending current ability, age/upside, and contract surplus.

    Same shape as HoopR's version: a rating-driven base, an age multiplier that rewards
    youth and penalizes decline, an upside bonus for high-potential young players, and a
    surplus-value term (a player earning less than their market rate is a more valuable
    trade chip than one making full freight, and vice versa).
    """
    ovr = player.overall
    base = max(0.0, (ovr - 45)) ** 1.6 / 8.0
    age = player.age
    if age <= 23:
        af = 1.18
    elif age <= 26:
        af = 1.08
    elif age <= 29:
        af = 1.0
    elif age <= 32:
        af = 0.85
    else:
        af = 0.65
    pot_bonus = max(0, player.scouted_potential() - ovr) * (0.30 if age <= 25 else 0.10)
    value = base * af + pot_bonus
    surplus = (market_salary(player, cap) - player.contract.current_salary) / 3_000_000.0
    return max(0.1, value + surplus)


# ---------------------------------------------------------------------------
# Trade & signing legality
# ---------------------------------------------------------------------------
def trade_matching_ok(space_before: int, outgoing: int, incoming: int) -> bool:
    """Can a team legally take back ``incoming`` salary given what it sends out ``outgoing``?

    A team may absorb incoming salary up to its existing cap space plus the salary it just
    freed up, plus a flat matching buffer (``config.TRADE_MATCH_BUFFER``) -- a simplified
    stand-in for the real NHL's retained-salary/matching mechanics (explicitly out of scope
    for v1, see config.py's comment on this constant).
    """
    allowance = space_before + outgoing + TRADE_MATCH_BUFFER
    return incoming <= allowance


def can_extend(team: Team, pid: int, world: World) -> Tuple[bool, str]:
    player = world.players.get(pid)
    if player is None or pid not in team.roster:
        return False, "Player is not on your roster."
    if player.contract.years_remaining >= MAX_CONTRACT_YEARS:
        return False, "Contract is already at the maximum length."
    return True, "Eligible to extend."


def extension_offer(world: World, player: Player) -> Tuple[int, int]:
    """A reasonable (salary, added years) a team would offer to extend/re-sign a player."""
    salary = min(market_salary(player, world.salary_cap), max_salary(world.salary_cap))
    add_years = max(1, min(MAX_CONTRACT_YEARS - player.contract.years_remaining, 4))
    return salary, add_years


def extend_contract(world: World, team: Team, pid: int, salary: int, add_years: int
                     ) -> Tuple[bool, str]:
    """Re-sign / extend an own player. Hockey's hard cap has no Bird-rights-style
    over-the-cap re-signing exception (see module docstring), so an extension must still
    fit under the cap once the new years are added on top of the player's *current*
    salary -- checked against the team's cap space excluding this player's own current
    salary (which is being replaced, not added to)."""
    ok, reason = can_extend(team, pid, world)
    if not ok:
        return False, reason
    player = world.players[pid]
    salary = max(MINIMUM_SALARY, salary)
    max_sal = max_salary(world.salary_cap)
    if salary > max_sal:
        return False, f"Above the maximum salary ({max_sal // 1_000_000}M)."
    space_excluding_self = cap_space(world, team) + player.contract.current_salary
    if salary > space_excluding_self:
        return False, "Not enough cap space to extend at that salary."
    add_years = min(add_years, MAX_CONTRACT_YEARS - player.contract.years_remaining)
    if add_years <= 0:
        return False, "No additional years available."
    player.contract.salaries.extend([salary] * add_years)
    player.contract.guaranteed.extend([True] * add_years)
    return True, f"Extended {add_years} year(s) at {salary // 1_000_000}M."


def grow_cap(world: World, rate: float = CAP_GROWTH_RATE) -> None:
    """Grow the live cap by ``rate`` (called each offseason). No tax-line/apron to grow in
    v1's simplified model -- just the one number."""
    world.salary_cap = int(world.salary_cap * (1 + rate))


def can_sign(world: World, team: Team, salary: int) -> Tuple[bool, str]:
    """Whether a team may sign a player (free agent or rookie) at ``salary``.

    Hard cap: unlike HoopR's soft-cap NBA model (minimum contracts and the mid-level
    exception both allow signing over the cap), v1's hockey cap never allows a signing
    that pushes payroll over ``world.salary_cap`` -- there is no exception mechanism.
    Roster-size legality uses hockey's real 23-man active-roster ceiling
    (``config.ROSTER_MAX``).

    A team must also keep back enough room to fill its *remaining mandatory* roster spots
    at the league minimum (``config.ROSTER_MIN``). Without that reserve a team can legally
    spend itself down to near-zero space while still short of a full roster, and then
    ``offseason.fill_rosters`` -- which must complete, since a team below ``ROSTER_MIN``
    (or below ``GOALIES_MIN``) cannot ice a legal lineup -- has no choice but to sign over
    the cap. That was directly observed breaking the hard cap for 27 of 32 teams in a
    single offseason once the economy got tight enough for it to bite. Reserving the room
    up front is both the realistic GM behavior and the only fix that keeps the hard cap an
    actual invariant rather than a hope.
    """
    if len(team.roster) >= ROSTER_MAX:
        return False, "Roster is full (23-man active-roster maximum)."
    allowance = signing_allowance(world, team)
    if salary > allowance:
        if allowance < cap_space(world, team):
            return False, "Not enough cap space (room is reserved to fill the roster minimum)."
        return False, "Not enough cap space."
    return True, "Cap space available."


def signing_allowance(world: World, team: Team) -> int:
    """The largest salary this team may legally commit to one more player.

    Cap space less whatever must be held back to fill the team's *remaining mandatory*
    roster spots at the league minimum. Callers that price a signing themselves (rather
    than just asking ``can_sign`` yes/no) must clamp to this, or they can spend the reserve
    that ``can_sign`` exists to protect and push the team into the illegal state described
    there.
    """
    spots_still_required = max(0, ROSTER_MIN - (len(team.roster) + 1))
    return max(0, cap_space(world, team) - spots_still_required * MINIMUM_SALARY)
