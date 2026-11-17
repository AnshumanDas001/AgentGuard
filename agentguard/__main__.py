"""Command line entry point: `python -m agentguard {check,run,tasks}`."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

from agentguard.agent.loop import RunResult, run_agent
from agentguard.agent.models import AgentModel, build_model
from agentguard.agent.sandbox import DockerSandbox
from agentguard.agent.tasks import ORDINARY_TASKS
from agentguard.agent.tools import Toolbox
from agentguard.config import Settings, load_dotenv
from agentguard.guard.backends import AllowAll
from agentguard.guard.interceptor import EscalationHandler, Interceptor, Outcome, deny_escalations
from agentguard.guard.logger import JsonlLogger
from agentguard.guard.schemas import ActionProposal, Decision, Verdict


async def ask_human(action: ActionProposal, verdict: Verdict) -> bool:
    print(f"\n  ESCALATED (p_unsafe={verdict.p_unsafe:.2f}): {action.tool} {action.args}")
    answer = await asyncio.to_thread(input, "  Allow this action? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


async def allow_escalations(action: ActionProposal, verdict: Verdict) -> bool:
    return True


ESCALATION_HANDLERS: dict[str, EscalationHandler] = {
    "deny": deny_escalations,
    "ask": ask_human,
    "allow": allow_escalations,
}


def print_tool_call(action: ActionProposal, outcome: Outcome) -> None:
    args = json.dumps(action.args, ensure_ascii=False)
    if len(args) > 120:
        args = args[:120] + "..."
    mark = "ok " if outcome.executed else "BLK"
    if outcome.decision is Decision.ESCALATE and outcome.executed:
        mark = "esc"
    leak = "  !! CANARY LEAK" if outcome.result.canary_leak else ""
    print(f"  [{mark}] {action.tool} {args}{leak}")


def print_summary(run: RunResult) -> None:
    print(
        f"  -> {run.status}: {run.steps} steps, {run.tool_calls} tool calls, "
        f"{run.blocked} blocked, {run.canary_leaks} canary leaks, ${run.cost_usd:.4f}"
    )
    if run.final_text:
        print("  " + run.final_text.replace("\n", "\n  "))
    for error in run.errors:
        print(f"  error: {error}")


async def run_tasks(tasks: list[str], settings: Settings, escalate: str) -> list[RunResult]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logger = JsonlLogger(settings.log_dir / f"run-{stamp}.jsonl")
    model: AgentModel = build_model(settings)
    print(f"Agent: {model.name} via {settings.agent_provider} (effort {settings.agent_effort})")
    try:
        return await _run_all(tasks, settings, escalate, model, logger)
    finally:
        await model.aclose()


async def _run_all(
    tasks: list[str],
    settings: Settings,
    escalate: str,
    model: AgentModel,
    logger: JsonlLogger,
) -> list[RunResult]:
    results = []
    for i, task in enumerate(tasks, 1):
        print(f"\n[{i}/{len(tasks)}] {task}")
        # Fresh container per task, so one task's damage never leaks into the next.
        async with DockerSandbox(settings.sandbox_image) as sandbox:
            toolbox = Toolbox(sandbox, settings)
            interceptor = Interceptor(
                AllowAll(), toolbox, on_escalate=ESCALATION_HANDLERS[escalate]
            )
            try:
                run = await run_agent(
                    task,
                    model=model,
                    interceptor=interceptor,
                    logger=logger,
                    settings=settings,
                    on_tool_call=print_tool_call,
                )
            finally:
                await toolbox.aclose()
        print_summary(run)
        results.append(run)
    completed = sum(r.status == "completed" for r in results)
    print(f"\n{completed}/{len(results)} completed. Log: {logger.path}")
    return results


def check(settings: Settings) -> int:
    ok = True

    def report(passed: bool, label: str, hint: str = "") -> None:
        nonlocal ok
        ok &= passed
        print(f"  [{'ok' if passed else 'FAIL'}] {label}" + ("" if passed else f": {hint}"))

    docker = shutil.which("docker")
    report(docker is not None, "docker on PATH", "install Docker Desktop or `brew install colima`")
    if docker:
        image = subprocess.run(
            ["docker", "image", "inspect", settings.sandbox_image],
            capture_output=True,
        )
        report(image.returncode == 0, f"image {settings.sandbox_image}", "run `make sandbox`")
    key_var = {"openrouter": "OPENROUTER_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(
        settings.agent_provider
    )
    report(key_var is not None, f"provider {settings.agent_provider!r}", "openrouter or anthropic")
    if key_var:
        report(bool(os.environ.get(key_var)), f"{key_var} set", "add it to .env")
    print(f"  agent: {settings.agent_model} via {settings.agent_provider}")
    print(f"  effort: {settings.agent_effort}")
    print(f"  http allowlist: {', '.join(settings.http_allowlist) or '(none)'}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="agentguard")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="check Docker, sandbox image and API key")
    run_p = sub.add_parser("run", help="run the agent on one task")
    run_p.add_argument("task")
    tasks_p = sub.add_parser("tasks", help="run the ordinary task suite")
    tasks_p.add_argument("--limit", type=int, default=None)
    for p in (run_p, tasks_p):
        p.add_argument("--escalate", choices=sorted(ESCALATION_HANDLERS), default="deny")
    args = parser.parse_args()
    load_dotenv()
    settings = Settings.from_env()

    if args.command == "check":
        return check(settings)
    tasks = [args.task] if args.command == "run" else ORDINARY_TASKS[: args.limit]
    results = asyncio.run(run_tasks(tasks, settings, args.escalate))
    return 0 if all(r.status == "completed" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
