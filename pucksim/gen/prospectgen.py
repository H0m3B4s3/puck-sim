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
from pucksim.models.contract import Contract
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

# ...but NOT uniformly across it. A real draft class is overwhelmingly 18-year-olds: that's
# the first year of eligibility, and a player who makes it to a second or third one is by
# definition somebody the league already passed over. Weights are a rough read of a real
# class's age composition.
#
# This is not cosmetic, and drawing uniformly (as this did originally) quietly broke the
# development system in two places. A prospect drafted at 20 or 21 has almost no runway --
# he reaches PROSPECT_STAGNATION_AGE within a season or two and starts losing ceiling
# before he's had a chance to use it -- and he skips junior entirely, since the CHL tier
# ends at 19. Measured over ten simulated seasons, undrafted players were exiting the
# development system at a median age of 24 having entered college at 20, with their
# potential already ground down. The age curves can't do their job if nobody arrives young
# enough to ride them.
_PROSPECT_AGE_WEIGHTS = (
    (18, 0.72),
    (19, 0.18),
    (20, 0.07),
    (21, 0.03),
)

# How many prospects a single draft class generates. Real NHL drafts run
# 7 rounds x 32 teams = 224 selections, but not every draft-eligible player in
# the world gets simulated -- only the ones who plausibly get picked need to
# exist. DEVPLAN.md doesn't specify a class size; sized here to comfortably
# exceed a plausible round count (see draft_system.py's DRAFT_ROUNDS) with
# real depth-of-talent falloff, so late picks are still meaningfully weaker
# than early ones rather than the pool running dry. PROVISIONAL/TUNABLE,
# flagged as a judgment call in this step's report.
#
# THIS IS ALSO THE KNOB THAT SETS HOW BIG THE UNDRAFTED POOL IS. ``_effective_rounds`` clamps
# the draft to ``pool_size // num_teams`` rounds, so pool and pick count scale together and
# roughly 85% of every class gets drafted at any size below ~260. Only a pool well clear of a
# full 7-round draft (224 picks) leaves a real undrafted class for the UDFA pathway to draw
# from -- at 150 the draft was actually only FOUR rounds, so nearly every credible player was
# drafted and the domestic undrafted route delivered ~0-1 NHL players a decade.
#
# Raised to 260 (2026-07-23 follow-up round) to make that route deliver real players. At 260
# the draft runs its full 7 rounds (260 // 32 = 8, clamped to DRAFT_ROUNDS), leaving ~36
# undrafted a year, and the domestic UDFA route now delivers a handful of NHL players per
# decade instead of almost none. The cost, measured and accepted: world population runs ~25%
# higher (~1500 vs ~1200), the offseason takes roughly twice as long, and the share of the
# league on entry-level deals rises to ~10-14% -- because a full draft has teams signing seven
# picks a year rather than four. That ELC share is if anything MORE realistic (real NHL rosters
# carry a comparable entry-level presence), and the economy bands / regression thresholds in
# test_econ_balance.py were widened to match after an 8-seed x 12-season sweep confirmed it.
PROSPECT_POOL_SIZE = 260

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
    """A draft-eligible age, weighted toward 18 (see ``_PROSPECT_AGE_WEIGHTS``)."""
    return rng.weighted_one([age for age, _ in _PROSPECT_AGE_WEIGHTS],
                             [w for _, w in _PROSPECT_AGE_WEIGHTS])


def _random_prospect_target_overall(rng: Rng) -> int:
    value = rng.gauss(_PROSPECT_OVERALL_MU, _PROSPECT_OVERALL_SIGMA)
    return int(round(max(_PROSPECT_OVERALL_FLOOR, min(90, value))))


# Production floors and the defenceman adjustment for `production_line` below.
_MIN_PER_GAME = 0.04          # ~2-3 points over a full junior season, not zero
_D_GOAL_SHARE = 0.30
_D_ASSIST_SHARE = 0.75


