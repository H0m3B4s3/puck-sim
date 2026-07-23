"""Offseason player development and aging -- PLUS a goalie season-form mechanic that is
NOT aging, and must never be confused with it. Read the second section of this docstring
carefully before touching either mechanism.

Structural precedent: HoopR's ``hoopsim/systems/development.py`` (73 lines: ``_overall_delta()``
age curve + ``_apply_delta()`` skill-bucket application, ``develop_player()``/``develop_all()``
orchestration). PuckSim ports the *shape*, not the numbers: young players climb toward their
potential (faster with ice time and work ethic), players in their prime plateau, veterans decline
-- losing physical tools first while keeping their hockey sense (mirrors HoopR's own "athleticism
fades first, IQ holds" framing, ported to skating/reflexes-vs-awareness instead of basketball's
athleticism/vertical-vs-IQ split). Runs once per offseason for every player in the league.

Age-curve shape (JUDGMENT CALL -- DEVPLAN.md hands this module ``config.PEAK_AGE_LOW``/
``PEAK_AGE_HIGH``/``RETIREMENT_AGE`` as INPUTS but does not specify an exact growth/decline
formula; HoopR's own curve is basketball-shaped and not a drop-in port for hockey's slightly
earlier peak / slightly longer tail):
  - Below ``PEAK_AGE_LOW`` (24): still climbing toward potential -- the growth rate itself
    tapers as the player approaches ``PEAK_AGE_LOW`` (a 19-year-old grows faster than a
    23-year-old, even though both are pre-peak), mirroring how real prospects' development
    curves are steepest right after entering the league and flatten as they approach their peak.
  - ``PEAK_AGE_LOW``..``PEAK_AGE_HIGH`` (24-29): plateau -- small symmetric noise around zero,
    no systematic drift either way (a player can still have a career year or a down year at 26,
    but the league-wide mean at this age band doesn't drift).
  - Above ``PEAK_AGE_HIGH``: decline, accelerating with age and steepening further past
    ``RETIREMENT_AGE - 5`` (a 38-year-old fades faster than a 30-year-old) -- this is what
    eventually makes ``age_and_retire``-equivalent logic (Step 2.7's ``offseason.py``) find
    players worth retiring by ``RETIREMENT_AGE``.
Growth is conserved league-wide, same principle as HoopR's own comment: the only reliable
source of positive movement is an unmet gap to potential; every other term is symmetric churn
centered at (or below) zero, so the league-wide overall mean doesn't quietly drift upward
forever as more offseasons run.

WHERE A PLAYER PLAYS, NOT JUST HOW OLD HE IS (docs/PROSPECT_DEV_PLAN.md)
=======================================================================
The pre-peak growth rate is scaled by how much developmental opportunity the player
actually got -- ``_opportunity_factor`` below. For a young NHL regular that's ice time,
which is HoopR's own rule ported over. For a prospect there is no NHL ice time to read, so
his development TIER stands in for it (``config.TIER_DEVELOPMENT``): the AHL develops best,
junior gives big minutes against weak competition, college is slowest by games played,
Europe lands mid-pack.

That distinction is the whole mechanical content of the tier system, and it was missing
until the prospect development round: a prospect's ``Player.season`` is empty because he
never played an NHL game, so the ice-time formula divided into a zero and handed every
prospect in the league the same flat 0.6. Read ``_opportunity_factor``'s docstring before
touching it -- the failure mode is silent, and it makes four carefully specified tiers
behave identically.

Prospects also lose potential when they stall (``_is_stagnating``), which is what lets a
bust actually bust rather than carrying an unrealized ceiling to age 25.

===========================================================================================
GOALIE SEASON-TO-YEAR "FORM" VARIANCE -- READ THIS BEFORE CHANGING ANYTHING GOALIE-RELATED
===========================================================================================
DEVPLAN.md Step 2.7's "Goalie year-to-year consistency" design note is implemented here as
``resample_goalie_form()``/``apply_goalie_form()``, called once per goalie per offseason
transition from ``develop_all()`` below (AFTER the permanent age-based ``_overall_delta`` has
already been applied). This is a SEPARATE mechanism from aging, layered on top of it:

  - ``_overall_delta``/``_apply_delta`` (above) are PERMANENT: they mutate ``player.ratings``
    itself, exactly like real aging -- a decline at 34 doesn't un-happen at 35.
  - Goalie "form" is TEMPORARY and RESAMPLED EVERY SEASON: it lives in a separate,
    non-``ratings`` field (``Player.season`` has no natural home for it either, since it must
    exist and be sampled BEFORE any games are played that season -- see ``GoalieForm`` below
    for exactly where this state lives and why) and is thrown away and re-rolled fresh at the
    next offseason transition. A bust or breakout season must NOT permanently drag the
    goalie's true ``ratings`` dict up or down -- ``ratings["reflexes"]``/etc. are completely
    untouched by this mechanism; only a separate multiplicative "form" scalar changes.

WHY THIS EXISTS (real hockey, and why gk_consistency is the right knob): real NHL goalies are
dramatically less year-to-year-consistent than skaters. A handful of true elite goalies
(contemporary examples: Vasilevskiy/Shesterkin/Hellebuyck-caliber -- not necessarily Vezina
winners every year, but reliably good-to-very-good EVERY year) stay tightly banded near their
true talent level season after season. Below that thin elite tier is a much larger "squishy
middle" where a goalie can post a breakout year, a down year, or a flatly average year almost
unpredictably, with no way to tell in advance which one is coming. ``attributes.py``'s
``gk_consistency`` rating (already a 0.10-weighted GOALIE_WEIGHTS skill component, i.e. it was
already part of a goalie's *overall* before this step) is repurposed here to ALSO drive this
season-to-season output *variance*: high ``gk_consistency`` -> a tight, elite-tier form spread
that stays close to 1.0 (their game rarely deviates far from their established rating); low
``gk_consistency`` -> a wide spread that can swing to a real breakout or a real bust. This does
not change what ``gk_consistency`` means as a skill rating (it's still weighted into
``overall()`` exactly as before) -- it now ALSO independently drives a temporary variance term
downstream of that overall, which is a new and separate use of the same underlying rating, not
a contradiction of its existing one.

*** THE SINGLE MOST IMPORTANT THING TO GET RIGHT IN THIS MODULE ***
This project has an established, hard "no upweighting" principle (see this session's
``[[feedback_no_upweighting]]`` memory and DEVPLAN.md Phase 2's intro material): realization
mechanics (morale/clutch/hot-hand -- see ``sim/ratings.py``'s ``morale_realization()``/
``clutch_realization()`` and ``sim/goalies.py``'s in-game hot-hand model) must NEVER let a
player exceed their rating ceiling on any single in-game shot/shift/save. That principle
governs DETERMINISTIC, WITHIN-A-SINGLE-GAME realization scaling -- it exists so a player's
rating stays a true, un-exceedable ceiling for what that player can do on any one play, no
matter how hot a streak or how confident their morale.

Goalie season-form variance is NOT that mechanism, is NOT governed by that principle, and must
NEVER be "fixed" to comply with it (e.g. by capping form at 1.0, or by making it one-directional
only-downside/only-upside). The two are different phenomena serving different purposes:
  - No-upweighting (in-game realization): deterministic, asymmetric-by-design (a ceiling, not a
    distribution), scoped to a single game's shot/shift resolution.
  - Season form (this module): probabilistic, SYMMETRIC natural statistical scatter around an
    unchanging true talent level, scoped to an entire season's aggregate output, resampled fresh
    every offseason. A goalie's rating is their TRUE TALENT LEVEL, not a hard ceiling they play
    at every night -- real athletes have good years and bad years around their true level, and
    that scatter can legitimately land above their "true" rating in a given season just as
    easily as below it. Capping this at 1.0 (never letting a season exceed the established
    rating) or making it one-directional would be a real bug: it would silently convert a
    legitimate "natural variance around a fixed mean" mechanic into a disguised violation of
    conservation (the league-wide goalie population would trend toward its ceiling every season,
    exactly the kind of systematic upward drift this codebase's other systems -- see
    ``_overall_delta``'s own "growth is conserved league-wide" comment just above -- are
    carefully designed to avoid).
So: symmetric, mean-preserving, resampled-not-accumulated, and completely untouched by the
in-game no-upweighting ceiling. If you are a future reader tempted to "fix" this into a
one-directional or capped-at-1.0 mechanic because it looks superficially like a no-upweighting
violation, you would be re-introducing the exact bug this docstring exists to prevent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from pucksim.config import (
    DEV_TIER_AHL,
    NHL_READY_OVERALL,
    PEAK_AGE_HIGH,
    PEAK_AGE_LOW,
    PROSPECT_STAGNATION_AGE,
    PROSPECT_STAGNATION_POTENTIAL_LOSS,
    RETIREMENT_AGE,
    TIER_DEVELOPMENT,
    TIER_DEVELOPMENT_DEFAULT,
    TIER_FIRST_SEASON_PENALTY,
)
from pucksim.models.attributes import ALL_GOALIE_RATINGS, RATING_GROUPS, clamp_rating
from pucksim.models.player import Player
from pucksim.models.world import World

_PHYSICAL = set(RATING_GROUPS["Physical"])                 # skating, agility, strength, stamina
_IQ = {"offensive_awareness", "defensive_awareness", "composure"}  # holds up longest with age

# All skater ratings this module can nudge (goalies use ALL_GOALIE_RATINGS instead -- see
# _apply_delta's dispatch below).
_SKATER_SKILL_RATINGS = [r for group in RATING_GROUPS.values() for r in group]


# ---------------------------------------------------------------------------
# Permanent age-based development curve
# ---------------------------------------------------------------------------
def _opportunity_factor(player: Player) -> float:
    """How much developmental opportunity this young player actually got this season.

    Two populations, one scale (roughly 0.6-1.4). A player on an NHL roster is scored on
    his ice time, which is HoopR's own rule ported: a prospect buried in a limited role
    develops slower than one getting real minutes. A player in a feeder tier has no NHL ice
    time to read, so his TIER is the proxy -- see ``config.TIER_DEVELOPMENT`` for the
    ordering and its reasoning.

    THE BUG THIS FIXES, because it is easy to reintroduce: this function used to be the
    ice-time branch alone, and a prospect's ``Player.season`` is empty (he never played an
    NHL game), so ``gp == 0``, ``mpg == 0.0``, and the factor collapsed to a flat 0.6 for
    EVERY prospect in the league. Age, tier, ice time, role -- none of it mattered. The
    development tiers can be as carefully specified as you like; this is the line that
    decides whether they mean anything.
    """
    if player.is_prospect:
        from pucksim.systems.prospects import current_tier, seasons_in_tier

        tier = current_tier(player)
        factor = TIER_DEVELOPMENT.get(tier, TIER_DEVELOPMENT_DEFAULT)
        if tier == DEV_TIER_AHL and seasons_in_tier(player) == 0:
            factor *= TIER_FIRST_SEASON_PENALTY
        return factor

    gp = player.season.gp if player.season else 0
    secs = player.season.secs if player.season else 0
    mpg = (secs / 60.0 / gp) if gp else 0.0
    return 0.6 + min(1.0, mpg / 16.0) * 0.8


def _overall_delta(player: Player, rng) -> float:
    """Expected overall-rating change this offseason, before per-rating distribution.

    See module docstring's "Age-curve shape" section for the reasoning behind each band's
    magnitude -- PROVISIONAL/TUNABLE (DEVPLAN.md hands this module PEAK_AGE_LOW/PEAK_AGE_HIGH/
    RETIREMENT_AGE as inputs but does not pin an exact formula; this is that judgment call).
    """
    gap = player.potential - player.overall
    age = player.age

    if age < PEAK_AGE_LOW:
        # Growth rate tapers the closer a player already is to the peak-age window --
        # earliest post-entry seasons grow fastest, easing off approaching PEAK_AGE_LOW.
        years_from_peak = max(1, PEAK_AGE_LOW - age)
        pace = min(0.34, 0.14 + 0.03 * years_from_peak)
        growth = gap * rng.uniform(pace * 0.6, pace) + rng.gauss(-0.2, 1.0)
    elif age <= PEAK_AGE_HIGH:
        # Plateau: small symmetric noise, no systematic drift either way.
        growth = rng.gauss(0.0, 1.1)
    else:
        years_past_peak = age - PEAK_AGE_HIGH
        # Decline accelerates with age, steepening further inside the last 5 years before
        # RETIREMENT_AGE (a 38-year-old fades noticeably faster than a 30-year-old).
        base_decline = -0.55 * years_past_peak
        if age >= RETIREMENT_AGE - 5:
            base_decline *= 1.6
        growth = rng.gauss(base_decline, 1.2 + 0.1 * years_past_peak)

    # Playing time accelerates growth for young players still climbing (mirrors HoopR:
    # a prospect buried in a limited role develops slower than one getting real minutes).
    if age < PEAK_AGE_LOW and growth > 0:
        growth *= _opportunity_factor(player)

    growth += (player.ratings.get("work_ethic", 70) - 70) * 0.015
    return growth


def _apply_delta(player: Player, delta: float, rng) -> None:
    """Distribute ``delta`` across every rating this player's position uses.

    Skaters lose athleticism-adjacent ratings first while decline; goalies (no Physical/Mental
    rating groups of their own -- see ALL_GOALIE_RATINGS) get a simpler uniform application,
    since goalie ratings don't cleanly split into a "physical fades first" vs. "IQ holds"
    dichotomy the way skater ratings do (there is no separate goalie IQ rating to protect).
    """
    skill_ratings = ALL_GOALIE_RATINGS if player.is_goalie else _SKATER_SKILL_RATINGS
    for skill in skill_ratings:
        if delta < 0:
            if (not player.is_goalie) and skill in _IQ:
                change = rng.gauss(0.25, 0.5)          # veterans keep their hockey sense longest
            elif (not player.is_goalie) and skill in _PHYSICAL:
                change = delta * 1.5 + rng.gauss(0, 1.1)   # athleticism/skating fades first
            else:
                change = delta * 0.9 + rng.gauss(0, 1.1)
        else:
            change = delta + rng.gauss(0, 1.0)
        player.ratings[skill] = clamp_rating(player.ratings.get(skill, 25) + change)


def develop_player(player: Player, rng) -> int:
    """Permanently age/develop one player's true ``ratings``; return the overall change.

    Does NOT touch goalie season-form (see ``resample_goalie_form`` below, called separately
    from ``develop_all``) -- this function is the permanent-change half only.
    """
    before = player.overall
    delta = _overall_delta(player, rng)
    _apply_delta(player, delta, rng)
    # Potential converges toward overall as a player ages out of the growth window, same
    # "don't let unrealized ceilings linger forever" logic as HoopR's own version.
    if player.age >= PEAK_AGE_LOW + 1 and player.potential > player.overall:
        player.potential = max(player.overall, player.potential - rng.randint(1, 3))
    elif _is_stagnating(player):
        lo, hi = PROSPECT_STAGNATION_POTENTIAL_LOSS
        player.potential = max(player.overall, player.potential - rng.randint(lo, hi))
    player.potential = max(player.potential, player.overall)
    return player.overall - before


def _is_stagnating(player: Player) -> bool:
    """Is this prospect old enough, and far enough behind, that his ceiling should fall?

    Busts have to be able to bust. The convergence rule above only starts at
    ``PEAK_AGE_LOW + 1`` (25), which is far too late to mean anything to a prospect -- a
    19-year-old with 85 potential kept every point of it until he was 25, so no prospect
    ever stopped being a prospect who might still make it, and a team's read on its own
    system never got worse. From ``config.PROSPECT_STAGNATION_AGE`` a player still in the
    development system and still short of NHL caliber starts losing ceiling every year.

    Downward-only, so this can't disturb the league-wide conservation ``_overall_delta``
    depends on (growth's only source is an unmet gap to potential -- this shrinks that gap,
    it never creates one).
    """
    return (player.is_prospect
            and player.age >= PROSPECT_STAGNATION_AGE
            and player.overall < NHL_READY_OVERALL
            and player.potential > player.overall)


# ---------------------------------------------------------------------------
# Goalie season-form variance (temporary, resampled every offseason -- see module docstring)
# ---------------------------------------------------------------------------
# Where this state lives, and why NOT on Player/ratings (a real design decision, flagged):
# a permanent Player field would need save-schema changes and would tempt a future reader into
# treating it as part of the player's permanent record (exactly what this mechanic must NOT be).
# Instead it's a small, explicit, serializable-if-needed container (GoalieFormState) that a
# caller (offseason.py) owns and threads alongside World -- mirroring sim/goalies.py's own
# GoalieRestState precedent (transient per-run tracking that doesn't belong in the permanent
# save schema) as closely as this different use case allows. Unlike GoalieRestState, this DOES
# need to persist across a save/reload within a season (a goalie's form for the CURRENT season
# must stay the same all season, not re-roll every time the save is loaded) -- so callers that
# care about save-persistence should serialize ``GoalieFormState.form`` alongside their own save
# data if they need it to survive a reload mid-season; ``systems/offseason.py`` in this codebase
# only calls this at the offseason boundary (a fresh resample every year regardless), so it does
# not itself need cross-reload persistence -- documented here for any future caller that might.
FORM_BASELINE = 1.0   # a goalie playing exactly at their established true-talent level

# Spread (std dev of the multiplicative form scalar) at the two ends of the gk_consistency
# scale (25-99, see config.RATING_MIN/MAX). PROVISIONAL/TUNABLE magnitudes -- no real save-
# percentage year-to-year variance data exists to fit against yet; chosen so:
#   - a maxed-out (99) gk_consistency goalie's form rarely strays outside roughly
#     [0.94, 1.06] (a tight, "reliably themselves every year" band matching the
#     Vasilevskiy/Shesterkin/Hellebuyck framing), and
#   - a minimum (25) gk_consistency goalie's form can plausibly swing as wide as roughly
#     [0.75, 1.25] (a real breakout or bust season), matching the "squishy middle" framing.
# Linearly interpolated by gk_consistency between these two anchors (see _form_spread below)
# -- inversely proportional to consistency, i.e. HIGH gk_consistency -> LOW spread.
_FORM_SPREAD_AT_MAX_CONSISTENCY = 0.020
_FORM_SPREAD_AT_MIN_CONSISTENCY = 0.085

# Symmetric clamp band so an extreme roll can't produce an absurd (e.g. negative or 3x)
# season -- generous enough to rarely bind for a low-consistency goalie's legitimate bust/
# breakout tail, tight enough to rule out nonsensical outputs. Centered on FORM_BASELINE, i.e.
# genuinely symmetric (see module docstring -- this must never become a one-sided cap).
FORM_MIN, FORM_MAX = 0.60, 1.40


def _form_spread(gk_consistency: int) -> float:
    """Std dev of the form roll for a goalie with this ``gk_consistency`` rating.

    Linear interpolation between the two anchor spreads above, inversely proportional to
    consistency (25 -> widest spread, 99 -> tightest). Ratings outside [25, 99] (shouldn't
    happen -- clamp_rating enforces this everywhere ratings are written) are clamped first
    defensively.
    """
    from pucksim.config import RATING_MAX, RATING_MIN
    c = max(RATING_MIN, min(RATING_MAX, gk_consistency))
    frac = (c - RATING_MIN) / (RATING_MAX - RATING_MIN)   # 0.0 (min) .. 1.0 (max)
    return (_FORM_SPREAD_AT_MIN_CONSISTENCY
            + frac * (_FORM_SPREAD_AT_MAX_CONSISTENCY - _FORM_SPREAD_AT_MIN_CONSISTENCY))


@dataclass
class GoalieFormState:
    """Transient, per-run tracker of each goalie's current-season "form" multiplier.

    Owned by whichever caller drives the offseason transition (``systems/offseason.py``'s
    ``archive_season``/``pre_draft`` equivalent -- see that module); NOT part of ``World``'s
    permanent schema (see module docstring's "where this state lives" note above). A caller
    that wants this to survive a save/reload mid-season should serialize ``form`` itself
    alongside its own save data.
    """

    form: Dict[int, float] = field(default_factory=dict)

    def get(self, pid: int) -> float:
        """Current form multiplier for ``pid``, or ``FORM_BASELINE`` if never resampled
        (e.g. a goalie who has never been through an offseason transition yet -- a rookie's
        debut season plays at their straight established rating, no form applied)."""
        return self.form.get(pid, FORM_BASELINE)


def resample_goalie_form(player: Player, rng) -> float:
    """Roll a fresh symmetric "form" multiplier for one goalie's UPCOMING season.

    Pure function of the goalie's current ``gk_consistency`` rating (read fresh every call --
    since aging can itself slowly move gk_consistency over a long career, a goalie's form
    spread can narrow or widen over time as their true consistency rating changes, same as
    any other rating-driven mechanic in this codebase). Symmetric Gaussian centered on
    FORM_BASELINE (1.0), clamped to [FORM_MIN, FORM_MAX] -- see module docstring for why this
    must stay symmetric and must NOT be capped at/below 1.0.

    Callers apply the returned value via ``apply_goalie_form`` (below) wherever goalie-facing
    save-probability math wants a form-adjusted rating; this function only produces the number.
    """
    consistency = player.ratings.get("gk_consistency", 70)
    spread = _form_spread(consistency)
    form = rng.gauss(FORM_BASELINE, spread)
    return max(FORM_MIN, min(FORM_MAX, form))


def resample_all_goalie_form(world: World, form_state: GoalieFormState) -> None:
    """Resample every rostered/free-agent goalie's form for the upcoming season in place."""
    for player in world.players.values():
        if player.is_goalie:
            form_state.form[player.pid] = resample_goalie_form(player, world.rng)


