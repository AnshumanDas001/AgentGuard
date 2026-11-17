"""Token pricing, used to put a dollar figure on agent runs and guard backends."""

from __future__ import annotations

from typing import Any

# USD per million tokens: (input, output). Anthropic first-party rates as of 2026-10-06.
# Record the date with any cost number you publish; prices change.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-4-8": (5.00, 25.00),
}

CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25


def estimate_cost(model: str, usage: Any) -> float:
    """Dollar cost of one response, from its `usage` block. Unknown models cost 0.0.

    With server-side fallbacks, `usage` covers only the attempt that produced the message,
    so this slightly undercounts turns where a fallback ran.
    """
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        return 0.0
    in_price, out_price = prices
    cache_read = getattr(usage, "cache_read_input_tokens", None) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", None) or 0
    input_cost = (
        usage.input_tokens
        + cache_read * CACHE_READ_MULTIPLIER
        + cache_write * CACHE_WRITE_MULTIPLIER
    ) * in_price
    return (input_cost + usage.output_tokens * out_price) / 1_000_000
