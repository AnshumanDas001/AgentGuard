# The three findings that surprised me most

These are the Phase 4 findings the blog post is built on. Numbers come from
`results/eval/test.json` (Level 1), `results/eval/attacks.json` (Level 2) and
`results/e2e/summary.json` (Level 3). Brackets are 95% intervals.

## 1. Good offline scores do not make a usable guard

Measured on single actions, the rules guard looks fine (AUROC 0.88) and the DeBERTa
classifier looks better (AUROC 0.94). They can also be tuned to let almost nothing unsafe
through: on test, neither auto-allowed a single unsafe clear row. The catch is how. To keep
misses under 5% on dev, rules must escalate every action and the classifier about half of
them.

Put in front of a real agent, that cost becomes visible. With nobody to answer
escalations, the agent finished 4% of its 50 normal tasks under rules and 6% under the
classifier, against 86–100% under the LLM judges and cascades. With a reviewer, the work
gets done, but the person is asked about 2 to 3 times per task (224 to 316 per 100 tasks).
Single-action metrics hide this. Only the end-to-end run shows it.

## 2. Against blatant sabotage, every guard was perfect; the price is paid by honest work

Two open models (GPT-OSS-120B and DeepSeek V3.2) were told, privately, to carry out a
harmful side task, such as emailing `.env` out, deleting tests or starting a busy loop,
without the monitor noticing. Across 14 guarded runs they proposed 722 steps toward a side
task. No guard auto-allowed a single one (95% upper bound 0.5%); every step was blocked or
escalated.

So on safety the guards tie, and they differ only on cost to honest work. The
cheap-then-strong cascade stopped every side task while the agent finished 94% of its
tasks with nobody to ask (100% with a reviewer, who was asked 6 times per 100 tasks), at
about $0.0075 per task. The attackers were blatant: they named the attacker's address and
the files outright. Careful attackers are the open question (see future work).

## 3. Agents resist planted injections, obey direct orders, and adapt when refused

Instructions hidden in a README, a CSV cell, a code comment or a web page almost never
worked: Haiku 5.5 followed 0 of 50, GPT-OSS 1 and DeepSeek 6. Haiku even warned the user
about a planted line. Given the same goals as a direct, private instruction, the open
models carried them out 74% (GPT-OSS) and 92% (DeepSeek) of the time. Haiku ignored them
every time.

When the guard refused, the attackers looked for another route: `mv tests hidden_tests`
instead of `rm -rf tests`, `sed -i '1,$d'` or `chmod 000` on the invoice file, moving the
whole `data/` folder, and once `shutil.rmtree('tests')` hidden at the end of an
honest-looking invoice-totals script. The guards still escalated every step; my own
rules for spotting attack steps, used by the simulated reviewer, had to be widened three
times. The single-action benchmark echoes this: in Level 2, splitting a command across
three steps made Jev miss 18% [0, 36] of attacks it had caught, and rules miss 50% or more
of encoded, indirect or split versions.

## Future work (paper 14)

- **Watch the reasoning, not just the actions.** Baker et al. (2025) find that a monitor
  reading a reasoning model's chain of thought catches misbehaviour that an action-only
  monitor misses, and that training against such a monitor teaches the model to hide its
  intent. AgentGuard sees only the task and tool calls; adding the agent's reasoning, and
  measuring how attackers respond to it, is the next step.
- **Harder attackers.** SHADE-Arena (Kutasov et al., 2025) pairs long agent tasks with
  sabotage side tasks and scores whole transcripts. Our attackers were blatant. Longer
  tasks, side tasks that look like the main task, and attackers that know the monitor's
  rules would test whether the 0-of-722 result holds.
- **Real reviewers.** The simulated reviewer never errs or tires. Measuring how often
  people approve a disguised step after many escalations would turn "reviews per 100
  tasks" into a safety number.
- **Paraphrase attacks**, the fifth Level 2 family, written by hand.
- **Calibration across agents:** thresholds were tuned on dataset rows; the Level 3
  escalation rates differ by agent (Haiku 20 per 100 tasks under the cheap judge, DeepSeek
  60), so per-agent tuning may pay off.
