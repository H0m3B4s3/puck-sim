"""Tests for pucksim.rng.Rng — determinism and save/restore round-tripping."""
from __future__ import annotations

from pucksim.rng import Rng


def test_same_seed_same_randint_sequence():
    a = Rng(42)
    b = Rng(42)
    seq_a = [a.randint(1, 100) for _ in range(20)]
    seq_b = [b.randint(1, 100) for _ in range(20)]
    assert seq_a == seq_b


def test_same_seed_same_uniform_sequence():
    a = Rng(1234)
    b = Rng(1234)
    seq_a = [a.uniform(0.0, 1.0) for _ in range(20)]
    seq_b = [b.uniform(0.0, 1.0) for _ in range(20)]
    assert seq_a == seq_b


def test_same_seed_same_choice_sequence():
    population = ["a", "b", "c", "d", "e", "f", "g"]
    a = Rng(99)
    b = Rng(99)
    seq_a = [a.choice(population) for _ in range(20)]
    seq_b = [b.choice(population) for _ in range(20)]
    assert seq_a == seq_b


def test_same_seed_same_random_and_gauss_sequence():
    a = Rng(7)
    b = Rng(7)
    for _ in range(10):
        assert a.random() == b.random()
        assert a.gauss(0.0, 1.0) == b.gauss(0.0, 1.0)


def test_same_seed_same_chance_and_shuffle_behavior():
    a = Rng(2026)
    b = Rng(2026)

    chances_a = [a.chance(0.5) for _ in range(20)]
    chances_b = [b.chance(0.5) for _ in range(20)]
    assert chances_a == chances_b

    seq_a = list(range(10))
    seq_b = list(range(10))
    a.shuffle(seq_a)
    b.shuffle(seq_b)
    assert seq_a == seq_b


def test_different_seeds_diverge():
    a = Rng(1)
    b = Rng(2)
    seq_a = [a.randint(0, 1_000_000) for _ in range(10)]
    seq_b = [b.randint(0, 1_000_000) for _ in range(10)]
    assert seq_a != seq_b


def test_chance_boundary_values_are_deterministic():
    rng = Rng(5)
    assert rng.chance(0.0) is False
    assert rng.chance(1.0) is True
    assert rng.chance(-1.0) is False
    assert rng.chance(2.0) is True


def test_get_state_set_state_round_trip_mid_sequence():
    """Capturing state mid-sequence and restoring it must reproduce the same
    subsequent draws — proving save/load determinism, not just fresh-seed
    determinism."""
    rng = Rng(555)

    # Burn some draws so we are mid-sequence.
    for _ in range(5):
        rng.random()
        rng.randint(1, 6)

    saved_state = rng.get_state()

    # Draws taken right after the save — these are the "original" future.
    original_future = [rng.random() for _ in range(10)] + [
        rng.randint(1, 100) for _ in range(10)
    ] + [rng.uniform(0.0, 1.0) for _ in range(10)]

    # Restore from the saved state via from_state and confirm the exact same
    # sequence of draws occurs again.
    restored = Rng.from_state(555, saved_state)
    replayed_future = [restored.random() for _ in range(10)] + [
        restored.randint(1, 100) for _ in range(10)
    ] + [restored.uniform(0.0, 1.0) for _ in range(10)]

    assert replayed_future == original_future


def test_set_state_on_existing_instance_round_trips():
    rng = Rng(31337)
    for _ in range(3):
        rng.gauss(0.0, 1.0)

    saved_state = rng.get_state()
    expected_next = rng.choice(["x", "y", "z", "w"])

    other = Rng(0)  # different seed entirely
    other.set_state(saved_state)
    assert other.choice(["x", "y", "z", "w"]) == expected_next


def test_get_state_is_json_serializable_shape():
    import json

    rng = Rng(10)
    rng.random()
    state = rng.get_state()

    # Must be a [version, list(ints), gauss_next] shape and survive a JSON
    # round-trip (lists/ints/float|None only).
    encoded = json.dumps(state)
    decoded = json.loads(encoded)

    assert isinstance(decoded, list)
    assert len(decoded) == 3
    version, internal, gauss_next = decoded
    assert isinstance(version, int)
    assert isinstance(internal, list)
    assert all(isinstance(x, int) for x in internal)
    assert gauss_next is None or isinstance(gauss_next, float)

    # And it still restores correctly after the JSON round-trip.
    restored = Rng.from_state(10, decoded)
    fresh = Rng(10)
    fresh.random()
    assert restored.randint(1, 1000) == fresh.randint(1, 1000)


def test_from_state_with_none_state_behaves_like_fresh_seed():
    rng = Rng.from_state(42, None)
    expected = Rng(42)
    assert rng.randint(1, 100) == expected.randint(1, 100)
