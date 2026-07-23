"""Tests for pucksim.models.player -- Step 1.6 done-criteria."""
from __future__ import annotations

import pytest

from pucksim.config import RATING_MAX, RATING_MIN
from pucksim.models import attributes as attr
from pucksim.models.contract import flat_contract
from pucksim.models.player import Injury, Player
from pucksim.models.stats import GoalieStatLine, SkaterStatLine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _skater_ratings(value: int = 70) -> dict:
    return {name: value for name in attr.ALL_RATINGS}


def _goalie_ratings(value: int = 70) -> dict:
    return {name: value for name in attr.ALL_GOALIE_RATINGS}


def make_skater(**overrides) -> Player:
    kwargs = dict(
        pid=1,
        name="Connor Test",
        age=24,
        position="C",
        ratings=_skater_ratings(75),
        potential=80,
        scout_error=0.0,
    )
    kwargs.update(overrides)
    return Player(**kwargs)


def make_goalie(**overrides) -> Player:
    kwargs = dict(
        pid=2,
        name="Gordie Netminder",
        age=27,
        position="G",
        ratings=_goalie_ratings(72),
        potential=78,
        scout_error=0.0,
    )
    kwargs.update(overrides)
    return Player(**kwargs)


# ---------------------------------------------------------------------------
# Construction & stat-line dispatch
# ---------------------------------------------------------------------------
def test_skater_gets_skater_stat_line_by_default():
    p = make_skater()
    assert isinstance(p.season, SkaterStatLine)
    assert isinstance(p.playoffs, SkaterStatLine)
    assert p.is_goalie is False


def test_goalie_gets_goalie_stat_line_by_default():
    p = make_goalie()
    assert isinstance(p.season, GoalieStatLine)
    assert isinstance(p.playoffs, GoalieStatLine)
    assert p.is_goalie is True


# ---------------------------------------------------------------------------
# overall()
# ---------------------------------------------------------------------------
def test_overall_in_range_and_differs_sensibly_by_position():
    skater = make_skater(ratings=_skater_ratings(70))
    goalie = make_goalie(ratings=_goalie_ratings(70))

    assert RATING_MIN <= skater.overall <= RATING_MAX
    assert RATING_MIN <= goalie.overall <= RATING_MAX

    # Bumping a skater-only rating should not move a goalie's overall, and
    # vice versa -- confirms overall() is dispatching on the right vocabulary
    # per position rather than blending across both.
    goalie_ratings_with_skater_noise = _goalie_ratings(70)
    goalie_ratings_with_skater_noise["shot_accuracy"] = 99
    goalie_same = make_goalie(ratings=goalie_ratings_with_skater_noise)
    assert goalie_same.overall == goalie.overall

    skater_ratings_with_goalie_noise = _skater_ratings(70)
    skater_ratings_with_goalie_noise["reflexes"] = 99
    skater_same = make_skater(ratings=skater_ratings_with_goalie_noise)
    assert skater_same.overall == skater.overall


def test_overall_increases_with_ratings_for_both_positions():
    low_skater = make_skater(ratings=_skater_ratings(RATING_MIN))
    high_skater = make_skater(ratings=_skater_ratings(RATING_MAX))
    assert low_skater.overall < high_skater.overall

    low_goalie = make_goalie(ratings=_goalie_ratings(RATING_MIN))
    high_goalie = make_goalie(ratings=_goalie_ratings(RATING_MAX))
    assert low_goalie.overall < high_goalie.overall


# ---------------------------------------------------------------------------
# to_dict()/from_dict() round trip -- both position types
# ---------------------------------------------------------------------------
def test_skater_round_trip_preserves_stat_line_type_and_values():
    p = make_skater(contract=flat_contract(1_000_000, 2))
    p.season.g = 12
    p.season.a = 20
    p.season.sog = 150
    p.playoffs.g = 3

    d = p.to_dict()
    restored = Player.from_dict(d)

    assert isinstance(restored.season, SkaterStatLine)
    assert isinstance(restored.playoffs, SkaterStatLine)
    assert restored.season.g == 12
    assert restored.season.a == 20
    assert restored.season.sog == 150
    assert restored.season.points == 32
    assert restored.playoffs.g == 3

    assert restored.pid == p.pid
    assert restored.name == p.name
    assert restored.age == p.age
    assert restored.position == p.position
    assert restored.ratings == p.ratings
    assert restored.potential == p.potential
    assert restored.overall == p.overall
    assert restored.contract.salaries == [1_000_000, 1_000_000]


