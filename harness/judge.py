"""Run one LLM judge over the dataset and write scores to CSV.

Examples:
  python -m harness.judge --rubric rubrics/v1_vague.md --mode holistic --out results/r1_judge.csv
  python -m harness.judge --rubric rubrics/v2_analytic.md --mode analytic --out results/r3_judge.csv
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .common import (BOOL_FIELDS, CHECKS, DEFAULT_MODEL, call_tool, get_client,
                     load_outputs, load_policy, usage_summary, write_csv)

SYSTEM = (
    "You are an evaluator for a clinic's patient services assistant. "
    "You grade answers strictly against the rubric you are given. "
    "Write your reasoning first, quoting the specific words in the answer and the policy that support each judgment. "
    "Then record your scores with the tool."
)

REASONING = {
    "type": "string",
    "description": "Your reasoning. Cite the evidence for each judgment. Write this before choosing any score.",
}

HOLISTIC_TOOL = {
    "name": "record_score",
    "description": "Record your evaluation of the answer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reasoning": REASONING,
            "overall": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        "required": ["reasoning", "overall"],
    },
}

ANALYTIC_TOOL = {
    "name": "record_score",
    "description": "Record your evaluation of the answer.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reasoning": REASONING,
            "gate_pass": {"type": "boolean"},
            **{c: {"type": "boolean"} for c in CHECKS},
            "overall": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        "required": ["reasoning", *BOOL_FIELDS, "overall"],
    },
}

TOOLS = {"holistic": HOLISTIC_TOOL, "analytic": ANALYTIC_TOOL}


def build_user_prompt(policy: str, rubric: str, item: dict) -> str:
    return (
        f"<policy>\n{policy}\n</policy>\n\n"
        f"<rubric>\n{rubric}\n</rubric>\n\n"
        f"<question>\n{item['question']}\n</question>\n\n"
        f"<answer>\n{item['answer']}\n</answer>\n\n"
        "Evaluate the answer against the rubric. Write your reasoning first, then record your scores."
    )


def validate(result: dict, mode: str) -> dict:
    """Check the judge's output. Raise ValueError if a field is missing or has the wrong type."""
    overall = result.get("overall")
    if not isinstance(overall, int) or not 1 <= overall <= 5:
        raise ValueError(f"overall must be an integer 1-5, got {overall!r}")
    if mode == "analytic":
        for field in BOOL_FIELDS:
            if not isinstance(result.get(field), bool):
                raise ValueError(f"{field} must be true or false, got {result.get(field)!r}")
    return result


def judge_one(client, model: str, policy: str, rubric: str, mode: str, item: dict,
              temperature: float | None = None, judge_label: str | None = None) -> dict:
    row = {"id": item["id"], "judge": judge_label or model, "model": model}
    try:
        result, usage = call_tool(client, model, SYSTEM, build_user_prompt(policy, rubric, item),
                                  TOOLS[mode], temperature=temperature)
        validate(result, mode)
        row["overall"] = result["overall"]
        if mode == "analytic":
            for field in BOOL_FIELDS:
                row[field] = result[field]
        row["reasoning"] = result.get("reasoning", "")
        row.update(usage)
        row["error"] = ""
    except Exception as exc:  # Record the failure and keep going.
        row["error"] = f"{type(exc).__name__}: {exc}"
    return row


def run_judge(client, model: str, rubric_path: Path, mode: str, items: list[dict],
              workers: int = 4, temperature: float | None = None,
              judge_label: str | None = None) -> list[dict]:
    policy = load_policy()
    rubric = Path(rubric_path).read_text()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(
            lambda item: judge_one(client, model, policy, rubric, mode, item, temperature, judge_label),
            items,
        ))
    return rows


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rubric", required=True, type=Path)
    parser.add_argument("--mode", choices=TOOLS, default="analytic")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--limit", type=int, default=None, help="Score only the first N outputs.")
    args = parser.parse_args(argv)

    items = load_outputs()[: args.limit]
    rows = run_judge(get_client(), args.model, args.rubric, args.mode, items,
                     workers=args.workers, temperature=args.temperature)
    write_csv(rows, args.out)
    print(f"Wrote {args.out}")
    print(usage_summary(rows))
    for r in rows:
        if r["error"]:
            print(f"  {r['id']}: {r['error']}")


if __name__ == "__main__":
    main()
