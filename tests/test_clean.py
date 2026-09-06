"""Cleaner tests.

The load-bearing test here is the equivalence one: the fast Polars path must agree with the plain
Python rules in etl.canon on every row. Those rules are what the documentation and the report
describe, so if the vectorised twin drifts from them the project starts publishing numbers its own
methodology does not explain.
"""

from __future__ import annotations

import polars as pl
import pytest

from etl.canon import (
    canon_area_key,
    canon_is_offplan,
    canon_property_type,
    canon_rooms,
)
from etl.clean import (
    area_coverage,
    clean_rent_contracts,
    clean_transactions,
    dedupe,
    expr_area_key,
    expr_is_offplan,
    expr_property_type,
    expr_rooms,
    load_duckdb,
)
from etl.schema import RENT_ALIASES, TRANSACTION_ALIASES, map_columns
from tests.conftest import make_transactions

ROOMS_VOCAB = [
    "Studio",
    "STUDIO",
    " studio ",
    "1 B/R",
    "2 B/R",
    "3 B/R",
    "10 B/R",
    "2 BR",
    "4 Bedroom",
    "5",
    "PENTHOUSE",
    "Office",
    "Shop",
    "Land",
    "N/A",
    "",
    "banana",
    None,
]
TYPE_VOCAB = [
    "Unit",
    "Flat",
    "apartment",
    "Villa",
    "Villa/House",
    "Land",
    "Building",
    "Shop",
    "Warehouse",
    "Spaceship",
    "",
    None,
]
AREA_VOCAB = [
    "Al Barsha South Fourth",
    "AL BARSHA SOUTH FOURTH",
    "Al Barsha South  Fourth",
    "Za'abeel",
    "Za’abeel",
    "Zaabeel",
    "Al Warqa'a First",
    "  Dubai   Marina ",
    "",
    "   ",
    None,
]
REG_VOCAB = ["Off-Plan Properties", "off plan", "Existing Properties", "Ready", "Grant", "", None]


class TestVectorisedRulesMatchTheReadableOnes:
    """The fast path and the documented rules must give the same answer, value for value."""

    def test_rooms(self):
        df = pl.DataFrame({"raw": ROOMS_VOCAB}, schema={"raw": pl.String})
        got = df.select(expr_rooms("raw").alias("v"))["v"].to_list()
        assert got == [canon_rooms(v) for v in ROOMS_VOCAB]

    def test_property_type(self):
        df = pl.DataFrame({"raw": TYPE_VOCAB}, schema={"raw": pl.String})
        got = df.select(expr_property_type("raw").alias("v"))["v"].to_list()
        assert got == [canon_property_type(v) for v in TYPE_VOCAB]

    def test_area_key(self):
        df = pl.DataFrame({"raw": AREA_VOCAB}, schema={"raw": pl.String})
        got = df.select(expr_area_key("raw").alias("v"))["v"].to_list()
        assert got == [canon_area_key(v) for v in AREA_VOCAB]

    def test_is_offplan(self):
        df = pl.DataFrame(
            {"reg": REG_VOCAB, "proc": ["Sell"] * len(REG_VOCAB)},
            schema={"reg": pl.String, "proc": pl.String},
        )
        got = df.select(expr_is_offplan("reg", "proc").alias("v"))["v"].to_list()
        assert got == [canon_is_offplan(r, "Sell") for r in REG_VOCAB]

    def test_agrees_across_a_whole_fixture(self):
        """Not just the awkward vocabulary — every row of a realistic frame."""
        df = make_transactions(2_000)
        got = df.select(
            expr_rooms("rooms_en").alias("rooms"),
            expr_property_type("property_type_en").alias("ptype"),
            expr_area_key("area_name_en").alias("akey"),
        )
        assert got["rooms"].to_list() == [canon_rooms(v) for v in df["rooms_en"]]
        assert got["ptype"].to_list() == [canon_property_type(v) for v in df["property_type_en"]]
        assert got["akey"].to_list() == [canon_area_key(v) for v in df["area_name_en"]]


@pytest.fixture
def cleaned(transactions_df):
    lf = transactions_df.lazy()
    mapping = map_columns(transactions_df.columns, TRANSACTION_ALIASES)
    return clean_transactions(lf, mapping).collect()


class TestCleanTransactions:
    def test_produces_the_canonical_columns(self, cleaned):
        assert {
            "ts",
            "area_name",
            "area_key",
            "price_aed",
            "price_per_sqm",
            "rooms",
            "property_type",
            "is_offplan",
            "provenance",
        } <= set(cleaned.columns)

    def test_price_per_sqm_is_derived_from_the_stored_values(self, cleaned):
        row = cleaned.filter(pl.col("area_sqm").is_not_null()).head(1).to_dicts()[0]
        assert row["price_per_sqm"] == pytest.approx(row["price_aed"] / row["area_sqm"])

    def test_stamps_provenance_on_every_row(self, cleaned):
        assert cleaned["provenance"].unique().to_list() == ["REAL"]

    def test_synthetic_provenance_is_carried_through(self, transactions_df):
        mapping = map_columns(transactions_df.columns, TRANSACTION_ALIASES)
        out = clean_transactions(transactions_df.lazy(), mapping, provenance="SYNTHETIC").collect()
        assert out["provenance"].unique().to_list() == ["SYNTHETIC"]

    def test_drops_rows_that_cannot_be_used(self, transactions_df):
        """A row with no price, date or area cannot contribute to anything this project computes."""
        broken = transactions_df.head(100).with_columns(
            pl.when(pl.int_range(0, 100, eager=False) < 10)
            .then(None)
            .otherwise(pl.col("actual_worth"))
            .alias("actual_worth")
        )
        mapping = map_columns(broken.columns, TRANSACTION_ALIASES)
        assert clean_transactions(broken.lazy(), mapping).collect().height == 90

    def test_keeps_a_stable_schema_when_optional_columns_are_absent(self, transactions_df):
        """A file without rooms must still load, with a typed null column rather than an error."""
        thin = transactions_df.drop("rooms_en", "property_type_en", "procedure_area")
        mapping = map_columns(thin.columns, TRANSACTION_ALIASES)
        out = clean_transactions(thin.lazy(), mapping).collect()
        assert out["rooms"].null_count() == out.height
        assert out["price_per_sqm"].null_count() == out.height
        assert out.height > 0

    def test_parses_dates_in_the_publisher_format(self, cleaned):
        assert cleaned["ts"].min().year == 2004
        assert cleaned["ts"].max().year == 2025

    def test_an_impossible_price_becomes_null_and_the_row_is_dropped(self, transactions_df):
        poisoned = transactions_df.head(50).with_columns(pl.lit(-1.0).alias("actual_worth"))
        mapping = map_columns(poisoned.columns, TRANSACTION_ALIASES)
        assert clean_transactions(poisoned.lazy(), mapping).collect().height == 0


