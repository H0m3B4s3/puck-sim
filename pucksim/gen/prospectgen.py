"""Draft-prospect generation -- a thin wrapper around gen/playergen.py.

DEVPLAN.md Step 2.5 explicitly leaves the choice open between extending
``playergen.py`` directly or adding a "thin wrapper" module around it. This file
takes the wrapper path: ``generate_skater``/``generate_goalie`` (Step 1.11)
already implement the entire archetype-driven generation pipeline (position/
archetype choice, baseline-then-skew-then-calibrate ratings, potential curve,
scout_error, handedness) that a draft prospect needs -- a prospect is not a
structurally different kind of player, just a player who (a) is draft-age, (b)
has a ``pre_draft`` scouting bio populated instead of already sitting on an NHL
roster, and (c) has no team/contract assigned yet. None of that warrants
duplicating playergen.py's generation logic; it only warrants a layer on top
that calls into it and adds the draft-specific bio/age framing.

Why a wrapper file instead of teaching playergen.py itself about drafts: keeps
playergen.py's job singular ("generate one archetype-shaped Player at an age/
target overall") and keeps draft-specific concerns (age band, pre_draft bio
shape, league_origin) colocated with the rest of the draft system rather than
mixed into the general-purpose generator that leaguegen.py also depends on for
building initial rosters.

Pre-draft bio shape (loosely ports HoopR's ``scouting.py``-adjacent
``_pre_draft_stats`` pattern from ``hoopsim/systems/draft_system.py`` --
HoopR generates a plausible per-game production line inferred from ratings,
purely as flavor for the scouting screen, not consumed by engine logic).
PuckSim's version is a hockey-shaped equivalent (goals/assists/points-per-game
instead of basketball's ppg/rpg/apg, a CHL/NCAA/USHL/international "level"
label). The production numbers themselves stay flavor-only -- inferred from
ratings, never fed back into generation or pick order -- but as of the prospect
development round (docs/PROSPECT_DEV_PLAN.md) the LEVEL is no longer flavor: it
sets ``Player.league_origin``, which decides which development tiers the player
is eligible for once he's drafted.
"""
from __future__ import annotations

from typing import Dict, List

from pucksim.config import DEFAULT_LEAGUE_ORIGIN, ROOKIE_AGE_RANGE
from pucksim.gen.playergen import generate_goalie, generate_skater
from pucksim.models.attributes import SKATER_POSITIONS
from pucksim.models.player import Player
from pucksim.rng import Rng

# Draft-eligible age band. DEVPLAN.md doesn't pin an exact range for v1 (no
# real CHL/NCAA/European junior-hockey eligibility rules exist yet -- that's
# the Phase 2 fork this step's league_origin field is a hook for). Real NHL
# draft eligibility is "turns 18 by Sept 15 of the draft year, or is 19-20 and
# has not yet been drafted" -- reusing config.ROOKIE_AGE_RANGE (18-21, already
# defined for Step 1.1's rookie-contract framing) as the prospect age band is
# a reasonable low-risk default that keeps one age-band constant doing double
# duty instead of inventing a second, narrower one. JUDGMENT CALL, flagged.
PROSPECT_AGE_RANGE = ROOKIE_AGE_RANGE

# How many prospects a single draft class generates. Real NHL drafts run
# 7 rounds x 32 teams = 224 selections, but not every draft-eligible player in
# the world gets simulated -- only the ones who plausibly get picked need to
# exist. DEVPLAN.md doesn't specify a class size; sized here to comfortably
# exceed a plausible round count (see draft_system.py's DRAFT_ROUNDS) with
# real depth-of-talent falloff, so late picks are still meaningfully weaker
# than early ones rather than the pool running dry. PROVISIONAL/TUNABLE,
# flagged as a judgment call in this step's report.
PROSPECT_POOL_SIZE = 150

