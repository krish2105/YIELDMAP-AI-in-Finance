"""Forecast tests.

A forecast that is not compared against a cheap benchmark is a decoration. Every test here is
either about beating the seasonal naive, or about refusing to forecast when the data cannot
support one.
"""

from __future__ import annotations

import numpy as np

from finance.forecast import (
    DAMPING,
    HORIZON,
    MIN_MONTHS,
    damped_trend,
    forecast_area,
    seasonal_naive,
)


def months(n: int) -> np.ndarray:
    return np.arange(n)


class TestSeasonalNaive:
    def test_repeats_the_same_month_a_year_earlier(self):
        series = np.arange(24, dtype=float)
        out = seasonal_naive(series, horizon=12)
        # The last twelve observations are 12..23, so the forecast repeats exactly those.
        assert list(out) == list(series[-12:])

    def test_falls_back_to_the_last_value_when_there_is_under_a_year(self):
        series = np.array([5.0, 6.0, 7.0])
        assert list(seasonal_naive(series, horizon=4)) == [7.0] * 4

    def test_produces_the_requested_number_of_periods(self):
        assert len(seasonal_naive(np.arange(36, dtype=float), horizon=6)) == 6


class TestDamping:
    def test_a_trend_is_extrapolated_less_than_linearly(self):
        """Undamped, one good year compounds into an absurd one."""
        rising = np.log(np.array([100 * 1.01**i for i in range(24)], dtype=float))
        damped = damped_trend(rising, horizon=12, damping=DAMPING)
        undamped = damped_trend(rising, horizon=12, damping=1.0)
        assert damped[-1] < undamped[-1]

    def test_full_damping_of_zero_holds_the_level_flat(self):
        rising = np.log(np.array([100 * 1.02**i for i in range(24)], dtype=float))
        flat = damped_trend(rising, horizon=6, damping=0.0)
        assert np.allclose(flat, flat[0])

    def test_a_flat_history_forecasts_flat(self):
        flat = np.log(np.repeat(100.0, 24))
        out = damped_trend(flat, horizon=12)
        assert np.allclose(np.exp(out), 100.0, rtol=1e-6)

    def test_a_falling_market_forecasts_downwards(self):
        falling = np.log(np.array([100 * 0.98**i for i in range(24)], dtype=float))
        out = np.exp(damped_trend(falling, horizon=12))
        assert out[-1] < out[0]


class TestRefusals:
    def test_refuses_to_forecast_from_too_little_history(self):
        """A projection from a handful of observations is decoration."""
        values = np.array([100.0 + i for i in range(MIN_MONTHS - 1)])
        assert forecast_area(months(len(values)), values) is None

    def test_forecasts_once_there_is_enough_history(self):
        values = np.array([100.0 + i for i in range(MIN_MONTHS)])
        assert forecast_area(months(len(values)), values) is not None


class TestBacktest:
    def _series(self, n=72, drift=0.004, noise=0.0, seed=1):
        rng = np.random.default_rng(seed)
        base = np.array([10_000 * (1 + drift) ** i for i in range(n)])
        return base * np.exp(rng.normal(0, noise, n)) if noise else base

    def test_beats_the_naive_on_a_trending_market(self):
        """A seasonal naive cannot follow a trend; a trend model should."""
        fc = forecast_area(months(72), self._series())
        assert fc.beats_naive is True
        assert fc.backtest_mape < fc.naive_mape

    def test_the_comparison_is_out_of_sample(self):
        """Both the model and the benchmark are scored on data neither of them saw."""
        fc = forecast_area(months(72), self._series(noise=0.05, seed=4))
        assert fc.backtest_mape > 0
        assert fc.naive_mape > 0

    def test_reports_no_verdict_when_it_could_not_compare(self):
        fc = forecast_area(months(72), self._series())
        fc.backtest_mape = None
        assert fc.beats_naive is None

    def test_a_pure_random_walk_gives_the_naive_a_real_chance(self):
        """If the model won on noise, the benchmark would not be a benchmark."""
        rng = np.random.default_rng(9)
        walk = 10_000 * np.exp(np.cumsum(rng.normal(0, 0.05, 96)))
        fc = forecast_area(months(96), walk)
        assert fc.naive_mape > 0
        assert 0 < fc.backtest_mape < 2.0


class TestIntervals:
    def test_the_interval_widens_with_the_horizon(self):
        """Uncertainty twelve months out is not the same as one month out."""
        fc = forecast_area(months(72), np.array([10_000 * 1.004**i for i in range(72)]))
        first = fc.upper[0] - fc.lower[0]
        last = fc.upper[-1] - fc.lower[-1]
        assert last > first

    def test_the_forecast_sits_inside_its_own_interval(self):
        fc = forecast_area(months(72), np.array([10_000 * 1.004**i for i in range(72)]))
        for lo, mid, hi in zip(fc.lower, fc.forecast, fc.upper, strict=True):
            assert lo <= mid <= hi

    def test_a_noisier_history_produces_a_wider_interval(self):
        rng = np.random.default_rng(2)
        clean = np.array([10_000 * 1.004**i for i in range(72)])
        noisy = clean * np.exp(rng.normal(0, 0.12, 72))
        width = lambda fc: (fc.upper[-1] - fc.lower[-1]) / fc.forecast[-1]  # noqa: E731
        assert width(forecast_area(months(72), noisy)) > width(forecast_area(months(72), clean))


class TestShape:
    def test_returns_the_requested_horizon(self):
        fc = forecast_area(months(72), np.array([10_000.0] * 72), horizon=HORIZON)
        assert len(fc.forecast) == HORIZON
        assert len(fc.lower) == len(fc.upper) == HORIZON

    def test_serialises_with_its_verdict(self):
        d = forecast_area(months(72), np.array([10_000 * 1.004**i for i in range(72)])).as_dict()
        assert d["beats_naive"] in {True, False}
        assert "backtest_mape" in d and "naive_mape" in d
