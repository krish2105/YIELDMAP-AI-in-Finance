"""The KPI contract, Python side.

Mirrors ``web/lib/kpi.ts``. Both read ``config/kpi_thresholds.json`` so the API and the UI can
never disagree about whether a cell has enough data to be shown.

Rule 3 lives here: a ``Kpi`` cannot be constructed without the SQL that produced it, so there is no
code path that emits a number the user cannot trace back to a query.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_THRESHOLDS_PATH = Path(__file__).resolve().parent.parent / "config" / "kpi_thresholds.json"
THRESHOLDS: dict = json.loads(_THRESHOLDS_PATH.read_text())

Confidence = Literal["high", "medium", "low", "insufficient"]
KpiFormat = Literal["currency_aed", "percent", "count", "ratio", "index", "score", "years"]
Provenance = Literal["REAL", "SYNTHETIC"]


def confidence_for(n: int, cv: float | None) -> Confidence:
    """Confidence from sample size and dispersion.

    ``cv`` is the coefficient of variation of the underlying sample (std / |mean|), or ``None`` for
    a quantity that has no dispersion, such as a count. A small or wildly dispersed sample is never
    reported confidently — this is what stops the 3D city extruding a community on three sales.
    """
    if n is None or not isinstance(n, int) or n < THRESHOLDS["min_n"]:
        return "insufficient"
    dispersion = 0.0 if cv is None or not math.isfinite(cv) else abs(cv)
    if n >= THRESHOLDS["high"]["min_n"] and dispersion <= THRESHOLDS["high"]["max_cv"]:
        return "high"
    if n >= THRESHOLDS["medium"]["min_n"] and dispersion <= THRESHOLDS["medium"]["max_cv"]:
        return "medium"
    return "low"


def sql_hash(sql: str) -> str:
    """Stable short hash of a query, used to link a rendered number to its source."""
    return hashlib.sha256(" ".join(sql.split()).encode()).hexdigest()[:16]


class KpiDelta(BaseModel):
    value: float
    window: str
    direction: Literal["up", "down", "flat"]


class KpiSource(BaseModel):
    kind: Literal["sql", "doc"]
    ref: str
    sha256: str | None = None


class Kpi(BaseModel):
    """A single number, plus everything needed to check it."""

    id: str
    label: str
    value: float | None
    unit: str
    format: KpiFormat
    n: int = Field(ge=0)
    asof: date
    method_id: str
    sql: str
    sql_hash: str = ""
    confidence: Confidence = "insufficient"
    delta: KpiDelta | None = None
    sources: list[KpiSource] = Field(default_factory=list)
    provenance: Provenance = "REAL"

    @field_validator("sql")
    @classmethod
    def _sql_must_be_real(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("a Kpi must carry the SQL that produced it (project Rule 3)")
        return v

    @property
    def synthetic(self) -> bool:
        return self.provenance == "SYNTHETIC"

    @property
    def suppressed(self) -> bool:
        """True when the tile must show 'insufficient data' rather than a number."""
        return self.value is None or self.confidence == "insufficient"


def make_kpi(
    *,
    id: str,
    label: str,
    value: float | None,
    unit: str,
    format: KpiFormat,
    n: int,
    asof: date,
    method_id: str,
    sql: str,
    cv: float | None = None,
    delta: KpiDelta | None = None,
    sources: list[KpiSource] | None = None,
    provenance: Provenance = "REAL",
) -> Kpi:
    """Build a Kpi, deriving confidence and the SQL hash.

    Values that fail the confidence floor are blanked here rather than at render time, so a
    too-thin number never leaves the API in the first place.
    """
    conf = confidence_for(n, cv)
    if value is not None and not math.isfinite(value):
        value = None
    srcs = list(sources) if sources else [KpiSource(kind="sql", ref=method_id)]
    return Kpi(
        id=id,
        label=label,
        value=None if conf == "insufficient" else value,
        unit=unit,
        format=format,
        n=n,
        asof=asof,
        method_id=method_id,
        sql=sql,
        sql_hash=sql_hash(sql),
        confidence=conf,
        delta=delta,
        sources=srcs,
        provenance=provenance,
    )
