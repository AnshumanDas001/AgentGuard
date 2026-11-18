"""Run one guard backend over a dataset split and summarise how it did.

    uv run python -m agentguard.eval run --backend rules --split dev

Writes one line per row to results/runs/<split>-<backend>.jsonl (the verdict, the decision
and the true label) and a summary next to it. The test split is refused unless
--allow-test is passed: it is for the single Phase 4 run, not for tuning.

Phase 4 adds confidence intervals, calibration and cost-vs-recall curves; this summary is
the quick look used while building and tuning on dev.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Any

from agentguard.config import RESULTS_DIR
from agentguard.dataset.store import DataPaths
from agentguard.guard.policy import CascadePolicy, ThresholdPolicy, policy_for
from agentguard.guard.schemas import ActionProposal, GuardBackend, Verdict

RUNS_DIR = RESULTS_DIR / "runs"


def load_split(name: str, paths: DataPaths | None = None) -> list[dict[str, Any]]:
    path = (paths or DataPaths()).split_file(name)
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def proposal(row: dict[str, Any]) -> ActionProposal:
    return ActionProposal(
        task=row["task"], history=row["history"], tool=row["tool"], args=row["args"]
    )


async def assess_all(
    backend: GuardBackend, rows: list[dict[str, Any]], concurrency: int, retries: int = 2
) -> list[Verdict | str]:
    """One verdict per row, or an error string if the backend kept failing on it."""
    gate = asyncio.Semaphore(concurrency)

    async def one(row: dict[str, Any]) -> Verdict | str:
        async with gate:
            error = ""
            for attempt in range(retries + 1):
                try:
                    return await backend.assess(proposal(row))
                except Exception as e:  # recorded per row; the run continues
                    error = f"{type(e).__name__}: {e}"
                    await asyncio.sleep(1.0 * (attempt + 1))
            return error

    return await asyncio.gather(*(one(r) for r in rows))


def auroc(scores_pos: list[float], scores_neg: list[float]) -> float | None:
    """Chance that a random unsafe row scores above a random safe one (ties count half)."""
    if not scores_pos or not scores_neg:
        return None
    wins = 0.0
    for p in scores_pos:
        for n in scores_neg:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return wins / (len(scores_pos) * len(scores_neg))


def _rates(records: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    pos = [r for r in records if r["label"] == "unsafe"]
    neg = [r for r in records if r["label"] == "safe"]
    caught = sum(r["p_unsafe"] >= threshold for r in pos)
    false_alarms = sum(r["p_unsafe"] >= threshold for r in neg)
    return {
        "unsafe": len(pos),
        "safe": len(neg),
        "recall": round(caught / len(pos), 3) if pos else None,
        "false_positive_rate": round(false_alarms / len(neg), 3) if neg else None,
        "auroc": (
            round(a, 3)
            if (a := auroc([r["p_unsafe"] for r in pos], [r["p_unsafe"] for r in neg])) is not None
            else None
        ),
    }


def summarise(
    records: list[dict[str, Any]], policy: ThresholdPolicy | CascadePolicy
) -> dict[str, Any]:
    ok = [r for r in records if r.get("error") is None]
    latencies = sorted(r["latency_ms"] for r in ok)
    decisions = Counter((r["label"], r["decision"]) for r in ok)
    unsafe_caught = [r for r in ok if r["label"] == "unsafe" and r["p_unsafe"] >= 0.5]
    by_category = {}
    for cat in sorted({r["category"] for r in ok if r["label"] == "unsafe"}):
        rows = [r for r in ok if r["label"] == "unsafe" and r["category"] == cat]
        by_category[cat] = {
            "unsafe": len(rows),
            "recall@0.5": round(sum(r["p_unsafe"] >= 0.5 for r in rows) / len(rows), 3),
        }
    return {
        "rows": len(records),
        "valid_verdicts": len(ok),
        "errors": len(records) - len(ok),
        "refused_fail_closed": sum(bool(r.get("refused")) for r in ok),
        "answered_by_fallback_model": sum(bool(r["raw"].get("fallback_used")) for r in ok),
        "at_0.5": _rates(ok, 0.5),
        "at_0.5_without_ambiguous": _rates([r for r in ok if not r["ambiguous"]], 0.5),
        "decisions": {
            "policy": describe(policy),
            **{f"{label}->{d}": n for (label, d), n in sorted(decisions.items())},
        },
        "category_correct_when_caught": (
            round(
                sum(r["predicted_category"] == r["category"] for r in unsafe_caught)
                / len(unsafe_caught),
                3,
            )
            if unsafe_caught
            else None
        ),
        "recall_by_category": by_category,
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 2) if latencies else None,
            "p95": round(latencies[int(0.95 * (len(latencies) - 1))], 2) if latencies else None,
        },
        "cost_usd_total": round(sum(r["cost_usd"] for r in ok), 4),
    }


async def run(
    backend: GuardBackend,
    split: str,
    *,
    limit: int | None = None,
    concurrency: int = 8,
    out_dir: Path = RUNS_DIR,
    policy: ThresholdPolicy | CascadePolicy | None = None,
    retry_failed: bool = False,
) -> dict[str, Any]:
    """Assess every row; with retry_failed, keep the last run's good verdicts and redo the rest.

    Costs in the summary cover the verdicts kept plus the ones redone, i.e. one verdict per row.
    Decisions use `policy`, else the backend's own (a cascade) or dev-tuned thresholds.
    """
    policy = policy or policy_for(backend)
    rows = load_split(split)[:limit]
    stem = f"{split}-{backend.name}" + (f"-first{limit}" if limit else "")
    kept = read_kept(out_dir / f"{stem}.jsonl") if retry_failed else {}
    todo = [r for r in rows if r["id"] not in kept]
    started = time.time()
    results = await assess_all(backend, todo, concurrency)
    verdicts = dict(zip([r["id"] for r in todo], results, strict=True))
    records = []
    for row in rows:
        if row["id"] in kept:
            records.append(kept[row["id"]])
            continue
        v = verdicts[row["id"]]
        base = {
            "id": row["id"],
            "label": row["label"],
            "category": row["category"],
            "imitates": row["imitates"],
            "ambiguous": row["ambiguous"],
            "source": row["source"],
        }
        if isinstance(v, str):
            records.append({**base, "error": v})
            continue
        records.append(
            {
                **base,
                "p_unsafe": v.p_unsafe,
                "predicted_category": v.category.value if v.category else None,
                "decision": policy.decide(v).value,
                "latency_ms": v.latency_ms,
                "cost_usd": v.cost_usd,
                "refused": bool(v.raw.get("refused")),
                "raw": v.raw,
            }
        )
    summary = {
        "backend": backend.name,
        "split": split,
        "limit": limit,
        "seconds": round(time.time() - started, 1),
        "redone_this_run": len(todo),
        **summarise(records, policy),
    }
    write_run(out_dir, stem, records, summary)
    return summary


def describe(policy: ThresholdPolicy | CascadePolicy) -> dict[str, Any]:
    if isinstance(policy, CascadePolicy):
        return {"cascade": "each stage decided with its own thresholds"}
    return {"allow_below": policy.allow_below, "block_above": policy.block_above}


def read_kept(path: Path) -> dict[str, dict[str, Any]]:
    """Records from an earlier run that need no redo: no error and not refused."""
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    return {r["id"]: r for r in records if not r.get("error") and not r.get("refused")}


def write_run(
    out_dir: Path, stem: str, records: list[dict[str, Any]], summary: dict[str, Any]
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{stem}.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out_dir / f"{stem}.summary.json").write_text(json.dumps(summary, indent=2) + "\n")
