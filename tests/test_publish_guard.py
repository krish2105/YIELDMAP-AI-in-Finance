"""Publish and provenance-guard tests.

The guard is the mechanism that keeps generated data out of graded work, so it is tested as
carefully as anything that computes a number.
"""

from __future__ import annotations

import json

import duckdb
import polars as pl
import pytest

from etl.publish import build_area_dimension, build_freshness, publish
from etl.results import result_path, results_dir
from scripts import guard_synthetic
from scripts.guard_synthetic import check, db_provenance, results_provenance


@pytest.fixture
def areas_csv(tmp_path):
    p = tmp_path / "areas.csv"
    p.write_text(
        "dld_name,common_name,lat,lon,coord_confidence,note\n"
        "Marsa Dubai,Dubai Marina,25.0805,55.1403,high,\n"
        "Business Bay,Business Bay,25.1857,55.2664,high,\n"
    )
    return p


def _db(tmp_path, provenance="REAL", extra_area=None):
    """A small database in the shape etl.clean produces."""
    rows = [
        {
            "ts": "2025-01-15",
            "area_name": "Marsa Dubai",
            "area_key": "marsa dubai",
            "price_aed": 2_400_000.0,
            "provenance": provenance,
        },
        {
            "ts": "2025-06-20",
            "area_name": "Business Bay",
            "area_key": "business bay",
            "price_aed": 1_600_000.0,
            "provenance": provenance,
        },
    ]
    if extra_area:
        rows.append(
            {
                "ts": "2025-03-01",
                "area_name": extra_area,
                "area_key": extra_area.lower(),
                "price_aed": 900_000.0,
                "provenance": provenance,
            }
        )
    tx = pl.DataFrame(rows).with_columns(pl.col("ts").str.to_date())
    rent = pl.DataFrame(
        {
            "start": ["2025-02-01"],
            "area_key": ["marsa dubai"],
            "annual_rent_aed": [120_000.0],
            "provenance": [provenance],
        }
    ).with_columns(pl.col("start").str.to_date())

    path = tmp_path / "y.duckdb"
    con = duckdb.connect(str(path))
    con.register("tx", tx)
    con.register("rent", rent)
    con.execute("create table transactions as select * from tx")
    con.execute("create table rent_contracts as select * from rent")
    con.close()
    return path


class TestAreaDimension:
    def test_is_driven_by_the_data_not_the_centroid_file(self, tmp_path, areas_csv):
        """An area the publisher reports but we have no coordinate for must still exist."""
        db = _db(tmp_path, extra_area="Unmapped Sector")
        con = duckdb.connect(str(db))
        build_area_dimension(con, areas_csv)
        rows = {
            r[0]: r for r in con.execute("select area_key, name, has_location from area").fetchall()
        }
        con.close()
        assert "unmapped sector" in rows
        assert rows["unmapped sector"][2] is False
        assert rows["marsa dubai"][2] is True

    def test_prefers_the_common_name_over_the_official_sector_name(self, tmp_path, areas_csv):
        db = _db(tmp_path)
        con = duckdb.connect(str(db))
        build_area_dimension(con, areas_csv)
        name = con.execute("select name from area where area_key = 'marsa dubai'").fetchone()[0]
        con.close()
        assert name == "Dubai Marina"

    def test_falls_back_to_the_published_name_when_there_is_no_mapping(self, tmp_path, areas_csv):
        db = _db(tmp_path, extra_area="Unmapped Sector")
        con = duckdb.connect(str(db))
        build_area_dimension(con, areas_csv)
        name = con.execute("select name from area where area_key = 'unmapped sector'").fetchone()[0]
        con.close()
        assert name == "Unmapped Sector"


class TestFreshness:
    def test_records_rows_and_the_latest_date_per_table(self, tmp_path):
        con = duckdb.connect(str(_db(tmp_path)))
        rows = {r["table_name"]: r for r in build_freshness(con)}
        con.close()
        assert rows["transactions"]["rows"] == 2
        assert rows["transactions"]["as_of"] == "2025-06-20"
        assert rows["rent_contracts"]["as_of"] == "2025-02-01"

    def test_a_table_with_any_synthetic_row_is_reported_as_synthetic(self, tmp_path):
        """A reader cannot tell which rows fed an aggregate, so the weaker claim governs."""
        path = _db(tmp_path, provenance="REAL")
        con = duckdb.connect(str(path))
        con.execute(
            "insert into transactions values ('2025-07-01', 'X', 'x', 100000.0, 'SYNTHETIC')"
        )
        rows = {r["table_name"]: r for r in build_freshness(con)}
        con.close()
        assert rows["transactions"]["provenance"] == "SYNTHETIC"

    def test_carries_the_download_hash_so_a_table_traces_to_a_file(self, tmp_path):
        con = duckdb.connect(str(_db(tmp_path)))
        manifest = {"files": [{"dataset": "transactions", "sha256": "deadbeef"}]}
        rows = {r["table_name"]: r for r in build_freshness(con, manifest)}
        con.close()
        assert rows["transactions"]["source_sha256"] == "deadbeef"
        assert rows["rent_contracts"]["source_sha256"] is None


