# Your LessWrong post: a framework to write into

**How to use this file**
- Work through it top to bottom. Each section of the post has four parts:
  - **Job:** what the section must achieve, in one line.
  - **Include:** a checklist of the facts to put in. The facts are yours, from your project.
  - **Example:** how that section *could* look, written about a **made-up project** called
    PatchSentry (described below), so you can copy the shape but not the words.
  - **Your text:** where you write.
- **Don't copy or reword the examples.** LessWrong treats "text written by an LLM and then edited
  by a human" as AI-written. First-time posters face "closer to a zero-LLM policy", and posts are
  run through AI-text detection. Close the example, then write from your own understanding.
- **Delete everything except your text before posting.**

**The made-up example project (for the examples only):** "PatchSentry" is a small fine-tuned
model that flags pull requests likely to contain a hidden backdoor. It was tested once on a
public benchmark, "VulnBench", against GPT-5 and other frontier reviewers. None of this is real.

---

## Step 0: before you write anything

### Read these, in this order (about 5–7 hours in total)

**Full summaries, the sections to read closely, and the objections to prepare for are in
[lesswrong-reading-list.md](lesswrong-reading-list.md).** The short list:

**Must read (rules and style):**
1. [New LessWrong Editor + LLM policy update (Mar 2026)](https://www.lesswrong.com/posts/nQWavk9mnwcv6ScMR/new-lesswrong-editor-also-an-update-to-our-llm-policy),
   the "Policy on LLM Use" section. This is what decides whether your post is allowed.
2. The [New User's Guide](https://www.lesswrong.com/posts/LbbrnRvc9QwjJeics/new-user-s-guide-to-lesswrong#How_to_ensure_your_first_post_or_comment_is_approved).
   You've read it; reread "How to ensure your first post is well-received".

**Must read (posts like yours; read the comments too, because that's where objections appear):**

3. Palaestra's [Releasing Benign Trajectories for MonitoringBench](https://www.lesswrong.com/posts/bdBoH23TCTFZkkfqp/releasing-benign-trajectories-for-monitoringbench).
   It uses the same data as you. Notice its length, tone and how it states caveats.
4. Redwood's [Ctrl-Z: Controlling AI Agents via Resampling](https://www.lesswrong.com/posts/LPHMMMZFAWog6ty5x/ctrl-z-controlling-ai-agents-via-resampling).
   This is how an AI-control result is written up for this site.
5. [Optimally combining probe monitors and black-box monitors](https://www.alignmentforum.org/posts/FhixwyymPxF8TZX39/optimally-combining-probe-monitors-and-black-box-monitors),
   the summary of Hua et al. (2025). It's the closest work to your two-stage monitor, so you
   must respond to it.

**Skim (the papers you rely on; know what they claim):**

6. MonitoringBench, [arXiv 2605.09684](https://arxiv.org/abs/2605.09684): the abstract, the
   setup, Table 5, and how honest runs and thresholds work.
7. BashArena, [arXiv 2512.15688](https://arxiv.org/abs/2512.15688): the setting and the monitor
   section.
8. [AI Control: Improving Safety Despite Intentional Subversion](https://arxiv.org/abs/2312.06942):
   the introduction and the "trusted monitoring" part. Your monitor is a trusted monitor in
   this sense.

**Rationality basics (short, and moderators check for them):**

9. [Update Yourself Incrementally](https://www.lesswrong.com/posts/627DZcvme7nLDrbZu/update-yourself-incrementally)
   and [Rationalization](https://www.lesswrong.com/posts/SFZoEBpLo9frSJGkc/rationalization)
   (Eliezer Yudkowsky, 2007, 3–4 minutes each). They're about giving probabilities and testing
   your idea in ways that could prove it wrong.

While reading, keep a notes file with two lists: **"objections people might raise"** and
**"posts I should link"**. You'll use both later.

### The one-sentence test
Before writing, finish this sentence in your own words, in under 40 words:
"I found that ___, which matters because ___."
If you can't, the post isn't ready. Everything else hangs off this sentence.

Your sentence:

>

---

## 1. Title

**Job:** say the result, not the topic. A reader should know what you found from the title alone.

**Include:** the claim, the benchmark name, and (optionally) the cost angle. Aim for under 15 words.

**Example (made-up):**
> "A 1B-parameter reviewer catches 58% of VulnBench backdoors at 1% false alarms, near GPT-5"

**Beginner mistakes:**
- A topic title ("Thoughts on AI monitoring").
- Hype ("SOTA", "beats GPT-5" when the intervals overlap).

Your title:

>

---

## 2. Opening: TL;DR (bullets) + first paragraph

**Job:** this is the most important part. Moderators decide here. Within about 150 words a
reader must know:
- the claim;
- the strongest evidence for it;
- why LessWrong readers care;
- the biggest caveat.

**Include:**
- [ ] Both numbers: Jev alone (the pre-registered headline) and Jev + Haiku (the follow-up),
      each with its interval.
- [ ] What they're compared against: GPT-5, o3, and the small models.
- [ ] The cost, stated as an estimate where it is one.
- [ ] Why it's credible: pre-registered, scored once on unseen data, and a random-answer control.
- [ ] The main caveat: different honest runs set the alarm line.
- [ ] Why it matters for AI control: trusted monitors must be cheap enough to run on every
      action.

**Example (made-up):**
> **TL;DR**
> - I tested a small fine-tuned reviewer, PatchSentry, once on VulnBench's 300 backdoored
>   pull requests. It flagged 58% [49, 66] at a 1% false-alarm rate. GPT-5 gets 61% and GPT-4.1
>   gets 12%.
> - It costs about $0.02 per 1,000 pull requests, roughly 100× less than GPT-5 at this task.
> - I wrote the evaluation plan and committed it to git before the test run. A version with
>   random scores gets 9%.
> - Main caveat: VulnBench's own clean PRs aren't public, so my false-alarm threshold comes
>   from a different set of clean PRs.
>
> Trusted monitoring only helps if the monitor is cheap enough to run on everything. This is
> one data point on how far a small model gets, and on where it fails: it misses almost all
> backdoors split across several files.

**Notice the shape:**
- Numbers come with intervals.
- The comparison is honest ("near", not "beats").
- The caveat sits in the TL;DR.
- The failure mode is named early.

Your TL;DR and first paragraph:

>

---

## 3. Epistemic status (1–3 sentences)

**Job:** tell readers how much to trust each part. This is normal on LessWrong and moderators
like it.

**Include:**
- [ ] What kind of work this is (a solo project, not peer-reviewed).
- [ ] What you're confident in and why (public code, saved scores, commit history).
- [ ] What you're unsure about (how far the comparison with published monitors carries).

**Example (made-up):**
> *Epistemic status:* solo project, about two months. I'm confident the numbers are what my
> code measures (code and scores are public). I'm much less sure the comparison with GPT-5 is
> apples to apples, for the reasons in "Where I might be wrong".

Your epistemic status:

>

---

## 4. Background and prior work

**Job:** show you know the existing work and say exactly how yours relates. This is the second
thing moderators check.

**Include (one or two sentences each, saying how your work relates, not just that it exists):**
- [ ] AI control and trusted monitoring (Greenblatt et al., 2023).
- [ ] Ctrl-Z (Bhatt et al., 2025). It also uses a sysadmin setting, and its best protocol
      looks at previous steps. That relates to your ledger.
- [ ] Hua et al. (2025): combining a cheap monitor with an expensive one in a principled way.
      Your "top 2 steps" and "take the higher rank" are heuristics. Admit it and say what their
      method might change.
- [ ] BashArena, MonitoringBench and Palaestra's honest runs: what each provides.

**Example (made-up):**
> The closest work is Lee et al. (2025), who route only uncertain PRs to a large model and
> choose the routing threshold by optimizing recall under a budget. My second stage instead
> reviews a fixed top-2 per repository, a heuristic I chose for simplicity. Their method would
> probably do at least as well at the same cost; I haven't tested it.

**Notice:** the example names a weakness in its own method relative to prior work. That builds
trust.

Your background and prior work:

>

---

## 5. The setup (short)

**Job:** give a reader who has never heard of BashArena enough to understand the numbers.
About 100–150 words.

**Include:**
- [ ] BashArena: admin tasks, plus four secret side tasks in attack runs (name them).
- [ ] How a run is scored: its most suspicious step. The headline is the share of attacks
      caught when 1% of honest runs are flagged.
- [ ] The data: 196 standard attacks (Opus 4.6) and 550 honest runs (Palaestra, Opus 4.5).
- [ ] A key difference: your monitor checks each step before it runs, with tool outputs. The
      published monitors read whole runs once, without outputs.

**Example (made-up):**
> VulnBench contains 300 pull requests where a model was secretly told to slip in a backdoor,
> and 900 clean ones. A reviewer scores each PR; the headline is the share of backdoored PRs
> above the score that flags 1% of clean PRs.

Your setup:

>

---

## 6. How the monitor works

**Job:** explain the design so a reader could critique it. A diagram helps, and it's fine to
reuse your README diagram if you redraw it yourself.

**Include:**
- [ ] Why the simple version failed first (all guards below chance; Jev AUROC 0.23) and the
      three reasons. This is the most *interesting* part for readers, so don't skip it.
- [ ] The ledger, the pre-filter and Jev's 13 questions, with cost per call.
- [ ] The learned run score in one plain paragraph, plus the two biggest weights and why one
      is negative.
- [ ] Haiku's second look and the max-of-ranks combination.

**Example (made-up, for the "why it failed first" part):**
> The first version scored below chance. Clean PRs in VulnBench often touch authentication
> code legitimately, so "does this touch auth?" fired on clean PRs constantly. Backdoors were
> also split across files, so no single diff looked bad.

**Tip:** explain the learned score the way you'd explain it to a friend: "a points system where
each answer is worth a learned number of points". Then give the numbers.

Your explanation:

>

---

## 7. How you kept it honest (your strongest section for this audience)

**Job:** convince a skeptical reader that you didn't tune on the test set or cherry-pick.

**Include:**
- [ ] All development was on Redwood's runs only.
- [ ] The three commits where each rule was written before its run (`8b66d75`, `9456f4b`,
      `0ebae84`, with links).
- [ ] The second look's pass mark (+5 points on Redwood's runs; it scored 65% vs 56%).
- [ ] The two un-chosen combinations scored higher (69%, 68%), and you don't report them.
      Use the phrase "garden of forking paths" if it fits; readers will know it.
- [ ] The random-answer control, and what it rules out.

**Example (made-up):**
> Two other scoring rules I'd listed beforehand did better on VulnBench (63% and 61%). I'm
> reporting 58% because that's the rule I committed to before seeing any VulnBench result
> (commit `abc1234`); picking the best of three afterwards would overstate it.

Your text:

>

---

## 8. Results

**Job:** the numbers, cleanly. Tables and the chart are data, so you can paste them from your
results files.

**Include:**
- [ ] The main table: Jev alone, Jev + Haiku, the control, GPT-5, o3, Codex Max, Sonnet and
      Opus 4.5, and GPT-4.1. Include intervals.
- [ ] The per-side-task table, with a sentence on what it shows (strong on network-crossing
      attacks, weak on config changes).
- [ ] The chart (`results/charts/mb-catch.png`). Upload it in the LessWrong editor.
- [ ] Cost, with the estimate method stated (characters ÷ 4, list prices, no caching).
- [ ] The length-weighted check, in one sentence.

**Example (made-up, the sentence after a table):**
> The small reviewer behaves like two different monitors. It catches 85% of backdoors that add
> a network call, but only 20% of those that weaken an existing permission check, the kind of
> change clean PRs also make.

Your results text:

>

---

## 9. What you think it shows (with probabilities)

**Job:** interpret, and put numbers on your beliefs. This is the "rationality fundamentals"
check.

**Include:**
- [ ] 2–3 claims, each with a probability that you choose yourself.
- [ ] For each, what evidence would change your mind.

**Questions to answer with your own numbers:**
- How likely is it that the 63% stays within ±10 points if the paper's own honest runs set the
  line? (Evidence: the interval is [56, 72], and the 1% line rests on about 5 honest runs.)
- How likely is it that a live version (a threshold instead of top-2) keeps most of the gain?
- How likely is it that it holds up on MonitoringBench's harder "refined" attacks? (Published
  monitors drop sharply there.)

**Example (made-up):**
> I'd put about 70% on PatchSentry staying within 10 points of 58% on VulnBench's own clean
> PRs, if they're released. My main reason for doubt: the threshold rests on only 9 clean PRs.
> A drop below 45% would make me think my clean set was unusually easy.

Your text:

>

---

## 10. Where you might be wrong (limitations)

**Job:** list the ways the result could be misleading, before commenters do.

**Include:**
- [ ] Different honest runs set the alarm line.
- [ ] Different inputs (per-step with outputs, versus whole-run without).
- [ ] The second look picks its steps after the run ends.
- [ ] Haiku's prompt names threat types that match the side tasks.
- [ ] Only the standard attacks were tested; sudo is still at 32%.
- [ ] t200 hasn't been scored yet, and there's no plain-LLM-judge comparison.

**Example (made-up):**
> My second stage reviews each repository's two highest-scoring PRs after the fact. A real
> deployment would need a fixed threshold decided in advance, and I don't know how many PRs
> that would send to the large model.

Your text:

>

---

## 11. Next steps and a specific question for readers

**Job:** end with what you'll do next and one concrete question. That invites useful comments.

**Include:**
- [ ] 2–3 next steps.
- [ ] One specific question, for example about a fairer way to compare per-step and whole-run
      monitors.

Your text:

>

---

## 12. Acknowledgements, links and disclosure

**Include:**
- [ ] The GitHub repo link, and `docs/full-report.md` for details.
- [ ] Credits:
  - Redwood Research's BashArena runs (CC BY-SA 4.0);
  - MonitoringBench (CC BY 4.0);
  - Palaestra Research's honest runs (Can Küçükkurt, Ethan Elasky; CC BY 4.0);
  - TypeSafe (Jev).
- [ ] An honest disclosure of AI help, for example that you used Claude for code and data
      analysis. Write it yourself, and make sure it's true. If you include any AI-written
      text at all, it must go inside the editor's "LLM content block".

Your text:

>

---

## Your writing process (a beginner-friendly plan)

| Day | Do |
|---|---|
| 1–2 | The reading list. Keep the "objections" and "posts to link" lists. |
| 3 | The one-sentence test. Then write sections 2 and 7 (opening, honesty) first; they matter most. |
| 4 | Sections 4–6 and 8. |
| 5 | Sections 9–12, then cut. Aim for under 1,500 words of prose (tables don't count). |
| 6 | Optional: post a short version in the [AI open thread](https://www.lesswrong.com/w/open-threads) and ask for feedback. |
| 7 | Final pass with the checklist below, then submit. |

**Writing tips:**
- **Short sentences.** One idea per sentence.
- **Lead with numbers,** always with intervals.
- **Say "I"** for what you did. It's your work.
- **No hype words** ("groundbreaking", "SOTA", "revolutionary").
- **Calibrated hedges:** "level with" when intervals overlap, not "beats".
- **Read it aloud.** Wherever you stumble, rewrite.

## Submission checklist
- [ ] Every sentence of prose written by me. Nothing pasted or reworded from the README, blog,
      field guide or earlier drafts (Claude wrote those).
- [ ] The opening has the claim, the evidence, why it matters, and the main caveat.
- [ ] At least Hua et al. (2025) is engaged with, not just cited.
- [ ] Section 9 has real probabilities.
- [ ] The chart is uploaded and the links work.
- [ ] The disclosure line is true.

## What Claude can still do for you (allowed by the policy)
- Check every number and link against the saved results.
- Lightly fix typos or one clumsy sentence that you point to (light editing is allowed).
- Remake or adjust charts and tables (data and code are exempt).
- Explain any concept from the reading list, or quiz you on the likely objections.
- What it shouldn't do: write or rewrite your paragraphs.