def production_line(rng: Rng, player: Player, level: str, games: int,
                     difficulty: float = 1.0) -> Dict:
    """A plausible season stat line for ``player`` at ``level``, inferred from his ratings.

    Flavor only -- like HoopR's equivalent, this is generated *from* already-rolled ratings
    purely for display; nothing reads it back into generation, pick order, or development
    (``prospect_rank()`` uses overall/scouted_potential directly, the same signal the engine
    itself trusts). It exists so a prospect's season is something you can look at rather
    than a rating quietly ticking up in the dark.

    ``difficulty`` scales production down for tougher competition: the formulas below are
    calibrated to major junior at 1.0, so the AHL (where a junior star's point totals fall
    off a cliff) passes something much lower. See ``TIER_STAT_LINE``.
    """
    r = player.ratings
    if player.is_goalie:
        # Save pct/GAA inferred from goalie ratings on a junior-hockey-plausible scale (a
        # bit softer competition than the NHL, so save pct runs a little higher / GAA a
        # little lower than typical NHL numbers for an equivalently-rated goalie). Harder
        # competition cuts both ways here, unlike a skater's counting stats: it pushes save
        # percentage down and goals-against up.
        reflexes = r.get("reflexes", 60)
        positioning = r.get("positioning", 60)
        edge = (reflexes + positioning - 120) * difficulty
        save_pct = 0.895 + edge * 0.0009 + rng.gauss(0, 0.006)
        gaa = 3.4 - edge * 0.012 + rng.gauss(0, 0.25)
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
    # Defencemen score far less than forwards at every level, and get proportionally more of
    # what they do produce from assists. Without this a 62-overall college defenceman was
    # posting 14 goals in 25 games, which is a Hobey Baker season, not a depth prospect's.
    goal_share, assist_share = (_D_GOAL_SHARE, _D_ASSIST_SHARE) if player.position == "D" else (1.0, 1.0)
    ppg = (0.35 + (scoring - 55) * 0.018 + rng.gauss(0, 0.10)) * difficulty * goal_share
    apg = (0.30 + (playmaking - 55) * 0.020 + rng.gauss(0, 0.10)) * difficulty * assist_share
    # Floored at a small positive rate rather than zero. The linear formula goes negative
    # for a low-rated player, and a junior forward who finishes a 58-game season with
    # literally 0 goals and 0 assists reads as broken data rather than as a weak prospect --
    # even the last man on a junior roster scores a few.
    goals = max(_MIN_PER_GAME, ppg) * games
    assists = max(_MIN_PER_GAME, apg) * games
    return {
        "level": level,
        "gp": games,
        "g": round(goals, 1),
        "a": round(assists, 1),
        "pts": round(goals + assists, 1),
    }


# Per-tier season shape for a developing prospect: (display label, games, difficulty).
# Games are real season lengths -- college's ~36 against junior's ~68 is a genuine
# difference and part of why college develops more slowly. Difficulty is relative to major
# junior at 1.0: an AHL season is where a junior scoring star's point totals collapse,
# which is the single most recognizable fact about the step up to pro. PROVISIONAL.
TIER_STAT_LINE = {
    "chl": ("CHL", 68, 1.00),
    "ncaa": ("NCAA", 36, 0.85),
    "ahl": ("AHL", 72, 0.62),
    "europe": ("Europe", 52, 0.78),
}


def development_season_line(rng: Rng, player: Player, tier: str) -> Dict:
    """One season's synthetic stat line for a prospect developing in ``tier``.

    Called once per prospect per offseason by ``systems/prospects.py`` and stored on his
    development record, so the UI can show what he actually did this year instead of only
    that his overall moved.
    """
    level, games, difficulty = TIER_STAT_LINE.get(tier, ("Junior", 60, 0.9))
    played = max(1, int(round(games * rng.uniform(0.55, 1.0))))   # injuries, healthy scratches
    return production_line(rng, player, level, played, difficulty)


