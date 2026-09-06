"""Clean a raw drop into the canonical tables, and load them into DuckDB.

The canonicalisation rules live in ``etl.canon`` as plain Python, which is the readable reference.
This module expresses the same rules as Polars expressions so they run over millions of rows at
speed, and the tests assert the two agree on every fixture row. That way the fast path can never
quietly drift from the rules the documentation describes.

Every row carries a ``provenance`` value. ``REAL`` means it came from the publisher;
``SYNTHETIC`` means it was generated to exercise the pipeline. Nothing downstream is allowed to
mix them silently, and no synthetic row may reach a Term 4 artefact.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb
import polars as pl

from etl.canon import (
    EXISTING_MARKERS,
    MAX_AREA_SQM,
    MAX_PRICE_AED,
    MAX_ROOMS,
    MIN_AREA_SQM,
    MIN_PRICE_AED,
    NOT_A_ROOM_COUNT,
    OFFPLAN_MARKERS,
    PROPERTY_TYPES,
    ROOM_WORDS,
)
from etl.results import result_path
from etl.schema import (
    RENT_ALIASES,
    TRANSACTION_ALIASES,
    ColumnMapping,
    map_columns,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "yieldmap.duckdb"

Provenance = Literal["REAL", "SYNTHETIC"]

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ------------------------------------------------------------------ expressions


def expr_clean_text(col: str) -> pl.Expr:
    """Trim and collapse internal whitespace; empty becomes null."""
    trimmed = pl.col(col).cast(pl.String).str.strip_chars().str.replace_all(r"\s+", " ")
    return pl.when(trimmed == "").then(None).otherwise(trimmed)


def expr_area_key(col: str) -> pl.Expr:
    """Vectorised twin of ``canon.canon_area_key``."""
    return (
        pl.col(col)
        .cast(pl.String)
        .str.strip_chars()
        .str.to_lowercase()
        # Apostrophes are deleted, not spaced: "Za'abeel" and "Zaabeel" are one place.
        .str.replace_all(r"[’ʼʻ'`]", "")
        .str.replace_all(r"[^\w\s]", " ")
        .str.replace_all(r"\s+", " ")
        .str.strip_chars()
        .replace("", None)
    )


def expr_rooms(col: str) -> pl.Expr:
    """Vectorised twin of ``canon.canon_rooms``."""
    text = pl.col(col).cast(pl.String).str.strip_chars().str.to_lowercase()
    text = text.str.replace_all(r"\s+", " ")

    # Words first ("studio", "1 b/r"), then a numeric pattern, then a bare number.
    from_words = text.replace_strict(ROOM_WORDS, default=None, return_dtype=pl.Int32)
    from_pattern = text.str.extract(r"(\d{1,2})\s*(?:b\s*/?\s*r|bed|bedroom|br)\b", 1).cast(
        pl.Int32
    )
    from_digits = pl.when(text.str.contains(r"^\d{1,2}$")).then(text.cast(pl.Int32)).otherwise(None)

    combined = pl.coalesce([from_words, from_pattern, from_digits])
    return (
        pl.when(text.is_in(list(NOT_A_ROOM_COUNT)) | text.is_null())
        .then(None)
        .when((combined < 0) | (combined > MAX_ROOMS))
        .then(None)
        .otherwise(combined)
        .cast(pl.Int32)
    )


def expr_property_type(col: str) -> pl.Expr:
    """Vectorised twin of ``canon.canon_property_type``."""
    text = (
        pl.col(col)
        .cast(pl.String)
        .str.strip_chars()
        .str.to_lowercase()
        .str.replace_all(r"\s+", " ")
    )
    return text.replace_strict(PROPERTY_TYPES, default=None, return_dtype=pl.String)


def expr_is_offplan(reg_col: str | None, proc_col: str | None) -> pl.Expr:
    """Vectorised twin of ``canon.canon_is_offplan``.

    Registration type is authoritative; the procedure name is the fallback for blank rows.
    """

    def verdict(col: str) -> pl.Expr:
        text = pl.col(col).cast(pl.String).str.strip_chars().str.to_lowercase()
        offplan = pl.any_horizontal([text.str.contains(m, literal=True) for m in OFFPLAN_MARKERS])
        existing = pl.any_horizontal([text.str.contains(m, literal=True) for m in EXISTING_MARKERS])
        return pl.when(offplan).then(True).when(existing).then(False).otherwise(None)

    parts = [verdict(c) for c in (reg_col, proc_col) if c]
    if not parts:
        return pl.lit(None, dtype=pl.Boolean)
    return pl.coalesce(parts).cast(pl.Boolean)


def expr_bounded_float(col: str, low: float, high: float) -> pl.Expr:
    """Cast to float and null out anything outside the possible range."""
    number = (
        pl.col(col)
        .cast(pl.String)
        .str.replace_all(",", "")
        .str.replace_all("AED", "")
        .str.strip_chars()
        .cast(pl.Float64, strict=False)
    )
    return pl.when(number.is_between(low, high)).then(number).otherwise(None)


def expr_timestamp(col: str) -> pl.Expr:
    """Parse a date across the formats open-data portals publish."""
    raw = pl.col(col).cast(pl.String).str.strip_chars()
    attempts = [raw.str.to_date(fmt, strict=False) for fmt in DATE_FORMATS]
    attempts.append(raw.str.to_datetime(strict=False).dt.date())
    return pl.coalesce(attempts)


# ----------------------------------------------------------------------- clean


def clean_transactions(
    lf: pl.LazyFrame, mapping: ColumnMapping, *, provenance: Provenance = "REAL"
) -> pl.LazyFrame:
    """Canonicalise a transactions frame. Rows missing a required field are dropped."""
    r = mapping.resolved
    out = lf.select(
        [
            expr_timestamp(r["ts"]).alias("ts"),
            expr_clean_text(r["area_name"]).alias("area_name"),
            expr_area_key(r["area_name"]).alias("area_key"),
            expr_bounded_float(r["price_aed"], MIN_PRICE_AED, MAX_PRICE_AED).alias("price_aed"),
            *_optional_transaction_columns(r),
            pl.lit(provenance).alias("provenance"),
        ]
    )
    out = out.with_columns(
        pl.when(pl.col("area_sqm") > 0)
        .then(pl.col("price_aed") / pl.col("area_sqm"))
        .otherwise(None)
        .alias("price_per_sqm")
    )
    return out.drop_nulls(subset=["ts", "area_key", "price_aed"])


def _optional_transaction_columns(r: dict[str, str]) -> list[pl.Expr]:
    """Columns that may be absent: emit a typed null so the schema is stable either way."""
    out: list[pl.Expr] = []

    def text(canonical: str) -> pl.Expr:
        col = r.get(canonical)
        return (
            expr_clean_text(col).alias(canonical)
            if col
            else pl.lit(None, dtype=pl.String).alias(canonical)
        )

    out += [text(c) for c in ("building_name", "project_name", "procedure", "property_sub_type")]
    out.append(
        expr_property_type(r["property_type"]).alias("property_type")
        if r.get("property_type")
        else pl.lit(None, dtype=pl.String).alias("property_type")
    )
    out.append(
        expr_rooms(r["rooms_raw"]).alias("rooms")
        if r.get("rooms_raw")
        else pl.lit(None, dtype=pl.Int32).alias("rooms")
    )
    out.append(
        expr_bounded_float(r["area_sqm"], MIN_AREA_SQM, MAX_AREA_SQM).alias("area_sqm")
        if r.get("area_sqm")
        else pl.lit(None, dtype=pl.Float64).alias("area_sqm")
    )
    out.append(expr_is_offplan(r.get("reg_type"), r.get("procedure")).alias("is_offplan"))
    out.append(
        expr_clean_text(r["transaction_id"]).alias("transaction_id")
        if r.get("transaction_id")
        else pl.lit(None, dtype=pl.String).alias("transaction_id")
    )
    return out


def clean_rent_contracts(
    lf: pl.LazyFrame, mapping: ColumnMapping, *, provenance: Provenance = "REAL"
) -> pl.LazyFrame:
    """Canonicalise a rent-contract frame."""
    r = mapping.resolved

    def text(canonical: str) -> pl.Expr:
        col = r.get(canonical)
        return (
            expr_clean_text(col).alias(canonical)
            if col
            else pl.lit(None, dtype=pl.String).alias(canonical)
        )

    out = lf.select(
        [
            expr_clean_text(r["contract_id"]).alias("contract_id")
            if r.get("contract_id")
            else pl.lit(None, dtype=pl.String).alias("contract_id"),
            expr_timestamp(r["start"]).alias("start")
            if r.get("start")
            else pl.lit(None, dtype=pl.Date).alias("start"),
            expr_timestamp(r["end"]).alias("end")
            if r.get("end")
            else pl.lit(None, dtype=pl.Date).alias("end"),
            expr_clean_text(r["area_name"]).alias("area_name"),
            expr_area_key(r["area_name"]).alias("area_key"),
            text("building_name"),
            text("project_name"),
            expr_property_type(r["property_type"]).alias("property_type")
            if r.get("property_type")
            else pl.lit(None, dtype=pl.String).alias("property_type"),
            expr_rooms(r["rooms_raw"]).alias("rooms")
            if r.get("rooms_raw")
            else pl.lit(None, dtype=pl.Int32).alias("rooms"),
            expr_bounded_float(r["area_sqm"], MIN_AREA_SQM, MAX_AREA_SQM).alias("area_sqm")
            if r.get("area_sqm")
            else pl.lit(None, dtype=pl.Float64).alias("area_sqm"),
            expr_bounded_float(r["annual_rent_aed"], MIN_PRICE_AED, MAX_PRICE_AED).alias(
                "annual_rent_aed"
            ),
            text("contract_type"),
            pl.lit(provenance).alias("provenance"),
        ]
    )
    return out.drop_nulls(subset=["area_key", "annual_rent_aed"])


def dedupe(lf: pl.LazyFrame, *, id_col: str | None = None) -> pl.LazyFrame:
    """Drop duplicate rows.

    Publishers re-publish overlapping windows, so the nightly job sees the same transaction more
    than once. When an identifier is present it decides; otherwise the whole canonical row does,
    which is conservative — it keeps two genuinely identical sales rather than losing one.
    """
    if id_col:
        return lf.filter(pl.col(id_col).is_not_null()).unique(subset=[id_col], keep="first")
    return lf.unique(keep="first")


# ------------------------------------------------------------------------ load


def load_duckdb(
    tables: dict[str, pl.DataFrame], db_path: Path, *, replace: bool = True
) -> dict[str, int]:
    """Write the canonical tables into DuckDB and return the row count of each."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    con = duckdb.connect(str(db_path))
    try:
        for name, df in tables.items():
            con.register("_incoming", df)
            if replace:
                con.execute(f"create or replace table {name} as select * from _incoming")
            else:
                con.execute(f"create table if not exists {name} as select * from _incoming limit 0")
                con.execute(f"insert into {name} select * from _incoming")
            con.unregister("_incoming")
            counts[name] = con.execute(f"select count(*) from {name}").fetchone()[0]
        con.execute("checkpoint")
    finally:
        con.close()
    return counts


