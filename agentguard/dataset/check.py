"""`make data-check`: validate every dataset file and report all problems at once."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import ValidationError

from agentguard.dataset.schema import LabeledRow, LabelRecord, Row
from agentguard.dataset.store import SPLIT_NAMES, DataPaths, iter_jsonl, raw_files, rules_version


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _first_error(e: ValidationError) -> str:
    err = e.errors()[0]
    where = ".".join(str(p) for p in err["loc"]) or "row"
    return f"{where}: {err['msg']}"


def file_sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(paths: DataPaths) -> Report:
    report = Report()
    rows: dict[str, Row] = {}
    by_fingerprint: dict[str, list[str]] = defaultdict(list)

    for path in raw_files(paths):
        for number, obj in iter_jsonl(path):
            where = f"{path.relative_to(paths.root)}:{number}"
            if isinstance(obj, str):
                report.errors.append(f"{where}: {obj}")
                continue
            try:
                row = Row.model_validate(obj)
            except ValidationError as e:
                report.errors.append(f"{where}: {_first_error(e)}")
                continue
            if row.id in rows:
                report.errors.append(f"{where}: duplicate id {row.id!r}")
                continue
            rows[row.id] = row
            by_fingerprint[row.fingerprint()].append(row.id)

    for ids in by_fingerprint.values():
        if len(ids) > 1:
            report.errors.append(f"identical action in identical context: {', '.join(ids)}")

    current = rules_version(paths)
    latest: dict[str, LabelRecord] = {}
    if paths.labels.is_file():
        for number, obj in iter_jsonl(paths.labels):
            where = f"{paths.labels.relative_to(paths.root)}:{number}"
            if isinstance(obj, str):
                report.errors.append(f"{where}: {obj}")
                continue
            try:
                record = LabelRecord.model_validate(obj)
            except ValidationError as e:
                report.errors.append(f"{where}: {_first_error(e)}")
                continue
            if record.id not in rows:
                report.errors.append(f"{where}: label for unknown row {record.id!r}")
            latest[record.id] = record

    stale = sorted(i for i, r in latest.items() if r.rules_version != current)
    if stale:
        report.warnings.append(
            f"{len(stale)} rows labeled under an older rules version than {current}; "
            f"relabel before freezing (first: {stale[0]})"
        )
    unlabeled = len(set(rows) - set(latest))
    if unlabeled:
        report.warnings.append(f"{unlabeled} of {len(rows)} rows not labeled yet")

    _check_splits(paths, report)
    return report


def _check_splits(paths: DataPaths, report: Report) -> None:
    seen: dict[str, str] = {}
    fingerprints: dict[str, str] = {}
    for name in SPLIT_NAMES:
        path = paths.split_file(name)
        if not path.is_file():
            continue
        for number, obj in iter_jsonl(path):
            where = f"splits/{name}.jsonl:{number}"
            if isinstance(obj, str):
                report.errors.append(f"{where}: {obj}")
                continue
            try:
                row = LabeledRow.model_validate(obj)
            except ValidationError as e:
                report.errors.append(f"{where}: {_first_error(e)}")
                continue
            for key, table in ((row.id, seen), (row.fingerprint(), fingerprints)):
                if key in table and table[key] != name:
                    report.errors.append(f"{where}: {row.id} leaks between {table[key]} and {name}")
                table[key] = name

    if paths.frozen.is_file():
        frozen = json.loads(paths.frozen.read_text())
        test = paths.split_file("test")
        if not test.is_file():
            report.errors.append("FROZEN.json exists but splits/test.jsonl is missing")
        elif file_sha256(test) != frozen["test_sha256"]:
            report.errors.append("splits/test.jsonl no longer matches its frozen hash")
