"""Risk and anomaly tests.

Two properties matter most. The score has to stay inside its bounds and move the right way when a
component moves, or the number means nothing. And a deliberately planted outlier has to be found,
because a detector that never fires is indistinguishable from one that works.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from finance.risk import (
    RAPID_RESALE_DAYS,
    detect_anomalies,
    flag_rapid_resales,
    flag_round_numbers,
    load_weights,
    scale_component,
    score_areas,
)


@pytest.fixture(scope="module")
def weights():
    return load_weights()


def market(
    n=400, area="marina", offplan=0.3, volatility=0.0, price=10_000.0, seed=1, projects=8
) -> pl.DataFrame:
    """A synthetic area with dials for each risk component."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        year = 2019 + i % 6
        # Volatility is injected as a per-year shock shared by that year's sales.
        shock = 1 + volatility * ((year - 2019) % 3 - 1)
        sqm = float(rng.uniform(50, 150))
        ppsqm = price * shock * float(np.exp(rng.normal(0, 0.05)))
        rows.append(
            {
                "transaction_id": f"t{i}",
                "ts": date(year, (i % 12) + 1, (i % 27) + 1),
                "area_key": area,
                "building_name": f"tower{i % 40}",
                "project_name": f"project{i % projects}",
                "property_type": "unit",
                "rooms": i % 4,
                "area_sqm": sqm,
                "price_aed": ppsqm * sqm,
                "price_per_sqm": ppsqm,
                "is_offplan": i < n * offplan,
            }
        )
    return pl.DataFrame(rows).sort("ts")


class TestScaling:
    def test_maps_the_low_end_to_zero_and_the_high_end_to_a_hundred(self):
        spec = {"scale": {"low": 0.1, "high": 0.7}}
        assert scale_component(0.1, spec) == 0.0
        assert scale_component(0.7, spec) == 100.0

    def test_clips_rather_than_extrapolating_beyond_the_band(self):
        """Letting one component run to 300 would let it dominate a bounded sum."""
        spec = {"scale": {"low": 0.1, "high": 0.7}}
        assert scale_component(-5.0, spec) == 0.0
        assert scale_component(50.0, spec) == 100.0

    def test_an_inverted_component_scores_high_when_the_raw_value_is_low(self):
        """Few transactions means hard to exit, which is more risk, not less."""
        spec = {"scale": {"low": 10, "high": 400}, "inverted": True}
        assert scale_component(10, spec) == 100.0
        assert scale_component(400, spec) == 0.0

    def test_a_missing_component_stays_missing(self):
        assert scale_component(None, {"scale": {"low": 0, "high": 1}}) is None


class TestScoreBounds:
    def test_the_score_stays_within_zero_and_a_hundred(self, weights):
        for offplan in (0.0, 0.5, 1.0):
            for vol in (0.0, 0.2, 0.9):
                df = detect_anomalies(market(offplan=offplan, volatility=vol))
                for r in score_areas(df, weights):
                    if r.score is not None:
                        assert 0.0 <= r.score <= 100.0

    def test_every_component_is_reported_alongside_the_total(self, weights):
        """A risk number that cannot be taken apart is one nobody should act on."""
        r = score_areas(detect_anomalies(market()), weights)[0]
        assert set(r.components) == set(weights["components"])
        assert r.score is not None


class TestMonotonicity:
    def _score(self, weights, **kwargs) -> float:
        df = detect_anomalies(market(**kwargs))
        return score_areas(df, weights)[0].score

    def test_more_volatile_prices_score_riskier(self, weights):
        assert self._score(weights, volatility=0.30) > self._score(weights, volatility=0.0)

    def test_more_off_plan_exposure_scores_riskier(self, weights):
        assert self._score(weights, offplan=0.9) > self._score(weights, offplan=0.0)

    def test_a_single_developer_scores_riskier_than_many(self, weights):
        assert self._score(weights, projects=1) > self._score(weights, projects=40)

    def test_a_thinner_market_scores_riskier(self, weights):
        assert self._score(weights, n=60) > self._score(weights, n=400)


