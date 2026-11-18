"""CLI: `python -m agentguard.e2e {run,sheet}` (Level 3 end-to-end runs)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from agentguard.config import Settings, load_dotenv


def main(argv: list[str] | None = None) -> int:
    from agentguard.e2e.run import CONFIGS, MODES

    parser = argparse.ArgumentParser(prog="agentguard.e2e")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="run the agent on the scenarios with one guard config")
    run_p.add_argument("--config", required=True, choices=CONFIGS)
    run_p.add_argument("--mode", default="deny", choices=MODES)
    run_p.add_argument("--only", nargs="*", help="scenario ids, e.g. n01 a05")
    run_p.add_argument("--concurrency", type=int, default=4)
    sub.add_parser("sheet", help="spreadsheet of every scenario, for review")
    args = parser.parse_args(argv)

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
        run_config(args.config, args.mode, settings, only=args.only, concurrency=args.concurrency)
    )
    errors = sum(r["status"] == "api_error" for r in records)
    normal = [r for r in records if r["kind"] == "normal" and r["status"] != "api_error"]
    attack = [r for r in records if r["kind"] == "attack" and r["status"] != "api_error"]
    print(
        f"{args.config}/{args.mode}: normal done {sum(r['passed'] for r in normal)}/{len(normal)}"
        f", attacks succeeded {sum(r['passed'] for r in attack)}/{len(attack)}"
        f" (attempted {sum(r['attempted'] for r in attack)}), errors {errors}"
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
