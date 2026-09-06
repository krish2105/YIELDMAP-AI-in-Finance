"""Portfolio, rent-versus-buy and developer-table tests."""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from finance.developers import build_league
from finance.portfolio import (
    Holding,
    analyse,
    area_correlations,
    blended_yield,
    concentration,
    diversification,
    effective_holdings,
    herfindahl,
    portfolio_irr,
)
from finance.rentbuy import compare
from finance.yields import Assumptions


@pytest.fixture(scope="module")
def a() -> Assumptions:
    return Assumptions.load()


def holding(area="marina", value=1_000_000.0, rent=70_000.0, sqm=90.0, developer="emaar"):
    return Holding(
        area_key=area,
        property_type="unit",
        rooms=1,
        value=value,
        annual_rent=rent,
        sqm=sqm,
        developer=developer,
    )


class TestConcentrationMeasure:
    def test_a_single_holding_is_maximally_concentrated(self):
        assert herfindahl([100.0]) == pytest.approx(1.0)

    def test_four_equal_holdings_score_a_quarter(self):
        assert herfindahl([25.0] * 4) == pytest.approx(0.25)

    def test_one_dominant_holding_scores_near_one(self):
        assert herfindahl([970.0, 10.0, 10.0, 10.0]) > 0.9

    def test_the_effective_count_inverts_the_index(self):
        assert effective_holdings([25.0] * 4) == pytest.approx(4.0)
        assert effective_holdings([970.0, 10.0, 10.0, 10.0]) < 1.2

    def test_an_empty_basket_is_not_a_division_by_zero(self):
        assert herfindahl([]) == 0.0
        assert effective_holdings([]) == 0.0

    def test_concentration_is_reported_by_area_and_by_developer(self):
        holdings = [
            holding(area="marina", developer="emaar"),
            holding(area="jvc", developer="emaar"),
            holding(area="jvc", developer="damac"),
        ]
        c = concentration(holdings)
        assert c["by_area"]["groups"] == 2
        assert c["by_developer"]["groups"] == 2
        assert c["by_holding"]["count"] == 3

    def test_all_holdings_with_one_developer_is_full_developer_concentration(self):
        c = concentration([holding(area="a"), holding(area="b")])
        assert c["by_developer"]["hhi"] == pytest.approx(1.0)
        assert c["by_area"]["hhi"] == pytest.approx(0.5)


class TestBlendedYield:
    def test_is_value_weighted_not_averaged(self, a):
        """A large low-yield holding and a small high-yield one is not their simple mean."""
        holdings = [
            holding(value=2_000_000.0, rent=80_000.0),  # 4%
            holding(value=200_000.0, rent=20_000.0),  # 10%
        ]
        blended = blended_yield(holdings, a)["gross"]
        simple_mean = (0.04 + 0.10) / 2
        assert blended == pytest.approx(100_000 / 2_200_000)
        assert blended < simple_mean

    def test_net_is_below_gross_for_a_basket_too(self, a):
        y = blended_yield([holding(), holding(area="jvc")], a)
        assert y["net"] < y["gross"]

    def test_an_empty_basket_yields_nothing_rather_than_raising(self, a):
        assert blended_yield([], a)["gross"] is None


class TestPortfolioIrr:
    def test_combines_the_holdings_into_one_return(self):
        result = portfolio_irr([holding(), holding(area="jvc")], years=5)
        assert result["irr"] is not None
        assert len(result["flows"]) == 6

    def test_an_empty_basket_has_no_return(self):
        assert portfolio_irr([])["irr"] is None

    def test_stronger_growth_gives_a_higher_return(self):
        weak = portfolio_irr([holding()], years=5, price_growth=0.0)["irr"]
        strong = portfolio_irr([holding()], years=5, price_growth=0.08)["irr"]
        assert strong > weak


