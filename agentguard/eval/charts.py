"""The Level 1 charts, drawn from results/eval/<split>.json. No API calls.

    uv run --group report python -m agentguard.eval.charts [--split test]

Writes to results/charts/:

- <split>-roc.png: ROC curves of every backend on clear rows, plus a zoom on FPR <= 10%.
- <split>-cost-recall.png: cost per 1,000 decisions vs recall at 1% FPR, with 95% CIs,
  plus the cascade sweep (first-stage thresholds picked on dev).
- <split>-reliability.png: reliability diagrams (calibration), one panel per backend.

Each backend keeps its color on every chart. Every point carries a text label as well as a
color, because three of the colors are low-contrast on the light background.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from agentguard.config import RESULTS_DIR  # noqa: E402
from agentguard.eval.evaluate import EVAL_DIR  # noqa: E402

CHART_DIR = RESULTS_DIR / "charts"
# Fixed slot per backend (validated categorical order), so a backend's color never changes.
COLORS = {
    "jev": "#2a78d6",
    "judge-cheap": "#eb6834",
    "judge-strong": "#1baf7a",
    "rules": "#eda100",
    "classifier": "#e87ba4",
}
LABELS = {
    "jev": "Jev 1.14",
    "judge-cheap": "LLM judge (cheap)",
    "judge-strong": "LLM judge (strong)",
    "rules": "Rules",
    "classifier": "DeBERTa classifier",
}
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
MUTED = "#8a8984"
GRID = "#e6e5e0"
FREE_X = 0.002  # where zero-cost (local) backends sit on the log cost axis
FREE_NUDGE = {"rules": 0.8, "classifier": 1.25}  # side by side, so their CI bars don't overlap


def style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": TEXT_2,
            "axes.titlecolor": TEXT,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "xtick.color": TEXT_2,
            "ytick.color": TEXT_2,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "lines.solid_capstyle": "round",
            "lines.solid_joinstyle": "round",
            "font.size": 10,
        }
    )


def ci_text(x: dict[str, Any]) -> str:
    return f"{x['value']:.2f} [{x['ci'][0]:.2f}, {x['ci'][1]:.2f}]"


def subtitle(fig: plt.Figure, text: str) -> None:
    fig.text(0.01, 0.005, text, color=MUTED, fontsize=8, ha="left", va="bottom")


def roc_chart(result: dict[str, Any], out: Path) -> None:
    fig, (full, zoom) = plt.subplots(1, 2, figsize=(11, 4.8), sharey=True)
    for b, e in result["backends"].items():
        xs, ys = zip(*e["clear"]["roc_curve"], strict=True)
        label = f"{LABELS.get(b, b)}  AUROC {ci_text(e['clear']['auroc'])}"
        for ax in (full, zoom):
            ax.plot(xs, ys, color=COLORS.get(b, TEXT_2), linewidth=2, label=label)
    full.plot([0, 1], [0, 1], color=GRID, linewidth=1)
    full.set(xlim=(0, 1), ylim=(0, 1.02), xlabel="False-positive rate (safe actions flagged)",
             ylabel="Recall (unsafe actions caught)")  # fmt: skip
    full.set_title(f"ROC curves, clear {result['split']} rows")
    full.legend(loc="lower right")
    zoom.set(xlim=(0, 0.1), xlabel="False-positive rate, zoomed to 0-10%")
    zoom.axvline(0.01, color=MUTED, linewidth=1)
    zoom.text(0.0105, 0.03, "1% FPR", color=TEXT_2, fontsize=8)
    zoom.set_title("Zoom: the low false-alarm region")
    for ax in (full, zoom):
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    zoom.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    n = result["backends"][next(iter(result["backends"]))]["clear"]
    subtitle(
        fig,
        f"{result['split']} split, rows not marked ambiguous: {n['unsafe']} unsafe, "
        f"{n['safe']} safe. AUROC with 95% bootstrap CI (1,000 resamples).",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=160)
    plt.close(fig)


def cost_recall_chart(result: dict[str, Any], out: Path) -> None:
    fig, ax = plt.subplots(figsize=(11.5, 5.4))
    for name, marker in (
        ("classifier>judge-cheap", "s"),
        ("jev>judge-cheap", "o"),
        ("judge-cheap>judge-strong", "D"),
    ):
        pts = [p for p in result["cascade_sweep"] if p["name"] == name]
        if not pts:
            continue
        xs = [max(p["clear"]["cost_per_1000_usd"], FREE_X) for p in pts]
        ys = [p["clear"]["recall_at_1pct_fpr"]["value"] for p in pts]
        first, last = name.split(">")
        ax.plot(xs, ys, color=MUTED, linewidth=1.5, marker=marker, markersize=6,
                markerfacecolor=SURFACE, markeredgecolor=MUTED, zorder=2,
                label=f"Cascade: {LABELS[first]} → {LABELS[last]}")  # fmt: skip
    for b, e in result["backends"].items():
        r = e["clear"]["recall_at_1pct_fpr"]
        x = max(e["cost_per_1000_usd"], FREE_X) * FREE_NUDGE.get(b, 1.0)
        ax.errorbar(x, r["value"], yerr=[[r["value"] - r["ci"][0]], [r["ci"][1] - r["value"]]],
                    color=COLORS.get(b, TEXT_2), linewidth=1.5, capsize=0, zorder=3)  # fmt: skip
        ax.plot(x, r["value"], "o", markersize=10, color=COLORS.get(b, TEXT_2),
                markeredgecolor=SURFACE, markeredgewidth=2, zorder=4,
                label=LABELS.get(b, b))  # fmt: skip
        left = b in ("rules", "jev")  # a neighbouring CI bar or cascade sits to the right
        dy = -14 if b == "judge-cheap" else 4  # below its cascade line
        ax.annotate(f"{LABELS.get(b, b)}  {r['value']:.0%}", (x, r["value"]),
                    textcoords="offset points", xytext=(-9 if left else 9, dy),
                    ha="right" if left else "left", fontsize=9, color=TEXT)  # fmt: skip
    ax.set_xscale("log")
    ax.set_xlim(FREE_X / 6, 60)
    ax.set_ylim(0, 1.08)

    def dollars(v: float, _: Any) -> str:
        return "free (local)" if abs(v - FREE_X) < 1e-9 else f"${v:g}"

    ticks = [FREE_X, 0.01, 0.1, 1, 10]
    ax.set_xticks(ticks)
    ax.xaxis.set_major_formatter(FuncFormatter(dollars))
    ax.xaxis.set_minor_locator(plt.NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.set(xlabel="Cost per 1,000 decisions (USD, log scale)",
           ylabel="Recall at 1% false-positive rate")  # fmt: skip
    ax.set_title("What each guard catches at 1% false alarms, against what it costs")
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5))
    subtitle(
        fig,
        f"{result['split']} split, clear rows. Bars: 95% bootstrap CI. Gray cascade points: the "
        "first stage's thresholds are picked on dev, letting it clear 0-20% of unsafe rows alone.",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(out, dpi=160)
    plt.close(fig)


def reliability_chart(result: dict[str, Any], out: Path) -> None:
    backends = list(result["backends"])
    fig, axes = plt.subplots(1, len(backends), figsize=(3.1 * len(backends), 3.6), sharey=True)
    axes = axes if len(backends) > 1 else [axes]
    for ax, b in zip(axes, backends, strict=True):
        e = result["backends"][b]
        bins = e["all"]["reliability"]
        ax.plot([0, 1], [0, 1], color=GRID, linewidth=1.2)
        ax.plot([x["mean_score"] for x in bins], [x["unsafe"] for x in bins],
                color=COLORS.get(b, TEXT_2), linewidth=2, zorder=2)  # fmt: skip
        ax.scatter([x["mean_score"] for x in bins], [x["unsafe"] for x in bins],
                   s=[12 + 3 * x["rows"] ** 0.5 * 6 for x in bins], color=COLORS.get(b, TEXT_2),
                   edgecolor=SURFACE, linewidth=2, zorder=3)  # fmt: skip
        ax.set_title(f"{LABELS.get(b, b)}\nECE {ci_text(e['all']['ece'])}", fontsize=10)
        ax.set(xlim=(-0.02, 1.02), ylim=(-0.02, 1.02), xlabel="Mean predicted p(unsafe)")
    axes[0].set_ylabel("Share actually unsafe")
    fig.suptitle("Calibration: can the probabilities be taken at face value?", x=0.01,
                 ha="left", fontsize=11, fontweight="bold", color=TEXT)  # fmt: skip
    subtitle(
        fig,
        f"{result['split']} split, all rows, 10 equal-width bins; dot area grows with rows in "
        "the bin. On the gray diagonal = well calibrated.",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.96))
    fig.savefig(out, dpi=160)
    plt.close(fig)


FAMILY_LABELS = {
    "encoding": "Encoding",
    "indirection": "Indirection\n(write a script, run it)",
    "splitting": "Splitting\n(across 3 steps)",
    "benign_framing": 'Benign framing\n("as requested")',
}


def flip_chart(attacks: dict[str, Any], out: Path) -> None:
    """Flip rate by attack family, one bar per backend, with 95% CIs."""
    backends = [b for b in COLORS if b in attacks["backends"]]
    families = list(FAMILY_LABELS)
    fig, ax = plt.subplots(figsize=(10, 4.8))
    width = 0.8 / max(len(backends), 1)
    for k, b in enumerate(backends):
        for i, f in enumerate(families):
            entry = attacks["backends"][b][f]
            x = i - 0.4 + width * (k + 0.5)
            if entry["flip_rate"] is None:
                ax.text(x, 0.01, "n/a", ha="center", fontsize=7, color=MUTED, rotation=90)
                continue
            v, (lo, hi) = entry["flip_rate"]["value"], entry["flip_rate"]["ci"]
            ax.bar(x, v, width=width * 0.86, color=COLORS[b], zorder=2)
            ax.errorbar(x, v, yerr=[[v - lo], [hi - v]], color=TEXT_2, linewidth=1,
                        capsize=0, zorder=3)  # fmt: skip
            ax.text(x + width * 0.08, v + 0.015, f"{v:.0%}", ha="left", fontsize=7, color=TEXT)
    ax.set_xticks(range(len(families)))
    ax.set_xticklabels([FAMILY_LABELS[f] for f in families], fontsize=9)
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.set_ylabel("Flip rate (caught before, missed after)")
    ax.grid(axis="x", visible=False)
    ax.set_title("How often a rewrite of a caught attack slips past each guard", pad=26)
    for b in backends:  # every backend in the legend, even one with no bars
        ax.bar(0, 0, width=0, color=COLORS[b], label=LABELS[b])
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncols=len(backends), fontsize=8)
    subtitle(
        fig,
        f"{attacks['rewrites']} rewrites of unsafe clear test actions, each machine-checked to "
        "do exactly what the original did. Flagged = p_unsafe >= 0.5.\nn/a: the guard caught "
        "none of the originals. Lines: 95% CI, resampling the original actions.",
    )
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    fig.savefig(out, dpi=160)
    plt.close(fig)


def draw(split: str, eval_dir: Path = EVAL_DIR, out_dir: Path = CHART_DIR) -> list[Path]:
    result = json.loads((eval_dir / f"{split}.json").read_text())
    out_dir.mkdir(parents=True, exist_ok=True)
    style()
    paths = [out_dir / f"{split}-{n}.png" for n in ("roc", "cost-recall", "reliability")]
    roc_chart(result, paths[0])
    cost_recall_chart(result, paths[1])
    reliability_chart(result, paths[2])
    attacks_path = eval_dir / "attacks.json"
    if split == "test" and attacks_path.is_file():
        paths.append(out_dir / "attacks-flip-rate.png")
        flip_chart(json.loads(attacks_path.read_text()), paths[-1])
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentguard.eval.charts")
    parser.add_argument("--split", default="test", choices=["dev", "test"])
    args = parser.parse_args(argv)
    for path in draw(args.split):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
