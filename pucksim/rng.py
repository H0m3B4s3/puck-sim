"""Seedable, save-restorable random number generation.

A single :class:`Rng` instance lives on the world. Saving captures its internal state so a
reloaded career reproduces simulations exactly. All game logic should pull randomness from the
world's rng rather than the global :mod:`random` module so determinism holds.
"""
from __future__ import annotations

import random
from typing import Any, List, Sequence, TypeVar

T = TypeVar("T")


class Rng:
    """Thin deterministic wrapper around :class:`random.Random`."""

    def __init__(self, seed: int | None = None) -> None:
        self._random = random.Random(seed)
        self.seed = seed

    # -- basic draws --------------------------------------------------------
    def random(self) -> float:
        """Uniform float in [0, 1)."""
        return self._random.random()

    def chance(self, p: float) -> bool:
        """True with probability ``p`` (clamped to [0, 1])."""
        if p <= 0.0:
            return False
        if p >= 1.0:
            return True
        return self._random.random() < p

    def randint(self, a: int, b: int) -> int:
        """Integer in [a, b] inclusive."""
        return self._random.randint(a, b)

    def uniform(self, a: float, b: float) -> float:
        return self._random.uniform(a, b)

    def gauss(self, mu: float, sigma: float) -> float:
        return self._random.gauss(mu, sigma)

    def triangular(self, low: float, high: float, mode: float) -> float:
        return self._random.triangular(low, high, mode)

    # -- collections --------------------------------------------------------
    def choice(self, seq: Sequence[T]) -> T:
        return self._random.choice(seq)

    def choices(self, population: Sequence[T], weights: Sequence[float], k: int = 1) -> List[T]:
        return self._random.choices(population, weights=weights, k=k)

    def weighted_one(self, population: Sequence[T], weights: Sequence[float]) -> T:
        return self._random.choices(population, weights=weights, k=1)[0]

    def sample(self, population: Sequence[T], k: int) -> List[T]:
        return self._random.sample(list(population), k)

    def shuffle(self, seq: List[Any]) -> None:
        self._random.shuffle(seq)

    # -- persistence --------------------------------------------------------
    def get_state(self) -> Any:
        """Return a JSON-serializable snapshot of the generator state."""
        state = self._random.getstate()
        # state is (version, tuple_of_ints, gauss_next); make it JSON-friendly.
        version, internal, gauss_next = state
        return [version, list(internal), gauss_next]

    def set_state(self, state: Any) -> None:
        version, internal, gauss_next = state
        self._random.setstate((version, tuple(internal), gauss_next))

    @classmethod
    def from_state(cls, seed: int | None, state: Any) -> "Rng":
        rng = cls(seed)
        if state is not None:
            rng.set_state(state)
        return rng
