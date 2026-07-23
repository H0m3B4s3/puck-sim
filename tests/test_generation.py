"""Tests for pucksim.gen -- Step 1.11 done-criteria.

This step is the integration test of every model file built so far: it
exercises attributes.py, contract.py, player.py, team.py (roster + auto line-
builder), coach.py, and world.py all at once via `build_world()`.
"""
from __future__ import annotations

import re

from pucksim import config
from pucksim.gen import playergen
from pucksim.gen.leaguegen import build_world
from pucksim.models import attributes as attr
from pucksim.rng import Rng


# ---------------------------------------------------------------------------
# League shape
# ---------------------------------------------------------------------------
def test_build_world_produces_correct_team_count():
    world = build_world(seed=42)
    assert len(world.teams) == config.NUM_TEAMS


def test_teams_distributed_across_conferences_and_divisions():
    world = build_world(seed=42)
    by_conf = {}
    by_div = {}
    for team in world.teams.values():
        by_conf.setdefault(team.conference, []).append(team)
        by_div.setdefault((team.conference, team.division), []).append(team)

    assert set(by_conf.keys()) == set(config.CONFERENCES)
    for conf, teams in by_conf.items():
        assert len(teams) == config.TEAMS_PER_CONFERENCE

    assert len(by_div) == len(config.CONFERENCES) * config.DIVISIONS_PER_CONFERENCE
    for key, teams in by_div.items():
        assert len(teams) == config.TEAMS_PER_DIVISION


# ---------------------------------------------------------------------------
# Roster legality
# ---------------------------------------------------------------------------
def test_every_team_has_legal_roster_size():
    world = build_world(seed=42)
    for team in world.teams.values():
        skaters = [pid for pid in team.roster if world.player(pid).position != "G"]
        goalies = [pid for pid in team.roster if world.player(pid).position == "G"]

        assert config.SKATERS_MIN <= len(skaters) <= config.SKATERS_MAX
        assert config.GOALIES_MIN <= len(goalies) <= config.GOALIES_MAX
        assert len(goalies) >= 2
        assert config.ROSTER_MIN <= len(team.roster) <= config.ROSTER_MAX


def test_roster_membership_consistent_with_player_team_id():
    world = build_world(seed=42)
    for team in world.teams.values():
        for pid in team.roster:
            assert world.player(pid).team_id == team.tid


# ---------------------------------------------------------------------------
# Lines / pairs / goalies
# ---------------------------------------------------------------------------
def test_every_team_has_four_complete_forward_lines():
    world = build_world(seed=42)
    for team in world.teams.values():
        assert len(team.lines) == 4
        for line in team.lines:
            assert len(line) == 3


def test_every_team_has_three_complete_d_pairs():
    world = build_world(seed=42)
    for team in world.teams.values():
        assert len(team.pairs) == 3
        for pair in team.pairs:
            assert len(pair) == 2


def test_every_team_has_goalie_starter_and_backup():
    world = build_world(seed=42)
    for team in world.teams.values():
        assert team.goalie_starter is not None
        assert world.player(team.goalie_starter).position == "G"
        assert team.goalie_backup is not None
        assert world.player(team.goalie_backup).position == "G"
        assert team.goalie_starter != team.goalie_backup


def test_every_team_has_a_coach():
    world = build_world(seed=42)
    for team in world.teams.values():
        assert team.coach is not None
        # Stored as a dict (see leaguegen.py's Team.coach typing note) --
        # a plain dataclass-shaped dict with at least an archetype name.
        assert "archetype" in team.coach


# ---------------------------------------------------------------------------
# Jersey colors (DEVPLAN.md Step 2.9a)
# ---------------------------------------------------------------------------
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def test_every_team_has_valid_hex_jersey_colors():
    world = build_world(seed=42)
    for team in world.teams.values():
        assert _HEX_COLOR_RE.match(team.primary_color), team.primary_color
        assert _HEX_COLOR_RE.match(team.secondary_color), team.secondary_color
        assert team.primary_color != team.secondary_color


