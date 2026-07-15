"""Tests for pucksim.models.attributes: rating scale, composites, overall, archetypes."""
from __future__ import annotations

import pytest

from pucksim.config import RATING_MAX, RATING_MIN
from pucksim.models import attributes as attr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mid_skater_ratings(value: int = 70) -> dict:
    return {name: value for name in attr.ALL_RATINGS}


def _mid_goalie_ratings(value: int = 70) -> dict:
    return {name: value for name in attr.ALL_GOALIE_RATINGS}


# ---------------------------------------------------------------------------
# Structural sanity
# ---------------------------------------------------------------------------
def test_positions_tuple_is_stable_five_slot_split():
    assert attr.POSITIONS == ("LW", "C", "RW", "D", "G")
    assert attr.SKATER_POSITIONS == ("LW", "C", "RW", "D")


def test_all_ratings_matches_rating_groups_flattened():
    flattened = [r for group in attr.RATING_GROUPS.values() for r in group]
    assert attr.ALL_RATINGS == flattened
    assert len(attr.ALL_RATINGS) == len(set(attr.ALL_RATINGS)), "no duplicate rating names"


def test_no_fighting_or_enforcer_rating_exists():
    # DESIGN.md: fighting/enforcers explicitly out of scope for v1.
    banned_substrings = ("fight", "enforcer")
    for rating in attr.ALL_RATINGS:
        for bad in banned_substrings:
            assert bad not in rating.lower(), f"unexpected rating name: {rating}"


def test_goalie_ratings_are_namespaced_separately_from_skater_ratings():
    skater_set = set(attr.ALL_RATINGS)
    goalie_set = set(attr.ALL_GOALIE_RATINGS)
    assert skater_set.isdisjoint(goalie_set)


# ---------------------------------------------------------------------------
# Weight-sum invariants (programmatic, looped over every position)
# ---------------------------------------------------------------------------
def test_position_weights_sum_to_one_for_every_skater_position():
    for pos in attr.SKATER_POSITIONS:
        weights = attr.POSITION_WEIGHTS[pos]
        total = sum(weights.values())
        assert total == pytest.approx(1.0), f"{pos} weights sum to {total}, expected 1.0"


def test_goalie_weights_sum_to_one():
    total = sum(attr.GOALIE_WEIGHTS.values())
    assert total == pytest.approx(1.0)


def test_composite_formulas_reference_only_real_skater_ratings():
    valid = set(attr.ALL_RATINGS)
    for name in attr.COMPOSITES:
        formula = attr._COMPOSITE_FORMULA[name]
        for rating_name in formula:
            assert rating_name in valid, f"composite {name} references unknown rating {rating_name}"


def test_position_weights_reference_only_real_composites():
    valid = set(attr.COMPOSITES)
    for pos, weights in attr.POSITION_WEIGHTS.items():
        for comp_name in weights:
            assert comp_name in valid


def test_goalie_weights_reference_only_real_goalie_ratings():
    valid = set(attr.ALL_GOALIE_RATINGS)
    for rating_name in attr.GOALIE_WEIGHTS:
        assert rating_name in valid


# ---------------------------------------------------------------------------
# clamp_rating()
# ---------------------------------------------------------------------------
def test_clamp_rating_bounds():
    assert attr.clamp_rating(0) == RATING_MIN
    assert attr.clamp_rating(200) == RATING_MAX
    assert attr.clamp_rating(70.4) == 70
    assert attr.clamp_rating(70.6) == 71


# ---------------------------------------------------------------------------
# overall() in [25, 99] at each position, skaters + goalie
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("position", ["LW", "C", "RW", "D"])
def test_skater_overall_in_range_mid_tier(position):
    ratings = _mid_skater_ratings(70)
    value = attr.overall(position, ratings)
    assert RATING_MIN <= value <= RATING_MAX


