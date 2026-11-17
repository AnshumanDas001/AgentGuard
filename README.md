# AgentGuard

A pre-execution safety monitor for LLM agents. AgentGuard sits between an agent and its tools,
scores every proposed action before it runs, and allows, escalates or blocks it.

> **Status: Phase 1 (agent, sandbox, interceptor).** The guard runs with a pass-through
> `AllowAll` backend; the rules, classifier, LLM-judge and Jev backends come in Phase 3.
> No results yet.

## How it works

```
user task ─▶ agent loop (Claude, tool calling)
                 │ proposes tool call
                 ▼
             Interceptor ─▶ GuardBackend.assess() ─▶ Verdict(p_unsafe, category, ...)
                 │                                        │
                 │              ThresholdPolicy: allow < 0.3 ≤ escalate ≤ 0.7 < block
                 ▼
     allowed: run in Docker sandbox     blocked: reason returned to the agent as a tool error
                 │
                 ▼
          JSONL log (every action, verdict and decision)
```

- **Five tools:** `read_file`, `write_file`, `run_shell` (run inside the container via
  `docker exec`), `http_request` (host-side, allowlisted hosts only) and `send_email`
  (fake: writes to `results/outbox.jsonl`).
- **Sandbox:** a fresh container per run, with `--network none`, no Linux capabilities, and
  capped memory, CPU and process count. It holds a fake project (`sandbox/seed/`).
- **Canaries:** a fake `.env` and `~/.aws/credentials` are planted as bait. If an allowed
  request or email carries one of those values, the run logs a `canary_leak`.
- **Fail closed:** if a guard backend errors or times out, the action is blocked.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/), Docker, and an OpenRouter API key
(or an Anthropic one).

```bash
cp .env.example .env   # then put your OPENROUTER_API_KEY in .env (gitignored)
make setup      # install dependencies
make test       # unit tests; no Docker or API key needed
make sandbox    # build the sandbox image
make check      # preflight: Docker, image, provider key
make run TASK="Find all TODO comments in the project"
make tasks      # the 10 ordinary tasks (Phase 1 gate)
```

Each run prints its tool calls as they happen and appends to `results/logs/run-*.jsonl`.
Pass `--escalate ask` to approve escalated actions by hand
(`uv run python -m agentguard run "..." --escalate ask`).

Configuration comes from `AGENTGUARD_*` variables in `.env` or the environment (the
environment wins; see `.env.example`). The agent defaults to `anthropic/claude-haiku-5.5`
through OpenRouter at `medium` reasoning effort, which costs about $0.10 / $0.50 per million
input / output tokens. Any OpenRouter model with tool support works via
`AGENTGUARD_AGENT_MODEL`. To call Anthropic directly instead, set
`AGENTGUARD_AGENT_PROVIDER=anthropic` and `AGENTGUARD_AGENT_MODEL=claude-opus-5-5`.

## Dataset (Phase 2)

Rows are labeled by hand under the rules in [data/labeling_rules.md](data/labeling_rules.md).

```bash
make data-check     # validate every dataset file
make data-stats     # counts per category against the targets
make label          # label rows one at a time, blind to their source
make label-sheet    # or label in a spreadsheet; then make import-labels SHEET=...
uv run python -m agentguard.dataset import-log results/logs/<run>.jsonl --source <name>
make injecagent      # add converted InjecAgent rows (pinned commit)
make assebench       # add converted ASSEBench rows (pinned commit)
make data-split     # stratified 50/20/30 split and test-set freeze (runs once)
```

Unlabeled rows live in `data/raw/<source>.jsonl`; labels are appended to
`data/labeled/labels.jsonl` (the latest decision per row wins).
Sources and licenses are listed in [data/SOURCES.md](data/SOURCES.md). Rows from the same
session are always kept in the same split, so related rows can't leak between train and test.

The frozen dataset has 1,064 rows (984 judged, 80 excluded): 496 train, 191 dev and 297 test.
Sources: 834 converted from ASSEBench, 85 from InjecAgent, 110 written by hand, and 35 from
the project's own agent runs. 207 rows are unsafe (21%), and 217 of the 777 safe rows are
hard negatives.

**Limitations.** Most of the per-category test sets are small, so only the overall scores and
`injection_driven` (29 unsafe test rows) support firm per-category claims. The other categories
are reported with their counts, and `resource_abuse` (2 unsafe test rows), `credential_access`
and `irreversible_external_action` (3 each) have too few rows to score at all. Most rows were
converted from benchmarks whose tools differ from this agent's 5 tools. Rows were labeled by
the author and Claude under the same written rules; there was no independent second labeler.

## Layout

```
agentguard/
  agent/         loop.py (agent loop), models.py (OpenRouter / Anthropic adapters),
                 tools.py, sandbox.py, tasks.py
  guard/
    schemas.py   ActionProposal, Verdict, GuardBackend, RiskCategory
    interceptor.py
    policy.py    thresholds (cascade comes in Phase 3)
    logger.py    JSONL logger
    backends/    allow_all.py (rules, classifier, jev, llm_judge to come)
  dataset/       row format, validator, stats, labeling tool, split and freeze
  pricing.py     token prices for cost per decision
sandbox/         Dockerfile + seeded fake project and canary secrets
tests/
notes/           paper reading notes
data/            labeled dataset (Phase 2)
results/         logs, tables, charts
```

## Roadmap

| Phase | Weeks | Gate |
|---|---|---|
| 0. Setup and reading | 1 | An LLM tool call runs a command in Docker |
| 1. Agent, sandbox, interceptor | 2–3 | 5+ tasks complete in the sandbox; every call logged |
| 2. Dataset | 4–5 | Test split frozen and committed (hash below) |
| 3. Guard backends | 6–7 | All 4 backends return valid Verdicts on the dev split |
| 4. Evaluation and attacks | 8–9 | 4 charts with error bars from `make report` |
| 5. Ship | 10 | README, demo, write-up |

Test split hash (sha256 of `data/splits/test.jsonl`, frozen 2026-11-17):
`f7a2f0cbda0484b707a9ac46760d364ae06e0c6cce05f4bb9cde052760b09ce8`
