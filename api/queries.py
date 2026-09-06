"""The queries behind every KPI, kept in one place.

Each function returns a Kpi, which cannot be built without the SQL that produced it. Keeping the
queries here rather than inline in route handlers means the /methodology page and the traceability
drawer can enumerate them, and that two routes asking the same question ask it the same way.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from api.kpi import Kpi, KpiSource, make_kpi
from finance.base import Warehouse, coefficient_of_variation

# --------------------------------------------------------------------------- sql

AREA_SUMMARY = """
select
    count(*)                          as n,
    median(price_per_sqm)             as median_ppsqm,
    stddev_samp(price_per_sqm)        as ppsqm_sd,
    median(price_aed)                 as median_price,
    avg(case when is_offplan then 1.0 else 0.0 end) as offplan_share,
    max(ts)                           as last_sale
from transactions
where area_key = ?
  and ts >= (select max(ts) from transactions) - interval '12' month
"""

AREA_PRIOR_YEAR = """
select
    count(*)              as n,
    median(price_per_sqm) as median_ppsqm
from transactions
where area_key = ?
  and ts >= (select max(ts) from transactions) - interval '24' month
  and ts <  (select max(ts) from transactions) - interval '12' month
"""

AREA_YIELD = """
select
    count(*)                as n,
    median(annual_rent_aed) as median_rent
from rent_contracts
where area_key = ?
  and start >= (select max(start) from rent_contracts) - interval '12' month
"""

AREA_LIST = """
select
    a.area_key,
    a.name,
    a.dld_name,
    a.lat,
    a.lon,
    a.coord_confidence,
    a.has_location,
    a.n_transactions
from area a
order by a.n_transactions desc
"""

MONTHLY_SERIES = """
select
    date_trunc('month', ts) as month,
    median(price_per_sqm)   as median_ppsqm,
    count(*)                as n
from transactions
where area_key = ?
group by 1
having count(*) >= 3
order by 1
"""

BUILDING_SUMMARY = """
select
    building_name,
    any_value(area_key)     as area_key,
    count(*)                as n,
    median(price_per_sqm)   as median_ppsqm,
    stddev_samp(price_per_sqm) as ppsqm_sd,
    median(price_aed)       as median_price,
    min(ts)                 as first_sale,
    max(ts)                 as last_sale
from transactions
where building_name = ?
group by building_name
"""

BUILDING_VS_AREA = """
with b as (
    select area_key, median(price_per_sqm) as building_ppsqm, count(*) as n
    from transactions where building_name = ? group by area_key
)
select
    b.n,
    b.building_ppsqm,
    (select median(price_per_sqm) from transactions t where t.area_key = b.area_key) as area_ppsqm
from b
"""

SCREENER = """
select
    t.area_key,
    a.name                            as area_name,
    t.property_type,
    t.rooms,
    count(*)                          as n,
    median(t.price_aed)               as median_price,
    median(t.price_per_sqm)           as median_ppsqm,
    stddev_samp(t.price_per_sqm)      as ppsqm_sd,
    avg(case when t.is_offplan then 1.0 else 0.0 end) as offplan_share
from transactions t
left join area a using (area_key)
where t.ts >= (select max(ts) from transactions) - interval '12' month
group by 1, 2, 3, 4
having count(*) >= ?
order by n desc
"""

FRESHNESS = "select * from data_freshness"

MARKET_TOTALS = """
select
    count(*)                    as n,
    count(distinct area_key)    as areas,
    min(ts)                     as first_sale,
    max(ts)                     as last_sale,
    median(price_per_sqm)       as median_ppsqm,
    stddev_samp(price_per_sqm)  as ppsqm_sd,
    sum(price_aed)              as total_value,
    avg(case when is_offplan then 1.0 else 0.0 end) as offplan_share
