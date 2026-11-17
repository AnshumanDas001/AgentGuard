"""Pass-through backend: approves everything. Used to wire up the pipeline in Phase 1."""

from __future__ import annotations

from agentguard.guard.schemas import ActionProposal, Verdict


class AllowAll:
    name = "allow_all"

    async def assess(self, action: ActionProposal) -> Verdict:
        return Verdict(p_unsafe=0.0, latency_ms=0.0, raw={"backend": self.name})
