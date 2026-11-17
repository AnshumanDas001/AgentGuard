"""`make data-stats`: how the dataset is shaping up against the targets in the rules."""

from __future__ import annotations

import math
from collections import Counter

from agentguard.dataset.store import DataPaths, load_labels, load_rows
from agentguard.guard.schemas import RiskCategory

# Rules section 9: per category, the TEST split needs these; the full dataset scales by 1/0.3.
TEST_SHARE = 0.3
TEST_MIN_UNSAFE = 30
TEST_MIN_HARD_NEGATIVES = 15
TARGET_UNSAFE_SHARE = 0.40
TARGET_HARD_NEGATIVE_SHARE = 1 / 3

FULL_MIN_UNSAFE = math.ceil(TEST_MIN_UNSAFE / TEST_SHARE)
FULL_MIN_HARD_NEGATIVES = math.ceil(TEST_MIN_HARD_NEGATIVES / TEST_SHARE)


def compute(paths: DataPaths) -> dict:
    rows = load_rows(paths)
    labels = load_labels(paths)
    decided = [labels[r.id] for r in rows if r.id in labels]
    usable = [r for r in decided if r.label != "excluded"]
    unsafe = [r for r in usable if r.label == "unsafe"]
    safe = [r for r in usable if r.label == "safe"]
    hard = [r for r in safe if r.imitates is not None]
    return {
        "rows": len(rows),
        "labeled": len(decided),
        "unlabeled": len(rows) - len(decided),
        "excluded": len(decided) - len(usable),
        "unsafe": len(unsafe),
        "safe": len(safe),
        "hard_negatives": len(hard),
        "ambiguous": sum(r.ambiguous for r in usable),
        "unsafe_by_category": Counter(r.category for r in unsafe),
        "hard_by_category": Counter(r.imitates for r in hard),
        "by_source": Counter(r.source for r in rows),
        "labeled_by_source": Counter(r.source for r in rows if r.id in labels),
        "by_rules_version": Counter(r.rules_version for r in decided),
    }


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "n/a"


def render(s: dict) -> str:
    usable = s["unsafe"] + s["safe"]
    lines = [
        f"Rows: {s['rows']}  labeled: {s['labeled']}  unlabeled: {s['unlabeled']}  "
        f"excluded: {s['excluded']}",
        f"Unsafe: {s['unsafe']} of {usable} ({_pct(s['unsafe'], usable)}; "
        f"target {TARGET_UNSAFE_SHARE:.0%})",
        f"Hard negatives: {s['hard_negatives']} of {s['safe']} safe "
        f"({_pct(s['hard_negatives'], s['safe'])}; target at least 33%)",
        f"Ambiguous: {s['ambiguous']}",
        "",
        f"{'Category':34} {'unsafe':>8} {'hard neg':>9}   "
        f"(full-dataset targets {FULL_MIN_UNSAFE} / {FULL_MIN_HARD_NEGATIVES})",
    ]
    for category in RiskCategory:
        u = s["unsafe_by_category"][category]
        h = s["hard_by_category"][category]
        flag = "" if u >= FULL_MIN_UNSAFE and h >= FULL_MIN_HARD_NEGATIVES else "  below target"
        lines.append(f"{category.value:34} {u:>8} {h:>9}{flag}")
    lines += ["", f"{'Source':34} {'rows':>8} {'labeled':>9}"]
    for source, n in sorted(s["by_source"].items()):
        lines.append(f"{source:34} {n:>8} {s['labeled_by_source'][source]:>9}")
    if s["by_rules_version"]:
        versions = ", ".join(f"{v}: {n}" for v, n in sorted(s["by_rules_version"].items()))
        lines += ["", f"Labels by rules version: {versions}"]
    return "\n".join(lines)
