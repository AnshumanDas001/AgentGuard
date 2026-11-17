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

from agentguard.dataset.schema import Row
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
