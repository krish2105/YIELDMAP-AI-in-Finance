"""Hedonic valuation: what a property's characteristics say it is worth.

A gradient-boosted regressor on the characteristics the registry actually records — area, type,
bedrooms, floor area, off-plan status and time. It answers "is this priced above or below what
comparable registered sales say", which is the question a buyer has and a portal listing cannot
answer.

Two decisions worth stating.

The target is log price per square metre, not price. Property prices are right-skewed across three
orders of magnitude, so squared error on the raw price would let a handful of penthouses dominate
the fit; and per square metre is the quantity that is comparable across unit sizes. Predictions are
exponentiated back, with the smearing correction that log-space fitting requires.

The holdout is the most recent year, not a random split. A random split lets the model see 2025
sales while predicting other 2025 sales, which flatters it enormously and answers a question nobody
asks. Splitting by time asks the real question: given everything up to last year, how wrong is it
about this year.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

from finance.base import DEFAULT_DB, Warehouse, write_result

FEATURES = ["area_key", "property_type", "rooms", "area_sqm", "is_offplan", "month_index"]
CATEGORICAL = ["area_key", "property_type"]

TRAINING_SQL = """
select
    ts,
    area_key,
    property_type,
    rooms,
    area_sqm,
    is_offplan,
    price_aed,
    price_per_sqm
from transactions
where price_per_sqm is not null
  and area_sqm is not null
  and price_aed is not null
