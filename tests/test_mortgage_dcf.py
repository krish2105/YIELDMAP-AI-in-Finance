"""Mortgage and cash-flow tests.

The IRR tests are built so the answer can be worked out by hand. A property bought outright for a
million, let at seventy thousand a year with no costs and sold five years later for what it cost,
returns exactly 7% — no solver required to know that. Tests whose expected values come from the
code they are testing prove only that the code is consistent with itself.
"""

from __future__ import annotations

import pytest
import yaml

from finance.dcf import irr, npv, project
from finance.mortgage import (
    MORTGAGE_PATH,
    MortgageRules,
    affordability,
    amortisation_schedule,
    monthly_payment,
)
from finance.yields import Assumptions


@pytest.fixture(scope="module")
def rules() -> MortgageRules:
    return MortgageRules.load()


@pytest.fixture(scope="module")
def costless() -> Assumptions:
    """Assumptions with every cost switched off, so an IRR can be checked by hand."""
    return Assumptions.load().replace(
        vacancy=0.0,
        service_charge_per_sqm=0.0,
        management_fee=0.0,
        maintenance=0.0,
        dld_transfer_fee=0.0,
        agent_commission=0.0,
        registration_fee=0.0,
    )


class TestMortgageConfig:
    def test_every_lending_parameter_declares_its_status_and_source(self):
        raw = yaml.safe_load(MORTGAGE_PATH.read_text())
        for key, body in raw.items():
            if not isinstance(body, dict):
                continue
            assert body.get("status") in {"verified", "estimate", "unverified"}, key
            if body.get("status") == "unverified":
                assert body.get("source_url"), f"{key} must name the source it awaits"

    def test_the_unverified_parameters_are_reported_rather_than_hidden(self, rules):
        """A wrong cap produces a confident affordability figure someone might act on."""
        assert "ltv_caps" in rules.unverified_fields()
        assert "debt_burden_ratio" in rules.unverified_fields()


class TestLoanToValueBands:
    def test_an_expatriate_first_home_under_five_million(self, rules):
        cap, band = rules.max_ltv(
            price=1_500_000, buyer="expatriate", first_property=True, is_offplan=False
        )
        assert cap == 0.80
        assert "expatriate" in band and "first" in band

    def test_a_more_expensive_first_home_is_capped_lower(self, rules):
        cap, _ = rules.max_ltv(
            price=8_000_000, buyer="expatriate", first_property=True, is_offplan=False
        )
        assert cap == 0.70

    def test_a_second_property_is_capped_lower_still(self, rules):
        cap, _ = rules.max_ltv(
            price=1_500_000, buyer="expatriate", first_property=False, is_offplan=False
        )
        assert cap == 0.60

    def test_a_national_may_borrow_more_than_an_expatriate_on_like_terms(self, rules):
        national, _ = rules.max_ltv(
            price=1_500_000, buyer="national", first_property=True, is_offplan=False
        )
        expat, _ = rules.max_ltv(
            price=1_500_000, buyer="expatriate", first_property=True, is_offplan=False
        )
        assert national > expat

    def test_off_plan_overrides_every_other_band(self, rules):
        cap, band = rules.max_ltv(
            price=1_000_000, buyer="national", first_property=True, is_offplan=True
        )
        assert cap == 0.50
        assert "off-plan" in band


class TestPayments:
    def test_matches_the_standard_annuity_formula(self):
        principal, annual, years = 1_000_000.0, 0.05, 20
        r = annual / 12
        n = years * 12
        expected = principal * r / (1 - (1 + r) ** -n)
        assert monthly_payment(principal, annual, years) == pytest.approx(expected)

    def test_an_interest_free_loan_repays_in_equal_slices(self):
        assert monthly_payment(120_000, 0.0, 10) == pytest.approx(1_000.0)

    def test_no_loan_means_no_payment(self):
        assert monthly_payment(0, 0.05, 25) == 0.0

    def test_a_zero_term_is_rejected_rather_than_dividing_by_zero(self):
        with pytest.raises(ValueError, match="at least one year"):
            monthly_payment(100_000, 0.05, 0)


class TestAmortisation:
    def test_the_loan_is_exactly_repaid_over_its_term(self):
        schedule = amortisation_schedule(1_000_000, 0.05, 25)
        assert sum(row["principal"] for row in schedule) == pytest.approx(1_000_000, abs=1.0)
        assert schedule[-1]["closing_balance"] == pytest.approx(0.0, abs=1.0)

    def test_interest_falls_and_principal_rises_as_the_balance_shrinks(self):
        schedule = amortisation_schedule(1_000_000, 0.05, 25)
        assert schedule[0]["interest"] > schedule[-1]["interest"]
        assert schedule[0]["principal"] < schedule[-1]["principal"]

    def test_each_year_of_payments_splits_into_interest_and_principal(self):
        for row in amortisation_schedule(800_000, 0.045, 20):
            assert row["payment"] == pytest.approx(row["interest"] + row["principal"], abs=0.01)


