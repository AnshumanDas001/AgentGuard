# Reading list for your LessWrong post

Links, what each piece says, and what to look for while reading. Read in this order: about
5–7 hours in total. Summaries were checked against the pages on 2026-11-24; anything marked
*(unverified)* wasn't read directly, so open it yourself before citing it.

While you read, keep two lists in a notes file:
- **objections people might raise** about your result;
- **posts I should link.**

---

## A. The rules (read first, about 30 minutes)

### 1. New LessWrong Editor! (Also, an update to our LLM policy.)
- **Link:** https://www.lesswrong.com/posts/nQWavk9mnwcv6ScMR/new-lesswrong-editor-also-an-update-to-our-llm-policy
- **Author, date, length:** RobertM, 14 Mar 2026, 6 min. Read only the "Policy on LLM Use" section.
- **What it says:**
  - First-time users face "closer to a zero-LLM policy".
  - "LLM output" covers three kinds of text: written by an LLM; written by a human then
    *substantially* edited by an LLM; and written by an LLM then edited by a human.
  - Not LLM output: human text that an LLM only *lightly* edited, and facts or arguments you
    researched with LLM help, *as long as you don't borrow its wording*. Code is exempt.
  - AI-written text must go in the editor's "LLM content blocks". A new user's post that is
    mostly such blocks is "pretty unlikely" to be approved.
  - Posts are checked by automatic AI-text detection, now for all users.
- **For you:** write every sentence yourself. Claude can fix typos, check numbers and make
  charts.

### 2. New User's Guide to LessWrong
- **Link:** https://www.lesswrong.com/posts/LbbrnRvc9QwjJeics/new-user-s-guide-to-lesswrong
- **Author, date:** Ruby, 17 May 2023, 14 min. You've read it. Reread "How to ensure your
  first post or comment is well-received".
- **The four things moderators check:**
  - a clear intro with the main point;
  - engaging existing arguments;
  - rationality basics;
  - a high bar for AI posts.

---

## B. Posts like yours (about 1.5 hours; read the comments too)

### 3. Releasing Benign Trajectories for MonitoringBench (Palaestra Research)
- **Link:** https://www.lesswrong.com/posts/bdBoH23TCTFZkkfqp/releasing-benign-trajectories-for-monitoringbench
- **Authors, date, length:** Can Küçükkurt and Ethan Elasky, 2 Sep 2026 (updated
  10 Nov 2026), 5 min. No comments yet.
- **What it says:**
  - MonitoringBench released 2,644 attack runs but no honest runs. Without honest runs you can't
    set a false-alarm threshold, so the authors made and released 550.
  - The runs were generated with Claude Opus 4.5 on the same 116 BashArena tasks, with task
    frequencies matched to 550 attack runs.
  - **Fairness screening:** a frontier model graded every honest run with MonitoringBench's own
    grading prompt. Runs scoring 7 or more were replaced. 12 of 550 were dropped: 9 used a
    sensitive API key, and 3 installed packages from unauthorized addresses.
  - **Controls they report:**
    - honest runs average about 27 steps, close to the attacks;
    - honest runs are longer in characters;
    - the final "submit" step was removed;
    - tool names were normalized;
    - parallel tool calls were off.
  - They say the set is meant for low-false-alarm, more expensive monitoring, not cheap bulk
    monitoring.
- **For you:**
  - **This is the data that sets your 1% line, so you must cite it.** Their screening means a
    few borderline honest runs were removed. That makes your false-alarm line a bit easier
    than raw honest traffic would. Mention it.
  - **Style to copy:** a bold TL;DR first, question headers ("What is MonitoringBench?"), and a
    "Things we control for" section where each caveat comes with what was done about it.
  - **A lesson:** a careful reader found that a few of their numbers don't add up between text
    and tables. Cross-check yours.

