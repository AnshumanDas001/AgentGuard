"""Turns a backend's probability into a decision, alone or as a cascade of backends."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentguard.config import RESULTS_DIR
from agentguard.guard.schemas import ActionProposal, Decision, GuardBackend, Verdict

TUNING_DIR = RESULTS_DIR / "tuning"


@dataclass(frozen=True)
class ThresholdPolicy:
    """Allow below `allow_below`, block above `block_above`, escalate in between.

    The defaults are the plan's starting point; tuned values come from the dev split only
    (`python -m agentguard.eval tune`).
    """

    allow_below: float = 0.3
    block_above: float = 0.7

    def __post_init__(self) -> None:
        if not 0.0 <= self.allow_below <= self.block_above <= 1.0:
            raise ValueError("need 0 <= allow_below <= block_above <= 1")

    def decide(self, verdict: Verdict) -> Decision:
        return self.decide_p(verdict.p_unsafe)

    def decide_p(self, p_unsafe: float) -> Decision:
        if p_unsafe < self.allow_below:
            return Decision.ALLOW
        if p_unsafe > self.block_above:
            return Decision.BLOCK
        return Decision.ESCALATE


def tuned_policy(backend: str, path: Path | None = None) -> ThresholdPolicy | None:
    """The dev-tuned thresholds for a backend, or None if it has not been tuned."""
    path = path or TUNING_DIR / "thresholds.json"
    if not path.is_file():
        return None
    entry = json.loads(path.read_text()).get("backends", {}).get(backend)
    if entry is None:
        return None
    return ThresholdPolicy(entry["allow_below"], entry["block_above"])


def policy_for(backend: GuardBackend) -> ThresholdPolicy | CascadePolicy:
    """A cascade's own policy, else the backend's dev-tuned thresholds, else the defaults."""
    own = getattr(backend, "policy", None)
    if isinstance(own, ThresholdPolicy | CascadePolicy):
        return own
    return tuned_policy(backend.name) or ThresholdPolicy()


@dataclass(frozen=True)
class CascadePolicy:
    """Decides a cascade's verdict: the stage that answered confidently has already decided.

    A verdict without that record (the interceptor's fail-closed verdict when the whole
    cascade errors or times out) falls back to the last stage's thresholds.
    """

    last: ThresholdPolicy

    def decide(self, verdict: Verdict) -> Decision:
        decided = verdict.raw.get("cascade_decision")
        return Decision(decided) if decided else self.last.decide(verdict)


class Cascade:
    """FrugalGPT-style: ask the cheapest guard first, and pay for the next one only if unsure.

    Each stage is a backend with its own thresholds. A stage's ALLOW or BLOCK is final; its
    ESCALATE hands the action to the next stage. The last stage's ESCALATE goes to a human,
    as with a single guard. A non-final stage that errors counts as unsure, so the next
    stage still looks; an error in the last stage propagates, and the interceptor fails
    closed. Use `cascade.policy` (the interceptor and runner do so by default).
    """

    def __init__(
        self, stages: Sequence[tuple[GuardBackend, ThresholdPolicy]], name: str | None = None
    ) -> None:
        if not stages:
            raise ValueError("a cascade needs at least one stage")
        self.stages = list(stages)
        self.name = name or ">".join(b.name for b, _ in self.stages)
        self.policy = CascadePolicy(self.stages[-1][1])

    async def assess(self, action: ActionProposal) -> Verdict:
        start = time.perf_counter()
        trail: list[dict[str, Any]] = []
        cost = 0.0
        for i, (backend, policy) in enumerate(self.stages):
            last = i == len(self.stages) - 1
            try:
                verdict = await backend.assess(action)
            except Exception as e:
                if last:
                    raise
                trail.append({"stage": backend.name, "error": f"{type(e).__name__}: {e}"})
                continue
            cost += verdict.cost_usd
            decision = policy.decide(verdict)
            trail.append(
                {
                    "stage": backend.name,
                    "p_unsafe": verdict.p_unsafe,
                    "decision": decision.value,
                    "cost_usd": verdict.cost_usd,
                }
            )
            if decision is not Decision.ESCALATE or last:
                return Verdict(
                    p_unsafe=verdict.p_unsafe,
                    category=verdict.category,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    cost_usd=cost,
                    raw={
                        "backend": self.name,
                        "cascade_decision": decision.value,
                        "decided_by": backend.name,
                        "stages": trail,
                        "final_raw": verdict.raw,
                    },
                )
        raise AssertionError("unreachable: the last stage always returns or raises")

    async def aclose(self) -> None:
        for backend, _ in self.stages:
            close = getattr(backend, "aclose", None)
            if close is not None:
                await close()


def default_cascade(path: Path | None = None) -> Cascade:
    """The cascade chosen on dev (results/tuning/cascade.json), built with its tuned stages."""
    from agentguard.guard.backends import build_backend

    path = path or TUNING_DIR / "cascade.json"
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found; run `python -m agentguard.eval tune`")
    chosen = json.loads(path.read_text())["chosen"]
    stages = [
        (build_backend(s["backend"]), ThresholdPolicy(s["allow_below"], s["block_above"]))
        for s in chosen["stages"]
    ]
    return Cascade(stages, name="cascade")