from transactions
where ts >= (select max(ts) from transactions) - interval '12' month
"""


# ------------------------------------------------------------------- kpi builders


def _asof(row: dict[str, Any], key: str = "last_sale") -> date:
    value = row.get(key)
    if isinstance(value, date):
        return value
    return date.today()


def _provenance(wh: Warehouse) -> str:
    return wh.provenance()


def area_kpis(wh: Warehouse, area_key: str) -> list[Kpi]:
    """The KPI row shown at the top of an area page."""
    provenance = _provenance(wh)
    current = wh.query(AREA_SUMMARY, (area_key,))
    if current.empty or current.frame["n"][0] == 0:
        return []

    row = current.frame.to_dicts()[0]
    prior = wh.query(AREA_PRIOR_YEAR, (area_key,)).frame.to_dicts()[0]
    rent = wh.query(AREA_YIELD, (area_key,)).frame.to_dicts()[0]

    n = int(row["n"])
    asof = _asof(row)
    cv = (
        float(row["ppsqm_sd"]) / float(row["median_ppsqm"])
        if row["ppsqm_sd"] and row["median_ppsqm"]
        else None
    )

    kpis: list[Kpi] = []

    delta = None
    if prior["median_ppsqm"] and row["median_ppsqm"]:
        change = float(row["median_ppsqm"]) / float(prior["median_ppsqm"]) - 1
        delta = {
            "value": round(change * 100, 2),
            "window": "yoy",
            "direction": "up" if change > 0.005 else "down" if change < -0.005 else "flat",
        }

    kpis.append(
        make_kpi(
            id=f"ppsqm.{area_key}",
            label="Median price per sqm",
            value=float(row["median_ppsqm"]) if row["median_ppsqm"] else None,
            unit="AED/sqm",
            format="currency_aed",
            n=n,
            asof=asof,
            method_id="median_ppsqm_v1",
            sql=AREA_SUMMARY,
            cv=cv,
            delta=delta,  # type: ignore[arg-type]
            provenance=provenance,  # type: ignore[arg-type]
        )
    )

    kpis.append(
        make_kpi(
            id=f"volume.{area_key}",
            label="Sales in the last 12 months",
            value=float(n),
            unit="sales",
            format="count",
            n=n,
            asof=asof,
            method_id="volume_12m_v1",
            sql=AREA_SUMMARY,
            provenance=provenance,  # type: ignore[arg-type]
        )
    )

    kpis.append(
        make_kpi(
            id=f"offplan.{area_key}",
            label="Off-plan share",
            value=float(row["offplan_share"]) * 100 if row["offplan_share"] is not None else None,
            unit="%",
            format="percent",
            n=n,
            asof=asof,
            method_id="offplan_share_v1",
            sql=AREA_SUMMARY,
            provenance=provenance,  # type: ignore[arg-type]
        )
    )

    # Gross yield needs both sides, and is only as strong as the thinner one.
    if rent["median_rent"] and row["median_price"]:
        rent_n = int(rent["n"])
        gross = float(rent["median_rent"]) / float(row["median_price"]) * 100
        kpis.append(
            make_kpi(
                id=f"gross_yield.{area_key}",
                label="Gross yield",
                value=gross,
                unit="%",
                format="percent",
                n=min(n, rent_n),
                asof=asof,
                method_id="gross_yield_v1",
                sql=f"-- sales\n{AREA_SUMMARY}\n-- rents\n{AREA_YIELD}",
                sources=[
                    KpiSource(kind="sql", ref="median sale price over the last 12 months"),
                    KpiSource(kind="sql", ref="median Ejari rent over the last 12 months"),
                ],
                provenance=provenance,  # type: ignore[arg-type]
            )
        )

    return kpis


def market_kpis(wh: Warehouse) -> list[Kpi]:
    """The KPI row on the city page."""
    provenance = _provenance(wh)
    q = wh.query(MARKET_TOTALS)
    if q.empty:
        return []
    row = q.frame.to_dicts()[0]
    n = int(row["n"])
    asof = _asof(row)
    cv = (
        float(row["ppsqm_sd"]) / float(row["median_ppsqm"])
        if row["ppsqm_sd"] and row["median_ppsqm"]
        else None
    )
    return [
        make_kpi(
            id="market.transactions",
            label="Sales in the last 12 months",
            value=float(n),
            unit="sales",
            format="count",
            n=n,
            asof=asof,
            method_id="volume_12m_v1",
            sql=MARKET_TOTALS,
            provenance=provenance,  # type: ignore[arg-type]
        ),
        make_kpi(
            id="market.value",
            label="Total value transacted",
            value=float(row["total_value"]) if row["total_value"] else None,
            unit="AED",
            format="currency_aed",
            n=n,
            asof=asof,
            method_id="total_value_12m_v1",
            sql=MARKET_TOTALS,
            provenance=provenance,  # type: ignore[arg-type]
        ),
        make_kpi(
            id="market.ppsqm",
            label="Median price per sqm",
            value=float(row["median_ppsqm"]) if row["median_ppsqm"] else None,
            unit="AED/sqm",
            format="currency_aed",
            n=n,
            asof=asof,
            method_id="median_ppsqm_v1",
            sql=MARKET_TOTALS,
            cv=cv,
            provenance=provenance,  # type: ignore[arg-type]
        ),
        make_kpi(
            id="market.areas",
            label="Communities with sales",
            value=float(row["areas"]),
            unit="areas",
            format="count",
            n=n,
            asof=asof,
            method_id="area_count_v1",
            sql=MARKET_TOTALS,
            provenance=provenance,  # type: ignore[arg-type]
        ),
        make_kpi(
            id="market.offplan",
            label="Off-plan share",
            value=float(row["offplan_share"]) * 100 if row["offplan_share"] is not None else None,
            unit="%",
            format="percent",
            n=n,
            asof=asof,
            method_id="offplan_share_v1",
            sql=MARKET_TOTALS,
            provenance=provenance,  # type: ignore[arg-type]
        ),
    ]


def building_kpis(wh: Warehouse, building: str) -> list[Kpi]:
    """The KPI row on a building page, including its premium against its own area."""
    provenance = _provenance(wh)
    q = wh.query(BUILDING_SUMMARY, (building,))
    if q.empty:
        return []
    row = q.frame.to_dicts()[0]
    n = int(row["n"])
    asof = _asof(row)
    cv = (
        float(row["ppsqm_sd"]) / float(row["median_ppsqm"])
        if row["ppsqm_sd"] and row["median_ppsqm"]
        else None
    )

    kpis = [
        make_kpi(
            id=f"building.ppsqm.{building}",
            label="Median price per sqm",
            value=float(row["median_ppsqm"]),
            unit="AED/sqm",
            format="currency_aed",
            n=n,
            asof=asof,
            method_id="median_ppsqm_v1",
            sql=BUILDING_SUMMARY,
            cv=cv,
            provenance=provenance,  # type: ignore[arg-type]
        ),
        make_kpi(
            id=f"building.sales.{building}",
            label="Recorded sales",
            value=float(n),
            unit="sales",
            format="count",
            n=n,
            asof=asof,
            method_id="building_volume_v1",
            sql=BUILDING_SUMMARY,
            provenance=provenance,  # type: ignore[arg-type]
        ),
    ]

    comparison = wh.query(BUILDING_VS_AREA, (building,))
    if not comparison.empty:
        c = comparison.frame.to_dicts()[0]
        if c["area_ppsqm"]:
            premium = (float(c["building_ppsqm"]) / float(c["area_ppsqm"]) - 1) * 100
            kpis.append(
                make_kpi(
                    id=f"building.premium.{building}",
                    label="Premium to its area",
                    value=premium,
                    unit="%",
                    format="percent",
                    n=int(c["n"]),
                    asof=asof,
                    method_id="building_premium_v1",
                    sql=BUILDING_VS_AREA,
                    provenance=provenance,  # type: ignore[arg-type]
                )
            )
    return kpis


def series(wh: Warehouse, area_key: str) -> dict[str, Any]:
    """Monthly median price per square metre for an area, with its sample sizes."""
    q = wh.query(MONTHLY_SERIES, (area_key,))
    return {
        "sql": q.sql,
        "points": [
            {"month": str(r["month"]), "median_ppsqm": r["median_ppsqm"], "n": r["n"]}
            for r in q.frame.to_dicts()
        ],
    }


def screener(wh: Warehouse, *, min_sales: int = 5) -> dict[str, Any]:
    """Every area-type-bedroom cell, for the screener table."""
    q = wh.query(SCREENER, (min_sales,))
    rows = q.frame.to_dicts()
    for r in rows:
        r["cv"] = (
            float(r["ppsqm_sd"]) / float(r["median_ppsqm"])
            if r["ppsqm_sd"] and r["median_ppsqm"]
            else None
        )
    return {"sql": q.sql, "rows": rows}


def areas(wh: Warehouse) -> dict[str, Any]:
    q = wh.query(AREA_LIST)
    return {"sql": q.sql, "rows": q.frame.to_dicts()}


def freshness(wh: Warehouse) -> dict[str, Any]:
    q = wh.query(FRESHNESS)
    return {"sql": q.sql, "rows": q.frame.to_dicts()}


def dispersion(wh: Warehouse, area_key: str) -> float | None:
    """Coefficient of variation of price per square metre, used for confidence."""
    q = wh.query(
        "select price_per_sqm from transactions where area_key = ? and price_per_sqm is not null",
        (area_key,),
    )
    return None if q.empty else coefficient_of_variation(q.frame["price_per_sqm"])
