import json
import random

import pytest

from agentguard.eval import bootstrap, evaluate, metrics
from agentguard.eval.run import auroc as brute_force_auroc


def test_auroc_matches_pairwise_count_with_ties():
    assert metrics.auroc([0.9, 0.8], [0.1, 0.8]) == pytest.approx(3.5 / 4)
    rng = random.Random(0)
    for _ in range(20):
        pos = [rng.choice([0.0, 0.2, 0.5, 0.9, 1.0]) for _ in range(rng.randint(1, 15))]
        neg = [rng.choice([0.0, 0.2, 0.5, 0.9, 1.0]) for _ in range(rng.randint(1, 15))]
        assert metrics.auroc(pos, neg) == pytest.approx(brute_force_auroc(pos, neg))
    assert metrics.auroc([], [0.1]) is None


def test_recall_at_fpr_never_exceeds_the_false_alarm_budget():
    neg = [0.1] * 99 + [0.95]  # 1% of 100 safe rows = 1 false alarm allowed
    assert metrics.recall_at_fpr([0.9, 0.05], neg) == 0.5
    # Two safe rows tied at the top: flagging them would be 2 false alarms, so the cut is 0.95.
    assert metrics.recall_at_fpr([0.9, 0.05], [0.1] * 98 + [0.95, 0.95]) == 0.0
    assert metrics.recall_at_fpr([1.0, 0.3], [0.2] * 10) == 1.0  # 0 allowed: cut is 0.2


def test_average_precision_by_hand():
    # 0.9 unsafe (P=1, R=.5), 0.8 safe, 0.7 unsafe (P=2/3, R=1).
    assert metrics.average_precision([0.9, 0.7], [0.8]) == pytest.approx(0.5 + 0.5 * 2 / 3)
    # A tie between an unsafe and a safe row is one threshold: P = 1/2 at R = 1.
    assert metrics.average_precision([0.5], [0.5]) == pytest.approx(0.5)


def test_calibration_error_and_bins():
    ece, table = metrics.calibration([0.05, 0.05, 0.95, 1.0], [False, True, True, True])
    # Bin 0: mean 0.05, 50% unsafe. Top bin (holds 1.0): mean 0.975, 100% unsafe.
    assert ece == pytest.approx(0.5 * 0.45 + 0.5 * 0.025)
    assert [b["rows"] for b in table] == [2, 2]


def test_percentile_and_roc_curve():
    assert metrics.percentile([4, 1, 3, 2], 50) == 2.5
    assert metrics.percentile([], 50) is None
    assert metrics.roc_curve([0.9], [0.1]) == [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0)]


def test_resamples_are_stratified_and_repeatable():
    draws = bootstrap.resamples(["u1", "u2"], ["s1", "s2", "s3"], n=50)
    assert draws == bootstrap.resamples(["u1", "u2"], ["s1", "s2", "s3"], n=50)
    assert all(sum(i.startswith("u") for i in d) == 2 and len(d) == 5 for d in draws)
    assert bootstrap.interval(list(range(101))) == (2, 98)
    out = bootstrap.with_ci(lambda ids: len(set(ids)) / 5, ["u1", "u2", "s1", "s2", "s3"], draws)
    assert out["value"] == 1.0 and out["ci"][1] <= 1.0


def _write_run(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _records(scores, cost=0.0):
    out = []
    for n, (label, p, ambiguous) in enumerate(scores):
        out.append({
            "id": f"r{n}", "label": label, "category": "data_exfiltration" if label == "unsafe"
            else None, "ambiguous": ambiguous, "p_unsafe": p, "latency_ms": 10.0 + n,
            "cost_usd": cost, "decision": "block" if p > 0.7 else "allow" if p < 0.3
            else "escalate", "raw": {"model": "m-1"},
        })  # fmt: skip
    return out


def test_evaluate_end_to_end_on_saved_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "tuned_policy", lambda name: None)
    rows = (
        [("unsafe", 0.9, False), ("unsafe", 0.6, False), ("unsafe", 0.4, True)]
        + [("safe", 0.1 * (n % 5), n == 0) for n in range(11)]
        + [("safe", 0.95, False)]
    )  # the weak guard's one confident false alarm
    weak = _records(rows)
    strong = _records([(lab, 1.0 if lab == "unsafe" else 0.0, amb) for lab, _, amb in rows], 0.001)
    for split in ("dev", "test"):
        _write_run(tmp_path / f"{split}-classifier.jsonl", weak)
        _write_run(tmp_path / f"{split}-judge-cheap.jsonl", strong)
    _write_run(tmp_path / "test-judge-cheap-r2.jsonl", strong)

    result = evaluate.evaluate("test", runs_dir=tmp_path, out_dir=tmp_path / "eval")
    assert (tmp_path / "eval" / "test.json").is_file()
    assert result["subsets"] == {"clear": 13, "all": 15, "ambiguous": 2}
    cheap = result["backends"]["judge-cheap"]
    assert cheap["clear"]["auroc"]["value"] == 1.0
    assert cheap["clear"]["recall_at_1pct_fpr"]["value"] == 1.0
    assert (
        cheap["latency"]["runs"] == 2
        and cheap["stability_across_runs"]["decision_changed_share"] == 0
    )
    assert cheap["cost_per_1000_usd"] == 1.0 and cheap["models"] == ["m-1"]
    assert result["backends"]["classifier"]["stability_across_runs"] is None
    diff = result["difference_to_judge-cheap"]["classifier"]["auroc"]
    assert diff["value"] < 0 and diff["ci"][0] <= diff["value"] <= diff["ci"][1]
    sweep = [p for p in result["cascade_sweep"] if p["name"] == "classifier>judge-cheap"]
    assert len(sweep) == len(evaluate.MISS_BUDGETS)
    assert all(0 <= p["clear"]["reach_last_stage"] <= 1 for p in sweep)
    assert evaluate.headline(result)["judge-cheap"]["AUROC (clear)"].startswith("1.0 [")


def test_evaluate_refuses_runs_with_missing_verdicts(tmp_path):
    _write_run(tmp_path / "test-rules.jsonl", [{"id": "r0", "label": "safe", "error": "boom"}])
    with pytest.raises(ValueError, match="without a verdict"):
        evaluate.evaluate("test", backends=("rules",), runs_dir=tmp_path, out_dir=tmp_path)
