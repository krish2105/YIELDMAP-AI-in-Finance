"""Portfolio analytics for a basket of holdings.

A single property's yield says nothing about whether a set of them is sensible. Two things change
once there is more than one: concentration, and correlation.

Concentration is measured with a Herfindahl-Hirschman index over value shares — the same measure
competition regulators use for market share, and for the same reason: it punishes a large single
share far more than several medium ones. Four equal holdings score 0.25; one holding plus three
tiny ones scores near 1.

Correlation is the part people skip. Holding four apartments in four Dubai communities feels
diversified and largely is not, because they move together. The effective number of independent
holdings is reported alongside the raw count, so the difference is visible rather than assumed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from finance.base import DEFAULT_DB, Warehouse, write_result
from finance.dcf import irr, project
from finance.yields import Assumptions, net_yield

AREA_MONTHLY_SQL = """
select
    area_key,
    date_trunc('month', ts) as month,
    median(price_per_sqm)   as ppsqm,
    count(*)                as n
from transactions
where price_per_sqm is not null
group by 1, 2
having count(*) >= 3
order by 1, 2
"""


@dataclass
class Holding:
    """One position in a basket."""

    area_key: str
    property_type: str
    rooms: int | None
    value: float
    annual_rent: float
    sqm: float
    developer: str | None = None
    loan: float = 0.0


def herfindahl(shares: list[float]) -> float:
    """Concentration of a set of shares. One holding scores 1; n equal holdings score 1/n."""
    total = sum(shares)
    if total <= 0:
        return 0.0
    return float(sum((s / total) ** 2 for s in shares))


def effective_holdings(shares: list[float]) -> float:
    """The inverse of the concentration index: how many equal holdings this is equivalent to."""
    hhi = herfindahl(shares)
    return 1.0 / hhi if hhi > 0 else 0.0


def blended_yield(holdings: list[Holding], a: Assumptions) -> dict[str, float | None]:
    """Value-weighted gross and net yield across the basket.

    Value-weighted rather than averaged: a two-million holding at 4% and a two-hundred-thousand one
    at 10% is a 4.5% portfolio, not a 7% one, and a simple mean would say 7%.
    """
    total_value = sum(h.value for h in holdings)
    if total_value <= 0:
        return {"gross": None, "net": None, "total_value": 0.0}

    gross_income = net_income = 0.0
    total_acquisition = 0.0
    for h in holdings:
        working = net_yield(h.annual_rent, h.value, h.sqm, a)
        if working is None:
            continue
        gross_income += working["gross_rent"]
        net_income += working["net_income"]
        total_acquisition += working["total_acquisition"]

    return {
        "gross": gross_income / total_value if total_value else None,
        "net": net_income / total_acquisition if total_acquisition else None,
        "total_value": total_value,
        "total_acquisition": total_acquisition,
        "annual_gross_income": gross_income,
        "annual_net_income": net_income,
    }


def portfolio_irr(
    holdings: list[Holding], *, years: int = 5, price_growth: float = 0.03, **kwargs: Any
) -> dict[str, Any]:
    """Combine each holding's projected cash flows and solve the whole basket's return."""
    if not holdings:
        return {"irr": None, "flows": [], "reason": "no holdings"}

    combined = np.zeros(years + 1)
    for h in holdings:
        p = project(
            price=h.value,
            annual_rent=h.annual_rent,
            sqm=h.sqm,
            years=years,
            price_growth=price_growth,
            loan_amount=h.loan,
            **kwargs,
        )
        combined += np.array(p.series)

    series = [float(v) for v in combined]
    return {"irr": irr(series), "flows": series, "years": years, "price_growth": price_growth}


def concentration(holdings: list[Holding]) -> dict[str, Any]:
    """Concentration by area, by developer and by individual holding."""

    def by(attr: str) -> dict[str, Any]:
        groups: dict[str, float] = {}
        for h in holdings:
            key = getattr(h, attr) or "unknown"
            groups[key] = groups.get(key, 0.0) + h.value
        shares = list(groups.values())
        return {
            "groups": len(groups),
            "hhi": round(herfindahl(shares), 4),
            "effective": round(effective_holdings(shares), 2),
            "largest_share": round(max(shares) / sum(shares), 4) if shares else 0.0,
        }

    values = [h.value for h in holdings]
    return {
        "by_area": by("area_key"),
        "by_developer": by("developer"),
        "by_holding": {
            "count": len(holdings),
            "hhi": round(herfindahl(values), 4),
            "effective": round(effective_holdings(values), 2),
        },
    }


def area_correlations(
    monthly: pl.DataFrame, areas: list[str], *, min_months: int = 24
) -> dict[str, Any]:
    """Correlation of month-on-month returns between the areas held.

    Returns rather than levels: two rising series correlate near one whatever they do, which tells
    you nothing. What matters is whether they move together month to month.
    """
    usable = []
    series: list[np.ndarray] = []
    for area in dict.fromkeys(areas):
        rows = monthly.filter(pl.col("area_key") == area).sort("month")
        if rows.height < min_months:
            continue
        values = rows["ppsqm"].to_numpy()
        series.append(np.diff(np.log(values)))
        usable.append(area)

    if len(series) < 2:
        return {
            "areas": usable,
            "matrix": None,
            "mean_correlation": None,
            "reason": "at least two areas with enough history are needed",
        }

    length = min(len(s) for s in series)
    matrix = np.corrcoef(np.array([s[-length:] for s in series]))
    off_diagonal = matrix[np.triu_indices_from(matrix, k=1)]

    return {
        "areas": usable,
        "months_compared": length,
        "matrix": [[round(float(v), 4) for v in row] for row in matrix],
        "mean_correlation": round(float(np.mean(off_diagonal)), 4),
        "max_correlation": round(float(np.max(off_diagonal)), 4),
    }


def diversification(conc: dict[str, Any], corr: dict[str, Any]) -> dict[str, Any]:
    """How diversified the basket really is, once correlation is taken into account.

    The effective count from concentration alone assumes holdings are independent. They are not:
    Dubai communities move together. Discounting by the average correlation gives a number closer
    to the truth, and always at or below the naive one.
    """
    naive = conc["by_holding"]["effective"]
    mean_corr = corr.get("mean_correlation")
    if mean_corr is None:
        return {
            "naive_effective_holdings": naive,
            "correlation_adjusted": None,
            "note": "not enough shared history between these areas to adjust for correlation",
        }

    rho = max(0.0, min(float(mean_corr), 0.999))
    adjusted = naive / (1 + rho * (naive - 1)) if naive > 0 else 0.0
    return {
        "naive_effective_holdings": naive,
        "mean_correlation": round(rho, 4),
        "correlation_adjusted": round(adjusted, 2),
        "note": (
            "Holdings in different Dubai communities still move together, so the correlation "
            "adjusted figure is the honest count of independent positions."
        ),
    }


def analyse(
    holdings: list[Holding],
    monthly: pl.DataFrame,
    *,
    assumptions: Assumptions | None = None,
    years: int = 5,
    price_growth: float = 0.03,
) -> dict[str, Any]:
    a = assumptions or Assumptions.load()
    conc = concentration(holdings)
    corr = area_correlations(monthly, [h.area_key for h in holdings])
    return {
        "method_id": "portfolio_v1",
        "holdings": len(holdings),
        "blended_yield": blended_yield(holdings, a),
        "projection": portfolio_irr(holdings, years=years, price_growth=price_growth),
        "concentration": conc,
        "correlation": corr,
        "diversification": diversification(conc, corr),
        "disclaimer": "A projection under stated assumptions. Not advice.",
    }


def _example_basket(wh: Warehouse) -> list[Holding]:
    """A worked basket drawn from the four busiest areas, for the results file."""
    rows = wh.query(
        """
        with recent as (
            select * from transactions
            where property_type = 'unit'
              and ts >= (select max(ts) from transactions) - interval '12' month
        )
        select
            t.area_key,
            median(t.price_aed) as price,
            median(t.area_sqm)  as sqm,
            count(*)            as n,
            any_value(t.project_name) as developer
        from recent t
        group by 1
        order by n desc
        limit 4
        """
    ).frame
    rents = wh.query(
        """
        select area_key, median(annual_rent_aed) as rent
        from rent_contracts
        where start >= (select max(start) from rent_contracts) - interval '12' month
        group by 1
        """
    ).frame
    joined = rows.join(rents, on="area_key", how="left")
    fallback = float(rents["rent"].median())
    return [
        Holding(
            area_key=r["area_key"],
            property_type="unit",
            rooms=None,
            value=float(r["price"]),
            annual_rent=float(r["rent"] or fallback),
            sqm=float(r["sqm"]),
            developer=r["developer"],
        )
        for r in joined.iter_rows(named=True)
    ]


def run(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    with Warehouse(db_path) as wh:
        monthly = wh.query(AREA_MONTHLY_SQL)
        basket = _example_basket(wh)
        provenance = wh.provenance()

    payload = analyse(basket, monthly.frame)
    payload["sql"] = {"area_monthly": monthly.sql}
    payload["example_basket"] = [
        {"area_key": h.area_key, "value": round(h.value), "annual_rent": round(h.annual_rent)}
        for h in basket
    ]
    path = write_result("portfolio.json", payload, provenance)
    return {"payload": payload, "path": path, "provenance": provenance}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    out = run(args.db)
    p = out["payload"]
    y, d, c = p["blended_yield"], p["diversification"], p["correlation"]
    print(f"{p['holdings']} holdings worth AED {y['total_value']:,.0f}")
    print(f"  blended gross yield   {y['gross']:.2%}")
    print(f"  blended net yield     {y['net']:.2%}")
    if p["projection"]["irr"] is not None:
        print(f"  portfolio IRR         {p['projection']['irr']:.2%} over 5 years")
    print(f"  area concentration    HHI {p['concentration']['by_area']['hhi']:.3f}")
    print(f"  effective holdings    {d['naive_effective_holdings']:.2f} naive")
    if d.get("correlation_adjusted") is not None:
        print(
            f"                        {d['correlation_adjusted']:.2f} after correlation "
            f"(mean rho {c['mean_correlation']:.2f})"
        )
    print(f"\nwrote {out['path']} ({out['provenance']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