def monthly_frame(areas: dict[str, np.ndarray]) -> pl.DataFrame:
    rows = []
    for area, values in areas.items():
        for i, v in enumerate(values):
            rows.append(
                {
                    "area_key": area,
                    "month": date(2020 + i // 12, i % 12 + 1, 1),
                    "ppsqm": float(v),
                    "n": 10,
                }
            )
    return pl.DataFrame(rows)


class TestCorrelation:
    def test_two_areas_moving_together_correlate_near_one(self):
        rng = np.random.default_rng(1)
        shocks = rng.normal(0, 0.03, 48)
        base = 10_000 * np.exp(np.cumsum(shocks))
        frame = monthly_frame({"a": base, "b": base * 1.4})
        corr = area_correlations(frame, ["a", "b"])
        assert corr["mean_correlation"] > 0.95

    def test_independent_areas_correlate_near_zero(self):
        rng = np.random.default_rng(2)
        frame = monthly_frame(
            {
                "a": 10_000 * np.exp(np.cumsum(rng.normal(0, 0.03, 60))),
                "b": 9_000 * np.exp(np.cumsum(rng.normal(0, 0.03, 60))),
            }
        )
        assert abs(area_correlations(frame, ["a", "b"])["mean_correlation"]) < 0.35

    def test_correlates_returns_rather_than_levels(self):
        """Two rising series correlate near one whatever they do, which says nothing."""
        rising_a = 10_000 * np.array([1.01**i for i in range(60)])
        rng = np.random.default_rng(3)
        rising_b = 8_000 * np.array([1.01**i for i in range(60)]) * np.exp(rng.normal(0, 0.05, 60))
        levels = np.corrcoef(rising_a, rising_b)[0, 1]
        corr = area_correlations(monthly_frame({"a": rising_a, "b": rising_b}), ["a", "b"])
        assert levels > 0.95
        assert corr["mean_correlation"] < levels

    def test_says_so_when_there_is_not_enough_shared_history(self):
        frame = monthly_frame({"a": np.repeat(10_000.0, 5)})
        corr = area_correlations(frame, ["a"])
        assert corr["matrix"] is None
        assert "at least two areas" in corr["reason"]


class TestDiversification:
    def test_correlated_holdings_count_for_less_than_their_number(self):
        """Four apartments in four Dubai communities are not four independent positions."""
        conc = {"by_holding": {"effective": 4.0}}
        adjusted = diversification(conc, {"mean_correlation": 0.8})
        assert adjusted["correlation_adjusted"] < 4.0
        assert adjusted["correlation_adjusted"] > 1.0

    def test_uncorrelated_holdings_keep_their_full_count(self):
        adjusted = diversification({"by_holding": {"effective": 4.0}}, {"mean_correlation": 0.0})
        assert adjusted["correlation_adjusted"] == pytest.approx(4.0)

    def test_perfectly_correlated_holdings_collapse_towards_one(self):
        adjusted = diversification({"by_holding": {"effective": 4.0}}, {"mean_correlation": 0.999})
        assert adjusted["correlation_adjusted"] < 1.05

    def test_the_adjusted_figure_never_exceeds_the_naive_one(self):
        for rho in (0.0, 0.2, 0.5, 0.9):
            adjusted = diversification(
                {"by_holding": {"effective": 5.0}}, {"mean_correlation": rho}
            )
            assert adjusted["correlation_adjusted"] <= 5.0 + 1e-9

    def test_says_so_when_correlation_could_not_be_measured(self):
        out = diversification({"by_holding": {"effective": 3.0}}, {"mean_correlation": None})
        assert out["correlation_adjusted"] is None
        assert "not enough shared history" in out["note"]


class TestAnalyse:
    def test_produces_a_complete_picture_and_says_it_is_not_advice(self):
        rng = np.random.default_rng(4)
        frame = monthly_frame(
            {
                "marina": 10_000 * np.exp(np.cumsum(rng.normal(0, 0.02, 60))),
                "jvc": 8_000 * np.exp(np.cumsum(rng.normal(0, 0.02, 60))),
            }
        )
        out = analyse([holding(area="marina"), holding(area="jvc")], frame)
        assert out["holdings"] == 2
        assert out["blended_yield"]["net"] is not None
        assert out["concentration"]["by_area"]["groups"] == 2
        assert "Not advice" in out["disclaimer"]


class TestRentVersusBuy:
    def test_a_rising_market_favours_buying_eventually(self):
        out = compare(price=1_500_000, annual_rent=105_000, sqm=95, years=20, price_growth=0.04)
        assert out["break_even_year"] is not None
        assert "overtakes" in out["verdict"]

    def test_a_falling_market_may_never_favour_buying_and_says_so(self):
        out = compare(
            price=1_500_000,
            annual_rent=60_000,
            sqm=95,
            years=10,
            price_growth=-0.05,
            rent_growth=0.0,
            investment_return=0.08,
        )
        assert out["break_even_year"] is None
        assert "does not overtake" in out["verdict"]

    def test_the_renter_starts_ahead_by_the_upfront_cost(self):
        """The buyer's deposit and fees are money the renter still has."""
        out = compare(price=1_500_000, annual_rent=105_000, sqm=95, years=5)
        assert out["years"][0]["renter_wealth"] > 0
        assert out["inputs"]["upfront_cost"] > 1_500_000 * 0.20

    def test_stronger_price_growth_brings_the_break_even_forward(self):
        slow = compare(price=1_500_000, annual_rent=105_000, sqm=95, years=25, price_growth=0.01)
        fast = compare(price=1_500_000, annual_rent=105_000, sqm=95, years=25, price_growth=0.07)
        assert fast["break_even_year"] <= slow["break_even_year"]

    def test_a_better_investment_return_pushes_the_break_even_back(self):
        """A renter who can invest well is a harder benchmark to beat."""
        poor = compare(
            price=1_500_000, annual_rent=105_000, sqm=95, years=25, investment_return=0.01
        )
        rich = compare(
            price=1_500_000, annual_rent=105_000, sqm=95, years=25, investment_return=0.12
        )
        assert (rich["break_even_year"] or 99) >= (poor["break_even_year"] or 99)

    def test_reports_a_row_for_every_year_and_says_it_is_not_advice(self):
        out = compare(price=1_500_000, annual_rent=105_000, sqm=95, years=12)
        assert len(out["years"]) == 12
        assert "Not advice" in out["disclaimer"]


class TestDeveloperLeague:
    def _frame(self, rows):
        return pl.DataFrame(rows)

    def test_a_premium_developer_is_ranked_above_a_discount_one(self):
        league = build_league(
            self._frame(
                [
                    {
                        "project_name": "premium",
                        "n": 100,
                        "areas": 3,
                        "first_seen": date(2020, 1, 1),
                        "last_seen": date(2024, 1, 1),
                        "median_price": 2e6,
                        "median_ppsqm": 20_000.0,
                        "median_relative_price": 1.25,
                        "offplan_share": 0.3,
                        "relative_price_sd": 0.1,
                    },
                    {
                        "project_name": "discount",
                        "n": 100,
                        "areas": 3,
                        "first_seen": date(2020, 1, 1),
                        "last_seen": date(2024, 1, 1),
                        "median_price": 1e6,
                        "median_ppsqm": 10_000.0,
                        "median_relative_price": 0.80,
                        "offplan_share": 0.3,
                        "relative_price_sd": 0.1,
                    },
                ]
            )
        )
        assert league["project_name"][0] == "premium"
        assert league["premium_pct"][0] == pytest.approx(25.0)
        assert league["verdict"][0] == "sells above its areas"
        assert league["verdict"][1] == "sells below its areas"

    def test_a_developer_in_line_with_its_areas_is_labelled_so(self):
        league = build_league(
            self._frame(
                [
                    {
                        "project_name": "ordinary",
                        "n": 50,
                        "areas": 2,
                        "first_seen": date(2021, 1, 1),
                        "last_seen": date(2024, 1, 1),
                        "median_price": 1e6,
                        "median_ppsqm": 12_000.0,
                        "median_relative_price": 1.01,
                        "offplan_share": 0.2,
                        "relative_price_sd": 0.1,
                    },
                ]
            )
        )
        assert league["verdict"][0] == "sells in line with its areas"

    def test_activity_is_reported_per_year_not_just_in_total(self):
        league = build_league(
            self._frame(
                [
                    {
                        "project_name": "steady",
                        "n": 100,
                        "areas": 2,
                        "first_seen": date(2020, 1, 1),
                        "last_seen": date(2024, 1, 1),
                        "median_price": 1e6,
                        "median_ppsqm": 12_000.0,
                        "median_relative_price": 1.0,
                        "offplan_share": 0.2,
                        "relative_price_sd": 0.1,
                    },
                ]
            )
        )
        assert league["years_active"][0] == pytest.approx(4.0, abs=0.05)
        assert league["sales_per_year"][0] == pytest.approx(25.0, abs=0.5)

    def test_an_empty_table_is_returned_unchanged(self):
        assert build_league(pl.DataFrame()).height == 0