def apply_goalie_form(rating_value: float, player: Player, form_state: GoalieFormState) -> float:
    """Scale a single goalie rating value by their current season's form multiplier.

    This is the ONE function downstream save-probability/skill-gap math should call to fold
    season form into a goalie's effective rating for THIS season -- callers should never read
    ``GoalieFormState.form`` directly and apply it themselves, so this stays the single place
    the "temporary, multiplicative, symmetric, not clamped to <=1.0" contract is enforced.
    Deliberately does NOT clamp the result to [RATING_MIN, RATING_MAX] -- callers that feed
    this into a probability/gap formula already have their own clamping at that boundary
    (see e.g. sim/ratings.py's realization functions), and clamping here too would silently
    reintroduce a ceiling this mechanic must not have.
    """
    return rating_value * form_state.get(player.pid)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def develop_all(world: World, form_state: GoalieFormState = None) -> None:
    """Permanently age/develop every player in the league one offseason.

    If ``form_state`` is given, also resamples every goalie's season-form multiplier for the
    upcoming season (see ``resample_all_goalie_form``) -- kept optional so callers that don't
    care about the goalie-form mechanic (e.g. a unit test exercising only the aging curve) can
    omit it without constructing throwaway state.
    """
    for player in world.players.values():
        develop_player(player, world.rng)
    if form_state is not None:
        resample_all_goalie_form(world, form_state)
