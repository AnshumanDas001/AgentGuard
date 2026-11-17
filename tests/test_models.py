import json

import httpx
import pytest
from conftest import FakeClient, message, tool_use

from agentguard.agent.loop import run_agent
from agentguard.agent.models import (
    AnthropicModel,
    ModelError,
    OpenRouterModel,
    ToolResultMsg,
    build_model,
    parse_arguments,
)
from agentguard.agent.tools import TOOL_SCHEMAS
from agentguard.config import Settings, load_dotenv
from agentguard.guard.backends import AllowAll
from agentguard.guard.interceptor import Interceptor


def completion(message: dict, finish: str = "stop", cost: float = 0.0005) -> dict:
    return {
        "id": "gen-1",
        "model": "anthropic/claude-haiku-5.5",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": cost},
    }


def call(call_id: str, name: str, args: dict | str) -> dict:
    raw = args if isinstance(args, str) else json.dumps(args)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": raw}}


class Router:
    """Scripted OpenRouter: replies with queued (status, body) pairs, records request bodies."""

    def __init__(self, replies: list[tuple[int, dict]]) -> None:
        self.replies = list(replies)
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        self.bodies.append(json.loads(request.content))
        status, body = self.replies.pop(0)
        return httpx.Response(status, json=body)

    def model(self) -> OpenRouterModel:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self))
        return OpenRouterModel(
            "anthropic/claude-haiku-5.5", api_key="test-key", http=http, retry_delay_s=0
        )


async def test_openrouter_tool_call_round_trip():
    reasoning = [{"type": "reasoning.encrypted", "data": "opaque"}]
    router = Router(
        [
            (200, completion({"role": "assistant", "content": None, "reasoning_details": reasoning,
                              "tool_calls": [call("c1", "run_shell", {"command": "ls"})]},
                             "tool_calls")),
            (200, completion({"role": "assistant", "content": "Done."}, cost=0.0002)),
        ]
    )  # fmt: skip
    convo = router.model().start("system prompt", "list files", TOOL_SCHEMAS)

    turn = await convo.next_turn()
    assert turn.stop == "tool_use" and turn.cost_usd == 0.0005
    assert turn.tool_calls[0].name == "run_shell"
    assert turn.tool_calls[0].args == {"command": "ls"}

    convo.add_tool_results([ToolResultMsg("c1", "README.md", False)])
    final = await convo.next_turn()
    assert final.stop == "end" and final.text == "Done."

    first, second = router.bodies
    assert first["messages"][0] == {"role": "system", "content": "system prompt"}
    assert first["tools"][0]["type"] == "function"
    assert first["reasoning"] == {"effort": "medium"}
    assistant, tool_msg = second["messages"][2], second["messages"][3]
    assert assistant["reasoning_details"] == reasoning  # passed back unmodified
    assert tool_msg == {"role": "tool", "tool_call_id": "c1", "content": "README.md"}


async def test_openrouter_marks_errors_in_tool_messages():
    router = Router([])
    convo = router.model().start("s", "t", TOOL_SCHEMAS)
    convo.add_tool_results([ToolResultMsg("c1", "Blocked by AgentGuard", True)])
    assert convo.messages[-1]["content"] == "ERROR: Blocked by AgentGuard"


@pytest.mark.parametrize(
    ("finish", "stop"), [("length", "max_tokens"), ("content_filter", "refusal")]
)
async def test_openrouter_finish_reasons(finish, stop):
    router = Router([(200, completion({"role": "assistant", "content": "x"}, finish))])
    turn = await router.model().start("s", "t", TOOL_SCHEMAS).next_turn()
    assert turn.stop == stop


async def test_openrouter_retries_rate_limit_then_succeeds():
    router = Router(
        [
            (429, {"error": {"code": 429, "message": "slow down"}}),
            (200, completion({"role": "assistant", "content": "ok"})),
        ]
    )
    turn = await router.model().start("s", "t", TOOL_SCHEMAS).next_turn()
    assert turn.text == "ok" and len(router.bodies) == 2


async def test_openrouter_auth_error_is_not_retried():
    router = Router([(401, {"error": {"code": 401, "message": "bad key"}})])
    with pytest.raises(ModelError, match="HTTP 401"):
        await router.model().start("s", "t", TOOL_SCHEMAS).next_turn()
    assert len(router.bodies) == 1


async def test_openrouter_gives_up_after_retries():
    router = Router([(503, {"error": "down"})] * 3)
    with pytest.raises(ModelError, match="HTTP 503"):
        await router.model().start("s", "t", TOOL_SCHEMAS).next_turn()
    assert len(router.bodies) == 3


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"path": "a.txt"}', {"path": "a.txt"}),
        ("", {}),
        ("{not json", {"_invalid_arguments": "{not json"}),
        ('["a"]', {"_invalid_arguments": '["a"]'}),
    ],
)
def test_parse_arguments(raw, expected):
    assert parse_arguments(raw) == expected


async def test_malformed_arguments_reach_agent_as_error(toolbox, logger, settings, sandbox):
    router = Router(
        [
            (200, completion({"role": "assistant", "content": None,
                              "tool_calls": [call("c1", "read_file", "{oops")]}, "tool_calls")),
            (200, completion({"role": "assistant", "content": "Gave up."})),
        ]
    )  # fmt: skip
    run = await run_agent(
        "read it", model=router.model(), interceptor=Interceptor(AllowAll(), toolbox),
        logger=logger, settings=settings,
    )  # fmt: skip
    assert run.status == "completed" and sandbox.calls == []
    tool_msg = router.bodies[1]["messages"][-1]
    assert tool_msg["content"].startswith("ERROR: Invalid arguments for read_file")
    assert run.cost_usd == pytest.approx(0.001)


async def test_anthropic_api_error_becomes_model_error():
    import anthropic

    class Failing(FakeClient):
        async def create(self, **kwargs):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APIConnectionError(request=request)

    convo = AnthropicModel("claude-opus-5-5", client=Failing([])).start("s", "t", TOOL_SCHEMAS)
    with pytest.raises(ModelError):
        await convo.next_turn()


async def test_anthropic_adapter_reports_tool_calls():
    client = FakeClient([message([tool_use("t1", "read_file", {"path": "x"})], "tool_use")])
    turn = (
        await AnthropicModel("claude-opus-5-5", client=client)
        .start("s", "t", TOOL_SCHEMAS)
        .next_turn()
    )
    assert turn.stop == "tool_use" and turn.tool_calls[0].args == {"path": "x"}
    assert turn.cost_usd > 0


def test_build_model_needs_openrouter_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ModelError, match="OPENROUTER_API_KEY"):
        build_model(Settings(agent_provider="openrouter"))
    with pytest.raises(ValueError):
        build_model(Settings(agent_provider="nope"))


def test_load_dotenv_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\nAG_TEST_A=from-file\nexport AG_TEST_B="quoted"\nAG_TEST_C=\n')
    monkeypatch.setenv("AG_TEST_A", "from-shell")
    monkeypatch.delenv("AG_TEST_B", raising=False)
    monkeypatch.delenv("AG_TEST_C", raising=False)
    load_dotenv(env)
    import os

    assert os.environ["AG_TEST_A"] == "from-shell"
    assert os.environ["AG_TEST_B"] == "quoted"
    assert "AG_TEST_C" not in os.environ
    monkeypatch.delenv("AG_TEST_B")
