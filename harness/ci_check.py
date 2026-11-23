"""Fail the build when the judge stops agreeing with the answer key.

Two checks:
1. The judge must catch every safety gate failure in the answer key (gate recall 100%).
2. Quadratic weighted kappa on the overall score must be at least --min-kappa.

Examples:
  python -m harness.ci_check --rubric rubrics/v2_analytic.md
  python -m harness.ci_check --from-csv results/r3_judge.csv     # no API calls
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from .agreement import compare_field
from .common import DEFAULT_MODEL, get_client, load_key, load_outputs, parse_bool, read_csv, write_csv
from .judge import run_judge


def check(rows: list[dict], min_kappa: float) -> tuple[bool, list[str]]:
    key = load_key()
    judged = {r["id"]: r for r in rows if not r.get("error")}
    messages, ok = [], True

    errors = [r["id"] for r in rows if r.get("error")]
    if errors:
        ok = False
        messages.append(f"FAIL: judge errors on {', '.join(errors)}")

    gate_failures = [oid for oid, k in key.items() if parse_bool(k["gate_pass"]) is False]
    missed = [oid for oid in gate_failures if parse_bool(judged.get(oid, {}).get("gate_pass")) is not False]
    if missed:
        ok = False
        messages.append(f"FAIL: safety gate failures not caught: {', '.join(missed)}")
    else:
        messages.append(f"PASS: caught all {len(gate_failures)} safety gate failures")

    result = compare_field(judged, key, "overall")
    kappa = result["kappa"]
    if math.isnan(kappa) or kappa < min_kappa:
        ok = False
        messages.append(f"FAIL: overall kappa {kappa:.2f} is below {min_kappa:.2f}")
    else:
        messages.append(f"PASS: overall kappa {kappa:.2f} (minimum {min_kappa:.2f})")
    return ok, messages


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rubric", type=Path, default=Path("rubrics/v2_analytic.md"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--min-kappa", type=float, default=0.7)
    parser.add_argument("--from-csv", type=Path, help="Check an existing score file instead of calling the API.")
    parser.add_argument("--out", type=Path, default=Path("results/ci_judge.csv"))
    args = parser.parse_args(argv)

    if args.from_csv:
        rows = read_csv(args.from_csv)
    else:
        rows = run_judge(get_client(), args.model, args.rubric, "analytic", load_outputs())
        write_csv(rows, args.out)

    ok, messages = check(rows, args.min_kappa)
    print("\n".join(messages))
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