def test_goalie_round_trip_preserves_stat_line_type_and_values():
    p = make_goalie()
    p.season.shots_faced = 300
    p.season.saves = 280
    p.season.goals_against = 20
    p.season.wins = 15

    d = p.to_dict()
    restored = Player.from_dict(d)

    assert isinstance(restored.season, GoalieStatLine)
    assert isinstance(restored.playoffs, GoalieStatLine)
    assert restored.season.shots_faced == 300
    assert restored.season.saves == 280
    assert restored.season.goals_against == 20
    assert restored.season.wins == 15
    assert restored.season.save_pct == pytest.approx(280 / 300)

    assert restored.position == "G"
    assert restored.ratings == p.ratings
    assert restored.overall == p.overall


def test_round_trip_preserves_free_agent_vs_signed_team_id():
    fa = make_skater(team_id=None)
    assert fa.is_free_agent is True
    restored_fa = Player.from_dict(fa.to_dict())
    assert restored_fa.is_free_agent is True
    assert restored_fa.team_id is None

    signed = make_skater(team_id=7)
    assert signed.is_free_agent is False
    restored_signed = Player.from_dict(signed.to_dict())
    assert restored_signed.team_id == 7
    assert restored_signed.is_free_agent is False


def test_round_trip_preserves_pre_draft_and_draft_bio():
    p = make_skater(
        pre_draft={"league": "OHL", "gp": 60, "pts": 90},
        draft={"year": 2024, "round": 1, "pick": 5, "team": 3},
    )
    restored = Player.from_dict(p.to_dict())
    assert restored.pre_draft == {"league": "OHL", "gp": 60, "pts": 90}
    assert restored.draft == {"year": 2024, "round": 1, "pick": 5, "team": 3}


def test_round_trip_preserves_development_record():
    """The development dict is the prospect round's whole state (docs/PROSPECT_DEV_PLAN.md)
    -- if it doesn't survive a save it takes every prospect in the league with it."""
    p = make_skater(
        age=18,
        development={"tier": "chl", "seasons": 1, "tier_seasons": 1,
                      "rights_tid": 4, "rights_expire": 2033,
                      "line": {"gp": 58, "g": 31, "a": 44}},
    )
    restored = Player.from_dict(p.to_dict())
    assert restored.development == p.development
    assert restored.is_prospect is True


def test_players_outside_the_development_system_round_trip_as_none():
    """Old saves (and every established NHL player) carry no development record."""
    p = make_skater()
    assert p.development is None
    assert p.is_prospect is False
    restored = Player.from_dict(p.to_dict())
    assert restored.development is None
    assert restored.is_prospect is False


def test_from_dict_defaults_development_on_a_pre_prospect_round_save():
    """A save written before Player.development existed has no such key at all."""
    legacy = make_skater().to_dict()
    del legacy["development"]
    restored = Player.from_dict(legacy)
    assert restored.development is None
    assert restored.is_prospect is False


def test_development_record_is_copied_not_aliased_on_serialization():
    """to_dict/from_dict must hand back an independent dict, same as draft/pre_draft --
    a shared reference would let a restored World mutate the one it was loaded from."""
    p = make_skater(development={"tier": "ncaa", "seasons": 0, "tier_seasons": 0,
                                  "rights_tid": None, "rights_expire": None, "line": {}})
    d = p.to_dict()
    d["development"]["tier"] = "ahl"
    assert p.development["tier"] == "ncaa"

    restored = Player.from_dict(d)
    restored.development["tier"] = "europe"
    assert d["development"]["tier"] == "ahl"


def test_a_prospect_is_also_a_free_agent():
    """Prospects hold no NHL roster spot and deliberately stay in World.free_agents --
    is_prospect is the data question, not the "may he be signed" rules question."""
    p = make_skater(team_id=None, development={"tier": "chl", "seasons": 0,
                                                "tier_seasons": 0, "rights_tid": 2,
                                                "rights_expire": 2032, "line": {}})
    assert p.is_prospect is True
    assert p.is_free_agent is True


