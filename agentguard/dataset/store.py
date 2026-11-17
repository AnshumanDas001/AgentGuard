"""Where dataset files live, and reading and writing them.

data/raw/<source>.jsonl      unlabeled rows, one file per source
data/labeled/labels.jsonl    labeling decisions, append-only; the latest per id wins
data/splits/                 train / dev / test, plus FROZEN.json once frozen
data/labeling_rules.md       the rules; its header sets the current rules version
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agentguard.config import ROOT
from agentguard.dataset.schema import LabeledRow, LabelRecord, Row

SPLIT_NAMES = ("train", "dev", "test")


class DatasetError(RuntimeError):
    pass


@dataclass(frozen=True)
class DataPaths:
    root: Path = ROOT / "data"

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def labels(self) -> Path:
        return self.root / "labeled" / "labels.jsonl"

    @property
    def splits(self) -> Path:
        return self.root / "splits"

    @property
    def frozen(self) -> Path:
        return self.splits / "FROZEN.json"

    @property
    def rules(self) -> Path:
        return self.root / "labeling_rules.md"

    def split_file(self, name: str) -> Path:
        return self.splits / f"{name}.jsonl"


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any] | str]]:
    """Yield (line number, parsed object) per non-blank line, or (line, error) if unparseable."""
    with path.open(encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                yield number, f"invalid JSON: {e}"
                continue
            yield number, obj if isinstance(obj, dict) else "line is not a JSON object"


def write_jsonl(path: Path, objects: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for obj in objects:
            f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def _load(path: Path, model: type) -> list:
    items = []
    for number, obj in iter_jsonl(path):
        if isinstance(obj, str):
            raise DatasetError(f"{path}:{number}: {obj}; run `make data-check`")
        try:
            items.append(model.model_validate(obj))
        except ValidationError as e:
            raise DatasetError(f"{path}:{number}: invalid; run `make data-check`\n{e}") from e
    return items


def raw_files(paths: DataPaths) -> list[Path]:
    return sorted(paths.raw.glob("*.jsonl")) if paths.raw.is_dir() else []


def load_rows(paths: DataPaths) -> list[Row]:
    rows: list[Row] = []
    for path in raw_files(paths):
        rows.extend(_load(path, Row))
    return rows


def load_labels(paths: DataPaths) -> dict[str, LabelRecord]:
    """Latest decision per row id (later lines override earlier ones)."""
    if not paths.labels.is_file():
        return {}
    return {record.id: record for record in _load(paths.labels, LabelRecord)}


def append_label(paths: DataPaths, record: LabelRecord) -> None:
    append_jsonl(paths.labels, record.model_dump(mode="json"))


def labeled_rows(paths: DataPaths) -> list[LabeledRow]:
    labels = load_labels(paths)
    return [LabeledRow.merge(row, labels[row.id]) for row in load_rows(paths) if row.id in labels]


def rules_version(paths: DataPaths) -> str:
    """The version in the rules header, e.g. '**Version 0.3, ...' -> '0.3'."""
    match = re.search(r"\*\*Version (\d+\.\d+)", paths.rules.read_text(encoding="utf-8"))
    if match is None:
        raise DatasetError(f"no '**Version X.Y' header in {paths.rules}")
    return match.group(1)
