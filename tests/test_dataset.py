import json
import re

import pytest
from pydantic import ValidationError

from agentguard.dataset import label as label_mod
from agentguard.dataset.check import check
from agentguard.dataset.importers import import_rows, rows_from_run_log
from agentguard.dataset.schema import LabelRecord, Row
from agentguard.dataset.split import allocate, assign, split_and_freeze, stratum
from agentguard.dataset.stats import compute
from agentguard.dataset.store import (
    DataPaths,
    DatasetError,
    append_label,
    labeled_rows,
    load_labels,
    rules_version,
    write_jsonl,
)
from agentguard.guard.schemas import RiskCategory

DESTRUCTIVE = RiskCategory.DESTRUCTIVE_FILE_OPS
EXFIL = RiskCategory.DATA_EXFILTRATION


@pytest.fixture
def paths(tmp_path):
    (tmp_path / "labeling_rules.md").write_text("# Labeling rules\n\n**Version 0.3, test.**\n")
    return DataPaths(root=tmp_path)


def row(row_id: str, **overrides) -> Row:
    fields = {
        "id": row_id,
        "source": "handwritten",
        "task": "Clean the build folder.",
        "history": [],
        "tool": "run_shell",
        "args": {"command": f"echo {row_id}"},
    }
    return Row(**{**fields, **overrides})


def record(row_id: str, label: str = "safe", version: str = "0.3", **fields) -> LabelRecord:
    return LabelRecord(
        id=row_id, label=label, rules_version=version, labeled_at="2026-10-22T00:00:00+00:00",
        **fields,
    )  # fmt: skip


def save_rows(paths: DataPaths, rows: list[Row], source: str = "handwritten") -> None:
    write_jsonl(paths.raw / f"{source}.jsonl", [r.model_dump(mode="json") for r in rows])


# --- schema ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"tool": "rm -rf"},
        {"tool": ""},
        {"args": {}},
        {"args": {"command": "ls", "extra": 1}},
        {"tool": "send_email", "args": {"to": "dana@example.com", "subject": "s", "body": "b"}},
        {"tool": "http_request", "args": {"method": "DELETE", "url": "u", "body": ""}},
        {"history": ["a", "b", "c", "d", "e", "f"]},
        {"id": "Has Spaces"},
        {"task": ""},
    ],
)
def test_row_rejects_malformed(overrides):
    with pytest.raises(ValidationError):
        row("r1", **overrides)


def test_row_proposal_and_fingerprint():
    a = row("a1", args={"command": "ls"})
    b = row("b1", source="generated", args={"command": "ls"}, meta={"hint": "safe"})
    assert a.proposal().model_dump() == {
        "task": "Clean the build folder.", "history": [], "tool": "run_shell",
        "args": {"command": "ls"},
    }  # fmt: skip
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != row("c1", args={"command": "ls -la"}).fingerprint()


@pytest.mark.parametrize(
    "fields",
    [
        {"label": "unsafe"},
        {"label": "unsafe", "category": DESTRUCTIVE, "imitates": DESTRUCTIVE},
        {"label": "unsafe", "category": DESTRUCTIVE, "secondary_category": DESTRUCTIVE},
        {"label": "safe", "category": DESTRUCTIVE},
        {"label": "excluded"},
        {"label": "excluded", "notes": "x", "imitates": DESTRUCTIVE},
        {"label": "safe", "ambiguous": True},
    ],
)
def test_label_record_rejects_inconsistent(fields):
    with pytest.raises(ValidationError):
        record("r1", **fields)


def test_label_record_valid_forms():
    assert record("r1", "unsafe", category=EXFIL, secondary_category=DESTRUCTIVE)
    assert record("r2", "safe", imitates=DESTRUCTIVE).hard_negative
    assert not record("r3", "safe").hard_negative
    assert record("r4", "excluded", notes="attack on another system (section 7)")
    with pytest.raises(ValidationError):
        record("r5", version="v1")


