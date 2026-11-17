"""What the DeBERTa classifier reads, and its label set. Shared by training and inference."""

from __future__ import annotations

from agentguard.guard.render import args_text
from agentguard.guard.schemas import ActionProposal, RiskCategory

# Class 0 is safe; the rest are the 7 risk categories. p_unsafe = 1 - P(safe).
LABELS: list[str] = ["safe", *(c.value for c in RiskCategory)]
MAX_LENGTH = 512
TASK_CHARS = 1000
ARGS_CHARS = 1500
STEP_CHARS = 700


def classifier_text(action: ActionProposal) -> tuple[str, str]:
    """(first, second) segments. The first holds the task and the action and is kept whole when
    possible; the second holds the history newest-first, so truncation drops the oldest steps."""
    first = (
        f"TASK: {action.task[:TASK_CHARS]}\n"
        f"ACTION: {action.tool}({args_text(action.args, ARGS_CHARS)})"
    )
    steps = [step[:STEP_CHARS] for step in reversed(action.history)]
    second = "\n".join(f"STEP -{i}: {s}" for i, s in enumerate(steps, 1)) or "(no earlier steps)"
    return first, second
