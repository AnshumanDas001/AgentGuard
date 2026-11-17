"""Append-only JSONL log. Every decision lands here so metrics can be recomputed for free."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JsonlLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps({"ts": datetime.now(UTC).isoformat(), **record}, default=str)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
