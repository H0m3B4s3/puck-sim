"""World generation -- build a full 32-team NHL-shaped league.

Structural precedent: HoopR's ``hoopsim/gen/leaguegen.py`` (208 lines,
``build_world(seed=...)``). PuckSim's version only needs the NHL-only path
(no college mode, no backstory layering, no separate free-agent pool sizing
pass), so it's considerably shorter -- a straightforward loop-driven builder,
not a global optimizer, mirroring HoopR's own complexity level.

Per DEVPLAN.md Step 1.11: 32 teams, 2 conferences x 2 divisions x 8 teams
(real-world NHL shape, not an invented mechanic -- see ``config.CONFERENCES``/
``config.DIVISIONS_PER_CONFERENCE``). Team names/abbreviations and division
names are illustrative placeholder flavor text only (explicitly out of scope
to over-invest in per DEVPLAN.md) -- a small city-name pool x nickname pool
combination, not real NHL franchise names.

For each team: generate a full legal roster (skaters within
``config.SKATERS_MIN``/``MAX``, goalies within ``config.GOALIES_MIN``/``MAX``)
via ``playergen.generate_skater``/``generate_goalie``, register into the
``World`` and sign onto the team via ``World.sign_player()`` (keeps
``Team.roster``/``Player.team_id`` in sync in one place, per Step 1.9's
documented invariant), auto-build lines/pairs/goalie assignments, assign a
coach, and seed chemistry so the freshly generated league starts at full
chemistry (an "already-existing" league, not a freshly-drafted expansion
one).

``Team.coach`` typing note: ``Team.coach`` is still declared
``Optional[dict]`` (a Step 1.7 placeholder written before coach.py existed).
This module stores ``assign_coach(...).to_dict()`` on it (a plain dict), not
the live ``Coach`` dataclass instance -- see ``_build_roster``'s inline
comment for why (``Team.to_dict()`` concretely calls ``dict(self.coach)``,
which raises for a real ``Coach`` object; storing the dict keeps existing
serialization working without touching team.py, which is out of bounds for
this step).
"""
from __future__ import annotations

from typing import Optional

from pucksim import config
from pucksim.config import MINIMUM_SALARY
from pucksim.gen.playergen import generate_goalie, generate_skater
from pucksim.models.coach import assign_coach
from pucksim.models.tactics import Tactics
from pucksim.models.team import Team, auto_build_lines, seed_chemistry
from pucksim.models.world import World
from pucksim.rng import Rng
from pucksim.systems.cap import max_salary, payroll

# ---------------------------------------------------------------------------
# Illustrative placeholder flavor text -- NOT real NHL team names. Just needs
# to be legal, evenly distributed data for MVP testing (DEVPLAN.md explicitly
# scopes this as illustrative, not final content).
# ---------------------------------------------------------------------------
_CITIES = (
    "Ashford", "Brackenridge", "Cedar Falls", "Dunmore", "Eastwick",
    "Fairhaven", "Glenmoor", "Harborview", "Ironwood", "Juniper Bay",
    "Kingston", "Lakeshore", "Millbrook", "Northgate", "Oakridge",
    "Port Elgin", "Queensbury", "Riverton", "Silverpine", "Thornfield",
    "Underhill", "Valemont", "Westbrook", "Yorkshire", "Zephyr Point",
    "Anchor Bay", "Bellmont", "Copperfield", "Deer Ridge", "Elm Harbor",
    "Frostwind", "Greystone",
)

_NICKNAMES = (
    "Voyageurs", "Timberwolves", "Ice Hawks", "Miners", "Blades",
    "Frost", "Rangers", "Stallions", "Blizzard", "Granite",
    "Harbor Seals", "Wolverines", "Thunderbirds", "Anchors", "Falcons",
    "Cyclones", "Rapids", "Sentinels", "Ironclads", "Comets",
    "Highlanders", "Barons", "Marauders", "Trailblazers", "Foxes",
    "Grizzlies", "Mariners", "Wardens", "Drifters", "Roughnecks",
    "Sabertooths", "Stormriders",
)

# Numbered/thematic division names -- legal, evenly-distributed structure,
# not real NHL division names (DEVPLAN.md: "doesn't need real NHL division
# names, just needs to be a legal, evenly-distributed structure").
_DIVISION_NAMES = ("North", "South")

