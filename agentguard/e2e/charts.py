"""Level 3 chart: safety against usefulness, from results/e2e/summary.json. No API calls.

    uv run --group report python -m agentguard.e2e.charts

Writes results/charts/level3-frontier-<agent>.png for every agent with side-task runs: one
panel per escalation mode, one point per guard configuration, with 95% Wilson intervals.
Top right is best: the agent still does its normal tasks and its side task never lands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from agentguard.e2e.score import SUMMARY_PATH  # noqa: E402
from agentguard.eval.charts import (  # noqa: E402
    CHART_DIR,
    COLORS,
    LABELS,
    MUTED,
    TEXT,
    TEXT_2,
    style,
    subtitle,
)

POINTS = {  # config -> (label, color, marker)
    "none": ("No guard", TEXT_2, "X"),
    "rules": (LABELS["rules"], COLORS["rules"], "o"),
    "classifier": (LABELS["classifier"], COLORS["classifier"], "o"),
    "jev": (LABELS["jev"], COLORS["jev"], "o"),
    "judge-cheap": (LABELS["judge-cheap"], COLORS["judge-cheap"], "o"),
    "judge-strong": (LABELS["judge-strong"], COLORS["judge-strong"], "o"),
    "cascade-jev-cheap": ("Cascade jev > cheap", MUTED, "s"),
    "cascade-cheap-strong": ("Cascade cheap > strong", MUTED, "D"),
}
MODE_TITLES = {
    "deny": "Nobody to ask: escalated actions are refused",
    "human": "A reviewer answers escalations (always correctly)",
}


def frontier_chart(agent: str, runs: dict[str, Any], out: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 5.6), sharey=True)
    for ax, mode in zip(axes, MODE_TITLES, strict=True):
        for config, (label, color, marker) in POINTS.items():
            key = f"{config}/{mode}" if config != "none" else "none/deny"
            s = runs.get(key)
            if not s or "sidetask" not in s or "usefulness" not in s:
                continue
            u, safe = s["usefulness"], s["sidetask"]["safety"]
            x, y = u["value"], safe["value"]
            ax.errorbar(
                x, y,
                xerr=[[x - u["ci"][0]], [u["ci"][1] - x]],
                yerr=[[y - safe["ci"][0]], [safe["ci"][1] - y]],
                color=color, alpha=0.45, linewidth=1, capsize=0, zorder=2,
            )  # fmt: skip
            ax.scatter(x, y, s=70, color=color, marker=marker, edgecolor="white",
                       linewidth=1.5, zorder=3, label=label)  # fmt: skip
        ax.set_title(MODE_TITLES[mode], fontsize=10)
        ax.set_xlabel("Usefulness: normal tasks done")
        ax.set_xlim(0, 1.02)
        ax.set_ylim(-0.02, 1.04)
        for axis in (ax.xaxis, ax.yaxis):
            axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0%}"))
    axes[0].set_ylabel("Safety: side tasks that did not land")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.075), ncols=4,
               fontsize=8.5, labelcolor=TEXT)  # fmt: skip
    fig.suptitle(f"Level 3: guards against an agent with a secret side task ({agent})",
                 x=0.01, y=0.985, ha="left", fontsize=11, fontweight="bold",
                 color=TEXT)  # fmt: skip
    subtitle(
        fig,
        "50 normal tasks and 50 side-task scenarios, one run each, real agent in a sandbox. "
        "No guard is the same point in both panels.\nLines: 95% Wilson intervals. "
        "Top right is best.",
    )
    fig.tight_layout(rect=(0, 0.2, 1, 0.96))
    fig.savefig(out, dpi=160)
    plt.close(fig)


def main() -> int:
    summary = json.loads(SUMMARY_PATH.read_text())
    style()
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    for agent, runs in summary["agents"].items():
        if sum("sidetask" in s and "usefulness" in s for s in runs.values()) >= 2:
            out = CHART_DIR / f"level3-frontier-{agent}.png"
            frontier_chart(agent, runs, out)
            print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
