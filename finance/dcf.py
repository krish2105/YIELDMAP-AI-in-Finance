"""Holding-period cash flows, IRR and NPV.

A yield is a snapshot; an investment is a sequence. This projects what an owner actually pays and
receives across a holding period — the deposit and fees up front, net rent less debt service each
year, and the sale proceeds after costs and after repaying whatever is left of the loan — and
reduces that sequence to an internal rate of return.

Leverage is the reason this is not just the net yield again. A mortgage shrinks the money at risk
while leaving the whole property's appreciation with the owner, so it lifts the return when prices
rise and deepens the loss when they fall. The projection therefore reports the unlevered return
alongside the levered one, because a levered IRR quoted on its own tells you about the loan rather
than about the property.

Every figure is a projection under stated assumptions, not a forecast of what will happen, and
certainly not advice.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy_financial as npf

from finance.base import DEFAULT_DB, Warehouse, write_result
from finance.mortgage import MortgageRules, amortisation_schedule
from finance.yields import Assumptions, acquisition_cost


@dataclass
class CashFlow:
    year: int
    rent: float = 0.0
    operating_costs: float = 0.0
    interest: float = 0.0
    principal: float = 0.0
    capital: float = 0.0
    net: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "year": self.year,
            "rent": round(self.rent, 2),
            "operating_costs": round(self.operating_costs, 2),
            "interest": round(self.interest, 2),
            "principal": round(self.principal, 2),
            "capital": round(self.capital, 2),
            "net": round(self.net, 2),
        }


@dataclass
class Projection:
    flows: list[CashFlow]
    irr: float | None
    npv: float | None
    equity_invested: float
    total_returned: float
    equity_multiple: float | None
    unlevered_irr: float | None
    assumptions: dict[str, Any] = field(default_factory=dict)

    @property
    def series(self) -> list[float]:
        return [f.net for f in self.flows]

    def as_dict(self) -> dict[str, Any]:
        return {
            "irr": self.irr,
            "unlevered_irr": self.unlevered_irr,
            "npv": self.npv,
            "equity_invested": round(self.equity_invested, 2),
            "total_returned": round(self.total_returned, 2),
            "equity_multiple": self.equity_multiple,
            "assumptions": self.assumptions,
            "flows": [f.as_dict() for f in self.flows],
            "disclaimer": ("A projection under stated assumptions, not a forecast and not advice."),
        }


def irr(series: list[float]) -> float | None:
    """Internal rate of return, or None when the series has no meaningful one.

    A series that never changes sign has no IRR: money that only ever goes out, or only ever comes
    in, has no rate at which its present value is zero. Returning None says so rather than
    reporting whatever a solver stumbled into.
    """
    if len(series) < 2:
        return None
    if all(v >= 0 for v in series) or all(v <= 0 for v in series):
        return None
    value = npf.irr(series)
    if value is None:
        return None
    value = float(value)
    return None if value != value else value  # NaN when the solver fails to converge


def npv(rate: float, series: list[float]) -> float:
    """Net present value, discounting from year 1 with year 0 taken at face value."""
    return float(series[0] + sum(v / (1 + rate) ** t for t, v in enumerate(series[1:], start=1)))


def project(
    *,
    price: float,
    annual_rent: float,
    sqm: float,
    years: int = 5,
    price_growth: float = 0.03,
    rent_growth: float = 0.03,
    loan_amount: float = 0.0,
    interest_rate: float = 0.0425,
    loan_term_years: int = 25,
    selling_cost: float = 0.02,
    discount_rate: float = 0.08,
    assumptions: Assumptions | None = None,
    rules: MortgageRules | None = None,
) -> Projection:
    """Project the cash flows of holding a property for a number of years."""
    a = assumptions or Assumptions.load()
    rules = rules or MortgageRules.load()

    total_acquisition = acquisition_cost(price, a)
    loan = max(min(loan_amount, price), 0.0)
    loan_fees = loan * (
        rules.value("mortgage_registration_fee") + rules.value("bank_arrangement_fee")
    )
    equity_at_entry = total_acquisition + loan_fees - loan

    schedule = amortisation_schedule(loan, interest_rate, loan_term_years) if loan else []

    flows = [CashFlow(year=0, capital=-equity_at_entry, net=-equity_at_entry)]

    for year in range(1, years + 1):
        rent = annual_rent * (1 + rent_growth) ** (year - 1)
        effective_rent = rent * (1 - a.vacancy)
        value_now = price * (1 + price_growth) ** year

        operating = (
            a.service_charge_per_sqm * sqm
            + effective_rent * a.management_fee
            + value_now * a.maintenance
        )
        row = schedule[year - 1] if year - 1 < len(schedule) else None
        interest = row["interest"] if row else 0.0
        principal = row["principal"] if row else 0.0

        flow = CashFlow(
            year=year,
            rent=effective_rent,
            operating_costs=-operating,
            interest=-interest,
            principal=-principal,
        )
        flow.net = effective_rent - operating - interest - principal

        if year == years:
            exit_price = value_now
            outstanding = row["closing_balance"] if row else 0.0
            proceeds = exit_price * (1 - selling_cost) - outstanding
            flow.capital = proceeds
            flow.net += proceeds

        flows.append(flow)

    series = [f.net for f in flows]
    returned = sum(v for v in series[1:] if v > 0)

    # The unlevered comparison: the same property bought outright. Reported alongside because a
    # levered IRR on its own describes the loan as much as the property.
    unlevered = (
        project(
            price=price,
            annual_rent=annual_rent,
            sqm=sqm,
            years=years,
            price_growth=price_growth,
            rent_growth=rent_growth,
            loan_amount=0.0,
            interest_rate=interest_rate,
            loan_term_years=loan_term_years,
            selling_cost=selling_cost,
            discount_rate=discount_rate,
            assumptions=a,
            rules=rules,
        ).irr
        if loan > 0
        else None
    )

    return Projection(
        flows=flows,
        irr=irr(series),
        npv=npv(discount_rate, series),
        equity_invested=equity_at_entry,
        total_returned=returned,
        equity_multiple=returned / equity_at_entry if equity_at_entry > 0 else None,
        unlevered_irr=unlevered,
        assumptions={
            "years": years,
            "price_growth": price_growth,
            "rent_growth": rent_growth,
            "loan_amount": loan,
            "interest_rate": interest_rate,
            "selling_cost": selling_cost,
            "discount_rate": discount_rate,
            "vacancy": a.vacancy,
            "service_charge_per_sqm": a.service_charge_per_sqm,
        },
    )


SCENARIOS = [
    {"name": "cash purchase, modest growth", "loan_ltv": 0.0, "growth": 0.03},
    {"name": "80% loan, modest growth", "loan_ltv": 0.80, "growth": 0.03},
    {"name": "80% loan, strong growth", "loan_ltv": 0.80, "growth": 0.08},
    {"name": "80% loan, falling market", "loan_ltv": 0.80, "growth": -0.05},
    {"name": "60% loan, flat market", "loan_ltv": 0.60, "growth": 0.0},
]


def run(db_path: Path = DEFAULT_DB, *, years: int = 5) -> dict[str, Any]:
    """Worked scenarios anchored to the market's own median cell.

    The point of the scenario table is the comparison rather than any single figure: the same
    property under five financing and growth assumptions, so a reader can see how much of a return
    comes from the property and how much from the loan.
    """
    with Warehouse(db_path) as wh:
        anchor = wh.query(
            """
            select
                median(price_aed)  as price,
                median(area_sqm)   as sqm
            from transactions
            where property_type = 'unit'
              and ts >= (select max(ts) from transactions) - interval '12' month
            """
        )
        rent = wh.query(
            """
            select median(annual_rent_aed) as rent
            from rent_contracts
            where start >= (select max(start) from rent_contracts) - interval '12' month
            """
        )
        provenance = wh.provenance()

    price = float(anchor.frame["price"][0])
    sqm = float(anchor.frame["sqm"][0])
    annual_rent = float(rent.frame["rent"][0])

    results = []
    for scenario in SCENARIOS:
        p = project(
            price=price,
            annual_rent=annual_rent,
            sqm=sqm,
            years=years,
            price_growth=scenario["growth"],
            rent_growth=max(scenario["growth"], 0.0),
            loan_amount=price * scenario["loan_ltv"],
        )
        results.append({"scenario": scenario["name"], **scenario, **p.as_dict()})

    payload = {
        "method_id": "dcf_v1",
        "anchor": {"price": price, "sqm": sqm, "annual_rent": annual_rent, "years": years},
        "sql": {"anchor": anchor.sql, "rent": rent.sql},
        "mortgage_parameters": MortgageRules.load().editable(),
        "scenarios": results,
        "disclaimer": "Projections under stated assumptions. Not forecasts, and not advice.",
    }
    path = write_result("dcf.json", payload, provenance)
    return {"payload": payload, "path": path, "provenance": provenance}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price", type=float, default=1_500_000)
    parser.add_argument("--rent", type=float, default=105_000)
    parser.add_argument("--sqm", type=float, default=95)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--loan", type=float, default=1_200_000)
    parser.add_argument("--growth", type=float, default=0.03)
    parser.add_argument("--scenarios", action="store_true", help="write the scenario table")
    args = parser.parse_args(argv)

    if args.scenarios:
        out = run()
        print(
            f"anchor: AED {out['payload']['anchor']['price']:,.0f}, "
            f"{out['payload']['anchor']['sqm']:.0f} sqm, "
            f"AED {out['payload']['anchor']['annual_rent']:,.0f} rent\n"
        )
        print(f"  {'scenario':<32} {'levered IRR':>12} {'unlevered':>11} {'multiple':>9}")
        for s in out["payload"]["scenarios"]:
            lev = f"{s['irr']:.2%}" if s["irr"] is not None else "n/a"
            unl = f"{s['unlevered_irr']:.2%}" if s["unlevered_irr"] is not None else "—"
            mult = f"{s['equity_multiple']:.2f}x" if s["equity_multiple"] else "—"
            print(f"  {s['scenario']:<32} {lev:>12} {unl:>11} {mult:>9}")
        print(f"\nwrote {out['path']} ({out['provenance']})")
        return 0

    p = project(
        price=args.price,
        annual_rent=args.rent,
        sqm=args.sqm,
        years=args.years,
        loan_amount=args.loan,
        price_growth=args.growth,
        rent_growth=args.growth,
    )
    print(
        f"AED {args.price:,.0f} property, AED {args.rent:,.0f} rent, "
        f"{args.loan / args.price:.0%} loan, {args.years} years at {args.growth:.0%} growth\n"
    )
    print("  year        rent   operating    interest   principal     capital         net")
    for f in p.flows:
        print(
            f"  {f.year:>4}  {f.rent:>10,.0f}  {f.operating_costs:>10,.0f}  "
            f"{f.interest:>10,.0f}  {f.principal:>10,.0f}  {f.capital:>10,.0f}  {f.net:>10,.0f}"
        )
    print(f"\n  equity invested   AED {p.equity_invested:,.0f}")
    print(f"  levered IRR       {p.irr:.2%}" if p.irr is not None else "  levered IRR       n/a")
    print(f"  unlevered IRR     {p.unlevered_irr:.2%}" if p.unlevered_irr is not None else "")
    print(f"  NPV at 8%         AED {p.npv:,.0f}")
    print(f"  equity multiple   {p.equity_multiple:.2f}x")
    print(f"\n  {p.as_dict()['disclaimer']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
