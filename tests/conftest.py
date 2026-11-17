from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from anthropic.types.beta import BetaMessage

from agentguard.agent.sandbox import ExecResult
from agentguard.agent.tools import Toolbox
from agentguard.config import Settings
from agentguard.guard.logger import JsonlLogger


@dataclass
class FakeSandbox:
    """Records every exec and replies with a canned result."""

    result: ExecResult = field(default_factory=lambda: ExecResult(0, "", ""))
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def exec(
        self, argv: list[str], *, stdin: bytes | None = None, timeout_s: float = 30.0
    ) -> ExecResult:
        self.calls.append({"argv": argv, "stdin": stdin, "timeout_s": timeout_s})
        return self.result


def message(content: list[dict[str, Any]], stop_reason: str = "end_turn") -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 100},
        }
    )


def tool_use(tool_id: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": args}


class FakeClient:
    """Stands in for AsyncAnthropic: returns scripted messages, records requests."""

    def __init__(self, responses: list[BetaMessage]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.beta = self
        self.messages = self

    async def create(self, **kwargs: Any) -> BetaMessage:
        # Snapshot the message list: the loop keeps appending to the same object.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        max_steps=5,
        http_allowlist=("example.com",),
        log_dir=tmp_path / "logs",
        outbox_path=tmp_path / "outbox.jsonl",
    )


@pytest.fixture
def sandbox() -> FakeSandbox:
    return FakeSandbox()


@pytest.fixture
def http_requests() -> list[httpx.Request]:
    return []


@pytest.fixture
def toolbox(sandbox: FakeSandbox, settings: Settings, http_requests: list) -> Toolbox:
    def handler(request: httpx.Request) -> httpx.Response:
        http_requests.append(request)
        return httpx.Response(200, text="<title>Example Domain</title>")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Toolbox(sandbox, settings, http=http)


@pytest.fixture
def logger(tmp_path: Path) -> JsonlLogger:
    return JsonlLogger(tmp_path / "logs" / "test.jsonl")
