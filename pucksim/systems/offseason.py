"""Offseason orchestration: archive the year, roll contracts, age/retire, run the draft and free
agency, reload next season.

Structural precedent: HoopR's ``hoopsim/systems/offseason.py`` (178 lines: ``archive_season()``
orchestration order -- awards -> career archival -> development). PuckSim ports that ordering
exactly, threaded through this codebase's own already-shipped systems (``systems/cap.py``,
``systems/draft_system.py``, ``systems/freeagency.py``, Steps 2.4/2.5) plus this step's five new
modules. The full order, matching HoopR's own documented sequence:

    archive (awards -> accolades -> career lines) -> expire contracts -> age/retire/develop
    (permanent aging + goalie season-form resample) -> draft -> free agency -> fill rosters ->
    grow cap -> momentum offseason reset -> start the next regular season.

Why awards must be computed BEFORE career archival (HoopR's own reasoning, ported verbatim):
rookies still have an empty ``career`` at award-computation time (Calder eligibility -- see
``systems/awards._is_rookie`` -- reads career-emptiness), and once each player's just-finished
season is appended to ``career``, "most improved"-style comparisons need last season's overall
to still be readable from the LAST career entry, not the one about to be added. Reversing this
order would silently break both.

Where the goalie season-form mechanic (DEVPLAN.md Step 2.7's "Goalie year-to-year consistency"
design note, ``systems/development.py``'s ``GoalieFormState``) plugs in: ``run_offseason``
below owns one ``GoalieFormState`` instance per World (mirrors ``sim/season.py``'s own
``GoalieRestState`` per-World-instance precedent) and passes it into ``development.develop_all``
so every goalie's form is freshly resampled for the upcoming season as part of the same
aging/development pass -- see ``_form_state_for``'s docstring for why this follows
``sim/season.py``'s exact id()-keyed-cache pattern rather than inventing a new one.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pucksim.config import (
    CAP_GROWTH_RATE,
    GOALIES_MAX,
    GOALIES_MIN,
    MINIMUM_SALARY,
    RETIREMENT_AGE,
    ROSTER_MAX,
    ROSTER_MIN,
    SKATERS_MAX,
    SKATERS_MIN,
)
from pucksim.models.contract import flat_contract
from pucksim.models.league import Phase, standings
from pucksim.models.world import World
from pucksim.sim.season import start_season
from pucksim.systems import awards, legacy
from pucksim.systems.development import GoalieFormState, develop_all

# ---------------------------------------------------------------------------
# Per-World goalie-form-state cache (mirrors sim/season.py's _REST_STATE_BY_WORLD_ID pattern
# exactly -- see that module's own extensive comment for the full correctness reasoning this
# borrows: id()-keyed, NOT a WeakKeyDictionary, because World is a plain @dataclass with a
# generated __eq__/no __hash__; the cache value holds a strong reference to World itself so a
# GC'd World's id can never be silently reused out from under a stale entry).
# ---------------------------------------------------------------------------
_FORM_STATE_BY_WORLD_ID: Dict[int, Tuple[World, GoalieFormState]] = {}


def _form_state_for(world: World) -> GoalieFormState:
    """Return (creating if needed) this World's persistent ``GoalieFormState``.

    A goalie's season-form multiplier must stay fixed for their ENTIRE season once resampled
    (see development.py's module docstring) -- it is resampled exactly once per offseason
    transition, not per game, so this state must survive across every game simmed within a
    season, which is exactly what a per-World-instance cache (rather than a throwaway per-call
    object) provides.
    """
    key = id(world)
    entry = _FORM_STATE_BY_WORLD_ID.get(key)
    if entry is None or entry[0] is not world:
        entry = (world, GoalieFormState())
        _FORM_STATE_BY_WORLD_ID[key] = entry
    return entry[1]


def goalie_form_state(world: World) -> GoalieFormState:
    """Public accessor for this World's current goalie form state -- callers (e.g. a future
    save-probability integration in sim/goalies.py, or a test wanting to inspect a specific
    goalie's rolled form) should go through this rather than reaching into the private cache."""
    return _form_state_for(world)


# ---------------------------------------------------------------------------
# Season archival (awards -> accolades -> per-player career line + milestones)
# ---------------------------------------------------------------------------
def _skater_career_line(p) -> dict:
    s = p.season
    return {
        "year": None, "gp": s.gp, "g": s.g, "a": s.a,
        "ppg": round(s.points / s.gp, 2) if s.gp else 0.0, "ovr": p.overall,
    }


def _goalie_career_line(p) -> dict:
    s = p.season
    return {
        "year": None, "gp": s.gp, "wins": s.wins, "shutouts": s.shutouts,
        "save_pct": round(s.save_pct, 3), "gaa": round(s.gaa, 2), "ovr": p.overall,
    }


def archive_season(world: World, champion_tid: Optional[int]) -> List[dict]:
    """Record the season into ``world.history``, roll careers, accrue accolades.

    Returns milestone events crossed this season. Mirrors HoopR's ``archive_season`` ordering
    exactly: awards computed first (see module docstring for why), then per-player career
    lines appended (each stamped with ``world.season_year`` here since the line-builders above
    leave ``year`` as a placeholder), then accolades ticked from those same awards.
    """
    conf_standings: Dict[str, List[int]] = {}
    for team in world.team_list():
        conf_standings.setdefault(team.conference, [])
    for team in standings(world.team_list(), world.schedule, world.standings_rule):
        conf_standings[team.conference].append(team.tid)

    season_awards = awards.compute_awards(world)
    champ = world.teams.get(champion_tid) if champion_tid in world.teams else None
    world.history.append({
        "year": world.season_year,
        "champion": champion_tid,
        "champion_name": champ.name if champ else "",
        "standings": conf_standings,
        "awards": season_awards,
    })
    # Tally each winner's personal accolades so career résumés stay self-contained for the HoF.
    legacy.record_accolades(world, season_awards, champion_tid)

    milestones: List[dict] = []
    for p in world.players.values():
        if p.season.gp == 0:
            continue
        before = legacy.career_totals(p.career)
        line = _goalie_career_line(p) if p.is_goalie else _skater_career_line(p)
        line["year"] = world.season_year
        team = world.teams.get(p.team_id) if p.team_id is not None else None
        line["team"] = team.abbrev if team else "FA"
        p.career.append(line)
        for ms in legacy.crossed_milestones(before, legacy.career_totals(p.career),
                                             is_goalie=p.is_goalie):
            milestones.append({**ms, "pid": p.pid, "name": p.name})
    return milestones


# ---------------------------------------------------------------------------
# Contracts / aging / retirement
# ---------------------------------------------------------------------------
def expire_contracts(world: World) -> List[int]:
    """Advance every rostered contract a year; return pids that hit free agency."""
    new_fas: List[int] = []
    for team in world.team_list():
        for pid in list(team.roster):
            player = world.players.get(pid)
            if player is None:
                continue
            player.contract.advance_year()
            if player.contract.years_remaining == 0:
                new_fas.append(pid)
    for pid in new_fas:
        world.release_player(pid)
    return new_fas


def age_and_retire(world: World) -> dict:
    """Age everyone a year, retire the old/declined, and freeze each retiree's legacy résumé.

    Returns ``{"retired": [pids], "inducted": [résumé snapshots]}``. Retirees are snapshotted
    via ``legacy.retire`` (appends to ``world.retired``, and ``world.hall_of_fame`` if worthy)
    so their careers survive being removed from the active player pool -- mirrors HoopR's own
    "no longer simply dropped" retirement handling exactly.
    """
    retiring: List[int] = []
    for p in list(world.players.values()):
        p.age += 1
        force = p.age >= RETIREMENT_AGE
        decline = p.age >= 35 and p.overall < 60 and world.rng.chance(0.5)
        if force or decline:
            retiring.append(p.pid)

    inducted: List[dict] = []
    for pid in retiring:
        p = world.players[pid]
        snap = legacy.retire(world, p)
        if snap["hof"]:
            inducted.append(snap)
        world.players.pop(pid)
        if p.team_id is not None and p.team_id in world.teams:
            world.teams[p.team_id].remove_player(pid)
        if pid in world.free_agents:
            world.free_agents.remove(pid)
    return {"retired": retiring, "inducted": inducted}


# ---------------------------------------------------------------------------
# Roster maintenance
# ---------------------------------------------------------------------------
def _goalies(world: World, pids) -> List[int]:
    return [pid for pid in pids if world.players[pid].is_goalie]


def _skaters(world: World, pids) -> List[int]:
    return [pid for pid in pids if not world.players[pid].is_goalie]


def enforce_roster_max(world: World) -> None:
    """Waive the lowest-rated players from any team over the roster maximum, INCLUDING any
    team whose overall headcount is legal but whose GOALIE sub-count alone exceeds
    ``config.GOALIES_MAX`` (see the two-part bug this docstring documents below).

    Draft picks can push a team over the limit even without shedding salary; waived players go
    to free agency where they can latch on elsewhere.

    Position-aware -- TWO DISTINCT BUGS FIXED here, both found during this step's end-to-end
    offseason integration testing (``tests/test_offseason.py``'s full-cycle tests), neither of
    which is hypothetical -- both were directly observed:

    1. Waiving purely by lowest overall, with no regard to position, could waive a team down to
       a single rostered goalie (goalies are a small, easily-exhausted sub-pool of ~2-3 per
       team, so "worst overall league-wide" can trivially pick off a below-average backup
       goalie while plenty of below-average skaters remain). Fixed by restricting waive
       candidates to whichever position group still has slack above its OWN minimum
       (``GOALIES_MIN``/``SKATERS_MIN``), never picking from a group already at its floor.
    2. A team can have a LEGAL overall headcount (e.g. 22, under ``ROSTER_MAX`` = 23) while
       still carrying too MANY goalies specifically (e.g. 4, over ``GOALIES_MAX`` = 3) -- a
       team-wide ``len(team.roster) > ROSTER_MAX`` check alone never notices this, since total
       headcount can stay comfortably under the ceiling even with a bloated goalie group (this
       happens routinely right after a draft: ``draft_system`` has no per-team goalie-slot cap
       of its own, so a team can easily draft its way to 4+ goalies while still under
       ``ROSTER_MAX`` in total). Fixed with a SEPARATE per-position-group enforcement pass
       (below the roster-max loop) that waives the worst goalie/skater whenever that group
       alone exceeds its own max, independent of total headcount.
    """
    for team in world.team_list():
        while len(team.roster) > ROSTER_MAX:
            goalies = _goalies(world, team.roster)
            skaters = _skaters(world, team.roster)
            candidates: List[int] = []
            if len(goalies) > GOALIES_MIN:
                candidates.extend(goalies)
            if len(skaters) > SKATERS_MIN:
                candidates.extend(skaters)
            if not candidates:
                # Every position group is already pinned at its own minimum -- can't legally
                # shrink further even though total roster size is still over ROSTER_MAX (a
                # narrow edge case, e.g. GOALIES_MIN + SKATERS_MIN could in principle already
                # equal or exceed ROSTER_MAX under a different config tuning). Stop rather than
                # illegally cut a position group below its floor.
                break
            worst = min(candidates, key=lambda pid: world.players[pid].overall)
            world.release_player(worst)

        # Bug #2 above: a per-position-group cap independent of total headcount.
        while len(_goalies(world, team.roster)) > GOALIES_MAX:
            worst = min(_goalies(world, team.roster), key=lambda pid: world.players[pid].overall)
            world.release_player(worst)
        while len(_skaters(world, team.roster)) > SKATERS_MAX:
            worst = min(_skaters(world, team.roster), key=lambda pid: world.players[pid].overall)
            world.release_player(worst)


def fill_rosters(world: World) -> None:
    """Ensure every team meets BOTH the overall roster minimum AND each position group's own
    minimum (``GOALIES_MIN``/``SKATERS_MIN``) by signing minimum-deal free agents.

    Position-aware for the same reason ``enforce_roster_max`` is (see that function's
    docstring): a team can be at/above ``ROSTER_MIN`` in raw headcount while still being short a
    goalie specifically (e.g. down to 1 goalie after retirements) -- filling by "just add the
    best available free agent regardless of position" would never notice or fix that, since
    skater free agents vastly outnumber goalie free agents in the pool. Goalie needs are
    resolved FIRST (a team literally cannot ice a game with zero rostered goalies), then skater
    needs, then any remaining shortfall against the overall ``ROSTER_MIN``.
    """
    def _sign_best(team, pool_filter) -> bool:
        candidates = [pid for pid in world.free_agents if pool_filter(world.players[pid])]
        if not candidates:
            return False
        best = max(candidates, key=lambda pid: world.players[pid].overall)
        contract = flat_contract(MINIMUM_SALARY, 1, is_rookie_scale=False,
                                  signed_year=world.season_year + 1)
        world.sign_player(best, team.tid)
        world.players[best].contract = contract
        return True

    for team in world.team_list():
        while len(_goalies(world, team.roster)) < GOALIES_MIN:
            if not _sign_best(team, lambda p: p.is_goalie):
                break   # no goalie free agents left -- can't fully satisfy the minimum
        while len(_skaters(world, team.roster)) < SKATERS_MIN:
            if not _sign_best(team, lambda p: not p.is_goalie):
                break
        while len(team.roster) < ROSTER_MIN and world.free_agents:
            if not _sign_best(team, lambda p: True):
                break


def cull_free_agents(world: World, keep: int = 80) -> int:
    """Keep the league population bounded: unsigned, lowest-rated free agents leave the league."""
    if len(world.free_agents) <= keep:
        return 0
    ranked = sorted(world.free_agents,
                    key=lambda pid: world.players[pid].overall, reverse=True)
    cut = ranked[keep:]
    for pid in cut:
        world.free_agents.remove(pid)
        world.players.pop(pid, None)
    return len(cut)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def pre_draft(world: World, champion_tid: Optional[int]) -> dict:
    """Archive the year, develop players (+ resample goalie form), expire contracts, age/retire.

    Runs BEFORE the draft (mirrors HoopR's own ``pre_draft`` step-ordering exactly): the draft
    needs this season's just-updated standings-derived draft order (``draft_system`` reads
    ``world.schedule``/``standings()`` directly, so this function doesn't need to hand anything
    off explicitly) and an already-aged/retired player pool so cap space reflects who's actually
    still around.
    """
    milestones = archive_season(world, champion_tid)
    form_state = _form_state_for(world)
    develop_all(world, form_state=form_state)
    new_fas = expire_contracts(world)
    ar = age_and_retire(world)
    return {"new_fas": len(new_fas), "retired": len(ar["retired"]), "inducted": ar["inducted"],
            "milestones": milestones}


def post_offseason(world: World) -> None:
    """Fill rosters to the minimum, cull the free-agent pool, grow the cap, reset momentum,
    advance the season year, and start the next regular season.

    ``enforce_roster_max`` runs again here (BUG FIX, found during this step's end-to-end
    offseason testing, see ``enforce_roster_max``'s own docstring for the position-aware fix
    itself): ``run_offseason`` already calls it once right after the draft, but
    ``systems.freeagency.run_free_agency`` runs AFTER that and can sign a team back over
    ``ROSTER_MAX`` on its own (free agency's own internal roster-target logic doesn't
    necessarily respect this module's exact ceiling) -- without a second pass here, a team could
    end an offseason over the legal roster maximum with no further step to catch it. Runs BEFORE
    ``fill_rosters`` (which only ever ADDS players) so the two can never fight each other in the
    same call.
    """
    from pucksim.systems import cap
    from pucksim.systems.momentum import offseason_reset

    enforce_roster_max(world)
    fill_rosters(world)
    cull_free_agents(world)
    cap.grow_cap(world, CAP_GROWTH_RATE)
    world.season_year += 1
    world.draft_class = None        # retire this year's class so next offseason starts clean
    offseason_reset(world)          # rust chemistry, drift morale toward baseline for the new year
    start_season(world)


def run_offseason(world: World, champion_tid: Optional[int]) -> dict:
    """Headless: run the FULL offseason (AI for every team) and start the next season.

    Order: archive/develop/age (``pre_draft``) -> draft -> free agency -> roster-max enforcement
    -> ``post_offseason`` (fill/cull/cap-growth/momentum-reset/season-start). Mirrors HoopR's own
    ``run_offseason`` orchestration shape, threaded through this codebase's already-shipped
    ``systems/draft_system.run_draft``/``systems/freeagency.run_free_agency`` (Steps 2.4/2.5)
    rather than reinventing draft/FA orchestration here.
    """
    from pucksim.systems import draft_system, freeagency

    summary = pre_draft(world, champion_tid)
    world.phase = Phase.DRAFT
    draft_summary = draft_system.run_draft(world)
    enforce_roster_max(world)

    world.phase = Phase.FREE_AGENCY
    fa_summary = freeagency.run_free_agency(world)

    post_offseason(world)
    summary.update({"draft": draft_summary, "free_agency": fa_summary})
    return summary
