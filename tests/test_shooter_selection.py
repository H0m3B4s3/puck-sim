"""Who shoots, and from where.

Defensemen scored 31% of all goals against a real-NHL ~13%. Two causes, of which the second was
much the larger:

1. Volume -- the two D on the ice took 34.6% of shot attempts (real ~26%), essentially on headcount,
   because they sat in the same weighted pool as forwards at full weight.
2. QUALITY -- ``_pick_zone_and_shot_type`` ran BEFORE the shooter was chosen, so a defenseman's point
   shot was modeled as exactly as dangerous as a winger's slot chance. D converted at 8.94% against a
   real ~4.5%, nearly the forward rate.

Separately, the shooter weight was ``max(1.0, scoring - 40)``. Against a league-mean composite of 60
that left a mean weight of 20, so a 90th-percentile shooter carried 2.05x an average one -- which
gave the league goal leader 17.7% of his team's shots against a real ~13.5%.
"""
import statistics

from pucksim import config
from pucksim.gen.leaguegen import build_world
from pucksim.models.player import Player
from pucksim.sim import engine as E
from pucksim.sim.engine import GameSim
from pucksim.sim.ratings import build_on_ice_cache


def _player(pid, position, accuracy, power, awareness):
    return Player(pid=pid, name=f"P{pid}", age=25, position=position,
                  ratings={"shot_accuracy": accuracy, "shot_power": power,
                           "offensive_awareness": awareness, "playmaking": 60})


# ---------------------------------------------------------------------------
# The weight curve
# ---------------------------------------------------------------------------
def test_shot_weight_rises_with_the_scoring_composite():
    weak = _player(1, "C", 40, 40, 40)
    strong = _player(2, "C", 90, 90, 90)
    cache = build_on_ice_cache([weak, strong])
    assert cache.shot_weights[1] > cache.shot_weights[0]


def test_weight_curve_is_far_flatter_than_the_old_offset_form():
    """The old ``scoring - 40`` gave a 90th-percentile shooter 2.05x an average one's weight. That
    compounds over a season into the goal leader taking 17.7% of team shots instead of ~13.5%."""
    average = _player(1, "C", 60, 60, 60)     # composite 60, the league mean
    elite = _player(2, "C", 81, 81, 81)       # composite 81, ~90th percentile
    cache = build_on_ice_cache([average, elite])
    ratio = cache.shot_weights[1] / cache.shot_weights[0]
    assert 1.2 < ratio < 1.8, f"elite/average shot weight ratio {ratio:.2f}"


def test_defensemen_are_weighted_down_relative_to_forwards():
    forward = _player(1, "C", 70, 70, 70)
    defender = _player(2, "D", 70, 70, 70)
    cache = build_on_ice_cache([forward, defender])
    assert cache.shot_weights[1] < cache.shot_weights[0]
    ratio = cache.shot_weights[1] / cache.shot_weights[0]
    assert abs(ratio - config.D_SHOT_WEIGHT_MULT) < 0.05


def test_even_a_poor_shooter_keeps_a_positive_weight():
    """A checking-line grinder still shoots sometimes. A zero weight would make him literally
    incapable of scoring, which no rating should do."""
    terrible = _player(1, "C", 25, 25, 25)
    cache = build_on_ice_cache([terrible])
    assert cache.shot_weights[0] >= config.SHOT_WEIGHT_MIN > 0


# ---------------------------------------------------------------------------
# Shooter-aware zones
# ---------------------------------------------------------------------------
def test_defensemen_draw_from_their_own_zone_table():
    zone_f, type_f = E._select_weights_for("C")
    zone_d, type_d = E._select_weights_for("D")
    assert zone_f is E._ZONE_SELECT_WEIGHT
    assert zone_d is E._D_ZONE_SELECT_WEIGHT
    assert type_d is E._D_SHOT_TYPE_SELECT_WEIGHT


def test_unknown_position_falls_back_to_the_forward_tables():
    """A caller that has not resolved a shooter must get sensible behavior, not a crash."""
    zone, shot_type = E._select_weights_for("")
    assert zone is E._ZONE_SELECT_WEIGHT and shot_type is E._SHOT_TYPE_SELECT_WEIGHT


def test_both_frequency_tables_are_normalized():
    for table in (E._ZONE_SELECT_WEIGHT, E._D_ZONE_SELECT_WEIGHT,
                  E._SHOT_TYPE_SELECT_WEIGHT, E._D_SHOT_TYPE_SELECT_WEIGHT):
        assert abs(sum(table.values()) - 1.0) < 1e-9, table


