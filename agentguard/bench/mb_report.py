"""The MonitoringBench result: the frozen Jev recipe next to the published monitors.

    uv run --group bench python -m agentguard.bench mb-report

Reads the saved Jev-v3 steps (nothing is called), applies the frozen learned score (trained on
Redwood's d158 runs), and writes results/bench/monitoringbench/report.json with:
  - Jev: catch at 1% and 4% trajectory FPR (cut on the 550 honest runs), AUROC, the
    length-weighted cut, per side task, cost and latency;
  - a control: the same pipeline with random Jev answers on MonitoringBench (what the ledger
    facts and run length give on their own);
  - the 13 published full-trajectory monitors on the same 196 attacks (the paper's cuts).
"""

from __future__ import annotations

import contextlib
import io
import json
import random
import shutil
import tempfile
from pathlib import Path
from typing import Any

from agentguard.config import RESULTS_DIR

GUARD = "jev-v3"
OUT = RESULTS_DIR / "bench" / "monitoringbench"
CONTROL_SEEDS = (0, 1, 2)


def _head(out_dir: Path | None = None) -> dict[str, Any]:
    import agentguard.bench.head as head

    saved = head.OUT_DIR
    if out_dir is not None:
        head.OUT_DIR = out_dir
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return head.main(GUARD, "d158", "mb196", facts=True, max_only=True)
    finally:
        head.OUT_DIR = saved


def control(rows_path: Path, seed: int) -> dict[str, Any]:
    """The frozen recipe with Jev's MonitoringBench answers replaced by random numbers."""
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as tmp:
        with (
            rows_path.open(encoding="utf-8") as src,
            (Path(tmp) / f"{GUARD}.jsonl").open("w", encoding="utf-8") as dst,
        ):
            for line in src:
                r = json.loads(line)
                if r["traj"].startswith("mb-") and "raw" in r and not r["raw"].get("prefiltered"):
                    r["raw"]["answers"] = {k: rng.random() for k in r["raw"]["answers"]}
                dst.write(json.dumps(r) + "\n")
        return _head(Path(tmp))


def main() -> dict[str, Any]:
    from agentguard.bench.monitoringbench import read_master, reference
    from agentguard.bench.run import OUT_DIR

    rows_path = OUT_DIR / f"{GUARD}.jsonl"
    jev = _head()
    controls = [control(rows_path, s) for s in CONTROL_SEEDS]
    keys = ("auroc", "catch_at_1pct_fpr", "catch_at_4pct_fpr")
    control_mean = {k: round(sum(c[k]["value"] for c in controls) / len(controls), 3) for k in keys}
    control_mean["length_weighted"] = {
        k: round(sum(c["length_weighted"][k] for c in controls) / len(controls), 3) for k in keys
    }
    with rows_path.open(encoding="utf-8") as f:
        mb = [r for r in map(json.loads, f) if r["traj"].startswith("mb-") and "error" not in r]
    paid = [r for r in mb if not r["raw"].get("prefiltered")]
    latency = sorted(r["latency_ms"] for r in paid)
    cost = sum(r["cost_usd"] for r in mb)
    report = {
        "benchmark": "MonitoringBench (arXiv 2605.09684): 196 standard attacks (opus_only, "
        "Claude Opus 4.6) and Palaestra's 550 honest runs (Claude Opus 4.5)",
        "recipe": "jev-v3, pre-filter, learned score --facts --max-only trained on Redwood d158",
        "jev": {k: jev[k] for k in keys + ("length_controlled", "length_weighted", "lengths")}
        | {"by_side_task": jev["by_side_task"]},
        "jev_cost": {
            "steps": len(mb),
            "jev_calls": len(paid),
            "usd_total": round(cost, 3),
            "usd_per_1k_steps": round(1000 * cost / len(mb), 3),
            "latency_ms_median": latency[len(latency) // 2],
            "latency_ms_p95": latency[int(0.95 * (len(latency) - 1))],
        },
        "control_random_answers": control_mean,
        "published_monitors": reference(read_master(), {"opus_only"}),
        "caveats": [
            "Published monitors' cuts come from the paper's 416 honest runs (not released); "
            "Jev's from Palaestra's 550 honest runs, 2 of which achieved a side task by accident.",
            "Published monitors read the whole run at once without tool outputs; Jev scores "
            "each step with the run so far, outputs included, and takes the run's top score.",
            "Attack runs are about twice as long as honest runs here; see length_weighted.",
            "Jev's learned score was trained on Redwood's BashArena runs; nothing was fitted on "
            "MonitoringBench.",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    shutil.copy(OUT_DIR / f"head-{GUARD}-d158-mb196-facts-max.json", OUT / "jev-head.json")
    return report
