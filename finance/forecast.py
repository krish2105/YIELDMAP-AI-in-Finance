"""Twelve-month price forecast per area, measured against a naive benchmark.

The benchmark is the point. Any model can produce a line that continues off the end of a chart;
the question is whether it beats the cheapest sensible alternative. Here that alternative is the
seasonal naive forecast — next January will look like last January — which on monthly property
data is a genuinely hard baseline, because most of the visible movement in a thin area is noise
that no model should be pretending to predict.

The method is deliberately simple: a damped local trend fitted to each area's log median price per
square metre, with an explicit seasonal term where there is enough history. Damping matters. An
undamped trend extrapolated twelve months forward turns a good year into an absurd one, and
property markets mean-revert rather than compounding indefinitely.

Areas without enough history do not get a forecast. They get an honest refusal, because a
projection from four observations is decoration.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from finance.base import DEFAULT_DB, Warehouse, write_result

SERIES_SQL = """
select
    area_key,
    date_trunc('month', ts)                as month,
    median(price_per_sqm)                  as ppsqm,
    count(*)                               as n
from transactions
where price_per_sqm is not null
group by 1, 2
having count(*) >= 3
order by 1, 2
"""

MIN_MONTHS = 36
HORIZON = 12
# A trend that keeps its full strength for a year turns one good year into an absurd one.
DAMPING = 0.85


@dataclass
class AreaForecast:
    area_key: str
    n_months: int
    fitted_level: float
    trend: float
    forecast: list[float]
    lower: list[float]
    upper: list[float]
    backtest_mape: float | None
    naive_mape: float | None

    @property
    def beats_naive(self) -> bool | None:
        if self.backtest_mape is None or self.naive_mape is None:
            return None
        return self.backtest_mape < self.naive_mape

    def as_dict(self) -> dict[str, Any]:
        return {
            "area_key": self.area_key,
            "n_months": self.n_months,
            "trend_per_month": round(self.trend, 6),
            "forecast": [round(v, 2) for v in self.forecast],
            "lower": [round(v, 2) for v in self.lower],
            "upper": [round(v, 2) for v in self.upper],
            "backtest_mape": self.backtest_mape,
            "naive_mape": self.naive_mape,
            "beats_naive": self.beats_naive,
        }


def seasonal_naive(series: np.ndarray, horizon: int, period: int = 12) -> np.ndarray:
    """Next January looks like last January. Falls back to the last value when history is short."""
    if len(series) >= period:
        return np.array([series[-period + (h % period)] for h in range(horizon)])
    return np.repeat(series[-1], horizon)


def damped_trend(
    log_series: np.ndarray, horizon: int, *, damping: float = DAMPING, window: int = 12
) -> np.ndarray:
    """Level plus a damped linear trend, fitted on the recent window.

    The trend is estimated on the last year rather than the whole history, because an area's
    direction of travel now matters more than its direction five years ago, and then damped
    geometrically so its influence decays across the horizon instead of compounding.
    """
    n = len(log_series)
    window = min(window, n)
    recent = log_series[-window:]
    x = np.arange(window)
    if window >= 2:
        slope, intercept = np.polyfit(x, recent, 1)
        level = intercept + slope * (window - 1)
    else:
        slope, level = 0.0, float(recent[-1])

    # Damped extrapolation: sum of phi, phi^2, ... rather than h * slope.
    cumulative = np.cumsum([damping**h for h in range(1, horizon + 1)])
    return level + slope * cumulative


def forecast_area(
    months: np.ndarray, values: np.ndarray, *, horizon: int = HORIZON
) -> AreaForecast | None:
    """Forecast one area, and honestly backtest it against the naive alternative."""
    if len(values) < MIN_MONTHS:
        return None

    log_values = np.log(values)

    # Backtest on a held-out final year, which is the only honest way to compare with the naive.
    holdout = min(horizon, max(6, len(values) // 5))
    train_log, test = log_values[:-holdout], values[-holdout:]

    model_pred = np.exp(damped_trend(train_log, holdout))
    naive_pred = seasonal_naive(np.exp(train_log), holdout)

    model_mape = float(np.mean(np.abs(model_pred - test) / test))
    naive_mape = float(np.mean(np.abs(naive_pred - test) / test))

    # Final fit uses everything, and the interval comes from the backtest error rather than from
    # the model's own optimism about itself.
    forward_log = damped_trend(log_values, horizon)
    forward = np.exp(forward_log)
    spread = max(model_mape, 0.02)
    widening = np.sqrt(np.arange(1, horizon + 1) / horizon)

    slope = float(
        np.polyfit(np.arange(min(12, len(log_values))), log_values[-min(12, len(log_values)) :], 1)[
            0
        ]
    )

    return AreaForecast(
        area_key="",
        n_months=len(values),
        fitted_level=float(np.exp(forward_log[0])),
        trend=slope,
        forecast=list(forward),
        lower=list(forward * (1 - spread * widening)),
        upper=list(forward * (1 + spread * widening)),
        backtest_mape=model_mape,
        naive_mape=naive_mape,
    )


def run(db_path: Path = DEFAULT_DB, *, horizon: int = HORIZON) -> dict[str, Any]:
    with Warehouse(db_path) as wh:
        q = wh.query(SERIES_SQL)
        provenance = wh.provenance()

    results: list[AreaForecast] = []
    skipped: list[dict[str, Any]] = []

    for (area,), group in q.frame.group_by("area_key", maintain_order=True):
        group = group.sort("month")
        values = group["ppsqm"].to_numpy()
        fc = forecast_area(group["month"].to_numpy(), values, horizon=horizon)
        if fc is None:
            skipped.append(
                {"area_key": area, "n_months": len(values), "reason": "too little history"}
            )
            continue
        fc.area_key = area
        results.append(fc)

    compared = [f for f in results if f.beats_naive is not None]
    wins = sum(1 for f in compared if f.beats_naive)
    win_rate = wins / len(compared) if compared else None

    payload = {
        "method_id": "forecast_v1",
        "method": "damped local trend on log median price per square metre",
        "benchmark": "seasonal naive: next January looks like last January",
        "horizon_months": horizon,
        "damping": DAMPING,
        "min_months_required": MIN_MONTHS,
        "sql": q.sql,
        "summary": {
            "areas_forecast": len(results),
            "areas_skipped": len(skipped),
            "areas_compared": len(compared),
            "areas_beating_naive": wins,
            "win_rate": win_rate,
            "median_model_mape": float(np.median([f.backtest_mape for f in compared]))
            if compared
            else None,
            "median_naive_mape": float(np.median([f.naive_mape for f in compared]))
            if compared
            else None,
        },
        "skipped": skipped[:50],
        "areas": [f.as_dict() for f in sorted(results, key=lambda f: f.area_key)],
    }
    path = write_result("forecast.json", payload, provenance)
    return {"payload": payload, "path": path, "provenance": provenance}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--horizon", type=int, default=HORIZON)
    args = parser.parse_args(argv)

    out = run(args.db, horizon=args.horizon)
    s = out["payload"]["summary"]
    print(f"{s['areas_forecast']} areas forecast, {s['areas_skipped']} skipped for thin history")
    if s["win_rate"] is not None:
        print(
            f"  beats seasonal naive on {s['areas_beating_naive']}/{s['areas_compared']} areas "
            f"({s['win_rate']:.1%})"
        )
        print(
            f"  median backtest MAPE   model {s['median_model_mape']:.1%}  "
            f"naive {s['median_naive_mape']:.1%}"
        )
    print(f"wrote {out['path']} ({out['provenance']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
