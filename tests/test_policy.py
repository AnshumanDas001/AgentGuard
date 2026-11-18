import json

import pytest

from agentguard.eval.tune import choose, cuts, pick_thresholds, replay, tune
from agentguard.guard.policy import (
    Cascade,
    CascadePolicy,
    ThresholdPolicy,
    default_cascade,
    policy_for,
    tuned_policy,
)
from agentguard.guard.schemas import ActionProposal, Decision, Verdict

ACTION = ActionProposal(task="t", tool="run_shell", args={"command": "ls"})


class Fixed:
    def __init__(self, name: str, p: float, cost: float = 0.0) -> None:
        self.name, self.p, self.cost, self.calls = name, p, cost, 0

    async def assess(self, action: ActionProposal) -> Verdict:
        self.calls += 1
        return Verdict(p_unsafe=self.p, latency_ms=1.0, cost_usd=self.cost)


class Broken:
    name = "broken"

    async def assess(self, action: ActionProposal) -> Verdict:
        raise RuntimeError("down")


def rec(row_id: str, label: str, p: float, cost: float = 0.0) -> dict:
    return {"id": row_id, "label": label, "p_unsafe": p, "cost_usd": cost, "latency_ms": 1.0}


# --- the live cascade -------------------------------------------------------------------------


async def test_confident_first_stage_decides_alone():
    cheap, strong = Fixed("cheap", 0.01, 0.001), Fixed("strong", 0.9, 0.01)
    cascade = Cascade([(cheap, ThresholdPolicy(0.1, 0.9)), (strong, ThresholdPolicy(0.3, 0.7))])
    verdict = await cascade.assess(ACTION)
    assert cascade.policy.decide(verdict) is Decision.ALLOW
    assert strong.calls == 0 and verdict.raw["decided_by"] == "cheap"
    assert verdict.cost_usd == pytest.approx(0.001)


async def test_unsure_first_stage_hands_over_and_costs_add_up():
    cheap, strong = Fixed("cheap", 0.5, 0.001), Fixed("strong", 0.9, 0.01)
    cascade = Cascade([(cheap, ThresholdPolicy(0.1, 0.9)), (strong, ThresholdPolicy(0.3, 0.7))])
    verdict = await cascade.assess(ACTION)
    assert cascade.policy.decide(verdict) is Decision.BLOCK
    assert verdict.raw["decided_by"] == "strong" and verdict.p_unsafe == 0.9
    assert [s["decision"] for s in verdict.raw["stages"]] == ["escalate", "block"]
    assert verdict.cost_usd == pytest.approx(0.011)


async def test_cascade_decision_overrides_the_final_p():
    # The first stage blocks at 0.6 under its own thresholds, which the last stage would escalate.
    cascade = Cascade(
        [(Fixed("a", 0.6), ThresholdPolicy(0.1, 0.5)), (Fixed("b", 0), ThresholdPolicy())]
    )
    verdict = await cascade.assess(ACTION)
    assert cascade.policy.decide(verdict) is Decision.BLOCK


async def test_broken_early_stage_counts_as_unsure_but_broken_last_stage_raises():
    cascade = Cascade([(Broken(), ThresholdPolicy()), (Fixed("strong", 0.01), ThresholdPolicy())])
    verdict = await cascade.assess(ACTION)
    assert cascade.policy.decide(verdict) is Decision.ALLOW
    assert "error" in verdict.raw["stages"][0]
    with pytest.raises(RuntimeError):
        await Cascade([(Fixed("a", 0.5), ThresholdPolicy()), (Broken(), ThresholdPolicy())]).assess(
            ACTION
        )


def test_cascade_policy_falls_back_to_last_stage_for_fail_closed_verdicts():
    policy = CascadePolicy(ThresholdPolicy(0.3, 0.7))
    assert policy.decide(Verdict(p_unsafe=1.0, latency_ms=0, raw={"fail_closed": True})) is (
        Decision.BLOCK
    )


def test_policy_for_prefers_a_cascades_own_policy(tmp_path, monkeypatch):
    cascade = Cascade([(Fixed("a", 0.1), ThresholdPolicy())])
    assert policy_for(cascade) is cascade.policy
    monkeypatch.setattr("agentguard.guard.policy.TUNING_DIR", tmp_path)
    assert policy_for(Fixed("a", 0.1)) == ThresholdPolicy()
    (tmp_path / "thresholds.json").write_text(
        json.dumps({"backends": {"a": {"allow_below": 0.1, "block_above": 0.2}}})
    )
    assert tuned_policy("a", tmp_path / "thresholds.json") == ThresholdPolicy(0.1, 0.2)