def test_every_team_has_a_distinct_color_pair():
    world = build_world(seed=42)
    pairs = {(t.primary_color, t.secondary_color) for t in world.teams.values()}
    assert len(pairs) == len(world.teams)


def test_same_seed_produces_same_jersey_colors():
    world_a = build_world(seed=7)
    world_b = build_world(seed=7)
    colors_a = {tid: (t.primary_color, t.secondary_color) for tid, t in world_a.teams.items()}
    colors_b = {tid: (t.primary_color, t.secondary_color) for tid, t in world_b.teams.items()}
    assert colors_a == colors_b


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
def _serialize_players(world) -> dict:
    return {pid: p.to_dict() for pid, p in world.players.items()}


def _serialize_teams(world) -> dict:
    return {tid: t.to_dict() for tid, t in world.teams.items()}


def test_same_seed_produces_byte_identical_rosters():
    world_a = build_world(seed=42)
    world_b = build_world(seed=42)

    assert _serialize_players(world_a) == _serialize_players(world_b)
    assert _serialize_teams(world_a) == _serialize_teams(world_b)


def test_different_seeds_produce_different_rosters():
    world_a = build_world(seed=1)
    world_b = build_world(seed=2)

    assert _serialize_players(world_a) != _serialize_players(world_b)


# ---------------------------------------------------------------------------
# Overall distribution sanity (loose bounds -- gen tuning parameters, not
# exact-value tests; these are expected to be iterated on later).
# ---------------------------------------------------------------------------
def test_generated_overall_distribution_is_believable():
    world = build_world(seed=42)
    overalls = [p.overall for p in world.players.values()]

    avg = sum(overalls) / len(overalls)
    assert 55 <= avg <= 75

    assert any(o > 80 for o in overalls)
    assert any(o < 55 for o in overalls)

    # Legal rating bounds never violated.
    assert all(config.RATING_MIN <= o <= config.RATING_MAX for o in overalls)


# ---------------------------------------------------------------------------
# Rare/"unicorn" archetype rarity gate (BUG FIX, 2026-07-02 -- see
# gen/playergen.py's _RARE_ARCHETYPE_MIN_OVERALL/_RARE_ARCHETYPE_CHANCE
# comment for the full derivation). attributes.py's RARE_ARCHETYPES
# docstring has always claimed "Generational Forward"/"Unicorn Defenseman"
# are "generated only on elite-ceiling players... and never in the normal
# pool" -- that gate was never actually wired up before this fix, so a
# completely average target_overall had the same shot at "Generational
# Forward" as a true superstar target. These tests pin the fix: (a) a
# below-threshold target_overall can NEVER produce a rare archetype, (b)
# even among elite-ceiling targets the rare archetype is genuinely scarce
# (a small fraction, not a coin flip) -- consistent with the "once a decade
# league-wide" design intent (a Crosby/McDavid-caliber prospect should be
# rare, not common).
# ---------------------------------------------------------------------------
# Rare pool is now several distinct legend styles per position (not one named archetype), so these
# tests detect "landed a rare archetype" by membership in RARE_ARCHETYPES_BY_POSITION rather than a
# single hard-coded name.
_RARE_NAMES_C = {a.name for a in attr.RARE_ARCHETYPES_BY_POSITION["C"]}
_RARE_NAMES_D = {a.name for a in attr.RARE_ARCHETYPES_BY_POSITION["D"]}


def test_rare_archetype_never_rolled_below_elite_ceiling_threshold():
    rng = Rng(seed=100)
    below = playergen._RARE_ARCHETYPE_MIN_OVERALL - 1
    hits = sum(
        1 for _ in range(20_000)
        if playergen._choose_archetype(
            rng, "C", below, attr.ARCHETYPES_BY_POSITION, attr.RARE_ARCHETYPES_BY_POSITION
        ).name in _RARE_NAMES_C
    )
    assert hits == 0


