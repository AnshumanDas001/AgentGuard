"""`make label`: label rows one at a time in the terminal, blind to where they came from.

Shows only what a guard would see (task, history, tool, args), never the row's id, source
or meta. Rows come in a fixed shuffled order so sources are mixed. Every decision is saved
immediately, so you can quit and resume at any time.
"""

from __future__ import annotations

import json
import random
import textwrap
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import ValidationError

from agentguard.dataset.schema import LabelRecord, Row
from agentguard.dataset.store import (
    DataPaths,
    append_label,
    load_labels,
    load_rows,
    rules_version,
)
from agentguard.guard.schemas import RiskCategory

Ask = Callable[[str], str]
Say = Callable[[str], None]

CATEGORIES = list(RiskCategory)
CATEGORY_MENU = "  ".join(f"{i}={c.value}" for i, c in enumerate(CATEGORIES, 1))


class Quit(Exception):
    pass


def render(row: Row, position: int, total: int) -> str:
    """The row as the labeler sees it."""
    lines = [f"\n{'=' * 78}", f"Row {position} of {total}", "", "TASK:"]
    lines += textwrap.wrap(row.task, 76, initial_indent="  ", subsequent_indent="  ")
    lines += ["", "HISTORY (oldest first):"]
    lines += [f"  {i}. {step}" for i, step in enumerate(row.history, 1)] or ["  (none)"]
    lines += ["", f"PROPOSED ACTION: {row.tool}"]
    for key, value in row.args.items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if "\n" in text:
            lines.append(f"  {key}:")
            lines += [f"    | {line}" for line in text.splitlines()]
        else:
            lines.append(f"  {key}: {text}")
    return "\n".join(lines)


def _choice(ask: Ask, say: Say, prompt: str, options: dict[str, str]) -> str:
    while True:
        answer = ask(prompt).strip().lower()
        if answer == "q":
            raise Quit
        if answer in options:
            return options[answer]
        say(f"  Please answer one of: {', '.join(k or 'Enter' for k in options)}")


def _category(ask: Ask, say: Say, prompt: str, optional: bool) -> RiskCategory | None:
    say(f"  {CATEGORY_MENU}")
    options = {str(i): str(i) for i in range(1, len(CATEGORIES) + 1)}
    if optional:
        options[""] = ""
    answer = _choice(ask, say, prompt, options)
    return CATEGORIES[int(answer) - 1] if answer else None


def _text(ask: Ask, say: Say, prompt: str, required: bool) -> str:
    while True:
        answer = ask(prompt).strip()
        if answer or not required:
            return answer
        say("  A note is required here.")


def prompt_label(ask: Ask, say: Say, row_id: str, version: str) -> LabelRecord | None:
    """Ask for one decision. Returns None to skip the row; raises Quit to stop."""
    label = _choice(
        ask,
        say,
        "Label: [s]afe  [u]nsafe  e[x]clude  [k] skip  [q]uit > ",
        {"s": "safe", "u": "unsafe", "x": "excluded", "k": "skip"},
    )
    if label == "skip":
        return None
    fields: dict = {"label": label}
    if label == "unsafe":
        fields["category"] = _category(ask, say, "Category (1-7) > ", optional=False)
        while True:
            secondary = _category(ask, say, "Secondary category (1-7, Enter for none) > ", True)
            if secondary != fields["category"]:
                break
            say("  The secondary category must differ from the category.")
        fields["secondary_category"] = secondary
    elif label == "safe":
        fields["imitates"] = _category(
            ask, say, "Hard negative? Category it imitates (1-7, Enter for none) > ", True
        )
    if label == "excluded":
        fields["notes"] = _text(ask, say, "Reason for excluding (rules section 7) > ", True)
    else:
        fields["ambiguous"] = (
            _choice(
                ask,
                say,
                "Ambiguous (needed the tie-breaker)? [y/N] > ",
                {"y": "y", "n": "n", "": "n"},
            )
            == "y"
        )
        fields["notes"] = _text(
            ask,
            say,
            "Notes (Enter to skip) > " if not fields["ambiguous"] else "Note (required) > ",
            fields["ambiguous"],
        )
    return LabelRecord(
        id=row_id,
        rules_version=version,
        labeled_at=datetime.now(UTC).isoformat(),
        **fields,
    )


def summarize(record: LabelRecord) -> str:
    parts = [record.label]
    if record.category:
        parts.append(record.category.value)
    if record.secondary_category:
        parts.append(f"also {record.secondary_category.value}")
    if record.imitates:
        parts.append(f"hard negative of {record.imitates.value}")
    if record.ambiguous:
        parts.append("ambiguous")
    return "Saved: " + ", ".join(parts)


def queue(paths: DataPaths, seed: int = 0) -> list[Row]:
    """Unlabeled rows in a fixed shuffled order, so sources are mixed."""
    labeled = load_labels(paths)
    rows = sorted((r for r in load_rows(paths) if r.id not in labeled), key=lambda r: r.id)
    random.Random(seed).shuffle(rows)
    return rows


def session(
    paths: DataPaths,
    *,
    ask: Ask = input,
    say: Say = print,
    limit: int | None = None,
    seed: int = 0,
) -> int:
    """Label until done, `limit` rows saved, or quit. Returns how many were saved."""
    version = rules_version(paths)
    todo = queue(paths, seed)
    say(f"{len(todo)} rows to label under rules v{version}. Enter q at any prompt to stop.")
    saved = 0
    for position, row in enumerate(todo, 1):
        if limit is not None and saved >= limit:
            break
        say(render(row, position, len(todo)))
        try:
            record = prompt_label(ask, say, row.id, version)
        except Quit:
            break
        except ValidationError as e:  # the prompts should prevent this; never save a bad record
            say(f"  Not saved: {e.errors()[0]['msg']}")
            continue
        if record is None:
            say("  Skipped.")
            continue
        append_label(paths, record)
        saved += 1
        say(f"  {summarize(record)}")
    say(f"\n{saved} labeled this session.")
    return saved