@pytest.mark.parametrize("position", ["LW", "C", "RW", "D"])
def test_skater_overall_in_range_extremes(position):
    low = attr.overall(position, _mid_skater_ratings(RATING_MIN))
    high = attr.overall(position, _mid_skater_ratings(RATING_MAX))
    assert RATING_MIN <= low <= RATING_MAX
    assert RATING_MIN <= high <= RATING_MAX
    assert low < high


def test_goalie_overall_in_range():
    ratings = _mid_goalie_ratings(70)
    value = attr.overall("G", ratings)
    assert RATING_MIN <= value <= RATING_MAX


def test_goalie_overall_dispatches_separately_from_skaters():
    # A goalie-position call must use GOALIE_WEIGHTS/ALL_GOALIE_RATINGS, not the
    # skater composite machinery — sanity-check that varying skater-only ratings
    # (which don't exist in the goalie dict) doesn't change the goalie overall.
    base = attr.overall("G", _mid_goalie_ratings(70))
    ratings_with_junk = _mid_goalie_ratings(70)
    ratings_with_junk["shot_accuracy"] = 99  # a skater rating, irrelevant to goalies
    assert attr.overall("G", ratings_with_junk) == base


def test_all_composites_returns_every_composite_axis():
    comps = attr.all_composites(_mid_skater_ratings(70))
    assert set(comps.keys()) == set(attr.COMPOSITES)
    for value in comps.values():
        assert RATING_MIN <= value <= RATING_MAX


# ---------------------------------------------------------------------------
# Archetype skews applied to a mid-tier (70) baseline never leave [25, 99]
# ---------------------------------------------------------------------------
def _apply_skews(baseline: dict, skews: dict) -> dict:
    result = dict(baseline)
    for rating, delta in skews.items():
        result[rating] = attr.clamp_rating(result.get(rating, RATING_MIN) + delta)
    return result


@pytest.mark.parametrize("archetype", attr.ARCHETYPES, ids=lambda a: a.name)
def test_skater_archetype_skews_stay_in_range(archetype):
    baseline = _mid_skater_ratings(70)
    skewed = _apply_skews(baseline, archetype.skews)
    for rating, value in skewed.items():
        assert RATING_MIN <= value <= RATING_MAX, f"{archetype.name}: {rating}={value}"


@pytest.mark.parametrize("archetype", attr.RARE_ARCHETYPES, ids=lambda a: a.name)
def test_rare_skater_archetype_skews_stay_in_range(archetype):
    baseline = _mid_skater_ratings(70)
    skewed = _apply_skews(baseline, archetype.skews)
    for rating, value in skewed.items():
        assert RATING_MIN <= value <= RATING_MAX, f"{archetype.name}: {rating}={value}"


@pytest.mark.parametrize("archetype", attr.GOALIE_ARCHETYPES, ids=lambda a: a.name)
def test_goalie_archetype_skews_stay_in_range(archetype):
    baseline = _mid_goalie_ratings(70)
    skewed = _apply_skews(baseline, archetype.skews)
    for rating, value in skewed.items():
        assert RATING_MIN <= value <= RATING_MAX, f"{archetype.name}: {rating}={value}"


@pytest.mark.parametrize("archetype", attr.RARE_GOALIE_ARCHETYPES, ids=lambda a: a.name)
def test_rare_goalie_archetype_skews_stay_in_range(archetype):
    baseline = _mid_goalie_ratings(70)
    skewed = _apply_skews(baseline, archetype.skews)
    for rating, value in skewed.items():
        assert RATING_MIN <= value <= RATING_MAX, f"{archetype.name}: {rating}={value}"


# ---------------------------------------------------------------------------
# Archetype registry / lookup tables
# ---------------------------------------------------------------------------
def test_archetypes_by_position_only_covers_skater_positions():
    assert set(attr.ARCHETYPES_BY_POSITION.keys()) == set(attr.SKATER_POSITIONS)
    for pos in attr.SKATER_POSITIONS:
        # every skater position should have at least one archetype available
        assert len(attr.ARCHETYPES_BY_POSITION[pos]) > 0


