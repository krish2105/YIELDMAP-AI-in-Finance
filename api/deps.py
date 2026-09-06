"""Shared dependencies: the warehouse and the results cache.

Access control moved to api/auth.py when the role stopped being something a client could
simply assert in a header.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status

# Roles and access control live in api/auth.py, re-exported here so the modules that already
# import from api.deps keep working. They are not redefined: two role tables would eventually
# disagree, and a disagreement about who may do what is a security bug.
from api.auth import (  # noqa: F401
    ROLE_ORDER,
    Principal,
    PrincipalDep,
    Role,
    current_principal,
    require,
)
from finance.base import DEFAULT_DB, Warehouse

ROOT = Path(__file__).resolve().parent.parent


def db_path() -> Path:
    return Path(os.environ.get("DUCKDB_PATH", str(DEFAULT_DB)))


def get_warehouse():
    """One read-only connection per request.

    DuckDB read-only connections are cheap and a per-request connection avoids the cross-thread
    sharing that a single global one would need to guard against.
    """
    path = db_path()
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The analytics database has not been built. Run the ingest workflow, or "
                "`uv run python -m etl.clean` locally."
            ),
        )
    wh = Warehouse(path)
    try:
        yield wh
    finally:
        wh.close()


WarehouseDep = Annotated[Warehouse, Depends(get_warehouse)]


@lru_cache(maxsize=32)
def _load_result(name: str, provenance: str) -> dict[str, Any] | None:
    base = ROOT / "docs" / "results"
    path = (base / name) if provenance == "REAL" else (base / "synthetic" / name)
    if not path.exists():
        # Fall back across provenance so a fresh checkout still serves whatever exists.
        other = (base / "synthetic" / name) if provenance == "REAL" else (base / name)
        path = other
    return json.loads(path.read_text()) if path.exists() else None


def result(name: str, provenance: str = "REAL") -> dict[str, Any]:
    """Read a model's published output, or say plainly that it has not been produced."""
    body = _load_result(name, provenance)
    if body is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{name} has not been produced yet; the model that writes it has not run.",
        )
    return body
