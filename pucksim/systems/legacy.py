"""Career legacy: accolade tallies, career résumés, milestones, the Hall of Fame, and all-time
leaderboards.

Structural precedent: HoopR's ``hoopsim/systems/legacy.py`` (186 lines: HOF resume-snapshot
pattern). This module ports that pattern directly, on top of PuckSim's own career ledger --
``Player.career`` (per-season lines, Step 1.6) plus ``Player.accolades`` (an award tally, same
step) -- so it can't tell whether a season was simulated live or fabricated at world creation
(no PuckSim equivalent of HoopR's ``gen/backstory.py`` exists yet, but the shape is kept
forward-compatible with one). A retiree is frozen into a self-contained *résumé* dict (the same
shape for living and retired players), which is what the Hall of Fame and record book store, so
the data survives the player being dropped from ``world.players``.

Hockey-specific career-line shape (JUDGMENT CALL -- DEVPLAN.md doesn't pin an exact ``career``
entry schema beyond "Player.career/accolades fields already exist for this step to populate"):
each season's ``career`` entry stores ``year``/``team``/``gp`` plus position-appropriate rate
stats (``ppg``/``g``/``a`` for skaters, ``save_pct``/``gaa``/``wins`` for goalies) and the
player's ``ovr`` at the time -- mirrors HoopR's own per-season line shape, position-split the
same way ``systems/awards.py`` already had to split skater vs. goalie scoring.

Hall of Fame scoring (JUDGMENT CALL, exact weights/threshold not specified by DEVPLAN.md):
weighted résumé score, tuned only by the same "a multi-time award winner/perennial All-Star-
equivalent career gets in, a long-tenured depth player does not" intuition HoopR's own
``HOF_THRESHOLD``/``ACCOLADE_WEIGHTS`` used -- PROVISIONAL, revisit once real simulated-league
career-length/accolade-frequency data exists to calibrate against.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from pucksim.models.player import Player
from pucksim.models.world import World

# -- accolades ----------------------------------------------------------------
# Tally keys accrued in offseason.archive_season as each season's awards are crowned. Mirrors
# HoopR's ACCOLADE_KEYS/ACCOLADE_LABELS shape exactly, swapped to hockey's five marquee awards
# (systems/awards.py) plus champion/scoring-title (Rocket Richard-equivalent) cross-cutting ones.
ACCOLADE_KEYS = ("hart", "norris", "vezina", "calder", "selke", "scoring_title", "champion")
ACCOLADE_LABELS = {
    "hart": "Hart Trophy (MVP)", "norris": "Norris Trophy", "vezina": "Vezina Trophy",
    "calder": "Calder Trophy", "selke": "Selke Trophy",
    "scoring_title": "Scoring Title", "champion": "Stanley Cup Champion",
}

# -- Hall of Fame scoring -------------------------------------------------------
# Weighted résumé score; a player clears the bar at HOF_THRESHOLD. PROVISIONAL, same framing as
# every other unresolved constant in this codebase -- tuned only by intuition (multi-award/
# multi-champion careers get in, journeymen do not), not fit to any real data.
ACCOLADE_WEIGHTS: Dict[str, float] = {
    "hart": 12.0, "norris": 6.0, "vezina": 6.0, "selke": 4.0,
    "scoring_title": 3.0, "champion": 3.0, "calder": 2.0,
}
PEAK_ANCHOR = 78            # overall above which peak play starts adding HoF weight
HOF_THRESHOLD = 50.0

# -- milestones -----------------------------------------------------------------
# (stat key in totals, human noun, ascending thresholds). Crossed during a season -> surfaced in
# the offseason summary. Skater milestones use career counting totals; goalie milestones use
# wins/shutouts (career points/goals for a goalie aren't a meaningful hockey milestone category).
MILESTONES = (
    ("pts", "point", (500, 1000)),
    ("g", "goal", (300, 500)),
    ("a", "assist", (500, 1000)),
    ("gp", "game", (500, 1000)),
)
GOALIE_MILESTONES = (
    ("wins", "win", (200, 300, 400)),
    ("shutouts", "shutout", (30, 50)),
    ("gp", "game", (400, 700)),
)


# ---------------------------------------------------------------------------
# Career math
# ---------------------------------------------------------------------------
def career_totals(career: List[dict]) -> Dict[str, float]:
    """Career counting totals + per-game averages, reconstructed from per-season ``career``
    lines. Dispatches on whether the entries carry skater or goalie shape (a player is one or
    the other for their whole career -- position doesn't change -- so this just checks the
    first entry, if any)."""
    if not career:
        return {"gp": 0}
    is_goalie = "save_pct" in career[0] or "wins" in career[0]
    gp = sum(e.get("gp", 0) for e in career)
    if is_goalie:
        wins = sum(e.get("wins", 0) for e in career)
        shutouts = sum(e.get("shutouts", 0) for e in career)
        # save_pct/gaa are rate stats -- reconstruct a GP-weighted career average rather than
        # naively averaging each season's rate (a 5-game cup of coffee shouldn't count as much
        # as a full 60-game season in the career average).
        weighted_sv = sum(e.get("gp", 0) * e.get("save_pct", 0.0) for e in career)
        weighted_gaa = sum(e.get("gp", 0) * e.get("gaa", 0.0) for e in career)
        return {
            "gp": int(gp), "wins": int(wins), "shutouts": int(shutouts),
            "save_pct": round(weighted_sv / gp, 3) if gp else 0.0,
            "gaa": round(weighted_gaa / gp, 2) if gp else 0.0,
        }
    g = sum(e.get("g", 0.0) for e in career)
    a = sum(e.get("a", 0.0) for e in career)
    pts = g + a
    return {
        "gp": int(gp), "g": int(round(g)), "a": int(round(a)), "pts": int(round(pts)),
        "ppg": round(pts / gp, 2) if gp else 0.0,
    }


def hof_score(resume: dict) -> float:
    """Weighted Hall-of-Fame score from a résumé's accolades, peak, longevity, and production."""
    acc = resume.get("accolades", {})
    score = sum(ACCOLADE_WEIGHTS.get(k, 0.0) * acc.get(k, 0) for k in ACCOLADE_WEIGHTS)
    score += max(0, resume.get("peak_ovr", 0) - PEAK_ANCHOR) * 2.0
    score += resume.get("seasons", 0) * 1.0
    totals = resume.get("totals", {})
    # Skaters are rewarded for career points, goalies for career wins -- whichever total this
    # résumé actually carries (mutually exclusive by position, see career_totals above).
    score += totals.get("pts", 0) / 300.0
    score += totals.get("wins", 0) / 40.0
    return round(score, 1)


