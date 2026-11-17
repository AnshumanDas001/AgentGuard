import json

from conftest import FakeClient, message, tool_use

from agentguard.agent.loop import run_agent
from agentguard.agent.models import AnthropicModel
from agentguard.guard.backends import AllowAll
from agentguard.guard.interceptor import Interceptor
from agentguard.guard.schemas import ActionProposal, RiskCategory, Verdict


class BlockShell:
    name = "block_shell"

    async def assess(self, action: ActionProposal) -> Verdict:
        p = 0.99 if action.tool == "run_shell" else 0.0
        return Verdict(p_unsafe=p, category=RiskCategory.DESTRUCTIVE_FILE_OPS, latency_ms=0)


def claude(client):
    return AnthropicModel("claude-opus-5-5", client=client)


def log_records(logger):
    return [json.loads(line) for line in logger.path.read_text().splitlines()]


async def test_tool_call_then_finish(toolbox, logger, settings, sandbox):
    client = FakeClient(
        [
            message([tool_use("t1", "run_shell", {"command": "ls"})], "tool_use"),
            message([{"type": "text", "text": "Listed the files."}]),
        ]
    )
    run = await run_agent(
        "list files", model=claude(client), interceptor=Interceptor(AllowAll(), toolbox),
        logger=logger, settings=settings,
    )  # fmt: skip
    assert run.status == "completed" and run.final_text == "Listed the files."
    assert run.tool_calls == 1 and run.blocked == 0
    assert run.cost_usd > 0

    second = client.requests[1]["messages"]
    assert second[-1]["role"] == "user"
    assert second[-1]["content"][0]["tool_use_id"] == "t1"
    assert client.requests[0]["fallbacks"] == "default"

    records = log_records(logger)
    assert [r["event"] for r in records] == ["run_start", "tool_call", "run_end"]
    assert records[1]["action"]["args"] == {"command": "ls"}
    assert records[1]["decision"] == "allow" and records[1]["executed"] is True


async def test_blocked_call_returns_error_to_agent(toolbox, logger, settings, sandbox):
    client = FakeClient(
        [
            message([tool_use("t1", "run_shell", {"command": "rm -rf ~"})], "tool_use"),
            message([{"type": "text", "text": "I could not do that."}]),
        ]
    )
    run = await run_agent(
        "clean up", model=claude(client), interceptor=Interceptor(BlockShell(), toolbox),
        logger=logger, settings=settings,
    )  # fmt: skip
    assert run.blocked == 1 and sandbox.calls == []
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "Blocked by AgentGuard" in result["content"]


async def test_history_carries_previous_steps(toolbox, logger, settings):
    client = FakeClient(
        [
            message([tool_use("t1", "write_file", {"path": "s.sh", "content": "rm -rf /"})],
                    "tool_use"),
            message([tool_use("t2", "run_shell", {"command": "bash s.sh"})], "tool_use"),
            message([{"type": "text", "text": "done"}]),
        ]
    )  # fmt: skip
    await run_agent(
        "task", model=claude(client), interceptor=Interceptor(AllowAll(), toolbox),
        logger=logger, settings=settings,
    )  # fmt: skip
    calls = [r for r in log_records(logger) if r["event"] == "tool_call"]
    assert calls[0]["action"]["history"] == []
    assert calls[1]["action"]["history"][0].startswith('write_file({"path": "s.sh"')
    assert calls[1]["action"]["history"][0].endswith("-> ran\nWrote 8 chars to s.sh")


async def test_stops_at_max_steps(toolbox, logger, settings):
    looping = [message([tool_use(f"t{i}", "run_shell", {"command": "true"})], "tool_use")
               for i in range(settings.max_steps)]  # fmt: skip
    run = await run_agent(
        "loop forever", model=claude(FakeClient(looping)),
        interceptor=Interceptor(AllowAll(), toolbox),
        logger=logger, settings=settings,
    )  # fmt: skip
    assert run.status == "max_steps" and run.steps == settings.max_steps


async def test_truncated_tool_call_is_not_run(toolbox, logger, settings, sandbox):
    client = FakeClient([message([tool_use("t1", "run_shell", {"command": "ls"})], "max_tokens")])
    run = await run_agent(
        "task", model=claude(client), interceptor=Interceptor(AllowAll(), toolbox),
        logger=logger, settings=settings,
    )  # fmt: skip
    assert run.status == "max_tokens" and sandbox.calls == []


async def test_refusal_ends_run(toolbox, logger, settings):
    client = FakeClient([message([], "refusal")])
    run = await run_agent(
        "task", model=claude(client), interceptor=Interceptor(AllowAll(), toolbox),
        logger=logger, settings=settings,
    )  # fmt: skip
    assert run.status == "refused"