### 4. Ctrl-Z: Controlling AI Agents via Resampling (Redwood Research)
- **Link:** https://www.lesswrong.com/posts/LPHMMMZFAWog6ty5x/ctrl-z-controlling-ai-agents-via-resampling
  (paper: https://arxiv.org/abs/2504.10374)
- **Authors, date, length:** Aryan Bhatt, Buck Shlegeris, Adam Kaufman, Tyler Tracy and
  others, 16 Apr 2025, 24 min.
- **What it says:**
  - **Setting:** BashBench, the predecessor of BashArena: 257 multi-step sysadmin tasks. The
    attacker (GPT-4o mini, using mostly human-designed strategies) tries to download and run a
    dummy "malware" file.
  - **The best attack** spreads short malicious commands over about 10 steps, among innocent
    code. That's the same "spread out" problem you hit.
  - **Main idea, resampling:** when an action looks suspicious, ask the model for a fresh one.
    An attacker's resamples tend to stay suspicious, so this both blocks and incriminates.
  - **Result:** the best protocol (resampling plus analysis of earlier steps) cut attack
    success from 58% to 7%, at a 5% cost to honest performance.
  - **"Important Limitations" section:**
    - a 15-step limit pushes attackers to act early;
    - the attacker is weak;
    - the setting got "somewhat gamified".
- **For you:**
  - **Relate it to your ledger.** Their best protocol also looks at earlier steps, which
    supports your finding that a per-step monitor needs memory of the run.
  - **Style to copy:** it lists required background reading up front, defines terms early,
    gives every figure a caption that says what to notice, and has a dedicated "Important
    Limitations" list where each item says *why* it matters.

### 5. Optimally Combining Probe Monitors and Black Box Monitors
- **Link:** https://www.alignmentforum.org/posts/FhixwyymPxF8TZX39/optimally-combining-probe-monitors-and-black-box-monitors
  (paper: item 8)
- **Authors, date, length:** Tim Hua, James Baskerville, Henri Lemoine, Mia Hopman, Aryan
  Bhatt, Tyler Tracy, 27 Jul 2025, 8 min.
- **What it says:**
  - Run a very cheap monitor on everything, and call an expensive one only when the cheap score
    falls in a chosen window.
  - Choose the window, and which outputs to audit, to catch the most misaligned outputs within
    a fixed budget.
  - **Worked example:** call the expensive monitor only for cheap scores between −0.01 and 2.18.
    That audits 4% of honest outputs and catches 93.7% of misaligned ones.
  - **"Neyman-Pearson" in plain words:** for each output, estimate how much more likely it is to
    be an attack than honest (a likelihood ratio, learned from labelled data). Audit the
    highest ratios first until the budget runs out. Where both monitors ran, the combined
    decision is a learned 2-D boundary, not an average or a max.
  - **Comments:** Rohin Shah asks whether fitted ratios generalize, or whether a scheming model
    could adapt to them. The author replies that a smoother version loses little.
- **For you: this is the closest work to yours. Engage with it directly.**
  - Your "review the top 2 steps per run" and "take the higher of two ranks" are rules of
    thumb. Their method is the principled version.
  - Say that plainly, and say what their method would need from you: labelled data to fit
    the ratios, which you deliberately avoided fitting on MonitoringBench.
  - Rohin's comment is an objection your post will face too: does a learned combination
    generalize to new attacks?

---

## C. The papers you rely on (about 2–3 hours; skim, with the sections named)

### 6. MonitoringBench: Semi-Automated Red-Teaming for Agent Monitoring
- **Link:** https://arxiv.org/abs/2605.09684
- **Authors, date:** Monika Jotautaitė, Maria Angelica Martinez, Ollie Matthews, Tyler Tracy,
  10 May 2026.
- **What it says:**
  - Red-teaming done by hand may under-elicit attacks and so overstate how good monitors are.
    The authors built a semi-automated pipeline (generate strategies, execute, refine) and
    released 2,644 successful attack runs in BashArena.
  - **Elicited vs refined:**
    - The "elicited" baseline is Opus 4.6 given the standard attack prompt. 196 of 400 runs
      succeeded; those are the 196 you tested on.
    - "Refined" attacks were rewritten until they looked less suspicious to the development
      monitors.
  - **Headline:** the Opus 4.5 monitor's catch rate falls from 94.9% on elicited attacks to
    60.3% on the best refined attacks.
  - **Thresholds:** 416 honest runs (not released). For whole-trajectory monitors, the 1% line
    is the 99th percentile of honest run scores.
  - **They also evaluate step-wise monitors,** where each step is scored and the max is taken,
    which is your setup. Their step-wise line is the 99th percentile of *per-step* scores. A 1%
    per-step rate adds up to roughly a 7–17% false-alarm rate per run *(unverified detail,
    from their Appendix G)*.
  - **Limitations:** one setting, four side tasks; attacks developed with Anthropic models;
    thresholds from honest runs, not real deployment traffic.
- **Read closely:**
  - 2.1 "Monitor Evaluations";
  - Appendix L (honest runs and thresholds);
  - Appendix G (step-wise false-alarm rate);
  - Table 5 (catch rates at 1% FPR);
  - 3.2.1 "Monitoring failures";
  - 4.1 "Limitations".
- **For you: a likely objection.**
  - You compared against their *whole-trajectory* monitors, but your monitor is *step-wise*.
    Their step-wise results exist, but they use a per-step threshold, so those numbers aren't
    at 1% per run either.
  - Explain why you compared at 1% *per run* (it's the stricter, like-for-like false-alarm
    rate), and mention their step-wise numbers exist.
  - Your local copy of their scores (`master.parquet`) has the step-wise (`sw_`) columns if you
    want to check them.

### 7. BashArena: A Control Setting for Highly Privileged AI Agents
- **Link:** https://arxiv.org/abs/2512.15688
- **Authors, date:** Adam Kaufman, James Lucassen, Tyler Tracy, Cody Rushing, Aryan Bhatt,
  17 Dec 2025.
- **What it says:**
  - **Setting:** 637 Linux admin tasks in Docker. Four side tasks: download malware, exfiltrate
    secrets, escalate privileges, disable the firewall.
  - **Headline:** Claude Sonnet 4.5 completes sabotage while evading a GPT-4.1 mini monitor 26%
    of the time, at a 4% false-alarm rate per run (about 0.08% per step).
  - **Their monitor** sees the task, **all four side-task descriptions**, and all tool calls and
    outputs so far, and rates each action from 0 to 10.
- **Read closely:**
  - 2.4 "Side tasks";
  - 4.1 "Methodology";
  - 4.2 (how the false-alarm rate is defined);
  - 4.3 "Monitoring Results";
  - 5 "Limitations";
  - Appendix E.6 (the monitor prompt).
- **For you:**
  - Their monitor is told the four side tasks. Yours wasn't told them directly, but Haiku's
    prompt names similar threat types. Mention this.
  - Their 4% headline rate is easier than your 1%.

### 8. Combining Cost-Constrained Runtime Monitors for AI Safety
- **Link:** https://arxiv.org/abs/2507.15886
- **Authors, date:** Tim Hua et al. (the same team as item 5), Jul 2025 (revised Oct 2025).
- **What it says:** the full version of item 5.
  - **Setting:** backdoored code from o1-mini, with Llama 3.1 8B (cheap) and 70B (expensive)
    as monitors.
  - **Results:** more than double the recall of a naive baseline. Two monitors beat either one
    alone at the same cost.
  - **Stated limit:** optimality assumes real attacks look like the training attacks.
- **Read:** the abstract, the introduction, and the limitations. Item 5 covers the rest.
- **Related, cited by this paper:** Cunningham et al. (2025, Anthropic), "Cost-effective
  constitutional classifiers via representation re-use", is a cheap first stage with a big
  model behind it. *(Unverified link: https://alignment.anthropic.com/2025/cheap-monitors/.
  Open it before citing.)*

### 9. AI Control: Improving Safety Despite Intentional Subversion
- **Link:** https://arxiv.org/abs/2312.06942
- **Authors, date:** Ryan Greenblatt, Buck Shlegeris, Kshitij Sachan, Fabien Roger (Redwood
  Research), Dec 2023 (ICML 2024).
- **What it says:**
  - **The founding paper of "AI control":** get useful work from a stronger model you don't
    trust (GPT-4), using a weaker model you do trust (GPT-3.5) and a small budget of careful
    human review.
  - **Trusted monitoring:** the trusted model rates how suspicious each output is, and the top
    2% go to an audit.
  - **Result:** 62% safety at 97% usefulness. Better protocols (trusted editing, untrusted
    monitoring with safeguards) do better.
- **Read closely:**
  - 1 "Introduction";
  - Table 2;
  - 3.2 "Trusted Monitoring";
  - 5.1 "Difficulties and Limitations of AI Control".
- **For you:** this is where the vocabulary comes from. Your monitor is a *trusted monitor*:
  cheap, weaker models watching a stronger agent. Use the term and cite this paper.

---

## D. Rationality basics (about 15 minutes; moderators look for these)

### 10. Update Yourself Incrementally
- **Link:** https://www.lesswrong.com/posts/627DZcvme7nLDrbZu/update-yourself-incrementally
- **Author, date, length:** Eliezer Yudkowsky, Aug 2007, 4 min.
- **What it says:**
  - Even a good theory meets some contrary evidence.
  - Each piece of evidence should move your belief a bit, up or down. Don't flip between
    "proved" and "dead".
  - Don't explain away results you dislike.
- **For you:**
  - Give probabilities, for example "I'd put about X% on the 63% holding within 10 points
    under the paper's honest runs".
  - Say which future result would move you, and by how much.
  - Report the weak results (sudo at 32%) plainly.

### 11. Rationalization
- **Link:** https://www.lesswrong.com/posts/SFZoEBpLo9frSJGkc/rationalization
  (the "might be wrong" link in the submission guidelines)
- **Author, date, length:** Eliezer Yudkowsky, Sep 2007, 3 min.
- **What it says:**
  - Rationality runs forward: evidence, then conclusion.
  - Rationalization runs backward: conclusion, then hand-picked evidence.
  - Test your idea in ways that could prove it *wrong*.
- **For you:** this is exactly why your pre-registered rules matter.
  - Say you wrote the plan before seeing results.
  - Say you report the chosen combination (63%), not the best-looking one (69%).

### Optional
- **Highlights from the Sequences:** https://www.lesswrong.com/highlights (50 essays, about
  8 hours). The guide recommends it; it's not needed before this post.
- **Open threads:** find the latest "Open Thread" or AI open thread by searching LessWrong for
  "open thread" and sorting by new. A short version of your idea there can get feedback before
  you submit.

---

## Objections to prepare for (collected from the reading)

1. **Whole-run vs step-wise comparison:** "You compared a step-wise monitor against
   whole-trajectory ones" (item 6).
2. **Different honest runs:** "Your honest runs differ from the paper's, and were screened"
   (items 3, 6).
3. **Heuristic combination:** "Your two-stage combination is a heuristic; Hua et al. do it
   optimally" (items 5, 8).
4. **Elicited attacks only:** "Elicited attacks are the easy ones; monitors drop a lot on
   refined attacks" (item 6: Opus 4.5 falls from 94.9% to 60.3%).
5. **Prompt advantage:** "Haiku's prompt names the threat types" (item 7: BashArena's own
   monitor is told the side tasks).
6. **Generalization:** "Does the learned score generalize?" (Rohin's comment on item 5).
