"""End-of-season awards, computed from regular-season production and team success.

Structural precedent: HoopR's ``hoopsim/systems/awards.py`` (108 lines: ``compute_awards()``,
one value function per award, a shared ``_entry()`` snapshot builder). PuckSim swaps the NBA's
MVP/DPOY/ROY/MIP/All-League for hockey's five marquee regular-season awards:

  - **Hart** (MVP)      -- most valuable player, league-wide, any position.
  - **Norris**          -- best defenseman.
  - **Vezina**          -- best goaltender.
  - **Calder**          -- best rookie (any position).
  - **Selke**           -- best DEFENSIVE forward (not "best defenseman" -- that's Norris; Selke
                            specifically honors a forward's two-way play, mirroring the real NHL
                            award's forward-only scope).

Run once per season from ``systems/offseason.archive_season``, BEFORE the season's stats roll
into career history -- so rookies still have an empty ``career`` and Calder eligibility can be
judged the same way every season, not just the first one ever simulated (see ``_is_rookie``
below for why age/career-emptiness is used together, not career-emptiness alone). Results are
stored as plain dicts on ``world.history`` (mirrors HoopR) and are self-contained (name/team/
stat snapshots), so they survive players later retiring.

Why goalies and skaters need separate eligibility/value math: ``Player.season`` is one of two
structurally different ``StatLine`` shapes (Step 1.3/1.6) -- a goalie's ``SkaterStatLine``-shaped
production metrics (``points``/``fo_pct``/etc.) simply don't exist on ``GoalieStatLine``, and
vice versa (``save_pct``/``gaa`` don't exist on a skater's line). Every award's candidate pool is
therefore filtered to the right StatLine type before scoring, rather than trying to force one
combined value function over both shapes.
"""
from __future__ import annotations

from typing import List, Optional

from pucksim.models.attributes import composite
from pucksim.models.player import Player
from pucksim.models.stats import GoalieStatLine, SkaterStatLine
from pucksim.models.team import Team
from pucksim.models.world import World

# Games-played fraction thresholds, same shape as HoopR's MIN_GP_FRACTION/ROOKIE_GP_FRACTION --
# a partial-season call-up or a player who was traded/injured for a big chunk of the year
# shouldn't be awards-eligible even if their per-game rate stats look great over a small sample.
# PROVISIONAL/TUNABLE (DEVPLAN.md doesn't pin an exact fraction) -- picked so a full-time
# NHL regular clears the bar comfortably while a September call-up or a season lost mostly to
# injury does not.
MIN_GP_FRACTION = 0.55          # Hart / Norris / Selke eligibility
GOALIE_MIN_GP_FRACTION = 0.40   # Vezina: goalies split starts with a backup all season by
                                # design (sim/goalies.py's rotation model), so a #1 goalie
                                # who nonetheless only starts ~60% of games needs a lower bar
                                # than a full-time skater to be eligible at all.
ROOKIE_GP_FRACTION = 0.40       # Calder gets the same lower bar as HoopR's ROY -- a rookie who
                                # breaks in partway through the season (very common) shouldn't
                                # be disqualified by the stricter skater-regular threshold.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _find_team(world: World, tid: Optional[int]) -> Optional[Team]:
    """Safe team lookup -- ``World.team()`` raises on a missing/free-agent tid; awards code
    routinely handles players whose team_id may not resolve (a player who was released/traded
    away after the stat line accrued), so this never raises."""
    if tid is None:
        return None
    return world.teams.get(tid)


def _is_rookie(p: Player) -> bool:
    """A true rookie has no archived career season yet.

    Mirrors HoopR's own reasoning (see that module's comment): on the very first simulated
    season, EVERY player's ``career`` is empty (nobody has an archived season yet), so the
    career-emptiness check alone would hand Calder to a 35-year-old veteran just because this
    happens to be the first season this World has ever archived. Gated by age as well (using
    ``ROOKIE_AGE_RANGE``'s upper bound would be too permissive for a late-blooming call-up who
    is nonetheless clearly not a rookie any more) -- specifically, no archived career AND an age
    young enough that this is plausibly an actual NHL debut season.
    """
    from pucksim.config import ROOKIE_AGE_RANGE
    return not p.career and p.age <= ROOKIE_AGE_RANGE[1] + 2


