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
from pucksim.gen.playergen import generate_goalie, generate_skater
from pucksim.models.coach import assign_coach
from pucksim.models.tactics import Tactics
from pucksim.models.team import Team, auto_build_lines, seed_chemistry
from pucksim.models.world import World
from pucksim.rng import Rng

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


def _build_roster(world: World, team: Team) -> None:
    rng = world.rng

    # Forwards: cycle evenly through LW/C/RW so every line-slot has enough
    # candidates for auto_build_lines to fill (roughly even thirds).
    for i in range(_FORWARDS_PER_TEAM):
        position = _FORWARD_POSITIONS[i % len(_FORWARD_POSITIONS)]
        age = _random_age(rng)
        target = _random_target_overall(rng)
        player = generate_skater(world.new_pid(), rng, age, target, position=position)
        world.add_player(player)
        world.sign_player(player.pid, team.tid)

    for _ in range(_DEFENSEMEN_PER_TEAM):
        age = _random_age(rng)
        target = _random_target_overall(rng)
        player = generate_skater(world.new_pid(), rng, age, target, position="D")
        world.add_player(player)
        world.sign_player(player.pid, team.tid)

    for _ in range(_GOALIES_PER_TEAM):
        age = _random_age(rng)
        # Goalies peak a bit later in real hockey; nudge the overall
        # distribution's center up slightly relative to skaters is
        # unnecessary for MVP -- reuse the same distribution for simplicity.
        target = _random_target_overall(rng)
        goalie = generate_goalie(world.new_pid(), rng, age, target)
        world.add_player(goalie)
        world.sign_player(goalie.pid, team.tid)

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

    tid = 0
    for conference in config.CONFERENCES:
        for division_idx in range(config.DIVISIONS_PER_CONFERENCE):
            division = _DIVISION_NAMES[division_idx % len(_DIVISION_NAMES)]
            for _ in range(config.TEAMS_PER_DIVISION):
                name, abbrev = _team_name_and_abbrev(rng, used_names, used_abbrevs)
                team = Team(
                    tid=tid,
                    name=name,
                    abbrev=abbrev,
                    conference=conference,
                    division=division,
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
