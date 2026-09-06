#!/usr/bin/env python
"""Refuse to let generated data reach a graded artefact.

The data ladder allows a labelled synthetic stand-in so the models and the interface can be built
while the publisher is unreachable. That is fine for development and dishonest in a report. This
guard is the mechanism that keeps the two apart, rather than relying on remembering.

It fails when the database holds synthetic rows, or when a results file was produced from them,
and it is run before any Term 4 artefact is generated as well as on every push.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "yieldmap.duckdb"
DEFAULT_RESULTS = ROOT / "docs" / "results"

# Reports about retrieval describe what the publisher served and legitimately mention provenance;
# flagging them would make the guard cry wolf on its own bookkeeping. Results computed *from*
# synthetic data are not exempted — they live in docs/results/synthetic/, which is not scanned.
EXEMPT_RESULT_FILES = {"source_probe.json", "source_discovery.json", "spa_discovery.json"}


def db_provenance(db_path: Path) -> dict[str, dict[str, int]]:
    """Row counts per provenance value, per table."""
    if not db_path.exists():
        return {}
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = [r[0] for r in con.execute("show tables").fetchall()]
        out: dict[str, dict[str, int]] = {}
        for table in tables:
            cols = [r[0] for r in con.execute(f"describe {table}").fetchall()]
            if "provenance" not in cols:
                continue
            rows = con.execute(
                f"select provenance, count(*) from {table} group by 1"  # noqa: S608 - table from show tables
            ).fetchall()
            out[table] = {str(p): int(n) for p, n in rows}
        return out
    finally:
        con.close()


def results_provenance(results_dir: Path) -> list[str]:
    """Result files that are not demonstrably real.

    The check is that a file *declares* provenance REAL, not that it avoids saying SYNTHETIC.
    Inferring from the absence of a word is a weak test: it passed a profile of generated data
    simply because that file happened not to contain the string. Requiring a declaration means a
    model that forgets to stamp its output is caught rather than quietly trusted.
    """
    flagged: list[str] = []
    if not results_dir.exists():
        return flagged
    for path in sorted(results_dir.glob("*.json")):
        if path.name in EXEMPT_RESULT_FILES:
            continue
        try:
            body = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            flagged.append(f"{path.name} (unreadable, so its provenance cannot be established)")
            continue
        declared = body.get("provenance") if isinstance(body, dict) else None
        if declared == "REAL":
            continue
        if declared is None:
            flagged.append(f"{path.name} (declares no provenance)")
        else:
            flagged.append(f"{path.name} (declares provenance {declared})")
    return flagged


def check(db_path: Path, results_dir: Path) -> tuple[bool, list[str]]:
    """Return (clean, reasons)."""
    reasons: list[str] = []

    for table, counts in db_provenance(db_path).items():
        synthetic = counts.get("SYNTHETIC", 0)
        if synthetic:
            total = sum(counts.values())
            reasons.append(
                f"{db_path.name}: table '{table}' holds {synthetic:,}/{total:,} synthetic rows"
            )

    for name in results_provenance(results_dir):
        reasons.append(f"{results_dir.name}/{name} is not established as real")

    return (not reasons), reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="write the provenance summary as JSON",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="report without failing; for development, never for artefact generation",
    )
    args = parser.parse_args(argv)

    clean, reasons = check(args.db, args.results)
    summary = {
        "clean": clean,
        "db": str(args.db),
        "db_provenance": db_provenance(args.db),
        "flagged_results": results_provenance(args.results),
        "reasons": reasons,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(summary, indent=2))

    if clean:
        print("provenance guard: clean — no synthetic data in the database or results")
        return 0

    print("provenance guard: BLOCKED — generated data must not reach a graded artefact")
    for reason in reasons:
        print(f"  - {reason}")
    print(
        "\nTo proceed: load real publisher data (see docs/datasets.md for the retrieval ladder), "
        "then rebuild the database and the results."
    )
    return 0 if args.warn_only else 1


if __name__ == "__main__":
    sys.exit(main())