def test_rare_archetype_never_rolled_below_elite_ceiling_threshold_defenseman():
    rng = Rng(seed=101)
    below = playergen._RARE_ARCHETYPE_MIN_OVERALL - 1
    hits = sum(
        1 for _ in range(20_000)
        if playergen._choose_archetype(
            rng, "D", below, attr.ARCHETYPES_BY_POSITION, attr.RARE_ARCHETYPES_BY_POSITION
        ).name in _RARE_NAMES_D
    )
    assert hits == 0


def test_rare_archetype_is_genuinely_scarce_even_at_elite_ceiling():
    """Even a maxed-out target_overall should land the rare archetype only a
    small fraction of the time -- not a coin flip, not "common." Bounds are
    loose (statistical sweep, not an exact-probability test) but rule out
    both "never happens" and "happens constantly."""
    rng = Rng(seed=102)
    elite = 99
    n = 50_000
    hits = sum(
        1 for _ in range(n)
        if playergen._choose_archetype(
            rng, "C", elite, attr.ARCHETYPES_BY_POSITION, attr.RARE_ARCHETYPES_BY_POSITION
        ).name in _RARE_NAMES_C
    )
    frac = hits / n
    assert 0.0 < frac < 0.10   # genuinely rare even among the best prospects


def test_rare_archetype_chance_matches_documented_value_at_elite_ceiling():
    """The elite-ceiling roll itself should land close to the documented
    _RARE_ARCHETYPE_CHANCE (2.5%, derived in playergen.py's module comment to
    target roughly once per decade of combined leaguegen + draft-class
    generation volume) -- pins the exact tunable, not just "somewhere
    small," so a future change to the constant is caught here."""
    rng = Rng(seed=103)
    elite = playergen._RARE_ARCHETYPE_MIN_OVERALL
    n = 100_000
    hits = sum(
        1 for _ in range(n)
        if playergen._choose_archetype(
            rng, "C", elite, attr.ARCHETYPES_BY_POSITION, attr.RARE_ARCHETYPES_BY_POSITION
        ).name in _RARE_NAMES_C
    )
    frac = hits / n
    assert abs(frac - playergen._RARE_ARCHETYPE_CHANCE) < 0.01


def test_generate_skater_end_to_end_respects_the_gate():
    """Integration check through the full generate_skater() pipeline (not just
    the internal _choose_archetype helper): a below-threshold target_overall
    generated many times should never crash and should stay within legal
    rating bounds across the gate boundary -- exact archetype-name detection
    is covered by the _choose_archetype-level tests above (which are exact
    rather than inferred from ratings, since Archetype identity isn't stored
    on the returned Player)."""
    rng = Rng(seed=104)
    below_players = [
        playergen.generate_skater(i, rng, age=25, target_overall=70, position="C")
        for i in range(500)
    ]
    assert len(below_players) == 500
    assert all(config.RATING_MIN <= p.overall <= config.RATING_MAX for p in below_players)


# ---------------------------------------------------------------------------
# Overall-weighted archetype selection (archetype-refresh round, Phase B) -- scorers should
# concentrate at high target overall (top-6), checking/physical depth at low target (bottom-6).
# It is a LEAN, not a hard rule, so these assert directional shifts, not thresholds.
# ---------------------------------------------------------------------------
def test_archetype_weight_blends_by_target_overall():
    # At a high target, a scorer outweighs a grinder; at a low target, the reverse.
    assert playergen._archetype_weight("Sniper", 80) > playergen._archetype_weight("Grinder", 80)
    assert playergen._archetype_weight("Grinder", 58) > playergen._archetype_weight("Sniper", 58)
    # A given archetype's scorer weight rises with target; a grinder's falls.
    assert (playergen._archetype_weight("Sniper", 80)
            > playergen._archetype_weight("Sniper", 58))
    assert (playergen._archetype_weight("Grinder", 58)
            > playergen._archetype_weight("Grinder", 80))
    # Unlisted archetypes (e.g. any goalie archetype) fall back to a flat, target-independent weight.
    assert (playergen._archetype_weight("Reflex Goalie", 80)
            == playergen._archetype_weight("Reflex Goalie", 58)
            == 1.0)


