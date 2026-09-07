"""Publish the measured test coverage, and hold two floors.

Coverage is a weak signal used as a strong one, so this does not chase a single headline number.
It holds two floors instead:

* an **overall floor**, low enough that ordinary work does not trip it and high enough that a
  large untested addition does;
* a **higher floor on the modules that enforce the project's own rules**. Those are the ones where
  a silent regression does not produce a wrong number — it produces a wrong number that nothing
  notices. RBAC, the KPI contract, the quota ledger, the provenance guard, the auditor and the
  budget are each the sole mechanism behind a promise made in CLAUDE.md, so each is held to a
  standard the rest of the tree is not.

The report goes to docs/results/coverage.json, like every other measurement here, so the figure in
the README is one this wrote rather than one someone typed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

OVERALL_FLOOR = 75.0
CRITICAL_FLOOR = 85.0

# Each entry names a rule from CLAUDE.md and the module that is the only thing enforcing it.
CRITICAL: dict[str, str] = {
    "api/auth.py": "RBAC: roles are asserted by the server, never by the caller",
    "api/kpi.py": "every number crossing the API carries the SQL that produced it",
    "api/limits.py": "the endpoints that spend budget are rate limited",
    "agents/auditor.py": "every run is audited; an uncited memo is rejected",
    "agents/budget.py": "agents run under a request budget and a kill switch",
    "agents/memory.py": "retrieved memories are untrusted and quarantined",
    "security/fencing.py": "untrusted text cannot break out of the fence that quotes it",
    "rag/quota.py": "zero paid inference: allowances are counted, not assumed",
    "etl/results.py": "generated results are routed away from the real ones",
    "scripts/guard_synthetic.py": "generated data cannot reach a Term 4 artefact",
}


def summarise(coverage: dict[str, Any]) -> dict[str, Any]:
    files = coverage["files"]
    missing = sorted(path for path in CRITICAL if path not in files)

    critical = [
        {
            "path": path,
            "rule": rule,
            "percent": round(files[path]["summary"]["percent_covered"], 1),
            "uncovered_lines": len(files[path]["missing_lines"]),
        }
        for path, rule in sorted(CRITICAL.items())
        if path in files
    ]
    overall = round(coverage["totals"]["percent_covered"], 2)

    failures = []
    if overall < OVERALL_FLOOR:
        failures.append(f"overall coverage {overall}% is below the {OVERALL_FLOOR}% floor")
    for path in missing:
        # A module that vanished from the report is not a pass. It is usually a rename, and the
        # rule it enforced is now unwatched.
        failures.append(f"{path} is named as rule-enforcing but was not measured")
    for row in critical:
        if row["percent"] < CRITICAL_FLOOR:
            failures.append(
                f"{row['path']} at {row['percent']}% is below the {CRITICAL_FLOOR}% floor "
                f"for rule-enforcing modules ({row['rule']})"
            )

    return {
        "provenance": "REAL",
        "note": (
            "Line coverage of the Python tree, measured by pytest-cov in CI. The critical list is "
            "the set of modules that are the sole mechanism behind a rule in CLAUDE.md; they are "
            "held to a higher floor than the rest."
        ),
        "overall_percent": overall,
        "overall_floor": OVERALL_FLOOR,
        "statements": coverage["totals"]["num_statements"],
        "missing_statements": coverage["totals"]["missing_lines"],
        "critical_floor": CRITICAL_FLOOR,
        "critical_modules": critical,
        "failures": failures,
    }


# CI runs tests that a laptop skips — the Postgres store suite needs a live server — so the
# committed figure and a fresh one are never identical. Drift worth catching is larger than that.
PUBLISHED_TOLERANCE = 3.0


def compare_to_published(fresh: dict[str, Any], published_path: Path) -> list[str]:
    """Whether the committed figure still describes what the suite actually covers."""
    if not published_path.exists():
        return [f"{published_path.name} is missing; run this without --gate and commit the result"]
    try:
        published = json.loads(published_path.read_text())
    except json.JSONDecodeError as exc:
        return [f"{published_path.name} is not readable JSON: {exc}"]

    drift = abs(published["overall_percent"] - fresh["overall_percent"])
    if drift > PUBLISHED_TOLERANCE:
        return [
            f"the committed coverage figure is {published['overall_percent']}% but this run "
            f"measured {fresh['overall_percent']}% — a {drift:.1f} point drift. Re-run "
            f"scripts.coverage_gate and commit the result."
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, default=ROOT / "coverage.json")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--gate", action="store_true", help="exit non-zero if a floor is breached")
    parser.add_argument(
        "--compare-published",
        action="store_true",
        help="also check the committed figure has not drifted from this run",
    )
    args = parser.parse_args(argv)

    if not args.coverage.exists():
        print(f"no coverage report at {args.coverage}; run pytest with --cov-report=json first")
        return 1

    report = summarise(json.loads(args.coverage.read_text()))

    from etl.results import result_path

    out = args.out or result_path("coverage.json", "REAL")
    if args.compare_published:
        report["failures"].extend(compare_to_published(report, out))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")

    print(f"overall {report['overall_percent']}% (floor {OVERALL_FLOOR}%)")
    for row in report["critical_modules"]:
        mark = " " if row["percent"] >= CRITICAL_FLOOR else "!"
        print(f" {mark} {row['percent']:5.1f}%  {row['path']:28} {row['rule']}")
    print(f"\nwrote {out}")

    for failure in report["failures"]:
        print(f"::error::{failure}")
    return 1 if (args.gate and report["failures"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
