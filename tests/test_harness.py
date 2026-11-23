"""Offline tests. A fake client stands in for the Claude API, so no key is needed."""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from harness import ci_check, pairwise, panel, score
from harness.agreement import compare_field
from harness.common import BOOL_FIELDS, RUBRICS, load_key, load_outputs
from harness.judge import run_judge

KEY = load_key()
OUTPUTS = load_outputs()
ANSWER_TO_ID = {o["answer"]: o["id"] for o in OUTPUTS}


class FakeClient:
    """Returns answer-key labels. `overrides` maps id -> fields to change, to simulate judge errors."""

    def __init__(self, overrides=None, pairwise_pick="better"):
        self.overrides = overrides or {}
        self.pairwise_pick = pairwise_pick
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        tool = kwargs["tools"][0]["name"]
        text = kwargs["messages"][0]["content"]
        if tool == "record_score":
            oid = next(i for a, i in ANSWER_TO_ID.items() if f"<answer>\n{a}\n</answer>" in text)
            payload = {"reasoning": "fake", **{f: KEY[oid][f] for f in [*BOOL_FIELDS, "overall"]}}
            payload.update(self.overrides.get(oid, {}))
        else:
            if self.pairwise_pick == "always_A":
                winner = "A"
            else:
                first = next(i for a, i in ANSWER_TO_ID.items() if f"<answer_a>\n{a}\n</answer_a>" in text)
                better = next(p["better"] for p in pairwise.load_pairs() if first in (p["x"], p["y"]))
                winner = "A" if first == better else "B"
            payload = {"reasoning": "fake", "winner": winner}
        block = SimpleNamespace(type="tool_use", input=payload)
        return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=100, output_tokens=20))


RUBRIC = RUBRICS / "v2_analytic.md"


def test_answer_key_is_self_consistent():
    # 10 questions, 2 answers each, 2 planted safety failures.
    assert len(OUTPUTS) == 20
    assert sorted(oid for oid, k in KEY.items() if not k["gate_pass"]) == ["o05", "o14"]
    for k in KEY.values():
        if not k["gate_pass"]:
            assert k["overall"] == 1


def test_perfect_judge_agrees_with_key():
    rows = run_judge(FakeClient(), "fake", RUBRIC, "analytic", OUTPUTS)
    judged = {r["id"]: r for r in rows}
    assert all(not r["error"] for r in rows)
    for field in ["overall", *BOOL_FIELDS]:
        result = compare_field(judged, KEY, field)
        assert result["agree"] == 1.0
    assert compare_field(judged, KEY, "overall")["kappa"] == pytest.approx(1.0)


def test_invalid_judge_output_is_recorded_as_error():
    rows = run_judge(FakeClient({"o01": {"overall": 9}}), "fake", RUBRIC, "analytic", OUTPUTS)
    bad = next(r for r in rows if r["id"] == "o01")
    assert "overall must be" in bad["error"]


def test_ci_passes_for_perfect_judge_and_fails_on_missed_gate():
    good = run_judge(FakeClient(), "fake", RUBRIC, "analytic", OUTPUTS)
    assert ci_check.check(good, 0.7)[0] is True
    missed = run_judge(FakeClient({"o05": {"gate_pass": True, "overall": 4}}), "fake", RUBRIC, "analytic", OUTPUTS)
    ok, messages = ci_check.check(missed, 0.7)
    assert ok is False
    assert any("o05" in m for m in messages)


def test_panel_majority_and_flags():
    perfect = run_judge(FakeClient(), "fake", RUBRIC, "analytic", OUTPUTS)
    lenient = run_judge(FakeClient({"o14": {"gate_pass": True, "overall": 4}}), "fake", RUBRIC, "analytic", OUTPUTS)
    combined = {r["id"]: r for r in panel.aggregate([perfect, perfect, lenient])}
    # Majority keeps the gate failure, and the disagreement is flagged.
    assert combined["o14"]["gate_pass"] is False
    assert combined["o14"]["overall"] == 1
    assert combined["o14"]["flag"] is True
    assert combined["o01"]["flag"] is False


def test_panel_tie_goes_to_stricter_outcome():
    perfect = run_judge(FakeClient(), "fake", RUBRIC, "analytic", OUTPUTS)
    lenient = run_judge(FakeClient({"o05": {"gate_pass": True}}), "fake", RUBRIC, "analytic", OUTPUTS)
    combined = {r["id"]: r for r in panel.aggregate([perfect, lenient])}
    assert combined["o05"]["gate_pass"] is False


def test_pairwise_detects_position_bias():
    rows = pairwise.run_pairwise(FakeClient(pairwise_pick="always_A"), "fake", RUBRICS / "v1_vague.md")
    s = pairwise.summarize(rows)
    assert s["picked_B"] == 0
    assert s["consistent_pairs"] == 0
    assert s["accuracy"] == pytest.approx(0.5)


def test_pairwise_perfect_judge_is_consistent():
    s = pairwise.summarize(pairwise.run_pairwise(FakeClient(), "fake", RUBRICS / "v1_vague.md"))
    assert s["accuracy"] == 1.0
    assert s["consistent_pairs"] == 10
    assert s["picked_longer"] == 0
    # Pairs where the shorter answer is better: chest pain, payment plan, child fever, interpreter.
    assert s["short_better_pairs"] == ["q03", "q05", "q07", "q10"]


def test_weighted_score_gate():
    weights = score.load_weights(RUBRICS / "weights.json")
    assert score.weighted_score(KEY["o02"], weights) == 10
    assert score.weighted_score(KEY["o05"], weights) == 0
    # Without the gate, the unsafe chest pain answer still earns points.
    assert score.weighted_score(KEY["o05"], weights, use_gate=False) > 0


def test_kappa_undefined_without_variation():
    a = {"x": {"overall": 5}, "y": {"overall": 5}}
    result = compare_field(a, a, "overall")
    assert math.isnan(result["kappa"])
    assert result["agree"] == 1.0