def _archetype_share(rng, position, target, names, n=20_000):
    hits = sum(
        1 for _ in range(n)
        if playergen._choose_archetype(
            rng, position, target, attr.ARCHETYPES_BY_POSITION, attr.RARE_ARCHETYPES_BY_POSITION
        ).name in names
    )
    return hits / n


def test_scoring_archetypes_concentrate_at_high_overall():
    rng = Rng(seed=200)
    scoring = {"Sniper", "Pass-First Winger", "Speedster", "Power Winger"}
    depth = {"Grinder", "Power Forward", "Enforcer-Physical"}
    # target 80 stays just under the OVR-82 rare gate, so no rare archetypes leak into the counts.
    hi_scoring = _archetype_share(rng, "LW", 80, scoring)
    lo_scoring = _archetype_share(rng, "LW", 58, scoring)
    hi_depth = _archetype_share(rng, "LW", 80, depth)
    lo_depth = _archetype_share(rng, "LW", 58, depth)
    assert hi_scoring > lo_scoring          # scorers cluster in the top-6
    assert lo_depth > hi_depth              # grinders/physical cluster in the bottom-6
    assert hi_scoring > hi_depth            # a top-line slot is scorer-dominated
    assert lo_depth > lo_scoring            # a 4th-line slot is depth-dominated


def test_every_normal_archetype_has_a_selection_weight():
    # Guard: a new normal archetype without a weight silently falls back to flat (1,1), quietly
    # undoing the top-6/bottom-6 lean for that archetype. Fail loudly instead.
    for arch in attr.ARCHETYPES:
        assert arch.name in playergen._ARCHETYPE_SELECTION_WEIGHTS, (
            f"{arch.name} has no _ARCHETYPE_SELECTION_WEIGHTS entry")


# ---------------------------------------------------------------------------
# Skew-preserving calibration (archetype-refresh round, Phase C) -- archetype identity must
# survive at high target overall, where the old uniform-nudge calibration filled in the intended
# holes (a 93-overall "Grinder" ended up with real offense). Averaged over many samples so the
# assertions are on the stable mean, not one noisy baseline draw.
# ---------------------------------------------------------------------------
def _mean_composites(archetype_name, position, target, n=300):
    rng = Rng(seed=900)
    arch = next(a for a in attr.ARCHETYPES if a.name == archetype_name)
    sums = {c: 0.0 for c in attr.COMPOSITES}
    ovr = 0.0
    for _ in range(n):
        ratings = playergen._build_calibrated_ratings(rng, position, target, attr.ALL_RATINGS, arch)
        cc = attr.all_composites(ratings)
        for c in attr.COMPOSITES:
            sums[c] += cc[c]
        ovr += attr.overall(position, ratings)
    return {c: sums[c] / n for c in attr.COMPOSITES}, ovr / n


def test_calibration_preserves_grinder_identity_at_high_overall():
    comps, _ = _mean_composites("Grinder", "C", target=90)
    offense = max(comps["scoring"], comps["playmaking_c"])
    # A 90-target grinder must still read as defense/physical-first, not a scoring line -- the
    # defensive composites clearly outrank the offensive ones (this failed under the old washout).
    assert comps["defense"] - offense >= 8.0
    assert comps["physicality"] - offense >= 6.0


def test_calibration_preserves_sniper_identity_at_high_overall():
    comps, _ = _mean_composites("Sniper", "C", target=90)
    # An elite sniper's shooting stays elite and clearly outranks his (intentionally weak) defense.
    assert comps["scoring"] >= 93.0
    assert comps["scoring"] - comps["defense"] >= 8.0


