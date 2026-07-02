"""Tests for the coach line-juggling AI -- DEVPLAN.md Step 2.8 done-criteria.

Covers, in order:
  1. The core done-criterion: a low-``line_juggling_patience`` coach reshuffles a cold
     line/pair combo more readily than a high-patience coach, in a controlled same-seed
     scenario -- driven directly against ``GameSim._maybe_juggle_lines_for_team`` (same "poke
     engine internals directly for a controlled scenario" pattern ``tests/test_goalies.py``
     already uses for pull-the-goalie), first with synthetic extreme patience values (0.0 vs
     1.0 -- a fully deterministic comparison, since patience==1.0 makes ``Rng.chance`` return
     False without even drawing, per ``Rng.chance``'s own early-return), then again with the
     real "Line Blender" (0.1) / "Patient Bencher" (0.95) archetypes from ``models/coach.py``.
  2. A lighter end-to-end sanity check: line-juggling wiring doesn't crash across real full
     games and a genuinely low-patience coach reshuffles at all over enough games (a real-
     gameplay smoke test, not the strict comparison -- that's test group 1's job).
  3. ``models/tactics.py``'s new PP/PK style fields (``pp_style``/``pk_aggression``) round-trip
     through ``Tactics.to_dict()``/``from_dict()``/``cycle()`` like ``forecheck_style`` always
     has, and ``models/team.py``'s ``Team.tactics`` now carries a real ``Tactics`` instance
     through a full to_dict()/from_dict() round trip (it used to be a bare dict placeholder).
"""
from __future__ import annotations

from pucksim.gen.leaguegen import build_world
from pucksim.models.coach import Coach, CoachProfile, profile_for
from pucksim.models.tactics import SETTINGS, Tactics
from pucksim.models.team import Team
from pucksim.sim.engine import GameSim


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sim_with_home_patience(seed: int, patience: float, name: str = "Test Coach") -> GameSim:
    """A GameSim (on-ice groups already populated) whose HOME team's coach has
    ``line_juggling_patience`` overridden to ``patience``, everything else left at Balanced
    defaults -- isolates the ONE knob this step's mechanic consumes.

    Sets ``_TeamState.coach_profile`` DIRECTLY rather than round-tripping through
    ``Coach.to_dict()``/``from_dict()``: ``Coach.to_dict()`` only ever serializes the
    ARCHETYPE NAME (see ``models/coach.py``), so a custom, not-in-``ARCHETYPES`` profile
    built just for a test would silently resolve back to the ``Balanced`` fallback on
    ``from_dict()`` (``profile_for()``'s documented never-crash-on-unknown-name behavior) --
    fine for this codebase's real save-loading path, but it would silently defeat a test that
    specifically needs a non-Balanced ``line_juggling_patience`` (e.g. the 0.0/1.0 extremes
    below), so this helper skips that round trip and assigns the live profile straight onto
    ``_TeamState.coach_profile``, exactly like ``_resolve_coach_profile`` would have produced
    had the profile actually been a registered archetype.
    """
    profile = CoachProfile(name=name, weight=1.0, line_juggling_patience=patience)
    return _sim_with_home_profile(seed, profile)


def _sim_with_home_profile(seed: int, profile: CoachProfile) -> GameSim:
    """As ``_sim_with_home_patience``, but takes an already-built ``CoachProfile`` (e.g. a real
    named archetype from ``models/coach.py``) rather than constructing a synthetic one."""
    world = build_world(seed=seed)
    tids = sorted(world.teams.keys())
    sim = GameSim(world, tids[0], tids[1])
    sim._advance_shift_for_all()   # populate on-ice groups / _current_line_idx, etc.
    sim.home.coach_profile = profile
    return sim


def _force_all_combos_cold(sim: GameSim) -> None:
    """Force every forward-line-slot/D-pair-slot on the home team to a deeply cold on-ice
    goal differential -- well past ``COMBO_COLD_GOAL_DIFF_THRESHOLD`` -- so every eligible slot
    is reshuffle-eligible on the next intermission check."""
    state = sim.home
    for idx in range(len(state.team.lines)):
        state.line_combo_diff[idx] = -5.0
    for idx in range(len(state.team.pairs)):
        state.pair_combo_diff[idx] = -5.0


