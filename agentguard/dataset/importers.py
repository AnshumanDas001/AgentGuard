"""Turn other material into unlabeled rows in data/raw/<source>.jsonl.

Benchmark converters (R-Judge, AgentDojo, ...) will live here too; for now, agent run logs.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from agentguard.dataset.schema import MAX_HISTORY, Row
from agentguard.dataset.store import DataPaths, append_jsonl, iter_jsonl, load_rows
from agentguard.guard.schemas import format_step


def rows_from_run_log(log_path: Path, source: str) -> list[Row]:
    """One row per tool call in an AgentGuard run log.

    History is rebuilt from the logged calls with the current `format_step`, so rows from
    older logs get the same history format (with outputs) as new ones.
    """
    rows = []
    steps: dict[str, list[str]] = defaultdict(list)
    for _, record in iter_jsonl(log_path):
        if not isinstance(record, dict) or record.get("event") != "tool_call":
            continue
        run_id = record["run_id"]
        action = record["action"]
        history = steps[run_id]
        rows.append(
            Row(
                id=f"{source}-{run_id}-{len(history) + 1:02d}",
                source=source,
                task=action["task"],
                history=history[-MAX_HISTORY:],
                tool=action["tool"],
                args=action["args"],
                meta={
                    "log": log_path.name,
                    "run_id": run_id,
                    "step": record["step"],
                    "agent_model": record.get("agent_model"),
                },
            )
        )
        history.append(
            format_step(
                action["tool"],
                action["args"],
                executed=record["executed"],
                decision=record["decision"],
                output=record.get("output", ""),
                is_error=record.get("is_error", False),
            )
        )
    return rows


def import_rows(paths: DataPaths, rows: list[Row]) -> tuple[int, int]:
    """Append rows to data/raw/<source>.jsonl, skipping any whose id, or whose exact action
    in the same context, is already in the dataset (`make data-check` rejects duplicates).
    Returns (added, skipped)."""
    existing = load_rows(paths)
    ids = {r.id for r in existing}
    fingerprints = {r.fingerprint() for r in existing}
    added = 0
    for row in rows:
        fingerprint = row.fingerprint()
        if row.id in ids or fingerprint in fingerprints:
            continue
        append_jsonl(paths.raw / f"{row.source}.jsonl", row.model_dump(mode="json"))
        ids.add(row.id)
        fingerprints.add(fingerprint)
        added += 1
    return added, len(rows) - added
