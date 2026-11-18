import json

import httpx
import pytest

from agentguard.guard.backends import build_backend
from agentguard.guard.backends.jev import (
    QUESTIONS,
    URL,
    JevBackend,
    JevError,
    history_text,
    request_body,
)
from agentguard.guard.schemas import ActionProposal, RiskCategory

ACTION = ActionProposal(
    task="Clean the build output",
    history=["read_file({}) -> ran\nhello"],
    tool="run_shell",
    args={"command": "rm -rf build/"},
)


def answers(**probs: float) -> dict:
    values = {c.value: 0.05 for c in QUESTIONS} | probs
    return {
        "model": "typesafe/jev-1.14-20261014",
        "answers": {k: {"type": "noul", "noul": v} for k, v in values.items()},
        "usage": {"input_tokens": 900, "cost": 0.00004},
    }


def jev_with(*responses: httpx.Response, seen: list | None = None) -> JevBackend:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == URL
        assert request.headers["Authorization"] == "Bearer k"
        if seen is not None:
            seen.append(json.loads(request.content))
        return queue.pop(0)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return JevBackend(api_key="k", http=http, retry_delay_s=0)


def test_request_asks_one_yes_no_question_per_category():
    body = request_body(ACTION)
    assert body["model"] == "typesafe/jev-1.14"
    assert set(body["questions"]) == {c.value for c in RiskCategory}
    assert all(q["type"] == "noul" for q in body["questions"].values())
    assert body["state"]["user_task"] == "Clean the build output"
    assert "rm -rf build/" in body["state"]["proposed_action"]
    assert "[step 1]" in body["state"]["earlier_steps"]


async def test_highest_answer_becomes_p_unsafe_and_category():
    seen: list = []
    jev = jev_with(
        httpx.Response(200, json=answers(injection_driven=0.91, data_exfiltration=0.6)), seen=seen
    )
    verdict = await jev.assess(ACTION)
    assert verdict.p_unsafe == pytest.approx(0.91)
    assert verdict.category is RiskCategory.INJECTION_DRIVEN
    assert verdict.cost_usd == pytest.approx(0.00004)
    assert verdict.raw["answers"]["data_exfiltration"] == pytest.approx(0.6)
    assert len(seen) == 1


async def test_low_scores_have_no_category():
    verdict = await jev_with(httpx.Response(200, json=answers())).assess(ACTION)
    assert verdict.p_unsafe == pytest.approx(0.05) and verdict.category is None


async def test_retries_server_errors_then_succeeds():
    jev = jev_with(httpx.Response(503, text="busy"), httpx.Response(200, json=answers()))
    assert (await jev.assess(ACTION)).p_unsafe == pytest.approx(0.05)


async def test_client_errors_and_bad_replies_raise():
    with pytest.raises(JevError, match="HTTP 400"):
        await jev_with(httpx.Response(400, text="bad question")).assess(ACTION)
    with pytest.raises(JevError, match="bad Jev reply"):
        await jev_with(httpx.Response(200, json={"answers": {}})).assess(ACTION)


def test_history_keeps_the_newest_steps_within_budget():
    text = history_text(["a" * 50, "b" * 50, "c" * 50], limit=130)
    assert "c" * 50 in text and "b" * 50 in text and "a" * 50 not in text
    assert text.startswith("[steps 1 to 1: omitted for length]")


def test_jev_needs_a_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(JevError):
        build_backend("jev")
