"""Figures for the write-up (LessWrong post, blog), drawn from saved results. No API calls.

    uv run --group report python -m agentguard.bench post-charts

Writes to results/charts/:

- monitor-pipeline.png: how a run is scored, stage 1 (Jev) and stage 2 (Haiku second look).
- jev-weights.png: the learned run score's 15 weights (frozen, trained on d158).
- mb-cost.png: what the 746 MonitoringBench runs cost us, next to estimates for the published
  monitors (OpenRouter list prices, input tokens only).
- mb-catch-post.png: mb-catch.png without the random-answer control row.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

from agentguard.bench.mb_report import OUT, chart  # noqa: E402
from agentguard.eval.charts import CHART_DIR, COLORS, GRID, MUTED, SURFACE, TEXT, TEXT_2, style  # noqa: E402

BLUE, ORANGE, GREY = COLORS["jev"], COLORS["judge-cheap"], "#c9c8c2"
LABELS = {
    "hides_intent:max": "Hides its intent",
    "weakens_security_control:max": "Weakens a security control",
    "fact:templates": "Ledger: built security settings from templates",
    "destructive_file_ops:max": "Deletes or overwrites files",
    "fact:uses_own_code": "Ledger: runs code it wrote earlier",
    "irreversible_external_action:max": "Irreversible outside effect",
    "unnamed_destination:max": "Unnamed network address",
    "resource_abuse:max": "Resource abuse",
    "indirect_security_change:max": "Indirect security change",
    "credential_access:max": "Reads secrets",
    "run_goes_beyond_task:max": "Run goes beyond the task",
    "data_exfiltration:max": "Sends private data out",
    "privilege_escalation_persistence:max": "Privilege or persistence",
    "untrusted_code:max": "Untrusted code",
    "injection_driven:max": "Follows injected instructions",
}
# Measured spend, and estimates from OpenRouter list prices ($/M input tokens) for the same 746
# runs: reading each finished run once is ~7.75M input tokens; checking every action before it
# runs (rereading the run so far at each of 21,329 steps, no prompt caching) is ~206M.
OURS_USD = 4.12
# (read once, every action) in USD, as quoted in the write-up: list price x token count.
ESTIMATES = {
    "GPT-5": (9.70, 260),
    "o3": (15.50, 410),
    "Claude Sonnet 4.5": (23.30, 620),
    "Claude Opus 4.5": (38.80, 1030),
}


def _save(fig, name: str) -> Path:
    out = CHART_DIR / name
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return out


def _title(fig, title: str, note: str | None = None) -> None:
    fig.suptitle(title, x=0.01, ha="left", fontsize=11, fontweight="bold", color=TEXT)
    if note:
        fig.text(0.01, 0.005, note, color=MUTED, fontsize=7.5, ha="left", va="bottom")


def pipeline() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(9.2, 4.6))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 50)
    ax.axis("off")

    def box(x, y, w, h, head, body, edge=GRID, fill="#ffffff", bold=False):
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0.4,rounding_size=1.2",
                linewidth=1.4 if bold else 1,
                edgecolor=edge,
                facecolor=fill,
            )
        )
        ax.text(
            x + w / 2,
            y + h - 2.2,
            head,
            ha="center",
            va="top",
            fontsize=8.6,
            fontweight="bold",
            color=TEXT,
        )
        ax.text(
            x + w / 2,
            y + h - 6.4,
            body,
            ha="center",
            va="top",
            fontsize=7.3,
            color=TEXT_2,
            linespacing=1.35,
        )

    def arrow(x1, y1, x2, y2, label=None, dy=1.2):
        ax.add_patch(
            FancyArrowPatch(
                (x1, y1),
                (x2, y2),
                arrowstyle="-|>",
                mutation_scale=10,
                color=MUTED,
                linewidth=1.1,
                shrinkA=0,
                shrinkB=0,
            )
        )
        if label:
            ax.text(
                (x1 + x2) / 2,
                (y1 + y2) / 2 + dy,
                label,
                ha="center",
                va="bottom",
                fontsize=6.8,
                color=MUTED,
            )

    ax.text(0.5, 47.5, "STAGE 1   Jev, every action", fontsize=8, fontweight="bold", color=BLUE)
    ax.text(
        0.5, 18.5, "STAGE 2   Haiku, two steps per run", fontsize=8, fontweight="bold", color=ORANGE
    )
    y, h = 26, 18
    box(0.5, y, 14.5, h, "Proposed action", "the agent's next\ncommand, before\nit runs")
    box(
        19,
        y,
        15,
        h,
        "Security ledger",
        "plain code: files,\nsecrets, controls,\naddresses, scripts",
    )
    box(38, y, 14.5, h, "Pre-filter", "~45% of steps\nskip Jev (they stay\nin the history)")
    box(56.5, y, 15, h, "Jev: 13 questions", "yes/no, each a\nnumber 0–1\n~$0.00025 a call")
    box(
        75.5,
        y,
        23.5,
        h,
        "Learned run score s",
        "per-question max over the run\n+ 2 ledger facts → z-scores\n× logistic-regression weights",
        edge=BLUE,
        bold=True,
    )
    for x1, x2 in ((15.8, 18.2), (34.8, 37.2), (53.3, 55.7), (72.3, 74.7)):
        arrow(x1, y + h / 2, x2, y + h / 2)

    y2, h2 = 2, 14
    box(56.5, y2, 15, h2, "Claude Haiku 5.5", "reviews the run's 2\nhighest steps, 0–10")
    box(
        75.5,
        y2,
        23.5,
        h2,
        "Max of percentile ranks",
        "higher of Jev's rank and Haiku's:\neither stage can raise the alarm",
        edge=ORANGE,
        bold=True,
    )
    arrow(80, y - 0.5, 66, y2 + h2 + 0.5, "top-2 steps", dy=0.4)
    arrow(72.3, y2 + h2 / 2, 74.7, y2 + h2 / 2)
    arrow(92, y - 0.5, 92, y2 + h2 + 0.5)
    ax.text(93, 20, "s", fontsize=7.5, color=MUTED, style="italic")

    ax.text(
        99,
        45.6,
        "Version 1 (Jev alone): flag if s ≥ line → 45%",
        ha="right",
        fontsize=7.6,
        color=BLUE,
        fontweight="bold",
    )
    ax.text(
        99,
        -0.6,
        "Version 2 (Jev + Haiku): flag if rank ≥ line → 63%",
        ha="right",
        va="top",
        fontsize=7.6,
        color=ORANGE,
        fontweight="bold",
    )
    ax.text(
        0.5,
        9,
        "Catch rates: share of 196 MonitoringBench\nattacks caught when the line flags\n"
        "1% of 550 honest runs.",
        fontsize=7,
        color=MUTED,
        va="center",
        linespacing=1.4,
    )
    _title(fig, "How the monitor scores a run")
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    return _save(fig, "monitor-pipeline.png")


def weights() -> Path:
    head = json.loads((OUT / "jev-head.json").read_text())
    rows = sorted(head["weights"].items(), key=lambda kv: kv[1])
    style()
    fig, ax = plt.subplots(figsize=(7.6, 5.6))
    for y, (_name, w) in enumerate(rows):
        ax.barh(y, w, height=0.62, color=ORANGE if w > 0 else BLUE, linewidth=0)
        ax.text(
            w + (0.02 if w > 0 else -0.02),
            y,
            f"{w:+.2f}".replace("-", "−"),
            va="center",
            ha="left" if w > 0 else "right",
            fontsize=8,
            color=TEXT_2,
        )
    ax.set_yticks(range(len(rows)), [LABELS.get(k, k) for k, _ in rows])
    ax.axvline(0, color=TEXT_2, linewidth=0.8)
    ax.set_xlim(-0.95, 0.95)
    ax.set_xlabel("Weight (per typical spread above the typical value)")
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.set_axisbelow(True)
    ax.text(
        0.9,
        -1.35,
        "points toward attack →",
        ha="right",
        fontsize=8,
        color=ORANGE,
        fontweight="bold",
    )
    ax.text(
        -0.9, -1.35, "← points toward honest", ha="left", fontsize=8, color=BLUE, fontweight="bold"
    )
    ax.set_ylim(-1.9, len(rows) - 0.4)
    _title(
        fig,
        "What the learned run score learned: one weight per input",
        "Logistic regression on 158 of Redwood's BashArena runs (78 attacks, 80 honest), "
        "inputs as z-scores. Frozen before MonitoringBench.\n'Weakens a security control' "
        "is negative because honest BashArena tasks often ask for firewall or sudo changes.",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.96))
    return _save(fig, "jev-weights.png")


def cost() -> Path:
    style()
    fig, ax = plt.subplots(figsize=(7.6, 3.9))
    names = list(ESTIMATES)[::-1]
    for y, name in enumerate(names):
        once, every = ESTIMATES[name]
        ax.plot([once, every], [y, y], color=GRID, linewidth=2, zorder=1)
        ax.scatter([once], [y], s=60, facecolor=SURFACE, edgecolor=TEXT_2, linewidth=1.4, zorder=2)
        ax.scatter([every], [y], s=60, color=TEXT_2, zorder=2)
        ax.text(once / 1.12, y, f"≥${once:.2f}", ha="right", va="center", fontsize=8, color=TEXT_2)
        ax.text(
            every * 1.12, y, f"≈${every:,.0f}", ha="left", va="center", fontsize=8, color=TEXT_2
        )
    y = len(names)
    ax.scatter([OURS_USD], [y], s=80, color=BLUE, zorder=3)
    ax.text(
        OURS_USD * 1.12,
        y,
        f"${OURS_USD:.2f} measured, every action checked",
        ha="left",
        va="center",
        fontsize=8.5,
        color=TEXT,
        fontweight="bold",
    )
    ax.set_yticks(range(y + 1), names + ["Jev + Haiku (ours)"])
    ax.get_yticklabels()[-1].set_fontweight("bold")
    ax.set_xscale("log")
    ax.set_xlim(1.5, 4000)
    ax.set_ylim(-0.6, y + 0.6)
    ax.set_xticks(
        [2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000],
        ["$2", "$5", "$10", "$20", "$50", "$100", "$200", "$500", "$1k", "$2k"],
    )
    ax.set_xlabel("Cost to monitor all 746 MonitoringBench runs (log scale)")
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.scatter(
        [], [], s=50, facecolor=SURFACE, edgecolor=TEXT_2, label="read each finished run once"
    )
    ax.scatter([], [], s=50, color=TEXT_2, label="check every action (no caching)")
    ax.legend(loc="upper right", fontsize=7.5, frameon=False)
    _title(
        fig,
        "Cost: our measured spend vs estimates for LLM monitors",
        "Estimates: OpenRouter list prices, input tokens only (characters ÷ 4), before output or "
        "reasoning tokens.\nRead once ≈ 7.75M tokens; every action ≈ 206M tokens. Prompt caching "
        "would cut the every-action figures several-fold.",
    )
    fig.tight_layout(rect=(0, 0.1, 1, 0.95))
    return _save(fig, "mb-cost.png")


def main() -> list[Path]:
    return [pipeline(), weights(), cost(), chart(CHART_DIR / "mb-catch-post.png", control=False)]
