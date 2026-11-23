"""Measure agreement between two sets of scores.

Cohen's kappa measures agreement after removing the agreement two graders
would reach by chance. 1.0 is perfect agreement. 0 is chance level.
For the 1-5 overall score, the script uses quadratic weighted kappa, which
counts a 4-versus-5 disagreement as smaller than a 1-versus-5 disagreement.

Examples:
  # Judge scores against the answer key
  python -m harness.agreement results/r3_judge.csv

  # Two judge runs against each other
  python -m harness.agreement results/r3_judge.csv --compare results/r3_judge_rerun.csv

  # Two human raters in one sheet (overall score only)
  python -m harness.agreement human_scores/round1.csv --raters rater_a rater_b
"""
from __future__ import annotations

import argparse
import math
import warnings
from pathlib import Path

from sklearn.metrics import cohen_kappa_score

from .common import BOOL_FIELDS, load_key, parse_bool, parse_int, read_csv


def _kappa(a, b, weights=None) -> float:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        value = cohen_kappa_score(a, b, weights=weights)
    return float(value)


def compare_field(a: dict, b: dict, field: str) -> dict:
    """Compare one field across two {id: row} maps. Skip ids with a blank value on either side."""
    is_overall = field == "overall"
    parse = parse_int if is_overall else parse_bool
    pairs = []
    for oid in sorted(set(a) & set(b)):
        va, vb = parse(a[oid].get(field)), parse(b[oid].get(field))
        if va is not None and vb is not None:
            pairs.append((oid, va, vb))
    n = len(pairs)
    result = {"field": field, "n": n, "kappa": math.nan, "agree": math.nan, "within1": math.nan,
              "disagreements": [p[0] for p in pairs if p[1] != p[2]]}
    if n == 0:
        return result
    xs, ys = [p[1] for p in pairs], [p[2] for p in pairs]
    result["agree"] = sum(x == y for x, y in zip(xs, ys)) / n
    if is_overall:
        result["within1"] = sum(abs(x - y) <= 1 for x, y in zip(xs, ys)) / n
    # Kappa needs at least two different values in the data.
    if len(set(xs) | set(ys)) > 1:
        result["kappa"] = _kappa(xs, ys, weights="quadratic" if is_overall else None)
    return result


def compare(a: dict, b: dict, fields: list[str]) -> list[dict]:
    return [compare_field(a, b, f) for f in fields]


def available_fields(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    cols = rows[0].keys()
    return [f for f in ["overall", *BOOL_FIELDS] if f in cols]


def fmt(x: float, pct: bool = False) -> str:
    if isinstance(x, float) and math.isnan(x):
        return "n/a"
    return f"{x:.0%}" if pct else f"{x:.2f}"


def print_report(results: list[dict], title: str) -> None:
    print(f"\n{title}")
    print(f"{'field':<12}{'n':>4}{'agree':>8}{'within1':>9}{'kappa':>8}  disagreements")
    for r in results:
        print(f"{r['field']:<12}{r['n']:>4}{fmt(r['agree'], True):>8}{fmt(r['within1'], True):>9}"
              f"{fmt(r['kappa']):>8}  {', '.join(r['disagreements'])}")
    print("kappa n/a means one side gave the same value every time, so kappa is undefined.")


def by_id(rows: list[dict]) -> dict:
    return {r["id"]: r for r in rows if not r.get("error")}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scores", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--compare", type=Path, help="Second score file. Default: the answer key.")
    group.add_argument("--raters", nargs=2, metavar=("COL_A", "COL_B"),
                       help="Compare two overall-score columns in one file.")
    args = parser.parse_args(argv)

    rows = read_csv(args.scores)

    if args.raters:
        col_a, col_b = args.raters
        a = {r["id"]: {"overall": r.get(col_a)} for r in rows}
        b = {r["id"]: {"overall": r.get(col_b)} for r in rows}
        print_report(compare(a, b, ["overall"]), f"{col_a} vs {col_b}")
        return

    a = by_id(rows)
    if args.compare:
        b = by_id(read_csv(args.compare))
        title = f"{args.scores.name} vs {args.compare.name}"
    else:
        b = load_key()
        title = f"{args.scores.name} vs answer key"
    fields = available_fields(rows)
    print_report(compare(a, b, fields), title)


if __name__ == "__main__":
    main()
