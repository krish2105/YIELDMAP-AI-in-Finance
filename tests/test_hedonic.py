"""Hedonic model tests.

The two that matter most are the leakage test and the additivity test. Leakage is the standard way
a valuation model comes to look excellent and be useless. Additivity is what makes the explanation
trustworthy: an attribution whose parts do not sum to the whole invites arithmetic that does not
hold, which is worse than offering no explanation at all.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from finance.hedonic import FEATURES, _baseline_ppsqm, fit, month_index


def make_market(n: int = 6_000, seed: int = 7) -> pl.DataFrame:
    """A small market with a known structure: area level, room premium and a time trend."""
    rng = np.random.default_rng(seed)
    areas = ["marina", "jvc", "downtown", "barsha"]
    levels = {"marina": 18_000.0, "jvc": 9_000.0, "downtown": 26_000.0, "barsha": 12_000.0}

    months = rng.integers(0, 96, n)
    area = rng.choice(areas, n)
    rooms = rng.integers(0, 4, n)
    sqm = 40 + rooms * 55 + rng.normal(0, 8, n)
    base = np.array([levels[a] for a in area])
    trend = 1 + 0.004 * months
    ppsqm = base * trend * (1 + 0.03 * rooms) * np.exp(rng.normal(0, 0.10, n))

    return pl.DataFrame(
        {
            "ts": [pl.date(2018, 1, 1) for _ in range(0)]
            or pl.date_range(
                pl.date(2018, 1, 1), pl.date(2025, 12, 1), interval="1mo", eager=True
            ).gather(months),
            "area_key": area,
            "property_type": rng.choice(["unit", "villa"], n, p=[0.85, 0.15]),
            "rooms": rooms,
            "area_sqm": sqm,
            "is_offplan": rng.random(n) < 0.3,
            "price_per_sqm": ppsqm,
            "price_aed": ppsqm * sqm,
        }
    ).sort("ts")


@pytest.fixture(scope="module")
def market() -> pl.DataFrame:
    return make_market()


@pytest.fixture(scope="module")
def fitted(market):
    return fit(market, holdout_months=12, seed=7)


class TestNoLeakage:
    def test_the_holdout_is_strictly_later_than_the_training_data(self, market, fitted):
        """A random split lets the model see this year while predicting this year."""
        df = market.with_columns(month_index(market["ts"], market["ts"].min()).alias("mi"))
        cutoff = df["mi"].max() - 12
        assert (
            df.filter(pl.col("mi") <= cutoff)["ts"].max()
            < df.filter(pl.col("mi") > cutoff)["ts"].min()
        )
        assert fitted.metrics["train_period"][1] < fitted.metrics["test_period"][0]

    def test_the_category_vocabulary_comes_only_from_the_training_period(self, market):
        early = market.head(2_000)
        model = fit(early, holdout_months=6, seed=7)
        assert set(model.categories["area_key"]) <= set(early["area_key"].unique().to_list())


class TestAccuracy:
    def test_beats_the_cell_median_baseline(self, market, fitted):
        """The model must earn its complexity against what a spreadsheet would do."""
        assert fitted.metrics["skill_vs_baseline"] > 0.10

    def test_holdout_error_is_close_to_the_data_s_own_noise_floor(self, fitted):
        """A MAPE far above the floor means the model is missing structure that is there."""
        m = fitted.metrics
        assert m["test"]["mape"] < m["estimated_noise_floor_mape"] * 1.6

    def test_is_not_systematically_biased(self, fitted):
        """Back-transforming from log space biases low unless the smearing factor is applied."""
        assert abs(fitted.metrics["test"]["bias"]) < 0.08
        assert fitted.smearing > 1.0

    def test_relies_on_location_most(self, fitted):
        top = [f["feature"] for f in fitted.metrics["importance"][:2]]
        assert "area_key" in top


class TestContributions:
    def test_parts_sum_to_the_whole(self, market, fitted):
        """Rescaled so the attribution is exactly the gap from baseline, not approximately."""
        for row in (market.head(1), market.tail(1), market.slice(500, 1)):
            contrib = fitted.contributions(row)
            predicted_log = float(fitted.model.predict(fitted.encode(row))[0])
            assert sum(contrib.values()) == pytest.approx(
                predicted_log - fitted.baseline_log, abs=1e-9
            )

    def test_names_every_feature(self, market, fitted):
        assert set(fitted.contributions(market.head(1))) == set(FEATURES)

    def test_a_cheap_area_contributes_negatively_against_a_dear_one(self, market, fitted):
        cheap = market.filter(pl.col("area_key") == "jvc").head(1)
        dear = market.filter(pl.col("area_key") == "downtown").head(1)
        assert fitted.contributions(cheap)["area_key"] < fitted.contributions(dear)["area_key"]


class TestUnseenValues:
    def test_an_unseen_area_is_missing_rather_than_silently_recoded(self, market, fitted):
        """Mapping an unknown category to an arbitrary integer would give it a meaning it lacks."""
        row = market.head(1).with_columns(pl.lit("a brand new community").alias("area_key"))
        encoded = fitted.encode(row)
        assert np.isnan(encoded[0, FEATURES.index("area_key")])

    def test_still_produces_a_prediction_for_an_unseen_area(self, market, fitted):
        row = market.head(1).with_columns(pl.lit("a brand new community").alias("area_key"))
        assert np.isfinite(fitted.predict_ppsqm(row)[0])


class TestBaseline:
    def test_falls_back_through_area_then_the_whole_market(self, market):
        train = market.head(4_000)
        test = market.head(1).with_columns(
            pl.lit("unseen").alias("area_key"), pl.lit(99).alias("rooms")
        )
        value = _baseline_ppsqm(train, test)
        assert np.isfinite(value[0])
        assert value[0] == pytest.approx(float(train["price_per_sqm"].median()))


class TestReproducibility:
    def test_the_same_seed_gives_the_same_model(self, market):
        a = fit(market, holdout_months=12, seed=11)
        b = fit(market, holdout_months=12, seed=11)
        assert a.metrics["test"]["mape"] == b.metrics["test"]["mape"]


class TestGuardrails:
    def test_refuses_to_fit_on_too_little_history_rather_than_producing_nonsense(self, market):
        with pytest.raises(ValueError, match="not enough history"):
            fit(market.head(50), holdout_months=12)
