"""Mortgage affordability under UAE lending rules.

Two constraints bind, and which one binds is the interesting part. The loan-to-value cap limits
the loan against the property; the debt-burden ratio limits it against the borrower's income. A
buyer with a large deposit and a modest salary is limited by income; a buyer with a high salary and
a small deposit is limited by the deposit. The calculator says which, because "you can borrow this
much" is far less useful than "you can borrow this much, and here is what is stopping you".

Every parameter comes from config/mortgage.yaml and every one carries a verification status. The
Central Bank's site refuses automated clients, so the lending caps are currently unverified and the
interface must present them as editable assumptions rather than as rules. Getting that wrong would
be the single most misleading thing this project could do, because a wrong cap produces a confident
affordability figure that a real person might act on.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy_financial as npf
import yaml

ROOT = Path(__file__).resolve().parent.parent
MORTGAGE_PATH = ROOT / "config" / "mortgage.yaml"

BuyerStatus = Literal["expatriate", "national"]


@dataclass(frozen=True)
class MortgageRules:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path = MORTGAGE_PATH) -> MortgageRules:
        return cls(raw=yaml.safe_load(path.read_text()))

    def value(self, key: str) -> float:
        return float(self.raw[key]["value"])

    def max_ltv(
        self, *, price: float, buyer: BuyerStatus, first_property: bool, is_offplan: bool
    ) -> tuple[float, str]:
        """The applicable loan-to-value cap and the band it came from.

        Bands are matched in file order, most specific first, so a price band with an upper bound
        wins over the open-ended one for the same buyer.
        """
        if is_offplan:
            return self.value("offplan_max_ltv"), "off-plan purchase"

        for band in self.raw["ltv_caps"]["bands"]:
            if band["buyer"] != buyer or bool(band["first_property"]) != bool(first_property):
                continue
            ceiling = band["max_price_aed"]
            if ceiling is None or price <= float(ceiling):
                label = f"{buyer}, {'first' if first_property else 'additional'} property"
                if ceiling is not None:
                    label += f", up to AED {float(ceiling):,.0f}"
                return float(band["max_ltv"]), label

        raise ValueError(f"no loan-to-value band matches {buyer}, first={first_property}")

    def unverified_fields(self) -> list[str]:
        """Which parameters are still awaiting a primary source."""
        return [
            key
            for key, body in self.raw.items()
            if isinstance(body, dict) and body.get("status") == "unverified"
        ]

    def editable(self) -> list[dict[str, Any]]:
        return [
            {
                "key": key,
                "label": body.get("label", key),
                "value": body.get("value"),
                "unit": body.get("unit"),
                "status": body.get("status"),
                "source": " ".join(str(body.get("source", "")).split()) or None,
                "source_url": body.get("source_url"),
                "verified_on": body.get("verified_on"),
            }
            for key, body in self.raw.items()
            if isinstance(body, dict) and ("value" in body or key == "ltv_caps")
        ]


def monthly_payment(principal: float, annual_rate: float, years: int) -> float:
    """Level repayment on an amortising loan."""
    if principal <= 0:
        return 0.0
    if years <= 0:
        raise ValueError("term must be at least one year")
    if annual_rate == 0:
        return principal / (years * 12)
    return float(-npf.pmt(annual_rate / 12, years * 12, principal))


def amortisation_schedule(
    principal: float, annual_rate: float, years: int
) -> list[dict[str, float]]:
    """Year-by-year interest, principal and closing balance.

    The DCF needs the split between interest and principal: only the interest is a cost, while the
    principal repaid is equity accumulating in the property.
    """
    payment = monthly_payment(principal, annual_rate, years)
    rate = annual_rate / 12
    balance = principal
    rows: list[dict[str, float]] = []
    for year in range(1, years + 1):
        interest_paid = principal_paid = 0.0
        for _ in range(12):
            interest = balance * rate
            principal_part = min(payment - interest, balance)
            balance -= principal_part
            interest_paid += interest
            principal_paid += principal_part
        rows.append(
            {
                "year": year,
                "payment": payment * 12,
                "interest": interest_paid,
                "principal": principal_paid,
                "closing_balance": max(balance, 0.0),
            }
        )
    return rows


@dataclass
class Affordability:
    max_loan: float
    deposit_required: float
    monthly_payment: float
    binding_constraint: str
    ltv_cap: float
    ltv_band: str
    loan_by_ltv: float
    loan_by_income: float
    unverified_parameters: list[str]

    @property
    def caveat(self) -> str | None:
        if not self.unverified_parameters:
            return None
        return (
            "Lending parameters are unverified against a primary source and are shown as editable "
            "assumptions, not as rules: " + ", ".join(self.unverified_parameters)
        )


def affordability(
    *,
    price: float,
    monthly_income: float,
    existing_monthly_debt: float = 0.0,
    annual_rate: float | None = None,
    years: int | None = None,
    buyer: BuyerStatus = "expatriate",
    first_property: bool = True,
    is_offplan: bool = False,
    rules: MortgageRules | None = None,
) -> Affordability:
    """How much can be borrowed, and which constraint is doing the limiting."""
    rules = rules or MortgageRules.load()
    rate = rules.value("default_interest_rate") if annual_rate is None else annual_rate
    term = int(rules.value("default_term_years") if years is None else years)
    term = min(term, int(rules.value("max_term_years")))

    ltv_cap, band = rules.max_ltv(
        price=price, buyer=buyer, first_property=first_property, is_offplan=is_offplan
    )
    loan_by_ltv = price * ltv_cap

    # The income constraint: total debt service may not exceed the burden ratio, and existing
    # borrowing eats into that allowance before this mortgage does.
    allowance = monthly_income * rules.value("debt_burden_ratio") - existing_monthly_debt
    if allowance <= 0:
        loan_by_income = 0.0
    elif rate == 0:
        loan_by_income = allowance * term * 12
    else:
        loan_by_income = float(npf.pv(rate / 12, term * 12, -allowance))

    max_loan = max(min(loan_by_ltv, loan_by_income), 0.0)
    binding = "loan-to-value cap" if loan_by_ltv <= loan_by_income else "debt burden ratio"
    if max_loan == 0.0:
        binding = "income leaves no room for further borrowing"

    return Affordability(
        max_loan=max_loan,
        deposit_required=max(price - max_loan, 0.0),
        monthly_payment=monthly_payment(max_loan, rate, term),
        binding_constraint=binding,
        ltv_cap=ltv_cap,
        ltv_band=band,
        loan_by_ltv=loan_by_ltv,
        loan_by_income=max(loan_by_income, 0.0),
        unverified_parameters=rules.unverified_fields(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price", type=float, default=1_500_000)
    parser.add_argument("--income", type=float, default=35_000)
    parser.add_argument("--existing-debt", type=float, default=0.0)
    parser.add_argument("--buyer", choices=["expatriate", "national"], default="expatriate")
    args = parser.parse_args(argv)

    result = affordability(
        price=args.price,
        monthly_income=args.income,
        existing_monthly_debt=args.existing_debt,
        buyer=args.buyer,
    )
    print(f"price AED {args.price:,.0f}, income AED {args.income:,.0f}/month")
    print(f"  loan-to-value cap  {result.ltv_cap:.0%}  ({result.ltv_band})")
    print(f"  loan by LTV        AED {result.loan_by_ltv:,.0f}")
    print(f"  loan by income     AED {result.loan_by_income:,.0f}")
    print(f"  maximum loan       AED {result.max_loan:,.0f}")
    print(f"  deposit required   AED {result.deposit_required:,.0f}")
    print(f"  monthly payment    AED {result.monthly_payment:,.0f}")
    print(f"  binding constraint {result.binding_constraint}")
    if result.caveat:
        print(f"\n  {result.caveat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