# --- store -----------------------------------------------------------------------------


def test_latest_label_wins(paths):
    save_rows(paths, [row("r1")])
    append_label(paths, record("r1", "safe"))
    append_label(paths, record("r1", "unsafe", category=DESTRUCTIVE))
    assert load_labels(paths)["r1"].label == "unsafe"
    merged = labeled_rows(paths)
    assert merged[0].category is DESTRUCTIVE and merged[0].task == "Clean the build folder."


def test_rules_version(paths):
    assert rules_version(paths) == "0.3"
    paths.rules.write_text("no header")
    with pytest.raises(DatasetError):
        rules_version(paths)


def test_real_rules_file_has_a_version():
    assert re.fullmatch(r"\d+\.\d+", rules_version(DataPaths()))


# --- check -----------------------------------------------------------------------------


def test_check_clean_dataset(paths):
    save_rows(paths, [row("r1"), row("r2")])
    append_label(paths, record("r1"))
    append_label(paths, record("r2", "unsafe", category=DESTRUCTIVE))
    report = check(paths)
    assert report.ok and report.warnings == []


def test_check_reports_every_problem(paths):
    good = row("r1").model_dump(mode="json")
    lines = [
        json.dumps(good),
        "{not json",
        json.dumps({**good, "tool": "not a tool", "id": "r2"}),
        json.dumps(good),  # duplicate id
        json.dumps({**good, "id": "r3"}),  # same action and context as r1
    ]
    paths.raw.mkdir(parents=True)
    (paths.raw / "handwritten.jsonl").write_text("\n".join(lines) + "\n")
    append_label(paths, record("ghost"))
    errors = "\n".join(check(paths).errors)
    assert "handwritten.jsonl:2: invalid JSON" in errors
    assert "handwritten.jsonl:3: tool" in errors
    assert "duplicate id 'r1'" in errors
    assert "r1, r3" in errors
    assert "unknown row 'ghost'" in errors


def test_check_warns_on_stale_and_unlabeled(paths):
    save_rows(paths, [row("r1"), row("r2")])
    append_label(paths, record("r1", version="0.2"))
    warnings = "\n".join(check(paths).warnings)
    assert "older rules version" in warnings and "1 of 2 rows not labeled" in warnings


# --- stats -----------------------------------------------------------------------------


def test_stats_counts(paths):
    save_rows(paths, [row(f"r{i}") for i in range(6)])
    append_label(paths, record("r0", "unsafe", category=EXFIL))
    append_label(paths, record("r1", "unsafe", category=DESTRUCTIVE))
    append_label(paths, record("r2", "safe", imitates=EXFIL))
    append_label(paths, record("r3", "safe", ambiguous=True, notes="tie-breaker"))
    append_label(paths, record("r4", "excluded", notes="third-party harm"))
    s = compute(paths)
    assert (s["rows"], s["labeled"], s["unlabeled"], s["excluded"]) == (6, 5, 1, 1)
    assert (s["unsafe"], s["safe"], s["hard_negatives"], s["ambiguous"]) == (2, 2, 1, 1)
    assert s["unsafe_by_category"][EXFIL] == 1 and s["hard_by_category"][EXFIL] == 1


# --- split -----------------------------------------------------------------------------


@pytest.mark.parametrize("n", range(0, 40))
def test_allocate_sums_and_shares(n):
    counts = allocate(n)
    assert sum(counts.values()) == n
    assert all(
        abs(counts[k] - n * s) < 1 for k, s in {"train": 0.5, "dev": 0.2, "test": 0.3}.items()
    )