class TestPublishIsIdempotent:
    def test_publishing_twice_gives_the_same_dimensions(self, tmp_path, areas_csv):
        db = _db(tmp_path)
        first = publish(db, areas_csv, tmp_path)
        second = publish(db, areas_csv, tmp_path)
        assert first["areas"] == second["areas"]
        assert [f["rows"] for f in first["freshness"]] == [f["rows"] for f in second["freshness"]]


class TestResultRouting:
    def test_real_and_generated_results_go_to_separate_directories(self, tmp_path):
        real = result_path("x.json", "REAL", base=tmp_path)
        synthetic = result_path("x.json", "SYNTHETIC", base=tmp_path)
        assert real.parent != synthetic.parent
        assert synthetic.parent.name == "synthetic"

    def test_a_glob_of_the_real_directory_never_picks_up_generated_results(self, tmp_path):
        result_path("real.json", "REAL", base=tmp_path).write_text("{}")
        result_path("fake.json", "SYNTHETIC", base=tmp_path).write_text("{}")
        assert [p.name for p in sorted(results_dir("REAL", tmp_path).glob("*.json"))] == [
            "real.json"
        ]


class TestProvenanceGuard:
    def test_passes_on_a_real_database(self, tmp_path):
        db = _db(tmp_path, provenance="REAL")
        clean, reasons = check(db, tmp_path / "results")
        assert clean is True
        assert reasons == []

    def test_blocks_on_a_synthetic_database_and_says_which_table(self, tmp_path):
        db = _db(tmp_path, provenance="SYNTHETIC")
        clean, reasons = check(db, tmp_path / "results")
        assert clean is False
        assert any("transactions" in r and "synthetic" in r for r in reasons)

    def test_counts_provenance_per_table(self, tmp_path):
        counts = db_provenance(_db(tmp_path, provenance="SYNTHETIC"))
        assert counts["transactions"] == {"SYNTHETIC": 2}

    def test_a_missing_database_is_not_a_failure(self, tmp_path):
        """CI does not commit the database; absence must not be read as contamination."""
        clean, reasons = check(tmp_path / "absent.duckdb", tmp_path / "results")
        assert clean is True

    def test_flags_a_result_file_produced_from_generated_data(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        (results / "hedonic.json").write_text(json.dumps({"provenance": "SYNTHETIC", "mape": 0.1}))
        assert results_provenance(results) == ["hedonic.json (declares provenance SYNTHETIC)"]

    def test_a_result_that_declares_nothing_is_not_trusted(self, tmp_path):
        """Inferring realness from the absence of a word let a generated profile through once."""
        results = tmp_path / "results"
        results.mkdir()
        (results / "profile.json").write_text(json.dumps({"n_datasets": 2, "total_rows": 100}))
        assert results_provenance(results) == ["profile.json (declares no provenance)"]

    def test_a_result_declaring_real_provenance_passes(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        (results / "hedonic.json").write_text(json.dumps({"provenance": "REAL", "mape": 0.1}))
        assert results_provenance(results) == []

    def test_an_unreadable_result_is_flagged_rather_than_skipped(self, tmp_path):
        results = tmp_path / "results"
        results.mkdir()
        (results / "broken.json").write_text("{not json")
        assert "broken.json" in results_provenance(results)[0]

    def test_does_not_scan_the_generated_results_directory(self, tmp_path):
        """Generated results are kept, in their own directory, and are not contamination."""
        results = tmp_path / "results"
        (results / "synthetic").mkdir(parents=True)
        (results / "synthetic" / "clean.json").write_text('{"provenance": "SYNTHETIC"}')
        clean, reasons = check(tmp_path / "absent.duckdb", results)
        assert clean is True


class TestTheGuardSaysWhatItInspected:
    """A guard that vouches for something it never opened is worse than no guard."""

    def test_an_absent_database_is_not_reported_as_a_clean_one(self, tmp_path, capsys) -> None:
        results = tmp_path / "results"
        results.mkdir()
        code = guard_synthetic.main(
            ["--db", str(tmp_path / "absent.duckdb"), "--results", str(results)]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "no database" in out
        # The reassuring line must not appear when nothing was inspected: it is the same sentence
        # whether the data is real, generated or missing, which is how a gap becomes a green tick.
        assert "no synthetic data in the database" not in out

    def test_the_report_records_whether_a_database_was_inspected(self, tmp_path) -> None:
        results = tmp_path / "results"
        results.mkdir()
        report = tmp_path / "report.json"
        guard_synthetic.main(
            [
                "--db",
                str(tmp_path / "absent.duckdb"),
                "--results",
                str(results),
                "--report",
                str(report),
            ]
        )
        assert json.loads(report.read_text())["db_inspected"] is False
