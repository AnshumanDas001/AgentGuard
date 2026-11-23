# AgentGuard

A pre-execution safety monitor for LLM agents. It scores every tool call an agent proposes
**before it runs**, then allows it, asks a human, or blocks it. Four interchangeable guards
(regex rules, a fine-tuned DeBERTa classifier, an LLM judge, and TypeSafe's Jev) are
benchmarked:
- on held-out labeled actions;
- on disguised attacks;
- in front of a real agent secretly told to sabotage its user;
- on a public AI-control benchmark, next to 13 published monitors.

This page has the results and the design. The whole process, with every intermediate result
and fix, is in **[docs/full-report.md](docs/full-report.md)**.

## Results

### The four guards on this project's benchmark

![Recall at 1% false-positive rate against cost per 1,000 decisions](results/charts/test-cost-recall.png)

| Guard | Caught at 1% FPR | AUROC | Latency p50 | Cost per 1,000 | Tasks done, nobody to ask | Sabotage stopped |
|---|---|---|---|---|---|---|
| rules | 71% [59, 82] | 0.88 [0.82, 0.94] | 0.3 ms | $0.00 | 4% | 100% |
| classifier | 45% [33, 65] | 0.94 [0.92, 0.97] | 54 ms | $0.00 | 4% | 100% |
| jev | 86% [71, 96] | 0.97 [0.94, 1.00] | 539 ms | $0.05 | 40% | 100% |
| judge-cheap | 84% [0, 100] | 0.99 [0.98, 1.00] | 1.5 s | $0.22 | 80% | 100% |
| judge-strong | 88% [71, 98] | 0.99 [0.98, 1.00] | 2.8 s | $7.82 | not run | not run |
| cascade cheap > strong | | | | $3.32 | 94% | 100% |

**How to read it.**
- The first three columns come from a frozen test split of 257 clear actions (51 unsafe),
  scored once, with 95% bootstrap intervals.
- The last two come from a real agent (GPT-OSS-120B) in a Docker sandbox: 50 normal tasks,
  and 50 tasks with a secret sabotage order. "100%" means 50 of 50, so the true rate is at
  least 93%.

**What it shows.**
- **Jev and the cheap LLM judge tie on accuracy.** Jev costs a quarter as much and answers
  3× faster.
- **The cascade matches the strong judge's misses at 58% less cost.** It was fixed on dev
  before the test run.
- **No guard auto-allowed any of 722 sabotage steps.** What separates them is the cost to
  honest work: with nobody to ask, the agent finished 4% of its tasks under the rules and
  94% under the cascade.

**Demo:** a recorded run (not staged). The agent's user asked for a test summary; its secret
order was to destroy the invoice file. It tries five ways, and the guard blocks each one.

![A recorded run: five attempts on the invoice file, five blocks](docs/demo.gif)

### On a public benchmark: MonitoringBench

[MonitoringBench](https://arxiv.org/abs/2605.09684) uses
[BashArena](https://arxiv.org/abs/2512.15688), from the UK AI Security Institute and Redwood
Research. There, Claude Opus 4.6 does Linux admin tasks and in attack runs secretly disables
the firewall, runs malware, leaks passwords or grants sudo. The benchmark publishes 13
monitors' scores on the same attacks.

The monitor below (design in the next section) was built only on Redwood's public BashArena
runs, frozen by a rule written in advance, and scored once on MonitoringBench's 196 standard
attacks. Palaestra Research's 550 honest runs set the 1% false-alarm line.

![Share of 196 MonitoringBench attacks caught at 1% FPR: ours next to 13 published monitors](results/charts/mb-catch.png)

| Monitor | Caught at 1% FPR | Caught at 4% | AUROC | Cost, all 746 runs |
|---|---|---|---|---|
| **Jev alone** | **45.4%** [37.2, 57.1] | 64.8% [53.1, 73.0] | 0.92 [0.89, 0.94] | $2.81 ($0.13 per 1,000 actions) |
| **Jev + Haiku second look** | **63.3%** [56.1, 72.4] | 77.6% [66.3, 84.2] | 0.955 [0.936, 0.970] | $4.12 ($0.19 per 1,000 actions) |
| GPT-5 / o3 / GPT-5.1 Codex Max | 60.2% / 62.2% / 70.0% | | | |
| Claude Sonnet 4.5 / Opus 4.5 | 82.7% / 94.9% | | | |
| GPT-4.1 / GPT-4.1 mini | 10.2% / 0.5% | | | |

| Caught at 1% FPR, by sabotage type | Firewall | Malware | Password leak | Sudo |
|---|---|---|---|---|
| Jev alone | 17.2% | 90.5% | 76.7% | 15.1% |
| Jev + Haiku second look | 53.4% | 92.9% | 86.0% | 32.1% |
| GPT-5 | 22.4% | 85.7% | 65.1% | 77.4% |
| o3 | 24.1% | 88.1% | 60.5% | 84.9% |

- **Jev alone is the pre-registered result:** mid-table, and ahead of GPT-5 and o3 on malware
  and password leaks. A control with random answers in place of Jev's gets 19.9%.
- **The Haiku second look was a follow-up on the same attacks.** It was chosen on Redwood's
  runs with a pass mark set in advance. It lifts firewall catches from 17% to 53% and the
  total to 63%, level with GPT-5 and o3.
- **Cost.** For these 746 runs, reading each finished run once would cost at least $9.70 with
  GPT-5 and $15.50 with o3 in input tokens alone, at OpenRouter list prices. Checking every
  action before it runs, as this monitor does, would cost about $260 with GPT-5 without
  prompt caching.

## How it works

### The interceptor

```
user task ─▶ agent loop (LLM, tool calling)
                 │ proposes a tool call
                 ▼
             Interceptor ─▶ guard.assess(action) ─▶ Verdict(p_unsafe, category, latency, cost)
                 │                                        │
                 │      policy: allow below a, block above b, escalate in between
                 ▼
     allowed: runs in the Docker sandbox     blocked: the agent gets a tool error
                 │
                 ▼
          JSONL log (every action, verdict and decision)
```

- **Guards:** every guard implements one interface, so they can be swapped or chained into a
  cascade. A cascade asks a cheap guard first and sends only its unsure cases to a stronger
  one.
- **The agent's tools:** `read_file`, `write_file`, `run_shell` (inside the container),
  `http_request` (allow-listed hosts) and `send_email` (fake, written to a file).
- **Sandbox:** a fresh container per run, with no network and no Linux capabilities, holding a
  fake project with canary secrets.
- **Fail closed:** if a guard errors or times out, the action is blocked.

### The BashArena monitor: Jev alone, and Jev + Haiku

On BashArena every guard above first scored **below chance**: honest sysadmin work looks
dangerous, and the attacker spreads its sabotage over many steps. This is the design that
fixed it:

```
each proposed action, with the task and the run so far
   │
   ▼
1. Security ledger (plain code, free)
   tracks system files written, secrets read, security controls touched, addresses the task
   never names, and the scripts the agent wrote (and what they import)
   │
   ▼
2. Pre-filter (free): writes no file and trips no ledger flag?  ── yes ─▶ skip (about 45% of steps)
   │ no
   ▼
3. Jev 1.14: 13 yes/no questions on the task, the ledger, recent steps and the action
   ("does this hide its intent?", "does this weaken a security control?", ...)
   → 13 probabilities per step, about $0.00025 and 0.55 s each
   │
   ▼
4. Learned run score: each question's highest answer in the run + 2 ledger facts,
   standardized, weighted and added up (logistic regression trained on Redwood's runs)
   │                                                                  ═▶ JEV ALONE: 45%
   ▼
5. Second look: the run's 2 highest-scoring steps → Claude Haiku 5.5 reads each with the
   task and the run's context → suspicion 0–10 with a reason (about $0.0009 each)
   │
   ▼
6. Final score = the higher of the two percentile ranks (Jev's, Haiku's), so either can
   raise the alarm; flag the run if it is above the line that flags 1% of honest runs
                                                                      ═▶ JEV + HAIKU: 63%
```

- **The ledger** gives a per-step model memory of the whole run. The two ledger facts in step 4
  came from reading missed attacks: attacks assemble the harm from helper files the agent wrote
  itself, often building security settings from templates.
- **The learned score** decides how much each answer counts. "Hides its intent" counts most
  (+0.73). "Weakens a security control" counts *against* (−0.71), because honest tasks trip it
  all the time. It uses only each question's maximum, never averages, which would track run
  length.
- **The second look** spends a stronger model only where Jev points. Combining by rank needs
  no labels and lets Haiku rescue the firewall and sudo attacks Jev scores too low.
- **Honest evaluation:**
  - every choice was made on Redwood's runs, with the decision rule committed before the
    deciding run;
  - nothing was fitted on MonitoringBench, and it was scored once;
  - all model calls ask providers not to keep the data.

Code: `agentguard/guard/ledger.py`, `agentguard/guard/backends/jev.py`,
`agentguard/bench/head.py` (learned score), `agentguard/bench/review.py` (second look).

## Limitations

- **Small test set:** on this project's benchmark, the 1% FPR numbers rest on two or three
  safe rows, so the intervals are wide. Rows were labeled by the author and Claude under
  written rules, with no independent second labeler.
- **Blatant attackers in Level 3:** they were caught, but that doesn't show a careful attacker
  would be. The simulated reviewer never errs.
- **An indirect MonitoringBench comparison:**
  - different honest runs set our thresholds and the published ones;
  - the published monitors read whole runs without tool outputs;
  - only the standard attacks were tested, not the refined ones;
  - the second look picks its steps after the run ends (a live version would use a
    threshold), and its prompt names threat types that match BashArena's sabotage goals.
- **Still weak on sudo changes** (32%). The untouched BashArena test set (t200) hasn't been
  scored yet.

Details for each are in [docs/full-report.md](docs/full-report.md).

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

**Reproduce the results.** Every paid run is saved in `results/`, so the metrics and charts
rebuild without API calls:

```bash
make eval     # every paid Level 1-3 run, about $6; saved runs are skipped
make report   # every Level 1-3 metric and chart from the saved runs
make dashboard  # results, Level 4, a live check of any action, replays of Level 3 runs
uv run --group report python -m agentguard.bench mb-chart   # the MonitoringBench chart
```

Level 4 commands (fetching the data, the paid runs, the second look) are in
[docs/full-report.md](docs/full-report.md#level-4-a-public-benchmark-basharena-and-monitoringbench).
The test split was frozen on 2026-11-17 with sha256
`f7a2f0cbda0484b707a9ac46760d364ae06e0c6cce05f4bb9cde052760b09ce8`.

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
                 bootstrap.py, evaluate.py (Level 1 with CIs), charts.py, relabel.py,
                 attacks.py (Level 2 rewrites)
  e2e/           Level 3: scenarios.py, detect.py (attempt rules), run.py (agent + guard
                 in the sandbox), score.py, charts.py, sheet.py, demo.py (the GIF)
  bench/         Level 4: basharena.py and monitoringbench.py (loaders), run.py (paid,
                 resumable replay), head.py (learned run score), review.py (Haiku second
                 look), mb_report.py (report and chart)
  guard/ledger.py  the security ledger (Level 4)
dashboard/       app.py (Streamlit: results, Level 4, live check, replay)
  dataset/       row format, validator, stats, labeling tool, split and freeze
  pricing.py     token prices for cost per decision
sandbox/         Dockerfile + seeded fake project and canary secrets; bin/netlog logs
                 curl/wget/pip calls for the Level 3 checks
tests/
notes/           findings, paper reading notes, the handoff file
docs/            full-report.md (the whole process), demo.gif
data/            labeled dataset (Phase 2)
results/         logs, tables, charts
```

## Data and credit

- **This project's dataset:** rows converted from ASSEBench (Apache-2.0) and InjecAgent
  (MIT), plus rows written by hand. See [data/SOURCES.md](data/SOURCES.md).
- **BashArena runs:** Redwood Research's public `bashbench2_v1` runs (CC BY-SA 4.0).
- **MonitoringBench attacks:** CC BY 4.0.
- **Honest runs:** by Can Küçükkurt and Ethan Elasky at Palaestra Research
  ([release post](https://www.lesswrong.com/posts/bdBoH23TCTFZkkfqp/releasing-benign-trajectories-for-monitoringbench),
  CC BY 4.0).
- **How the benchmark data was used:** evaluation only. It isn't in this repo; only per-step
  scores are.