class TestCleanRentContracts:
    def test_cleans_an_ejari_shaped_frame(self):
        df = pl.DataFrame(
            {
                "contract_id": ["R1", "R2", "R3"],
                "contract_start_date": ["2025-01-15", "2025-02-01", "2025-03-01"],
                "contract_end_date": ["2026-01-14", "2026-01-31", "2026-02-28"],
                "area_name_en": ["Dubai Marina", "Za'abeel", "Zaabeel"],
                "annual_amount": [95_000, 130_000, None],
                "ejari_property_type_en": ["Unit", "Unit", "Unit"],
                "rooms_en": ["1 B/R", "2 B/R", "Studio"],
                "actual_area": [78.0, 120.0, 40.0],
            }
        )
        mapping = map_columns(df.columns, RENT_ALIASES)
        out = clean_rent_contracts(df.lazy(), mapping).collect()
        assert out.height == 2  # the row with no rent is dropped
        assert out["area_key"].to_list() == ["dubai marina", "zaabeel"]
        assert out["rooms"].to_list() == [1, 2]


class TestDedupe:
    def test_removes_republished_rows_by_identifier(self, transactions_df):
        doubled = pl.concat([transactions_df.head(100), transactions_df.head(100)])
        assert dedupe(doubled.lazy(), id_col="transaction_id").collect().height == 100

    def test_without_an_identifier_the_whole_row_decides(self):
        df = pl.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
        assert dedupe(df.lazy()).collect().height == 2

    def test_rows_with_no_identifier_are_dropped_when_deduping_by_one(self):
        df = pl.DataFrame({"transaction_id": ["A", None, "B"], "v": [1, 2, 3]})
        out = dedupe(df.lazy(), id_col="transaction_id").collect()
        assert sorted(out["transaction_id"].to_list()) == ["A", "B"]

    def test_cleaning_the_same_drop_twice_gives_the_same_rows(self, transactions_df):
        """The publisher republishes overlapping windows; a nightly job must be idempotent."""
        mapping = map_columns(transactions_df.columns, TRANSACTION_ALIASES)
        once = dedupe(
            clean_transactions(transactions_df.lazy(), mapping), id_col="transaction_id"
        ).collect()
        twice = dedupe(
            clean_transactions(pl.concat([transactions_df, transactions_df]).lazy(), mapping),
            id_col="transaction_id",
        ).collect()
        assert once.height == twice.height


class TestLoad:
    def test_writes_the_tables_and_reports_their_row_counts(self, tmp_path, cleaned):
        counts = load_duckdb({"transactions": cleaned}, tmp_path / "y.duckdb")
        assert counts["transactions"] == cleaned.height

    def test_publishing_twice_inserts_once(self, tmp_path, cleaned):
        """The nightly job runs on a schedule; a rerun must not double the table."""
        db = tmp_path / "y.duckdb"
        first = load_duckdb({"transactions": cleaned}, db)
        second = load_duckdb({"transactions": cleaned}, db)
        assert first == second

    def test_append_mode_adds_rows(self, tmp_path, cleaned):
        db = tmp_path / "y.duckdb"
        load_duckdb({"transactions": cleaned}, db)
        counts = load_duckdb({"transactions": cleaned}, db, replace=False)
        assert counts["transactions"] == cleaned.height * 2


class TestAreaCoverage:
    def test_reports_which_areas_have_no_centroid_rather_than_placing_them_at_the_origin(
        self, tmp_path
    ):
        areas = tmp_path / "areas.csv"
        areas.write_text(
            "dld_name,common_name,lat,lon,coord_confidence,note\n"
            "Dubai Marina,Dubai Marina,25.08,55.14,high,\n"
        )
        cov = area_coverage(areas, ["dubai marina", "somewhere unmapped", "dubai marina"])
        assert cov["areas_in_data"] == 2
        assert cov["areas_with_centroid"] == 1
        assert cov["coverage"] == 0.5
        assert cov["missing_centroid"] == ["somewhere unmapped"]

    def test_the_shipped_table_covers_every_area_the_generator_uses(self):
        from pathlib import Path

        from etl.synthetic import load_areas

        root = Path(__file__).resolve().parent.parent
        names = [a["dld_name"] for a in load_areas(root / "data" / "areas.csv")]
        cov = area_coverage(root / "data" / "areas.csv", [canon_area_key(n) for n in names])
        assert cov["coverage"] == 1.0
