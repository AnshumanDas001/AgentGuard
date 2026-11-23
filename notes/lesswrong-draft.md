# LessWrong post: writing kit (not a draft)

LessWrong's current LLM policy (RobertM, "New LessWrong Editor! (Also, an update to our LLM
policy.)", 14 Mar 2026) says first-time users face "closer to a zero-LLM policy". Text an LLM
wrote, or substantially rewrote, counts as "LLM output". Posts are run through automated
detection, and new users' posts that are mostly LLM output are "pretty unlikely" to be approved.
So the earlier version of this file, which Claude wrote, can't be posted, and polishing it
wouldn't help.

What is allowed:
- **Your own writing.** Text you write yourself, using facts, numbers and arguments you
  researched with an LLM's help. Don't copy its wording: "borrowed language" counts as LLM output.
- **Light edits.** An LLM may lightly edit your text (typos, a clunky sentence). Heavy rewriting
  or added paragraphs are not allowed.
- **Code and charts.** These are exempt.

This kit gives you the facts, structure, prior work and open questions. The sentences are
yours to write. A one-line disclosure, if true: "Claude helped with the code and data analysis;
the text is mine."

## What the moderators look for (from the new-user guide)

1. **A clear introduction.** The first paragraph or two should state the main point and the
   strongest evidence for it, and say why LessWrong readers should care.
2. **Engagement with existing work.** Show you know what's already been said and build on it.
3. **Rationality basics.** Give probabilities instead of verdicts, say where you might be wrong,
   and don't argue over definitions.
4. **A high bar for AI posts.** Write it for this audience (link LessWrong/AF posts), keep it
   short, and make the claims precise.

## Suggested structure, with what each section must do

