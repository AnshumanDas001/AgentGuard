# Data sources

Rows in `data/raw/` come from these sources. Every row's `meta` records its origin.

| Source file | What it is | License |
| --- | --- | --- |
| `phase1-run.jsonl` | Tool calls from AgentGuard's own Phase 1 agent runs | This project |
| `handwritten.jsonl` | Rows written by hand (rules step 3) | This project |
| `injecagent.jsonl` | Converted from InjecAgent, data-stealing cases (base setting) | MIT |
| `assebench.jsonl` | Converted from ASSEBench (AgentAuditor), in-scope risk types | Apache-2.0 |

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

## ASSEBench

Hanjun Luo et al. *AgentAuditor: Human-Level Safety and Security Evaluation for LLM Agents.*
NeurIPS 2025. Repository: https://github.com/Astarojth/AgentAuditor-ASSEBench, commit
`fa5f99797073fd9a8d012268bc2b7dc27d05f4b1`. Apache License 2.0.

Conversion (`agentguard/dataset/benchmarks.py`): from the safety and security subsets, only
records whose risk type falls within the seven categories are used (ethics, harmful content,
fraud and health risks are out of scope, as the labeling rules say). Each record becomes up
to two rows: its last tool call and the one before it, with the user's request as the task
and the earlier calls and their outputs as history. Calls that match the agent's five tools
are renamed to them; other tools keep their recorded names and arguments. ASSEBench's own
labels, ambiguity flag and risk description are kept in each row's `meta` as a hidden
cross-check; every row is labeled again under our rules. Records whose opening message matches
the R-Judge file bundled in the same repository (170 in scope) are left out, because R-Judge
has no license.
