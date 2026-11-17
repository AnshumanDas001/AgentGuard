"""Model adapters: one interface for the agent loop, whichever API serves the model.

Each adapter owns its conversation history, because the Anthropic and OpenAI-style
(OpenRouter) message formats differ. The loop only sees ModelTurns and ToolCalls.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic
import httpx

from agentguard.config import Settings
from agentguard.pricing import estimate_cost

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16_000


class ModelError(RuntimeError):
    """The model API failed (after retries) or returned something unusable."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolResultMsg:
    tool_call_id: str
    content: str
    is_error: bool


@dataclass(frozen=True)
class ModelTurn:
    stop: str  # tool_use | end | max_tokens | refusal | pause
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    cost_usd: float = 0.0
    model: str = ""


class Conversation(Protocol):
    async def next_turn(self) -> ModelTurn: ...

    def add_tool_results(self, results: list[ToolResultMsg]) -> None: ...


class AgentModel(Protocol):
    name: str

    def start(self, system: str, task: str, tools: list[dict[str, Any]]) -> Conversation: ...

    async def aclose(self) -> None: ...


# --- Anthropic (direct) -------------------------------------------------------------------


class AnthropicModel:
    def __init__(
        self,
        model: str,
        *,
        effort: str = "medium",
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.name = model
        self.effort = effort
        self.client = client or anthropic.AsyncAnthropic()

    def start(self, system: str, task: str, tools: list[dict[str, Any]]) -> Conversation:
        return _AnthropicConversation(self, system, task, tools)

    async def aclose(self) -> None:
        close = getattr(self.client, "close", None)
        if close is not None:
            await close()


class _AnthropicConversation:
    def __init__(
        self, model: AnthropicModel, system: str, task: str, tools: list[dict[str, Any]]
    ) -> None:
        self.model = model
        self.system = system
        self.tools = tools
        self.messages: list[dict[str, Any]] = [{"role": "user", "content": task}]

    async def next_turn(self) -> ModelTurn:
        try:
            response = await self.model.client.beta.messages.create(
                model=self.model.name,
                max_tokens=MAX_TOKENS,
                system=self.system,
                tools=self.tools,
                messages=self.messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.model.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APIError as e:
            raise ModelError(f"{type(e).__name__}: {e}") from e

        cost = estimate_cost(response.model, response.usage)
        if response.stop_reason == "refusal":
            return ModelTurn("refusal", cost_usd=cost, model=response.model)
        # Append the whole content list (thinking blocks included), never an edited copy.
        self.messages.append({"role": "assistant", "content": response.content})
        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason == "max_tokens":
            return ModelTurn("max_tokens", text, cost_usd=cost, model=response.model)
        calls = [
            ToolCall(b.id, b.name, dict(b.input)) for b in response.content if b.type == "tool_use"
        ]
        if calls:
            stop = "tool_use"
        elif response.stop_reason == "pause_turn":
            stop = "pause"
        else:
            stop = "end"
        return ModelTurn(stop, text, calls, cost, response.model)

    def add_tool_results(self, results: list[ToolResultMsg]) -> None:
        # All results for one turn go back in a single user message.
        content = [
            {
                "type": "tool_result",
                "tool_use_id": r.tool_call_id,
                "content": r.content,
                "is_error": r.is_error,
            }
            for r in results
        ]
        self.messages.append({"role": "user", "content": content})


# --- OpenRouter (OpenAI-compatible chat completions) --------------------------------------


def to_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


def parse_arguments(raw: str | None) -> dict[str, Any]:
    """Tool arguments arrive as a JSON string. Anything unparseable is passed on under a key
    no tool accepts, so the toolbox rejects it and the model sees an error."""
    if not raw:
        return {}
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        return {"_invalid_arguments": raw}
    return args if isinstance(args, dict) else {"_invalid_arguments": raw}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict)).strip()
    return ""


