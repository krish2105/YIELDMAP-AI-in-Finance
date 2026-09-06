"""Shared fixtures.

The generated frame here is a *test* fixture with the shape of a DLD transactions drop. It exists
to exercise the pipeline's edge cases with known answers — it is never loaded into the database and
never reaches a result file. Data that stands in for real rows in the pipeline is a separate thing,
carries ``provenance = 'SYNTHETIC'``, and is blocked from every Term 4 artefact.
"""

from __future__ import annotations

import random
from pathlib import Path

import polars as pl
import pytest

# Deliberately planted defects, so the profiler can be checked against known answers.
N_ROWS = 10_000
NULL_ROOMS = 1_200  # rooms_en missing, as it is for land and many older rows
BLANK_BUILDING = 800  # empty string rather than a null, as open-data CSVs often encode it

AREAS = [
    ("Jumeirah Village Circle", 25.0575, 55.2093),
    ("Dubai Marina", 25.0805, 55.1403),
    ("Business Bay", 25.1857, 55.2664),
    ("Downtown Dubai", 25.1950, 55.2744),
    ("Palm Jumeirah", 25.1124, 55.1390),
]
PROPERTY_TYPES = ["Unit", "Villa", "Land", "Building"]
ROOMS = ["Studio", "1 B/R", "2 B/R", "3 B/R", "4 B/R"]


def make_transactions(n: int = N_ROWS, seed: int = 217) -> pl.DataFrame:
    """A DLD-shaped transactions frame with known defects."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        area, _, _ = AREAS[i % len(AREAS)]
        ptype = PROPERTY_TYPES[rng.randrange(len(PROPERTY_TYPES))]
        sqm = round(rng.uniform(35, 420), 2)
        ppsqm = rng.uniform(8_000, 32_000)
        year = 2004 + (i % 22)
        rows.append(
            {
                "transaction_id": f"T{i:07d}",
                "instance_date": f"{year:04d}-{1 + (i % 12):02d}-{1 + (i % 28):02d}",
                "trans_group_en": rng.choice(["Sales", "Mortgages", "Gifts"]),
                "procedure_name_en": rng.choice(["Sell", "Sell Pre-Registration", "Mortgage"]),
                "reg_type_en": rng.choice(["Existing Properties", "Off-Plan Properties"]),
                "area_name_en": area,
                "building_name_en": f"Tower {i % 300}",
                "project_name_en": f"Project {i % 90}" if i % 7 else None,
                "property_type_en": ptype,
                "property_sub_type_en": rng.choice(["Flat", "Villa", "Land", "Office"]),
                "rooms_en": ROOMS[rng.randrange(len(ROOMS))],
                "has_parking": rng.choice([0, 1]),
                "procedure_area": sqm,
                "actual_worth": round(sqm * ppsqm, 2),
                "meter_sale_price": round(ppsqm, 2),
            }
        )
    df = pl.DataFrame(rows)

    # Plant the defects at known positions so the tests can assert exact counts.
    idx = pl.int_range(0, df.height, eager=True)
    df = df.with_columns(
        pl.when(idx < NULL_ROOMS).then(None).otherwise(pl.col("rooms_en")).alias("rooms_en"),
        pl.when((idx >= NULL_ROOMS) & (idx < NULL_ROOMS + BLANK_BUILDING))
        .then(pl.lit(""))
        .otherwise(pl.col("building_name_en"))
        .alias("building_name_en"),
    )
    return df


@pytest.fixture(scope="session")
def transactions_df() -> pl.DataFrame:
    return make_transactions()


@pytest.fixture(scope="session")
def transactions_csv(tmp_path_factory, transactions_df: pl.DataFrame) -> Path:
    path = tmp_path_factory.mktemp("raw") / "transactions.csv"
    transactions_df.write_csv(path)
    return path
