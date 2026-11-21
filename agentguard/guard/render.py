"""Turn an ActionProposal into text, for guards that read text (the LLM judge, the classifier)."""

from __future__ import annotations

import json
from typing import Any

from agentguard.guard.schemas import ActionProposal

# Long enough for the whole task: a guard that cannot see the part of the task that asks for an
# action flags it as unrequested. Was 2,000 until Level 4: BashArena's tasks run to 9,556
# characters, and the ones in our dataset and Level 3 to 705, so earlier results are unchanged.
TASK_CHARS = 10_000
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
