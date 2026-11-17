"""`make data-split`: stratified 50/20/30 split, then freeze. Runs once; refuses to rerun."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import UTC, datetime

from agentguard.dataset.check import check, file_sha256
from agentguard.dataset.schema import LabeledRow
from agentguard.dataset.store import (
    SPLIT_NAMES,
    DataPaths,
    DatasetError,
    labeled_rows,
    load_rows,
    rules_version,
    write_jsonl,
)

SHARES = {"train": 0.5, "dev": 0.2, "test": 0.3}


def stratum(row: LabeledRow) -> str:
    """Rows are split within these groups, so every split gets its share of each."""
    if row.label == "unsafe":
        return f"unsafe:{row.category}"
    if row.imitates is not None:
        return f"hard:{row.imitates}"
    return "safe:plain"


def allocate(n: int) -> dict[str, int]:
    """Split n items by SHARES, giving leftovers to the largest remainders (test first)."""
    exact = {name: n * share for name, share in SHARES.items()}
    counts = {name: int(value) for name, value in exact.items()}
    order = sorted(SPLIT_NAMES, key=lambda s: (-(exact[s] - counts[s]), s != "test"))
    for name in order[: n - sum(counts.values())]:
        counts[name] += 1
    return counts


def group_stratum(members: list[LabeledRow]) -> str:
    """A session's stratum: its first unsafe category, else look-alike, else plain."""
    return min(
        (stratum(r) for r in members),
        key=lambda k: (not k.startswith("unsafe"), not k.startswith("hard"), k),
    )


def assign(rows: list[LabeledRow], seed: int) -> dict[str, list[LabeledRow]]:
    """Split whole sessions (Row.group), stratified, so related rows never cross splits."""
    sessions: dict[str, list[LabeledRow]] = defaultdict(list)
    for row in rows:
        sessions[row.group()].append(row)
    strata: dict[str, list[str]] = defaultdict(list)
    for key, members in sessions.items():
        strata[group_stratum(members)].append(key)
    rng = random.Random(seed)
    out: dict[str, list[LabeledRow]] = {name: [] for name in SPLIT_NAMES}
    for key in sorted(strata):
        keys = sorted(strata[key])
        rng.shuffle(keys)
        start = 0
        for name, count in allocate(len(keys)).items():
            for session in keys[start : start + count]:
                out[name].extend(sessions[session])
            start += count
    return {name: sorted(members, key=lambda r: r.id) for name, members in out.items()}


def split_and_freeze(paths: DataPaths, seed: int = 0) -> dict:
    if paths.frozen.exists():
        raise DatasetError(
            f"{paths.frozen} exists: the test split is frozen and is never regenerated. "
            "Problems go in data/errata.md (rules section 9)."
        )
    report = check(paths)
    if not report.ok:
        raise DatasetError("fix `make data-check` errors first:\n" + "\n".join(report.errors))
    rows = labeled_rows(paths)
    unlabeled = len(load_rows(paths)) - len(rows)
    if unlabeled:
        raise DatasetError(f"{unlabeled} rows are not labeled yet")
    current = rules_version(paths)
    stale = [r.id for r in rows if r.rules_version != current]
    if stale:
        raise DatasetError(f"{len(stale)} rows labeled under an older rules version than {current}")

    usable = [r for r in rows if r.label != "excluded"]
    splits = assign(usable, seed)
    for name, members in splits.items():
        write_jsonl(paths.split_file(name), [r.model_dump(mode="json") for r in members])
    info = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "rules_version": current,
        "seed": seed,
        "counts": {name: len(members) for name, members in splits.items()},
        "test_sha256": file_sha256(paths.split_file("test")),
    }
    paths.frozen.write_text(json.dumps(info, indent=2) + "\n")
    return info
