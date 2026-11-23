"""Pairwise comparison with an order-swap test for position bias and length bias.

Each pair is judged twice: once with answer x shown first, once with y first.
A consistent judge picks the same answer both times.

Example:
  python -m harness.pairwise --rubric rubrics/v1_vague.md --out results/r4_pairwise.csv
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .common import (DEFAULT_MODEL, call_tool, get_client, load_outputs, load_pairs,
                     load_policy, usage_summary, write_csv)

SYSTEM = (
    "You compare two answers from a clinic's patient services assistant. "
    "Use the rubric you are given. Write your reasoning first, then pick the better answer with the tool."
)

PAIRWISE_TOOL = {
    "name": "record_winner",
    "description": "Record which answer is better.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reasoning": {"type": "string", "description": "Your reasoning. Write this before choosing."},
            "winner": {"type": "string", "enum": ["A", "B"]},
        },
        "required": ["reasoning", "winner"],
    },
}


def build_user_prompt(policy: str, rubric: str, question: str, answer_a: str, answer_b: str) -> str:
    return (
        f"<policy>\n{policy}\n</policy>\n\n"
        f"<rubric>\n{rubric}\n</rubric>\n\n"
        f"<question>\n{question}\n</question>\n\n"
        f"<answer_a>\n{answer_a}\n</answer_a>\n\n"
        f"<answer_b>\n{answer_b}\n</answer_b>\n\n"
        "Which answer is better according to the rubric? Write your reasoning first, then record the winner."
    )


def judge_order(client, model, policy, rubric, outputs, pair, first, second, order) -> dict:
    row = {"question_id": pair["question_id"], "order": order, "shown_first": first, "shown_second": second,
           "better": pair["better"], "model": model}
    try:
        result, usage = call_tool(
            client, model, SYSTEM,
            build_user_prompt(policy, rubric, outputs[first]["question"],
                              outputs[first]["answer"], outputs[second]["answer"]),
            PAIRWISE_TOOL,
        )
        if result.get("winner") not in ("A", "B"):
            raise ValueError(f"winner must be A or B, got {result.get('winner')!r}")
        row["winner_position"] = result["winner"]
        row["winner_id"] = first if result["winner"] == "A" else second
        row["correct"] = row["winner_id"] == pair["better"]
        row["reasoning"] = result.get("reasoning", "")
        row.update(usage)
        row["error"] = ""
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def run_pairwise(client, model: str, rubric_path: Path, workers: int = 4) -> list[dict]:
    policy = load_policy()
    rubric = Path(rubric_path).read_text()
    outputs = {o["id"]: o for o in load_outputs()}
    jobs = []
    for pair in load_pairs():
        jobs.append((pair, pair["x"], pair["y"], "xy"))
        jobs.append((pair, pair["y"], pair["x"], "yx"))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(
            lambda j: judge_order(client, model, policy, rubric, outputs, *j), jobs))


def summarize(rows: list[dict]) -> dict:
    """Compute accuracy, order consistency, position preference, and length bias."""
    outputs = {o["id"]: o for o in load_outputs()}
    ok = [r for r in rows if not r.get("error")]
    by_q: dict[str, dict] = {}
    for r in ok:
        by_q.setdefault(r["question_id"], {})[r["order"]] = r

    complete = {q: v for q, v in by_q.items() if "xy" in v and "yx" in v}
    consistent = [q for q, v in complete.items() if v["xy"]["winner_id"] == v["yx"]["winner_id"]]
    flipped = sorted(set(complete) - set(consistent))

    # Length bias: pairs where the better answer is the shorter one.
    short_better = []
    for q, v in complete.items():
        r = v["xy"]
        better, other = r["better"], (r["shown_second"] if r["shown_first"] == r["better"] else r["shown_first"])
        if len(outputs[better]["answer"]) < len(outputs[other]["answer"]):
            short_better.append(q)
    picked_longer = sum(1 for q in short_better for o in ("xy", "yx") if not complete[q][o]["correct"])

    return {
        "judgments": len(ok),
        "accuracy": sum(1 for r in ok if r["correct"]) / len(ok) if ok else float("nan"),
        "picked_A": sum(1 for r in ok if r["winner_position"] == "A"),
        "picked_B": sum(1 for r in ok if r["winner_position"] == "B"),
        "pairs_complete": len(complete),
        "consistent_pairs": len(consistent),
        "flipped_pairs": flipped,
        "short_better_pairs": sorted(short_better),
        "picked_longer": picked_longer,
        "short_better_judgments": 2 * len(short_better),
    }


def print_summary(s: dict) -> None:
    print(f"\nJudgments: {s['judgments']}   accuracy vs answer key: {s['accuracy']:.0%}")
    print(f"Position: picked the first answer (A) {s['picked_A']} times, the second (B) {s['picked_B']} times")
    print(f"Order consistency: {s['consistent_pairs']} of {s['pairs_complete']} pairs kept the same winner after the swap")
    if s["flipped_pairs"]:
        print(f"  Flipped pairs (position bias): {', '.join(s['flipped_pairs'])}")
    print(f"Length bias: in pairs where the shorter answer is better ({', '.join(s['short_better_pairs'])}),")
    print(f"  the judge picked the longer answer {s['picked_longer']} of {s['short_better_judgments']} times")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rubric", type=Path, default=Path("rubrics/v1_vague.md"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    rows = run_pairwise(get_client(), args.model, args.rubric, workers=args.workers)
    write_csv(rows, args.out)
    print(f"Wrote {args.out}")
    print(usage_summary(rows))
    print_summary(summarize(rows))


if __name__ == "__main__":
    main()
