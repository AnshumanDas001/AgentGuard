"""Dataset command line: `python -m agentguard.dataset <command>`; see --help."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from agentguard.dataset import authoring, benchmarks
from agentguard.dataset import check as check_mod
from agentguard.dataset import label as label_mod
from agentguard.dataset import sheet as sheet_mod
from agentguard.dataset import stats as stats_mod
from agentguard.dataset.importers import import_rows, rows_from_run_log
from agentguard.dataset.split import split_and_freeze
from agentguard.dataset.store import DataPaths, DatasetError


def main() -> int:
    parser = argparse.ArgumentParser(prog="agentguard.dataset")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="validate every dataset file")
    sub.add_parser("stats", help="counts and progress against the targets")
    label_p = sub.add_parser("label", help="label unlabeled rows, one at a time")
    label_p.add_argument("--limit", type=int, default=None, help="stop after N saved labels")
    import_p = sub.add_parser("import-log", help="add rows from an AgentGuard run log")
    import_p.add_argument("log", type=Path)
    import_p.add_argument("--source", default="agent-run", help="source name for the rows")
    export_p = sub.add_parser("export-sheet", help="write unlabeled rows to an .xlsx to label")
    export_p.add_argument("--out", type=Path, default=None)
    import_s = sub.add_parser("import-sheet", help="save labels from a filled-in .xlsx")
    import_s.add_argument("workbook", type=Path)
    write_p = sub.add_parser("write-sheet", help="blank .xlsx for writing new rows by hand")
    write_p.add_argument("--rows", type=int, default=60)
    write_p.add_argument("--out", type=Path, default=None)
    written_p = sub.add_parser("import-written", help="add handwritten rows from a filled .xlsx")
    written_p.add_argument("workbook", type=Path)
    injec_p = sub.add_parser("import-injecagent", help="fetch InjecAgent and add converted rows")
    injec_p.add_argument("--per-tool", type=int, default=5, help="cases per user tool (17 tools)")
    split_p = sub.add_parser("split", help="stratified split and freeze (runs once)")
    split_p.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    paths = DataPaths()

    try:
        if args.command == "check":
            report = check_mod.check(paths)
            for warning in report.warnings:
                print(f"warning: {warning}")
            for error in report.errors:
                print(f"error: {error}")
            print("ok" if report.ok else f"{len(report.errors)} errors")
            return 0 if report.ok else 1
        if args.command == "stats":
            print(stats_mod.render(stats_mod.compute(paths)))
            return 0
        if args.command == "label":
            label_mod.session(paths, limit=args.limit)
            return 0
        if args.command == "import-log":
            added, skipped = import_rows(paths, rows_from_run_log(args.log, args.source))
            print(
                f"added {added} rows to data/raw/{args.source}.jsonl "
                f"({skipped} skipped: already in the dataset)"
            )
            return 0
        if args.command == "export-sheet":
            stamp = datetime.now().strftime("%Y%m%d-%H%M")
            out = args.out or paths.root / "labeled" / "sheets" / f"labeling-{stamp}.xlsx"
            count = sheet_mod.export_sheet(paths, out)
            print(f"wrote {count} rows to {out}")
            print("fill in the yellow columns, save, then run: make import-labels SHEET=<path>")
            return 0
        if args.command == "import-sheet":
            result = sheet_mod.import_sheet(paths, args.workbook)
            for warning in result.warnings:
                print(f"warning: {warning}")
            for error in result.errors:
                print(f"error: {error}")
            if result.errors:
                print(f"nothing saved: fix the {len(result.errors)} errors above and import again")
                return 1
            print(f"saved {result.saved} labels; {result.blank} rows left blank stay unlabeled")
            return 0
        if args.command == "write-sheet":
            stamp = datetime.now().strftime("%Y%m%d-%H%M")
            out = args.out or paths.root / "labeled" / "sheets" / f"writing-{stamp}.xlsx"
            authoring.export_template(out, rows=args.rows)
            print(f"wrote a blank sheet with {args.rows} lines to {out}")
            print("write rows on the Write tab, save, then run: make import-written SHEET=<path>")
            return 0
        if args.command == "import-written":
            result = authoring.import_written(paths, args.workbook)
            for warning in result.warnings:
                print(f"warning: {warning}")
            for error in result.errors:
                print(f"error: {error}")
            if result.errors:
                print(f"nothing saved: fix the {len(result.errors)} errors above and import again")
                return 1
            print(f"added {len(result.added)} rows to data/raw/handwritten.jsonl (unlabeled)")
            return 0
        if args.command == "import-injecagent":
            files = benchmarks.fetch_injecagent(paths.root / "external" / "injecagent")
            rows, skipped = benchmarks.rows_from_injecagent(files[0].parent, args.per_tool)
            for note in skipped:
                print(f"skipped {note}")
            added, existing = import_rows(paths, rows)
            print(f"added {added} rows to data/raw/injecagent.jsonl ({existing} already there)")
            return 0
        if args.command == "split":
            print(json.dumps(split_and_freeze(paths, seed=args.seed), indent=2))
            return 0
    except DatasetError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nstopped; everything labeled so far is saved")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
