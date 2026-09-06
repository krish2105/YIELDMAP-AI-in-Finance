"""Area risk score, and the anomalies that feed it.

Two things live here because they are two views of the same question: what makes the other numbers
on this page less trustworthy.

The risk score is a weighted blend of five components, each scaled to 0-100. It is a judgement,
not a measurement, so the weights sit in config/risk_weights.yaml where they can be argued with,
and the component breakdown is always published alongside the total. A single risk number that
cannot be taken apart is a number nobody should act on.

The anomaly detector combines three signals, deliberately rather than relying on one. An isolation
forest on hedonic residuals catches prices that do not fit their characteristics. A rapid-resale
rule catches flips. A round-number rule catches the suspiciously tidy figures that often mark a
transfer at an agreed rather than a market price. Each flag names which rule fired, because
"unusual" without a reason is not actionable.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml
from sklearn.ensemble import IsolationForest

from finance.base import DEFAULT_DB, Warehouse, write_result

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS_PATH = ROOT / "config" / "risk_weights.yaml"

RAPID_RESALE_DAYS = 90
# Prices that land exactly on a round figure are more often negotiated than market-set.
ROUND_NUMBER_UNITS = (1_000_000, 500_000, 250_000, 100_000)

TRANSACTIONS_SQL = """
select
    transaction_id,
    ts,
    area_key,
    building_name,
    project_name,
    property_type,
    rooms,
    area_sqm,
    price_aed,
    price_per_sqm,
    is_offplan