# Fraction of the generated pool that are goalies vs. skaters. Real NHL draft
# classes run a bit lighter on goalies than an NHL roster's ~13% goalie share
# (teams draft goalies more conservatively -- goalie development is notoriously
# unpredictable), so this undershoots roster composition slightly.
# PROVISIONAL/TUNABLE.
PROSPECT_GOALIE_FRACTION = 0.10

# Target-overall distribution for the *current-ability* half of a prospect
# (potential is generated separately by playergen's own _potential() curve,
# which already skews young players toward a much higher ceiling than their
# current overall -- see that function's docstring). Prospects are, by
# construction, rawer than an average established NHL player: this sits well
# below leaguegen.py's own _OVERALL_MU (66.0) for full-roster generation, on
# the theory that an 18-21-year-old's *current* NHL-equivalent ability is
# typically below the league-average veteran even for a future star (their
# potential curve is what makes them draftable, not their current level).
# PROVISIONAL/TUNABLE.
_PROSPECT_OVERALL_MU = 52.0
_PROSPECT_OVERALL_SIGMA = 9.0
_PROSPECT_OVERALL_FLOOR = 30

# Pre-draft "level" flavor label pool + weights. Started life as pure flavor text
# (HoopR's own _PRE_DRAFT_LEVELS pattern) but is no longer inert: the prospect
# development round (docs/PROSPECT_DEV_PLAN.md) derives each prospect's
# ``league_origin`` from the level he was generated at, which then decides which
# development tiers he is eligible for. Weights are a rough read of a real NHL draft
# class's composition. PROVISIONAL/TUNABLE.
_PRE_DRAFT_LEVELS = (
    ("CHL", 0.40),
    ("NCAA", 0.28),
    ("USHL", 0.12),
    ("International", 0.14),
    ("High School / Prep", 0.06),
)

# Pre-draft level -> config.LEAGUE_ORIGIN_CHOICES. Only the CHL fork really matters
# mechanically (major junior permanently forfeits NCAA eligibility, and bars the AHL
# before 20), so the three US amateur routes all collapse onto the same "ncaa" origin:
# a USHL or prep player is on the college track by construction -- developing him is
# the USHL's entire purpose -- and neither is barred from anything the NCAA isn't.
_ORIGIN_BY_LEVEL = {
    "CHL": "chl",
    "NCAA": "ncaa",
    "USHL": "ncaa",
    "High School / Prep": "ncaa",
    "International": "europe",
}


def _random_prospect_age(rng: Rng) -> int:
    lo, hi = PROSPECT_AGE_RANGE
    return rng.randint(lo, hi)


def _random_prospect_target_overall(rng: Rng) -> int:
    value = rng.gauss(_PROSPECT_OVERALL_MU, _PROSPECT_OVERALL_SIGMA)
    return int(round(max(_PROSPECT_OVERALL_FLOOR, min(90, value))))


def _pre_draft_bio(rng: Rng, player: Player) -> Dict:
    """A plausible pre-draft per-game production line, inferred from ratings.

    Flavor only -- like HoopR's equivalent, this is generated *from* the
    player's already-rolled ratings purely for a scouting-report display; it
    is never read back into generation or pick-order logic (prospect_rank()
    below reads overall/scouted_potential directly, the same signal the
    engine itself trusts).
    """
    r = player.ratings
    is_goalie = player.is_goalie
    games = rng.randint(28, 68)
    level = rng.weighted_one([lv for lv, _ in _PRE_DRAFT_LEVELS],
                              [w for _, w in _PRE_DRAFT_LEVELS])
    if is_goalie:
        # Goalie bio: save pct/GAA inferred from goalie ratings, on a
        # junior/college-hockey-plausible scale (a bit softer competition
        # than the NHL, so save pct runs a little higher / GAA a little
        # lower than typical NHL numbers for an equivalently-rated goalie).
        reflexes = r.get("reflexes", 60)
        positioning = r.get("positioning", 60)
        save_pct = 0.895 + (reflexes + positioning - 120) * 0.0009 + rng.gauss(0, 0.006)
        gaa = 3.4 - (reflexes + positioning - 120) * 0.012 + rng.gauss(0, 0.25)
        return {
            "level": level,
            "gp": games,
            "save_pct": round(min(0.945, max(0.870, save_pct)), 3),
            "gaa": round(min(4.5, max(1.6, gaa)), 2),
        }

    shot_accuracy = r.get("shot_accuracy", 60)
    playmaking = r.get("playmaking", 60)
    puck_handling = r.get("puck_handling", 60)
    scoring = 0.55 * shot_accuracy + 0.45 * puck_handling
    ppg = 0.35 + (scoring - 55) * 0.018 + rng.gauss(0, 0.10)
    apg = 0.30 + (playmaking - 55) * 0.020 + rng.gauss(0, 0.10)
    goals = max(0, ppg) * games
    assists = max(0, apg) * games
    return {
        "level": level,
        "gp": games,
        "g": round(goals, 1),
        "a": round(assists, 1),
        "pts": round(goals + assists, 1),
    }


