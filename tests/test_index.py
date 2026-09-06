"""Repeat-sales index tests.

The first test is the whole reason this model exists. A median price per square metre moves when
the mix of what sold changes, not only when prices change; a repeat-sales index compares each
property against itself so composition cancels. If that property does not hold, the index is just
an expensive median.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from finance.index import (
    MIN_HOLD_DAYS,
    annual_growth,
    build_pairs,
    estimate_index,
    largest_connected_component,
)


def sale(unit: str, area: str, when: date, ppsqm: float, sqm: float = 100.0, rooms: int = 2):
    return {
        "ts": when,
        "area_key": area,
        "building_name": unit,
        "property_type": "unit",
        "rooms": rooms,
        "area_sqm": sqm,
        "price_aed": ppsqm * sqm,
        "price_per_sqm": ppsqm,
        "transaction_id": f"{unit}-{when}",
    }


def frame(rows) -> pl.DataFrame:
    return pl.DataFrame(rows).sort("ts")


def month_date(m: int, day: int = 10) -> date:
    return date(2020 + m // 12, m % 12 + 1, day)


def panel(
    n_units: int,
    *,
    months: int = 24,
    gaps: tuple[int, ...] = (4, 5, 6, 7, 9, 12),
    price,
    area: str = "x",
    prefix: str = "u",
    seed: int = 1,
):
    """A repeat-sales panel whose periods form one connected web.

    Gaps are varied deliberately. If every unit were resold after exactly the same number of
    months, the periods would split into independent chains — January-to-July never meeting
    February-to-August — and a repeat-sales index is not identified across a break like that. Real
    holding periods vary, so the fixtures should too.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for unit in range(n_units):
        gap = int(rng.choice(gaps))
        buy = int(rng.integers(0, max(1, months - gap)))
        sell = buy + gap
        uid = f"{prefix}{unit}"
        rows.append(sale(uid, area, month_date(buy), price(buy, unit, rng)))
        rows.append(sale(uid, area, month_date(sell), price(sell, unit, rng)))
    return rows


class TestCompositionImmunity:
    """The reason a repeat-sales index exists rather than a median."""

    def test_a_changing_mix_moves_the_median_but_not_the_index(self):
        rng = np.random.default_rng(0)
        rows = []
        # Two markets, cheap and dear. No individual property ever changes price. Early months are
        # mostly cheap sales, later months mostly dear ones, so the mix moves and prices do not.
        for unit in range(600):
            gap = int(rng.choice([4, 5, 6, 7, 9]))
            buy = int(rng.integers(0, 24 - gap))
            # The later a unit trades, the likelier it is a dear one.
            dear = rng.random() < (0.2 + 0.7 * buy / 24)
            ppsqm = 25_000.0 if dear else 8_000.0
            area = "dear" if dear else "cheap"
            uid = f"{area}{unit}"
            rows.append(sale(uid, area, month_date(buy), ppsqm))
            rows.append(sale(uid, area, month_date(buy + gap), ppsqm))

        df = frame(rows)

        medians = (
            df.with_columns((pl.col("ts").dt.year() * 12 + pl.col("ts").dt.month()).alias("m"))
            .group_by("m")
            .agg(pl.col("price_per_sqm").median().alias("median"))
            .sort("m")
        )
        assert medians["median"][-1] > medians["median"][0] * 1.5, (
            "the fixture must actually shift the mix, or this test proves nothing"
        )

        index, diagnostics = estimate_index(build_pairs(df))
        assert diagnostics["periods_dropped_as_disconnected"] == 0
        levels = index["index"].to_numpy()
        assert np.allclose(levels, levels[0], rtol=1e-6), (
            "no individual property changed price, so the index must be flat"
        )


class TestRecoversAKnownTruth:
    def test_reproduces_a_drift_it_was_never_told_about(self):
        """Prices are generated with a fixed monthly drift; the index has to find it."""
        monthly = 0.01
        rows = panel(
            700,
            months=48,
            price=lambda m, _u, rng: 10_000 * (1 + monthly) ** m * np.exp(rng.normal(0, 0.03)),
            seed=3,
        )
        index, diagnostics = estimate_index(build_pairs(frame(rows)))
        span = len(index) - 1
        implied = (index["index"][-1] / index["index"][0]) ** (1 / span) - 1
        assert implied == pytest.approx(monthly, abs=0.002)
        assert diagnostics["periods_dropped_as_disconnected"] == 0

        # R-squared is deliberately not asserted to be high. It measures how much of the variance
        # in individual pair returns the period dummies explain, and with holding periods of four
        # to twelve months the drift signal per pair is small next to the noise on each sale. A low
        # value there is expected and says nothing against the index; what matters is that the
        # level rises steadily, which is checked directly.
        levels = index["index"].to_numpy()
        rank_correlation = np.corrcoef(np.argsort(np.argsort(levels)), np.arange(len(levels)))[0, 1]
        assert rank_correlation > 0.95

    def test_a_falling_market_gives_a_falling_index(self):
        rows = panel(
            500,
            months=36,
            price=lambda m, _u, rng: 20_000 * (0.99**m) * np.exp(rng.normal(0, 0.02)),
            seed=5,
        )
        index, _ = estimate_index(build_pairs(frame(rows)))
        assert index["index"][-1] < index["index"][0] * 0.85