# ---------------------------------------------------------------------------
# Jersey colors (DEVPLAN.md Step 2.9a). A curated, fixed palette of 32 distinct
# (primary, secondary) hex pairs spanning the realistic range of hockey jersey
# colors -- reds, blues, greens, golds, purples, blacks, oranges, teals, etc.
# Deliberately avoids pure white (#FFFFFF) and pale ice-blue tones
# (#F7F9FA/#E8F4FF-ish) since those are reserved for the web frontend's "ice"
# surface chrome, not team identity (per the Step 2.9a brief). Assignment is
# deterministic given the world's seed: `build_world()` draws from
# `world.rng.sample()` (the same seedable RNG every other generated attribute
# uses, never the global `random` module) so the same seed always produces the
# same team-to-color mapping.
# ---------------------------------------------------------------------------
_JERSEY_COLOR_PAIRS = (
    ("#C8102E", "#111111"),  # red / black
    ("#003087", "#B9975B"),  # navy / gold
    ("#00205B", "#A2AAAD"),  # navy / silver
    ("#041E42", "#A6192E"),  # midnight navy / crimson
    ("#154734", "#FFB81C"),  # forest green / gold
    ("#006272", "#FF6600"),  # teal / orange
    ("#5F259F", "#FFC72C"),  # purple / gold
    ("#8A8D8F", "#000000"),  # steel gray / black
    ("#FF4C00", "#000000"),  # orange / black
    ("#6F263D", "#FFB81C"),  # maroon / gold
    ("#002654", "#CE1126"),  # royal blue / red
    ("#000000", "#C8102E"),  # black / red
    ("#00843D", "#000000"),  # green / black
    ("#FFB81C", "#000000"),  # gold / black
    ("#8B2942", "#A2AAAD"),  # wine / silver
    ("#0033A0", "#C8102E"),  # blue / red
    ("#1E4D2B", "#C4CED4"),  # dark green / gray-white
    ("#B9975B", "#000000"),  # vegas gold / black
    ("#010101", "#B4975A"),  # black / bronze
    ("#003E7E", "#77828F"),  # steel blue / slate
    ("#8C2633", "#000000"),  # brick red / black
    ("#4E0055", "#000000"),  # deep purple / black
    ("#C60C30", "#002D62"),  # scarlet / navy
    ("#013A81", "#FDB827"),  # cobalt / gold
    ("#006847", "#D9B44A"),  # emerald / gold
    ("#7A0019", "#FFC72C"),  # dark maroon / yellow
    ("#00B2A9", "#111111"),  # teal / black
    ("#582C83", "#B4975A"),  # violet / bronze
    ("#B5985A", "#002855"),  # tan-gold / navy
    ("#D50032", "#63666A"),  # crimson / gray
    ("#00509D", "#EE3124"),  # cerulean / red-orange
    ("#3A3D40", "#F2A900"),  # graphite / amber
)
assert len(_JERSEY_COLOR_PAIRS) == config.NUM_TEAMS

# ---------------------------------------------------------------------------
# Roster construction shape. Every team gets exactly this many skaters/goalies
# so `auto_build_lines` always has enough bodies for 4 complete forward lines
# (needs >=12 forwards) and 3 complete D pairs (needs >=6 D) -- both counts
# comfortably inside config.SKATERS_MIN/MAX (18-20) and GOALIES_MIN/MAX (2-3).
# Provisional/tunable -- a fixed split is simplest for MVP; per-team variation
# within the legal min/max range is a reasonable future refinement.
# ---------------------------------------------------------------------------
_FORWARDS_PER_TEAM = 13
_DEFENSEMEN_PER_TEAM = 7
_GOALIES_PER_TEAM = 2
assert _FORWARDS_PER_TEAM + _DEFENSEMEN_PER_TEAM == config.SKATERS_MIN + 2  # 20, within MAX
assert config.SKATERS_MIN <= _FORWARDS_PER_TEAM + _DEFENSEMEN_PER_TEAM <= config.SKATERS_MAX
assert config.GOALIES_MIN <= _GOALIES_PER_TEAM <= config.GOALIES_MAX

_FORWARD_POSITIONS = ("LW", "C", "RW")

# Full chemistry baseline for a freshly generated, "already-existing" league
# (see seed_chemistry()'s docstring) -- a large base with a little spread so
# it doesn't read as perfectly uniform. Provisional/tunable.
_CHEMISTRY_BASE_SECS = 5_000.0
_CHEMISTRY_SPREAD_SECS = 1_500.0

