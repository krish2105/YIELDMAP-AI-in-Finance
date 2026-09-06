"""Profiler tests, against a fixture with deliberately planted defects.

The point of profiling is that the report describes the data rather than the data description, so
these tests check the profiler finds defects that were planted at known positions.
"""

from __future__ import annotations

import json

import polars as pl

from etl.profile import (
    MARK_END,
    MARK_START,
    MAX_DISTINCT,
    profile_dir,
    profile_file,
    profile_frame,
    render_markdown,
    update_datasets_doc,
)
from tests.conftest import BLANK_BUILDING, N_ROWS, NULL_ROOMS


def field(prof: dict, name: str) -> dict:
    return next(f for f in prof["fields"] if f["name"] == name)


class TestFrameProfile:
    def test_reports_shape(self, transactions_df):
        prof = profile_frame(transactions_df)
        assert prof["rows"] == N_ROWS
        assert prof["columns"] == transactions_df.width
        assert "area_name_en" in prof["column_names"]

    def test_every_column_is_described(self, transactions_df):
        prof = profile_frame(transactions_df)
        assert len(prof["fields"]) == transactions_df.width
        for f in prof["fields"]:
            assert {"name", "dtype", "nulls", "blanks", "null_rate", "n_distinct"} <= set(f)

    def test_finds_the_planted_nulls(self, transactions_df):
        f = field(profile_frame(transactions_df), "rooms_en")
        assert f["nulls"] == NULL_ROOMS
        assert f["null_rate"] == round(NULL_ROOMS / N_ROWS, 6)

    def test_counts_empty_strings_as_missing_not_as_a_value(self, transactions_df):
        """Open-data CSVs encode missing as a blank; a naive null count misses it entirely."""
        f = field(profile_frame(transactions_df), "building_name_en")
        assert f["nulls"] == 0
        assert f["blanks"] == BLANK_BUILDING
        assert f["null_rate"] == round(BLANK_BUILDING / N_ROWS, 6)

    def test_numeric_columns_carry_a_range(self, transactions_df):
        f = field(profile_frame(transactions_df), "actual_worth")
        assert f["min"] <= f["median"] <= f["max"]
        assert f["min"] > 0

    def test_date_columns_carry_a_parsed_range(self, transactions_df):
        f = field(profile_frame(transactions_df), "instance_date")
        assert f["date_min"].startswith("2004")
        assert f["date_max"].startswith("2025")
        assert f["date_parsed_rate"] == 1.0

    def test_categorical_columns_carry_their_common_values(self, transactions_df):
        f = field(profile_frame(transactions_df), "area_name_en")
        values = {t["value"] for t in f["top_values"]}
        assert "Dubai Marina" in values
        assert sum(t["count"] for t in f["top_values"]) == N_ROWS

    def test_distinct_count_is_capped_for_identifier_columns(self, transactions_df):
        f = field(profile_frame(transactions_df), "transaction_id")
        assert f["n_distinct"] == MAX_DISTINCT
        assert f["distinct_capped"] is True

    def test_low_cardinality_columns_are_not_capped(self, transactions_df):
        f = field(profile_frame(transactions_df), "property_type_en")
        assert f["n_distinct"] == 4
        assert f["distinct_capped"] is False


class TestFileProfile:
    def test_profiles_a_csv_on_disk(self, transactions_csv):
        prof = profile_file(transactions_csv)
        assert prof["rows"] == N_ROWS
        assert prof["bytes"] > 0
        assert prof["sampled"] is False

    def test_sampling_keeps_the_row_count_exact(self, transactions_csv):
        """A sampled profile must never let a reader mistake the sample for the whole file."""
        prof = profile_file(transactions_csv, sample_rows=500)
        assert prof["rows"] == N_ROWS
        assert prof["rows_profiled"] == 500
        assert prof["sampled"] is True

    def test_round_trips_through_parquet(self, tmp_path, transactions_df):
        path = tmp_path / "transactions.parquet"
        transactions_df.write_parquet(path)
        assert profile_file(path)["rows"] == N_ROWS