class TestPairFormation:
    def test_a_property_sold_once_forms_no_pair(self):
        assert build_pairs(frame([sale("a", "x", date(2022, 1, 1), 10_000)])).height == 0

    def test_a_resale_inside_the_minimum_holding_period_is_excluded(self):
        """A flip weeks later is a flip, not evidence about the market."""
        rows = [
            sale("a", "x", date(2022, 1, 1), 10_000),
            sale("a", "x", date(2022, 2, 1), 13_000),
        ]
        assert build_pairs(frame(rows)).height == 0

    def test_a_resale_after_the_minimum_holding_period_is_included(self):
        rows = [
            sale("a", "x", date(2022, 1, 1), 10_000),
            sale("a", "x", date(2022, 7, 1), 12_000),  # 181 days, past the floor
        ]
        pairs = build_pairs(frame(rows))
        assert pairs.height == 1
        assert pairs["hold_days"][0] > MIN_HOLD_DAYS

    def test_three_sales_give_two_consecutive_pairs(self):
        rows = [
            sale("a", "x", date(2020, 1, 1), 10_000),
            sale("a", "x", date(2021, 6, 1), 12_000),
            sale("a", "x", date(2023, 1, 1), 15_000),
        ]
        assert build_pairs(frame(rows)).height == 2

    def test_units_of_different_size_in_one_building_are_different_properties(self):
        """Without a unit identifier, size and bedroom count are what make a unit itself."""
        rows = [
            sale("tower", "x", date(2020, 1, 1), 10_000, sqm=60),
            sale("tower", "x", date(2022, 1, 1), 12_000, sqm=140),
        ]
        assert build_pairs(frame(rows)).height == 0

    def test_an_absurd_price_change_is_treated_as_a_data_error(self):
        rows = [
            sale("a", "x", date(2020, 1, 1), 10_000),
            sale("a", "x", date(2022, 1, 1), 10_000_000),
        ]
        assert build_pairs(frame(rows)).height == 0

    def test_a_sale_with_no_building_cannot_be_identified(self):
        rows = [
            {**sale("a", "x", date(2020, 1, 1), 10_000), "building_name": None},
            {**sale("a", "x", date(2022, 1, 1), 12_000), "building_name": None},
        ]
        assert build_pairs(frame(rows)).height == 0


class TestWeighting:
    def test_a_long_holding_period_carries_less_weight_than_a_short_one(self):
        """Idiosyncratic noise accumulates with time, so a long gap says less per pair."""
        rng = np.random.default_rng(11)
        rows = panel(
            500,
            months=24,
            price=lambda m, _u, r: 10_000 * (1.008**m) * np.exp(r.normal(0, 0.02)),
            seed=11,
        )
        # Twenty very long pairs carrying an implausible fourfold move.
        for unit in range(20):
            month = int(rng.integers(0, 12))
            rows.append(sale(f"long{unit}", "x", month_date(month), 10_000))
            rows.append(sale(f"long{unit}", "x", month_date(month + 84), 40_000))

        index, diagnostics = estimate_index(build_pairs(frame(rows)))
        near = float(index.filter(pl.col("period").dt.year() == 2021)["index"].mean())
        # The short pairs imply roughly 10% a year. Unweighted, the fourfold long pairs would drag
        # the near-term level far above that.
        assert 100 < near < 135, f"near-term level {near:.0f} should follow the short pairs"
        assert diagnostics["n_pairs"] > 400


class TestConnectivity:
    """A repeat-sales index is only identified within a connected set of periods."""

    def test_separate_webs_are_reported_and_the_smaller_one_dropped(self):
        # One large connected web, plus a small isolated pocket that touches nothing else.
        rows = panel(300, months=24, price=lambda m, _u, r: 10_000 * (1.01**m), seed=8)
        for unit in range(10):
            rows.append(sale(f"iso{unit}", "x", month_date(200), 10_000))
            rows.append(sale(f"iso{unit}", "x", month_date(206), 30_000))

        _, diagnostics = estimate_index(build_pairs(frame(rows)))
        assert diagnostics["periods_dropped_as_disconnected"] == 2
        assert diagnostics["pairs_dropped_as_disconnected"] == 10

    def test_a_fully_connected_web_drops_nothing(self):
        rows = panel(300, months=24, price=lambda m, _u, r: 10_000 * (1.01**m), seed=9)
        _, diagnostics = estimate_index(build_pairs(frame(rows)))
        assert diagnostics["periods_dropped_as_disconnected"] == 0
        assert diagnostics["pairs_dropped_as_disconnected"] == 0

    def test_the_component_finder_picks_the_larger_web(self):
        pairs = pl.DataFrame(
            {
                "buy_period": [date(2020, 1, 1), date(2020, 2, 1), date(2021, 6, 1)],
                "sell_period": [date(2020, 2, 1), date(2020, 3, 1), date(2021, 7, 1)],
            }
        )
        assert largest_connected_component(pairs) == {
            date(2020, 1, 1),
            date(2020, 2, 1),
            date(2020, 3, 1),
        }


class TestGuardrails:
    def test_refuses_to_publish_an_index_from_too_few_periods(self):
        rows = [
            sale("a", "x", date(2020, 1, 1), 10_000),
            sale("a", "x", date(2020, 8, 1), 11_000),
        ]
        with pytest.raises(ValueError, match="need"):
            estimate_index(build_pairs(frame(rows)))

    def test_reports_how_many_periods_are_thin(self):
        rows = panel(150, months=24, price=lambda m, _u, r: 10_000 * (1.01**m), seed=2)
        _, diagnostics = estimate_index(build_pairs(frame(rows)))
        assert "thin_periods" in diagnostics
        assert diagnostics["n_pairs"] == 150


class TestAnnualGrowth:
    def test_first_year_has_no_growth_to_report(self):
        frame_ = pl.DataFrame(
            {
                "period": [date(2020, 1, 1), date(2021, 1, 1)],
                "index": [100.0, 110.0],
                "n_pairs": [10, 12],
            }
        )
        rows = annual_growth(frame_)
        assert rows[0]["growth"] is None
        assert rows[1]["growth"] == pytest.approx(0.10)
