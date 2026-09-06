"""Simulation routes: mortgage affordability, cash-flow projection, rent versus buy, portfolio.

Everything here computes a projection from inputs the caller supplies. Nothing is stored, nothing
is executed, and every response repeats that it is not advice — these are the endpoints where a
reader is most likely to mistake a model for a recommendation.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import polars as pl
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from api.deps import WarehouseDep
from finance import portfolio as portfolio_model
from finance.dcf import project
from finance.mortgage import MortgageRules, affordability
from finance.rentbuy import compare as rent_vs_buy
from finance.yields import Assumptions, net_yield

router = APIRouter(tags=["simulate"])

NOT_ADVICE = (
    "A projection under the assumptions you supplied. Not a forecast, not a recommendation, and "
    "YIELDMAP cannot execute any transaction."
)


class AffordabilityRequest(BaseModel):
    price: Annotated[float, Field(gt=0, le=5e9)]
    monthly_income: Annotated[float, Field(gt=0, le=1e8)]
    existing_monthly_debt: Annotated[float, Field(ge=0, le=1e8)] = 0.0
    annual_rate: Annotated[float | None, Field(ge=0, le=0.5)] = None
    years: Annotated[int | None, Field(ge=1, le=40)] = None
    buyer: Literal["expatriate", "national"] = "expatriate"
    first_property: bool = True
    is_offplan: bool = False


class ProjectionRequest(BaseModel):
    price: Annotated[float, Field(gt=0, le=5e9)]
    annual_rent: Annotated[float, Field(ge=0, le=1e9)]
    sqm: Annotated[float, Field(gt=0, le=1e6)]
    years: Annotated[int, Field(ge=1, le=30)] = 5
    price_growth: Annotated[float, Field(ge=-0.5, le=0.5)] = 0.03
    rent_growth: Annotated[float, Field(ge=-0.5, le=0.5)] = 0.03
    loan_amount: Annotated[float, Field(ge=0, le=5e9)] = 0.0
    interest_rate: Annotated[float, Field(ge=0, le=0.5)] = 0.0425
    selling_cost: Annotated[float, Field(ge=0, le=0.2)] = 0.02
    discount_rate: Annotated[float, Field(ge=0, le=0.5)] = 0.08
    # Assumption overrides from the interface's editable panel.
    vacancy: Annotated[float | None, Field(ge=0, le=1)] = None
    service_charge_per_sqm: Annotated[float | None, Field(ge=0, le=5000)] = None
    management_fee: Annotated[float | None, Field(ge=0, le=1)] = None


class RentBuyRequest(BaseModel):
    price: Annotated[float, Field(gt=0, le=5e9)]
    annual_rent: Annotated[float, Field(gt=0, le=1e9)]
    sqm: Annotated[float, Field(gt=0, le=1e6)]
    years: Annotated[int, Field(ge=1, le=40)] = 15
    deposit_fraction: Annotated[float, Field(ge=0.05, le=1.0)] = 0.20
    interest_rate: Annotated[float, Field(ge=0, le=0.5)] = 0.0425
    price_growth: Annotated[float, Field(ge=-0.5, le=0.5)] = 0.03
    rent_growth: Annotated[float, Field(ge=-0.5, le=0.5)] = 0.03
    investment_return: Annotated[float, Field(ge=0, le=0.5)] = 0.05


class HoldingIn(BaseModel):
    area_key: str
    property_type: str = "unit"
    rooms: int | None = None
    value: Annotated[float, Field(gt=0, le=5e9)]
    annual_rent: Annotated[float, Field(ge=0, le=1e9)]
    sqm: Annotated[float, Field(gt=0, le=1e6)]
    developer: str | None = None
    loan: Annotated[float, Field(ge=0, le=5e9)] = 0.0


class PortfolioRequest(BaseModel):
    holdings: Annotated[list[HoldingIn], Field(min_length=1, max_length=50)]
    years: Annotated[int, Field(ge=1, le=30)] = 5
    price_growth: Annotated[float, Field(ge=-0.5, le=0.5)] = 0.03


def _assumptions(req: ProjectionRequest) -> Assumptions:
    base = Assumptions.load()
    overrides = {
        k: v
        for k, v in (
            ("vacancy", req.vacancy),
            ("service_charge_per_sqm", req.service_charge_per_sqm),
            ("management_fee", req.management_fee),
        )
        if v is not None
    }
    return base.replace(**overrides) if overrides else base


@router.get("/simulate/assumptions")
def assumptions() -> dict[str, Any]:
    """The editable inputs behind every simulation, with how well founded each one is."""
    return {
        "yield": Assumptions.load().editable(),
        "mortgage": MortgageRules.load().editable(),
        "unverified": MortgageRules.load().unverified_fields(),
        "notice": (
            "Fields marked unverified are shown as assumptions rather than as rules. Change them "
            "and the numbers change."
        ),
    }


@router.post("/simulate/affordability")
def simulate_affordability(req: AffordabilityRequest) -> dict[str, Any]:
    """How much can be borrowed, and which constraint is doing the limiting."""
    result = affordability(
        price=req.price,
        monthly_income=req.monthly_income,
        existing_monthly_debt=req.existing_monthly_debt,
        annual_rate=req.annual_rate,
        years=req.years,
        buyer=req.buyer,
        first_property=req.first_property,
        is_offplan=req.is_offplan,
    )
    return {
        "max_loan": result.max_loan,
        "deposit_required": result.deposit_required,
        "monthly_payment": result.monthly_payment,
        "binding_constraint": result.binding_constraint,
        "ltv_cap": result.ltv_cap,
        "ltv_band": result.ltv_band,
        "loan_by_ltv": result.loan_by_ltv,
        "loan_by_income": result.loan_by_income,
        "unverified_parameters": result.unverified_parameters,
        "caveat": result.caveat,
        "notice": NOT_ADVICE,
    }


@router.post("/simulate/projection")
def simulate_projection(req: ProjectionRequest) -> dict[str, Any]:
    """Holding-period cash flows, IRR and NPV, levered and unlevered."""
    if req.loan_amount > req.price:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="the loan cannot exceed the purchase price",
        )
    a = _assumptions(req)
    projection = project(
        price=req.price,
        annual_rent=req.annual_rent,
        sqm=req.sqm,
        years=req.years,
        price_growth=req.price_growth,
        rent_growth=req.rent_growth,
        loan_amount=req.loan_amount,
        interest_rate=req.interest_rate,
        selling_cost=req.selling_cost,
        discount_rate=req.discount_rate,
        assumptions=a,
    )
    yield_working = net_yield(req.annual_rent, req.price, req.sqm, a)
    return {
        **projection.as_dict(),
        "yield": yield_working,
        "notice": NOT_ADVICE,
    }


@router.post("/simulate/rent-vs-buy")
def simulate_rent_vs_buy(req: RentBuyRequest) -> dict[str, Any]:
    """Buyer equity against renter wealth, year by year, and the break-even."""
    return {**rent_vs_buy(**req.model_dump()), "notice": NOT_ADVICE}


@router.post("/simulate/portfolio")
def simulate_portfolio(req: PortfolioRequest, wh: WarehouseDep) -> dict[str, Any]:
    """Blended yield, portfolio IRR, concentration and correlation for a basket."""
    holdings = [portfolio_model.Holding(**h.model_dump()) for h in req.holdings]
    monthly = wh.query(portfolio_model.AREA_MONTHLY_SQL).frame
    if monthly.height == 0:
        monthly = pl.DataFrame({"area_key": [], "month": [], "ppsqm": [], "n": []})
    out = portfolio_model.analyse(holdings, monthly, years=req.years, price_growth=req.price_growth)
    return {**out, "provenance": wh.provenance(), "notice": NOT_ADVICE}