class TestDirectoryProfile:
    def test_profiles_every_file_and_totals_the_rows(self, tmp_path, transactions_df):
        transactions_df.write_csv(tmp_path / "transactions.csv")
        transactions_df.head(100).write_csv(tmp_path / "rent_contracts.csv")
        report = profile_dir(tmp_path)
        assert report["n_datasets"] == 2
        assert report["total_rows"] == N_ROWS + 100
        assert report["errors"] == []

    def test_one_unreadable_file_does_not_lose_the_others(self, tmp_path, transactions_df):
        transactions_df.write_csv(tmp_path / "good.csv")
        (tmp_path / "bad.parquet").write_bytes(b"not a parquet file")
        report = profile_dir(tmp_path)
        assert report["n_datasets"] == 1
        assert len(report["errors"]) == 1
        assert report["errors"][0]["path"] == "bad.parquet"

    def test_picks_up_the_download_manifest_so_the_profile_is_traceable(
        self, tmp_path, transactions_df
    ):
        transactions_df.head(10).write_csv(tmp_path / "transactions.csv")
        (tmp_path / "manifest.json").write_text(
            json.dumps({"generated_at": "2026-09-06T00:00:00+00:00", "files": [{"sha256": "abc"}]})
        )
        report = profile_dir(tmp_path)
        assert report["manifest"]["files"][0]["sha256"] == "abc"

    def test_report_is_json_serialisable(self, tmp_path, transactions_df):
        transactions_df.head(50).write_csv(tmp_path / "transactions.csv")
        json.loads(json.dumps(profile_dir(tmp_path), default=str))

    def test_handles_an_empty_drop(self, tmp_path):
        report = profile_dir(tmp_path)
        assert report["n_datasets"] == 0
        assert report["total_rows"] == 0

    def test_handles_a_file_with_no_rows(self, tmp_path):
        pl.DataFrame({"a": pl.Series([], dtype=pl.Int64)}).write_csv(tmp_path / "empty.csv")
        report = profile_dir(tmp_path)
        assert report["datasets"][0]["rows"] == 0


class TestMarkdownRendering:
    """The documentation table is generated from the measurement, never typed."""

    def test_renders_a_row_per_dataset_with_measured_numbers(self, tmp_path, transactions_df):
        transactions_df.write_csv(tmp_path / "transactions.csv")
        md = render_markdown(profile_dir(tmp_path))
        assert "| `transactions` |" in md
        assert f"{N_ROWS:,}" in md
        assert "2004-01-01 to 2025" in md

    def test_names_the_worst_column_rather_than_just_a_number(self, tmp_path, transactions_df):
        transactions_df.write_csv(tmp_path / "transactions.csv")
        md = render_markdown(profile_dir(tmp_path))
        # project_name_en is null on every 7th row: 14.3%, the worst in the fixture.
        assert "`project_name_en`" in md
        assert "14.3%" in md

    def test_says_so_plainly_when_there_is_nothing_to_report(self):
        assert "No profile has been produced yet" in render_markdown({"datasets": []})

    def test_replaces_only_the_generated_region_of_the_doc(self, tmp_path, transactions_df):
        transactions_df.head(10).write_csv(tmp_path / "transactions.csv")
        doc = tmp_path / "datasets.md"
        doc.write_text(f"# Datasets\n\nkeep me\n\n{MARK_START}\nold\n{MARK_END}\n\nkeep me too\n")
        assert update_datasets_doc(profile_dir(tmp_path), doc) is True
        text = doc.read_text()
        assert "keep me" in text and "keep me too" in text
        assert "old" not in text
        assert text.count(MARK_START) == 1

    def test_appends_a_section_when_the_doc_has_no_markers(self, tmp_path, transactions_df):
        transactions_df.head(10).write_csv(tmp_path / "transactions.csv")
        doc = tmp_path / "datasets.md"
        doc.write_text("# Datasets\n")
        assert update_datasets_doc(profile_dir(tmp_path), doc) is True
        assert MARK_START in doc.read_text()

    def test_is_idempotent(self, tmp_path, transactions_df):
        transactions_df.head(10).write_csv(tmp_path / "transactions.csv")
        doc = tmp_path / "datasets.md"
        doc.write_text(f"# Datasets\n\n{MARK_START}\nold\n{MARK_END}\n")
        report = profile_dir(tmp_path)
        assert update_datasets_doc(report, doc) is True
        assert update_datasets_doc(report, doc) is False

    def test_does_nothing_when_the_doc_is_absent(self, tmp_path):
        assert update_datasets_doc({"datasets": []}, tmp_path / "nope.md") is False


class TestProvenanceRouting:
    """A profile of generated data must not land in the real results directory."""

    def test_a_drop_with_a_marker_is_reported_as_generated(self, tmp_path, transactions_df):
        transactions_df.head(20).write_csv(tmp_path / "transactions.csv")
        (tmp_path / "SYNTHETIC").write_text("generated")
        assert profile_dir(tmp_path)["provenance"] == "SYNTHETIC"

    def test_a_drop_without_a_marker_is_reported_as_real(self, tmp_path, transactions_df):
        transactions_df.head(20).write_csv(tmp_path / "transactions.csv")
        assert profile_dir(tmp_path)["provenance"] == "REAL"

    def test_the_generated_table_carries_a_visible_warning(self, tmp_path, transactions_df):
        transactions_df.head(20).write_csv(tmp_path / "transactions.csv")
        (tmp_path / "SYNTHETIC").write_text("generated")
        md = render_markdown(profile_dir(tmp_path))
        assert "generated data, not the Dubai registry" in md
        assert "provenance: SYNTHETIC" in md

    def test_a_real_table_carries_no_warning(self, tmp_path, transactions_df):
        transactions_df.head(20).write_csv(tmp_path / "transactions.csv")
        md = render_markdown(profile_dir(tmp_path))
        assert "generated data" not in md
        assert "provenance: REAL" in md
