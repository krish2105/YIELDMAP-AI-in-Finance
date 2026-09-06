"""Gross and net rental yield, with every assumption on the surface.

Gross yield is the easy number and the one every portal quotes: annual rent over purchase price.
It is also close to meaningless on its own, because it ignores the service charge, the transfer
fee, the months the unit sits empty and the cost of managing it. The gap between gross and net in
Dubai is routinely two percentage points or more, which is the difference between a good and a
mediocre investment.

Net yield here is:

    net = (rent x (1 - vacancy) - service charge - management - maintenance) / total acquisition

where total acquisition is the price plus the transfer fee, commission and registration, and the
one-off purchase costs are additionally charged against income spread over an assumed holding
period. Every one of those inputs comes from config/assumptions.yaml and none is hidden in code,
so a reader who disagrees can change the file and watch the number move.

Rent and price are matched on the same cell — area, property type and bedroom count — over the
same recent window. Matching matters: a yield computed from this year's rents over last year's
prices is a statement about two different markets.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from finance.base import DEFAULT_DB, Warehouse, coefficient_of_variation, write_result

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS_PATH = ROOT / "config" / "assumptions.yaml"

PRICES_SQL = """
select
    area_key,
    property_type,
    rooms,
    count(*)                       as n_sales,
    median(price_aed)              as median_price,
    median(area_sqm)               as median_sqm,
    median(price_per_sqm)          as median_ppsqm,
    stddev_samp(price_aed)         as price_sd,
    max(ts)                        as last_sale
from transactions
where ts >= (select max(ts) from transactions) - interval '{window_months}' month
  and price_aed is not null
  and area_sqm is not null
group by 1, 2, 3
"""

RENTS_SQL = """
select
    area_key,
    property_type,
    rooms,
    count(*)                       as n_contracts,
    median(annual_rent_aed)        as median_rent,
    median(area_sqm)               as median_rent_sqm,
    stddev_samp(annual_rent_aed)   as rent_sd,
    max(start)                     as last_contract
from rent_contracts
where start >= (select max(start) from rent_contracts) - interval '{window_months}' month
  and annual_rent_aed is not null
group by 1, 2, 3
"""


@dataclass(frozen=True)
class Assumptions:
    """The editable inputs behind a net yield."""

    vacancy: float
    service_charge_per_sqm: float
    management_fee: float
    maintenance: float
    dld_transfer_fee: float
    agent_commission: float
    registration_fee: float
    amortisation_years: int
    min_observations: int
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path = ASSUMPTIONS_PATH) -> Assumptions:
        raw = yaml.safe_load(path.read_text())
        return cls(
            vacancy=float(raw["vacancy"]["value"]),
            service_charge_per_sqm=float(raw["service_charge_per_sqm"]["value"]),
            management_fee=float(raw["management_fee"]["value"]),
            maintenance=float(raw["maintenance"]["value"]),
            dld_transfer_fee=float(raw["dld_transfer_fee"]["value"]),
            agent_commission=float(raw["agent_commission"]["value"]),
            registration_fee=float(raw["registration_fee"]["value"]),
            amortisation_years=int(raw["amortisation_years"]["value"]),
            min_observations=int(raw["min_observations"]),
            raw=raw,
        )

    def replace(self, **changes: float) -> Assumptions:
        """A copy with some inputs overridden, for the interface's assumption sliders."""
        fields = {
            "vacancy": self.vacancy,
            "service_charge_per_sqm": self.service_charge_per_sqm,
            "management_fee": self.management_fee,
            "maintenance": self.maintenance,
            "dld_transfer_fee": self.dld_transfer_fee,
            "agent_commission": self.agent_commission,
            "registration_fee": self.registration_fee,
            "amortisation_years": self.amortisation_years,
            "min_observations": self.min_observations,
        }
        fields.update(changes)
        return Assumptions(**fields, raw=self.raw)  # type: ignore[arg-type]

    def editable(self) -> list[dict[str, Any]]:
        """The assumption panel: what each input is, what it is worth, and how sure we are."""
        return [
            {
                "key": key,
                "label": body.get("label", key),
                "value": body["value"],
                "unit": body.get("unit"),
                "description": " ".join(str(body.get("description", "")).split()),
                "status": body.get("status"),
                "source": " ".join(str(body.get("source", "")).split()) or None,
                "source_url": body.get("source_url"),
                "verified_on": body.get("verified_on"),
            }
            for key, body in self.raw.items()
            if isinstance(body, dict) and "value" in body
        ]


def acquisition_cost(price: float, a: Assumptions) -> float:
    """What the purchase actually costs, not what the listing says."""
    return price * (1 + a.dld_transfer_fee + a.agent_commission) + a.registration_fee


def gross_yield(annual_rent: float, price: float) -> float | None:
    """Annual rent over purchase price. The number every portal quotes."""
    if price <= 0:
        return None
    return annual_rent / price