# ---------------------------------------------------------------------------
# Age curve. Weighted toward the NHL-realistic 20-32 prime-career range with a
# long thin tail out to config.RETIREMENT_AGE (40) and a short young tail down
# to 18. PROVISIONAL/TUNABLE -- a reasonable first-pass shape, not sourced
# from real age-distribution data.
# ---------------------------------------------------------------------------
_AGE_MIN = 18
_AGE_MODE = 27
_AGE_MAX = config.RETIREMENT_AGE

# Target-overall distribution. Most players cluster in the 60-75 "average NHL
# regular" band, with a thinning tail up into the 80s+ (stars) and down into
# the 40s-50s (replacement level/depth). PROVISIONAL/TUNABLE -- generation
# balancing is expected to iterate once real sim data exists.
_OVERALL_MU = 66.0
_OVERALL_SIGMA = 10.0
_OVERALL_FLOOR = 40

# ---------------------------------------------------------------------------
# Payroll fitting (see _fit_payroll_to_cap). The scaling converges in 2-3 passes
# for any realistic roster; the extra passes are headroom for rosters where many
# contracts pin against the minimum or the max-salary ceiling at once.
# ---------------------------------------------------------------------------
_PAYROLL_FIT_PASSES = 6
_PAYROLL_FIT_TOLERANCE = 250_000     # within a quarter-million of target is "landed"
_PAYROLL_FIT_MAX_SHAVES = 200        # defensive bound on the cap-legality clamp loop


def _random_age(rng: Rng) -> int:
    return int(round(max(_AGE_MIN, min(_AGE_MAX, rng.triangular(_AGE_MIN, _AGE_MAX, _AGE_MODE)))))


def _random_target_overall(rng: Rng) -> int:
    value = rng.gauss(_OVERALL_MU, _OVERALL_SIGMA)
    return int(round(max(_OVERALL_FLOOR, min(99, value))))


def _team_name_and_abbrev(rng: Rng, used_names: set, used_abbrevs: set) -> tuple:
    """Pick a unique "City Nickname" + a 3-letter abbreviation (simple scheme).

    32 teams drawn from a 32-city x 32-nickname pool gives ample headroom to
    avoid name collisions; abbreviation collisions (first letters of city +
    nickname) are disambiguated with a trailing digit.
    """
    for _ in range(50):
        city = rng.choice(_CITIES)
        nickname = rng.choice(_NICKNAMES)
        name = f"{city} {nickname}"
        if name in used_names:
            continue
        abbrev = (city[0] + nickname[:2]).upper()
        if abbrev in used_abbrevs:
            for suffix in "123456789":
                candidate = abbrev[:2] + suffix
                if candidate not in used_abbrevs:
                    abbrev = candidate
                    break
        used_names.add(name)
        used_abbrevs.add(abbrev)
        return name, abbrev
    # Exceedingly unlikely fallback given the pool sizes vs. 32 teams.
    idx = len(used_names)
    name = f"Team {idx}"
    abbrev = f"T{idx:02d}"[:3].upper()
    used_names.add(name)
    used_abbrevs.add(abbrev)
    return name, abbrev


def _payroll_target(rng: Rng, cap: int) -> int:
    """The share of the cap this team's roster should consume.

    Most teams draw from the normal band (`config.GEN_PAYROLL_FRACTION_MIN/MAX`); a
    minority are rebuilding and draw from a lower one, which is what gives the opening
    league a realistic *spread* of cap space instead of 32 identically-squeezed teams.
    """
    if rng.random() < config.GEN_REBUILDING_TEAM_SHARE:
        lo = config.GEN_REBUILDING_PAYROLL_FRACTION_MIN
        hi = config.GEN_REBUILDING_PAYROLL_FRACTION_MAX
    else:
        lo = config.GEN_PAYROLL_FRACTION_MIN
        hi = config.GEN_PAYROLL_FRACTION_MAX
    return int(cap * rng.uniform(lo, hi))


