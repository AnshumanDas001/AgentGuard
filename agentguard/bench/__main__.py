"""CLI: `python -m agentguard.bench {fetch,run,score}` (Level 4, public benchmarks)."""

from __future__ import annotations

import argparse
import urllib.request

from agentguard.config import load_dotenv


def fetch() -> int:
    """Download the public BashArena logs (once) and cache them as JSONL."""
    from agentguard.bench.basharena import CACHE, DATA_DIR, DOWNLOAD_URL, RUN_IDS, convert

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    paths = {}
    for kind, run_id in RUN_IDS.items():
        path = DATA_DIR / f"{run_id}.eval"
        if not path.is_file():
            print(f"downloading the {kind} runs ...")
            request = urllib.request.Request(
                DOWNLOAD_URL.format(run_id=run_id), headers={"User-Agent": "agentguard-bench"}
            )
            with urllib.request.urlopen(request) as response, path.open("wb") as f:
                f.write(response.read())
        paths[kind] = path
    print(f"{convert(paths)} runs cached in {CACHE}")
    return 0


def main(argv: list[str] | None = None) -> int:
    from agentguard.bench.run import SAMPLES

    parser = argparse.ArgumentParser(prog="agentguard.bench")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch", help="download and cache the public BashArena runs")
    run_p = sub.add_parser("run", help="score one guard on every step of a fixed sample of runs")
    run_p.add_argument("--guard", required=True)
    run_p.add_argument("--sample", default="all", choices=list(SAMPLES))
    run_p.add_argument("--concurrency", type=int, default=8)
    run_p.add_argument("--max-cost", type=float, help="stop new checks once this many USD spent")
    sub.add_parser("score", help="metrics from the saved runs")
    rv_p = sub.add_parser("review", help="second look: Haiku reviews each run's top Jev steps")
    rv_p.add_argument("--sample", default="d158", choices=list(SAMPLES))
    rv_p.add_argument("--max-cost", type=float, required=True)
    rv_p.add_argument("--concurrency", type=int, default=8)
    rve_p = sub.add_parser("review-eval", help="catch rates with the second look (no calls)")
    rve_p.add_argument("--sample", default="d158", choices=list(SAMPLES))
    sub.add_parser("mb-report", help="MonitoringBench result vs published monitors (bench group)")
    mb_p = sub.add_parser(
        "mb-convert", help="convert downloaded MonitoringBench logs (bench group)"
    )
    mb_p.add_argument("--all", action="store_true", help="all 2,644 attacks, not just the 196")
    head_p = sub.add_parser("head", help="learned run score on a guard's answers (train/test)")
    head_p.add_argument("--guard", default="jev-v2")
    head_p.add_argument("--train", default="f50", choices=list(SAMPLES))
    head_p.add_argument("--test", default="v58", choices=list(SAMPLES))
    head_p.add_argument("--facts", action="store_true", help="add the two run-level ledger facts")
    head_p.add_argument("--max-only", action="store_true", help="each question's run max only")
    head_p.add_argument("--profile", action="store_true", help="add Jev-v4 task-profile features")
    args = parser.parse_args(argv)

    if args.command == "fetch":
        return fetch()
    if args.command == "review-eval":
        import json

        from agentguard.bench.review import evaluate

        print(json.dumps(evaluate(args.sample), indent=2))
        return 0
    if args.command == "mb-report":
        import json

        from agentguard.bench.mb_report import main as report_main

        r = report_main()
        print(
            json.dumps({k: r[k] for k in ("jev", "jev_cost", "control_random_answers")}, indent=2)
        )
        return 0
    if args.command == "mb-convert":
        from agentguard.bench.monitoringbench import build

        print(build(None if args.all else {"opus_only"}))
        return 0
    if args.command == "head":
        from agentguard.bench.head import main as head_main

        head_main(args.guard, args.train, args.test, args.facts, args.max_only, args.profile)
        return 0
    if args.command == "score":
        from agentguard.bench.score import main as score_main

        score_main()
        return 0
    load_dotenv()
    if args.command == "review":
        from agentguard.bench.review import main as review_main

        review_main(args.sample, args.max_cost, args.concurrency)
        return 0
    from agentguard.bench.run import main as run_main

    run_main(args.guard, args.sample, args.concurrency, args.max_cost)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