class TestAffordability:
    def test_the_twenty_percent_deposit_case(self):
        """An expatriate first home at 80% LTV needs a fifth of the price in cash."""
        result = affordability(price=1_500_000, monthly_income=60_000)
        assert result.max_loan == pytest.approx(1_200_000)
        assert result.deposit_required == pytest.approx(300_000)
        assert result.binding_constraint == "loan-to-value cap"

    def test_a_modest_income_is_limited_by_the_debt_burden_not_the_deposit(self):
        result = affordability(price=5_000_000, monthly_income=20_000)
        assert result.binding_constraint == "debt burden ratio"
        assert result.max_loan < result.loan_by_ltv

    def test_existing_borrowing_reduces_what_can_be_borrowed(self):
        clear = affordability(price=5_000_000, monthly_income=30_000)
        indebted = affordability(
            price=5_000_000, monthly_income=30_000, existing_monthly_debt=10_000
        )
        assert indebted.max_loan < clear.max_loan

    def test_an_income_already_fully_committed_can_borrow_nothing(self):
        result = affordability(price=1_500_000, monthly_income=20_000, existing_monthly_debt=15_000)
        assert result.max_loan == 0.0
        assert "no room" in result.binding_constraint

    def test_a_higher_rate_reduces_what_the_same_income_supports(self):
        cheap = affordability(price=9_000_000, monthly_income=40_000, annual_rate=0.02)
        dear = affordability(price=9_000_000, monthly_income=40_000, annual_rate=0.09)
        assert dear.max_loan < cheap.max_loan

    def test_the_result_carries_the_unverified_caveat(self):
        assert "unverified" in affordability(price=1_000_000, monthly_income=40_000).caveat


class TestIrrByHand:
    """Expected values worked out on paper, not taken from the code being tested."""

    def test_a_flat_market_returns_exactly_the_rental_yield(self, costless):
        # Buy for a million, receive 70,000 a year for five years, sell for a million.
        # The cash flows are -1,000,000 then four years of 70,000 then 1,070,000, which is
        # a bond at 7%.
        p = project(
            price=1_000_000,
            annual_rent=70_000,
            sqm=100,
            years=5,
            price_growth=0.0,
            rent_growth=0.0,
            loan_amount=0.0,
            selling_cost=0.0,
            assumptions=costless,
        )
        assert p.irr == pytest.approx(0.07, abs=1e-6)

    def test_pure_appreciation_returns_exactly_the_growth_rate(self, costless):
        # No rent at all: a million becomes a million times 1.05 to the fifth, so the annualised
        # return is 5% by construction.
        p = project(
            price=1_000_000,
            annual_rent=0.0,
            sqm=100,
            years=5,
            price_growth=0.05,
            rent_growth=0.0,
            loan_amount=0.0,
            selling_cost=0.0,
            assumptions=costless,
        )
        assert p.irr == pytest.approx(0.05, abs=1e-6)

    def test_the_equity_invested_is_the_price_when_there_are_no_costs_or_loan(self, costless):
        p = project(
            price=1_000_000,
            annual_rent=70_000,
            sqm=100,
            years=5,
            loan_amount=0.0,
            selling_cost=0.0,
            assumptions=costless,
        )
        assert p.equity_invested == pytest.approx(1_000_000)

    def test_a_five_percent_selling_cost_lowers_the_return(self, costless):
        kwargs = {
            "price": 1_000_000,
            "annual_rent": 70_000,
            "sqm": 100,
            "years": 5,
            "price_growth": 0.0,
            "rent_growth": 0.0,
            "loan_amount": 0.0,
            "assumptions": costless,
        }
        assert project(**kwargs, selling_cost=0.05).irr < project(**kwargs, selling_cost=0.0).irr


class TestIrrEdges:
    def test_a_series_that_never_turns_positive_has_no_return(self):
        assert irr([-100.0, -10.0, -10.0]) is None

    def test_a_series_that_never_turns_negative_has_no_return(self):
        assert irr([100.0, 10.0]) is None

    def test_a_single_flow_has_no_return(self):
        assert irr([-100.0]) is None

    def test_npv_discounts_from_year_one(self):
        assert npv(0.10, [-100.0, 110.0]) == pytest.approx(0.0)
        assert npv(0.0, [-100.0, 50.0, 60.0]) == pytest.approx(10.0)


class TestLeverage:
    def test_borrowing_lifts_the_return_when_growth_beats_the_rate(self, costless):
        p = project(
            price=1_000_000,
            annual_rent=70_000,
            sqm=100,
            years=5,
            price_growth=0.08,
            rent_growth=0.03,
            loan_amount=700_000,
            interest_rate=0.04,
            selling_cost=0.0,
            assumptions=costless,
        )
        assert p.unlevered_irr is not None
        assert p.irr > p.unlevered_irr

    def test_borrowing_deepens_the_loss_when_prices_fall(self, costless):
        p = project(
            price=1_000_000,
            annual_rent=70_000,
            sqm=100,
            years=5,
            price_growth=-0.06,
            rent_growth=0.0,
            loan_amount=700_000,
            interest_rate=0.06,
            selling_cost=0.0,
            assumptions=costless,
        )
        assert p.irr < p.unlevered_irr

    def test_an_unlevered_projection_reports_no_separate_unlevered_figure(self, costless):
        p = project(
            price=1_000_000, annual_rent=70_000, sqm=100, loan_amount=0.0, assumptions=costless
        )
        assert p.unlevered_irr is None


class TestOutput:
    def test_carries_its_assumptions_and_says_it_is_not_advice(self):
        out = project(price=1_500_000, annual_rent=100_000, sqm=95, years=5).as_dict()
        assert out["assumptions"]["years"] == 5
        assert "not advice" in out["disclaimer"]
        assert len(out["flows"]) == 6  # year zero plus five years

    def test_the_yearly_lines_reconcile_to_the_net_figure(self):
        p = project(price=1_500_000, annual_rent=100_000, sqm=95, years=5, loan_amount=1_000_000)
        for f in p.flows[1:]:
            assert f.net == pytest.approx(
                f.rent + f.operating_costs + f.interest + f.principal + f.capital
            )
