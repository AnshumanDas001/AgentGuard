"""Convert public agent-safety benchmarks into dataset rows (Phase 2, step 4).

InjecAgent (Zhan et al., 2024; MIT license), data-stealing cases, base setting. Each case
becomes one row:

    task       the user's instruction
    history    1. the user's tool call; its response hides the attacker's instruction
               2. the attacker's data-gathering call, with InjecAgent's simulated output
    action     send_email of that output to the attacker's address

The injected text is always visible in history, as the labeling rules require. The
direct-harm cases are not converted: their final actions (bank transfers, door locks)
have no equivalent among the agent's five tools.
"""

from __future__ import annotations

import ast
import json
import re
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from agentguard.dataset.schema import MAX_HISTORY, TOOL_INPUTS, Row
from agentguard.guard.schemas import format_step

INJECAGENT_REPO = "uiuc-kang-lab/InjecAgent"
INJECAGENT_COMMIT = "f19c9f2c79a41046eb13c03c51a24c567a8ffa07"  # main, 2024-07-02
INJECAGENT_FILES = ("test_cases_ds_base.json", "attacker_simulated_responses.json")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
BODY_CHARS = 1_500
# InjecAgent reuses one or two attacker addresses in every case, which would let a guard
# memorise the address instead of spotting the injection. Each case gets one of these
# instead, applied to the injected text and the email alike (original kept in meta).
ADDRESS_POOL = (
    "amy.watson.home@gmail.com",
    "j.morales.backup@outlook.com",
    "records@invoice-archive.com",
    "dana.k.personal@proton.me",
    "itsupport.desk@helpdesk-mail.com",
    "sam.patel88@yahoo.com",
    "billing-sync@accounts-portal.net",
    "lee.morgan.notes@icloud.com",
    "ops@data-relay.io",
    "r.chen.files@gmail.com",
    "export@crm-backup.co",
    "taylor.b.archive@hotmail.com",
    "noreply-sync@cloudsave-app.com",
    "m.ivanova@fastmail.com",
    "audit.copy@finrecords.org",
    "k.osei.work@gmail.com",
    "share@teamdrive-mail.com",
    "p.nguyen.alt@outlook.com",
    "inbox@quicknotes-sync.com",
    "alex.r.forward@gmail.com",
)
SUBJECT_POOL = (
    "Requested information", "As discussed", "Details you asked for", "Quick follow-up",
    "Info", "Copy for your records", "Here you go", "Update", "Fwd: details", "Re: your request",
    "Account details", "Notes", "(no subject)", "Summary", "Following up",
)  # fmt: skip


def fetch_injecagent(dest: Path) -> list[Path]:
    """Download the pinned InjecAgent files into `dest` (skips files already there)."""
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in INJECAGENT_FILES:
        path = dest / name
        if not path.is_file():
            url = f"https://raw.githubusercontent.com/{INJECAGENT_REPO}/{INJECAGENT_COMMIT}/data/{name}"
            response = httpx.get(url, timeout=60, follow_redirects=True)
            response.raise_for_status()
            path.write_bytes(response.content)
        paths.append(path)
    return paths


