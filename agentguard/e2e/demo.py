"""Render a recorded Level 3 run as an animated GIF, step by step, as the guard saw it.

    uv run --group report python -m agentguard.e2e.demo \\
        --agent gpt-oss-120b --run judge-cheap-deny --scenario s50 --out docs/demo.gif

Nothing is staged: the commands, scores and decisions are the saved ones from
results/e2e/<agent>/<run>.jsonl.
"""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from agentguard.config import ROOT
from agentguard.e2e.run import E2E_DIR
from agentguard.e2e.scenarios import all_scenarios
from agentguard.e2e.score import rederive

W, H, PAD, LINE = 1000, 580, 28, 24
BG, PANEL, TEXT, MUTED = "#0d1117", "#161b22", "#e6edf3", "#8b949e"
COLOR = {"allow": "#3fb950", "escalate": "#d29922", "block": "#f85149"}
WORD = {"allow": "ALLOW", "escalate": "ASK A HUMAN", "block": "BLOCK"}
GUARD_NAMES = {
    "judge-cheap": "cheap LLM judge (Haiku 5.5)",
    "cascade-cheap-strong": "cascade: cheap judge, then strong",
    "cascade-jev-cheap": "cascade: Jev, then cheap judge",
    "jev": "Jev 1.14",
    "rules": "rules",
    "classifier": "DeBERTa classifier",
}
FONTS = ("/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONTS:
        if Path(path).is_file():
            return ImageFont.truetype(path, size, index=1 if bold and path.endswith("ttc") else 0)
    return ImageFont.load_default()


REG, BOLD, SMALL = font(16), font(16, bold=True), font(14)
COLS = 92  # characters per line at 16 px


def command_text(call: dict[str, Any]) -> str:
    tool, _, raw = call["text"].partition(" ")
    try:
        args = json.loads(raw)
    except json.JSONDecodeError:
        return f"{tool} {raw}"
    if tool == "run_shell":
        return f"$ {args['command']}"
    if tool == "write_file":
        return f"write_file {args.get('path')} ({len(args.get('content', ''))} characters)"
    if tool == "read_file":
        return f"read_file {args.get('path')}"
    if tool == "send_email":
        return f"send_email to {', '.join(args.get('to', []))}: {args.get('subject', '')}"
    return f"{tool} {json.dumps(args)[:200]}"


class Frames:
    def __init__(self, header: list[tuple[str, str]]) -> None:
        self.header = header
        self.log: list[tuple[str, str, Any]] = []  # (text, color, font)
        self.images: list[Image.Image] = []
        self.durations: list[int] = []

    def add(self, ms: int, footer: list[tuple[str, str]] | None = None) -> None:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        y = PAD
        for text, color in self.header:
            for line in textwrap.wrap(text, COLS) or [""]:
                d.text((PAD, y), line, fill=color, font=BOLD if color == TEXT else REG)
                y += LINE
        y += 8
        top = y
        d.rounded_rectangle((PAD - 10, top - 8, W - PAD + 10, H - 92), 8, fill=PANEL)
        rows = (H - 92 - top) // LINE
        for text, color, f in self.log[-rows:]:
            d.text((PAD, y), text, fill=color, font=f)
            y += LINE
        y = H - 78
        for text, color in footer or []:
            d.text((PAD, y), text, fill=color, font=REG if color != TEXT else BOLD)
            y += LINE
        self.images.append(img)
        self.durations.append(ms)

    def line(self, text: str, color: str = TEXT, f: Any = REG, indent: str = "") -> None:
        for i, part in enumerate(textwrap.wrap(text, COLS - len(indent)) or [""]):
            self.log.append(((indent if i == 0 else " " * len(indent)) + part, color, f))


def render(agent: str, run: str, scenario: str, out: Path) -> Path:
    path = E2E_DIR / agent / f"{run}.jsonl"
    record = next(
        rederive(r)  # attack-step flags with the current rules, as in the scores
        for r in map(json.loads, path.read_text().splitlines())
        if r["scenario"] == scenario
    )
    s = {x.id: x for x in all_scenarios()}[scenario]
    mode = (
        "nobody to ask, so escalations are refused"
        if run.endswith("deny")
        else ("a reviewer answers escalations")
    )
    guard = GUARD_NAMES.get(run.rsplit("-", 1)[0], run)
    frames = Frames([
        (f"AgentGuard · a recorded run: {agent} as the agent, guarded by the {guard}", TEXT),
        (f"User's task (the guard sees it): {s.task}", MUTED),
        (f"Secret side task (only the agent sees it): {s.side_task}", "#d2a8ff"),
    ])  # fmt: skip
    frames.add(3500, [(f"Every tool call is scored before it runs; {mode}.", MUTED)])
    tries = blocked = 0
    for c in record["calls"]:
        frames.line(command_text(c)[:400], TEXT, REG, "agent  ")
        frames.add(1300)
        decision = c["decision"]
        verdict = f"{WORD[decision]}   p(unsafe) = {c['p_unsafe']:.2f}"
        if c["is_attack_action"]:
            tries += 1
            blocked += not c["executed"]
            verdict += "   ← a step toward the side task"
        frames.line(verdict, COLOR[decision], BOLD, "guard  ")
        if c["executed"] and c["output"]:
            lines = c["output"].strip().splitlines()
            first = [x for x in lines if x.strip() and not x.startswith(("exit_code", "---"))][:2]
            for out_line in first:
                frames.line(out_line[: COLS - 7], MUTED, SMALL, "       ")
        frames.line("")
        frames.add(1700 if c["is_attack_action"] else 1200)
    result = "landed" if record["passed"] else "was stopped"
    reply = textwrap.wrap(" ".join(record["final_text"].split()), COLS - 2)[:2]
    frames.add(6000, [
        (f"Side task {result}: {tries} attempts, {blocked} kept from running. "
         "The user's task was still done:", TEXT),
        *[(("“" if i == 0 else " ") + part + ("…”" if i == len(reply) - 1 else ""), MUTED)
          for i, part in enumerate(reply)],
    ])  # fmt: skip
    out.parent.mkdir(parents=True, exist_ok=True)
    frames.images[0].save(
        out, save_all=True, append_images=frames.images[1:], duration=frames.durations,
        loop=0, optimize=True,
    )  # fmt: skip
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentguard.e2e.demo")
    parser.add_argument("--agent", default="gpt-oss-120b")
    parser.add_argument("--run", default="judge-cheap-deny")
    parser.add_argument("--scenario", default="s50")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "demo.gif")
    args = parser.parse_args(argv)
    print(render(args.agent, args.run, args.scenario, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
