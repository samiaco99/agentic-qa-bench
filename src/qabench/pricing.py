"""Approximate list prices (USD per million tokens) for cost estimates in the scorecard.

Estimates only: they ignore long-context tiers and fallback hops. Check current pricing
before quoting numbers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:
        # 5-minute cache writes are billed at 1.25x the input price.
        return self.input * 1.25


PRICES: dict[str, Price] = {
    "claude-fable-5-1": Price(input=10.00, output=50.00, cache_read=0.25),
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_read=0.20),
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_read=0.20),
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_read=0.01),
}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def estimated_cost(self, model: str) -> float | None:
        price = PRICES.get(model)
        if price is None:
            return None
        return (
            self.input_tokens * price.input
            + self.output_tokens * price.output
            + self.cache_creation_input_tokens * price.cache_write
            + self.cache_read_input_tokens * price.cache_read
        ) / 1_000_000