class OpenRouterModel:
    def __init__(
        self,
        model: str,
        *,
        api_key: str,
        effort: str = "medium",
        http: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        retry_delay_s: float = 1.0,
    ) -> None:
        self.name = model
        self.effort = effort
        self.max_retries = max_retries
        self.retry_delay_s = retry_delay_s
        self.http = http or httpx.AsyncClient(timeout=120.0)
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Title": "AgentGuard",
        }

    def start(self, system: str, task: str, tools: list[dict[str, Any]]) -> Conversation:
        return _OpenRouterConversation(self, system, task, tools)

    async def complete(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST with retries on rate limits, server errors and dropped connections."""
        error = "no attempt made"
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.http.post(OPENROUTER_URL, json=body, headers=self.headers)
            except httpx.TransportError as e:
                error = f"{type(e).__name__}: {e}"
            else:
                if response.status_code == 200:
                    return response.json()
                error = f"HTTP {response.status_code}: {response.text[:500]}"
                if response.status_code not in RETRY_STATUSES:
                    raise ModelError(error)
            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay_s * 2**attempt)
        raise ModelError(error)

    async def aclose(self) -> None:
        await self.http.aclose()


class _OpenRouterConversation:
    def __init__(
        self, model: OpenRouterModel, system: str, task: str, tools: list[dict[str, Any]]
    ) -> None:
        self.model = model
        self.tools = [to_openai_tool(t) for t in tools]
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]

    async def next_turn(self) -> ModelTurn:
        data = await self.model.complete(
            {
                "model": self.model.name,
                "messages": self.messages,
                "tools": self.tools,
                "tool_choice": "auto",
                "max_tokens": MAX_TOKENS,
                "reasoning": {"effort": self.model.effort},
            }
        )
        if data.get("error"):
            raise ModelError(f"OpenRouter error: {data['error']}")
        choices = data.get("choices") or []
        if not choices:
            raise ModelError(f"OpenRouter returned no choices: {str(data)[:500]}")
        choice = choices[0]
        if choice.get("error"):
            raise ModelError(f"OpenRouter provider error: {choice['error']}")

        served = data.get("model", self.model.name)
        cost = float((data.get("usage") or {}).get("cost") or 0.0)
        finish = choice.get("finish_reason")
        if finish == "content_filter":
            return ModelTurn("refusal", cost_usd=cost, model=served)

        message = choice.get("message") or {}
        assistant: dict[str, Any] = {"role": "assistant", "content": message.get("content")}
        if message.get("tool_calls"):
            assistant["tool_calls"] = message["tool_calls"]
        if message.get("reasoning_details"):
            # Must go back unmodified for the model to keep its reasoning across tool calls.
            assistant["reasoning_details"] = message["reasoning_details"]
        self.messages.append(assistant)

        text = _text(message.get("content"))
        if finish == "length":
            return ModelTurn("max_tokens", text, cost_usd=cost, model=served)
        calls = [
            ToolCall(
                tc["id"], tc["function"]["name"], parse_arguments(tc["function"].get("arguments"))
            )
            for tc in message.get("tool_calls") or []
        ]
        return ModelTurn("tool_use" if calls else "end", text, calls, cost, served)

    def add_tool_results(self, results: list[ToolResultMsg]) -> None:
        # OpenAI-style tool messages have no error flag, so errors are marked in the text.
        for r in results:
            content = f"ERROR: {r.content}" if r.is_error else r.content
            self.messages.append(
                {"role": "tool", "tool_call_id": r.tool_call_id, "content": content}
            )


def build_model(settings: Settings) -> AgentModel:
    if settings.agent_provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise ModelError("OPENROUTER_API_KEY is not set; add it to .env")
        return OpenRouterModel(settings.agent_model, api_key=api_key, effort=settings.agent_effort)
    if settings.agent_provider == "anthropic":
        return AnthropicModel(settings.agent_model, effort=settings.agent_effort)
    raise ValueError(f"unknown agent provider: {settings.agent_provider!r}")
