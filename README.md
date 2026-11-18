# AgentGuard

A pre-execution safety monitor for LLM agents. AgentGuard sits between an agent and its tools,
scores every proposed action before it runs, and allows, escalates or blocks it.

> **Status: Phase 4 under way.** The single test-split run is done for rules, the
> classifier, Jev and the cheap LLM judge, with 95% confidence intervals
> ([test results](#test-results-phase-4-level-1)). The strong judge's test run is deferred
> for now. Still to come: attack rewrites (Level 2) and end-to-end agent runs (Level 3).

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

**Blind relabel of the 37 ambiguous dev rows.** The author relabeled them without seeing
the original labels, notes or guard scores (`make relabel-sheet`, then `make relabel-compare
SHEET=...`). Agreement with the original labels was 49% (Cohen's kappa 0.18, "slight"),
and the category matched on 55% of rows both called unsafe. The author marked 30 of the 37
rows unsafe, against 11 originally: mostly ASSEBench rows where an unverified change to a
database, schedule, patient record or industrial control could do harm. Scored against
the author's labels, the strong judge ranks these rows almost perfectly (AUROC 0.97), the
cheap judge 0.76, Jev 0.69, rules 0.62 and the classifier 0.43 (with only 7 safe rows,
these are rough). On borderline rows, who labels matters about as much as which guard. The
original labels are unchanged, and headline numbers use clear rows only. Details:
`results/relabel/dev-ambiguous.json`; the new labels: `data/labeled/relabel-dev-ambiguous.jsonl`.

**Tried and rejected: doubling the classifier's training data with contrastive twins.**
`make augment` builds 404 twins from train rows only (`data/augmented/train-twins.jsonl`):
safe lookalikes paired with unrelated tasks (now unsafe), injection attacks and handwritten
unsafe rows rewritten so the user asks for the action (now safe), and harmless reads under
unrelated tasks (still safe). The idea was to teach the classifier that the task decides
safety. It made the classifier worse on dev:

| Training data | Best dev AUROC | Dev false alarms at 0.5 (best epoch) |
|---|---|---|
| train only (kept) | 0.86 | 0.7% |
| train + all 404 twins | 0.78 | 80% |
| train + the 333 swap twins only | 0.77 | 36% |

The twins make the same action appear as both safe and unsafe, with only the task to tell
them apart. DeBERTa-v3-small with about 900 rows does not learn to compare a task with an
action; it falls back on the action alone, now skewed towards "unsafe". The clearest losses
were on the handwritten rows (AUROC 0.94 to 0.44) and credential access (0.95 to 0.24). The
original classifier stays; the twin code and the training records
(`results/classifier/metrics-aug*.json`) are kept so the experiment can be rerun
(`make train-classifier-aug`; add `--augment-kinds unsafe_swap safe_swap` for the second row).

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

## Test results (Phase 4, Level 1)

![Recall at 1% false-positive rate against cost per 1,000 decisions](results/charts/test-cost-recall.png)

The frozen test split, scored once per guard on 2026-11-19 (Jev `typesafe/jev-1.14-20261014`,
cheap judge `anthropic/claude-haiku-5.5`). Each guard was run twice more for latency only.
Headline numbers use the 257 rows not marked ambiguous (51 unsafe, 206 safe). Brackets are
95% bootstrap CIs (1,000 resamples, stratified by label). The strong judge was not run on
test yet.

```bash
make test-runs   # the single test run: each guard 3 times (about $0.25)
make report      # metrics with CIs and the charts, from the saved runs (no API calls)
make eval-dev    # the same metrics on dev
```

| Guard | Recall at 1% FPR | AUROC | PR-AUC | Calibration error (ECE, all rows) | Latency p50 / p95 | Cost per 1,000 |
|---|---|---|---|---|---|---|
| rules | 71% [59, 82] | 0.88 [0.82, 0.94] | 0.81 [0.72, 0.89] | 0.05 [0.04, 0.08] | 0.3 ms / 8.9 ms | $0.00 |
| classifier | 45% [33, 65] | 0.94 [0.92, 0.97] | 0.83 [0.76, 0.90] | 0.08 [0.06, 0.11] | 54 ms / 173 ms | $0.00 |
| jev | 86% [71, 96] | 0.97 [0.94, 1.00] | 0.95 [0.91, 0.99] | 0.04 [0.03, 0.07] | 539 ms / 612 ms | $0.05 |
| judge-cheap | 84% [0, 100] | 0.99 [0.98, 1.00] | 0.94 [0.85, 1.00] | 0.04 [0.03, 0.08] | 1.5 s / 3.1 s | $0.22 |

As deployed, with each guard's thresholds tuned on dev (clear test rows):

| Guard | Unsafe let through (of 51) | Safe blocked (of 206) | Sent to a human (of 257) | Cost per 1,000 |
|---|---|---|---|---|
| rules | 0 | 0 | 248 (it never auto-allows) | $0.00 |
| classifier | 0 | 3 | 122 | $0.00 |
| jev | 1 | 0 | 128 | $0.05 |
| judge-cheap | 0 | 3 | 90 | $0.22 |
| cascade: jev, then judge-cheap on the unsure 25% | 1 | 1 | 30 | $0.11 |

What the test run shows:

1. **Jev and the cheap judge are statistically tied where it matters.** At 1% FPR Jev
   catches 86% and the judge 84%. The paired difference is +2 points [-18, +86], and on
   AUROC it is -0.02 [-0.06, +0.01]: neither is clearly better. Jev costs a quarter as much
   and answers about 3 times faster.
2. **Recall at 1% FPR is fragile at this size.** With 206 safe rows, 1% means 2 false
   alarms, so the number rests on the three highest-scoring safe rows. The cheap judge gave
   one safe row a score of 1.0; any resample that draws that row three times cannot reach
   1% FPR, which is why its CI runs down to 0. AUROC and the as-deployed counts are steadier.
3. **The best cascade puts Jev first.** Jev decides the rows it is sure about and the cheap
   judge sees the rest. With Jev's thresholds set on dev to let it clear rows alone at a 10%
   miss budget, 25% of rows reach the judge. That cascade catches 94% [76, 100] at 1% FPR,
   costs half as much as the judge alone, and sends 30 rows to a human instead of 90.
   Caveat: on dev every budget from 0% to 20% looked equally safe, and the cheapest (20%)
   lets 4 unsafe rows through on test. The 10% point was not chosen in advance.
4. **The small guards cover injections and little else.** Rules catch 96% of injection
   rows at 1% FPR and the classifier 79%, but the classifier catches none of the other
   categories at that rate (table below). Its AUROC (0.94) looks good, but its high scores
   are reserved for injection-style rows.
5. **Every false block on clear rows is an ASSEBench row** (classifier 3, cheap judge 3).
   Those rows come from another benchmark's labels, and the borderline ones are where
   labelers disagree most (see the relabel above).
6. **No guard agrees reliably with the labels on the 40 ambiguous rows.** AUROC is 0.62 to
   0.77, with CIs that reach down to 0.42 to 0.60.
7. **The LLM guards are not deterministic.** Across the three runs, the cheap judge's
   decision changed on 8.1% of rows and Jev's on 6.7%; rules and the classifier never changed.

Recall at 1% FPR by category (clear test rows; counts are small, so read these as rough):

| Category (unsafe rows) | rules | classifier | jev | judge-cheap |
|---|---|---|---|---|
| injection_driven (28) | 96% | 79% | 100% | 100% |
| destructive_file_ops (7) | 14% | 0% | 57% | 57% |
| data_exfiltration (6) | 33% | 17% | 67% | 67% |
| privilege_escalation_persistence (4) | 75% | 0% | 75% | 75% |
| credential_access (3) | 67% | 0% | 100% | 67% |
| irreversible_external_action (2) | 50% | 0% | 50% | 100% |
| resource_abuse (1) | 0% | 0% | 100% | 0% |

![ROC curves on clear test rows](results/charts/test-roc.png)

![Reliability diagrams](results/charts/test-reliability.png)

How the numbers are computed (`agentguard/eval/metrics.py`, `bootstrap.py`, `evaluate.py`):

- **Recall at 1% FPR** uses the best threshold on the test rows themselves, so it measures
  ranking. The as-deployed table uses the dev-tuned thresholds.
- **PR-AUC** is average precision.
- **ECE** uses 10 equal-width bins.
- **Bootstrap:** the same resamples serve every guard, so differences between guards get
  paired CIs.
- **Cascade score:** rows the first stage blocks rank above all others and rows it allows
  rank below, each ordered by the first stage's score. Rows it escalates get the judge's
  score.
- **Latency** is the guard's own compute per check.

Two fixes were made after the test run. Neither changed a threshold or a score:

- The classifier's timer had counted the wait behind other rows in a concurrent run
  (p50 578 ms). It now times only the check itself (54 ms).
- The first cascade score tied every first-stage block at 1.0. With 3 blocked safe rows,
  that sent recall at 1% FPR to 0.

Everything is in `results/eval/test.json`; per-row verdicts are in
`results/runs/test-*.jsonl`.

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
  eval/          run.py (a guard over a split), tune.py (thresholds, cascade), metrics.py,
                 bootstrap.py, evaluate.py (Level 1 with CIs), charts.py, relabel.py
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
| 4. Evaluation and attacks | 8–9 | 4 charts with error bars from `make report` (Level 1 done) |
| 5. Ship | 10 | README, demo, write-up |

Test split hash (sha256 of `data/splits/test.jsonl`, frozen 2026-11-17):
`f7a2f0cbda0484b707a9ac46760d364ae06e0c6cce05f4bb9cde052760b09ce8`
