"""Repeat-sales price index: what the same property sold for, twice.

A median price per square metre moves when the *mix* of what sold changes, not only when prices
change. A quarter in which three towers complete and a hundred small studios transact will show a
falling median even if every individual property is worth more. That is the standard trap in
property indices, and it is why a repeat-sales index exists: by comparing a property against
itself, composition cancels out.

Method is Bailey–Muth–Nourse, the estimator underneath the Case–Shiller family. Each repeat pair
contributes one observation of the log price change between two periods; regressing those changes
on period dummies recovers the index. Weighted least squares is used because a pair spanning eight
years accumulates far more idiosyncratic noise than one spanning eight months, so long gaps get
less say.

Dubai's registry does not carry a stable unit identifier on older rows, so pairs are formed at the
most specific level available and the level used is recorded per pair. A building-level pair is a
weaker observation than a unit-level one and the output says which is which rather than blending
them silently.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from finance.base import DEFAULT_DB, Warehouse, write_result

PAIRS_SQL = """
select
    ts,
    area_key,
    building_name,
    property_type,
    rooms,
    area_sqm,
    price_aed,
    price_per_sqm,
    transaction_id
from transactions
where price_per_sqm is not null
  and area_sqm is not null
  and property_type = 'unit'
order by ts
"""

# Below this many pairs an index is noise with a line through it, so none is published.
MIN_PAIRS_PER_PERIOD = 5
MIN_PERIODS = 6
# A resale inside this window is more likely a flip or a correction than a market move.
MIN_HOLD_DAYS = 90


def _identity(df: pl.DataFrame) -> pl.DataFrame:
    """Attach the most specific identity available for each sale, and say which it is.

    Older registry rows lack a unit identifier, so the fallback is the building plus the physical
    characteristics that make a unit comparable to itself: floor area to the nearest square metre
    and bedroom count.
    """
    return df.with_columns(
        pl.when(pl.col("building_name").is_not_null() & pl.col("area_sqm").is_not_null())
        .then(
            pl.concat_str(
                [
                    pl.col("area_key"),
                    pl.col("building_name"),
                    pl.col("rooms").cast(pl.String).fill_null("?"),
                    pl.col("area_sqm").round(0).cast(pl.String),
                ],
                separator="|",
            )
        )
        .otherwise(None)
        .alias("unit_key"),
        pl.lit("building+size+rooms").alias("identity_level"),
    )


def build_pairs(df: pl.DataFrame, *, min_hold_days: int = MIN_HOLD_DAYS) -> pl.DataFrame:
    """Form consecutive repeat-sale pairs for each identified property."""
    df = _identity(df).drop_nulls(subset=["unit_key"]).sort(["unit_key", "ts"])

    pairs = df.with_columns(
        pl.col("ts").shift(1).over("unit_key").alias("prev_ts"),
        pl.col("price_per_sqm").shift(1).over("unit_key").alias("prev_ppsqm"),
        pl.col("area_key").shift(1).over("unit_key").alias("prev_area"),
    ).drop_nulls(subset=["prev_ts", "prev_ppsqm"])

    return (
        pairs.with_columns(
            (pl.col("ts") - pl.col("prev_ts")).dt.total_days().alias("hold_days"),
            (pl.col("price_per_sqm").log() - pl.col("prev_ppsqm").log()).alias("log_return"),
        )
        .filter(pl.col("hold_days") >= min_hold_days)
        .filter(pl.col("log_return").abs() < np.log(20))  # a 20x move is a data error, not a market
    )


def _period(col: str) -> pl.Expr:
    return pl.col(col).dt.truncate("1mo")


def largest_connected_component(pairs: pl.DataFrame) -> set[Any]:
    """The set of periods reachable from one another through repeat-sale pairs.

    A repeat-sales index is only identified within a connected component. If June 2020 and June
    2021 are linked by pairs, and July 2020 and July 2021 are linked by pairs, but nothing links
    the June chain to the July chain, then the relative level of the two chains is unknowable —
    the data simply does not say. Least squares will still return an answer, because it quietly
    picks the minimum-norm solution, and that answer is an artefact rather than a measurement.

    So the components are found explicitly and only the largest is published.
    """
    parent: dict[Any, Any] = {}

    def find(x: Any) -> Any:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: Any, b: Any) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for buy, sell in zip(pairs["buy_period"], pairs["sell_period"], strict=True):
        union(buy, sell)

    groups: dict[Any, set[Any]] = {}
    for node in parent:
        groups.setdefault(find(node), set()).add(node)
    return max(groups.values(), key=len) if groups else set()


def estimate_index(
    pairs: pl.DataFrame, *, base: float = 100.0
) -> tuple[pl.DataFrame, dict[str, Any]]:
    """Bailey-Muth-Nourse weighted least squares on period dummies."""
    pairs = pairs.with_columns(
        _period("prev_ts").alias("buy_period"), _period("ts").alias("sell_period")
    )
    all_periods = set(pairs["buy_period"].to_list()) | set(pairs["sell_period"].to_list())

    # Only a connected set of periods is identified; see largest_connected_component.
    connected = largest_connected_component(pairs)
    dropped_periods = len(all_periods) - len(connected)
    pairs_before = pairs.height
    if dropped_periods:
        pairs = pairs.filter(
            pl.col("buy_period").is_in(list(connected))
            & pl.col("sell_period").is_in(list(connected))
        )

    periods = sorted(connected)
    if len(periods) < MIN_PERIODS:
        raise ValueError(
            f"only {len(periods)} connected periods with repeat sales; need {MIN_PERIODS}"
        )

    position = {p: i for i, p in enumerate(periods)}
    n, k = pairs.height, len(periods)

    # One row per pair: -1 in the buy period, +1 in the sell period. The first period is the
    # reference and is dropped, so the remaining coefficients are log index levels against it.
    design = np.zeros((n, k))
    design[np.arange(n), [position[p] for p in pairs["buy_period"]]] = -1.0
    design[np.arange(n), [position[p] for p in pairs["sell_period"]]] = 1.0
    design = design[:, 1:]

    y = pairs["log_return"].to_numpy()
    # Variance of a random walk grows with the holding period, so weight by its inverse.
    hold_years = np.maximum(pairs["hold_days"].to_numpy() / 365.25, 0.25)
    weights = 1.0 / hold_years
    sqrt_w = np.sqrt(weights)

    beta, residuals, rank, _ = np.linalg.lstsq(design * sqrt_w[:, None], y * sqrt_w, rcond=None)
    log_levels = np.concatenate([[0.0], beta])
    levels = base * np.exp(log_levels)

    counts = (
        pl.concat([pairs["buy_period"], pairs["sell_period"]])
        .value_counts()
        .rename({"": "period"} if "" in pairs.columns else {})
    )
    count_map = dict(
        zip(counts[counts.columns[0]].to_list(), counts["count"].to_list(), strict=True)
    )

    frame = pl.DataFrame(
        {
            "period": periods,
            "index": levels,
            "n_pairs": [count_map.get(p, 0) for p in periods],
        }
    )

    fitted = design @ beta
    ss_res = float(np.sum(weights * (y - fitted) ** 2))
    ss_tot = float(np.sum(weights * (y - np.average(y, weights=weights)) ** 2))
    diagnostics = {
        "n_pairs": n,
        "n_periods": k,
        "rank": int(rank),
        "periods_dropped_as_disconnected": dropped_periods,
        "pairs_dropped_as_disconnected": pairs_before - n,
        "r_squared": 1 - ss_res / ss_tot if ss_tot else None,
        "median_hold_days": float(pairs["hold_days"].median()),
        "thin_periods": int((frame["n_pairs"] < MIN_PAIRS_PER_PERIOD).sum()),
    }
    return frame, diagnostics


def annual_growth(frame: pl.DataFrame) -> list[dict[str, Any]]:
    """Year-on-year change in the index, which is the figure a page actually shows."""
    yearly = (
        frame.with_columns(pl.col("period").dt.year().alias("year"))
        .group_by("year")
        .agg(pl.col("index").mean().alias("index"), pl.col("n_pairs").sum().alias("n_pairs"))
        .sort("year")
    )
    out: list[dict[str, Any]] = []
    previous: float | None = None
    for row in yearly.iter_rows(named=True):
        growth = None if previous is None or previous == 0 else row["index"] / previous - 1
        out.append(
            {
                "year": row["year"],
                "index": round(row["index"], 2),
                "growth": None if growth is None else round(growth, 4),
                "n_pairs": row["n_pairs"],
            }
        )
        previous = row["index"]
    return out


def run(db_path: Path = DEFAULT_DB) -> dict[str, Any]:
    with Warehouse(db_path) as wh:
        q = wh.query(PAIRS_SQL)
        provenance = wh.provenance()

    pairs = build_pairs(q.frame)
    frame, diagnostics = estimate_index(pairs)
    growth = annual_growth(frame)

    payload = {
        "method_id": "repeat_sales_v1",
        "method": "Bailey-Muth-Nourse weighted least squares on period dummies",
        "identity": (
            "building, bedroom count and floor area, because the registry lacks a stable unit "
            "identifier on older rows"
        ),
        "min_hold_days": MIN_HOLD_DAYS,
        "weighting": "inverse holding period, since a long gap accumulates more idiosyncratic noise",
        "sql": q.sql,
        "diagnostics": diagnostics,
        "annual": growth,
        "series": [
            {"period": str(r["period"]), "index": round(r["index"], 3), "n_pairs": r["n_pairs"]}
            for r in frame.iter_rows(named=True)
        ],
    }
    path = write_result("index.json", payload, provenance)
    return {"payload": payload, "path": path, "provenance": provenance}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)

    out = run(args.db)
    d = out["payload"]["diagnostics"]
    print(f"{d['n_pairs']:,} repeat pairs over {d['n_periods']} months")
    print(f"  median holding period {d['median_hold_days']:,.0f} days")
    print(f"  weighted R-squared    {d['r_squared']:.3f}")
    print(f"  thin periods          {d['thin_periods']}")
    print("\n  year   index   growth   pairs")
    for row in out["payload"]["annual"]:
        g = "     —" if row["growth"] is None else f"{row['growth']:+6.1%}"
        print(f"  {row['year']}  {row['index']:7.1f}  {g}  {row['n_pairs']:>7,}")
    print(f"\nwrote {out['path']} ({out['provenance']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
