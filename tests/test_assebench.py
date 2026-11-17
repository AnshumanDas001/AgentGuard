import json

from agentguard.dataset.benchmarks import (
    map_call,
    parse_call,
    rows_from_assebench,
    rows_from_record,
)


def record(
    rid, risk="Privacy Violations & Data Breach", label=1, turns=None, opening="Tidy my inbox."
):
    turns = turns or [
        {"role": "user", "content": opening},
        {
            "role": "agent",
            "thought": "look first",
            "action": 'GmailReadEmail: {"email_id": "e1"}\n',
        },
        {"role": "environment", "content": "From: lee@example.com"},
        {
            "role": "agent",
            "thought": "now send",
            "action": "send_email{'to': 'x@example.com', 'subject': 'Hi', 'content': 'notes'}",
        },
        {"role": "environment", "content": "sent"},
        {"role": "agent", "thought": "done", "action": "Complete{}"},
    ]
    return {
        "id": rid,
        "contents": [turns],
        "label": label,
        "risk_type": risk,
        "ambiguous": 0,
        "application_scenario": "Email Management",
        "failure_mode": "x",
        "risk_description": "d",
    }


def test_parse_call_formats():
    assert parse_call('TerminalExecute: {"command": "ls"}\n') == (
        "TerminalExecute",
        {"command": "ls"},
    )
    assert parse_call("read_file{'file_name_or_path': 'a.py'}") == (
        "read_file",
        {"file_name_or_path": "a.py"},
    )
    assert parse_call("Complete{}") is None
    assert parse_call("I will now check the file.") is None
    assert parse_call("Search[broken") == ("Search", {"input": "[broken"})


def test_map_call_renames_only_exact_matches():
    assert map_call("TerminalExecute", {"command": "ls"}) == ("run_shell", {"command": "ls"})
    assert map_call("read_website", {"url": "https://a.example"})[0] == "http_request"
    assert map_call("send_email", {"to": "a@x.com; b@x.com", "content": "hi"}) == (
        "send_email",
        {"to": ["a@x.com", "b@x.com"], "subject": "", "body": "hi"},
    )
    # an attachment has no equivalent in our send_email, so the call keeps its own shape
    kept = {"to": "a@x.com", "content": "hi", "attachment": "/docs/report.pdf"}
    assert map_call("send_email", kept) == ("send_email_external", kept)
    spoof = {"receiver": "a@x.com", "sender": "ceo@x.com", "title": "Urgent", "content": "pay"}
    assert map_call("send_email", spoof) == ("send_email_external", spoof)
    assert (
        map_call("send_email", {"to": "a@x.com", "title": "Hi", "content": "c"})[1]["subject"]
        == "Hi"
    )
    assert map_call("GmailReadEmail", {"email_id": "e1"}) == ("GmailReadEmail", {"email_id": "e1"})


def test_row_uses_last_call_with_history_and_hidden_reference():
    last, earlier = rows_from_record(record("17"), "safety", loose_label=0)
    assert earlier.id == "assebench-safety-17-step1" and earlier.tool == "GmailReadEmail"
    assert earlier.history == [] and earlier.meta["is_last_call"] is False
    row = last
    assert row.id == "assebench-safety-17" and row.task == "Tidy my inbox."
    assert row.tool == "send_email" and row.args["to"] == ["x@example.com"]
    assert len(row.history) == 1 and row.history[0].startswith(
        'GmailReadEmail({"email_id": "e1"}) -> ran'
    )
    assert "From: lee@example.com" in row.history[0]
    assert row.meta["suggested_label"] == "unsafe" and row.meta["suggested_label_lenient"] == "safe"


def test_later_user_messages_join_the_task():
    turns = [
        {"role": "user", "content": "Check the logs."},
        {"role": "agent", "action": 'TerminalExecute: {"command": "ls logs"}'},
        {"role": "environment", "content": "app.log"},
        {"role": "user", "content": "Now clear them."},
        {"role": "agent", "action": 'TerminalExecute: {"command": "rm logs/app.log"}'},
    ]
    row = rows_from_record(record("9", turns=turns), "security")[0]
    assert row.task == "Check the logs.\n\nLater the user said: Now clear them."
    assert row.tool == "run_shell" and row.args == {"command": "rm logs/app.log"}


def test_rows_from_assebench_filters(tmp_path):
    safety = [
        record("1"),
        record("2", risk="Ethical, Compliance & Integrity Violations"),
        record("3", opening="A task copied from R-Judge."),
    ]
    no_calls = record(
        "4", turns=[{"role": "user", "content": "hi"}, {"role": "agent", "action": "Hello!"}]
    )
    files = {
        "AgentJudge-safety.json": safety,
        "AgentJudge-security.json": [no_calls],
        "AgentJudge-loose.json": safety,
        "rjudge.json": [
            {"contents": [[{"role": "user", "content": "A task copied from R-Judge."}]]}
        ],
    }
    for name, data in files.items():
        (tmp_path / name).write_text(json.dumps(data))
    no_calls["risk_type"] = "Prompt Injection"
    (tmp_path / "AgentJudge-security.json").write_text(json.dumps([no_calls]))
    rows, skipped = rows_from_assebench(tmp_path)
    assert [r.id for r in rows] == ["assebench-safety-1", "assebench-safety-1-step1"]
    assert skipped == {"out of scope": 1, "copied from R-Judge": 1, "no tool call": 1}
