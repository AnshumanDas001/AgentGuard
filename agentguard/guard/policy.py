"""Turns a backend's probability into a decision."""

from __future__ import annotations

from dataclasses import dataclass

from agentguard.guard.schemas import Decision, Verdict


@dataclass(frozen=True)
class ThresholdPolicy:
    """Allow below `allow_below`, block above `block_above`, escalate in between.

    The defaults are the plan's starting point; tune them on the dev split only.
    """

    allow_below: float = 0.3
    block_above: float = 0.7

    def __post_init__(self) -> None:
        if not 0.0 <= self.allow_below <= self.block_above <= 1.0:
            raise ValueError("need 0 <= allow_below <= block_above <= 1")

    def decide(self, verdict: Verdict) -> Decision:
        if verdict.p_unsafe < self.allow_below:
            return Decision.ALLOW
        if verdict.p_unsafe > self.block_above:
            return Decision.BLOCK
        return Decision.ESCALATE