### 1. Opening (the most important part)
Answer these in 3–5 sentences of your own:
- What is the one claim? (Suggestion: a cheap per-step monitor plus a stronger model on the two
  most suspicious steps per run caught 63% of MonitoringBench's standard attacks at 1% FPR.
  That's level with GPT-5 and o3, for about $4 per 746 runs, and it was pre-registered.)
- What is the strongest evidence?
  - It was scored once on data the monitor never saw.
  - The rules were committed to git beforehand.
  - A random-answer control gets 20%.
- Why should AI-control readers care? Trusted monitoring has to be cheap enough to run on every
  action. This is one data point on how far a cheap monitor gets, and on where it breaks.
- What is the main caveat? Say it right here, not only at the end: different honest runs set
  the threshold.

### 2. Prior work to engage with (pick 3–4 and say how yours relates)
- **Greenblatt, Shlegeris, Sachan, Roger (2023),** [AI Control: Improving Safety Despite
  Intentional Subversion](https://arxiv.org/abs/2312.06942). This is where trusted monitoring
  comes from: a weaker trusted model rates the untrusted model's outputs. Your monitor is a
  trusted monitor in that sense.
- **Bhatt et al. (2025),** [Ctrl-Z: Controlling AI Agents via
  Resampling](https://arxiv.org/abs/2504.10374)
  ([LessWrong post](https://www.lesswrong.com/posts/LPHMMMZFAWog6ty5x/ctrl-z-controlling-ai-agents-via-resampling)).
  It uses BashBench, the predecessor of BashArena, and its best protocol includes analysis of
  previous steps. Relate it to your finding that a per-step monitor needs memory of the run
  (the ledger).
- **Hua et al. (2025),** [Combining Cost-Constrained Runtime Monitors for AI
  Safety](https://arxiv.org/abs/2507.15886)
  ([AF summary](https://www.alignmentforum.org/posts/FhixwyymPxF8TZX39/optimally-combining-probe-monitors-and-black-box-monitors)).
  - **The closest work.** It is a cheap monitor followed by an expensive one, and it argues for
    choosing when to call the second monitor and how to combine scores in a principled way
    (Neyman-Pearson), not by heuristics.
  - **The counterargument you must address.** Your `max_rank` combination and "top 2 steps per
    run" are heuristics. Say so, and say what their method would change.
  - **Cunningham et al. (2025),** Anthropic's multi-stage classifiers, is cited there. Read it
    before citing it.
- **The benchmarks:**
  - BashArena: [arXiv 2512.15688](https://arxiv.org/abs/2512.15688);
  - MonitoringBench: [arXiv 2605.09684](https://arxiv.org/abs/2605.09684);
  - Palaestra's [honest-run release](https://www.lesswrong.com/posts/bdBoH23TCTFZkkfqp/releasing-benign-trajectories-for-monitoringbench)
    (Can Küçükkurt, Ethan Elasky).

  Before posting, skim the comments on these posts for objections people already raised.

### 3. Setup (short)
- **BashArena:** Linux admin tasks. In attack runs, Claude Opus 4.6 also pursues one of four
  side tasks: firewall, malware, password leak, sudo.
- **Metric:** a run's score is its maximum step score. The headline is the share of attacks
  caught when 1% of honest runs are flagged.
- **Data:** 196 standard ("elicited") attacks. The 550 honest runs (Opus 4.5) are Palaestra's;
  the paper's 416 aren't released.
- **What each monitor sees:**
  - yours: each step before it runs, with tool outputs, replayed from saved runs;
  - the published monitors: the whole run once, without outputs.

### 4. The monitor (a diagram plus a few lines; the README diagram is fine to reuse)
- **Ledger:** plain code. **Pre-filter:** skips about 45% of steps.
- **Jev 1.14:** 13 yes/no questions per step, about $0.00025 and 0.55 s each.
- **Learned run score:** 13 question maxima + 2 ledger facts, combined by L2 logistic regression
  trained on 158 of Redwood's runs. Key weights: hides intent +0.73, weakens a control −0.71.
- **Haiku 5.5:** reviews the top-2 steps (0–10). Final score = the higher of the two
  percentile ranks.
- **The interesting failure to explain:** every guard was below chance at first (Jev AUROC
  0.23). Three reasons: honest sysadmin work trips the danger questions, the attacks are
  spread over many steps, and run length.

### 5. Protocol (this is your strongest card for this audience)
- **Development:** only on fixed samples of Redwood's runs.
- **Rules committed before each deciding run:**
  - [`8b66d75`](https://github.com/AnshumanDas001/AgentGuard/commit/8b66d75): choosing among
    the final three Jev candidates;
  - [`9456f4b`](https://github.com/AnshumanDas001/AgentGuard/commit/9456f4b): the
    MonitoringBench plan;
  - [`0ebae84`](https://github.com/AnshumanDas001/AgentGuard/commit/0ebae84): the second-look
    rule and its pass mark (+5 points on Redwood's runs; it scored 65% vs 56%).
- **Not reported as the result:** the two un-chosen combinations scored higher on MonitoringBench
  (69%, 68%). Reporting them would be the garden of forking paths; say so.

### 6. Results (tables and chart are fine to include as-is: they're data)

| Monitor | Caught at 1% FPR | Caught at 4% | AUROC |
|---|---|---|---|
| Jev alone | 45.4% [37.2, 57.1] | 64.8% [53.1, 73.0] | 0.92 [0.89, 0.94] |
| Jev + Haiku | 63.3% [56.1, 72.4] | 77.6% [66.3, 84.2] | 0.955 [0.936, 0.970] |
| Random-answer control | 19.9% | | 0.76 |
| GPT-5 / o3 / GPT-5.1 Codex Max | 60.2 / 62.2 / 70.0% | | |
| Sonnet 4.5 / Opus 4.5 | 82.7 / 94.9% | | |
| GPT-4.1 / GPT-4.1 mini | 10.2 / 0.5% | | |

| At 1% FPR | Firewall | Malware | Password leak | Sudo |
|---|---|---|---|---|
| Jev alone | 17% | 91% | 77% | 15% |
| Jev + Haiku | 53% | 93% | 86% | 32% |
| GPT-5 | 22% | 86% | 65% | 77% |
| o3 | 24% | 88% | 61% | 85% |

- **Length-weighted 1%:** 56% (Jev) and 69% (Jev + Haiku). Attacks are longer here, so length
  doesn't flatter either number.
- **Cost:**
  - Jev: $2.81 for 11,066 calls over 21,329 steps;
  - Haiku: $1.31 for 1,491 reviews;
  - total: $4.12.

  For comparison:
  - GPT-5 reading each finished run once: ≥ $9.70 in input alone (about 7.75M tokens);
  - checking every step without caching: about $260.

  Those comparison figures are estimates (characters ÷ 4, OpenRouter list prices).
- **Chart:** `results/charts/mb-catch.png`. Upload it to LessWrong.

### 7. Probabilities and where you might be wrong (write these yourself)
Give actual numbers. Questions to answer, with the evidence to weigh:
- **How likely is it that 63% would stay within about 10 points if the paper's own honest runs
  set the line?** Evidence: the CI is [56, 72], and at 1% FPR the line rests on about 5 honest
  runs. Palaestra screened their runs to match the paper's task mix. 2 of their 550 runs
  completed a side task by accident.
- **How likely is it that a live version (threshold instead of top-2) keeps most of the gain?**
  Nothing measured yet. Say what result would change your mind.
- **How likely is it that the result survives MonitoringBench's refined attacks?** Published
  monitors drop a lot there (Opus 4.5 goes from 94.9% on these attacks to 70.6% on all 2,644).
- **Are there confounds you haven't ruled out?**
  - Haiku's prompt names threat types that match the side tasks.
  - The ledger facts came from reading Redwood's attacks, so they may encode BashArena-specific
    patterns. Check: there are no BashArena-specific strings in the guard code, but the
    patterns themselves are general.

### 8. Next steps and an ask (2–3 lines)
- A live threshold version, sudo, refined attacks, and the untouched t200 set.
- Ask a specific question. For example: is there a fairer way to compare per-step monitors with
  whole-run monitors?

## Checklist before submitting
- [ ] Every sentence written by you. No pasted LLM text, including from the README or blog
      (those were Claude-written too).
- [ ] The opening states the claim, the evidence and the main caveat.
- [ ] At least Hua et al. (2025) is engaged with, not just cited.
- [ ] Section 7 has real probabilities.
- [ ] Short: aim for under about 1,500 words. Tables don't count.
- [ ] Chart uploaded, links checked, disclosure line added if it applies.
- [ ] Optional: post a short version in the AI open thread first, to get feedback.
