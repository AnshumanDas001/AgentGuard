"""`make data-stats`: how the dataset is shaping up against the targets in the rules."""

from __future__ import annotations

from collections import Counter

from agentguard.dataset.store import DataPaths, load_labels, load_rows
from agentguard.guard.schemas import RiskCategory

# Rules section 9 (D7, option 2): per-category results are graded by how many unsafe rows the
# TEST split will hold (about TEST_SHARE of each category), and every category needs a floor.
TEST_SHARE = 0.3
TEST_MEASURABLE = 30  # unsafe rows in test for a per-category result to count as a headline
TEST_INDICATIVE = 10  # below this in test, a per-category result is "too few to measure"
FLOOR_UNSAFE = 20  # full dataset, per category: so no category is near-empty
FLOOR_HARD_NEGATIVES = 10
TARGET_HARD_NEGATIVE_SHARE = 0.25


def tier(unsafe: int) -> str:
    """How a category's test result can be reported, from its full-dataset unsafe count."""
    in_test = unsafe * TEST_SHARE
    if in_test >= TEST_MEASURABLE:
        return "measurable"
    if in_test >= TEST_INDICATIVE:
        return "indicative"
    return "too few"


def shortfall(unsafe: int, hard: int) -> str:
    """Rows still needed to reach the floor, or '' if it is met."""
    need = [f"{FLOOR_UNSAFE - unsafe} unsafe"] if unsafe < FLOOR_UNSAFE else []
    if hard < FLOOR_HARD_NEGATIVES:
        need.append(f"{FLOOR_HARD_NEGATIVES - hard} look-alike")
    return "needs " + " + ".join(need) if need else ""


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
        f"Unsafe: {s['unsafe']} of {usable} ({_pct(s['unsafe'], usable)}; no target: guards are "
        "scored per class, so the mix does not bias recall or false-positive rate)",
        f"Hard negatives: {s['hard_negatives']} of {s['safe']} safe "
        f"({_pct(s['hard_negatives'], s['safe'])}; target at least "
        f"{TARGET_HARD_NEGATIVE_SHARE:.0%})",
        f"Ambiguous: {s['ambiguous']}",
        "",
        f"{'Category':34} {'unsafe':>7} {'hard neg':>9} {'≈ test':>7}  {'result':11} floor "
        f"({FLOOR_UNSAFE} / {FLOOR_HARD_NEGATIVES})",
    ]
    for category in RiskCategory:
        u = s["unsafe_by_category"][category]
        h = s["hard_by_category"][category]
        lines.append(
            f"{category.value:34} {u:>7} {h:>9} {round(u * TEST_SHARE):>7}  {tier(u):11} "
            f"{shortfall(u, h) or 'ok'}"
        )
    lines += ["", f"{'Source':34} {'rows':>8} {'labeled':>9}"]
    for source, n in sorted(s["by_source"].items()):
        lines.append(f"{source:34} {n:>8} {s['labeled_by_source'][source]:>9}")
    if s["by_rules_version"]:
        versions = ", ".join(f"{v}: {n}" for v, n in sorted(s["by_rules_version"].items()))
        lines += ["", f"Labels by rules version: {versions}"]
    return "\n".join(lines)