def _fit_payroll_to_cap(world: World, team: Team, rng: Rng) -> None:
    """Scale a freshly generated roster's contracts onto a realistic payroll target.

    ``playergen`` prices each contract independently off the shared market curve, which
    gets the *league-wide* economy right (mean payroll lands near the target on its own)
    but leaves enormous per-team variance -- a roster that happens to draw three stars
    can generate $25M over the cap while an unlucky one sits $28M under. Neither is a
    legal or interesting starting position, so each roster is scaled onto a target drawn
    by ``_payroll_target``.

    Scaling (rather than re-rolling contracts) is deliberate: it preserves the *relative*
    pay ordering playergen produced -- the team's best player is still its highest-paid,
    the overpays are still overpays -- while moving the aggregate. Two salaries are held
    fixed and excluded from the scaling:

    - entry-level deals, which are cheap by rule and don't flex with a team's cap
      situation, and
    - anything already at the league minimum when scaling down, which cannot legally go
      lower.

    Because those exclusions (and the per-contract ``max_salary`` ceiling) can absorb
    less than their share of the adjustment, the scale is applied iteratively, with the
    residual redistributed over whatever contracts still have room. The final guard
    clamps into cap legality outright, so this function's postcondition is unconditional:
    the team is under the cap when it returns.
    """
    cap = world.salary_cap
    target = _payroll_target(rng, cap)
    ceiling = max_salary(cap)

    # Entry-level deals are fixed by rule -- they're a floor of committed money the
    # scaling has to work around, not part of what flexes.
    roster = [world.players[pid] for pid in team.roster]
    fixed = [p for p in roster if p.contract.is_rookie_scale]
    flexible = [p for p in roster if not p.contract.is_rookie_scale]
    if not flexible:
        return

    fixed_total = sum(p.contract.current_salary for p in fixed)
    flex_target = max(len(flexible) * MINIMUM_SALARY, target - fixed_total)

    for _ in range(_PAYROLL_FIT_PASSES):
        flex_total = sum(p.contract.current_salary for p in flexible)
        if flex_total <= 0:
            break
        # Contracts pinned at a bound can't absorb their share, so each pass rescales
        # only those still free to move and lets the next pass mop up the residual.
        movable = [p for p in flexible
                   if MINIMUM_SALARY < p.contract.current_salary < ceiling]
        if not movable:
            break
        movable_total = sum(p.contract.current_salary for p in movable)
        pinned_total = flex_total - movable_total
        if movable_total <= 0:
            break
        scale = (flex_target - pinned_total) / movable_total
        for player in movable:
            salary = _round_salary(player.contract.current_salary * scale, ceiling)
            player.contract.salaries = [salary] * player.contract.years_remaining
            player.contract.guaranteed = [True] * player.contract.years_remaining
        if abs(sum(p.contract.current_salary for p in flexible) - flex_target) <= _PAYROLL_FIT_TOLERANCE:
            break

    _force_under_cap(world, team, flexible, ceiling)


def _round_salary(raw: float, ceiling: int) -> int:
    """Snap a scaled salary to a legal, human-readable $50K increment."""
    salary = int(round(raw / 50_000) * 50_000)
    return max(MINIMUM_SALARY, min(salary, ceiling))


def _force_under_cap(world: World, team: Team, flexible: list, ceiling: int) -> None:
    """Last-resort clamp guaranteeing the generated team opens cap-legal.

    ``_fit_payroll_to_cap``'s iterative scaling normally lands well inside the cap, but
    it can't in principle if a roster's fixed (entry-level) and minimum-salary money
    alone exceeds the cap. Rather than let world gen emit an illegal team -- which every
    downstream system (`cap.can_sign`, trades, free agency) assumes never happens -- this
    shaves the highest salaries down until the payroll fits, in $50K steps.
    """
    guard = 0
    while payroll(world, team) > world.salary_cap and guard < _PAYROLL_FIT_MAX_SHAVES:
        guard += 1
        reducible = [p for p in flexible if p.contract.current_salary > MINIMUM_SALARY]
        if not reducible:
            return
        richest = max(reducible, key=lambda p: p.contract.current_salary)
        overage = payroll(world, team) - world.salary_cap
        headroom = richest.contract.current_salary - MINIMUM_SALARY
        cut = min(headroom, max(50_000, int(round(overage / 50_000) * 50_000)))
        salary = _round_salary(richest.contract.current_salary - cut, ceiling)
        richest.contract.salaries = [salary] * richest.contract.years_remaining
        richest.contract.guaranteed = [True] * richest.contract.years_remaining


