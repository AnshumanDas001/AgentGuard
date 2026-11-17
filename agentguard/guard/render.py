"""Turn an ActionProposal into text, for guards that read text (the LLM judge, the classifier)."""

from __future__ import annotations

import json
from typing import Any

from agentguard.guard.schemas import ActionProposal

TASK_CHARS = 2000
ARGS_CHARS = 3000


def args_text(args: dict[str, Any], limit: int = ARGS_CHARS) -> str:
    text = json.dumps(args, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} more chars]"


def action_line(action: ActionProposal) -> str:
    return f"{action.tool}({args_text(action.args)})"


def render_for_judge(action: ActionProposal) -> str:
    """The judge sees the task, the history and the action, each fenced as data."""
    task = action.task[:TASK_CHARS]
    if action.history:
        steps = "\n\n".join(f"[step {i}] {step}" for i, step in enumerate(action.history, 1))
    else:
        steps = "(no earlier steps)"
    return (
        f"<task>\n{task}\n</task>\n\n"
        f"<history>\n{steps}\n</history>\n\n"
        f"<proposed_action>\n{action_line(action)}\n</proposed_action>"
    )
