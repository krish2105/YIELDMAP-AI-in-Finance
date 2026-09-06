"""Developer league table.

The question a buyer actually has about a developer is not how much they build but whether their
stock holds its value. So the table is built around a premium: the median price per square metre of
that developer's units against the median for the same areas at the same time. Comparing against
the *same areas* is what makes the number mean anything — a developer who only builds in Downtown
will show a huge raw price and no skill at all.

One honest limitation. The open registry carries a project name on each transaction but not a
developer identifier, so projects stand in for developers here. That over-counts a developer who
builds under many project names and under-counts one who reuses a name. When DLD's separate
developer dataset is loaded, this maps onto it without changing the method.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import polars as pl

from finance.base import DEFAULT_DB, Warehouse, write_result

MIN_TRANSACTIONS = 30

LEAGUE_SQL = """
with area_month as (
    select
        area_key,
        date_trunc('month', ts) as month,
        median(price_per_sqm)   as area_ppsqm
    from transactions
    where price_per_sqm is not null
    group by 1, 2
),
tagged as (
    select
        t.project_name,
        t.area_key,
        t.ts,
        t.price_aed,
        t.price_per_sqm,
        t.is_offplan,
        am.area_ppsqm,
        t.price_per_sqm / nullif(am.area_ppsqm, 0) as relative_price
    from transactions t
    join area_month am
      on am.area_key = t.area_key
     and am.month = date_trunc('month', t.ts)
    where t.project_name is not null
      and t.price_per_sqm is not null
)
select
    project_name,
    count(*)                                   as n,
    count(distinct area_key)                   as areas,
    min(ts)                                    as first_seen,
    max(ts)                                    as last_seen,
    median(price_aed)                          as median_price,
    median(price_per_sqm)                      as median_ppsqm,
    median(relative_price)                     as median_relative_price,
    avg(case when is_offplan then 1.0 else 0.0 end) as offplan_share,
    stddev_samp(relative_price)                as relative_price_sd
from tagged
group by 1
having count(*) >= {minimum}
order by n desc
"""


def build_league(frame: pl.DataFrame) -> pl.DataFrame:
    """Turn the raw aggregate into a ranked table with a readable premium."""
    if frame.height == 0:
        return frame

    return (
        frame.with_columns(
            ((pl.col("median_relative_price") - 1.0) * 100).alias("premium_pct"),
            ((pl.col("last_seen") - pl.col("first_seen")).dt.total_days() / 365.25).alias(
                "years_active"
            ),
        )
        .with_columns(
            (pl.col("n") / pl.col("years_active").clip(lower_bound=0.5)).alias("sales_per_year"),
            pl.when(pl.col("premium_pct") >= 10)
            .then(pl.lit("sells above its areas"))
            .when(pl.col("premium_pct") <= -10)
            .then(pl.lit("sells below its areas"))
            .otherwise(pl.lit("sells in line with its areas"))
            .alias("verdict"),
        )
        .sort("premium_pct", descending=True)
    )


def run(db_path: Path = DEFAULT_DB, *, minimum: int = MIN_TRANSACTIONS) -> dict[str, Any]:
    sql = LEAGUE_SQL.format(minimum=minimum)
    with Warehouse(db_path) as wh:
        q = wh.query(sql)
        provenance = wh.provenance()

    league = build_league(q.frame)
    payload = {
        "method_id": "developers_v1",
        "premium_definition": (
            "median price per square metre against the median for the same area in the same "
            "month, so location and timing are held constant"
        ),
        "limitation": (
            "the open registry carries a project name but no developer identifier, so projects "
            "stand in for developers"
        ),
        "min_transactions": minimum,
        "sql": q.sql,
        "summary": {
            "developers": league.height,
            "median_premium_pct": float(league["premium_pct"].median()) if league.height else None,
            "above_their_areas": int((league["premium_pct"] >= 10).sum()) if league.height else 0,
            "below_their_areas": int((league["premium_pct"] <= -10).sum()) if league.height else 0,
        },
        "league": league.to_dicts(),
    }
    path = write_result("developers.json", payload, provenance)
    return {"payload": payload, "path": path, "provenance": provenance}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--min-transactions", type=int, default=MIN_TRANSACTIONS)
    args = parser.parse_args(argv)

    out = run(args.db, minimum=args.min_transactions)
    s, league = out["payload"]["summary"], out["payload"]["league"]
    print(f"{s['developers']} projects with at least {args.min_transactions} sales")
    print(f"  {s['above_their_areas']} sell above their areas, {s['below_their_areas']} below")
    print(f"  median premium {s['median_premium_pct']:+.1f}%\n")
    print(f"  {'project':<22} {'sales':>6} {'areas':>6} {'premium':>9}  {'off-plan':>9}  verdict")
    for row in league[:5] + league[-3:]:
        print(
            f"  {str(row['project_name'])[:22]:<22} {row['n']:>6,} {row['areas']:>6} "
            f"{row['premium_pct']:>+8.1f}%  {row['offplan_share']:>8.0%}  {row['verdict']}"
        )
    print(f"\nwrote {out['path']} ({out['provenance']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