def test_defenseman_shot_quality_is_meaningfully_lower():
    """The core of the fix. If these converge, D start scoring like forwards again."""
    def mean_quality(zone_table, type_table):
        zone = sum(zone_table[z] * E._ZONE_QUALITY[z] for z in zone_table)
        shot = sum(type_table[t] * E._SHOT_TYPE_QUALITY[t] for t in type_table)
        return 0.5 * zone + 0.5 * shot

    forward = mean_quality(E._ZONE_SELECT_WEIGHT, E._SHOT_TYPE_SELECT_WEIGHT)
    defender = mean_quality(E._D_ZONE_SELECT_WEIGHT, E._D_SHOT_TYPE_SELECT_WEIGHT)
    assert defender < forward - 0.05, f"D quality {defender:.3f} vs F {forward:.3f}"


def test_defensemen_mostly_shoot_from_the_point():
    assert E._D_ZONE_SELECT_WEIGHT["point"] > 0.35
    assert E._D_ZONE_SELECT_WEIGHT["crease"] < 0.05
    assert E._D_ZONE_SELECT_WEIGHT["point"] > E._ZONE_SELECT_WEIGHT["point"]
    assert E._D_ZONE_SELECT_WEIGHT["slot"] < E._ZONE_SELECT_WEIGHT["slot"]


def test_defensemen_lean_on_the_slap_shot():
    assert E._D_SHOT_TYPE_SELECT_WEIGHT["slap"] > E._SHOT_TYPE_SELECT_WEIGHT["slap"]
    assert E._D_SHOT_TYPE_SELECT_WEIGHT["tip"] < E._SHOT_TYPE_SELECT_WEIGHT["tip"]


def test_zone_selection_actually_differs_by_position_in_play():
    """End to end through the engine, not just the tables."""
    world = build_world(seed=7)
    sim = GameSim(world, 0, 1)
    offense = sim.home
    forward = next(world.player(pid) for pid in offense.team.lines[0]
                   if world.player(pid).position != "D")
    defender = next(world.player(pid) for pid in offense.team.pairs[0]
                    if world.player(pid).position == "D")

    def point_share(shooter):
        hits = sum(1 for _ in range(400)
                   if sim._pick_zone_and_shot_type(offense, shooter)[0] == "point")
        return hits / 400

    assert point_share(defender) > point_share(forward) + 0.15


# ---------------------------------------------------------------------------
# Special-teams double duty
# ---------------------------------------------------------------------------
def test_power_play_forwards_are_kept_off_the_top_penalty_kill():
    """A coach does not put his leading scorer on the top PK unit. Because _pk_defensive_value ranks
    by a `defense` composite that elite two-way forwards top, the same forwards landed on PP1 AND
    PK1 and collected ~6.3 minutes of special-teams time a night against ~3 for a real first-liner --
    the measured cause of first-line ice time running ~4 minutes over its NHL band."""
    world = build_world(seed=7)
    overlaps = 0
    slots = 0
    for tid in sorted(world.teams.keys()):
        team = world.team(tid)
        pp_forwards = {pid for pid in team.pp_unit_1 if world.player(pid).position != "D"}
        pk_forwards = {pid for pid in team.pk_unit_1 if world.player(pid).position != "D"}
        overlaps += len(pp_forwards & pk_forwards)
        slots += len(pk_forwards)
    assert slots > 0
    assert overlaps == 0, f"{overlaps} of {slots} PK1 forward slots went to a PP1 forward"


def test_penalty_kill_units_are_still_full_size():
    """PP1 forwards are pushed to the BACK of the ranking, not removed -- on a thin roster they must
    still be eligible or the unit would come up short."""
    world = build_world(seed=7)
    for tid in sorted(world.teams.keys()):
        team = world.team(tid)
        assert len(team.pk_unit_1) == config.PK_UNIT_SIZE, f"team {tid} PK1 {team.pk_unit_1}"
        assert len(team.pk_unit_2) == config.PK_UNIT_SIZE, f"team {tid} PK2 {team.pk_unit_2}"


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------
def test_defensemen_take_a_realistic_share_of_shots_and_convert_far_worse():
    world = build_world(seed=7)
    d_sog = f_sog = d_goals = f_goals = 0
    for i in range(10):
        result = GameSim(world, i % 32, (i + 9) % 32).play()
        for pid, line in result.skater_box.items():
            if world.player(pid).position == "D":
                d_sog += line.sog
                d_goals += line.g
            else:
                f_sog += line.sog
                f_goals += line.g
    share = d_sog / (d_sog + f_sog)
    assert 0.18 <= share <= 0.30, f"D took {share:.1%} of shots on goal"
    d_pct = d_goals / d_sog
    f_pct = f_goals / f_sog
    assert d_pct < f_pct * 0.75, f"D shooting {d_pct:.1%} vs F {f_pct:.1%} -- too close"
