"""Where agent commands actually run: a throwaway Docker container with no network."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from dataclasses import dataclass
from typing import Protocol, Self

WORKDIR = "/home/agent/project"


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class Sandbox(Protocol):
    async def exec(
        self, argv: list[str], *, stdin: bytes | None = None, timeout_s: float = 30.0
    ) -> ExecResult: ...


async def _run(*argv: str, stdin: bytes | None = None, timeout_s: float) -> ExecResult:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ExecResult(exit_code=-1, stdout="", stderr="timed out", timed_out=True)
    return ExecResult(
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=out.decode("utf-8", errors="replace"),
        stderr=err.decode("utf-8", errors="replace"),
    )


class DockerSandbox:
    """One fresh container per agent run, removed on exit.

    Hard limits: no network, no Linux capabilities, capped memory, CPU and process count.
    The guard decides what *should* run; this bounds the damage when the guard is wrong.
    """

    def __init__(
        self,
        image: str,
        *,
        memory: str = "512m",
        cpus: str = "1",
        pids_limit: int = 256,
    ) -> None:
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.name = f"agentguard-{uuid.uuid4().hex[:8]}"
        self._started = False

    async def __aenter__(self) -> Self:
        if shutil.which("docker") is None:
            raise SandboxError("docker not found on PATH; install Docker Desktop or colima")
        result = await _run(
            "docker", "run", "--detach", "--rm",
            "--name", self.name,
            "--network", "none",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--memory", self.memory,
            "--cpus", self.cpus,
            "--pids-limit", str(self.pids_limit),
            self.image,
            timeout_s=60,
        )  # fmt: skip
        if result.exit_code != 0:
            raise SandboxError(f"failed to start sandbox: {result.stderr.strip()}")
        self._started = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._started:
            await _run("docker", "rm", "--force", self.name, timeout_s=30)
            self._started = False

    async def exec(
        self, argv: list[str], *, stdin: bytes | None = None, timeout_s: float = 30.0
    ) -> ExecResult:
        if not self._started:
            raise SandboxError("sandbox is not running; use `async with DockerSandbox(...)`")
        # Killing the `docker exec` client leaves the process running in the container,
        # so enforce the deadline inside the container too.
        inner = ["timeout", "--signal=KILL", str(int(timeout_s)), *argv]
        flags = ["--interactive"] if stdin is not None else []
        result = await _run(
            "docker", "exec", *flags, "--workdir", WORKDIR, self.name, *inner,
            stdin=stdin,
            timeout_s=timeout_s + 5,
        )  # fmt: skip
        if result.exit_code == 137 and not result.timed_out:
            return ExecResult(137, result.stdout, result.stderr or "killed", True)
        return result