def test_round_trip_preserves_career_and_accolades():
    p = make_skater()
    p.career.append({"season": 2023, "g": 30, "a": 40})
    p.accolades["hart"] = 1
    restored = Player.from_dict(p.to_dict())
    assert restored.career == [{"season": 2023, "g": 30, "a": 40}]
    assert restored.accolades == {"hart": 1}


# ---------------------------------------------------------------------------
# Injury-driven properties
# ---------------------------------------------------------------------------
def test_no_injury_is_available():
    p = make_skater()
    assert p.injury is None
    assert p.is_injured is False
    assert p.available is True


def test_active_injury_marks_unavailable():
    p = make_skater(injury=Injury("Sprained knee", games_remaining=5, severity="moderate"))
    assert p.is_injured is True
    assert p.available is False


def test_injury_with_zero_games_remaining_is_not_injured():
    # Edge case: an Injury object still attached but healed (games_remaining
    # ticked down to 0) should read as not-injured/available.
    p = make_skater(injury=Injury("Bruised hand", games_remaining=0, severity="minor"))
    assert p.is_injured is False
    assert p.available is True


def test_injury_round_trips():
    p = make_skater(injury=Injury("Concussion", games_remaining=10, severity="major"))
    restored = Player.from_dict(p.to_dict())
    assert restored.injury is not None
    assert restored.injury.description == "Concussion"
    assert restored.injury.games_remaining == 10
    assert restored.injury.severity == "major"

    healthy = make_skater()
    restored_healthy = Player.from_dict(healthy.to_dict())
    assert restored_healthy.injury is None


# ---------------------------------------------------------------------------
# scouted_potential()
# ---------------------------------------------------------------------------
def test_scouted_potential_differs_from_raw_when_scout_error_nonzero():
    p = make_skater(potential=80, scout_error=10.0, ratings=_skater_ratings(50))
    assert p.scouted_potential() != p.potential
    assert p.scouted_potential() == min(99, 90)


def test_scouted_potential_matches_potential_when_scout_error_zero_and_above_overall():
    p = make_skater(potential=80, scout_error=0.0, ratings=_skater_ratings(50))
    assert p.overall < 80
    assert p.scouted_potential() == 80


def test_scouted_potential_converges_toward_true_potential_as_scout_error_shrinks():
    ratings = _skater_ratings(50)
    true_potential = 85

    far_off = make_skater(potential=true_potential, scout_error=14.0, ratings=ratings)
    closer = make_skater(potential=true_potential, scout_error=4.0, ratings=ratings)
    exact = make_skater(potential=true_potential, scout_error=0.0, ratings=ratings)

    assert abs(far_off.scouted_potential() - true_potential) > abs(
        closer.scouted_potential() - true_potential
    )
    assert abs(closer.scouted_potential() - true_potential) >= abs(
        exact.scouted_potential() - true_potential
    )
    assert exact.scouted_potential() == true_potential


def test_scouted_potential_never_below_overall_and_never_above_99():
    # Large negative scout_error should still not report below current overall.
    p = make_skater(potential=40, scout_error=-30.0, ratings=_skater_ratings(90))
    assert p.scouted_potential() >= p.overall

    # Large positive scout_error should clamp at 99.
    p2 = make_skater(potential=95, scout_error=50.0, ratings=_skater_ratings(50))
    assert p2.scouted_potential() == 99


# ---------------------------------------------------------------------------
# Misc identity properties
# ---------------------------------------------------------------------------
def test_short_name():
    p = make_skater(name="Connor McDavid")
    assert p.short_name == "C. McDavid"


def test_rating_safe_lookup_with_default():
    p = make_skater(ratings={"skating": 80})
    assert p.rating("skating") == 80
    assert p.rating("nonexistent_key") == RATING_MIN
    assert p.rating("nonexistent_key", default=50) == 50


def test_default_contract_is_free_agent_shape():
    p = make_skater()
    assert p.contract.salaries == []
    assert p.contract.years_remaining == 0


# ---------------------------------------------------------------------------
# Handedness (shoots)
# ---------------------------------------------------------------------------
def test_shoots_defaults_to_left():
    p = make_skater()
    assert p.shoots == "L"


def test_shoots_round_trips():
    p = make_skater(shoots="R")
    restored = Player.from_dict(p.to_dict())
    assert restored.shoots == "R"
