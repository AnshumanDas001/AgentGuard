"""Level 1 metrics, as plain functions of scores and labels (no API calls, no numpy).

`pos` is the list of p_unsafe scores of unsafe rows, `neg` the scores of safe rows. A row is
flagged at threshold t when its score is >= t, matching `eval run`'s "at 0.5" numbers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def auroc(pos: Sequence[float], neg: Sequence[float]) -> float | None:
    """Chance a random unsafe row outscores a random safe one (ties count half), via ranks."""
    if not pos or not neg:
        return None
    scored = sorted([(p, 1) for p in pos] + [(n, 0) for n in neg])
    rank_sum, i = 0.0, 0
    while i < len(scored):
        j = i
        while j < len(scored) and scored[j][0] == scored[i][0]:
            j += 1
        mid_rank = (i + 1 + j) / 2  # tied scores share their average rank
        rank_sum += mid_rank * sum(label for _, label in scored[i:j])
        i = j
    n_pos, n_neg = len(pos), len(neg)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def roc_curve(pos: Sequence[float], neg: Sequence[float]) -> list[tuple[float, float]]:
    """(false-positive rate, recall) at every distinct score used as the threshold."""
    points = [(0.0, 0.0)]
    for t in sorted(set(pos) | set(neg), reverse=True):
        points.append((sum(n >= t for n in neg) / len(neg), sum(p >= t for p in pos) / len(pos)))
    return points


def recall_at_fpr(pos: Sequence[float], neg: Sequence[float], max_fpr: float = 0.01) -> float:
    """Highest recall of any threshold that flags at most max_fpr of safe rows.

    The threshold is picked on the same rows it is scored on (the usual definition), so this
    measures ranking quality; `deployed` below scores the thresholds picked on dev.
    """
    cut = fpr_cut(neg, max_fpr)
    return sum(p > cut for p in pos) / len(pos)


def fpr_cut(neg: Sequence[float], max_fpr: float = 0.01) -> float:
    """Flag scores strictly above this and at most max_fpr of safe rows are flagged.

    It is the (allowed+1)-th highest safe score: flagging ties with it would add more than
    `allowed` false alarms.
    """
    allowed = math.floor(max_fpr * len(neg) + 1e-9)
    ranked = sorted(neg, reverse=True)
    return ranked[allowed] if allowed < len(ranked) else -math.inf


def average_precision(pos: Sequence[float], neg: Sequence[float]) -> float | None:
    """PR-AUC as average precision: precision at each recall step, weighted by the step.

    Tied scores form one threshold, as in sklearn's average_precision_score.
    """
    if not pos:
        return None
    total, tp, fp, ap = len(pos), 0, 0, 0.0
    scored = sorted([(p, 1) for p in pos] + [(n, 0) for n in neg], reverse=True)
    i = 0
    while i < len(scored):
        j = i
        while j < len(scored) and scored[j][0] == scored[i][0]:
            j += 1
        new_tp = sum(label for _, label in scored[i:j])
        tp, fp = tp + new_tp, fp + (j - i - new_tp)
        ap += (new_tp / total) * (tp / (tp + fp))
        i = j
    return ap


def calibration(
    scores: Sequence[float], labels: Sequence[bool], bins: int = 10
) -> tuple[float, list[dict[str, float]]]:
    """Expected Calibration Error over equal-width bins, and the per-bin table behind it.

    ECE is the row-weighted average gap between the mean score in a bin and the share of
    unsafe rows in it. A score of exactly 1.0 goes in the top bin.
    """
    table = []
    ece = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, s in enumerate(scores) if lo <= s < hi or (b == bins - 1 and s == hi)]
        if not idx:
            continue
        mean_score = sum(scores[i] for i in idx) / len(idx)
        unsafe_share = sum(labels[i] for i in idx) / len(idx)
        ece += len(idx) / len(scores) * abs(mean_score - unsafe_share)
        table.append(
            {"lo": lo, "hi": hi, "rows": len(idx), "mean_score": mean_score, "unsafe": unsafe_share}
        )
    return ece, table


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolation percentile, q in [0, 100]."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)
