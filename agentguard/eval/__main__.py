"""CLI: `python -m agentguard.eval run --backend NAME --split dev`, `... tune`, `... evaluate`."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from agentguard.config import load_dotenv
from agentguard.eval.run import run
from agentguard.guard.backends import BACKEND_NAMES, build_backend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentguard.eval")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run a guard backend over a split")
    run_p.add_argument("--backend", required=True, choices=BACKEND_NAMES)
    run_p.add_argument("--split", default="dev", choices=["train", "dev", "test", "attacks"])
    run_p.add_argument("--limit", type=int, default=None, help="only the first N rows")
    run_p.add_argument("--concurrency", type=int, default=8)
    run_p.add_argument(
        "--retry-failed",
        action="store_true",
        help="keep the last run's good verdicts; redo only errors and refusals",
    )
    run_p.add_argument(
        "--allow-test", action="store_true", help="the single Phase 4 run on the frozen test split"
    )
    run_p.add_argument(
        "--repeat", type=int, default=1, help="2 or 3: an extra run for latency (<stem>-rN)"
    )
    eval_p = sub.add_parser(
        "evaluate", help="Level 1 metrics with bootstrap CIs from saved runs (no API calls)"
    )
    eval_p.add_argument("--split", default="dev", choices=["dev", "test"])
    sub.add_parser(
        "tune",
        help="pick thresholds and a cascade from the saved dev runs (no API calls)",
    )
    sub.add_parser("attacks-build", help="Level 2 rewrites of unsafe test rows (no API calls)")
    sub.add_parser("attacks-score", help="flip rates from the saved attack runs (no API calls)")
    sub.add_parser("relabel-sheet", help="blind sheet of the ambiguous dev rows")
    compare_p = sub.add_parser("relabel-compare", help="compare a filled relabel sheet")
    compare_p.add_argument("sheet", type=Path)
    args = parser.parse_args(argv)

    if args.command == "relabel-sheet":
        from agentguard.eval.relabel import SHEET_PATH, export

        print(f"{export()} rows written to {SHEET_PATH}")
        return 0
    if args.command == "relabel-compare":
        from agentguard.eval.relabel import compare

        print(json.dumps(compare(args.sheet), indent=2))
        return 0
    if args.command == "attacks-build":
        from collections import Counter

        from agentguard.eval.attacks import build, write
        from agentguard.eval.run import ATTACKS_PATH

        rows = build()
        write(rows)
        print(f"{len(rows)} rewrites, each checked to rebuild its original, in {ATTACKS_PATH}")
        print(dict(Counter(r["meta"]["family"] for r in rows)))
        return 0
    if args.command == "attacks-score":
        from agentguard.eval.attacks import OUT_PATH, score

        result = score()
        print(json.dumps(result["backends"], indent=2))
        print(f"full results: {OUT_PATH}")
        return 0
    if args.command == "evaluate":
        from agentguard.eval.evaluate import EVAL_DIR, evaluate, headline

        result = evaluate(args.split)
        print(json.dumps(headline(result), indent=2))
        print(f"full results: {EVAL_DIR / (args.split + '.json')}")
        return 0
    if args.command == "tune":
        from agentguard.eval.tune import tune

        result = tune()
        print(json.dumps(brief(result), indent=2))
        return 0

    if args.split == "test" and not args.allow_test:
        print(
            "The test split is frozen for the single Phase 4 run. Tune on dev; "
            "pass --allow-test only for that final run.",
            file=sys.stderr,
        )
        return 2
    load_dotenv()

    async def go() -> dict:
        backend = build_backend(args.backend)
        try:
            return await run(
                backend,
                args.split,
                limit=args.limit,
                concurrency=args.concurrency,
                retry_failed=args.retry_failed,
                repeat=args.repeat,
            )
        finally:
            close = getattr(backend, "aclose", None)
            if close is not None:
                await close()

    summary = asyncio.run(go())
    print(json.dumps(summary, indent=2))
    return 0 if summary["errors"] == 0 else 1


def brief(result: dict) -> dict:
    """The headline of a tuning run; the full detail is in results/tuning/."""
    keys = ("unsafe_allowed_n", "safe_blocked_n", "escalated_n", "cost_per_1000_usd")
    return {
        "thresholds": {
            b: {
                "allow_below": round(e["allow_below"], 3),
                "block_above": round(e["block_above"], 3),
            }
            | {k: e["dev_tuned"][k] for k in keys}
            for b, e in result["thresholds"]["backends"].items()
        },
        "cascades": {
            c["name"]: {k: c["dev"][k] for k in keys} for c in result["cascade"]["candidates"]
        },
        "chosen": (result["cascade"]["chosen"] or {}).get("name"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
