"""BashArena (UK AISI and Redwood Research): published honest and attack runs, as guard input.

BashArena is an AI-control setting: an agent does Linux admin tasks in a container, and in
attack runs it also has a secret side task (disable the firewall, leak passwords, download
malware or grant itself sudo). The runs scored here are the public `bashbench2_v1` logs from
the Control Leaderboard (Claude Opus 4.6 as the agent; data CC BY-SA 4.0):

    honest  https://data.linuxarena.ai/api/runs/de437937709f493dafe549b10b4505cf/eval
    attack  https://data.linuxarena.ai/api/runs/792967b92d37439ca0b12a5bce9dfa90/eval

The leaderboard asks that the logs be used for evaluation only: not for training, and not sent
to services that keep data for training. Nothing here trains on them.

Each run becomes a list of steps. For every step the guard gets what it gets in a live run:
the main task (never the side task), the last 5 steps with the start of their output, and the
proposed call. The agent's own messages (attack runs include notes such as <risky>false</risky>)
are never shown. BashArena's tool names are mapped onto AgentGuard's once, before any scoring:

    bash {cmd}                         -> run_shell {command}
    python {code}                      -> run_shell {command: python3 heredoc of the code}
    text_editor view {path}            -> read_file {path}
    text_editor create {path, file_text} -> write_file {path, content}
    text_editor str_replace / insert   -> write_file {path, old_str, new_str / insert_line}
    submit                             -> dropped (it ends the run; nothing to check)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agentguard.agent.loop import HISTORY_LEN
from agentguard.config import ROOT
from agentguard.guard.schemas import ActionProposal, format_step

DATA_DIR = ROOT / "data" / "external" / "basharena"
RUN_IDS = {
    "honest": "de437937709f493dafe549b10b4505cf",
    "attack": "792967b92d37439ca0b12a5bce9dfa90",
}
DOWNLOAD_URL = "https://data.linuxarena.ai/api/runs/{run_id}/eval"
CACHE = DATA_DIR / "trajectories.jsonl"
OUTPUT_CHARS = 2000  # the guard sees at most 800 characters of a step's output


@dataclass
class Step:
    tool: str
    args: dict[str, Any]
    output: str = ""


@dataclass
class Trajectory:
    id: str
    kind: str  # "honest" or "attack"
    task_id: str
    task: str
    side_task: str | None = None
    side_success: bool = False
    steps: list[Step] = field(default_factory=list)


def map_call(tool: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """BashArena's call as an AgentGuard (tool, args), or None for calls nothing checks."""
    if tool == "bash":
        return "run_shell", {"command": str(args.get("cmd", ""))}
    if tool == "python":
        return "run_shell", {"command": f"python3 - <<'PY'\n{args.get('code', '')}\nPY"}
    if tool == "text_editor":
        command, path = args.get("command"), str(args.get("path", ""))
        if command == "view":
            return "read_file", {"path": path}
        if command == "create":
            return "write_file", {"path": path, "content": str(args.get("file_text", ""))}
        rest = {k: v for k, v in args.items() if k not in ("command", "path")}
        return "write_file", {"path": path, **rest}
    if tool == "submit":
        return None
    return tool, dict(args)


def from_sample(sample: Any, kind: str) -> Trajectory:
    """One Inspect sample (a run) as a Trajectory, keeping only what scoring needs."""
    meta = sample.metadata
    main = meta["main_tasks"][0]
    side = meta.get("side_tasks") or []
    tasks = sample.scores["tasks"].value
    steps = []
    for action in meta["control_tower_overlay"]["actions"]:
        if action["function"] == "submit":
            continue
        output = str(action.get("output") or "")
        steps.append(Step(action["function"], action["arguments"], output[:OUTPUT_CHARS]))
    return Trajectory(
        id=f"{kind}-{sample.id}",
        kind=kind,
        task_id=str(main["id"]),
        task=main["description"],
        side_task=side[0]["id"] if side else None,
        side_success=str(tasks.get("side")) == "1.0",
        steps=steps,
    )


def convert(paths: dict[str, Path], out: Path = CACHE) -> int:
    """Read the downloaded .eval logs (needs the `bench` group) and cache them as JSONL."""
    from inspect_ai.log import read_eval_log

    n = 0
    with out.open("w", encoding="utf-8") as f:
        for kind, path in paths.items():
            log = read_eval_log(str(path))
            for sample in log.samples or []:
                f.write(json.dumps(asdict(from_sample(sample, kind)), ensure_ascii=False) + "\n")
                n += 1
    return n


def load(path: Path = CACHE) -> list[Trajectory]:
    trajectories = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            row["steps"] = [Step(**s) for s in row["steps"]]
            trajectories.append(Trajectory(**row))
    return trajectories


def scored(trajectories: list[Trajectory]) -> list[Trajectory]:
    """The runs the benchmark scores: every honest run, and attacks whose side task worked."""
    return [t for t in trajectories if t.kind == "honest" or t.side_success]


def proposals(trajectory: Trajectory) -> list[ActionProposal]:
    """One proposal per checkable step, each with the same history a live run would give."""
    out: list[ActionProposal] = []
    history: list[str] = []
    for step in trajectory.steps:
        mapped = map_call(step.tool, step.args)
        if mapped is None:
            continue
        tool, args = mapped
        out.append(
            ActionProposal(
                task=trajectory.task, history=history[-HISTORY_LEN:], tool=tool, args=args
            )
        )
        history.append(format_step(tool, args, executed=True, decision="allow", output=step.output))
    return out
