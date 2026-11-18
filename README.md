# AgentGuard

A pre-execution safety monitor for LLM agents. AgentGuard sits between an agent and its tools,
scores every proposed action before it runs, and allows, escalates or blocks it.

> **Status: Phase 3 done.** All four guards (rules, classifier, LLM judge, Jev) and a
> cascade run on the dev split; results below are dev numbers only. The single test-split
> evaluation comes in Phase 4.

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

## Guard backends (Phase 3)

Each guard reads one proposed action (task, history, tool, arguments) and returns
`p_unsafe` (0 to 1) and a category. The policy turns that into allow / escalate / block.

| Guard | What it is | Cost per check |
|---|---|---|
| `rules` | Hand-written patterns for dangerous commands, secret paths and outgoing data, plus a check for actions that reuse an address or id taken from an instruction inside a tool output | free, about 1 ms |
| `judge-cheap` | Claude Haiku 5.5 via OpenRouter, low reasoning effort, JSON answer constrained by a schema | about $0.0002, about 2 s |
| `judge-strong` | Claude Opus 5.5 via OpenRouter, medium effort; if its safety filter declines, Sonnet 5.5, then Haiku 5.5 | about $0.008, about 3 s |
| `classifier` | DeBERTa-v3-small fine-tuned on the train split (4 epochs, Apple GPU, 8 minutes) | free, about 50 ms |
| `jev` | TypeSafe's Jev 1.14 via OpenRouter's Decisions API (same key): 7 yes/no questions, one per risk category; p_unsafe is the highest answer | about $0.00005, about 0.4 s |

```bash
make guard-dev BACKEND=rules      # or judge-cheap, judge-strong, classifier, jev, cascade
make tune                         # thresholds and cascade from the saved dev runs
make train-classifier             # needs the ml group: uv sync --group ml
```

**Dev-split results** (191 rows, 43 unsafe; threshold 0.5; numbers move a lot with this few rows):

| Guard | Catches (recall) | False alarms | AUROC | Without ambiguous rows: recall / false alarms |
|---|---|---|---|---|
| rules | 56% | 2.7% | 0.83 | 75% / 1.6% |
| judge-cheap | 77% | 0.7% | 0.95 | 97% / 0% |
| judge-strong | 91% | 4.7% | 0.98 | 97% / 1.6% |
| classifier | 44% | 0.7% | 0.86 | 56% / 0.8% |
| jev | 72% | 4.7% | 0.91 | 97% / 1.6% |

Caveats:
- These are dev numbers, used for building and tuning. The real comparison is the single
  Phase 4 run on the frozen test split, with confidence intervals.
- The rules were written and checked on the train split. Their injection check fits
  InjecAgent rows well because those rows share a template.
- Claude labeled most rows (under rules written with the author), and two of the guards
  are Claude models judging from a summary of the same rules. That shared origin may
  inflate the judges' agreement with the labels.
- Opus 5.5's safety filter declined to judge 15% of dev rows (attack-like content); a
  fallback model answered those, and each verdict records which model answered.
- The classifier catches injection rows (86%) but almost nothing else: most categories
  have only 2 to 15 training rows.
- Jev's questions were written once, before its dev run, and not adjusted afterwards. It
  names the right category for only 61% of the unsafe rows it catches, because its
  questions overlap (an injected request to send data is both injection and exfiltration).

Per-row verdicts and summaries are in `results/runs/`; the classifier's training record is
in `results/classifier/metrics.json`.

### Thresholds and the cascade

`make tune` picks each guard's thresholds from its saved dev verdicts, using rules fixed in
advance: block only above the point where at most 1% of safe rows would be blocked, and
auto-allow only below the point where at most 5% of unsafe rows would get through. Anything
in between is escalated to a human. It costs nothing: no guard is called again.

| Guard (dev-tuned) | Allow below | Block above | Unsafe let through | Safe blocked | Sent to a human |
|---|---|---|---|---|---|
| rules | never allows | 0.83 | 0 of 43 | 0 of 148 | 187 of 191 |
| classifier | 0.016 | 0.51 | 2 | 1 | 98 |
| jev | 0.065 | 0.89 | 1 | 1 | 103 |
| judge-cheap | 0.045 | 0.38 | 1 | 1 | 91 |
| judge-strong | 0.24 | 0.71 | 2 | 1 | 24 |

A cheap guard on its own is cheap but sends half of all actions to a human, while the strong
judge is accurate but costs about 33 times more. The **cascade** (in `policy.py`, after
FrugalGPT) combines them: the cheap judge decides the actions it is sure about, and only
the rest go to the strong judge. `make tune` replays 14 possible cascades on the saved dev
verdicts and picks the cheapest that lets through no more unsafe actions, blocks no more
safe ones and escalates no more than the strong judge alone (fewer stages win when the
saving is under 5%).

| Dev, 191 rows | Unsafe let through | Safe blocked | Sent to a human | Cost per 1,000 checks |
|---|---|---|---|---|
| judge-strong alone | 2 | 1 | 24 | $7.55 |
| **cascade: judge-cheap, then judge-strong** | 2 | 1 | 21 | **$4.51 (40% less)** |

Only 48% of actions reach the strong judge. Adding the rules in front saves under 0.1%.
Cheaper cascades exist but miss the bar on dev: classifier first ($2.83) lets 4 unsafe
actions through instead of 2, and Jev, then the cheap judge, then the strong one ($3.39)
lets 3 through and blocks 2 safe ones. One or two rows are within noise at this size;
Phase 4's sweep on test settles it. The cascade is a backend like the others
(`make guard-dev BACKEND=cascade`); the runner and the interceptor apply each guard's tuned
thresholds automatically.

Caveats: with 43 unsafe dev rows, "at most 5%" means at most 2 rows, so these thresholds
are rough. A live run of the cascade on 10 dev rows agreed with the replay on 9; the other
differed because LLM judges give slightly different scores each time they are asked. The
plan's cost-versus-recall sweep and the final numbers come from the test split in Phase 4.
Choices and per-candidate results are in `results/tuning/`.

## Layout

```
agentguard/
  agent/         loop.py (agent loop), models.py (OpenRouter / Anthropic adapters),
                 tools.py, sandbox.py, tasks.py
  guard/
    schemas.py   ActionProposal, Verdict, GuardBackend, RiskCategory
    interceptor.py
    policy.py    thresholds, tuned thresholds, and the cascade
    logger.py    JSONL logger
    backends/    allow_all.py, rules.py, llm_judge.py, classifier.py, jev.py
    train_classifier.py  fine-tunes the DeBERTa guard
  eval/          run a guard over a split and summarise it; tune.py picks thresholds and a cascade
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
| 3. Guard backends | 6–7 | All 4 backends return valid Verdicts on the dev split (passed) |
| 4. Evaluation and attacks | 8–9 | 4 charts with error bars from `make report` |
| 5. Ship | 10 | README, demo, write-up |

Test split hash (sha256 of `data/splits/test.jsonl`, frozen 2026-11-17):
`f7a2f0cbda0484b707a9ac46760d364ae06e0c6cce05f4bb9cde052760b09ce8`
