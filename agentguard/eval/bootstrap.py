"""95% bootstrap confidence intervals (1,000 resamples), as the plan asks for every number.

Resampling is stratified: unsafe and safe rows are redrawn separately, so each resample keeps
the split's unsafe count and recall-style metrics are always defined. The same resamples are
used for every backend, so the CI of a difference between two backends is paired.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import Any

N_RESAMPLES = 1000
SEED = 20261119


def resamples(
    ids_pos: Sequence[str], ids_neg: Sequence[str], n: int = N_RESAMPLES, seed: int = SEED
) -> list[list[str]]:
    rng = random.Random(seed)
    return [
        rng.choices(ids_pos, k=len(ids_pos)) + rng.choices(ids_neg, k=len(ids_neg))
        for _ in range(n)
    ]


def interval(values: Sequence[float], level: float = 0.95) -> tuple[float, float] | None:
    """Percentile interval of the resampled values (None values dropped)."""
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    tail = (1 - level) / 2
    lo = v[int(tail * (len(v) - 1))]
    hi = v[int(round((1 - tail) * (len(v) - 1)))]
    return lo, hi


def with_ci(
    stat: Callable[[Sequence[str]], float | None],
    ids: Sequence[str],
    draws: list[list[str]],
    digits: int = 3,
) -> dict[str, Any]:
    """{"value", "ci": [lo, hi]} for stat on the full rows and on each resample."""
    value = stat(ids)
    ci = interval([stat(d) for d in draws])
    return {
        "value": round(value, digits) if value is not None else None,
        "ci": [round(ci[0], digits), round(ci[1], digits)] if ci else None,
    }