def _rostered_skaters(world: World) -> List[Player]:
    return [p for t in world.team_list() for pid in t.roster
            if pid in world.players and not (p := world.players[pid]).is_goalie
            and isinstance(p.season, SkaterStatLine) and p.season.gp > 0]


def _rostered_goalies(world: World) -> List[Player]:
    return [p for t in world.team_list() for pid in t.roster
            if pid in world.players and (p := world.players[pid]).is_goalie
            and isinstance(p.season, GoalieStatLine) and p.season.gp > 0]


def _entry(world: World, p: Player, **extra) -> dict:
    """A self-contained award snapshot (frozen name/team/stats plus a live tid for coloring)."""
    team = _find_team(world, p.team_id)
    s = p.season
    out = {
        "pid": p.pid,
        "name": p.name,
        "tid": p.team_id,
        "team": team.abbrev if team else "FA",
        "position": p.position,
        "overall": p.overall,
        "gp": s.gp,
    }
    if isinstance(s, SkaterStatLine):
        out.update({
            "g": s.g, "a": s.a, "pts": s.points,
            "ppg": round(s.points / s.gp, 2) if s.gp else 0.0,
        })
    elif isinstance(s, GoalieStatLine):
        out.update({
            "wins": s.wins, "save_pct": round(s.save_pct, 3), "gaa": round(s.gaa, 2),
            "shutouts": s.shutouts,
        })
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Value functions -- one per award, mirroring HoopR's per-award scoring-function shape.
# ---------------------------------------------------------------------------
def _hart_value(p: Player, team_win_pct: float) -> float:
    """Hart (MVP) -- an all-in-one production score across ANY position, nudged by team
    success (a star driving a winning team reads as more "valuable" than identical stats on a
    last-place club, same team-success nudge HoopR's own MVP formula uses)."""
    s = p.season
    if s.gp == 0:
        return 0.0
    prod = s.points / s.gp + 0.35 * (s.hits + s.blocks + s.takeaways) / s.gp
    return prod * (0.7 + 0.3 * team_win_pct)


def _norris_value(p: Player) -> float:
    """Norris (best defenseman) -- blends the defenseman's own defensive composite with their
    two-way/offensive production, since the real award has historically favored D-men who
    contribute at both ends (a shutdown-only D-man and a pure offensive-D-man can both win it).
    """
    s = p.season
    if s.gp == 0:
        return 0.0
    per_game_pts = s.points / s.gp
    per_game_phys = (s.blocks + s.hits) / s.gp
    return (composite(p.ratings, "defense") * 0.5
            + composite(p.ratings, "playmaking_c") * 0.2
            + per_game_pts * 6.0
            + per_game_phys * 1.5)


def _selke_value(p: Player) -> float:
    """Selke (best defensive FORWARD) -- forward-only two-way award; unlike Norris this is
    explicitly NOT about offensive production, it's about shutting down the opponent's best
    while still being a positive possession/faceoff presence."""
    s = p.season
    if s.gp == 0:
        return 0.0
    fo_bonus = s.fo_pct * 5.0 if (s.fo_won + s.fo_lost) > 0 else 0.0
    per_game_defense = (s.blocks + s.takeaways) / s.gp
    return (composite(p.ratings, "defense") * 0.6
            + composite(p.ratings, "faceoff_c") * 0.15
            + per_game_defense * 2.0
            + fo_bonus)


