"""Shared plumbing for the finance models.

Two things every model here needs, and neither belongs in the models themselves.

First, a query helper that hands back the SQL alongside the rows. The traceability rule says every
number resolves to a query, and the reliable way to guarantee that is to make the query the thing
that travels, rather than asking each model to remember to record it.

Second, a results writer that stamps provenance and routes the file accordingly, so a figure
computed from the synthetic stand-in physically cannot land in the directory the report reads.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import polars as pl

from etl.results import result_path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "yieldmap.duckdb"


class Query:
    """A SQL string and its result, kept together."""

    __slots__ = ("sql", "params", "frame")

    def __init__(self, sql: str, params: tuple[Any, ...], frame: pl.DataFrame) -> None:
        self.sql = " ".join(sql.split())
        self.params = params
        self.frame = frame

    def __len__(self) -> int:
        return self.frame.height

    @property
    def empty(self) -> bool:
        return self.frame.height == 0


class Warehouse:
    """Read-only access to the analytics database."""

    def __init__(self, db_path: Path | str = DEFAULT_DB) -> None:
        self.path = Path(db_path)
        if not self.path.exists():
            raise FileNotFoundError(
                f"no analytics database at {self.path}. Run `uv run python -m etl.clean` first."
            )
        self._con = duckdb.connect(str(self.path), read_only=True)

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> Query:
        frame = self._con.execute(sql, params).pl()
        return Query(sql, params, frame)

    def scalar(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        row = self._con.execute(sql, params).fetchone()
        return row[0] if row else None

    def provenance(self) -> str:
        """The weakest provenance of any fact table.

        A model reading a table with any synthetic row produces a synthetic result, because a
        reader cannot tell which rows fed an aggregate.
        """
        tables = {r[0] for r in self._con.execute("show tables").fetchall()}
        values: set[str] = set()
        for table in ("transactions", "rent_contracts"):
            if table in tables:
                values |= {
                    r[0]
                    for r in self._con.execute(
                        f"select distinct provenance from {table}"  # noqa: S608 - fixed table names
                    ).fetchall()
                }
        return "SYNTHETIC" if "SYNTHETIC" in values else "REAL"

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> Warehouse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def write_result(name: str, payload: dict[str, Any], provenance: str) -> Path:
    """Write a model's measured output, stamped and routed by provenance."""
    body = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "provenance": provenance,
        **payload,
    }
    path = result_path(name, provenance)  # type: ignore[arg-type]
    path.write_text(json.dumps(body, indent=2, default=str))
    return path


def coefficient_of_variation(values: pl.Series) -> float | None:
    """Dispersion relative to the mean, which is what the confidence badge reads."""
    clean = values.drop_nulls()
    if len(clean) < 2:
        return None
    mean = clean.mean()
    if not mean:
        return None
    std = clean.std()
    return None if std is None else abs(float(std) / float(mean))