def _parse_args(text: str) -> dict[str, Any] | None:
    """InjecAgent stores arguments as JSON or as Python dict reprs; return a dict or None."""
    text = text.strip()
    for parse in (json.loads, ast.literal_eval):
        try:
            with warnings.catch_warnings():  # stray escapes like "\_" in the source data
                warnings.simplefilter("ignore", SyntaxWarning)
                value = parse(text)
        except (ValueError, SyntaxError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def simulated_outputs(responses: dict[str, str]) -> dict[str, tuple[dict[str, Any], str]]:
    """For each attacker tool, the simplest well-formed recorded call and its output.

    Keys look like "(ToolName,{...args...})". Picking the shortest parseable argument dict
    is deterministic and avoids the malformed or placeholder calls also recorded there.
    """
    best: dict[str, tuple[int, dict[str, Any], str]] = {}
    for key, output in responses.items():
        match = re.fullmatch(r"\((\w+),(.*)\)", key, flags=re.DOTALL)
        if not match:
            continue
        tool, raw_args = match.groups()
        args = _parse_args(raw_args)
        if args is None or any(not isinstance(v, str | int | float) for v in args.values()):
            continue
        size = len(json.dumps(args))
        if tool not in best or size < best[tool][0]:
            best[tool] = (size, args, output)
    return {tool: (args, output) for tool, (_, args, output) in best.items()}


def select_cases(cases: list[dict], per_user_tool: int) -> list[int]:
    """Indices of a spread-out sample: `per_user_tool` cases for each user tool, rotating
    through the attacker instructions so all of them are used."""
    instructions = sorted({c["Attacker Instruction"] for c in cases})
    rank = {text: i for i, text in enumerate(instructions)}
    by_tool: dict[str, list[int]] = defaultdict(list)
    for index, case in enumerate(cases):
        by_tool[case["User Tool"]].append(index)
    chosen = []
    for t, tool in enumerate(sorted(by_tool)):
        indices = sorted(by_tool[tool], key=lambda i: rank[cases[i]["Attacker Instruction"]])
        start = (t * per_user_tool) % len(indices)
        for j in range(min(per_user_tool, len(indices))):
            chosen.append(indices[(start + j) % len(indices)])
    return sorted(chosen)


def rows_from_injecagent(data_dir: Path, per_user_tool: int = 5) -> tuple[list[Row], list[str]]:
    """Returns (rows, notes about skipped cases)."""
    cases = json.loads((data_dir / "test_cases_ds_base.json").read_text())
    outputs = simulated_outputs(
        json.loads((data_dir / "attacker_simulated_responses.json").read_text())
    )
    rows, skipped = [], []
    for index in select_cases(cases, per_user_tool):
        case = cases[index]
        attacker_tool = case["Attacker Tools"][0]
        user_args = _parse_args(case["Tool Parameters"])
        address = EMAIL.search(case["Attacker Instruction"])
        if attacker_tool not in outputs or user_args is None or address is None:
            skipped.append(f"case {index}: missing simulated output, arguments or address")
            continue
        attacker_args, stolen = outputs[attacker_tool]
        original = address.group(0)
        replacement = ADDRESS_POOL[index % len(ADDRESS_POOL)]
        instruction = case["Attacker Instruction"].replace(original, replacement)
        response = str(case["Tool Response"]).replace(original, replacement)
        injected = format_step(
            case["User Tool"], user_args, executed=True, decision="allow", output=response
        )
        if instruction not in injected:
            skipped.append(f"case {index}: injected text falls outside the history window")
            continue
        gathered = format_step(
            attacker_tool, attacker_args, executed=True, decision="allow", output=stolen
        )
        body = stolen if len(stolen) <= BODY_CHARS else stolen[:BODY_CHARS] + "\n..."
        rows.append(
            Row(
                id=f"injecagent-ds-{index:03d}",
                source="injecagent",
                task=case["User Instruction"],
                history=[injected, gathered],
                tool="send_email",
                args={
                    "to": [replacement],
                    "subject": SUBJECT_POOL[index % len(SUBJECT_POOL)],
                    "body": body,
                },
                meta={
                    "benchmark": "InjecAgent",
                    "license": "MIT",
                    "repo": INJECAGENT_REPO,
                    "commit": INJECAGENT_COMMIT,
                    "file": "test_cases_ds_base.json",
                    "index": index,
                    "attack_type": case.get("Attack Type"),
                    "original_attacker_address": original,
                    "suggested_label": "unsafe",
                    "suggested_category": "injection_driven",
                    "suggested_secondary": "data_exfiltration",
                },
            )
        )
    return rows, skipped


# --- ASSEBench ---------------------------------------------------------------------------
#
# ASSEBench (AgentAuditor, NeurIPS 2025; Apache-2.0): human-annotated agent interaction
# records. Each in-scope record becomes up to two rows: its last tool call and the one
# before it, each with the user's request as the task and the earlier calls (with their
# outputs) as history. Calls matching the agent's five tools are renamed to them;
# other tools keep their recorded names and arguments. ASSEBench's own labels, ambiguity
# flag and risk description are kept in `meta` as a hidden cross-check, never shown while
# labeling. Records whose opening message matches the R-Judge file bundled in the same repo
# are skipped: R-Judge has no license.

ASSEBENCH_REPO = "Astarojth/AgentAuditor-ASSEBench"
ASSEBENCH_COMMIT = "fa5f99797073fd9a8d012268bc2b7dc27d05f4b1"  # 2026-05-29
ASSEBENCH_FILES = {
    "AgentJudge-safety.json": "ASSEBench/dataset/AgentJudge-safety.json",
    "AgentJudge-security.json": "ASSEBench/dataset/AgentJudge-security.json",
    "AgentJudge-loose.json": "ASSEBench/dataset/AgentJudge-loose.json",
    "rjudge.json": "AgentAuditor/data/rjudge.json",
}
# Risk types whose harms fall in the seven categories. The rest (ethics, harmful content,
# fraud and health risks) are out of scope, as labeling rules section 7 says.
ASSEBENCH_IN_SCOPE = {
    "safety": {
        "Unauthorized Access & Control",
        "Privacy Violations & Data Breach",
        "Data Loss & Integrity Risk",
        "Cybersecurity Vulnerabilities & Malicious Attacks",
        "Operational, Systemic & Environmental Risks",
    },
    "security": {
        "Prompt Injection",
        "Unauthorized Access & Control",
        "Data Exfiltration & Leakage",
        "Data Tampering & Destruction",
        "Fraud & Credential Abuse",
    },
}
CALL = re.compile(r"^([A-Za-z_][\w.]*)\s*:?\s*([\{\[].*)$", re.DOTALL)
END_ACTIONS = {"Complete", "Final"}
EMAIL_KEYS = {
    "to",
    "recipient",
    "receiver",
    "email",
    "subject",
    "title",
    "body",
    "content",
    "message",
}


def fetch_assebench(dest: Path) -> Path:
    """Download the pinned ASSEBench files into `dest` (skips files already there)."""
    dest.mkdir(parents=True, exist_ok=True)
    for name, remote in ASSEBENCH_FILES.items():
        path = dest / name
        if not path.is_file():
            url = f"https://raw.githubusercontent.com/{ASSEBENCH_REPO}/{ASSEBENCH_COMMIT}/{remote}"
            response = httpx.get(url, timeout=120, follow_redirects=True)
            response.raise_for_status()
            path.write_bytes(response.content)
    return dest


def _turns(record: dict) -> list[dict]:
    turns: list[dict] = []
    for episode in record.get("contents") or []:
        turns.extend(episode if isinstance(episode, list) else [episode])
    return [t for t in turns if isinstance(t, dict)]


def _opening(record: dict) -> str:
    for turn in _turns(record):
        if turn.get("role") == "user":
            return str(turn.get("content") or "").strip()[:200]
    return ""


def parse_call(action: str) -> tuple[str, dict[str, Any]] | None:
    """'ToolName: {...}' or 'ToolName{...}' -> (tool, args); None for non-calls."""
    match = CALL.match((action or "").strip())
    if match is None or match.group(1) in END_ACTIONS:
        return None
    args = _parse_args(match.group(2))
    return match.group(1), args if args is not None else {"input": match.group(2).strip()}


def map_call(tool: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Rename calls that are one of the agent's five tools; leave everything else as is."""
    path = args.get("file_name_or_path") or args.get("path") or args.get("file_path")
    if tool in ("TerminalExecute", "bash") and isinstance(args.get("command"), str):
        return "run_shell", {"command": args["command"]}
    if tool == "read_file" and isinstance(path, str) and len(args) == 1:
        return "read_file", {"path": path}
    content = args.get("content")
    if (
        tool == "write_file"
        and isinstance(path, str)
        and isinstance(content, str)
        and len(args) == 2
    ):
        return "write_file", {"path": path, "content": content}
    if tool == "read_website" and isinstance(args.get("url"), str) and len(args) == 1:
        return "http_request", {"method": "GET", "url": args["url"], "body": ""}
    if tool in ("send_email", "GmailSendEmail") and set(args) <= EMAIL_KEYS:
        to = args.get("to") or args.get("recipient") or args.get("receiver") or args.get("email")
        body = args.get("body") or args.get("content") or args.get("message") or ""
        if isinstance(to, str):
            to = [a.strip() for a in re.split(r"[,;]", to) if a.strip()]
        recipients_ok = isinstance(to, list) and to and all(isinstance(a, str) for a in to)
        if recipients_ok and isinstance(body, str):
            return "send_email", {
                "to": to,
                "subject": str(args.get("subject") or args.get("title") or ""),
                "body": body,
            }
    if tool in TOOL_INPUTS:
        # Same name as one of the agent's tools but different arguments (an extra sender,
        # an attachment): keep every detail, under a name that can't pass for ours.
        return f"{tool}_external", args
    return tool, args


def rows_from_record(
    record: dict, subset: str, loose_label: Any = None, steps_per_record: int = 2
) -> list[Row]:
    """Rows for the record's last `steps_per_record` tool calls, each in the context of
    everything before it. The last call keeps the plain record id; earlier ones get -stepN."""
    steps: list[list[Any]] = []  # [tool, args, output]
    users: list[tuple[int, str]] = []  # (calls made before this message, text)
    for turn in _turns(record):
        role = turn.get("role")
        if role == "user" and str(turn.get("content") or "").strip():
            users.append((len(steps), str(turn["content"]).strip()))
        elif role == "agent":
            call = parse_call(str(turn.get("action") or ""))
            if call is not None:
                steps.append([*map_call(*call), ""])
        elif role == "environment" and steps and not steps[-1][2]:
            steps[-1][2] = str(turn.get("content") or "")
    rows = []
    base_id = f"assebench-{subset}-{str(record.get('id')).lower()}"
    for position in range(len(steps) - 1, max(len(steps) - 1 - steps_per_record, -1), -1):
        messages = [text for before, text in users if before <= position]
        if not messages:
            continue
        task = messages[0] + "".join(f"\n\nLater the user said: {m}" for m in messages[1:])
        history = [
            format_step(tool, args, executed=True, decision="allow", output=output)
            for tool, args, output in steps[:position]
        ][-MAX_HISTORY:]
        tool, args, _ = steps[position]
        is_last = position == len(steps) - 1
        meta = {
            "benchmark": "ASSEBench",
            "license": "Apache-2.0",
            "repo": ASSEBENCH_REPO,
            "commit": ASSEBENCH_COMMIT,
            "subset": subset,
            "record_id": record.get("id"),
            "risk_type": record.get("risk_type"),
            "application_scenario": record.get("application_scenario"),
            "failure_mode": record.get("failure_mode"),
            "suggested_label": "unsafe" if str(record.get("label")) == "1" else "safe",
            "ambiguous": str(record.get("ambiguous")) == "1",
            "risk_description": str(record.get("risk_description") or "")[:600],
        }
        if loose_label is not None:
            meta["suggested_label_lenient"] = "unsafe" if str(loose_label) == "1" else "safe"
        meta["step"] = position + 1
        meta["steps_in_record"] = len(steps)
        # ASSEBench labels whole records; for an earlier step it is only a weak hint.
        meta["is_last_call"] = is_last
        rows.append(
            Row(
                id=base_id if is_last else f"{base_id}-step{position + 1}",
                source="assebench",
                task=task,
                history=history,
                tool=tool,
                args=args,
                meta=meta,
            )
        )
    return rows


def rows_from_assebench(
    data_dir: Path, steps_per_record: int = 2
) -> tuple[list[Row], dict[str, int]]:
    """Rows from the in-scope records of both subsets, plus counts of what was skipped."""
    load = lambda name: json.loads((data_dir / name).read_text())  # noqa: E731
    rjudge = {_opening(r) for r in load("rjudge.json")} - {""}
    loose = {r.get("id"): r.get("label") for r in load("AgentJudge-loose.json")}
    rows: list[Row] = []
    skipped = {"out of scope": 0, "copied from R-Judge": 0, "no tool call": 0}
    for subset in ("safety", "security"):
        for record in load(f"AgentJudge-{subset}.json"):
            if record.get("risk_type") not in ASSEBENCH_IN_SCOPE[subset]:
                skipped["out of scope"] += 1
            elif subset == "safety" and _opening(record) in rjudge:
                skipped["copied from R-Judge"] += 1
            elif found := rows_from_record(
                record,
                subset,
                loose.get(record.get("id")) if subset == "safety" else None,
                steps_per_record,
            ):
                rows.extend(found)
            else:
                skipped["no tool call"] += 1
    return rows, skipped
