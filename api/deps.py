"""Shared dependencies: the warehouse, the results cache and role-based access."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, Header, HTTPException, status

from finance.base import DEFAULT_DB, Warehouse

ROOT = Path(__file__).resolve().parent.parent
Role = Literal["viewer", "analyst", "admin"]
ROLE_ORDER: dict[str, int] = {"viewer": 0, "analyst": 1, "admin": 2}


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


def current_role(x_yieldmap_role: Annotated[str | None, Header()] = None) -> Role:
    """The caller's role.

    A header rather than a session because this deployment has no login: the interface sets it and
    the API enforces it. Anything unrecognised is treated as the least privileged role rather than
    rejected, so a misconfigured client degrades to read-only instead of breaking.
    """
    value = (x_yieldmap_role or "viewer").strip().lower()
    return value if value in ROLE_ORDER else "viewer"  # type: ignore[return-value]


RoleDep = Annotated[str, Depends(current_role)]


def require(minimum: Role):
    """Dependency factory enforcing a minimum role."""

    def _check(role: RoleDep) -> str:
        if ROLE_ORDER[role] < ROLE_ORDER[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"this endpoint needs the {minimum} role; you have {role}",
            )
        return role

    return Depends(_check)
