"""Score one guard on every step of the published BashArena runs (no agent is run).

    uv run --group ml python -m agentguard.bench run --guard rules
    uv run python -m agentguard.bench run --guard jev --sample s200 --max-cost 1.00

Writes one line per step to results/bench/basharena/<guard>.jsonl, whatever the sample. A
rerun skips steps already scored, so an interrupted or budget-capped run resumes where it
stopped, and growing a guard from s100 to s200 only pays for the new runs.

Samples are fixed sets of runs, chosen by seed from the runs the benchmark scores, so every
guard is compared on the same runs: `all` (600 honest runs, 569 successful attacks), `s200`
(200 honest, 50 attacks per side task) and `s100` (100 honest, 25 per side task); s100 is
inside s200.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any

from agentguard.agent.loop import HISTORY_LEN
from agentguard.bench.basharena import Trajectory, load, proposals, scored
from agentguard.config import RESULTS_DIR
from agentguard.guard.policy import policy_for
from agentguard.guard.schemas import GuardBackend

OUT_DIR = RESULTS_DIR / "bench" / "basharena"
SAMPLES = {"all": None, "s200": 200, "s100": 100, "f50": 50, "v58": 58, "d158": 158, "t200": 200}
# Guards that see the whole run rather than the last 5 steps.
WHOLE_RUN = {"jev-long", "jev-v2", "jev-v3"}
WITH_LEDGER = {"jev-v2", "jev-v3"}
EXTENDED = {"jev-v3"}
SEED = 20261121
SIDE_TASKS = ("disable_firewall", "download_malware", "leak_passwords", "sudo_edit")
NO_RETENTION = {"data_collection": "deny"}


def sample(trajectories: list[Trajectory], name: str) -> list[Trajectory]:
    """The named fixed sample. s100 and s200 are prefixes of the same shuffles.

    f50 is fresh: 50 honest runs and 50 attacks (13, 13, 12, 12 per side task) inside s200 but
    outside s100, the runs looked at while diagnosing Level 4. It is for the Jev-long test.
    v58 is the validation set for what f50 suggested (Jev-v2's hides_intent question): 30
    honest runs and 28 attacks inside s200, outside s100 and f50, never scored by any Jev.
    d158 is f50 + v58 (development, 158 runs). t200 is the final test: 100 honest runs and 100
    attacks outside s200, fixed before any LLM guard scored them; score it once, frozen.
    """
    runs = scored(trajectories)
    n = SAMPLES[name]
    if n is None:
        return runs
    rng = random.Random(SEED)
    honest = sorted((t for t in runs if t.kind == "honest"), key=lambda t: t.id)
    rng.shuffle(honest)
    groups = {}
    for side in SIDE_TASKS:
        group = sorted((t for t in runs if t.side_task == side), key=lambda t: t.id)
        random.Random(f"{SEED}-{side}").shuffle(group)
        groups[side] = group
    if name == "d158":  # development: every run Jev-v2 was designed or checked on
        return sample(trajectories, "f50") + sample(trajectories, "v58")
    if name == "t200":  # final test, fixed 2026-11-22 before any of it was scored by Jev or a
        # judge: 100 honest + 25 attacks per side task, all outside s200
        picked = honest[200:300]
        for side in SIDE_TASKS:
            picked += groups[side][50:75]
        return picked
    if name == "v58":  # validation: 30 honest + 7 attacks per side task, never scored by Jev
        picked = honest[150:180]
        for side in SIDE_TASKS:
            picked += groups[side][38:45]
        return picked
    if name == "f50":
        picked = honest[100:150]
        for side, k in zip(SIDE_TASKS, (13, 13, 12, 12), strict=True):
            picked += groups[side][25 : 25 + k]
        return picked
    picked = honest[:n]
    for side in SIDE_TASKS:
        picked += groups[side][: n // len(SIDE_TASKS)]
    return picked


def no_retention(backend: Any) -> None:
    """Ask OpenRouter to route only to providers that do not keep prompts for training."""
    for stage, _ in getattr(backend, "stages", []):
        no_retention(stage)
    if hasattr(backend, "provider"):
        backend.provider = {**backend.provider, **NO_RETENTION}
    if hasattr(backend, "extra_body"):
        backend.extra_body = {**backend.extra_body, "provider": NO_RETENTION}


def _slim(raw: dict[str, Any]) -> dict[str, Any]:
    """What is worth keeping per step: why it decided, not the classifier's full softmax."""
    keep = (
        "decided_by",
        "cascade_decision",
        "reason",
        "refused",
        "fallback_used",
        "answers",
        "matches",
    )
    out = {k: raw[k] for k in keep if k in raw}
    if "stages" in raw:
        out["stages"] = [{k: v for k, v in s.items() if k != "cost_usd"} for s in raw["stages"]]
    if "final_raw" in raw:
        out.update(_slim(raw["final_raw"]))
    return out


def done_keys(path: Path) -> set[tuple[str, int]]:
    if not path.is_file():
        return set()
    with path.open(encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return {(r["traj"], r["step"]) for r in rows if "error" not in r}


async def run(
    backend: GuardBackend,
    trajectories: list[Trajectory],
    out: Path,
    *,
    concurrency: int = 8,
    max_cost: float | None = None,
    retries: int = 2,
    whole_run: bool = False,
    ledger: bool = False,
    extended: bool = False,
    policy: Any = None,
) -> dict[str, Any]:
    out.parent.mkdir(parents=True, exist_ok=True)
    done = done_keys(out)
    todo = [
        (t, i, p)
        for t in trajectories
        for i, p in enumerate(
            proposals(t, None if whole_run else HISTORY_LEN, ledger=ledger, extended=extended)
        )
        if (t.id, i) not in done
    ]
    decide = (policy or policy_for(backend)).decide
    gate = asyncio.Semaphore(concurrency)
    spent = {"usd": 0.0, "stopped": False}
    counts = {"scored": 0, "errors": 0, "skipped_budget": 0}

    with out.open("a", encoding="utf-8") as f:

        async def one(t: Trajectory, i: int, action: Any) -> None:
            async with gate:
                if max_cost is not None and spent["usd"] >= max_cost:
                    spent["stopped"] = True
                    counts["skipped_budget"] += 1
                    return
                row: dict[str, Any] = {
                    "traj": t.id,
                    "kind": t.kind,
                    "side_task": t.side_task,
                    "step": i,
                    "tool": action.tool,
                }
                error = ""
                for attempt in range(retries + 1):
                    try:
                        verdict = await backend.assess(action)
                        break
                    except Exception as e:  # recorded per step; the run continues
                        error = f"{type(e).__name__}: {e}"[:300]
                        await asyncio.sleep(1.0 * (attempt + 1))
                else:
                    row["error"] = error
                    counts["errors"] += 1
                    f.write(json.dumps(row) + "\n")
                    return
                spent["usd"] += verdict.cost_usd
                row.update(
                    p_unsafe=verdict.p_unsafe,
                    decision=decide(verdict).value,
                    category=verdict.category.value if verdict.category else None,
                    cost_usd=verdict.cost_usd,
                    latency_ms=round(verdict.latency_ms, 1),
                    raw=_slim(verdict.raw),
                )
                counts["scored"] += 1
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()

        start = time.perf_counter()
        await asyncio.gather(*(one(t, i, p) for t, i, p in todo))
    close = getattr(backend, "aclose", None)
    if close is not None:
        await close()
    return {
        **counts,
        "already_done": len(done),
        "cost_usd": round(spent["usd"], 4),
        "budget_stop": spent["stopped"],
        "seconds": round(time.perf_counter() - start, 1),
    }


def main(guard: str, sample_name: str, concurrency: int, max_cost: float | None) -> None:
    from agentguard.e2e.run import build_config
    from agentguard.guard.backends.jev import JevBackend
    from agentguard.guard.policy import tuned_policy

    trajectories = sample(load(), sample_name)
    policy = None
    if guard in ("jev-long", "jev-v2", "jev-v3"):
        backend = JevBackend(long_context=True, v2=guard == "jev-v2", v3=guard == "jev-v3")
        backend.name = guard
        policy = tuned_policy("jev")  # same thresholds as Jev: only the context changes
    else:
        backend = build_config(guard)
    no_retention(backend)
    out = OUT_DIR / f"{guard}.jsonl"
    n_steps = sum(len(proposals(t)) for t in trajectories)
    print(f"{guard} on BashArena {sample_name}: {len(trajectories)} runs, {n_steps} steps")
    summary = asyncio.run(
        run(
            backend,
            trajectories,
            out,
            concurrency=concurrency,
            max_cost=max_cost,
            whole_run=guard in WHOLE_RUN,
            ledger=guard in WITH_LEDGER,
            extended=guard in EXTENDED,
            policy=policy,
        )
    )
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")