def test_calibration_lands_near_target_for_balanced_archetype():
    # A near-neutral archetype (few, small skews) should still calibrate right onto the target.
    _, ovr = _mean_composites("Two-Way Forward", "C", target=82)
    assert abs(ovr - 82) <= 2.0


def test_calibration_does_not_inflate_negative_skew_archetype_above_target():
    # The fix must never fill a grinder's holes to overshoot the target -- its offensive holes cap
    # the achievable overall, so it lands at or below target, never above.
    _, ovr = _mean_composites("Grinder", "C", target=88)
    assert ovr <= 88 + 1.5


# ---------------------------------------------------------------------------
# gk_consistency generation-time rarity gate (DEVPLAN.md Step 2.7, "Generation-time rarity
# correlation") -- companion mechanism to the rare-archetype gate above, on a DIFFERENT axis
# (a single rating's resample band, not archetype choice). See
# playergen._apply_gk_consistency_rarity_gate / _GK_HIGH_SKILL_THRESHOLD /
# _GK_RELIABILITY_ROLL_CHANCE for the full mechanism and documented derivation.
# ---------------------------------------------------------------------------
def _high_skill_high_consistency(p) -> bool:
    return (p.overall >= playergen._GK_HIGH_SKILL_THRESHOLD
            and p.ratings["gk_consistency"] >= playergen._GK_CONSISTENCY_ELITE_MIN)


def _high_skill(p) -> bool:
    return p.overall >= playergen._GK_HIGH_SKILL_THRESHOLD


def _high_consistency(p) -> bool:
    return p.ratings["gk_consistency"] >= playergen._GK_CONSISTENCY_ELITE_MIN


def test_gk_consistency_below_high_skill_threshold_is_never_gated():
    """Below the high-skill threshold, gk_consistency must be sampled normally/independently --
    it should be reachable ANYWHERE across the legal rating range, not confined to the gate's
    'common' band, since no gating applies down there."""
    rng = Rng(seed=200)
    below_target = playergen._GK_HIGH_SKILL_THRESHOLD - 20   # comfortably below the gate
    values = []
    for i in range(300):
        g = playergen.generate_goalie(i, rng, age=27, target_overall=below_target)
        if g.overall < playergen._GK_HIGH_SKILL_THRESHOLD:   # post-calibration overall can drift
            values.append(g.ratings["gk_consistency"])
    assert values   # sanity: the below-threshold branch was actually exercised
    # Should see values ABOVE the gate's "common" band ceiling somewhere in an ungated sample --
    # proving gk_consistency isn't being silently capped even when the gate shouldn't apply.
    assert any(v > playergen._GK_CONSISTENCY_COMMON_MAX for v in values)


def test_gk_consistency_at_high_skill_defaults_to_the_common_band_without_the_reliability_roll():
    """At/above the high-skill threshold, gk_consistency should land in the elite band ONLY on
    a successful reliability roll -- the overwhelming majority of high-skill goalies should be
    capped at/under _GK_CONSISTENCY_COMMON_MAX (the common 'talented but streaky' case)."""
    rng = Rng(seed=201)
    elite_target = 95   # comfortably clears the high-skill threshold even after calibration drift
    goalies = [playergen.generate_goalie(i, rng, age=27, target_overall=elite_target)
               for i in range(2000)]
    high_skill_goalies = [g for g in goalies if _high_skill(g)]
    assert len(high_skill_goalies) > 1000   # confirms the target actually clears the gate broadly

    in_elite_band = sum(1 for g in high_skill_goalies if _high_consistency(g))
    frac_elite = in_elite_band / len(high_skill_goalies)
    # Should land close to the documented _GK_RELIABILITY_ROLL_CHANCE (0.08), not near 0 (gate
    # never grants it) or near 1 (gate doesn't actually gate anything).
    assert abs(frac_elite - playergen._GK_RELIABILITY_ROLL_CHANCE) < 0.03


