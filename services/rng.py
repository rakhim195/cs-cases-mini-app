"""Cryptographically secure RNG helpers for case unboxing."""

from __future__ import annotations

import bisect
import secrets
from collections.abc import Mapping, Sequence
from typing import Any

STAT_TRAK_CHANCE = 0.10
STAT_TRAK_MULTIPLIER = 1.3

WEAR_BANDS: tuple[tuple[str, float, float], ...] = (
    ("Factory New", 0.00, 0.07),
    ("Minimal Wear", 0.07, 0.15),
    ("Field-Tested", 0.15, 0.38),
    ("Well-Worn", 0.38, 0.45),
    ("Battle-Scarred", 0.45, 1.00),
)


def secure_uniform() -> float:
    """Uniform float in [0.0, 1.0) drawn from the OS CSPRNG."""
    return secrets.randbits(53) / float(1 << 53)


def weighted_pick(items: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Pick one item with probability proportional to its 'weight'."""
    cumulative: list[float] = []
    total = 0.0
    for item in items:
        total += float(item["weight"])
        cumulative.append(total)
    point = secure_uniform() * total
    return items[bisect.bisect_right(cumulative, point)]


def uniform_choice(items: Sequence[Any]) -> Any:
    """Uniformly pick one element (used for decorative reel filler)."""
    return items[secrets.randbelow(len(items))]


def roll_wear(min_float: float = 0.0, max_float: float = 1.0) -> tuple[str, float]:
    """Roll a skin float inside its own [min_float, max_float] range and
    map it onto the CS:GO wear bands."""
    lo = max(0.0, float(min_float))
    hi = min(1.0, float(max_float))
    if hi <= lo:
        hi, lo = 1.0, 0.0
    value = lo + secure_uniform() * (hi - lo)
    range_cap = round(hi - 0.0001, 4)
    for name, _low, high in WEAR_BANDS:
        if value < high:
            # Clamp so a value like 0.37996 does not round to 0.38 and
            # escape its own band (0.15 <= x < 0.38), and so rounding
            # cannot push the float past the skin's own max_float.
            return name, max(lo, min(round(value, 4), range_cap))
    return WEAR_BANDS[-1][0], min(round(value, 4), range_cap)


def roll_stat_trak() -> bool:
    return secure_uniform() < STAT_TRAK_CHANCE


def compute_price(base_price: float, stat_trak: bool) -> float:
    multiplier = STAT_TRAK_MULTIPLIER if stat_trak else 1.0
    return round(float(base_price) * multiplier, 2)
