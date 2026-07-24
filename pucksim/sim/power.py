"""Team power ratings -- a single "how good is this team" number per club.

Mirrors HoopR's ``hoopsim/sim/power.py`` (SRS + roster-prior blend), with the numbers retuned
for hockey (goal margins instead of point margins, a goalie-weighted talent read instead of a
minutes-weighted rotation). Two things are produced here:

* **Projected strength** (``projected_strength`` / ``strength_stars``) -- a preseason,
  no-games-needed read of pure roster talent. This is what answers "how good (or bad) is the
  team I'm taking over?" on the team-selection screen, before a single puck has dropped.
* **In-season power ratings** (``power_ratings``) -- once games are played, a blended net
  rating (goals better/worse than an average team, à la a Simple Rating System) that folds a
  strength-of-schedule-adjusted results term together with the roster-talent prior. Early in a
  season the prior anchors the number and its weight decays as games accumulate, so a 5-3 team
  that has beaten nobody can still be told apart from a 3-5 team that has played a gauntlet.

Both reads share one talent model (``_team_talent``): a star-weighted average of the roster's
best skaters blended with the starting goalie's overall, since a single goaltender swings hockey
games far more than any one skater (DESIGN.md point 4). Outputs are league-relative -- the
in-season net ratings are de-meaned so the league always averages 0.0, and the stars are a
rank-based spread so a team is judged against its peers, not an absolute scale.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from pucksim.models.team import Team, roster_players
from pucksim.models.world import World

# Cap on per-game goal margin fed into SRS: a 7-goal blowout shouldn't count several times a
# 2-goal win. Garbage-time goals are noise, not signal.
_MARGIN_CAP = 5.0
# Games-played half-life for trusting results over the roster prior. At gp == _RESULTS_K the
# blend is 50/50; by a full 82-game season results dominate (~0.85 weight).
_RESULTS_K = 14.0
# Goals of net rating per standard deviation of roster talent. Keeps the prior's spread sensible
# (~±1.2 goals/game at the extremes) regardless of the league's absolute overall inflation.
_PRIOR_SPREAD = 0.6

# How the talent read is built from a roster (see ``_team_talent``).
_SKATER_SLOTS = 18          # a dressed lineup of skaters (12 F + 6 D)
_GOALIE_WEIGHT = 0.25       # a starting goalie is ~a quarter of a hockey team's strength
_NO_GOALIE_PENALTY = 5.0    # overall points docked when a roster has no goalie at all
_EMPTY_ROSTER_TALENT = 60.0  # never-crash fallback for a roster with no skaters


@dataclass
class PowerRating:
    tid: int
    power: float        # blended net rating (goals vs an average team), league-mean 0
    srs: float          # results-only Simple Rating System (0 until games are played)
    prior: float        # roster-talent prior (net goals)
    sos: float          # strength of schedule: average opponent power faced
    rank: int = 0       # 1 = best in league
    proj_win_pct: float = 0.0


# ---------------------------------------------------------------------------
# Roster-talent read (shared by the preseason strength and the in-season prior)
# ---------------------------------------------------------------------------
def _team_talent(world: World, team: Team) -> float:
    """A single talent scalar (~overall scale) for the roster: the best skaters, star-weighted,
    blended with the starting goalie's overall.

    Deliberately does NOT use ``team.rotation_pool`` (which in PuckSim is the *scratch* pool --
    roster minus whoever's in an active line/pair, the opposite of HoopR's rotation) -- a team's
    strength is its best players, not its bench. Works with no lines built and no games played,
    so it's usable straight off ``build_world`` on the selection screen.
    """
    roster = roster_players(team, world.players)
    skaters = sorted((p for p in roster if p.position != "G"),
                     key=lambda p: p.overall, reverse=True)
    goalies = sorted((p for p in roster if p.position == "G"),
                     key=lambda p: p.overall, reverse=True)
    if not skaters:
        return _EMPTY_ROSTER_TALENT

    top = skaters[:_SKATER_SLOTS]
    # Heavier weight on the best players -- a top pair/top line swings games more than the 18th
    # skater. Weights run high-to-low over the dressed skaters (top ~six carry the most).
    weights = [max(1.0, float(_SKATER_SLOTS + 1 - i)) for i in range(len(top))]
    skater_val = sum(p.overall * w for p, w in zip(top, weights)) / sum(weights)

    goalie_val = goalies[0].overall if goalies else skater_val - _NO_GOALIE_PENALTY
    return skater_val * (1.0 - _GOALIE_WEIGHT) + goalie_val * _GOALIE_WEIGHT


def roster_priors(world: World) -> Dict[int, float]:
    """Net-rating prior per team from roster talent, standardized across the league (goals)."""
    teams = world.team_list()
    talents = {t.tid: _team_talent(world, t) for t in teams}
    vals = list(talents.values())
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    std = var ** 0.5 or 1.0
    return {tid: (t - mean) / std * _PRIOR_SPREAD for tid, t in talents.items()}


# ---------------------------------------------------------------------------
# Results-based SRS
# ---------------------------------------------------------------------------
def _regular_games(world: World):
    return [g for g in world.schedule if g.played and not g.is_playoff]


def compute_srs(world: World) -> Tuple[Dict[int, float], Dict[int, List[int]]]:
    """Solve the Simple Rating System via fixed-point iteration over played regular games.

    Returns ``(rating_by_tid, opponents_by_tid)`` -- goal-margin ratings (league mean 0) plus the
    opponent list each team faced, so callers can compute strength of schedule without a second
    pass over the schedule.
    """
    teams = world.team_list()
    margins: Dict[int, List[float]] = {t.tid: [] for t in teams}
    opps: Dict[int, List[int]] = {t.tid: [] for t in teams}
    for g in _regular_games(world):
        diff = g.home_score - g.away_score
        capped = max(-_MARGIN_CAP, min(_MARGIN_CAP, diff))
        margins[g.home].append(capped)
        opps[g.home].append(g.away)
        margins[g.away].append(-capped)
        opps[g.away].append(g.home)

    avg_margin = {tid: (sum(m) / len(m) if m else 0.0) for tid, m in margins.items()}
    rating = dict(avg_margin)
    for _ in range(50):
        nxt = {}
        for tid in rating:
            opp = opps[tid]
            sos = sum(rating[o] for o in opp) / len(opp) if opp else 0.0
            nxt[tid] = avg_margin[tid] + sos
        # De-mean each pass so the system stays anchored at 0 and converges cleanly.
        m = sum(nxt.values()) / len(nxt)
        rating = {tid: v - m for tid, v in nxt.items()}
    return rating, opps


# ---------------------------------------------------------------------------
# Blended power ratings
# ---------------------------------------------------------------------------
def _win_pct_from_net(net: float) -> float:
    """Logistic map from net goal rating to an expected win percentage, kept in (0, 1).

    Calibrated for hockey's tighter spread: ~+0.5 goals/game of net rating ≈ a .62 team,
    ~+1.0 ≈ a .73 team."""
    return 1.0 / (1.0 + math.exp(-net / 1.0))


def power_ratings(world: World) -> List[PowerRating]:
    """One :class:`PowerRating` per team, ranked best-first."""
    priors = roster_priors(world)
    srs, opps = compute_srs(world)
    teams = world.team_list()
    gp = {t.tid: t.games_played for t in teams}

    blended: Dict[int, float] = {}
    for t in teams:
        w = gp[t.tid] / (gp[t.tid] + _RESULTS_K)
        blended[t.tid] = w * srs[t.tid] + (1 - w) * priors[t.tid]
    # Re-center the blend so the league mean is exactly 0.
    m = sum(blended.values()) / len(blended)
    blended = {tid: v - m for tid, v in blended.items()}

    out: List[PowerRating] = []
    for t in teams:
        opp = opps[t.tid]
        sos = sum(blended[o] for o in opp) / len(opp) if opp else 0.0
        out.append(PowerRating(
            tid=t.tid,
            power=blended[t.tid],
            srs=srs[t.tid],
            prior=priors[t.tid],
            sos=sos,
            proj_win_pct=_win_pct_from_net(blended[t.tid]),
        ))
    out.sort(key=lambda r: r.power, reverse=True)
    for i, r in enumerate(out, start=1):
        r.rank = i
    return out


def power_map(world: World) -> Dict[int, PowerRating]:
    return {r.tid: r for r in power_ratings(world)}


# ---------------------------------------------------------------------------
# Preseason team strength (for team selection, before any games are played)
# ---------------------------------------------------------------------------
def projected_strength(world: World) -> Dict[int, int]:
    """A single projected-rating number per team on the familiar overall (~25-99) scale: the
    goalie-weighted, star-weighted roster talent, rounded.

    Unlike :func:`power_ratings`, this needs no games played -- it's the roster-talent read used
    to rank franchises on the team-selection screen so the user knows what they're taking over."""
    return {t.tid: round(_team_talent(world, t)) for t in world.team_list()}


def strength_stars(world: World) -> Dict[int, int]:
    """1-5 stars by where each team's projected strength ranks league-wide (even quintiles).

    Rank-based so the stars always spread across the league instead of clustering -- a team is
    judged relative to its peers, not against an absolute scale."""
    talents = {t.tid: _team_talent(world, t) for t in world.team_list()}
    order = sorted(talents, key=lambda tid: talents[tid])     # weakest first
    n = len(order) or 1
    return {tid: min(5, 1 + i * 5 // n) for i, tid in enumerate(order)}