from transactions
where price_per_sqm is not null and area_sqm is not null
order by ts
"""


def load_weights(path: Path = WEIGHTS_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def scale_component(value: float | None, spec: dict[str, Any]) -> float | None:
    """Map a raw component onto 0-100, clipped at both ends.

    Clipping rather than extrapolating: an area with twice the volatility of the worst band is
    still just "as risky as it gets" on this axis, and letting one component run to 300 would let
    it silently dominate a weighted sum that is supposed to be bounded.
    """
    if value is None:
        return None
    low, high = float(spec["scale"]["low"]), float(spec["scale"]["high"])
    if high == low:
        return 0.0
    position = (value - low) / (high - low)
    if spec.get("inverted"):
        position = 1.0 - position
    return float(np.clip(position, 0.0, 1.0) * 100.0)


# ------------------------------------------------------------------ anomalies


def flag_round_numbers(df: pl.DataFrame) -> pl.Series:
    """True where a price is exactly a round figure."""
    price = df["price_aed"]
    flags = np.zeros(df.height, dtype=bool)
    for unit in ROUND_NUMBER_UNITS:
        flags |= (price % unit == 0).to_numpy()
    # Anything divisible by a million is also divisible by the smaller units, so require the price
    # to be large enough that landing on the unit is genuinely unlikely.
    return pl.Series(flags & (price >= 250_000).to_numpy())


def flag_rapid_resales(df: pl.DataFrame, *, within_days: int = RAPID_RESALE_DAYS) -> pl.Series:
    """True where the same property changed hands again within the window."""
    keyed = df.with_columns(
        pl.concat_str(
            [
                pl.col("area_key"),
                pl.col("building_name").fill_null("?"),
                pl.col("rooms").cast(pl.String).fill_null("?"),
                pl.col("area_sqm").round(0).cast(pl.String),
            ],
            separator="|",
        ).alias("_unit")
    ).with_row_index("_row")

    ordered = keyed.sort(["_unit", "ts"])
    gaps = ordered.with_columns(
        (pl.col("ts") - pl.col("ts").shift(1).over("_unit")).dt.total_days().alias("_gap")
    )
    flagged_rows = set(
        gaps.filter(pl.col("_gap").is_not_null() & (pl.col("_gap") <= within_days))[
            "_row"
        ].to_list()
    )
    return pl.Series([i in flagged_rows for i in range(df.height)])


def flag_price_outliers(
    df: pl.DataFrame, *, contamination: float = 0.01, seed: int = 217
) -> tuple[pl.Series, np.ndarray]:
    """Isolation forest on price residuals against the area-and-type norm.

    The forest is run on residuals rather than raw prices, because raw price is dominated by area
    and size: without residualising, every large villa in an expensive area looks anomalous and
    every studio looks normal, which is the opposite of useful.
    """
    if df.height < 50:
        return pl.Series([False] * df.height), np.zeros(df.height)

    norms = df.group_by(["area_key", "property_type"]).agg(
        pl.col("price_per_sqm").median().alias("_norm")
    )
    joined = df.join(norms, on=["area_key", "property_type"], how="left")
    residual = np.log(joined["price_per_sqm"].to_numpy()) - np.log(
        joined["_norm"].fill_null(joined["price_per_sqm"].median()).to_numpy()
    )
    size = np.log(joined["area_sqm"].to_numpy())

    features = np.column_stack([residual, size])
    forest = IsolationForest(contamination=contamination, random_state=seed, n_estimators=200)
    labels = forest.fit_predict(features)
    scores = -forest.score_samples(features)
    return pl.Series(labels == -1), scores


def detect_anomalies(df: pl.DataFrame, *, contamination: float = 0.01) -> pl.DataFrame:
    """Combine the three signals, naming which fired for each flagged transaction."""
    outlier, scores = flag_price_outliers(df, contamination=contamination)
    rapid = flag_rapid_resales(df)
    round_number = flag_round_numbers(df)

    out = df.with_columns(
        outlier.alias("is_price_outlier"),
        rapid.alias("is_rapid_resale"),
        round_number.alias("is_round_number"),
        pl.Series(scores).alias("outlier_score"),
    )
    return out.with_columns(
        (pl.col("is_price_outlier") | pl.col("is_rapid_resale") | pl.col("is_round_number")).alias(
            "is_anomaly"
        ),
        # Null rather than an empty string for a rule that did not fire: concat_str skips nulls
        # entirely, whereas empty strings leave stray separators behind.
        pl.concat_str(
            [
                pl.when(pl.col("is_price_outlier"))
                .then(pl.lit("price out of line"))
                .otherwise(None),
                pl.when(pl.col("is_rapid_resale"))
                .then(pl.lit("resold within 90 days"))
                .otherwise(None),
                pl.when(pl.col("is_round_number"))
                .then(pl.lit("exactly round price"))
                .otherwise(None),
            ],
            separator="; ",
            ignore_nulls=True,
        ).alias("reasons"),
    )


# ----------------------------------------------------------------- risk score


@dataclass
class AreaRisk:
    area_key: str
    n: int
    components: dict[str, float | None]
    raw: dict[str, float | None]
    score: float | None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "area_key": self.area_key,
            "n": self.n,
            "score": None if self.score is None else round(self.score, 1),
            "components": {
                k: None if v is None else round(v, 1) for k, v in self.components.items()
            },
            "raw": self.raw,
            "reason": self.reason,
        }


def score_areas(df: pl.DataFrame, weights: dict[str, Any]) -> list[AreaRisk]:
    """Score every area, refusing where the sample cannot support one."""
    specs = weights["components"]
    minimum = int(weights["min_transactions"])
    results: list[AreaRisk] = []

    df = df.with_columns(pl.col("ts").dt.year().alias("_year"))

    for (area,), group in df.group_by("area_key", maintain_order=True):
        n = group.height
        if n < minimum:
            results.append(
                AreaRisk(
                    area_key=area,
                    n=n,
                    components=dict.fromkeys(specs),
                    raw={},
                    score=None,
                    reason=f"only {n} transactions; {minimum} needed for a score",
                )
            )
            continue

        offplan_share = float(group["is_offplan"].fill_null(False).mean())

        shares = (
            group.group_by("project_name").len().with_columns((pl.col("len") / n).alias("share"))
        )
        hhi = float((shares["share"] ** 2).sum())

        yearly = (
            group.group_by("_year")
            .agg(pl.col("price_per_sqm").median().alias("m"))
            .sort("_year")["m"]
            .to_numpy()
        )
        volatility = float(np.std(np.diff(yearly) / yearly[:-1])) if len(yearly) >= 3 else None

        anomaly_rate = float(group["is_anomaly"].mean()) if "is_anomaly" in group.columns else 0.0

        raw = {
            "offplan_share": offplan_share,
            "developer_concentration": hhi,
            "price_volatility": volatility,
            "illiquidity": float(n),
            "anomaly_density": anomaly_rate,
        }
        components = {k: scale_component(raw[k], specs[k]) for k in specs}

        available = {k: v for k, v in components.items() if v is not None}
        total_weight = sum(specs[k]["weight"] for k in available)
        score = (
            sum(specs[k]["weight"] * v for k, v in available.items()) / total_weight
            if total_weight
            else None
        )
        results.append(AreaRisk(area_key=area, n=n, components=components, raw=raw, score=score))

    return results


def run(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    weights = load_weights()
    with Warehouse(db_path) as wh:
        q = wh.query(TRANSACTIONS_SQL)
        provenance = wh.provenance()

    flagged = detect_anomalies(q.frame)
    scored = score_areas(flagged, weights)
    published = [r for r in scored if r.score is not None]

    anomalies = flagged.filter(pl.col("is_anomaly"))
    payload = {
        "method_id": "risk_v1",
        "weights": weights,
        "sql": q.sql,
        "anomalies": {
            "total_transactions": flagged.height,
            "flagged": anomalies.height,
            "rate": anomalies.height / flagged.height if flagged.height else 0.0,
            "by_rule": {
                "price out of line": int(flagged["is_price_outlier"].sum()),
                "resold within 90 days": int(flagged["is_rapid_resale"].sum()),
                "exactly round price": int(flagged["is_round_number"].sum()),
            },
            "examples": anomalies.sort("outlier_score", descending=True)
            .head(20)
            .select(["ts", "area_key", "price_aed", "price_per_sqm", "reasons"])
            .to_dicts(),
        },
        "summary": {
            "areas": len(scored),
            "areas_scored": len(published),
            "areas_unscored": len(scored) - len(published),
            "median_score": float(np.median([r.score for r in published])) if published else None,
        },
        "areas": [
            r.as_dict() for r in sorted(scored, key=lambda r: (r.score is None, -(r.score or 0)))
        ],
    }
    path = write_result("risk.json", payload, provenance)
    return {"payload": payload, "path": path, "provenance": provenance}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    out = run(args.db)
    p = out["payload"]
    a, s = p["anomalies"], p["summary"]
    print(f"{a['flagged']:,} of {a['total_transactions']:,} transactions flagged ({a['rate']:.2%})")
    for rule, count in a["by_rule"].items():
        print(f"    {rule:<24} {count:>7,}")
    print(
        f"\n{s['areas_scored']} areas scored, {s['areas_unscored']} too thin; "
        f"median score {s['median_score']:.0f}"
    )
    print("\n  highest risk areas")
    for r in p["areas"][:5]:
        if r["score"] is None:
            continue
        drivers = sorted(
            ((k, v) for k, v in r["components"].items() if v is not None),
            key=lambda kv: kv[1],
            reverse=True,
        )[:2]
        print(
            f"    {r['area_key'][:30]:<30} {r['score']:>5.0f}  "
            f"driven by {', '.join(k for k, _ in drivers)}"
        )
    print(f"\nwrote {out['path']} ({out['provenance']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
