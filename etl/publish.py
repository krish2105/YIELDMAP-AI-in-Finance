"""Publish the cleaned data: build the dimensions and record what is in the database.

Two jobs.

First, derive the tables that every page reads from but no single model owns: the area dimension
(joining the publisher's area names to the curated centroids) and a freshness table saying what is
loaded, how much of it, as of when, and from where. The freshness table is what the /data page and
the "as of" date on every KPI read.

Second, report. Publishing is idempotent by construction — the dimensions are rebuilt from the
facts each time — so the nightly job can run repeatedly without doubling anything.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from etl.canon import canon_area_key
from etl.results import result_path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "yieldmap.duckdb"

FACT_TABLES = ("transactions", "rent_contracts")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def build_area_dimension(con: duckdb.DuckDBPyConnection, areas_csv: Path) -> int:
    """Build the area dimension from the data, left-joined to the curated centroids.

    Driven by the data rather than the centroid file, so an area the publisher reports but this
    project has no coordinate for still exists as an area — it simply has no location. The
    alternative, an inner join, would silently drop transactions from the whole application.
    """
    with areas_csv.open() as fh:
        rows = [
            {
                "area_key": canon_area_key(r["dld_name"]),
                "dld_name": r["dld_name"],
                "common_name": r["common_name"],
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "coord_confidence": r["coord_confidence"],
            }
            for r in csv.DictReader(fh)
        ]
    con.execute(
        "create or replace table area_centroid (area_key varchar, dld_name varchar, common_name varchar, lat double, lon double, coord_confidence varchar)"
    )
    con.executemany(
        "insert into area_centroid values (?, ?, ?, ?, ?, ?)",
        [tuple(r.values()) for r in rows],
    )

    con.execute(
        """
        create or replace table area as
        with observed as (
            select area_key, any_value(area_name) as area_name, count(*) as n_transactions
            from transactions
            group by area_key
        )
        select
            o.area_key,
            coalesce(c.common_name, o.area_name) as name,
            o.area_name as dld_name,
            c.lat,
            c.lon,
            c.coord_confidence,
            c.area_key is not null as has_location,
            o.n_transactions
        from observed o
        left join area_centroid c using (area_key)
        order by o.n_transactions desc
        """
    )
    return con.execute("select count(*) from area").fetchone()[0]


def build_freshness(
    con: duckdb.DuckDBPyConnection, manifest: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Record what is loaded, how much, as of when, and from which download."""
    by_dataset = {}
    for entry in (manifest or {}).get("files", []):
        if entry.get("dataset"):
            by_dataset[entry["dataset"]] = entry

    tables = {r[0] for r in con.execute("show tables").fetchall()}
    rows: list[dict[str, Any]] = []
    for table in FACT_TABLES:
        if table not in tables:
            continue
        cols = {r[0] for r in con.execute(f"describe {table}").fetchall()}
        date_col = "ts" if "ts" in cols else ("start" if "start" in cols else None)
        as_of = (
            con.execute(f"select max({date_col}) from {table}").fetchone()[0]  # noqa: S608
            if date_col
            else None
        )
        provenances = [
            r[0]
            for r in con.execute(f"select distinct provenance from {table}").fetchall()  # noqa: S608
        ]
        rows.append(
            {
                "table_name": table,
                "rows": con.execute(f"select count(*) from {table}").fetchone()[0],  # noqa: S608
                "as_of": str(as_of) if as_of else None,
                # Mixed provenance is reported as SYNTHETIC: the weaker claim governs the whole
                # table, since a reader cannot tell which rows fed a given aggregate.
                "provenance": "SYNTHETIC" if "SYNTHETIC" in provenances else "REAL",
                "source_sha256": by_dataset.get(table, {}).get("sha256"),
                "refreshed_at": _now(),
            }
        )

    con.execute(
        "create or replace table data_freshness ("
        "table_name varchar, rows bigint, as_of date, provenance varchar, "
        "source_sha256 varchar, refreshed_at varchar)"
    )
    if rows:
        con.executemany(
            "insert into data_freshness values (?, ?, ?, ?, ?, ?)",
            [tuple(r.values()) for r in rows],
        )
    return rows


def publish(db_path: Path, areas_csv: Path, raw_dir: Path) -> dict[str, Any]:
    manifest_path = raw_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None

    con = duckdb.connect(str(db_path))
    try:
        n_areas = build_area_dimension(con, areas_csv)
        freshness = build_freshness(con, manifest)
        located = con.execute("select count(*) from area where has_location").fetchone()[0]
        con.execute("checkpoint")
    finally:
        con.close()

    return {
        "generated_at": _now(),
        "db": str(db_path),
        "areas": n_areas,
        "areas_with_location": located,
        "freshness": freshness,
        "provenance": (
            "SYNTHETIC" if any(f["provenance"] == "SYNTHETIC" for f in freshness) else "REAL"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--areas", type=Path, default=ROOT / "data" / "areas.csv")
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"no database at {args.db}; run etl.clean first")
        return 1

    report = publish(args.db, args.areas, args.raw)
    out = result_path("publish.json", report["provenance"])
    out.write_text(json.dumps(report, indent=2, default=str))
    print(
        f"published: {report['areas']} areas "
        f"({report['areas_with_location']} located), "
        f"{len(report['freshness'])} fact tables, provenance {report['provenance']}"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
