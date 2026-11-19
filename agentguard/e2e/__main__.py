"""CLI: `python -m agentguard.e2e {run,score,sheet}` (Level 3 end-to-end runs)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from agentguard.config import Settings, load_dotenv


def main(argv: list[str] | None = None) -> int:
    from agentguard.e2e.run import CONFIGS, KINDS, MODES

    parser = argparse.ArgumentParser(prog="agentguard.e2e")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run the agent on the scenarios with one guard config")
    run_p.add_argument("--config", required=True, choices=CONFIGS)
    run_p.add_argument("--mode", default="deny", choices=MODES)
    run_p.add_argument("--only", nargs="*", help="scenario ids, e.g. n01 a05")
    run_p.add_argument("--kinds", nargs="+", default=list(KINDS), choices=KINDS)
    run_p.add_argument("--concurrency", type=int, default=4)
    sub.add_parser("sheet", help="spreadsheet of every scenario, for review")
    sub.add_parser("score", help="usefulness, safety and interruptions from saved runs")
    args = parser.parse_args(argv)

    if args.command == "score":
        from agentguard.e2e.score import main as score_main

        return score_main()
    if args.command == "sheet":
        from agentguard.e2e.sheet import SHEET_PATH, export

        print(f"{export()} scenarios written to {SHEET_PATH}")
        return 0
    load_dotenv()
    settings = Settings.from_env()
    if args.config == "none" and args.mode == "human":
        print("`none` never escalates; use --mode deny", file=sys.stderr)
        return 2
    from agentguard.e2e.run import run_config

    records = asyncio.run(
        run_config(
            args.config,
            args.mode,
            settings,
            only=args.only,
            kinds=tuple(args.kinds),
            concurrency=args.concurrency,
        )  # fmt: skip
    )
    errors = sum(r["status"] == "api_error" for r in records)
    ok = [r for r in records if r["status"] != "api_error"]
    for kind in args.kinds:
        rows = [r for r in ok if r["kind"] == kind]
        what = "done" if kind == "normal" else "succeeded"
        tried = "" if kind == "normal" else f" (attempted {sum(r['attempted'] for r in rows)})"
        print(f"{args.config}/{args.mode} {kind}: {what} {sum(r['passed'] for r in rows)}"
              f"/{len(rows)}{tried}")  # fmt: skip
    print(f"errors {errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
