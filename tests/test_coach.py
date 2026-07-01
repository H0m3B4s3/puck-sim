"""Tests for pucksim.models.coach -- Step 1.10 done-criteria."""
from pucksim.models.coach import (
    ARCHETYPES,
    BALANCED,
    Coach,
    CoachProfile,
    assign_coach,
    profile_for,
)
from pucksim.rng import Rng


def test_assign_coach_produces_valid_coach_from_archetypes():
    rng = Rng(seed=42)
    coach = assign_coach(cid=7, rng=rng)

    assert isinstance(coach, Coach)
    assert coach.cid == 7
    assert coach.name == "Coach 7"
    assert isinstance(coach.profile, CoachProfile)

    archetype_names = {profile.name for profile, _weight in ARCHETYPES}
    assert coach.profile.name in archetype_names


def test_assign_coach_is_deterministic_for_a_given_seed():
    coach_a = assign_coach(cid=1, rng=Rng(seed=99))
    coach_b = assign_coach(cid=1, rng=Rng(seed=99))
    assert coach_a.profile.name == coach_b.profile.name


def test_assign_coach_can_produce_different_archetypes_across_seeds():
    names = {assign_coach(cid=1, rng=Rng(seed=s)).profile.name for s in range(30)}
    # With 6 archetypes and 30 different seeds, we should see some variety.
    assert len(names) > 1


def test_profile_for_balanced_works():
    profile = profile_for("Balanced")
    assert profile is BALANCED
    assert profile.name == "Balanced"


def test_profile_for_unknown_archetype_falls_back_to_balanced():
    # Fallback behavior choice: an unknown/missing archetype name never raises --
    # it resolves to the Balanced profile instead, so a stale/corrupt save can't
    # crash the game.
    profile = profile_for("Nonexistent Archetype")
    assert profile is BALANCED


def test_all_archetypes_have_distinct_names_and_valid_ranges():
    names = [profile.name for profile, _weight in ARCHETYPES]
    assert len(names) == len(set(names))
    assert len(ARCHETYPES) >= 4

    for profile, weight in ARCHETYPES:
        assert weight > 0
        assert 0.0 <= profile.forecheck_aggression <= 1.0
        assert 0.0 <= profile.pp_style_aggression <= 1.0
        assert 0.0 <= profile.pk_style_aggression <= 1.0
        assert 0.0 <= profile.line_juggling_patience <= 1.0
        assert 0.0 <= profile.shot_volume <= 1.0
        assert 0.0 <= profile.shot_quality_bias <= 1.0
        assert 0.0 <= profile.defensive_risk_tolerance <= 1.0
        assert profile.pp_forwards in (3, 4)
        assert profile.goalie_pull_max_deficit >= 1
        assert profile.goalie_pull_time_threshold_secs > 0


def test_high_event_gambler_is_the_extreme_on_every_risk_axis():
    gambler = profile_for("High-Event Gambler")
    structure = profile_for("Defensive Structure")

    # The two archetypes built to sit at opposite ends of the risk spectrum
    # should actually score as opposites on every new risk-tolerance knob,
    # not just the pre-existing forecheck/pp/pk aggression ones.
    assert gambler.shot_volume > structure.shot_volume
    assert gambler.shot_quality_bias < structure.shot_quality_bias
    assert gambler.defensive_risk_tolerance > structure.defensive_risk_tolerance
    assert gambler.goalie_pull_time_threshold_secs > structure.goalie_pull_time_threshold_secs
    assert gambler.goalie_pull_max_deficit >= structure.goalie_pull_max_deficit
    assert gambler.pp_forwards == 4
    assert structure.pp_forwards == 3


def test_shot_volume_and_shot_quality_bias_are_independent_axes():
    # Deliberately not a single combined "pace" tradeoff -- confirm a profile
    # can score high on one axis without being forced low on the other.
    profile = CoachProfile(name="Volume+Quality", weight=1.0, shot_volume=0.9,
                            shot_quality_bias=0.9)
    assert profile.shot_volume == 0.9
    assert profile.shot_quality_bias == 0.9


def test_coach_to_dict_from_dict_round_trip_reconstructs_profile_by_name():
    coach = assign_coach(cid=3, rng=Rng(seed=5))
    d = coach.to_dict()

    assert d["cid"] == 3
    assert d["archetype"] == coach.profile.name

    restored = Coach.from_dict(d)
    assert restored.cid == coach.cid
    assert restored.name == coach.name
    assert restored.profile.name == coach.profile.name
    assert restored.profile == coach.profile


def test_coach_from_dict_falls_back_to_balanced_for_unknown_archetype():
    restored = Coach.from_dict({"cid": 4, "name": "Coach 4", "archetype": "Made Up"})
    assert restored.profile is BALANCED
