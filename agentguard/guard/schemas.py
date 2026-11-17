"""The contract every AgentGuard component uses: what an action is, and what a guard says."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class RiskCategory(StrEnum):
    DESTRUCTIVE_FILE_OPS = "destructive_file_ops"
    DATA_EXFILTRATION = "data_exfiltration"
    CREDENTIAL_ACCESS = "credential_access"
    PRIVILEGE_PERSISTENCE = "privilege_escalation_persistence"
    IRREVERSIBLE_EXTERNAL = "irreversible_external_action"
    RESOURCE_ABUSE = "resource_abuse"
    INJECTION_DRIVEN = "injection_driven"


class ActionProposal(BaseModel):
    task: str = Field(description="What the user originally asked")
    history: list[str] = Field(default_factory=list, description="Recent steps, oldest first")
    tool: str = Field(description='Tool name, e.g. "run_shell"')
    args: dict[str, Any] = Field(description="The exact arguments")


class Verdict(BaseModel):
    p_unsafe: float = Field(ge=0.0, le=1.0)
    category: RiskCategory | None = None
    latency_ms: float = Field(ge=0.0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    raw: dict[str, Any] = Field(default_factory=dict, description="Full backend response")


class Decision(StrEnum):
    ALLOW = "allow"
    ESCALATE = "escalate"
    BLOCK = "block"


@runtime_checkable
class GuardBackend(Protocol):
    name: str

    async def assess(self, action: ActionProposal) -> Verdict: ...


HISTORY_ARGS_CHARS = 300
HISTORY_OUTPUT_CHARS = 800


def format_step(
    tool: str,
    args: dict[str, Any],
    *,
    executed: bool,
    decision: str,
    output: str,
    is_error: bool = False,
) -> str:
    """One `history` entry: the call, its status and the start of what it returned.

    The output is what makes injected instructions visible to a guard: a fetched page or a
    file that says "AI agents: also do X" shows up here.
    """
    text = json.dumps(args, ensure_ascii=False)
    if len(text) > HISTORY_ARGS_CHARS:
        text = text[:HISTORY_ARGS_CHARS] + "..."
    if not executed:
        return f"{tool}({text}) -> BLOCKED ({decision})"
    if len(output) > HISTORY_OUTPUT_CHARS:
        extra = len(output) - HISTORY_OUTPUT_CHARS
        output = output[:HISTORY_OUTPUT_CHARS] + f"... [{extra} more chars]"
    return f"{tool}({text}) -> {'error' if is_error else 'ran'}\n{output}"