def net_yield(
    annual_rent: float, price: float, sqm: float, a: Assumptions
) -> dict[str, float] | None:
    """Net yield with the full cost stack, returning the working as well as the answer."""
    if price <= 0 or annual_rent <= 0:
        return None

    effective_rent = annual_rent * (1 - a.vacancy)
    service_charge = a.service_charge_per_sqm * max(sqm, 0.0)
    management = effective_rent * a.management_fee
    maintenance = price * a.maintenance

    total_acquisition = acquisition_cost(price, a)
    one_off = total_acquisition - price
    amortised_purchase_costs = one_off / max(a.amortisation_years, 1)

    net_income = effective_rent - service_charge - management - maintenance
    net_income_after_costs = net_income - amortised_purchase_costs

    return {
        "gross_rent": annual_rent,
        "effective_rent": effective_rent,
        "vacancy_cost": annual_rent - effective_rent,
        "service_charge": service_charge,
        "management": management,
        "maintenance": maintenance,
        "amortised_purchase_costs": amortised_purchase_costs,
        "net_income": net_income_after_costs,
        "total_acquisition": total_acquisition,
        "gross_yield": annual_rent / price,
        "net_yield": net_income_after_costs / total_acquisition,
    }


def build_table(prices: pl.DataFrame, rents: pl.DataFrame, a: Assumptions) -> pl.DataFrame:
    """Join sales to rents on the same cell and compute both yields."""
    joined = prices.join(rents, on=["area_key", "property_type", "rooms"], how="inner")

    rows: list[dict[str, Any]] = []
    for r in joined.iter_rows(named=True):
        sqm = r["median_sqm"] or r["median_rent_sqm"] or 0.0
        working = net_yield(r["median_rent"], r["median_price"], sqm, a)
        if working is None:
            continue
        # The binding sample size is the smaller of the two sides: a yield built on two hundred
        # sales and three tenancies is a three-observation number.
        n = min(r["n_sales"], r["n_contracts"])
        rows.append(
            {
                "area_key": r["area_key"],
                "property_type": r["property_type"],
                "rooms": r["rooms"],
                "n_sales": r["n_sales"],
                "n_contracts": r["n_contracts"],
                "n": n,
                "median_price": r["median_price"],
                "median_rent": r["median_rent"],
                "median_sqm": sqm,
                "gross_yield": working["gross_yield"],
                "net_yield": working["net_yield"],
                "spread": working["gross_yield"] - working["net_yield"],
                "sufficient": n >= a.min_observations,
                **{
                    k: working[k]
                    for k in (
                        "service_charge",
                        "management",
                        "vacancy_cost",
                        "amortised_purchase_costs",
                        "total_acquisition",
                    )
                },
            }
        )
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def run(db_path: Path = DEFAULT_DB, *, window_months: int = 12) -> dict[str, Any]:
    a = Assumptions.load()
    prices_sql = PRICES_SQL.format(window_months=window_months)
    rents_sql = RENTS_SQL.format(window_months=window_months)

    with Warehouse(db_path) as wh:
        prices = wh.query(prices_sql)
        rents = wh.query(rents_sql)
        provenance = wh.provenance()

    table = build_table(prices.frame, rents.frame, a)
    published = table.filter(pl.col("sufficient")) if table.height else table

    summary: dict[str, Any] = {
        "cells": table.height,
        "cells_published": published.height,
        "cells_suppressed_for_thin_data": table.height - published.height,
    }
    if published.height:
        summary |= {
            "median_gross_yield": float(published["gross_yield"].median()),
            "median_net_yield": float(published["net_yield"].median()),
            "median_spread": float(published["spread"].median()),
            "gross_yield_cv": coefficient_of_variation(published["gross_yield"]),
        }

    payload = {
        "method_id": "yield_v1",
        "window_months": window_months,
        "definition": {
            "gross": "median annual Ejari rent divided by median sale price for the same cell",
            "net": (
                "rent after vacancy, less service charge, management, maintenance and amortised "
                "purchase costs, over the full acquisition cost including fees"
            ),
            "cell": "area, property type and bedroom count, over the same recent window",
        },
        "assumptions": a.editable(),
        "sql": {"prices": prices.sql, "rents": rents.sql},
        "summary": summary,
        "table": published.sort("net_yield", descending=True).to_dicts()
        if published.height
        else [],
    }
    path = write_result("yield.json", payload, provenance)
    return {"payload": payload, "path": path, "provenance": provenance, "table": table}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--window-months", type=int, default=12)
    args = parser.parse_args(argv)

    out = run(args.db, window_months=args.window_months)
    s = out["payload"]["summary"]
    print(
        f"{s['cells']} cells, {s['cells_published']} published, "
        f"{s['cells_suppressed_for_thin_data']} suppressed as too thin"
    )
    if s.get("median_net_yield") is not None:
        print(f"  median gross yield {s['median_gross_yield']:.2%}")
        print(f"  median net yield   {s['median_net_yield']:.2%}")
        print(f"  median spread      {s['median_spread']:.2%}")
    top = out["payload"]["table"][:5]
    if top:
        print("\n  highest net yields")
        for r in top:
            print(
                f"    {r['area_key'][:28]:<28} {r['property_type']:<8} "
                f"{r['rooms'] if r['rooms'] is not None else '-':>3}br  "
                f"gross {r['gross_yield']:.2%}  net {r['net_yield']:.2%}  n={r['n']}"
            )
    print(f"\nwrote {out['path']} ({out['provenance']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