def _labeled_dataset(paths: DataPaths) -> None:
    rows = [row(f"u{i:02d}") for i in range(40)] + [row(f"h{i:02d}") for i in range(20)]
    rows += [row(f"p{i:02d}") for i in range(40)] + [row("x00")]
    save_rows(paths, rows)
    for i in range(40):
        append_label(paths, record(f"u{i:02d}", "unsafe", category=DESTRUCTIVE))
        append_label(paths, record(f"p{i:02d}", "safe"))
    for i in range(20):
        append_label(paths, record(f"h{i:02d}", "safe", imitates=DESTRUCTIVE))
    append_label(paths, record("x00", "excluded", notes="port scan (section 7)"))


def test_split_is_stratified_disjoint_and_deterministic(paths):
    _labeled_dataset(paths)
    rows = [r for r in labeled_rows(paths) if r.label != "excluded"]
    splits = assign(rows, seed=0)
    for name, share in {"train": 0.5, "dev": 0.2, "test": 0.3}.items():
        by_stratum = {
            s: sum(stratum(r) == s for r in splits[name])
            for s in ("unsafe:destructive_file_ops", "hard:destructive_file_ops", "safe:plain")
        }
        assert by_stratum == {
            "unsafe:destructive_file_ops": round(40 * share),
            "hard:destructive_file_ops": round(20 * share),
            "safe:plain": round(40 * share),
        }
    ids = [r.id for members in splits.values() for r in members]
    assert len(ids) == len(set(ids)) == 100
    assert assign(rows, seed=0) == splits and assign(rows, seed=1) != splits  # fmt: skip


def test_split_freezes_once_and_detects_tampering(paths):
    _labeled_dataset(paths)
    info = split_and_freeze(paths)
    assert info["counts"] == {"train": 50, "dev": 20, "test": 30}
    assert "x00" not in paths.split_file("test").read_text()
    assert check(paths).ok
    with pytest.raises(DatasetError, match="frozen"):
        split_and_freeze(paths)
    test_file = paths.split_file("test")
    test_file.write_text(test_file.read_text() + "\n")
    assert any("frozen hash" in e for e in check(paths).errors)


def test_split_refuses_unlabeled_or_stale(paths):
    save_rows(paths, [row("r1"), row("r2")])
    append_label(paths, record("r1"))
    with pytest.raises(DatasetError, match="not labeled"):
        split_and_freeze(paths)
    append_label(paths, record("r2", version="0.2"))
    with pytest.raises(DatasetError, match="older rules version"):
        split_and_freeze(paths)
    assert not paths.frozen.exists()


# --- labeling tool ---------------------------------------------------------------------


def scripted(answers: list[str]):
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return answers.pop(0)

    return ask, prompts


def test_render_is_blind():
    r = row("hand-0042", source="secret-source", meta={"suggested_label": "unsafe"},
            history=["read_file({\"path\": \"README.md\"}) -> ran"],
            tool="write_file", args={"path": "a.py", "content": "x = 1\ny = 2"})  # fmt: skip
    text = label_mod.render(r, 3, 10)
    for hidden in ("hand-0042", "secret-source", "suggested_label"):
        assert hidden not in text
    assert "Row 3 of 10" in text and "    | y = 2" in text and "README.md" in text


def test_label_session_saves_each_decision(paths):
    save_rows(paths, [row("r1"), row("r2"), row("r3")])
    out: list[str] = []
    ask, _ = scripted([
        "u", "9", "2", "2", "", "", "",            # unsafe; 9 invalid; 2; secondary 2 rejected
        "s", "1", "y", "", "looks like a delete",  # safe hard negative, ambiguous, note required
        "k",                                       # skip
    ])  # fmt: skip
    saved = label_mod.session(paths, ask=ask, say=out.append)
    assert saved == 2
    labels = load_labels(paths)
    decided = sorted(labels.values(), key=lambda r: r.label)
    assert [r.label for r in decided] == ["safe", "unsafe"]
    safe, unsafe = decided
    assert unsafe.category is EXFIL and unsafe.secondary_category is None
    assert safe.imitates is DESTRUCTIVE and safe.ambiguous and safe.notes == "looks like a delete"
    assert all(r.rules_version == "0.3" for r in decided)
    assert any("must differ" in line for line in out)
    assert any("Please answer one of" in line for line in out)
    assert len(labels) == 2  # the skipped row stays unlabeled


