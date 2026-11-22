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
    head_p = sub.add_parser("head", help="learned run score on a guard's answers (train/test)")
    head_p.add_argument("--guard", default="jev-v2")
    head_p.add_argument("--train", default="f50", choices=list(SAMPLES))
    head_p.add_argument("--test", default="v58", choices=list(SAMPLES))
    args = parser.parse_args(argv)

    if args.command == "fetch":
        return fetch()
    if args.command == "head":
        from agentguard.bench.head import main as head_main

        head_main(args.guard, args.train, args.test)
        return 0
    if args.command == "score":
        from agentguard.bench.score import main as score_main

        score_main()
        return 0
    load_dotenv()
    from agentguard.bench.run import main as run_main

    run_main(args.guard, args.sample, args.concurrency, args.max_cost)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