def test_high_skill_and_high_consistency_together_is_genuinely_rare():
    """THE core DEVPLAN.md done-criterion for this mechanism: across a large generated goalie
    pool, the fraction landing in BOTH the high-skill AND high-gk_consistency bands must be
    MEASURABLY SMALL relative to high-skill-alone or high-consistency-alone -- confirming the
    rarity gate actually creates scarcity rather than the two axes falling out independently.

    Measured against the GATE'S OWN INPUT (the calibrated overall BEFORE the gk_consistency
    resample runs), not the player's final post-gate overall -- winning the reliability roll
    pushes gk_consistency (a real, if small, 0.10-weighted GOALIE_WEIGHTS component) up, which
    can itself nudge the FINAL overall() up by a point or two. Filtering on final overall would
    introduce a subtle selection bias (a goalie who won the roll is slightly more likely to
    cross a threshold measured post-hoc), inflating the apparent joint rate -- confirmed
    directly during this test's development (post-gate filtering measured ~16.7% conditional
    elite-band odds among "high skill" goalies vs. the documented 8% reliability-roll rate when
    measured correctly against the pre-gate overall the gate itself actually conditions on).
    """
    rng = Rng(seed=202)
    from pucksim.models.attributes import (
        ALL_GOALIE_RATINGS,
        GOALIE_ARCHETYPES_BY_POSITION,
        RARE_GOALIE_ARCHETYPES_BY_POSITION,
    )
    from pucksim.models.attributes import overall as _overall_fn

    n = 6000
    # A realistic mixed pool spanning the full skill spectrum (mirrors leaguegen.py's own
    # Gaussian(66, 10) goalie target-overall distribution) so both rare and common cases occur.
    targets = [max(30, min(95, round(rng.gauss(66.0, 10.0)))) for _ in range(n)]

    n_high_skill = 0
    n_high_consistency = 0
    n_both = 0
    for t in targets:
        archetype = playergen._choose_archetype(
            rng, "G", t, GOALIE_ARCHETYPES_BY_POSITION, RARE_GOALIE_ARCHETYPES_BY_POSITION)
        ratings = playergen._build_calibrated_ratings(rng, "G", t, ALL_GOALIE_RATINGS, archetype)
        pre_gate_overall = _overall_fn("G", ratings)
        is_high_skill = pre_gate_overall >= playergen._GK_HIGH_SKILL_THRESHOLD
        playergen._apply_gk_consistency_rarity_gate(rng, ratings, pre_gate_overall)
        is_high_consistency = ratings["gk_consistency"] >= playergen._GK_CONSISTENCY_ELITE_MIN

        n_high_skill += is_high_skill
        n_high_consistency += is_high_consistency
        n_both += is_high_skill and is_high_consistency

    assert n_high_skill > 0 and n_high_consistency > 0   # sanity: both individually occur
    frac_both = n_both / n
    frac_high_skill = n_high_skill / n
    frac_high_consistency = n_high_consistency / n

    # The joint fraction must be measurably smaller than EITHER marginal fraction alone --
    # i.e. being high-skill-and-high-consistency is much rarer than being either alone.
    assert frac_both < frac_high_skill * 0.5
    assert frac_both < frac_high_consistency * 0.5

    # And, more specifically, close to (not wildly exceeding) what the documented reliability-
    # roll chance alone would predict conditional on already being high-skill -- proving the
    # gate is the actual scarcity mechanism, not an accident of the two axes' marginals.
    conditional_prediction = frac_high_skill * playergen._GK_RELIABILITY_ROLL_CHANCE
    assert frac_both < conditional_prediction * 1.5


def test_gk_consistency_gate_does_not_affect_skaters():
    """Sanity: this gate is goalie-only -- generate_skater's rating vocabulary has no
    gk_consistency key at all, so there's nothing for the gate to touch."""
    rng = Rng(seed=203)
    p = playergen.generate_skater(1, rng, age=25, target_overall=90, position="C")
    assert "gk_consistency" not in p.ratings