def test_goalie_archetypes_by_position_only_covers_goalie():
    assert set(attr.GOALIE_ARCHETYPES_BY_POSITION.keys()) == {"G"}
    assert len(attr.GOALIE_ARCHETYPES_BY_POSITION["G"]) > 0


def test_rare_archetypes_exist_for_both_skaters_and_goalies():
    assert len(attr.RARE_ARCHETYPES) >= 1
    assert len(attr.RARE_GOALIE_ARCHETYPES) >= 1


def test_no_archetype_has_a_fighting_or_enforcer_skew():
    all_archetypes = (
        attr.ARCHETYPES + attr.RARE_ARCHETYPES
        + attr.GOALIE_ARCHETYPES + attr.RARE_GOALIE_ARCHETYPES
    )
    for archetype in all_archetypes:
        for rating in archetype.skews:
            assert "fight" not in rating.lower()
            assert "enforcer" not in rating.lower()


# ---------------------------------------------------------------------------
# Role mapping (SIM_SYNERGY_PLAN Phase 0/1 + archetype-refresh round) -- every
# archetype the generator can hand out must map explicitly to a role, or it
# silently falls back to DEFAULT_SKATER_ROLE (a synergy-signal bug that never
# raises). These guards fail loudly when a new archetype is added without a role.
# ---------------------------------------------------------------------------
def test_every_archetype_name_maps_to_a_valid_role():
    all_archetypes = (
        attr.ARCHETYPES + attr.RARE_ARCHETYPES
        + attr.GOALIE_ARCHETYPES + attr.RARE_GOALIE_ARCHETYPES
    )
    for archetype in all_archetypes:
        assert archetype.name in attr.ROLE_FOR_ARCHETYPE, (
            f"{archetype.name} has no ROLE_FOR_ARCHETYPE entry -- it would silently "
            f"fall back to DEFAULT_SKATER_ROLE and lose its synergy identity")
        assert attr.ROLE_FOR_ARCHETYPE[archetype.name] in attr.ALL_ROLES


def test_role_for_archetype_uses_the_stored_mapping_for_forwards():
    # Spot-check the refresh round's role assignments actually route through role_for_archetype.
    assert attr.role_for_archetype("Elite Sniper", "RW") == attr.ROLE_FINISHER
    assert attr.role_for_archetype("Power Winger", "LW") == attr.ROLE_FINISHER
    assert attr.role_for_archetype("Playmaking Juggernaut", "C") == attr.ROLE_PLAYMAKER
    assert attr.role_for_archetype("Offensive Juggernaut", "C") == attr.ROLE_GENERATIONAL
    assert attr.role_for_archetype("Puck-Moving Norris", "D") == attr.ROLE_OFFENSIVE_D
    # Goalies always collapse to ROLE_GOALIE regardless of the (goalie) archetype.
    assert attr.role_for_archetype("Generational Goalie", "G") == attr.ROLE_GOALIE


def test_skater_archetype_skews_reference_only_real_skater_ratings():
    # A skew keyed on a mistyped rating name silently no-ops in generation
    # (_build_calibrated_ratings only applies keys already in the ratings dict),
    # so an identity would quietly vanish. Guard every skater archetype's keys.
    valid = set(attr.ALL_RATINGS)
    for archetype in attr.ARCHETYPES + attr.RARE_ARCHETYPES:
        for rating in archetype.skews:
            assert rating in valid, f"{archetype.name}: unknown skater rating {rating!r}"


def test_goalie_archetype_skews_reference_only_real_goalie_ratings():
    valid = set(attr.ALL_GOALIE_RATINGS)
    for archetype in attr.GOALIE_ARCHETYPES + attr.RARE_GOALIE_ARCHETYPES:
        for rating in archetype.skews:
            assert rating in valid, f"{archetype.name}: unknown goalie rating {rating!r}"
