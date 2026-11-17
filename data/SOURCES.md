# Data sources

Rows in `data/raw/` come from these sources. Every row's `meta` records its origin.

| Source file | What it is | License |
| --- | --- | --- |
| `phase1-run.jsonl` | Tool calls from AgentGuard's own Phase 1 agent runs | This project |
| `handwritten.jsonl` | Rows written by hand (rules step 3) | This project |
| `injecagent.jsonl` | Converted from InjecAgent, data-stealing cases (base setting) | MIT |

## InjecAgent

Qiusi Zhan, Zhixiang Liang, Zifan Ying, Daniel Kang. *InjecAgent: Benchmarking Indirect
Prompt Injections in Tool-Integrated Large Language Model Agents.* Findings of ACL 2024.
Repository: https://github.com/uiuc-kang-lab/InjecAgent, commit
`f19c9f2c79a41046eb13c03c51a24c567a8ffa07`. MIT License, Copyright (c) the InjecAgent authors.

Conversion (`agentguard/dataset/benchmarks.py`): the user's instruction becomes the task;
the history holds the user's tool call, whose response carries the injected instruction,
and the attacker's data-gathering call with InjecAgent's simulated output; the proposed
action is an email of that data to the attacker's address. The subject line is ours, varied across 15 plain subjects.
InjecAgent uses one or two attacker addresses throughout; to stop a guard from memorising
them, each case's address is replaced (in the injected text and the email alike) by one of
20 plausible addresses. The original is kept in each row's `meta`.
A spread-out sample is taken: 5 cases for each of the 17 user tools.