order by ts
"""


@dataclass
class HedonicModel:
    """A fitted hedonic model plus everything needed to explain and audit it."""

    model: HistGradientBoostingRegressor
    categories: dict[str, list[str]]
    baseline_log: float
    smearing: float
    first_month: Any
    metrics: dict[str, Any] = field(default_factory=dict)

    def encode(self, df: pl.DataFrame) -> np.ndarray:
        """Ordinal-encode categories against the fitted vocabulary; unseen values become NaN.

        NaN rather than a new integer: the tree handles missing natively, whereas an unseen
        category silently mapped to an arbitrary code would be given a meaning it does not have.

        Time is derived here from ``ts`` when the caller has not already supplied it, so nothing
        outside this class needs to know how the model encodes time. The API layer passes a plain
        description of a property and gets a valuation.
        """
        if "month_index" not in df.columns:
            df = df.with_columns(month_index(df["ts"], self.first_month).alias("month_index"))
        cols = []
        for name in FEATURES:
            if name in CATEGORICAL:
                lookup = {v: float(i) for i, v in enumerate(self.categories[name])}
                cols.append(
                    df[name]
                    .replace_strict(lookup, default=None, return_dtype=pl.Float64)
                    .to_numpy()
                )
            elif name == "is_offplan":
                cols.append(df[name].cast(pl.Float64, strict=False).to_numpy())
            else:
                cols.append(df[name].cast(pl.Float64, strict=False).to_numpy())
        return np.column_stack(cols)

    def predict_ppsqm(self, df: pl.DataFrame) -> np.ndarray:
        """Predicted price per square metre, back-transformed from log space."""
        log_pred = self.model.predict(self.encode(df))
        return np.exp(log_pred) * self.smearing

    def contributions(self, row: pl.DataFrame) -> dict[str, float]:
        """Per-feature contribution to one prediction, in log space.

        Each feature is replaced by the training median (or the most common category) and the
        change in prediction is attributed to it. The parts are then rescaled so they sum exactly
        to prediction minus baseline — an explanation whose parts do not add up to the whole is
        worse than none, because it invites arithmetic that does not hold.
        """
        encoded = self.encode(row)
        full = float(self.model.predict(encoded)[0])
        gap = full - self.baseline_log

        raw: dict[str, float] = {}
        for i, name in enumerate(FEATURES):
            ablated = encoded.copy()
            ablated[0, i] = self.baseline_row[i]
            raw[name] = full - float(self.model.predict(ablated)[0])

        total = sum(raw.values())
        if abs(total) < 1e-12:
            return dict.fromkeys(FEATURES, 0.0)
        scale = gap / total
        return {k: v * scale for k, v in raw.items()}

    baseline_row: np.ndarray = field(default=None, repr=False)  # type: ignore[assignment]


def month_index(ts: pl.Series, first: Any) -> pl.Series:
    """Months since the first observation, which is how the model sees time."""
    return (ts.dt.year() - first.year) * 12 + (ts.dt.month() - first.month)


def fit(df: pl.DataFrame, *, holdout_months: int = 12, seed: int = 217) -> HedonicModel:
    """Fit on everything before the holdout window and measure on the window."""
    first = df["ts"].min()
    df = df.with_columns(month_index(df["ts"], first).alias("month_index"))

    cutoff = df["month_index"].max() - holdout_months
    train = df.filter(pl.col("month_index") <= cutoff)
    test = df.filter(pl.col("month_index") > cutoff)
    if train.height < 100:
        raise ValueError(f"not enough history to fit: {train.height} training rows")

    categories = {name: sorted(train[name].drop_nulls().unique().to_list()) for name in CATEGORICAL}

    model = HistGradientBoostingRegressor(
        loss="squared_error",
        max_iter=400,
        learning_rate=0.06,
        max_depth=None,
        min_samples_leaf=40,
        l2_regularization=1.0,
        categorical_features=[FEATURES.index(c) for c in CATEGORICAL],
        random_state=seed,
    )

    fitted = HedonicModel(
        model=model, categories=categories, baseline_log=0.0, smearing=1.0, first_month=first
    )
    x_train = fitted.encode(train)
    y_train = np.log(train["price_per_sqm"].to_numpy())
    model.fit(x_train, y_train)

    # Duan's smearing estimate: exp() of a mean log is a median, not a mean, so a back-transformed
    # prediction is biased low without this correction.
    residuals = y_train - model.predict(x_train)
    fitted.smearing = float(np.mean(np.exp(residuals)))
    fitted.baseline_log = float(np.mean(y_train))
    fitted.baseline_row = np.array(
        [
            float(np.nanmedian(x_train[:, i]))
            if name not in CATEGORICAL
            else float(np.nanmedian(x_train[:, i]))
            for i, name in enumerate(FEATURES)
        ]
    )

    fitted.metrics = _evaluate(fitted, train, test)
    fitted.metrics["importance"] = _importance(fitted, test, seed)
    return fitted


def _baseline_ppsqm(train: pl.DataFrame, test: pl.DataFrame) -> np.ndarray:
    """The honest thing to beat: the median price per square metre for the same cell.

    Area, type and bedroom count, falling back to area then to the whole market when a cell is
    unseen. This is what a careful person with a spreadsheet would do, so any claim the model makes
    has to be measured against it rather than against zero.
    """
    keys = ["area_key", "property_type", "rooms"]
    cell = train.group_by(keys).agg(pl.col("price_per_sqm").median().alias("cell"))
    area = train.group_by("area_key").agg(pl.col("price_per_sqm").median().alias("area"))
    overall = float(train["price_per_sqm"].median())

    joined = test.join(cell, on=keys, how="left").join(area, on="area_key", how="left")
    return joined["cell"].fill_null(joined["area"]).fill_null(overall).to_numpy()


def _noise_floor(actual: np.ndarray, pred: np.ndarray) -> float:
    """Rough irreducible error, from the dispersion of log residuals.

    For multiplicative noise, mean absolute percentage error cannot fall below roughly
    sqrt(2/pi) times the residual log standard deviation. Reporting it stops a MAPE being read as
    model failure when it is actually the data's own scatter.
    """
    resid = np.log(actual) - np.log(pred)
    return float(np.std(resid) * np.sqrt(2 / np.pi))


def _evaluate(fitted: HedonicModel, train: pl.DataFrame, test: pl.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {
        "n_train": train.height,
        "n_test": test.height,
        "train_period": [str(train["ts"].min()), str(train["ts"].max())],
        "test_period": [str(test["ts"].min()), str(test["ts"].max())] if test.height else None,
    }
    for label, frame in (("train", train), ("test", test)):
        if frame.height == 0:
            continue
        actual = frame["price_per_sqm"].to_numpy()
        pred = fitted.predict_ppsqm(frame)
        err = pred - actual
        out[label] = {
            "mae_ppsqm": float(np.mean(np.abs(err))),
            "mape": float(np.mean(np.abs(err / actual))),
            "median_ape": float(np.median(np.abs(err / actual))),
            "rmse_ppsqm": float(np.sqrt(np.mean(err**2))),
            "bias": float(np.mean(err / actual)),
        }

    if test.height:
        actual = test["price_per_sqm"].to_numpy()
        model_pred = fitted.predict_ppsqm(test)
        base_pred = _baseline_ppsqm(train, test)
        base_mape = float(np.mean(np.abs(base_pred - actual) / actual))
        model_mape = out["test"]["mape"]
        out["baseline"] = {
            "method": "median price per sqm for the same area, type and bedroom count",
            "mape": base_mape,
            "mae_ppsqm": float(np.mean(np.abs(base_pred - actual))),
        }
        out["skill_vs_baseline"] = (
            float((base_mape - model_mape) / base_mape) if base_mape else None
        )
        out["estimated_noise_floor_mape"] = _noise_floor(actual, model_pred)
    return out


def _importance(fitted: HedonicModel, test: pl.DataFrame, seed: int) -> list[dict[str, Any]]:
    """Permutation importance on the holdout: which features the model actually relies on."""
    if test.height < 50:
        return []
    sample = test.head(5_000)
    result = permutation_importance(
        fitted.model,
        fitted.encode(sample),
        np.log(sample["price_per_sqm"].to_numpy()),
        n_repeats=5,
        random_state=seed,
        scoring="neg_mean_absolute_error",
    )
    return sorted(
        (
            {"feature": name, "importance": float(m), "std": float(s)}
            for name, m, s in zip(
                FEATURES, result.importances_mean, result.importances_std, strict=True
            )
        ),
        key=lambda d: d["importance"],
        reverse=True,
    )


def run(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    with Warehouse(db_path) as wh:
        q = wh.query(TRAINING_SQL)
        provenance = wh.provenance()

    fitted = fit(q.frame)
    payload = {
        "method_id": "hedonic_v1",
        "target": "log price per square metre, back-transformed with Duan smearing",
        "holdout": "most recent 12 months, split by time rather than at random",
        "features": FEATURES,
        "smearing_factor": fitted.smearing,
        "sql": q.sql,
        "metrics": fitted.metrics,
    }
    path = write_result("hedonic.json", payload, provenance)
    return {"payload": payload, "path": path, "provenance": provenance}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    out = run(args.db)
    m = out["payload"]["metrics"]
    print(f"trained on {m['n_train']:,} rows ({m['train_period'][0]} to {m['train_period'][1]})")
    print(f"tested on  {m['n_test']:,} rows ({m['test_period'][0]} to {m['test_period'][1]})")
    print(f"  holdout MAPE       {m['test']['mape']:.1%}")
    print(f"  holdout median APE {m['test']['median_ape']:.1%}")
    print(f"  holdout MAE        {m['test']['mae_ppsqm']:,.0f} AED/sqm")
    print(f"  baseline MAPE      {m['baseline']['mape']:.1%}")
    print(f"  skill vs baseline  {m['skill_vs_baseline']:+.1%}")
    print(f"  est. noise floor   {m['estimated_noise_floor_mape']:.1%} MAPE")
    print(f"  top features       {', '.join(f['feature'] for f in m['importance'][:3])}")
    print(f"wrote {out['path']} ({out['provenance']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