def _vezina_value(p: Player) -> float:
    """Vezina (best goaltender) -- rewards save percentage (the primary real-world Vezina
    signal) with a workload floor already enforced by ``GOALIE_MIN_GP_FRACTION`` eligibility,
    plus a GAA and shutout nudge."""
    s = p.season
    if s.gp == 0:
        return 0.0
    return s.save_pct * 100.0 - s.gaa * 1.5 + s.shutouts * 0.3


def _calder_value(p: Player, team_win_pct: float) -> float:
    """Calder (best rookie) -- skaters and goalies compete on the SAME award in real hockey, so
    this dispatches by StatLine shape to a comparable-ish scale rather than picking only one
    position type to be eligible."""
    s = p.season
    if s.gp == 0:
        return 0.0
    if isinstance(s, GoalieStatLine):
        return s.save_pct * 100.0 - s.gaa * 1.5
    return (s.points / s.gp + 0.2 * (s.hits + s.blocks) / s.gp) * (0.8 + 0.2 * team_win_pct)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def compute_awards(world: World) -> dict:
    """Pick the season's award winners (Hart/Norris/Vezina/Calder/Selke) from current
    (not-yet-archived) season stats. Returns a dict keyed by award name; an award key is simply
    absent if no candidate met its eligibility bar (e.g. a brand-new/mid-construction World with
    no games played yet) -- callers should never assume every key is always present.
    """
    games = _games_played(world)
    min_gp = games * MIN_GP_FRACTION
    goalie_min_gp = games * GOALIE_MIN_GP_FRACTION
    rookie_gp = games * ROOKIE_GP_FRACTION
    wp = {t.tid: _win_pct(t) for t in world.team_list()}

    skaters = _rostered_skaters(world)
    goalies = _rostered_goalies(world)
    defensemen = [p for p in skaters if p.position == "D"]
    forwards = [p for p in skaters if p.position in ("LW", "C", "RW")]

    awards: dict = {}

    hart_eligible = [p for p in skaters + goalies if p.season.gp >= min_gp]
    if hart_eligible:
        # Goalies compete for the Hart too in real hockey (rare, but legal) -- score via the
        # same per-position value split so a Vezina-caliber goalie CAN win Hart in principle,
        # without goalie save-pct/GAA needing to be shoehorned into the skater production formula.
        def hart_val(p: Player) -> float:
            if p.is_goalie:
                return _vezina_value(p) * 0.5   # goalies are a plausible but harder Hart case
            return _hart_value(p, wp.get(p.team_id, 0.0))
        awards["hart"] = _entry(world, max(hart_eligible, key=hart_val))

    norris_eligible = [p for p in defensemen if p.season.gp >= min_gp]
    if norris_eligible:
        awards["norris"] = _entry(world, max(norris_eligible, key=_norris_value))

    vezina_eligible = [p for p in goalies if p.season.gp >= goalie_min_gp]
    if vezina_eligible:
        awards["vezina"] = _entry(world, max(vezina_eligible, key=_vezina_value))

    selke_eligible = [p for p in forwards if p.season.gp >= min_gp]
    if selke_eligible:
        awards["selke"] = _entry(world, max(selke_eligible, key=_selke_value))

    calder_eligible = [p for p in skaters + goalies
                       if _is_rookie(p) and p.season.gp >= rookie_gp]
    if calder_eligible:
        def calder_val(p: Player) -> float:
            return _calder_value(p, wp.get(p.team_id, 0.0))
        awards["calder"] = _entry(world, max(calder_eligible, key=calder_val))

    return awards


def _win_pct(team: Team) -> float:
    gp = team.games_played
    return team.wins / gp if gp else 0.0


def _games_played(world: World) -> int:
    """Fallback games-per-team estimate when ``World`` has no ``season_games`` attribute
    (PuckSim's ``World`` doesn't carry one directly -- ``config.SEASON_GAMES`` is the intended
    source, imported lazily here to avoid a hard import-order dependency at module load)."""
    from pucksim.config import SEASON_GAMES
    return SEASON_GAMES
