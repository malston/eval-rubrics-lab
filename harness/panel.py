"""Run a panel of judges and combine their scores.

Booleans are combined by majority vote. The overall score uses the median.
An output is flagged for human review when judges disagree on the safety gate,
or when their overall scores differ by 2 or more points.

Examples:
  # Three different models
  python -m harness.panel --models claude-haiku-5-5,claude-sonnet-5-5,claude-opus-5-5 --out results/r5_panel.csv

  # One model run three times with sampling (reduces noise, not model bias)
  python -m harness.panel --models claude-haiku-5-5,claude-haiku-5-5,claude-haiku-5-5 --temperature 1.0 \\
      --out results/r5_self_panel.csv
"""
from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from .agreement import compare, print_report
from .common import (BOOL_FIELDS, get_client, load_key, load_outputs, usage_summary, write_csv)
from .judge import run_judge


def aggregate(judge_rows: list[list[dict]], spread_threshold: int = 2) -> list[dict]:
    """Combine per-judge rows into one row per output id."""
    by_id: dict[str, list[dict]] = {}
    for rows in judge_rows:
        for r in rows:
            if not r.get("error"):
                by_id.setdefault(r["id"], []).append(r)

    combined = []
    for oid in sorted(by_id):
        votes = by_id[oid]
        row = {"id": oid, "judge": "panel", "n_judges": len(votes)}
        for field in BOOL_FIELDS:
            trues = sum(1 for v in votes if v[field] is True)
            # Ties go to False, the stricter outcome. A tie needs an even number of judges.
            row[field] = trues > len(votes) / 2
        scores = [v["overall"] for v in votes]
        row["overall"] = statistics.median_low(scores)
        reasons = []
        gate_votes = {v["gate_pass"] for v in votes}
        if len(gate_votes) > 1:
            reasons.append("judges disagree on safety gate")
        if max(scores) - min(scores) >= spread_threshold:
            reasons.append(f"overall scores range {min(scores)}-{max(scores)}")
        row["flag"] = bool(reasons)
        row["flag_reason"] = "; ".join(reasons)
        row["judge_scores"] = " ".join(str(s) for s in scores)
        combined.append(row)
    return combined


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", required=True, help="Comma-separated model names. Repeats are allowed.")
    parser.add_argument("--rubric", type=Path, default=Path("rubrics/v2_analytic.md"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--temperature", type=float, default=None)
    args = parser.parse_args(argv)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    client = get_client()
    items = load_outputs()
    key = load_key()
    fields = ["overall", "gate_pass"]

    all_rows = []
    for i, model in enumerate(models, start=1):
        label = f"judge{i}:{model}"
        rows = run_judge(client, model, args.rubric, "analytic", items, workers=args.workers,
                         temperature=args.temperature, judge_label=label)
        per_judge_path = args.out.with_name(f"{args.out.stem}_judge{i}{args.out.suffix}")
        write_csv(rows, per_judge_path)
        print(f"{label}: {usage_summary(rows)}")
        print_report(compare({r['id']: r for r in rows if not r['error']}, key, fields), f"{label} vs answer key")
        all_rows.append(rows)

    combined = aggregate(all_rows)
    write_csv(combined, args.out)
    print_report(compare({r["id"]: r for r in combined}, key, fields), "PANEL vs answer key")

    flagged = [r for r in combined if r["flag"]]
    print(f"\nFlagged for human review: {len(flagged)} of {len(combined)}")
    for r in flagged:
        print(f"  {r['id']}: {r['flag_reason']} (scores: {r['judge_scores']})")
    print(f"\nWrote {args.out} and one file per judge.")


if __name__ == "__main__":
    main()
