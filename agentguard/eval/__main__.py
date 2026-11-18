"""CLI: `python -m agentguard.eval run --backend NAME --split dev`, and `... tune`."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from agentguard.config import load_dotenv
from agentguard.eval.run import run
from agentguard.guard.backends import BACKEND_NAMES, build_backend


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentguard.eval")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run a guard backend over a split")
    run_p.add_argument("--backend", required=True, choices=BACKEND_NAMES)
    run_p.add_argument("--split", default="dev", choices=["train", "dev", "test"])
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
    sub.add_parser(
        "tune",
        help="pick thresholds and a cascade from the saved dev runs (no API calls)",
    )
    args = parser.parse_args(argv)

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