# ---------------------------------------------------------------------------
# 1a. Deterministic extremes: patience 0.0 vs 1.0.
# ---------------------------------------------------------------------------
def test_zero_patience_reshuffles_readily_while_full_patience_never_does():
    """patience == 1.0 must NEVER reshuffle (LINE_JUGGLE_BASE_RESHUFFLE_CHANCE * (1 - 1.0) == 0,
    and Rng.chance(0) returns False outright, no draw consumed -- fully deterministic, zero
    flake risk). patience == 0.0 reshuffles with probability 0.9 per cold slot per intermission
    check; forcing ALL line/pair slots cold every trial and running enough trials makes "at
    least one reshuffle happens" a near-certainty (with ~7 cold slots/trial at p=0.9,
    P(zero reshuffles in one trial) < 1e-6) without relying on a lucky single roll.
    """
    low = _sim_with_home_patience(seed=42, patience=0.0)
    high = _sim_with_home_patience(seed=42, patience=1.0)

    trials = 20
    for _ in range(trials):
        _force_all_combos_cold(low)
        low._maybe_juggle_lines_for_team(low.home)

        _force_all_combos_cold(high)
        high._maybe_juggle_lines_for_team(high.home)

    assert high.home.reshuffle_count == 0, (
        "a patience==1.0 coach must never reshuffle, even after repeated cold stretches"
    )
    assert low.home.reshuffle_count > 0, (
        "a patience==0.0 coach should have reshuffled at least once across 20 forced-cold trials"
    )
    assert low.home.reshuffle_count > high.home.reshuffle_count


# ---------------------------------------------------------------------------
# 1b. Real archetypes: "Line Blender" (0.1) vs "Patient Bencher" (0.95).
# ---------------------------------------------------------------------------
def test_line_blender_archetype_reshuffles_more_than_patient_bencher_archetype():
    """Same controlled scenario as above, but using the actual named archetypes from
    models/coach.py rather than synthetic profiles -- confirms the real per-archetype
    line_juggling_patience values (0.1 vs 0.95, both already committed since Step 1.10)
    actually drive materially different reshuffle behavior now that this step wires the
    knob to a real consumer."""
    blender_profile = profile_for("Line Blender")
    bencher_profile = profile_for("Patient Bencher")
    assert blender_profile.line_juggling_patience < bencher_profile.line_juggling_patience

    low = _sim_with_home_profile(seed=7, profile=blender_profile)
    high = _sim_with_home_profile(seed=7, profile=bencher_profile)

    trials = 40
    for _ in range(trials):
        _force_all_combos_cold(low)
        low._maybe_juggle_lines_for_team(low.home)

        _force_all_combos_cold(high)
        high._maybe_juggle_lines_for_team(high.home)

    assert low.home.reshuffle_count > high.home.reshuffle_count


# ---------------------------------------------------------------------------
# 1c. Combo tracking sanity: a 5v5 goal actually moves the tracker, a reshuffle resets it.
# ---------------------------------------------------------------------------
def test_score_goal_updates_combo_diff_and_reshuffle_resets_swapped_slots():
    sim = _sim_with_home_patience(seed=3, patience=0.5)
    home, away = sim.home, sim.away
    assert home.line_combo_diff == {}
    assert home._current_line_idx == 0
    assert home._current_pair_idx == 0

    shooter = home.players[home.on_ice[0]]
    goalie = away.goalie()
    sim._score_goal(home, away, shooter, goalie, "slot", "wrist", rush=False, rebound=False)

    # Home scored at 5v5 -- their current line/pair slot should be credited +1, away's debited -1.
    assert home.line_combo_diff.get(home._current_line_idx) == 1.0
    assert home.pair_combo_diff.get(home._current_pair_idx) == 1.0
    assert away.line_combo_diff.get(away._current_line_idx) == -1.0
    assert away.pair_combo_diff.get(away._current_pair_idx) == -1.0

    # Force that same home line slot cold and reshuffle it directly -- its tracker must reset.
    cold_idx = home._current_line_idx
    home.line_combo_diff[cold_idx] = -5.0
    before_lines = [list(line) for line in home.team.lines]
    sim._swap_line_slot(home, cold_idx)
    assert home.line_combo_diff[cold_idx] == 0.0
    assert home.reshuffle_count == 1
    assert home.team.lines != before_lines  # personnel actually changed somewhere


