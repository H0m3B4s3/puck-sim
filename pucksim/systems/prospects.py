"""Reserved prospects -- v1's minimal stand-in for junior/AHL affiliation.

PuckSim v1 has no minor-league system: ``Team.roster`` *is* the NHL active roster, and a
real two-way/AHL-affiliate reserve list is explicitly deferred (see ``systems/cap.py``'s
module docstring). That gap turned out to be an *economic* problem, not just a missing
feature, which is why this module exists.

Without anywhere to develop, a drafted 18-year-old had exactly two fates, both wrong:

- Sign onto the NHL roster immediately at an entry-level cap hit. Prospect pools generate
  around a median overall of ~52 against a league median of ~67, so ~150 sub-replacement
  teenagers a year displaced real, market-priced NHL players. Within three offseasons 41%
  of all rostered players were on entry-level deals and league payroll had fallen from
  ~94% of the cap to ~65% -- the cap pressure the whole economy depends on, gone.
- Or sit in the free-agent pool and get deleted by ``offseason.cull_free_agents``, which
  keeps only the top ~80 free agents by current overall. A raw prospect never survives
  that cut, so the draft fed nothing into the league at all and the talent pipeline ran
  dry -- leaving teams with tens of millions in cap space and no one worth signing.

This module models the missing middle: a drafted player who isn't NHL-ready is *reserved*
-- still developing (``development.develop_all`` already runs over every player in the
world, rostered or not, so they improve on schedule), protected from the free-agent cull,
and off-limits to NHL signings until their development window closes. That window is
staggered by draft position, so a class trickles into the league over several seasons the
way a real one does rather than arriving all at once.

It is deliberately not a full AHL: there is no minor-league team, roster, schedule, or
stats, no distinction between a prospect in junior vs. the AHL vs. the NCAA vs. Europe,
and no midseason call-up -- a prospect graduates at an offseason boundary or not at all.
Those are real features, not oversights to paper over here; this is the minimum reserve
status that keeps the draft -> development -> NHL pipeline (and therefore the league's
economy) intact until a proper minor-league system lands.
"""
from __future__ import annotations

from typing import List

from pucksim.config import (PROSPECT_DEVELOPMENT_YEARS_BY_PICK,
                             PROSPECT_DEVELOPMENT_YEARS_DEFAULT)
from pucksim.models.player import Player
from pucksim.models.world import World


def development_years(pick_number: int) -> int:
    """Seasons of development a player picked at ``pick_number`` needs before the NHL.

    Staggered by draft position (``config.PROSPECT_DEVELOPMENT_YEARS_BY_PICK``): a draft
    class doesn't arrive all at once, it trickles in over several seasons from the top of
    the board down.
    """
    for last_pick, years in PROSPECT_DEVELOPMENT_YEARS_BY_PICK:
        if pick_number <= last_pick:
            return years
    return PROSPECT_DEVELOPMENT_YEARS_DEFAULT


def years_since_drafted(player: Player, season_year: int) -> int:
    """Seasons elapsed since this player was drafted, or -1 if they never were."""
    draft = getattr(player, "draft", None)
    if not draft:
        return -1
    return season_year - draft.get("year", season_year)


def is_reserved_prospect(player: Player, season_year: int) -> bool:
    """Is this player a drafted prospect still serving their development window?

    Three conditions, all required: they hold draft rights, they aren't on an NHL roster
    (a top pick who went straight to the NHL is not reserved -- they're just a player),
    and their pick-dependent development window hasn't elapsed. Once it has, they graduate
    into the normal free-agent market and can be signed by anyone at market price -- or,
    if they never developed into an NHL player, wash out of the league via
    ``offseason.cull_free_agents`` like any other unwanted free agent. Both outcomes are
    realistic: most late-round picks never play a game.
    """
    if player.team_id is not None:
        return False
    draft = getattr(player, "draft", None)
    if not draft:
        return False
    elapsed = years_since_drafted(player, season_year)
    return 0 <= elapsed < development_years(draft.get("pick", 1))


def reserved_prospects(world: World) -> List[Player]:
    """Every prospect currently inside their development window."""
    return [p for p in world.players.values()
            if is_reserved_prospect(p, world.season_year)]
