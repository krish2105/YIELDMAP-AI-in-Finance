"""Rent or buy: after how many years does buying come out ahead?

The comparison people usually make is monthly rent against a monthly mortgage payment, and it is
wrong in both directions. It ignores the transfer fee, the service charge and the maintenance a
renter never pays; and it ignores that a renter keeps their deposit and can invest it.

This does it properly, as two competing uses of the same money over the same period:

* **Buy** — pay the deposit and fees now, then the mortgage, service charge and maintenance each
  year, and finish holding a property worth whatever it is then worth, less the outstanding loan
  and selling costs.
* **Rent** — pay rent each year, and invest the deposit the buyer put down plus whatever the
  buyer's annual outgoings exceed the rent, at an assumed investment return.

The output is the break-even year: the first year at which the buyer's net position overtakes the
renter's. If that never happens inside the horizon, it says so instead of manufacturing a number.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from finance.mortgage import MortgageRules, amortisation_schedule
from finance.yields import Assumptions, acquisition_cost


@dataclass
class YearComparison:
    year: int
    buyer_equity: float
    renter_wealth: float
    buyer_outlay: float
    renter_outlay: float

    @property
    def advantage(self) -> float:
        return self.buyer_equity - self.renter_wealth

    def as_dict(self) -> dict[str, float]:
        return {
            "year": self.year,
            "buyer_equity": round(self.buyer_equity, 2),
            "renter_wealth": round(self.renter_wealth, 2),
            "buyer_outlay": round(self.buyer_outlay, 2),
            "renter_outlay": round(self.renter_outlay, 2),
            "advantage": round(self.advantage, 2),
        }


def compare(
    *,
    price: float,
    annual_rent: float,
    sqm: float,
    years: int = 15,
    deposit_fraction: float = 0.20,
    interest_rate: float = 0.0425,
    loan_term_years: int = 25,
    price_growth: float = 0.03,
    rent_growth: float = 0.03,
    investment_return: float = 0.05,
    selling_cost: float = 0.02,
    assumptions: Assumptions | None = None,
    rules: MortgageRules | None = None,
) -> dict[str, Any]:
    """Track a buyer's equity against a renter's invested wealth, year by year."""
    a = assumptions or Assumptions.load()
    rules = rules or MortgageRules.load()

    loan = price * (1 - deposit_fraction)
    total_acquisition = acquisition_cost(price, a)
    loan_fees = loan * (
        rules.value("mortgage_registration_fee") + rules.value("bank_arrangement_fee")
    )
    upfront = total_acquisition + loan_fees - loan

    schedule = amortisation_schedule(loan, interest_rate, loan_term_years)

    # The renter starts with the buyer's deposit and fees invested instead of spent.
    renter_pot = upfront
    rows: list[YearComparison] = []
    buyer_cumulative = upfront
    renter_cumulative = 0.0

    for year in range(1, years + 1):
        row = schedule[year - 1] if year - 1 < len(schedule) else None
        mortgage_paid = row["payment"] if row else 0.0
        outstanding = row["closing_balance"] if row else 0.0

        value_now = price * (1 + price_growth) ** year
        rent_now = annual_rent * (1 + rent_growth) ** (year - 1)

        buyer_annual = mortgage_paid + a.service_charge_per_sqm * sqm + value_now * a.maintenance
        renter_annual = rent_now

        # The renter invests the difference when the buyer pays more, and draws on the pot when
        # the buyer pays less — which is what happens once rent overtakes a fixed mortgage.
        renter_pot = renter_pot * (1 + investment_return) + (buyer_annual - renter_annual)

        buyer_cumulative += buyer_annual
        renter_cumulative += renter_annual

        buyer_equity = value_now * (1 - selling_cost) - outstanding
        rows.append(
            YearComparison(
                year=year,
                buyer_equity=buyer_equity,
                renter_wealth=renter_pot,
                buyer_outlay=buyer_cumulative,
                renter_outlay=renter_cumulative,
            )
        )

    break_even = next((r.year for r in rows if r.advantage >= 0), None)

    return {
        "method_id": "rent_vs_buy_v1",
        "break_even_year": break_even,
        "horizon_years": years,
        "verdict": (
            f"buying overtakes renting in year {break_even}"
            if break_even
            else f"buying does not overtake renting within {years} years under these assumptions"
        ),
        "inputs": {
            "price": price,
            "annual_rent": annual_rent,
            "deposit_fraction": deposit_fraction,
            "upfront_cost": round(upfront, 2),
            "interest_rate": interest_rate,
            "price_growth": price_growth,
            "rent_growth": rent_growth,
            "investment_return": investment_return,
            "selling_cost": selling_cost,
            "service_charge_per_sqm": a.service_charge_per_sqm,
        },
        "years": [r.as_dict() for r in rows],
        "disclaimer": (
            "A comparison under stated assumptions, most of which are contestable. Not advice."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price", type=float, default=1_500_000)
    parser.add_argument("--rent", type=float, default=105_000)
    parser.add_argument("--sqm", type=float, default=95)
    parser.add_argument("--years", type=int, default=15)
    parser.add_argument("--growth", type=float, default=0.03)
    args = parser.parse_args(argv)

    out = compare(
        price=args.price,
        annual_rent=args.rent,
        sqm=args.sqm,
        years=args.years,
        price_growth=args.growth,
        rent_growth=args.growth,
    )
    print(f"AED {args.price:,.0f} to buy, AED {args.rent:,.0f} a year to rent")
    print(f"upfront cost of buying: AED {out['inputs']['upfront_cost']:,.0f}\n")
    print("  year   buyer equity   renter wealth     advantage")
    for r in out["years"]:
        print(
            f"  {r['year']:>4}   {r['buyer_equity']:>12,.0f}   {r['renter_wealth']:>13,.0f}   "
            f"{r['advantage']:>11,.0f}"
        )
    print(f"\n  {out['verdict']}")
    print(f"  {out['disclaimer']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