# --- tuning -----------------------------------------------------------------------------------


def test_cuts_sit_between_scores():
    assert cuts([0.2, 0.1, 0.2, 0.5]) == [0.0, pytest.approx(0.15), pytest.approx(0.35), 1.0]


def test_pick_thresholds_respects_both_limits():
    safe = [rec(f"s{i}", "safe", 0.05) for i in range(98)]
    safe += [rec("s98", "safe", 0.6), rec("s99", "safe", 0.9)]
    unsafe = [rec(f"u{i}", "unsafe", 0.95) for i in range(19)] + [rec("u19", "unsafe", 0.02)]
    policy = pick_thresholds(safe + unsafe, max_fpr=0.01, max_miss=0.05)
    # Blocks only the 0.9 and 0.95 rows: one safe row in 100 is 1%.
    assert 0.6 < policy.block_above < 0.9
    # Allows the 0.02 unsafe row (1 in 20 = 5%); no unsafe row sits between 0.02 and 0.95,
    # so it allows everything up to the block cut and escalates nothing.
    assert policy.allow_below == policy.block_above
    tight = pick_thresholds(safe + unsafe, max_fpr=0.01, max_miss=0.0)
    assert tight.allow_below < 0.02


def test_replay_matches_the_cascade_rules():
    cheap = [rec("x", "safe", 0.01, 0.001), rec("y", "unsafe", 0.5, 0.001)]
    strong = [rec("x", "safe", 0.9, 0.01), rec("y", "unsafe", 0.9, 0.01)]
    out = replay([(cheap, ThresholdPolicy(0.1, 0.9)), (strong, ThresholdPolicy(0.3, 0.7))])
    assert [(o["decision"], o["decided_at"]) for o in out] == [
        (Decision.ALLOW, 0),
        (Decision.BLOCK, 1),
    ]
    assert out[1]["cost_usd"] == pytest.approx(0.011)


def candidate(name: str, stages: int, cost: float, missed: int = 0) -> dict:
    return {
        "name": name,
        "stages": [{}] * stages,
        "dev": {
            "unsafe_allowed_n": missed,
            "safe_blocked_n": 0,
            "escalated_n": 0,
            "cost_per_1000_usd": cost,
            "mean_latency_ms": 1.0,
        },
    }


def test_choose_prefers_fewer_stages_when_savings_are_tiny():
    picked = choose(
        [
            candidate("judge-strong", 1, 10.0),
            candidate("cheap>strong", 2, 5.0),
            candidate("rules>cheap>strong", 3, 4.9),
            candidate("leaky", 2, 1.0, missed=3),
        ]
    )
    assert picked["name"] == "cheap>strong"


def write_run(runs_dir, backend: str, records: list[dict]) -> None:
    rows = [
        {**r, "category": None, "imitates": None, "ambiguous": False, "source": "s"}
        for r in records
    ]
    (runs_dir / f"dev-{backend}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_tune_writes_thresholds_and_a_buildable_cascade(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    labels = ["safe"] * 8 + ["unsafe"] * 4
    cheap_p = [0.01] * 6 + [0.5, 0.5] + [0.99, 0.99, 0.5, 0.5]
    strong_p = [0.01] * 8 + [0.99] * 4
    write_run(
        runs,
        "judge-cheap",
        [
            rec(str(i), lab, p, 0.0001)
            for i, (lab, p) in enumerate(zip(labels, cheap_p, strict=True))
        ],
    )
    write_run(
        runs,
        "judge-strong",
        [
            rec(str(i), lab, p, 0.01)
            for i, (lab, p) in enumerate(zip(labels, strong_p, strict=True))
        ],
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    out = tmp_path / "tuning"
    result = tune(runs_dir=runs, out_dir=out)
    assert result["cascade"]["chosen"]["name"] == "judge-cheap>judge-strong"
    assert json.loads((out / "thresholds.json").read_text())["backends"].keys() == {
        "judge-cheap",
        "judge-strong",
    }
    built = default_cascade(out / "cascade.json")
    assert [b.name for b, _ in built.stages] == ["judge-cheap", "judge-strong"]
