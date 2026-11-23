# Eval Rubrics Lab

A hands-on lab for engineers. You build and test an evaluation for a healthcare chatbot, one technique at a time.

The chatbot is the patient services assistant for Harborview Family Clinic, a fictional clinic. It answers administrative questions: refills, cancellations, records, billing. The dataset has 20 of its answers. Some are correct. Others have planted flaws, including two answers that could hurt a patient.

You start by grading with a vague rubric and watching graders disagree. Each round adds one technique and measures the improvement.

| Round | Technique | Main command |
|---|---|---|
| 1 | Vague rubric, human graders | `harness.agreement --raters` |
| 2 | Analytic rubric: binary checks, anchored scale, safety gate | `harness.agreement --raters` |
| 3 | Single LLM judge (an LLM that scores outputs) with reasoning before the score | `harness.judge`, `harness.agreement` |
| 4 | Pairwise comparison with position and length bias tests | `harness.pairwise` |
| 5 | Panel of judges with disagreement flags | `harness.panel` |
| 6 | Gates and weights, then evals in continuous integration (CI) | `harness.score`, `harness.ci_check` |

The step-by-step exercises are in [LAB_GUIDE.md](LAB_GUIDE.md). Facilitators should read [FACILITATOR.md](FACILITATOR.md) first.

## Setup

1. Install Python 3.10 or later and Claude Code.
2. Install the dependencies:

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Set your Claude API key:

   ```bash
   export ANTHROPIC_API_KEY=<your-key>
   ```

4. Check the setup with the offline tests. These tests use a fake client and make no API calls.

   ```bash
   python -m pytest -q
   ```

Run every command from the repository root.

## Repository layout

```
data/
  policy.md            The clinic policy. The only source of truth for grading.
  outputs.jsonl        20 assistant answers to 10 patient questions (2 answers per question).
  answer_key.jsonl     Correct labels and the planted flaw for each answer. Facilitators only.
  pairs.jsonl          The 10 answer pairs and the better answer in each pair.
rubrics/
  v1_vague.md          "Rate quality 1 to 5."
  v2_analytic_starter.md  Round 2 starter with TODOs.
  v2_analytic.md       Reference solution.
  weights.json         Check weights for round 6.
harness/
  judge.py             Run one LLM judge over the dataset.
  agreement.py         Cohen's kappa and percent agreement.
  pairwise.py          Pairwise comparison with an order-swap test.
  panel.py             Several judges, majority vote and median, disagreement flags.
  score.py             Weighted score with a safety gate.
  ci_check.py          Pass/fail check for CI.
human_scores/          Sheets for human grading in rounds 1 and 2.
results/               Your output files. Ignored by Git.
tests/                 Offline tests with a fake client.
```

## Models and cost

The default judge is `claude-haiku-5-5`. Change it with `--model`. Round 5 also uses `claude-sonnet-5-5` and `claude-opus-5-5`.

Each script prints token counts and API time. A full run of all rounds makes about 200 API calls. Check current pricing before a large class.

`--temperature` is optional. When you omit it, the scripts use the API default. This lab has not been verified against every model's temperature support.

## Ideas for Claude Code

Learners can use Claude Code during the lab. Good prompts:

- "Read rubrics/v2_analytic_starter.md and data/policy.md. Help me write the safety gate. Do not show me the reference solution."
- "Read results/r3_judge.csv. For each disagreement with the answer key, quote the judge's reasoning and tell me which rubric line caused it."
- "Add a `--rubric-b` option to harness/pairwise.py so I can compare two rubrics in one run."