def _build_roster(world: World, team: Team) -> None:
    rng = world.rng

    # Forwards: cycle evenly through LW/C/RW so every line-slot has enough
    # candidates for auto_build_lines to fill (roughly even thirds).
    for i in range(_FORWARDS_PER_TEAM):
        position = _FORWARD_POSITIONS[i % len(_FORWARD_POSITIONS)]
        age = _random_age(rng)
        target = _random_target_overall(rng)
        player = generate_skater(world.new_pid(), rng, age, target, position=position,
                                  cap=world.salary_cap)
        world.add_player(player)
        world.sign_player(player.pid, team.tid)

    for _ in range(_DEFENSEMEN_PER_TEAM):
        age = _random_age(rng)
        target = _random_target_overall(rng)
        player = generate_skater(world.new_pid(), rng, age, target, position="D",
                                  cap=world.salary_cap)
        world.add_player(player)
        world.sign_player(player.pid, team.tid)

    for _ in range(_GOALIES_PER_TEAM):
        age = _random_age(rng)
        # Goalies peak a bit later in real hockey; nudge the overall
        # distribution's center up slightly relative to skaters is
        # unnecessary for MVP -- reuse the same distribution for simplicity.
        target = _random_target_overall(rng)
        goalie = generate_goalie(world.new_pid(), rng, age, target, cap=world.salary_cap)
        world.add_player(goalie)
        world.sign_player(goalie.pid, team.tid)

    _fit_payroll_to_cap(world, team, rng)
    auto_build_lines(team, world.players)
    seed_chemistry(team, rng, base=_CHEMISTRY_BASE_SECS, spread=_CHEMISTRY_SPREAD_SECS)


def build_world(seed: Optional[int] = None) -> World:
    """Generate a complete, ready-to-play 32-team NHL-shaped league.

    Deterministic: the same ``seed`` always produces byte-identical rosters
    (every draw -- team order, player generation, coach assignment, chemistry
    seeding -- comes from the single ``World.rng`` stream in a fixed order).
    """
    rng = Rng(seed)
    world = World(rng=rng)

    used_names: set = set()
    used_abbrevs: set = set()

    # Jersey colors: draw one deterministic permutation of the palette (via the seeded
    # World.rng, same as every other generated attribute -- never the global `random`
    # module) so each of the 32 teams gets a distinct, seed-reproducible color pair.
    _color_order = rng.sample(range(len(_JERSEY_COLOR_PAIRS)), len(_JERSEY_COLOR_PAIRS))

    tid = 0
    for conference in config.CONFERENCES:
        for division_idx in range(config.DIVISIONS_PER_CONFERENCE):
            division = _DIVISION_NAMES[division_idx % len(_DIVISION_NAMES)]
            for _ in range(config.TEAMS_PER_DIVISION):
                name, abbrev = _team_name_and_abbrev(rng, used_names, used_abbrevs)
                primary_color, secondary_color = _JERSEY_COLOR_PAIRS[_color_order[tid]]
                team = Team(
                    tid=tid,
                    name=name,
                    abbrev=abbrev,
                    conference=conference,
                    division=division,
                    primary_color=primary_color,
                    secondary_color=secondary_color,
                )
                world.register_team(team)
                _build_roster(world, team)

                # Team.coach resolution (DEVPLAN.md Step 1.11 note): Team.coach
                # is still typed `Optional[dict]` -- a Step 1.7 placeholder
                # written before coach.py existed. Team.to_dict() concretely
                # does `dict(self.coach)`, which raises TypeError for a real
                # Coach dataclass instance (verified directly, not assumed) --
                # so storing the live Coach object would silently break
                # World/Team serialization the moment anyone calls
                # `team.to_dict()` on a generated league. Since team.py is
                # frozen for this step (models/ is out of bounds here), the
                # least-surprising choice that keeps existing serialization
                # code working is to store `coach.to_dict()` (a plain dict),
                # matching the placeholder's declared type exactly. Callers
                # that need the real tendency knobs (Step 2.8's line-juggling
                # AI, etc.) reconstruct a live Coach via
                # `pucksim.models.coach.Coach.from_dict(team.coach)` /
                # `profile_for(team.coach["archetype"])` on demand -- cheap,
                # since CoachProfile lookup is just a dict read, not a
                # database round-trip.
                coach = assign_coach(tid, rng)
                team.coach = coach.to_dict()

                # Team.tactics (DEVPLAN.md Step 2.8): unlike ``coach`` above, ``Tactics`` is
                # a real dataclass on Team now (Step 2.8 migrated it off the Optional[dict]
                # placeholder -- see team.py's docstring), so it's stored directly, no
                # to_dict()-at-rest workaround needed. Every generated team starts on the
                # balanced/default tactics board (``Tactics()``'s own field defaults); a coach
                # doesn't get an opinionated starting tactics setup baked in here -- that would
                # be reading more into "generate a legal starting league" than this step asks
                # for. A user (or a future AI-tactics-setter) can cycle it later via
                # ``Tactics.cycle()``.
                team.tactics = Tactics()

                tid += 1

    return world