class TestRefusal:
    def test_an_area_below_the_floor_gets_no_score_and_says_why(self, weights):
        """A risk score from twelve sales is a guess wearing a number's clothes."""
        df = detect_anomalies(market(n=12))
        r = score_areas(df, weights)[0]
        assert r.score is None
        assert "transactions" in r.reason

    def test_the_refusal_still_reports_the_sample_size(self, weights):
        r = score_areas(detect_anomalies(market(n=12)), weights)[0]
        assert r.n == 12


class TestAnomalyDetection:
    def test_a_planted_outlier_is_flagged(self):
        """A detector that never fires is indistinguishable from one that works."""
        df = market(n=500)
        poisoned = df.with_columns(
            pl.when(pl.col("transaction_id") == "t250")
            .then(pl.col("price_per_sqm") * 12)
            .otherwise(pl.col("price_per_sqm"))
            .alias("price_per_sqm")
        ).with_columns((pl.col("price_per_sqm") * pl.col("area_sqm")).alias("price_aed"))

        flagged = detect_anomalies(poisoned, contamination=0.02)
        row = flagged.filter(pl.col("transaction_id") == "t250")
        assert row["is_price_outlier"][0] is True
        assert "price out of line" in row["reasons"][0]

    def test_an_ordinary_market_is_not_mostly_flagged(self):
        flagged = detect_anomalies(market(n=500), contamination=0.01)
        assert flagged["is_anomaly"].mean() < 0.10

    def test_a_flag_always_names_the_rule_that_fired(self):
        flagged = detect_anomalies(market(n=300))
        for r in flagged.filter(pl.col("is_anomaly")).iter_rows(named=True):
            assert r["reasons"], "an unusual flag without a reason is not actionable"
            assert "; ;" not in r["reasons"]
            assert not r["reasons"].endswith("; ")


class TestRapidResales:
    def _pair(self, gap_days: int) -> pl.DataFrame:
        first = date(2023, 1, 10)
        rows = [
            {
                "transaction_id": f"r{i}",
                "ts": first if i == 0 else first + timedelta(days=gap_days),
                "area_key": "marina",
                "building_name": "tower1",
                "rooms": 2,
                "area_sqm": 100.0,
                "price_aed": 1_000_000.0 * (1 + 0.2 * i),
                "price_per_sqm": 10_000.0 * (1 + 0.2 * i),
            }
            for i in range(2)
        ]
        return pl.DataFrame(rows)

    def test_a_resale_inside_the_window_is_flagged(self):
        assert flag_rapid_resales(self._pair(30)).any()

    def test_a_resale_outside_the_window_is_not(self):
        assert not flag_rapid_resales(self._pair(RAPID_RESALE_DAYS + 60)).any()

    def test_only_the_second_sale_is_flagged_not_the_first(self):
        flags = flag_rapid_resales(self._pair(30)).to_list()
        assert flags.count(True) == 1

    def test_different_properties_in_one_building_are_not_a_resale(self):
        df = self._pair(30).with_columns(pl.Series("area_sqm", [100.0, 180.0]))
        assert not flag_rapid_resales(df).any()


class TestRoundNumbers:
    def test_an_exactly_round_price_is_flagged(self):
        df = pl.DataFrame({"price_aed": [1_000_000.0, 2_500_000.0]})
        assert flag_round_numbers(df).to_list() == [True, True]

    def test_an_ordinary_price_is_not(self):
        df = pl.DataFrame({"price_aed": [1_234_567.0, 987_654.0]})
        assert flag_round_numbers(df).to_list() == [False, False]

    def test_a_small_round_price_is_ignored(self):
        """Landing on a round figure is only surprising when the number is large."""
        df = pl.DataFrame({"price_aed": [100_000.0]})
        assert flag_round_numbers(df).to_list() == [False]


class TestWeightsFile:
    def test_every_component_declares_a_weight_a_label_and_a_rationale(self, weights):
        for key, spec in weights["components"].items():
            assert 0 < spec["weight"] <= 1, key
            assert spec.get("label"), key
            assert spec.get("rationale"), key
            assert {"low", "high"} <= set(spec["scale"]), key

    def test_the_weights_sum_to_one(self, weights):
        total = sum(spec["weight"] for spec in weights["components"].values())
        assert total == pytest.approx(1.0)
