"""Take the files an operator downloaded and turn them into the warehouse.

The bulk CSVs are published on a host that refuses datacenter addresses, so no automated job in
this project can fetch them — but any person on an ordinary connection can. This is the seam
between those two facts, and it exists so the handoff is one command rather than a list of
instructions someone has to follow correctly.

It works out which file is which by looking at the columns rather than the name, because a
download is called whatever the portal decided to call it that day. It unpacks archives, strips
the byte-order mark Excel adds, and refuses rather than guesses when a file matches nothing.

    uv run python -m scripts.ingest_upload ~/Downloads
    uv run python -m scripts.ingest_upload transactions.csv rents.csv --build

Turning real data into the warehouse also flips provenance from SYNTHETIC to REAL, which is what
unblocks the Term 4 artefacts: the guard stops blocking once no generated row remains.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

import polars as pl

from etl.schema import RENT_ALIASES, TRANSACTION_ALIASES, map_columns

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

TABLES = (
    ("transactions", TRANSACTION_ALIASES),
    ("rent_contracts", RENT_ALIASES),
)

READABLE = {".csv", ".parquet", ".txt"}


def candidates(paths: list[Path]) -> list[Path]:
    """Every readable file among the given files and directories, archives unpacked."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(p for p in sorted(path.rglob("*")) if p.suffix.lower() in READABLE)
            found.extend(p for p in sorted(path.rglob("*.zip")))
        elif path.suffix.lower() == ".zip" or path.suffix.lower() in READABLE:
            found.append(path)
    return found


def unpack(archive: Path, into: Path) -> list[Path]:
    out: list[Path] = []
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            if Path(name).suffix.lower() not in READABLE:
                continue
            target = into / Path(name).name
            with zf.open(name) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            out.append(target)
    return out


def shown(path: Path) -> str:
    """A path relative to the repository when it is inside it, absolute when it is not.

    `--raw` can point anywhere, and `relative_to` raises rather than falling back — so the tidier
    output was a crash for anyone staging a drop outside the checkout.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def columns_of(path: Path) -> list[str] | None:
    """The header, or None if this is not a table this project can read."""
    try:
        if path.suffix.lower() == ".parquet":
            return pl.scan_parquet(path).collect_schema().names()
        return (
            pl.scan_csv(
                path, infer_schema_length=200, ignore_errors=True, truncate_ragged_lines=True
            )
            .collect_schema()
            .names()
        )
    except Exception:  # noqa: BLE001 - an unreadable file is a fact about the file, not an error
        return None


def identify(path: Path) -> tuple[str, int, list[str]] | None:
    """Which canonical table this file is, by how many required columns it satisfies.

    Named by content rather than filename because a download is called whatever the portal decided
    to call it. A file that satisfies neither table's required columns is reported, not guessed at.
    """
    columns = columns_of(path)
    if not columns:
        return None
    best: tuple[str, int, list[str]] | None = None
    for key, aliases in TABLES:
        mapping = map_columns(columns, aliases)
        if not mapping.usable:
            continue
        score = len(mapping.resolved)
        if best is None or score > best[1]:
            best = (key, score, list(mapping.missing_required))
    return best


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="files or a directory of downloads")
    parser.add_argument("--raw", type=Path, default=RAW)
    parser.add_argument(
        "--build", action="store_true", help="rebuild the warehouse and models afterwards"
    )
    parser.add_argument("--dry-run", action="store_true", help="report what would happen")
    args = parser.parse_args(argv)

    args.raw.mkdir(parents=True, exist_ok=True)
    staging = args.raw / "_unpacked"

    files: list[Path] = []
    for path in candidates([p.expanduser() for p in args.paths]):
        if path.suffix.lower() == ".zip":
            staging.mkdir(parents=True, exist_ok=True)
            unpacked = unpack(path, staging)
            print(f"unpacked {path.name}: {len(unpacked)} file(s)")
            files.extend(unpacked)
        else:
            files.append(path)

    if not files:
        print("nothing readable in the paths given", file=sys.stderr)
        return 1

    # Every file that matches a table is kept, not just the best one.
    #
    # The Land Department's own portal exports a *date range* rather than a bulk file, so the
    # realistic download is several files — one per year, or per month — that all describe the
    # same table. An earlier version of this kept whichever had the most mapped columns and
    # silently dropped the rest, which for that download shape loses almost everything while
    # printing a confident success line.
    #
    # Overlapping ranges cost nothing: etl.clean dedupes, by transaction id where there is one and
    # by whole row otherwise. So downloading 2020-2024 and then 2023-2025 is safe.
    matched: dict[str, list[tuple[Path, int]]] = {}
    unmatched: list[tuple[Path, str]] = []
    for path in files:
        verdict = identify(path)
        if verdict is None:
            unmatched.append((path, "not a readable table"))
            continue
        key, score, _ = verdict
        matched.setdefault(key, []).append((path, score))

    for key, _ in TABLES:
        if key in matched:
            parts = matched[key]
            size = sum(p.stat().st_size for p, _ in parts) / 1024 / 1024
            best = max(score for _, score in parts)
            noun = "file" if len(parts) == 1 else "files"
            print(f"{key:16} <- {len(parts)} {noun}  ({size:.1f} MB, {best} mapped columns)")
            for part, _ in sorted(parts, key=lambda x: x[0].name):
                print(f"                     {part.name}")
        else:
            print(f"{key:16} <- MISSING")

    for path, why in unmatched:
        print(f"  ignored {path.name}: {why}")

    if not matched:
        print(
            "\nNone of those files matched a table this project reads. The transactions extract "
            "needs a date, an area and a price; the rent extract needs an area and an annual "
            "amount. Check docs/datasets.md for the exact columns.",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    for key, parts in matched.items():
        for existing in args.raw.glob(f"{key}.*"):
            existing.unlink()
        for existing in args.raw.glob(f"{key}__*"):
            existing.unlink()

        ordered = sorted(parts, key=lambda x: x[0].name)
        if len(ordered) == 1:
            path, _ = ordered[0]
            destination = args.raw / f"{key}{path.suffix.lower()}"
            shutil.copy2(path, destination)
            print(f"wrote {shown(destination)}")
            continue

        # Several parts of one table. They are kept as separate files rather than concatenated
        # here: the reader already globs them, and stitching CSVs by hand means deciding what to
        # do about headers, encodings and a partial last line — three ways to corrupt a dataset
        # silently, for no benefit.
        for i, (path, _) in enumerate(ordered):
            destination = args.raw / f"{key}__{i:03d}{path.suffix.lower()}"
            shutil.copy2(path, destination)
        print(f"wrote {len(ordered)} parts for {key} into {shown(args.raw)}")

    # The marker is what makes every downstream stage stamp rows SYNTHETIC. Real files replace
    # generated ones, so it goes — and with it the block on Term 4 artefacts.
    marker = args.raw / "SYNTHETIC"
    if marker.exists():
        marker.unlink()
        print("removed the SYNTHETIC marker: this drop is real")

    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)

    missing = [k for k, _ in TABLES if k not in matched]
    if missing:
        print(f"\nStill missing: {', '.join(missing)}. The build will skip those tables.")

    if args.build:
        import subprocess

        print("\nrebuilding…")
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "scripts.build_all", "--force"], cwd=ROOT
        )
        return result.returncode

    print("\nNext: uv run python -m scripts.build_all --force")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