def generate_prospect(pid: int, rng: Rng, position: str = None) -> Player:
    """Generate one draft-eligible prospect Player.

    Delegates entirely to ``playergen.generate_skater``/``generate_goalie`` for
    ratings/archetype/potential/scout_error (no duplicated generation logic --
    see module docstring), then layers on the draft-specific bits: a
    draft-age (``PROSPECT_AGE_RANGE``), a lower-than-veteran target current
    overall (prospects are unfinished products), a populated ``pre_draft`` bio,
    and a ``league_origin`` derived from that bio's level. Returns with
    ``team_id=None`` (undrafted) -- callers must go through
    ``freeagency.sign_rookie``/``World.sign_player`` once a team actually
    drafts this prospect, never assign a team directly.
    """
    age = _random_prospect_age(rng)
    target_overall = _random_prospect_target_overall(rng)

    if position == "G":
        player = generate_goalie(pid, rng, age, target_overall)
    else:
        player = generate_skater(pid, rng, age, target_overall, position=position)

    player.pre_draft = _pre_draft_bio(rng, player)
    # Origin follows the level the bio just rolled, so the two can never disagree --
    # a prospect whose scouting report reads "CHL" is a major-junior player for
    # eligibility purposes too (see _ORIGIN_BY_LEVEL).
    player.league_origin = _ORIGIN_BY_LEVEL.get(player.pre_draft["level"],
                                                 DEFAULT_LEAGUE_ORIGIN)
    return player


def generate_prospect_pool(rng: Rng, new_pid, size: int = PROSPECT_POOL_SIZE) -> List[Player]:
    """Generate a full draft class's worth of undrafted prospects.

    ``new_pid`` is a zero-arg callable (typically ``World.new_pid``) so id
    allocation stays centralized on World, matching every other generator in
    this codebase (leaguegen.py's ``_build_roster`` follows the same
    ``world.new_pid()``-per-player pattern). Goalies are drawn at
    ``PROSPECT_GOALIE_FRACTION`` of the pool (rounded), skaters fill the rest
    across ``SKATER_POSITIONS`` evenly via playergen's own random-position
    fallback. Callers are responsible for registering the returned players
    onto ``World`` (``World.add_player`` -- this function does not touch World
    itself, keeping it a pure generator like playergen.py's functions).
    """
    n_goalies = max(1, round(size * PROSPECT_GOALIE_FRACTION))
    n_skaters = size - n_goalies

    prospects: List[Player] = []
    for _ in range(n_goalies):
        prospects.append(generate_prospect(new_pid(), rng, position="G"))
    for i in range(n_skaters):
        position = SKATER_POSITIONS[i % len(SKATER_POSITIONS)]
        prospects.append(generate_prospect(new_pid(), rng, position=position))

    rng.shuffle(prospects)
    return prospects
