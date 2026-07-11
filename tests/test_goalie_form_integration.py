"""Integration coverage for goalie season-form (DEVPLAN.md Step 2.7) actually reaching the sim.

``tests/test_development.py`` already proves the form mechanic in isolation (symmetric scatter,
consistency-driven spread, can exceed 1.0, permanent-rating-safe). What THIS module proves is the
wiring added when form was threaded through ``simulate_game`` -> ``GameSim`` -> ``_goalie_skill``:
that a goalie's per-season form multiplier measurably moves save outcomes in the right direction,
and that the default (no form state) path is unchanged.
"""
from __future__ import annotations

from pucksim.gen.leaguegen import build_world
from pucksim.sim.engine import GameSim, simulate_game
from pucksim.systems.development import GoalieFormState


def _uniform_form(world, value: float) -> GoalieFormState:
    """A GoalieFormState that puts every goalie in the league at the same form ``value``."""
    state = GoalieFormState()
    for p in world.players.values():
        if p.is_goalie:
            state.form[p.pid] = value
    return state


def _total_goals(seed: int, *, form_value: float | None, n_games: int = 40) -> int:
    """Sim ``n_games`` fresh games at ``seed`` and total both teams' goals. Each game rebuilds
    the World from the same seed so the only varying input across the two calls is form."""
    total = 0
    for g in range(n_games):
        world = build_world(seed=seed + g)
        tids = sorted(world.teams.keys())
        form_state = None if form_value is None else _uniform_form(world, form_value)
        result = simulate_game(world, tids[0], tids[1], form_state=form_state)
        total += result.home_score + result.away_score
    return total


def test_high_form_goalies_allow_fewer_goals_than_low_form_goalies():
    """The load-bearing integration assertion: a league of red-hot goalies (form at the 1.40
    ceiling) surrenders materially fewer goals than a league of ice-cold ones (form at the 0.60
    floor), holding teams/seeds fixed. Proves ``_goalie_skill`` folds form into the save gap."""
    hot = _total_goals(1000, form_value=1.40)
    cold = _total_goals(1000, form_value=0.60)
    assert hot < cold, f"hot-goalie league scored {hot}, cold-goalie league scored {cold}"


def test_baseline_form_matches_no_form_state():
    """Form at exactly 1.0 (baseline) must be indistinguishable from passing no form state at
    all -- the ``form_state is None`` fast path and an all-1.0 state are the same physics."""
    none_goals = _total_goals(2000, form_value=None)
    baseline_goals = _total_goals(2000, form_value=1.0)
    assert none_goals == baseline_goals


def test_form_state_is_optional_and_defaults_to_no_effect():
    """A one-off GameSim with no form_state still runs and is deterministic -- the additive
    extension must not perturb the existing default sim path."""
    world_a = build_world(seed=7)
    world_b = build_world(seed=7)
    tids = sorted(world_a.teams.keys())
    ra = GameSim(world_a, tids[0], tids[1]).play()
    rb = GameSim(world_b, tids[0], tids[1], form_state=None).play()
    assert (ra.home_score, ra.away_score) == (rb.home_score, rb.away_score)