def test_label_session_quit_and_resume(paths):
    save_rows(paths, [row("r1"), row("r2")])
    ask, _ = scripted(["x", "attack on another system", "q"])
    assert label_mod.session(paths, ask=ask, say=lambda _: None) == 1
    ask, _ = scripted(["s", "", "", ""])
    assert label_mod.session(paths, ask=ask, say=lambda _: None) == 1
    assert len(load_labels(paths)) == 2


# --- importers -------------------------------------------------------------------------


def test_import_run_log(paths, tmp_path):
    log = tmp_path / "run.jsonl"
    call = {
        "event": "tool_call",
        "run_id": "aaa",
        "agent_model": "m",
        "executed": True,
        "decision": "allow",
        "is_error": False,
    }
    events = [
        {"event": "run_start", "run_id": "aaa"},
        {**call, "step": 1, "output": "README.md\nsrc",
         "action": {"task": "t", "history": [], "tool": "run_shell", "args": {"command": "ls"}}},
        {**call, "step": 2, "output": "# invoice-tool",
         "action": {"task": "t", "history": ["old format"], "tool": "read_file",
                    "args": {"path": "README.md"}}},
        {"event": "run_end", "run_id": "aaa"},
    ]  # fmt: skip
    log.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    rows = rows_from_run_log(log, "phase1-run")
    assert [r.id for r in rows] == ["phase1-run-aaa-01", "phase1-run-aaa-02"]
    assert rows[1].history == ['run_shell({"command": "ls"}) -> ran\nREADME.md\nsrc']
    assert rows[1].meta["step"] == 2
    assert import_rows(paths, rows) == (2, 0)
    assert import_rows(paths, rows) == (0, 2)
    assert check(paths).ok


def test_import_rows_skips_identical_actions(paths):
    first = row("run-a-01", source="agent-run", args={"command": "ls"})
    same_action = row("run-b-01", source="agent-run", args={"command": "ls"})
    different = row("run-b-02", source="agent-run", args={"command": "pwd"})
    assert import_rows(paths, [first]) == (1, 0)
    assert import_rows(paths, [same_action, different]) == (1, 1)
    assert check(paths).ok


def test_benchmark_tools_are_accepted_but_ours_stay_strict():
    other = row("b1", tool="GmailReadEmail", args={"email_id": 7, "folder": ["inbox"]})
    assert other.tool == "GmailReadEmail" and other.proposal().args["email_id"] == 7
    with pytest.raises(ValidationError):
        row("b2", tool="run_shell", args={"cmd": "ls"})


def test_split_keeps_sessions_together(paths):
    rows = [row(f"s{g}-{i}", meta={"run_id": f"run{g}"}) for g in range(20) for i in range(3)]
    save_rows(paths, rows)
    for r in rows:
        append_label(paths, record(r.id, "safe"))
    splits = assign(labeled_rows(paths), seed=0)
    where = {r.meta["run_id"]: name for name, members in splits.items() for r in members}
    for name, members in splits.items():
        assert all(where[r.meta["run_id"]] == name for r in members)
    assert {n: len(m) // 3 for n, m in splits.items()} == {"train": 10, "dev": 4, "test": 6}


def test_check_flags_a_session_split_across_sets(paths):
    a = row("a1", meta={"run_id": "r1"}).model_dump(mode="json")
    b = row("a2", meta={"run_id": "r1"}).model_dump(mode="json")
    label = {"label": "safe", "rules_version": "0.3", "labeled_at": "2026-11-17T00:00:00+00:00"}
    write_jsonl(paths.split_file("train"), [{**a, **label}])
    write_jsonl(paths.split_file("test"), [{**b, **label}])
    assert any("leaks between train and test" in e for e in check(paths).errors)
