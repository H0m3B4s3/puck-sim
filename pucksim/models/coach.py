"""Head-coach archetypes -- a team's tactical lean and in-game AI behavior.

Each team has a :class:`Coach` whose ``profile`` (a :class:`CoachProfile`, looked up by
archetype name) drives tactical/behavioral tendencies consumed by later steps: the coach's
default tactics lean (Step 2.8 extends ``tactics.py``), forecheck/special-teams aggression
(Step 2.1's strength-state engine), and -- the hockey-specific behavior HoopR's
basketball-only coach model has no analog for -- **line juggling**: how readily the coach
reshuffles forward lines/D-pairs when trailing or when combinations are running cold
(DESIGN.md's "Coach archetypes" carryover section; consumed by Step 2.8's reshuffle
trigger in ``sim/engine.py``, not by this module).

Mirrors the shape of HoopR's ``hoopsim/models/coach.py`` (148 lines): a frozen
``CoachProfile`` tendency-knob dataclass, a weighted ``ARCHETYPES`` preset table, a
``Coach`` dataclass tying an instance to an archetype by name, ``profile_for()`` lookup,
and ``assign_coach()`` weighted-random selection. Tendency *numbers* are hockey's own, not
basketball's.

Fallback behavior (explicit choice, mirrors HoopR's actual behavior): an unknown/missing
archetype name never raises -- ``profile_for()`` falls back to the ``"Balanced"`` profile,
and ``Coach.from_dict()`` does the same for a corrupted/forward-incompatible save. A bad
archetype name is a data-quality problem, not something that should crash the game.

Amended 2026-07-01 (post-Wave-3 design pass) with additional in-game system knobs
requested alongside the original tendency set: ``pp_forwards`` (3F/2D vs. 4F/1D power-play
shape), ``shot_volume``/``shot_quality_bias`` (deliberately two independent axes, not one
combined pace tradeoff -- how many shot attempts a coach's system generates vs. how much it
favors higher-quality looks over raw volume), ``defensive_risk_tolerance`` (D pinching/gap
control aggression), and ``goalie_pull_max_deficit``/``goalie_pull_time_threshold_secs``
(explicit threshold fields rather than one abstract "pull aggression" float, so Step 2.2's
pull-the-goalie mechanic doesn't have to invent the aggression-to-threshold mapping later).
All of these are still pure data -- nothing consumes them until the sim engine steps above.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from pucksim.rng import Rng

BALANCED_NAME = "Balanced"


@dataclass(frozen=True)
class CoachProfile:
    """Static tendency knobs for one coaching archetype (looked up, never mutated).

    None of these knobs are consumed yet -- the sim engine that reads them doesn't
    exist until Step 1.12/2.1/2.2/2.8 -- but they're defined now so archetypes/saves
    have a stable shape before that engine work starts. All are floats on a 0-1 scale
    unless noted otherwise:

    - ``forecheck_aggression`` -- how aggressively the team forechecks (0 = passive
      trap/contain, 1 = full aggressive pressure on the forecheck).
    - ``pp_style_aggression`` -- power-play risk-taking (0 = conservative puck
      possession/perimeter, 1 = high-risk/high-reward).
    - ``pp_forwards`` -- ``int``, either ``3`` or ``4``: how many forwards this coach
      deploys on the top power-play unit. ``3`` is the conservative 3F/2D shape
      (more D-zone/blue-line coverage if the PP breaks down); ``4`` is the aggressive
      4F/1D "overload" look (more offensive-zone bodies, thinner if it turns over).
    - ``pk_style_aggression`` -- penalty-kill pressure vs. a passive collapsed box (0 =
      passive box, 1 = aggressive pressure/gambling for turnovers).
    - ``line_juggling_patience`` -- how quickly/aggressively this coach reshuffles
      forward lines/D-pairs when trailing or when combinations are running cold. LOW
      patience (near 0) juggles readily; HIGH patience (near 1) sticks with lines
      longer. This is the hockey-specific knob DESIGN.md calls out as having no
      basketball analog.
    - ``shot_volume`` -- how many shot attempts per game this coach's system
      generates (0 = deliberate/possession-cycling, fewer attempts; 1 = high-event,
      shoot-from-anywhere/dump-and-chase chaos, many attempts). Deliberately a
      separate axis from ``shot_quality_bias`` below rather than one combined
      pace tradeoff -- a coach can in principle push both volume and quality at
      once, even if that combination is rare among the archetypes below.
    - ``shot_quality_bias`` -- how much this coach's system favors higher
      expected-goal shot attempts over just generating volume (0 = fires from
      anywhere, 1 = works for the high-danger look before shooting). Independent
      of ``shot_volume`` (see above).
    - ``defensive_risk_tolerance`` -- how aggressively defensemen pinch at the
      blue line / press the gap rather than playing it safe (0 = conservative,
      holds the line and rarely pinches; 1 = aggressive, pinches often -- raises
      both turnover-forced-the-other-way rate and got-caught-below-the-puck rate).
    - ``goalie_pull_max_deficit`` -- ``int``, the largest score deficit at which
      this coach will still consider pulling the goalie for an extra attacker
      (e.g. ``1`` = only when trailing by exactly one, ``3`` = will pull down by
      up to three).
    - ``goalie_pull_time_threshold_secs`` -- the latest amount of time remaining
      (in seconds) at which this coach starts considering the pull -- a bigger
      number means an earlier/more aggressive pull (e.g. ``170.0`` starts
      considering it with the whole final ~3 minutes to play; ``70.0`` waits
      until truly desperate, ~1 minute left).
    """

    name: str                          # archetype label, e.g. "Aggressive Forechecker"
    weight: float                      # relative frequency when assigning coaches
    forecheck_aggression: float = 0.5
    pp_style_aggression: float = 0.5
    pp_forwards: int = 3
    pk_style_aggression: float = 0.5
    line_juggling_patience: float = 0.5
    shot_volume: float = 0.5
    shot_quality_bias: float = 0.5
    defensive_risk_tolerance: float = 0.5
    goalie_pull_max_deficit: int = 2
    goalie_pull_time_threshold_secs: float = 120.0


# "Balanced" is the anchor/fallback -- moderate values on every knob. Any unknown or
# missing archetype name resolves to this profile (see profile_for()) so a bad/corrupted
# save never crashes the game.
BALANCED = CoachProfile(
    name=BALANCED_NAME,
    weight=30.0,
    forecheck_aggression=0.5,
    pp_style_aggression=0.5,
    pp_forwards=3,
    pk_style_aggression=0.5,
    line_juggling_patience=0.5,
    shot_volume=0.5,
    shot_quality_bias=0.5,
    defensive_risk_tolerance=0.5,
    goalie_pull_max_deficit=2,
    goalie_pull_time_threshold_secs=120.0,
)

ARCHETYPES: List[Tuple[CoachProfile, float]] = [
    (BALANCED, BALANCED.weight),
    (
        # High-event, high-pressure system: forechecks hard, pinches the blue
        # line, fires often (volume over quality), runs the 4F/1D PP overload,
        # and pulls the goalie early/often when trailing.
        CoachProfile(
            name="Aggressive Forechecker",
            weight=16.0,
            forecheck_aggression=0.85,
            pp_style_aggression=0.6,
            pp_forwards=4,
            pk_style_aggression=0.65,
            line_juggling_patience=0.25,
            shot_volume=0.75,
            shot_quality_bias=0.4,
            defensive_risk_tolerance=0.7,
            goalie_pull_max_deficit=3,
            goalie_pull_time_threshold_secs=150.0,
        ),
        16.0,
    ),
    (
        # Low-event, low-risk system: passive forecheck/trap, holds the blue
        # line rather than pinching, works for a good look before shooting,
        # conservative 3F/2D PP, and won't pull the goalie until truly
        # desperate.
        CoachProfile(
            name="Defensive Structure",
            weight=16.0,
            forecheck_aggression=0.2,
            pp_style_aggression=0.35,
            pp_forwards=3,
            pk_style_aggression=0.3,
            line_juggling_patience=0.8,
            shot_volume=0.35,
            shot_quality_bias=0.7,
            defensive_risk_tolerance=0.25,
            goalie_pull_max_deficit=1,
            goalie_pull_time_threshold_secs=75.0,
        ),
        16.0,
    ),
    (
        # The extreme end of every risk axis: highest shot volume, thinnest
        # shot-quality discipline, most aggressive PK pressure and D pinching,
        # 4F/1D PP, earliest/most willing goalie pull.
        CoachProfile(
            name="High-Event Gambler",
            weight=10.0,
            forecheck_aggression=0.7,
            pp_style_aggression=0.9,
            pp_forwards=4,
            pk_style_aggression=0.85,
            line_juggling_patience=0.4,
            shot_volume=0.85,
            shot_quality_bias=0.3,
            defensive_risk_tolerance=0.8,
            goalie_pull_max_deficit=3,
            goalie_pull_time_threshold_secs=170.0,
        ),
        10.0,
    ),
    (
        # Conservative in every gameplay sense; the "patience" in the name is
        # about line stability, but it pairs naturally with low-risk special
        # teams and a late/reluctant goalie pull.
        CoachProfile(
            name="Patient Bencher",
            weight=8.0,
            forecheck_aggression=0.45,
            pp_style_aggression=0.4,
            pp_forwards=3,
            pk_style_aggression=0.4,
            line_juggling_patience=0.95,
            shot_volume=0.4,
            shot_quality_bias=0.65,
            defensive_risk_tolerance=0.3,
            goalie_pull_max_deficit=1,
            goalie_pull_time_threshold_secs=70.0,
        ),
        8.0,
    ),
    (
        # Defined by the line-juggling extreme, not by risk tolerance -- kept
        # near Balanced on every other axis so its one standout trait (near-0
        # patience) stays legible in testing/AI behavior.
        CoachProfile(
            name="Line Blender",
            weight=8.0,
            forecheck_aggression=0.55,
            pp_style_aggression=0.55,
            pp_forwards=3,
            pk_style_aggression=0.5,
            line_juggling_patience=0.1,
            shot_volume=0.55,
            shot_quality_bias=0.5,
            defensive_risk_tolerance=0.5,
            goalie_pull_max_deficit=2,
            goalie_pull_time_threshold_secs=120.0,
        ),
        8.0,
    ),
]

# Name -> profile lookup table, derived from ARCHETYPES (single source of truth).
_ARCHETYPES_BY_NAME = {profile.name: profile for profile, _weight in ARCHETYPES}


def profile_for(archetype_name: str) -> CoachProfile:
    """Look up a :class:`CoachProfile` by archetype name.

    Falls back to the ``Balanced`` profile for an unknown/missing name rather than
    raising -- a bad or stale archetype name (e.g. from an older save after archetypes
    are rebalanced) shouldn't crash the game.
    """
    return _ARCHETYPES_BY_NAME.get(archetype_name, BALANCED)


@dataclass
class Coach:
    """A team's head coach: identity plus a reference to a named archetype profile."""

    cid: int
    name: str                # the person's name, e.g. "Coach 7" -- real namegen is later
    profile: CoachProfile

    def to_dict(self) -> dict:
        return {
            "cid": self.cid,
            "name": self.name,
            "archetype": self.profile.name,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Coach":
        return cls(
            cid=d["cid"],
            name=d.get("name", f"Coach {d['cid']}"),
            profile=profile_for(d.get("archetype", BALANCED_NAME)),
        )


def assign_coach(cid: int, rng: Rng) -> Coach:
    """Pick a weighted-random archetype and construct a :class:`Coach` instance.

    ``rng`` is a :class:`pucksim.rng.Rng` (its ``weighted_one`` draws one item from a
    population using parallel weights, matching HoopR's ``assign_coach()`` pattern).
    """
    profiles = [profile for profile, _weight in ARCHETYPES]
    weights = [weight for _profile, weight in ARCHETYPES]
    chosen = rng.weighted_one(profiles, weights)
    return Coach(cid=cid, name=f"Coach {cid}", profile=chosen)
