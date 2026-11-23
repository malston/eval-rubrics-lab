# Lab Guide

Work in pairs. Do not open `data/answer_key.jsonl` until a step tells you to. The scripts read it for you.

Read `data/policy.md` before you start. It is short, and every grading decision depends on it.

---

## Round 1: Vague rubric (about 20 minutes)

**Goal:** see how much two careful graders disagree when the rubric is vague.

1. Open `human_scores/round1.csv`. It has 10 answers.
2. Read `rubrics/v1_vague.md`. That one line is the whole rubric.
3. Each partner scores all 10 answers alone, without talking. Partner A fills the `rater_a` column. Partner B fills `rater_b`.
4. Measure your agreement:

   ```bash
   python -m harness.agreement human_scores/round1.csv --raters rater_a rater_b
   ```

5. Discuss the answers you disagreed on. Write down why. Typical reasons: different ideas of what "good" means, or one grader noticed a problem the other missed.

**Look for:** Did you both give a low score to o05, the chest pain answer? It is polite and has correct booking facts.

---

## Round 2: Analytic rubric (about 30 minutes)

**Goal:** turn your disagreements into a rubric that two graders apply the same way.

1. Open `rubrics/v2_analytic_starter.md` and replace every TODO. Use your notes from round 1.
2. Rules for good checks:
   - Each check is a yes/no question.
   - A grader answers each check by pointing at words in the answer or the policy.
   - Each anchor on the 1 to 5 scale describes which checks pass or fail.
3. Open `human_scores/round2.csv` and score the same 10 answers again with your new rubric. Work alone again.
4. Measure agreement:

   ```bash
   python -m harness.agreement human_scores/round2.csv --raters rater_a rater_b
   ```

5. Compare with round 1. Then read `rubrics/v2_analytic.md`, the reference solution, and compare it with yours.

**Look for:** the safety gate. A failed gate sets the score to 1, however good the rest of the answer is.

---

## Round 3: Single LLM judge (about 30 minutes)

**Goal:** turn the rubric into a judge prompt and measure the judge against the answer key.

1. Read `harness/judge.py`. Note these design choices:
   - The judge must answer through a tool. The tool's schema forces structured JSON output.
   - `reasoning` comes before the scores, and the system prompt asks for evidence first.
   - `validate()` rejects malformed output, and the script records it as an error.
2. Run the vague rubric:

   ```bash
   python -m harness.judge --rubric rubrics/v1_vague.md --mode holistic --out results/r3_vague.csv
   python -m harness.agreement results/r3_vague.csv
   ```

3. Run your rubric, then the reference rubric:

   ```bash
   python -m harness.judge --rubric rubrics/v2_analytic_starter.md --mode analytic --out results/r3_mine.csv
   python -m harness.judge --rubric rubrics/v2_analytic.md --mode analytic --out results/r3_ref.csv
   python -m harness.agreement results/r3_mine.csv
   python -m harness.agreement results/r3_ref.csv
   ```

4. Pick two disagreements. Open the CSV and read the judge's `reasoning` for each. Decide if the judge, the rubric, or the answer key is wrong.
5. Change one line of your rubric to fix one disagreement. Rerun and measure again.
6. Run the same rubric twice and compare the runs. This shows how much the judge varies from run to run:

   ```bash
   python -m harness.judge --rubric rubrics/v2_analytic.md --out results/r3_ref_rerun.csv
   python -m harness.agreement results/r3_ref.csv --compare results/r3_ref_rerun.csv
   ```

**Look for:** the per-check kappa values. A low kappa on one check usually points to one unclear rubric line.

---

## Round 4: Pairwise comparison and judge bias (about 25 minutes)

**Goal:** measure position bias and length bias.

Position bias means the judge favors the answer shown first (or second). Length bias means the judge favors the longer answer.

1. Read `harness/pairwise.py`. Each of the 10 pairs is judged twice, once in each order.
2. Run it with the vague rubric:

   ```bash
   python -m harness.pairwise --rubric rubrics/v1_vague.md --out results/r4_vague.csv
   ```

3. Read the summary. Count the flipped pairs. Check how often the judge picked the longer answer when the shorter one is better.
4. Run it again with the reference rubric and compare:

   ```bash
   python -m harness.pairwise --rubric rubrics/v2_analytic.md --out results/r4_ref.csv
   ```

5. Stretch: try a smaller and a larger model with `--model` and compare the bias numbers.

**Look for:** pairs q05 and q10. In both, the worse answer is long and friendly.

---

## Round 5: Panel of judges (about 30 minutes)

**Goal:** combine several judges and send their disagreements to a human.

1. Read `aggregate()` in `harness/panel.py`. Booleans use a majority vote. A tie goes to false, the stricter result. The overall score uses the median.
2. Run a panel of three different models:

   ```bash
   python -m harness.panel --models claude-haiku-5-5,claude-sonnet-5-5,claude-opus-5-5 --out results/r5_mixed.csv
   ```

3. Run a panel of one model three times:

   ```bash
   python -m harness.panel --models claude-haiku-5-5,claude-haiku-5-5,claude-haiku-5-5 --temperature 1.0 \
       --out results/r5_self.csv
   ```

4. Compare each judge with the panel. Read the flagged outputs. Would a human reviewer agree with the flag?
5. Note the token and time cost of each panel. Decide if the improvement is worth the cost for this task.

**Look for:** a panel built only from Claude models shares one model family. It reduces random noise. It does not remove a bias that all the models share. To test that, add a judge from another provider (stretch exercise, needs a second API key and a small change to `harness/common.py`).

---

## Round 6: Gates, weights, and CI (about 30 minutes)

**Goal:** turn scores into a decision and protect the eval from regressions.

1. Score a judge run with the gate on and off:

   ```bash
   python -m harness.score results/r3_ref.csv
   python -m harness.score results/r3_ref.csv --no-gate
   ```

2. Find o05 and o14 in both rankings. Without the gate, unsafe answers can rank above safe but incomplete ones.
3. Edit `rubrics/weights.json`. Change one weight and see how the ranking changes. Discuss which weights fit a patient-facing assistant.
4. Run the CI check:

   ```bash
   python -m harness.ci_check --rubric rubrics/v2_analytic.md
   ```

   CI (continuous integration) runs automatic checks on every code change. This check fails if the judge misses any safety gate failure, or if overall kappa drops below 0.7.

5. Break the rubric on purpose. For example, delete rule 2 of the safety gate. Run the CI check again and confirm it fails.
6. Read `.github/workflows/eval.yml`. It runs the same check on each pull request that changes a rubric.

**Look for:** a judge can reach high overall agreement and still miss a safety failure. The gate check catches that case. The kappa check alone does not.
