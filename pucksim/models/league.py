"""League-level structures: phases, scheduled games, and standings logic.

Standings math design note (Step 1.8): unlike HoopR's basketball-only ``league.py``
(a simple win_pct sort), hockey standings are **rule-parameterized** -- three
selectable presets live in ``config.STANDINGS_RULES`` (see that file's docstring
for the exact point tables). This module never hardcodes point values; it always
reads them from ``config.STANDINGS_RULES[rule]``.

Where do accumulated points/goal-diff live? ``Team`` (models/team.py) already has a
*simplified* 3-bucket win/loss/ot_loss counter plus a ``streak`` field, used for a
quick ``record_str`` display and populated via ``Team.record_result()``. That model
cannot represent everything standings math needs: it doesn't distinguish an OT loss
from a shootout loss, doesn't have a "tie" bucket (relevant only under "retro"), and
carries no goals-for/against totals for tiebreaking. Rather than bolt all of that
onto ``Team`` (which would mean extending/duplicating state that a later step,
world.py/season.py, may still want in its current simple shape for the scoreboard),
``standings()`` in this module is **pure and stateless**: it replays the full list of
played ``Game`` objects into local per-team-id accumulator dicts (points, wins,
goals-for, goals-against) every time it's called, and never mutates ``Team`` fields.
This keeps the function trivially testable (hand-build some games, call standings())
and avoids fighting Team's existing simplified counters, which remain valid for
their own narrower purpose (e.g. a scoreboard "record" string) untouched by this
module. ``Team`` is not modified by this step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from pucksim.config import STANDINGS_RULES
from pucksim.models.team import Team


class Phase:
    """Ordered phases of a season. Stored as plain strings for JSON friendliness."""

    PRESEASON = "preseason"
    REGULAR_SEASON = "regular_season"
    PLAYOFFS = "playoffs"
    DRAFT = "draft"
    FREE_AGENCY = "free_agency"
    OFFSEASON = "offseason"

    ORDER: List[str] = [
        PRESEASON, REGULAR_SEASON, PLAYOFFS, DRAFT, FREE_AGENCY, OFFSEASON,
    ]

    LABELS = {
        PRESEASON: "Preseason",
        REGULAR_SEASON: "Regular Season",
        PLAYOFFS: "Playoffs",
        DRAFT: "Draft",
        FREE_AGENCY: "Free Agency",
        OFFSEASON: "Offseason",
    }

    @classmethod
    def label(cls, phase: str) -> str:
        return cls.LABELS.get(phase, phase.title())

    @classmethod
    def next(cls, current: str) -> str:
        """Advance to the next phase in ``ORDER``, wrapping around to the start.

        Mirrors HoopR's phase-machine shape (a season is a repeating cycle:
        preseason -> regular season -> playoffs -> draft -> free agency ->
        offseason -> back to preseason for the next year), so callers don't need
        special-case "end of list" handling -- advancing past OFFSEASON simply
        starts the next season's PRESEASON.
        """
        idx = cls.ORDER.index(current)
        return cls.ORDER[(idx + 1) % len(cls.ORDER)]


@dataclass
class Game:
    gid: int
    day: int                       # integer game-day index within the season
    home: int                      # home team id
    away: int                      # away team id
    home_score: int = 0
    away_score: int = 0
    played: bool = False
    is_playoff: bool = False
    series_id: Optional[str] = None
    # Hockey-specific resolution flags (DEVPLAN.md Step 1.8): how the game ended,
    # needed by points_for_game() to pick the right column out of
    # config.STANDINGS_RULES. At most one of these should be True for a given
    # game; a regulation decision has both False.
    went_ot: bool = False
    went_so: bool = False          # shootout

    @property
    def winner(self) -> Optional[int]:
        """Winning team id, or ``None`` if unplayed or the game is a tie.

        A tie is legal only under the "retro" standings rule (no OT/SO):
        ``is_tie`` covers that case and both ``winner``/``loser`` return
        ``None`` for it, same as an unplayed game.
        """
        if not self.played or self.is_tie:
            return None
        return self.home if self.home_score > self.away_score else self.away

    @property
    def loser(self) -> Optional[int]:
        """Losing team id, mirrors ``winner`` (``None`` if unplayed or a tie)."""
        if not self.played or self.is_tie:
            return None
        return self.away if self.home_score > self.away_score else self.home

    @property
    def is_tie(self) -> bool:
        """True if the game ended level and no shootout occurred.

        Corrected 2026-07-01 (Step 1.13 integration): earlier revisions of this property also
        required ``not went_ot``, on the assumption that overtime always ends with a decisive
        goal. DESIGN.md point 8 says otherwise: regular-season OT is a single sudden-death period
        played *regardless* of standings rule -- "Retro" just skips the shootout that would
        normally follow an undecided OT. So a legitimate tie can absolutely have ``went_ot=True``
        (OT was played and didn't produce a goal); what actually rules out a tie is a shootout
        occurring (``went_so``), since a shootout by construction always ends decisively. Only
        reachable in practice under the "retro" standings rule (config.STANDINGS_RULES["retro"]),
        since "standard"/"three_two_one_zero" always carry the game to a shootout if OT doesn't
        decide it -- but this property itself doesn't enforce that; it's purely a description of
        the recorded scoreline/flags.
        """
        return self.played and self.home_score == self.away_score and not self.went_so

    def involves(self, tid: int) -> bool:
        return self.home == tid or self.away == tid

    def opponent_of(self, tid: int) -> int:
        return self.away if self.home == tid else self.home

    def to_dict(self) -> dict:
        return {
            "gid": self.gid, "day": self.day, "home": self.home, "away": self.away,
            "home_score": self.home_score, "away_score": self.away_score,
            "played": self.played, "is_playoff": self.is_playoff, "series_id": self.series_id,
            "went_ot": self.went_ot, "went_so": self.went_so,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Game":
        return cls(
            gid=d["gid"], day=d["day"], home=d["home"], away=d["away"],
            home_score=d.get("home_score", 0), away_score=d.get("away_score", 0),
            played=d.get("played", False), is_playoff=d.get("is_playoff", False),
            series_id=d.get("series_id"),
            went_ot=d.get("went_ot", False), went_so=d.get("went_so", False),
        )


# ---------------------------------------------------------------------------
# Standings math -- parameterized by rule (DEVPLAN.md Step 1.8's core new work).
# ---------------------------------------------------------------------------
def points_for_game(rule: str, team_id: int, game: Game) -> int:
    """Standings points earned by ``team_id`` for one played ``game``, under ``rule``.

    ``rule`` is a key into ``config.STANDINGS_RULES`` ("standard"/"retro"/
    "three_two_one_zero"); the point values themselves are never hardcoded here --
    they're read straight out of that dict, which is the single source of truth
    (see config.py's module comment for the exact tables).

    Outcome resolution, in order:
      - tie (only possible under "retro"): both teams get ``rule["tie"]``.
      - shootout decision (``went_so``): winner gets ``so_win``, loser ``so_loss``.
      - OT decision (``went_ot``, not ``went_so``): winner gets ``ot_win``, loser
        ``ot_loss``.
      - regulation decision (neither flag set): winner gets ``reg_win``, loser
        ``reg_loss``.

    Data-integrity guard: a game with ``went_so=True`` under a rule whose
    ``has_shootout`` is False (i.e. "retro") should be structurally unreachable --
    the season/OT-resolution logic (a later step) is responsible for never
    producing such a game while "retro" is the active rule. If one somehow shows
    up here anyway, this raises ``ValueError`` rather than silently returning a
    wrong/undefined point value, since ``rule["so_win"]``/``rule["so_loss"]`` are
    literally ``None`` in that preset (see config.STANDINGS_RULES["retro"]).
    """
    if not game.played:
        raise ValueError(f"points_for_game() called on an unplayed game (gid={game.gid})")
    if not game.involves(team_id):
        raise ValueError(f"team {team_id} is not part of game {game.gid}")

    rule_table = STANDINGS_RULES[rule]

    if game.is_tie:
        points = rule_table["tie"]
        if points is None:
            raise ValueError(
                f"game {game.gid} is a tie but rule {rule!r} has no 'tie' points defined"
            )
        return points

    if game.went_so:
        if not rule_table["has_shootout"]:
            # Data-integrity situation: a shootout-flagged game under a rule that
            # doesn't use shootouts (currently only "retro"). This should never
            # be reachable if upstream OT/SO resolution respects the active
            # rule -- raise loudly instead of guessing.
            raise ValueError(
                f"game {game.gid} has went_so=True but rule {rule!r} has "
                f"has_shootout=False -- data-integrity violation"
            )
        outcome_key = "so_win" if game.winner == team_id else "so_loss"
    elif game.went_ot:
        outcome_key = "ot_win" if game.winner == team_id else "ot_loss"
    else:
        outcome_key = "reg_win" if game.winner == team_id else "reg_loss"

    points = rule_table[outcome_key]
    if points is None:
        raise ValueError(
            f"rule {rule!r} has no points defined for outcome {outcome_key!r} "
            f"(game {game.gid})"
        )
    return points


@dataclass
class _Accumulator:
    points: int = 0
    wins: int = 0
    goals_for: int = 0
    goals_against: int = 0


def _build_accumulators(teams: List[Team], games: List[Game], rule: str) -> Dict[int, _Accumulator]:
    accum: Dict[int, _Accumulator] = {team.tid: _Accumulator() for team in teams}
    for game in games:
        if not game.played:
            continue
        for tid in (game.home, game.away):
            if tid not in accum:
                # Game references a team not in the provided list -- skip rather
                # than error, so standings() can be called with a subset of teams
                # (e.g. one conference) alongside the full game list.
                continue
            acc = accum[tid]
            acc.points += points_for_game(rule, tid, game)
            if game.winner == tid:
                acc.wins += 1
            if tid == game.home:
                acc.goals_for += game.home_score
                acc.goals_against += game.away_score
            else:
                acc.goals_for += game.away_score
                acc.goals_against += game.home_score
    return accum


def standings(teams: List[Team], games: List[Game], rule: str) -> List[Team]:
    """Order ``teams`` by accumulated standings points under ``rule``.

    Points/wins/goal-differential are computed by replaying ``games`` (only the
    ones with ``played=True``) through ``points_for_game()`` into local
    accumulator dicts -- see this module's docstring for why this is done
    statelessly rather than by mutating ``Team`` fields.

    Tiebreaker chain (descending points, then descending wins, then descending
    goal differential, then ascending team id as a final stable tiebreaker):
    this exact chain is **provisional/unspecified by DESIGN.md** -- DEVPLAN.md
    flags the tiebreaker chain as "provisional" for this step. Real NHL
    tiebreakers (games played, ROW, head-to-head, etc.) are more elaborate and
    can replace this later without changing this function's signature.
    """
    accum = _build_accumulators(teams, games, rule)

    def sort_key(team: Team):
        acc = accum.get(team.tid, _Accumulator())
        goal_diff = acc.goals_for - acc.goals_against
        # Sort descending on points/wins/goal_diff, ascending on tid -- negate
        # the "higher is better" fields so a single ascending sort does it all.
        return (-acc.points, -acc.wins, -goal_diff, team.tid)

    return sorted(teams, key=sort_key)


def conference_standings(teams: List[Team], games: List[Game], rule: str) -> Dict[str, List[Team]]:
    """Group ``standings()`` results by ``team.conference``."""
    ordered = standings(teams, games, rule)
    result: Dict[str, List[Team]] = {}
    for team in ordered:
        result.setdefault(team.conference, []).append(team)
    return result
