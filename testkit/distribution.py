"""League-wide statistical distribution measurement -- the calibration instrument for the sim.

Why this exists (2026-07-24): playtesting surfaced that PuckSim's *team*-level scoring was already
right (~6.3 goals/game combined, squarely NHL-realistic) while every layer underneath it was not.
A full 32-team season on seed 7 produced a league goal leader with 82 goals -- a DEFENSEMAN -- off
13.5 shots on goal per team per game (NHL: ~30) converting at 23.3% (NHL: ~10%). Nothing in the
codebase measured any of that, which is exactly why it survived this long: ``run_season.py``
printed standings, a top-10 scorer list and goalie save percentages, none of which look wrong when
the underlying event budget is half of real and the conversion rate is double.

So this module is deliberately a *library*, not a print function bolted onto the harness:

  * ``measure(world)`` turns a finished season into a :class:`LeagueDistribution` of ~20 scalars.
  * ``TARGETS`` records the NHL reference band for each of those scalars, in one place.
  * ``format_report()`` renders the two together with an explicit PASS/FAIL per row.

``testkit/run_season.py`` calls all three to print a report; ``tests/test_distribution.py`` calls
the first two to assert the bands. Keeping the metric math in one place means the number a test
asserts is definitionally the number the harness printed -- there is no second implementation to
drift.

Everything here is READ-ONLY over a finished ``World``. It computes from data the sim already
records (``Player.season``, ``World.game_results``, ``Team.lines``/``pairs``) and adds no counters
to the engine.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from pucksim.models.world import World

# ---------------------------------------------------------------------------
# NHL reference bands
# ---------------------------------------------------------------------------
# Each entry is (low, high) INCLUSIVE, expressed per-82-games where the metric is a season total.
# Sourced from recent (2022-2024) NHL league-wide rates, deliberately given as bands rather than
# points: the goal is "does a simulated league look like a hockey league", not "does it reproduce
# one specific season". Bands are wide enough that ordinary seed-to-seed variance passes and narrow
# enough that a structural bug fails.
#
# PROVISIONAL only in the sense that the bands can be argued with -- they are NOT placeholders like
# the engine's first-pass tuning constants. If a band moves, that is a deliberate statement about
# what this sim is trying to be, and it belongs in docs/DISTRIBUTION_TARGETS.md alongside the
# reasoning, not quietly widened to make a failing run pass.
TARGETS: Dict[str, Tuple[float, float]] = {
    # -- team-level rates: the invariant this whole calibration round must preserve ----------
    # Widened from an initial (6.0, 6.4) on 2026-07-24 after measuring the sim's own seed-to-seed
    # spread: four full seasons on a correctly-calibrated engine produced 5.91 / 6.12 / 6.34 / 6.37,
    # a mean of 6.19 with a range of +/-0.23. The original band was narrower than that spread, so it
    # would have failed roughly a quarter of runs for no reason other than which league got
    # generated. This is a band matching measured variance, NOT a band loosened to let a failing
    # calibration through -- the center is unchanged and real NHL seasons vary at least this much.
    "goals_per_game": (5.85, 6.45),
    # -- event budget -----------------------------------------------------------------------
    "sog_per_team_game": (28.0, 32.0),
    "corsi_per_team_game": (50.0, 60.0),
    "pct_team_games_under_15_sog": (0.0, 3.0),
    "shooting_pct": (9.5, 10.8),
    "save_pct": (0.893, 0.908),
    # -- credit distribution ----------------------------------------------------------------
    "assists_per_goal": (1.62, 1.76),
    "d_goal_share_pct": (11.0, 16.0),
    # -- individual leaderboard shape -------------------------------------------------------
    "goal_leader": (50, 66),
    "point_leader": (100, 135),
    "skaters_ge_50_goals": (0, 6),
    "skaters_ge_40_goals": (6, 18),
    "skaters_ge_30_goals": (28, 48),
    "skaters_ge_20_goals": (90, 125),
    # -- deployment -------------------------------------------------------------------------
    "toi_f1_min": (18.0, 20.0),
    "toi_f4_min": (10.0, 12.0),
    "toi_d1_min": (23.0, 25.0),
    "toi_d3_min": (15.0, 17.0),
}

# Metrics worth printing but not worth failing a build over -- context for reading the ones above,
# not targets in their own right (median goals depends heavily on how many 13th forwards a league
# carries, and the leader's shot share is a diagnostic for WHY the goal leader is where he is).
_UNBANDED = (
    "median_skater_goals",
    "top_shooter_shot_share_pct",
    "sog_stdev_per_team_game",
)

_LABELS: Dict[str, str] = {
    "goals_per_game": "goals/game (combined)",
    "sog_per_team_game": "SOG / team / game",
    "corsi_per_team_game": "Corsi / team / game",
    "pct_team_games_under_15_sog": "team-games under 15 SOG (%)",
    "shooting_pct": "league shooting %",
    "save_pct": "league save %",
    "assists_per_goal": "assists per goal",
    "d_goal_share_pct": "D share of all goals (%)",
    "goal_leader": "goal leader",
    "point_leader": "point leader",
    "skaters_ge_50_goals": "skaters >= 50 goals",
    "skaters_ge_40_goals": "skaters >= 40 goals",
    "skaters_ge_30_goals": "skaters >= 30 goals",
    "skaters_ge_20_goals": "skaters >= 20 goals",
    "toi_f1_min": "TOI: 1st line F (min)",
    "toi_f4_min": "TOI: 4th line F (min)",
    "toi_d1_min": "TOI: 1st pair D (min)",
    "toi_d3_min": "TOI: 3rd pair D (min)",
    "median_skater_goals": "median skater goals",
    "top_shooter_shot_share_pct": "leader's share of team SOG (%)",
    "sog_stdev_per_team_game": "SOG / team / game (stdev)",
}

# Corsi is credited to every skater on the ice for an attempt, so summing ``corsi_for`` across a
# league counts each attempt once per attacking skater. Dividing by 5 recovers the attempt count.
# Slightly understates during a pulled-goalie 6-skater shift (a handful of attempts per season,
# far below the resolution of the band above) -- documented rather than special-cased.
_SKATERS_ON_ICE = 5


@dataclass
class LeagueDistribution:
    """Every measured scalar for one finished season. Field names match ``TARGETS`` keys."""

    goals_per_game: float = 0.0
    sog_per_team_game: float = 0.0
    sog_stdev_per_team_game: float = 0.0
    pct_team_games_under_15_sog: float = 0.0
    corsi_per_team_game: float = 0.0
    shooting_pct: float = 0.0
    save_pct: float = 0.0
    assists_per_goal: float = 0.0
    d_goal_share_pct: float = 0.0
    goal_leader: int = 0
    point_leader: int = 0
    skaters_ge_50_goals: int = 0
    skaters_ge_40_goals: int = 0
    skaters_ge_30_goals: int = 0
    skaters_ge_20_goals: int = 0
    median_skater_goals: float = 0.0
    top_shooter_shot_share_pct: float = 0.0
    toi_f1_min: float = 0.0
    toi_f4_min: float = 0.0
    toi_d1_min: float = 0.0
    toi_d3_min: float = 0.0

    # Context, not metrics: printed in the header so a report is self-describing.
    games_played: int = 0
    skaters_counted: int = 0
    # (name, position, g, a, points) for the top few, so the report shows WHO, not just how many.
    goal_leaders: List[tuple] = field(default_factory=list)

    def value(self, key: str) -> float:
        return getattr(self, key)

    def in_band(self, key: str) -> Optional[bool]:
        """True/False against ``TARGETS[key]``, or None for an unbanded diagnostic metric."""
        band = TARGETS.get(key)
        if band is None:
            return None
        lo, hi = band
        return lo <= getattr(self, key) <= hi

    def failures(self) -> List[str]:
        """Keys whose measured value falls outside their target band."""
        return [k for k in TARGETS if not self.in_band(k)]


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------
def measure(world: World) -> LeagueDistribution:
    """Compute the full distribution for ``world``'s just-finished regular season.

    Reads ``Player.season`` (season totals), ``World.game_results`` (per-game box scores, needed
    for the shots-on-goal *spread* -- season totals can't tell you whether a 27-shot average came
    from consistent 27s or from alternating 9s and 45s) and ``Team.lines``/``Team.pairs`` (to
    attribute ice time to a deployment slot). Safe to call on a partially-played season; every
    rate divides defensively.
    """
    dist = LeagueDistribution()

    games = [g for g in world.schedule if g.played]
    dist.games_played = len(games)
    if not games:
        return dist

    skaters = [p for p in world.players.values()
               if not p.is_goalie and p.season is not None and p.season.gp > 0]
    dist.skaters_counted = len(skaters)
    if not skaters:
        return dist

    team_games = len(games) * 2

    # -- team-level ------------------------------------------------------------------------
    dist.goals_per_game = sum(g.home_score + g.away_score for g in games) / len(games)

    total_goals = sum(p.season.g for p in skaters)
    total_assists = sum(p.season.a for p in skaters)
    total_sog = sum(p.season.sog for p in skaters)
    total_corsi = sum(p.season.corsi_for for p in skaters)

    dist.sog_per_team_game = total_sog / team_games
    dist.corsi_per_team_game = total_corsi / _SKATERS_ON_ICE / team_games
    if total_sog:
        dist.shooting_pct = 100.0 * total_goals / total_sog
    if total_goals:
        dist.assists_per_goal = total_assists / total_goals

    goalies = [p for p in world.players.values()
               if p.is_goalie and p.season is not None and p.season.shots_faced > 0]
    faced = sum(p.season.shots_faced for p in goalies)
    if faced:
        dist.save_pct = sum(p.season.saves for p in goalies) / faced

    d_goals = sum(p.season.g for p in skaters if p.position == "D")
    if total_goals:
        dist.d_goal_share_pct = 100.0 * d_goals / total_goals

    # -- per-game shot spread --------------------------------------------------------------
    per_team_game_sog = _per_team_game_sog(world, games)
    if per_team_game_sog:
        dist.sog_per_team_game = statistics.fmean(per_team_game_sog)
        if len(per_team_game_sog) > 1:
            dist.sog_stdev_per_team_game = statistics.stdev(per_team_game_sog)
        under = sum(1 for s in per_team_game_sog if s < 15)
        dist.pct_team_games_under_15_sog = 100.0 * under / len(per_team_game_sog)

    # -- leaderboard shape ------------------------------------------------------------------
    goals = sorted((p.season.g for p in skaters), reverse=True)
    dist.goal_leader = goals[0]
    dist.median_skater_goals = statistics.median(goals)
    dist.skaters_ge_50_goals = sum(1 for g in goals if g >= 50)
    dist.skaters_ge_40_goals = sum(1 for g in goals if g >= 40)
    dist.skaters_ge_30_goals = sum(1 for g in goals if g >= 30)
    dist.skaters_ge_20_goals = sum(1 for g in goals if g >= 20)
    dist.point_leader = max(p.season.points for p in skaters)

    by_goals = sorted(skaters, key=lambda p: (p.season.g, p.season.points), reverse=True)
    dist.goal_leaders = [
        (p.name, p.position, p.season.g, p.season.a, p.season.points, p.season.sog)
        for p in by_goals[:5]
    ]

    # Why the goal leader is where he is: a leader taking 22% of his team's shots is a
    # shooter-selection problem; one taking 13% with an absurd conversion rate is a save-percentage
    # problem. This single number separates those two diagnoses at a glance.
    top_shooter = max(skaters, key=lambda p: p.season.sog)
    if top_shooter.team_id is not None:
        team_sog = sum(p.season.sog for p in skaters if p.team_id == top_shooter.team_id)
        if team_sog:
            dist.top_shooter_shot_share_pct = 100.0 * top_shooter.season.sog / team_sog

    # -- deployment -------------------------------------------------------------------------
    toi = _toi_by_slot(world)
    dist.toi_f1_min = toi.get("F1", 0.0)
    dist.toi_f4_min = toi.get("F4", 0.0)
    dist.toi_d1_min = toi.get("D1", 0.0)
    dist.toi_d3_min = toi.get("D3", 0.0)
    return dist


def _per_team_game_sog(world: World, games) -> List[int]:
    """One SOG total per team per played game, from ``world.game_results`` box scores.

    ``game_results`` keys skater box lines by pid across BOTH teams, so each line is attributed
    back to a side via the player's current ``team_id``. A player traded mid-season would have his
    earlier games attributed to his new club; that shifts a handful of shots between two teams in
    a 1312-game season and cannot move a league-wide mean or stdev meaningfully, so it's accepted
    rather than reconstructed from roster history.
    """
    totals: List[int] = []
    for game in games:
        record = world.game_results.get(game.gid)
        if not record:
            continue
        home = away = 0
        for pid, line in record.get("skater_box", {}).items():
            player = world.players.get(int(pid))
            if player is None:
                continue
            sog = line.get("sog", 0)
            if player.team_id == game.home:
                home += sog
            elif player.team_id == game.away:
                away += sog
        totals.append(home)
        totals.append(away)
    return totals


_FORWARD_POSITIONS = ("LW", "C", "RW")


def _toi_by_slot(world: World) -> Dict[str, float]:
    """Mean per-game ice time in MINUTES for each deployment tier (F1-F4, D1-D3).

    Tiers are assigned by RANKING each team's skaters on actual per-game ice time -- top 3 forwards
    are "F1", next 3 "F2", and so on; top 2 defensemen are "D1". It deliberately does NOT read
    ``Team.lines``/``Team.pairs``.

    Reading the line chart looks more direct and is wrong over a full season, because the coach
    line-juggling AI mutates ``team.lines`` as the season goes (measured: ~34 reshuffles per team
    per season, and 31 of 32 teams had changed their lines within the first 20 days). Attributing a
    player's whole-season ice time to whatever slot he happens to occupy in game 82 averages his
    time across every slot he passed through, which compresses the measured spread toward flat and
    hides exactly the thing this metric exists to detect. Ranking is invariant to that: a player who
    got first-line minutes all year is a first-liner no matter where the chart currently lists him.

    Not circular, despite ranking on the quantity being measured. The question is not "who is on
    line 1" but "how much more does a team's most-used forward trio play than its least-used" --
    a spread, which a flat rotation still fails (every tier converges on the same value) and a
    weighted one still passes.
    """
    buckets: Dict[str, List[float]] = {}
    for team in world.team_list():
        forwards, defensemen = [], []
        for pid in team.roster:
            player = world.players.get(pid)
            if player is None or player.season is None or player.season.gp == 0:
                continue
            toi = player.season.secs / player.season.gp / 60.0
            if player.position in _FORWARD_POSITIONS:
                forwards.append(toi)
            elif player.position == "D":
                defensemen.append(toi)
        forwards.sort(reverse=True)
        defensemen.sort(reverse=True)
        for tier in range(4):
            group = forwards[tier * 3:tier * 3 + 3]
            if group:
                buckets.setdefault(f"F{tier + 1}", []).extend(group)
        for tier in range(3):
            group = defensemen[tier * 2:tier * 2 + 2]
            if group:
                buckets.setdefault(f"D{tier + 1}", []).extend(group)
    return {slot: statistics.fmean(vals) for slot, vals in buckets.items() if vals}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _fmt(key: str, value: float) -> str:
    if key == "save_pct":
        return f"{value:.3f}"
    if isinstance(value, int) or key.startswith("skaters_ge") or key.endswith("leader"):
        return f"{value:.0f}"
    return f"{value:.2f}"


def _fmt_band(key: str) -> str:
    band = TARGETS.get(key)
    if band is None:
        return "--"
    lo, hi = band
    if key == "save_pct":
        return f"{lo:.3f} - {hi:.3f}"
    if float(lo).is_integer() and float(hi).is_integer():
        return f"{lo:.0f} - {hi:.0f}"
    # Two decimals, not one: the assists-per-goal band (1.62 - 1.76) rounds to a visibly wrong
    # "1.6 - 1.8" at one decimal, which reads as a much looser target than it is.
    return f"{lo:.2f} - {hi:.2f}"


def format_report(dist: LeagueDistribution, title: str = "League distribution") -> str:
    """Render ``dist`` as a fixed-width table with a PASS/FAIL marker per banded metric."""
    lines: List[str] = []
    lines.append("")
    lines.append(title)
    lines.append("=" * len(title))
    lines.append(f"({dist.games_played} games, {dist.skaters_counted} skaters with GP > 0)")
    lines.append("")

    if dist.goal_leaders:
        lines.append("Goal leaders")
        lines.append(f"  {'Name':<24}{'Pos':<5}{'G':>4}{'A':>4}{'P':>5}{'SOG':>6}")
        for name, pos, g, a, pts, sog in dist.goal_leaders:
            lines.append(f"  {name:<24}{pos:<5}{g:>4}{a:>4}{pts:>5}{sog:>6}")
        lines.append("")

    header = f"{'Metric':<32}{'Actual':>10}{'Target':>16}{'':>8}"
    lines.append(header)
    lines.append("-" * len(header))

    for key in list(TARGETS) + list(_UNBANDED):
        label = _LABELS.get(key, key)
        actual = _fmt(key, dist.value(key))
        band = _fmt_band(key)
        ok = dist.in_band(key)
        marker = "" if ok is None else ("  PASS" if ok else "  FAIL")
        lines.append(f"{label:<32}{actual:>10}{band:>16}{marker:>8}")

    failures = dist.failures()
    lines.append("-" * len(header))
    if failures:
        lines.append(f"{len(failures)} of {len(TARGETS)} metrics outside target band.")
    else:
        lines.append(f"All {len(TARGETS)} metrics within target band.")
    return "\n".join(lines)
