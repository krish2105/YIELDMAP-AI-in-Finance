"""Market, area and building routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from api import queries
from api.deps import WarehouseDep, result
from api.kpi import Kpi

router = APIRouter(tags=["market"])

NOT_ADVICE = (
    "Information, not advice. Figures describe recorded transactions, not a recommendation."
)


@router.get("/market")
def market(wh: WarehouseDep) -> dict[str, Any]:
    """Headline KPIs for the whole market."""
    kpis = queries.market_kpis(wh)
    return {
        "kpis": [k.model_dump(mode="json") for k in kpis],
        "provenance": wh.provenance(),
        "notice": NOT_ADVICE,
    }


@router.get("/areas")
def list_areas(wh: WarehouseDep) -> dict[str, Any]:
    """Every area, with its centroid where one is known."""
    data = queries.areas(wh)
    return {
        "areas": data["rows"],
        "sql": data["sql"],
        "provenance": wh.provenance(),
        "without_location": sum(1 for r in data["rows"] if not r["has_location"]),
    }


@router.get("/areas/{area_key}")
def area_detail(area_key: str, wh: WarehouseDep) -> dict[str, Any]:
    """One area: its KPI row, its monthly series and its risk breakdown."""
    kpis: list[Kpi] = queries.area_kpis(wh, area_key)
    if not kpis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no transactions recorded for '{area_key}' in the last 12 months",
        )

    provenance = wh.provenance()
    risk = next(
        (
            row
            for row in result("risk.json", provenance).get("areas", [])
            if row["area_key"] == area_key
        ),
        None,
    )
    forecast = next(
        (
            row
            for row in result("forecast.json", provenance).get("areas", [])
            if row["area_key"] == area_key
        ),
        None,
    )

    return {
        "area_key": area_key,
        "kpis": [k.model_dump(mode="json") for k in kpis],
        "series": queries.series(wh, area_key),
        "risk": risk,
        "forecast": forecast,
        "provenance": provenance,
        "notice": NOT_ADVICE,
    }


@router.get("/buildings/{name}")
def building_detail(name: str, wh: WarehouseDep) -> dict[str, Any]:
    """One building, and how it prices against its own area."""
    kpis = queries.building_kpis(wh, name)
    if not kpis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no transactions recorded for '{name}'"
        )
    return {
        "building": name,
        "kpis": [k.model_dump(mode="json") for k in kpis],
        "provenance": wh.provenance(),
        "notice": NOT_ADVICE,
    }


@router.get("/compare")
def compare(
    wh: WarehouseDep,
    areas: Annotated[list[str], Query(description="area keys to compare")] = [],  # noqa: B006
) -> dict[str, Any]:
    """Several areas side by side, on the same KPIs."""
    if not areas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="name at least one area to compare"
        )
    if len(areas) > 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="comparing more than six areas at once makes the chart unreadable",
        )

    out = []
    for key in areas:
        kpis = queries.area_kpis(wh, key)
        out.append(
            {
                "area_key": key,
                "found": bool(kpis),
                "kpis": [k.model_dump(mode="json") for k in kpis],
                "series": queries.series(wh, key) if kpis else None,
            }
        )
    return {"areas": out, "provenance": wh.provenance(), "notice": NOT_ADVICE}


@router.get("/screener")
def screener(
    wh: WarehouseDep,
    min_sales: Annotated[int, Query(ge=1, le=1000)] = 5,
    property_type: str | None = None,
    rooms: int | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> dict[str, Any]:
    """Every area, type and bedroom cell, filterable."""
    data = queries.screener(wh, min_sales=min_sales)
    rows = data["rows"]
    if property_type:
        rows = [r for r in rows if r["property_type"] == property_type]
    if rooms is not None:
        rows = [r for r in rows if r["rooms"] == rooms]
    return {
        "rows": rows[:limit],
        "total_matching": len(rows),
        "sql": data["sql"],
        "provenance": wh.provenance(),
        "notice": NOT_ADVICE,
    }


@router.get("/index")
def price_index(wh: WarehouseDep) -> dict[str, Any]:
    """The repeat-sales index."""
    return result("index.json", wh.provenance())


@router.get("/yield")
def yields(wh: WarehouseDep) -> dict[str, Any]:
    """Gross and net yield by cell, with the assumptions behind the net figure."""
    return result("yield.json", wh.provenance())


@router.get("/forecast")
def forecast(wh: WarehouseDep) -> dict[str, Any]:
    """Twelve-month forecasts and how each scored against the naive benchmark."""
    return result("forecast.json", wh.provenance())


@router.get("/risk")
def risk(wh: WarehouseDep) -> dict[str, Any]:
    """Risk scores and their component breakdowns."""
    return result("risk.json", wh.provenance())


@router.get("/anomalies")
def anomalies(wh: WarehouseDep, limit: Annotated[int, Query(ge=1, le=500)] = 50) -> dict[str, Any]:
    """Flagged transactions, each naming the rule that fired."""
    body = result("risk.json", wh.provenance())["anomalies"]
    return {**body, "examples": body["examples"][:limit]}


@router.get("/developers")
def developers(wh: WarehouseDep) -> dict[str, Any]:
    """Developer league table, ranked on premium to their own areas."""
    return result("developers.json", wh.provenance())


@router.get("/hedonic")
def hedonic(wh: WarehouseDep) -> dict[str, Any]:
    """Valuation model card: accuracy, baseline, noise floor and feature reliance."""
    return result("hedonic.json", wh.provenance())


@router.get("/data/freshness")
def data_freshness(wh: WarehouseDep) -> dict[str, Any]:
    """What is loaded, how much, as of when, and from which download."""
    data = queries.freshness(wh)
    provenance = wh.provenance()
    return {
        "tables": data["rows"],
        "sql": data["sql"],
        "provenance": provenance,
        "warning": (
            "These figures come from generated data, not the Dubai registry."
            if provenance == "SYNTHETIC"
            else None
        ),
    }