def _pre_draft_bio(rng: Rng, player: Player) -> Dict:
    """The pre-draft scouting line: one season's production at the level he came up in."""
    level = rng.weighted_one([lv for lv, _ in _PRE_DRAFT_LEVELS],
                              [w for _, w in _PRE_DRAFT_LEVELS])
    return production_line(rng, player, level, rng.randint(28, 68))


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

    # playergen prices a contract onto every player it makes, because its main caller
    # (leaguegen) is building an already-running league where everyone is signed. A draft
    # prospect is the exception: he is unsigned by definition, and this function's contract
    # has always said so ("no team/contract assigned yet") without it actually being true.
    #
    # Not cosmetic -- it silently disabled the entry-level system. Arriving under contract
    # meant `prospects.is_elc_eligible` refused him (you can't sign a player who's already
    # signed), so no prospect could ever be given a real ELC, nothing ever slid, and the
    # AHL's "you must be under professional contract to turn pro" gate opened for free on a
    # $800k deal nobody agreed to. Measured after one offseason: 77 teenaged prospects
    # holding one- and two-year minimum contracts with a signed_year of 0.
    player.contract = Contract.free_agent()
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


# ---------------------------------------------------------------------------
# International free agents (docs/PROSPECT_DEV_PLAN.md -- the second pathway in)
# ---------------------------------------------------------------------------
# The KHL/SHL import route: a European pro who was never drafted, developed at home
# instead, and arrives already grown. Real, and a real transaction type -- teams sign these
# players outright, with no draft rights and no entry-level scale, which makes them a
# genuinely different kind of acquisition from a prospect or a domestic free agent.
#
# Ages start above PROSPECT_AGE_RANGE deliberately: these are finished products, not
# prospects. A 22-27-year-old is past the development system entirely (see
# config.MAX_PROSPECT_AGE), so he goes straight onto the free-agent market.
INTERNATIONAL_FA_AGE_RANGE = (22, 27)

# Ability distribution. Centered a little BELOW leaguegen's own _OVERALL_MU (66.0) with a
# wider spread: most imports are useful depth, a few are genuinely good, and the tail is
# what makes checking the market each summer worth doing. Not a source of free stars --
# they're priced at market rate by `cap.market_salary` like any other free agent, so a
# good one costs what he's worth. PROVISIONAL/TUNABLE.
_IMPORT_OVERALL_MU = 63.0
_IMPORT_OVERALL_SIGMA = 7.0

# How many arrive each offseason. Small on purpose: this is a side door into the league,
# not a parallel draft.
INTERNATIONAL_FA_PER_SEASON = 8


def generate_international_free_agent(pid: int, rng: Rng, position: str = None) -> Player:
    """One European pro entering the league as an unrestricted free agent.

    Same generation pipeline as everyone else (``playergen``), differing only in age band,
    ability distribution, and ``league_origin``. Returns with ``team_id=None`` and no
    development record -- he is not a prospect, he is a free agent, and callers register
    him with ``World.add_player`` like any other.
    """
    age = rng.randint(*INTERNATIONAL_FA_AGE_RANGE)
    target = int(round(max(40, min(90, rng.gauss(_IMPORT_OVERALL_MU, _IMPORT_OVERALL_SIGMA)))))

    if position == "G":
        player = generate_goalie(pid, rng, age, target)
    else:
        player = generate_skater(pid, rng, age, target, position=position)

    player.league_origin = "europe"
    return player


def generate_international_free_agents(rng: Rng, new_pid,
                                        count: int = INTERNATIONAL_FA_PER_SEASON
                                        ) -> List[Player]:
    """A season's worth of imports. Goalie share matches the draft pool's."""
    players: List[Player] = []
    n_goalies = 1 if rng.chance(count * PROSPECT_GOALIE_FRACTION) else 0
    for _ in range(n_goalies):
        players.append(generate_international_free_agent(new_pid(), rng, position="G"))
    for i in range(count - n_goalies):
        position = SKATER_POSITIONS[i % len(SKATER_POSITIONS)]
        players.append(generate_international_free_agent(new_pid(), rng, position=position))
    rng.shuffle(players)
    return players