def area_coverage(areas_csv: Path, area_keys: list[str]) -> dict[str, Any]:
    """Which areas in the data have a curated centroid, and which do not.

    Reported rather than silently filled: an area without coordinates renders as "no location"
    instead of appearing at the origin, and the gap is visible so it can be closed.
    """
    from etl.canon import canon_area_key

    curated = pl.read_csv(areas_csv)
    curated_keys = {canon_area_key(n) for n in curated["dld_name"].to_list()}
    present = {k for k in area_keys if k}
    missing = sorted(present - curated_keys)
    return {
        "areas_in_data": len(present),
        "areas_with_centroid": len(present & curated_keys),
        "coverage": round(len(present & curated_keys) / len(present), 4) if present else 0.0,
        "missing_centroid": missing[:100],
        "n_missing_centroid": len(missing),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--areas", type=Path, default=ROOT / "data" / "areas.csv")
    parser.add_argument("--provenance", choices=["REAL", "SYNTHETIC"], default="REAL")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="defaults to docs/results/clean.json, or docs/results/synthetic/ when generated",
    )
    args = parser.parse_args(argv)
    out = args.out or result_path("clean.json", args.provenance)

    report: dict[str, Any] = {"generated_at": _now(), "provenance": args.provenance, "tables": {}}
    tables: dict[str, pl.DataFrame] = {}

    for key, aliases, cleaner, id_col in (
        ("transactions", TRANSACTION_ALIASES, clean_transactions, "transaction_id"),
        ("rent_contracts", RENT_ALIASES, clean_rent_contracts, "contract_id"),
    ):
        path = next(
            (p for p in args.raw.glob(f"{key}.*") if p.suffix in {".csv", ".parquet"}), None
        )
        if path is None:
            print(f"{key}: no file in {args.raw}")
            continue
        lf = (
            pl.scan_parquet(path)
            if path.suffix == ".parquet"
            else pl.scan_csv(
                path, infer_schema_length=10_000, ignore_errors=True, truncate_ragged_lines=True
            )
        )
        columns = lf.collect_schema().names()
        mapping = map_columns(columns, aliases)
        if not mapping.usable:
            print(f"{key}: unusable, missing {mapping.missing_required}")
            report["tables"][key] = {"error": "missing required columns"}
            continue
        cleaned = dedupe(
            cleaner(lf, mapping, provenance=args.provenance),
            id_col=id_col if id_col in mapping.resolved else None,
        ).collect()
        tables[key] = cleaned
        report["tables"][key] = {
            "source": path.name,
            "rows_in": int(lf.select(pl.len()).collect().item()),
            "rows_out": cleaned.height,
            "unmapped_columns": list(mapping.unmapped),
            "missing_optional": list(mapping.missing),
        }
        print(f"{key}: {report['tables'][key]['rows_in']:,} -> {cleaned.height:,} rows")

    if not tables:
        print("nothing to clean")
        return 1

    report["counts"] = load_duckdb(tables, args.db)
    if "transactions" in tables and args.areas.exists():
        report["area_coverage"] = area_coverage(
            args.areas, tables["transactions"]["area_key"].to_list()
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"wrote {args.db} and {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
