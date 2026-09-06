"""Profile a raw data drop: what is actually in these files.

Written before any modelling, because the master plan's row counts and column counts are claims
about the publisher's data that this project has to verify rather than repeat. Everything the
report says about the shape of the data comes from ``docs/results/profile.json``, which this
module produces.

Profiling is lazy and streaming, so an 800 MB transactions CSV does not have to fit in memory.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from etl.results import result_path

ROOT = Path(__file__).resolve().parent.parent

# Cap the distinct-value count: knowing a column has "more than this many" distinct values is
# enough to tell an identifier from a category, and counting all of them on 1.5M rows is waste.
MAX_DISTINCT = 200

DATE_HINT = re.compile(r"(date|_dt$|^dt_|time|period|month|year)", re.IGNORECASE)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _is_date_like(name: str, dtype: pl.DataType) -> bool:
    if dtype in (pl.Date, pl.Datetime):
        return True
    return dtype == pl.String and bool(DATE_HINT.search(name))


def _parse_dates(series: pl.Series) -> pl.Series | None:
    """Best-effort date parse across the formats open-data portals actually publish."""
    if series.dtype in (pl.Date, pl.Datetime):
        return series
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = series.str.to_date(fmt, strict=False)
        except Exception:  # noqa: BLE001 - a format that does not apply is not an error
            continue
        if parsed.is_not_null().sum() >= max(1, int(0.5 * len(series))):
            return parsed
    return None


def profile_column(df: pl.DataFrame, name: str) -> dict[str, Any]:
    """Describe one column: type, completeness, cardinality, and range where meaningful."""
    s = df.get_column(name)
    n = len(s)
    nulls = int(s.null_count())
    # Open data commonly encodes missing as an empty string rather than a null.
    blanks = int((s == "").sum()) if s.dtype == pl.String else 0
    missing = nulls + blanks

    col: dict[str, Any] = {
        "name": name,
        "dtype": str(s.dtype),
        "nulls": nulls,
        "blanks": blanks,
        "null_rate": round(missing / n, 6) if n else None,
        "n_distinct": None,
        "distinct_capped": False,
    }

    try:
        distinct = int(s.n_unique())
        col["n_distinct"] = min(distinct, MAX_DISTINCT)
        col["distinct_capped"] = distinct > MAX_DISTINCT
    except Exception:  # noqa: BLE001
        pass

    if s.dtype.is_numeric():
        non_null = s.drop_nulls()
        if len(non_null):
            col |= {
                "min": float(non_null.min()),
                "max": float(non_null.max()),
                "mean": float(non_null.mean()),
                "median": float(non_null.median()),
            }
    elif _is_date_like(name, s.dtype):
        parsed = _parse_dates(s.drop_nulls())
        if parsed is not None and parsed.is_not_null().any():
            valid = parsed.drop_nulls()
            col |= {
                "date_min": str(valid.min()),
                "date_max": str(valid.max()),
                "date_parsed_rate": round(len(valid) / max(1, len(s.drop_nulls())), 4),
            }
    elif s.dtype == pl.String:
        top = (
            df.select(pl.col(name))
            .filter(pl.col(name).is_not_null() & (pl.col(name) != ""))
            .group_by(name)
            .len()
            .sort("len", descending=True)
            .head(5)
        )
        col["top_values"] = [
            {"value": r[0], "count": int(r[1])} for r in top.iter_rows() if r[0] is not None
        ]

    return col


def profile_frame(df: pl.DataFrame, *, name: str = "frame") -> dict[str, Any]:
    """Profile an in-memory frame. Split out from file handling so it is testable directly."""
    return {
        "name": name,
        "rows": df.height,
        "columns": df.width,
        "column_names": df.columns,
        "fields": [profile_column(df, c) for c in df.columns],
    }


def profile_file(path: Path, *, sample_rows: int | None = None) -> dict[str, Any]:
    """Profile one CSV or Parquet file.

    ``sample_rows`` profiles only the head, which keeps a nightly job inside its time budget on a
    very large drop. When it is used the profile records that it was a sample, so no downstream
    reader mistakes a sampled count for a full one.
    """
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        lf = pl.scan_parquet(path)
    else:
        lf = pl.scan_csv(
            path,
            infer_schema_length=10_000,
            ignore_errors=True,
            try_parse_dates=False,
            truncate_ragged_lines=True,
        )

    total_rows = int(lf.select(pl.len()).collect().item())
    df = lf.head(sample_rows).collect() if sample_rows else lf.collect()

    prof = profile_frame(df, name=path.stem)
    prof |= {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "bytes": path.stat().st_size,
        "rows": total_rows,
        "rows_profiled": df.height,
        "sampled": bool(sample_rows and df.height < total_rows),
    }
    return prof


def drop_provenance(raw_dir: Path) -> str:
    """Whether this drop came from the publisher or from the generator.

    etl.synthetic leaves a marker file beside the data it writes, so a profile of generated data
    can route itself away from the real results directory rather than relying on someone
    remembering to pass a flag.
    """
    return "SYNTHETIC" if (raw_dir / "SYNTHETIC").exists() else "REAL"


def profile_dir(raw_dir: Path, *, sample_rows: int | None = None) -> dict[str, Any]:
    """Profile every tabular file in a drop directory."""
    files = sorted(p for p in raw_dir.glob("*") if p.suffix.lower() in {".csv", ".parquet", ".txt"})
    datasets: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in files:
        print(f"profiling {path.name} ({path.stat().st_size:,} bytes)", flush=True)
        try:
            datasets.append(profile_file(path, sample_rows=sample_rows))
        except Exception as exc:  # noqa: BLE001 - one bad file must not lose the rest
            errors.append({"path": path.name, "error": f"{type(exc).__name__}: {exc}"})
            print(f"  failed: {exc}", flush=True)

    manifest_path = raw_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None

    return {
        "generated_at": _now(),
        "provenance": drop_provenance(raw_dir),
        "raw_dir": str(raw_dir),
        "n_datasets": len(datasets),
        "total_rows": sum(d["rows"] for d in datasets),
        "errors": errors,
        "manifest": manifest,
        "datasets": datasets,
    }


MARK_START = "<!-- profile:start -->"
MARK_END = "<!-- profile:end -->"


def render_markdown(report: dict[str, Any]) -> str:
    """Render a profile report as the measured-shape table for docs/datasets.md.

    The table in the documentation is generated, never typed, so it cannot drift from the data.
    """
    if not report.get("datasets"):
        return (
            "No profile has been produced yet. Run the ingest workflow "
            "(`.github/workflows/ingest.yml`); it writes `docs/results/profile.json` and "
            "regenerates this table."
        )

    provenance = report.get("provenance", "REAL")
    banner = (
        "> **These figures describe generated data, not the Dubai registry.** The pipeline is "
        "running on the labelled stand-in described above. They are here so the shape of the "
        "pipeline is visible, and must not be cited as facts about Dubai.\n"
        if provenance == "SYNTHETIC"
        else ""
    )
    lines = [
        banner,
        f"Measured on {report['generated_at']} from `{report['raw_dir']}` (provenance: {provenance}).",
        "",
        "| Dataset | Rows | Columns | Date range | Worst null rate | Size |",
        "|---|---:|---:|---|---:|---:|",
    ]
    for ds in report["datasets"]:
        dated = [f for f in ds["fields"] if "date_min" in f]
        span = (
            f"{min(f['date_min'] for f in dated)} to {max(f['date_max'] for f in dated)}"
            if dated
            else "not dated"
        )
        rates = [f["null_rate"] for f in ds["fields"] if f["null_rate"] is not None]
        worst = max(rates) if rates else 0.0
        worst_col = ""
        if rates:
            worst_field = max(
                (f for f in ds["fields"] if f["null_rate"] is not None),
                key=lambda f: f["null_rate"],
            )
            worst_col = f" (`{worst_field['name']}`)"
        mb = ds.get("bytes", 0) / (1024 * 1024)
        lines.append(
            f"| `{ds['name']}` | {ds['rows']:,} | {ds['columns']} | {span} "
            f"| {worst:.1%}{worst_col} | {mb:,.1f} MB |"
        )

    if report.get("errors"):
        lines += ["", "Files that could not be profiled:", ""]
        lines += [f"- `{e['path']}`: {e['error']}" for e in report["errors"]]

    return "\n".join(lines)


def update_datasets_doc(report: dict[str, Any], doc: Path) -> bool:
    """Replace the generated region of docs/datasets.md. Returns True if the file changed."""
    if not doc.exists():
        return False
    text = doc.read_text()
    block = f"{MARK_START}\n{render_markdown(report)}\n{MARK_END}"
    if MARK_START in text and MARK_END in text:
        head, rest = text.split(MARK_START, 1)
        _, tail = rest.split(MARK_END, 1)
        updated = f"{head}{block}{tail}"
    else:
        updated = f"{text.rstrip()}\n\n## Measured shape\n\n{block}\n"
    if updated != text:
        doc.write_text(updated)
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="defaults to docs/results/profile.json, or docs/results/synthetic/ for a generated drop",
    )
    parser.add_argument("--doc", type=Path, default=ROOT / "docs" / "datasets.md")
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=None,
        help="profile only the first N rows (row counts stay exact)",
    )
    args = parser.parse_args(argv)

    if not args.raw.exists():
        print(f"no raw directory at {args.raw}; nothing to profile")
        return 1

    report = profile_dir(args.raw, sample_rows=args.sample_rows)
    out = args.out or result_path("profile.json", report["provenance"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(
        f"wrote {out}: {report['n_datasets']} datasets, "
        f"{report['total_rows']:,} rows, provenance {report['provenance']}"
    )

    if update_datasets_doc(report, args.doc):
        print(f"updated {args.doc}")
    return 0 if report["n_datasets"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