# ---------------------------------------------------------------------------
# 2. End-to-end sanity: real full games, wiring doesn't crash, low patience fires in practice.
# ---------------------------------------------------------------------------
def test_full_games_do_not_crash_and_low_patience_coach_reshuffles_in_real_play():
    """Play several real full games (via GameSim.play(), not just the direct trigger call) with
    the home team coached by the most reactive archetype available (Line Blender,
    patience=0.1) and confirm: (a) nothing crashes, (b) across enough real games the mechanism
    actually fires at least once -- proving the intermission wiring (``_play_period`` ->
    ``_maybe_juggle_lines_for_all``) is really connected, not just the direct-call path tested
    above."""
    world = build_world(seed=99)
    tids = sorted(world.teams.keys())
    home_tid, away_tid = tids[0], tids[1]

    blender_profile = profile_for("Line Blender")
    total_reshuffles = 0
    for i in range(15):
        sim = GameSim(world, home_tid, away_tid)
        sim.home.team.coach = Coach(cid=999, name="Line Blender",
                                    profile=blender_profile).to_dict()
        sim.home.coach_profile = sim.home._resolve_coach_profile(sim.home.team)
        result = sim.play()
        assert result.home_score >= 0 and result.away_score >= 0
        total_reshuffles += sim.home.reshuffle_count

    assert total_reshuffles >= 0   # never negative / never crashes (sanity floor)
    # Real gameplay is stochastic, but 15 full games' worth of intermission checks for the
    # most reactive archetype should trigger the mechanism at least once in the overwhelming
    # majority of runs; this is a real-gameplay smoke test, not the strict comparison (that's
    # test group 1's job), so failure here would point at a wiring regression, not noise.
    assert total_reshuffles > 0


# ---------------------------------------------------------------------------
# 3. tactics.py PP/PK extension + Team.tactics real-instance wiring.
# ---------------------------------------------------------------------------
def test_tactics_pp_and_pk_fields_exist_with_sane_defaults():
    t = Tactics()
    assert t.pp_style in SETTINGS["pp_style"]
    assert t.pk_aggression in SETTINGS["pk_aggression"]
    assert "pp_style" in SETTINGS and "pk_aggression" in SETTINGS


def test_tactics_cycle_and_round_trip_cover_new_fields():
    t = Tactics()
    start = t.pp_style
    t.cycle("pp_style")
    assert t.pp_style != start
    assert t.pp_style in SETTINGS["pp_style"]

    t.pk_aggression = "aggressive"
    d = t.to_dict()
    assert d["pp_style"] == t.pp_style
    assert d["pk_aggression"] == "aggressive"

    restored = Tactics.from_dict(d)
    assert restored.pp_style == t.pp_style
    assert restored.pk_aggression == "aggressive"


def test_tactics_from_dict_falls_back_on_invalid_pp_style():
    restored = Tactics.from_dict({"pp_style": "not-a-real-option", "forecheck_style": "aggressive"})
    assert restored.pp_style == Tactics().pp_style   # falls back to the field default
    assert restored.forecheck_style == "aggressive"  # valid values still pass through


def test_team_tactics_is_a_real_instance_after_generation():
    world = build_world(seed=5)
    for team in world.teams.values():
        assert isinstance(team.tactics, Tactics)


def test_team_tactics_round_trips_as_a_real_tactics_instance():
    team = Team(tid=0, name="Test", abbrev="TST", conference="East")
    team.tactics = Tactics(forecheck_style="aggressive", pp_style="spread",
                            pk_aggression="passive")
    d = team.to_dict()
    assert d["tactics"] == {"forecheck_style": "aggressive", "pp_style": "spread",
                            "pk_aggression": "passive"}

    restored = Team.from_dict(d)
    assert isinstance(restored.tactics, Tactics)
    assert restored.tactics.forecheck_style == "aggressive"
    assert restored.tactics.pp_style == "spread"
    assert restored.tactics.pk_aggression == "passive"


def test_team_tactics_none_still_round_trips_as_none():
    """A bare Team() with no tactics assigned yet must still round-trip as None -- Team.tactics
    is Optional[Tactics], not a mandatory field (see tests/test_team.py's identical pre-existing
    coverage for the ``coach`` field, which stays a dict placeholder)."""
    team = Team(tid=1, name="Test2", abbrev="TS2", conference="West")
    d = team.to_dict()
    assert d["tactics"] is None
    restored = Team.from_dict(d)
    assert restored.tactics is None