def resume(world: World, player: Player, retired_year: Optional[int] = None) -> dict:
    """A self-contained legacy résumé -- works for a living player or a retiree being frozen."""
    career = player.career
    totals = career_totals(career)
    peak_ovr = max([e.get("ovr", 0) for e in career] + [player.overall])
    team = world.teams.get(player.team_id) if player.team_id is not None else None
    last_team = career[-1].get("team") if career else (team.abbrev if team else "FA")
    out = {
        "pid": player.pid,
        "name": player.name,
        "position": player.position,
        "seasons": len(career),
        "peak_ovr": peak_ovr,
        "totals": totals,
        "accolades": {k: v for k, v in player.accolades.items() if v},
        "last_team": last_team,
        "first_year": career[0].get("year") if career else world.season_year,
        "last_year": career[-1].get("year") if career else world.season_year,
        "draft": dict(player.draft) if player.draft else None,
    }
    out["hof_score"] = hof_score(out)
    out["hof"] = out["hof_score"] >= HOF_THRESHOLD
    if retired_year is not None:
        out["retired_year"] = retired_year
        out["induction_year"] = retired_year if out["hof"] else None
    return out


# ---------------------------------------------------------------------------
# Accolade accrual (called from offseason.archive_season after awards are computed)
# ---------------------------------------------------------------------------
def _tick(world: World, pid: Optional[int], key: str) -> None:
    p = world.players.get(pid) if pid is not None else None
    if p is not None:
        p.accolades[key] = p.accolades.get(key, 0) + 1


def record_accolades(world: World, awards: dict, champion_tid: Optional[int]) -> None:
    """Tick each season-award winner's personal tally so career résumés stay self-contained.

    Keys mirror ``systems/awards.compute_awards``'s exact award-name vocabulary
    (hart/norris/vezina/calder/selke) -- if that module's award keys ever change, this function
    must change with it (no indirection layer between the two by design, same as HoopR's
    matching pattern between its own awards.py/legacy.py).
    """
    for key in ("hart", "norris", "vezina", "calder", "selke"):
        entry = awards.get(key)
        if entry:
            _tick(world, entry.get("pid"), key)
    champ = world.teams.get(champion_tid) if champion_tid in world.teams else None
    if champ is not None:
        for pid in champ.roster:
            p = world.players.get(pid)
            if p is not None and p.season.gp > 0:
                _tick(world, pid, "champion")


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------
def crossed_milestones(prev: Dict[str, float], now: Dict[str, float], is_goalie: bool = False
                        ) -> List[dict]:
    """Milestone thresholds a player's career totals crossed between ``prev`` and ``now``."""
    table = GOALIE_MILESTONES if is_goalie else MILESTONES
    out: List[dict] = []
    for key, noun, thresholds in table:
        before, after = prev.get(key, 0), now.get(key, 0)
        for t in thresholds:
            if before < t <= after:
                out.append({"stat": key, "noun": noun, "value": t})
    return out


# ---------------------------------------------------------------------------
# Retirement -> résumé snapshot + Hall of Fame
# ---------------------------------------------------------------------------
def retire(world: World, player: Player) -> dict:
    """Freeze a retiring player into a résumé snapshot; induct into the Hall of Fame if worthy.

    Returns the snapshot (with ``hof``/``induction_year`` set) so callers can surface inductees.
    Appends to ``world.retired`` (and ``world.hall_of_fame`` if the résumé clears the bar) --
    see ``models/world.py``'s module docstring for why these fields exist on World.
    """
    snap = resume(world, player, retired_year=world.season_year)
    world.retired.append(snap)
    if snap["hof"]:
        world.hall_of_fame.append(snap)
    return snap


# ---------------------------------------------------------------------------
# All-time leaderboards (living + retired)
# ---------------------------------------------------------------------------
LEADERBOARD_CATEGORIES = ("pts", "g", "a", "gp", "wins", "shutouts")


def leaderboards(world: World, category: str = "pts", limit: int = 25) -> List[dict]:
    """Career totals across everyone -- current players and retirees -- ranked for the record
    book."""
    rows: List[dict] = []
    seen = set()
    for p in world.players.values():
        if p.career:                                  # only players with completed seasons
            r = resume(world, p)
            r["active"] = True
            rows.append(r)
            seen.add(p.pid)
    for snap in world.retired:
        if snap.get("pid") not in seen:               # a current player can't also be retired
            row = dict(snap)
            row["active"] = False
            rows.append(row)
    rows.sort(key=lambda r: r["totals"].get(category, 0), reverse=True)
    return rows[:limit]
