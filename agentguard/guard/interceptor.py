"""Sits between the agent and its tools: every call is reviewed before it runs."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agentguard.agent.tools import Toolbox, ToolResult
from agentguard.guard.policy import CascadePolicy, ThresholdPolicy, policy_for
from agentguard.guard.schemas import ActionProposal, Decision, GuardBackend, Verdict

# Called for ESCALATE decisions; returns True to let the action run.
EscalationHandler = Callable[[ActionProposal, Verdict], Awaitable[bool]]


async def deny_escalations(action: ActionProposal, verdict: Verdict) -> bool:
    return False


@dataclass(frozen=True)
class Outcome:
    verdict: Verdict
    decision: Decision
    executed: bool
    result: ToolResult


class Interceptor:
    def __init__(
        self,
        backend: GuardBackend,
        toolbox: Toolbox,
        *,
        policy: ThresholdPolicy | CascadePolicy | None = None,
        on_escalate: EscalationHandler = deny_escalations,
        guard_timeout_s: float = 30.0,
    ) -> None:
        self.backend = backend
        self.toolbox = toolbox
        self.policy = policy or policy_for(backend)  # cascade's own, tuned, or defaults
        self.on_escalate = on_escalate
        self.guard_timeout_s = guard_timeout_s

    async def assess(self, action: ActionProposal) -> Verdict:
        """Ask the backend, failing closed: a guard error or timeout counts as unsafe."""
        start = time.perf_counter()
        try:
            return await asyncio.wait_for(self.backend.assess(action), self.guard_timeout_s)
        except Exception as e:
            return Verdict(
                p_unsafe=1.0,
                latency_ms=(time.perf_counter() - start) * 1000,
                raw={"error": f"{type(e).__name__}: {e}", "fail_closed": True},
            )

    async def handle(self, action: ActionProposal) -> Outcome:
        verdict = await self.assess(action)
        decision = self.policy.decide(verdict)
        allowed = decision is Decision.ALLOW or (
            decision is Decision.ESCALATE and await self.on_escalate(action, verdict)
        )
        if not allowed:
            category = verdict.category.value if verdict.category else "unspecified"
            message = (
                f"Blocked by AgentGuard (p_unsafe={verdict.p_unsafe:.2f}, category={category}). "
                "The action was not executed. Find a safer way to do the user's task, or "
                "explain why it cannot be done."
            )
            return Outcome(verdict, decision, False, ToolResult(message, is_error=True))
        result = await self.toolbox.execute(action.tool, action.args)
        return Outcome(verdict, decision, True, result)
