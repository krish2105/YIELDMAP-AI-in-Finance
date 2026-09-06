"""Build everything downstream of the raw drop: the warehouse, the models, the index.

Deployment needs this. The database is not committed — it is 6MB of derived data with a
provenance stamp — so a fresh container has to rebuild it before the API can answer anything.
Doing that by hand is how a deployed site ends up showing figures nobody can reproduce.

Each stage is skipped if its output already exists and `--force` was not given, so running this
on a container that already has a warehouse costs nothing.

    uv run python -m scripts.build_all              # build what is missing
    uv run python -m scripts.build_all --force      # rebuild from scratch
    uv run python -m scripts.build_all --synthetic  # generate the stand-in drop first
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "yieldmap.duckdb"
RAW = ROOT / "data" / "raw"
INDEX = ROOT / "rag" / "index.json"

# Order matters: the warehouse before anything that queries it, the index last because it reads
# both the corpus and the finished figures.
MODEL_STAGES = [
    ("hedonic valuation", "finance.hedonic"),
    ("repeat-sales index", "finance.index"),
    ("yields", "finance.yields"),
    ("mortgage", "finance.mortgage"),
    ("discounted cash flow", "finance.dcf"),
    ("forecast", "finance.forecast"),
    ("risk and anomalies", "finance.risk"),
    ("portfolio", "finance.portfolio"),
    ("rent versus buy", "finance.rentbuy"),
    ("developers", "finance.developers"),
    ("unit economics", "finance.unit_economics"),
]


def has_drop() -> bool:
    """Whether data/raw holds a drop the cleaner can read.

    The cleaner accepts either format, so this has to as well — checking only for Parquet made
    this script report "no raw drop" while sitting next to two CSVs.
    """
    return any(p.suffix in {".csv", ".parquet"} for p in RAW.glob("*") if p.is_file())


def run(label: str, module: str, *args: str) -> None:
    started = time.monotonic()
    print(f"→ {label}", flush=True)
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", module, *args], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-4000:], file=sys.stderr)
        raise SystemExit(f"{label} failed ({module})")
    print(f"  {label} in {time.monotonic() - started:.1f}s", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the warehouse, the models and the index.")
    parser.add_argument("--force", action="store_true", help="rebuild even if outputs exist")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="generate the labelled stand-in drop first, for an environment with no real download",
    )
    parser.add_argument(
        "--skip-models",
        action="store_true",
        help="warehouse and index only; the API serves cached results from docs/results",
    )
    args = parser.parse_args(argv)

    started = time.monotonic()

    if args.synthetic and (args.force or not has_drop()):
        run("generating the stand-in drop", "etl.synthetic")

    if args.force or not DB.exists():
        if not has_drop():
            print(
                "no raw drop in data/raw. Pass --synthetic to generate the labelled stand-in, or "
                "fetch a real drop with the ingest workflow first.",
                file=sys.stderr,
            )
            return 1
        # The provenance of the warehouse follows the drop's own marker, so a stand-in cannot be
        # published as real by passing the wrong flag here.
        provenance = "SYNTHETIC" if (RAW / "SYNTHETIC").exists() else "REAL"
        run("cleaning into the warehouse", "etl.clean", "--provenance", provenance)
        run("publishing dimensions", "etl.publish")

    if not args.skip_models:
        for label, module in MODEL_STAGES:
            run(label, module)

    if args.force or not INDEX.exists():
        run("building the retrieval index", "rag.indexer")

    print(f"\nbuilt in {time.monotonic() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
