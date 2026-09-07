"""The operator upload path.

This is the seam the whole data ladder rests on: the bulk files are published on a host that
refuses datacenter addresses, so a person downloads them and this turns them into the warehouse.
It has to work on what the portal actually hands over — its column names, its filenames, its
archives — not on tidied fixtures, so the cases here use the real Dubai Pulse column headers.
"""

from __future__ import annotations

import zipfile

import pytest

from scripts.ingest_upload import identify, main

# The columns Dubai Pulse actually publishes, upper-cased as they arrive in the CSV.
DLD_TRANSACTIONS = (
    "TRANSACTION_NUMBER,INSTANCE_DATE,PROCEDURE_NAME_EN,TRANS_GROUP_EN,REG_TYPE_EN,"
    "AREA_NAME_EN,BUILDING_NAME_EN,PROJECT_NAME_EN,PROPERTY_TYPE_EN,PROPERTY_SUB_TYPE_EN,"
    "ROOMS_EN,PROCEDURE_AREA,ACTUAL_WORTH,METER_SALE_PRICE\n"
    "1-2024-100,01-03-2024,Sell,Sales,Existing Properties,Marsa Dubai,MARINA GATE 1,"
    "Marina Gate,Unit,Flat,2 B/R,102.5,2450000,23902\n"
    "1-2024-101,02-03-2024,Sell,Sales,Off-Plan Properties,Business Bay,BAY SQUARE,"
    "Bay Square,Unit,Flat,1 B/R,68.0,1290000,18970\n"
)

DLD_RENTS = (
    "CONTRACT_ID,CONTRACT_START_DATE,CONTRACT_END_DATE,AREA_NAME_EN,PROPERTY_NAME,"
    "EJARI_PROPERTY_TYPE_EN,EJARI_BUS_PROPERTY_TYPE_EN,ACTUAL_AREA,ANNUAL_AMOUNT,VERSION_EN\n"
    "E-1,01-01-2024,31-12-2024,Marsa Dubai,MARINA GATE 1,Unit,2 B/R,102.5,145000,New\n"
    "E-2,15-02-2024,14-02-2025,Business Bay,BAY SQUARE,Unit,1 B/R,68.0,88000,Renewed\n"
)


@pytest.fixture
def downloads(tmp_path):
    """A downloads folder, named the way a portal names things."""
    folder = tmp_path / "Downloads"
    folder.mkdir()
    (folder / "Transactions (1).csv").write_text(DLD_TRANSACTIONS)
    (folder / "rent_contracts_export_2026.csv").write_text(DLD_RENTS)
    (folder / "receipt.pdf").write_bytes(b"%PDF-1.4 not a table")
    return folder


class TestIdentification:
    def test_a_transactions_extract_is_recognised_by_its_columns(self, downloads) -> None:
        """Not by its name: the portal calls it whatever it likes, including 'Transactions (1)'."""
        verdict = identify(downloads / "Transactions (1).csv")
        assert verdict is not None
        assert verdict[0] == "transactions"

    def test_a_rent_extract_is_recognised_by_its_columns(self, downloads) -> None:
        verdict = identify(downloads / "rent_contracts_export_2026.csv")
        assert verdict is not None
        assert verdict[0] == "rent_contracts"

    def test_something_that_is_not_a_table_is_not_guessed_at(self, tmp_path) -> None:
        junk = tmp_path / "notes.csv"
        junk.write_text("alpha,beta\n1,2\n")
        assert identify(junk) is None

    def test_the_two_extracts_are_not_confused_with_each_other(self, downloads) -> None:
        """They share area and size columns, so the distinction has to come from the rest."""
        assert (
            identify(downloads / "Transactions (1).csv")[0]
            != (identify(downloads / "rent_contracts_export_2026.csv")[0])
        )


class TestIntake:
    def test_a_downloads_folder_becomes_a_raw_drop(self, downloads, tmp_path, capsys) -> None:
        raw = tmp_path / "raw"
        assert main([str(downloads), "--raw", str(raw)]) == 0
        assert (raw / "transactions.csv").exists()
        assert (raw / "rent_contracts.csv").exists()
        # The unreadable file is reported, not copied or fatal.
        assert not (raw / "receipt.pdf").exists()

    def test_a_zip_is_unpacked(self, tmp_path) -> None:
        archive = tmp_path / "dld_open_data.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("Transactions.csv", DLD_TRANSACTIONS)
            zf.writestr("Rents.csv", DLD_RENTS)
        raw = tmp_path / "raw"
        assert main([str(archive), "--raw", str(raw)]) == 0
        assert (raw / "transactions.csv").exists()
        assert (raw / "rent_contracts.csv").exists()

    def test_real_files_clear_the_synthetic_marker(self, downloads, tmp_path) -> None:
        """The marker is what stamps every downstream row SYNTHETIC and blocks the artefacts."""
        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "SYNTHETIC").write_text("generated")
        main([str(downloads), "--raw", str(raw)])
        assert not (raw / "SYNTHETIC").exists()

    def test_a_dry_run_writes_nothing(self, downloads, tmp_path) -> None:
        raw = tmp_path / "raw"
        assert main([str(downloads), "--raw", str(raw), "--dry-run"]) == 0
        assert not list(raw.glob("*.csv")) if raw.exists() else True

    def test_nothing_usable_is_an_error_with_an_explanation(self, tmp_path, capsys) -> None:
        folder = tmp_path / "empty"
        folder.mkdir()
        (folder / "notes.csv").write_text("alpha,beta\n1,2\n")
        assert main([str(folder), "--raw", str(tmp_path / "raw")]) == 1
        assert "needs a date, an area and a price" in capsys.readouterr().err

    def test_every_file_matching_a_table_is_kept(self, tmp_path) -> None:
        """The Land Department's portal exports a date range rather than a bulk file, so the
        realistic download is one file per year. An earlier version kept whichever had the most
        mapped columns and dropped the rest, which for that download shape loses almost everything
        while printing a confident success line."""
        folder = tmp_path / "d"
        folder.mkdir()
        (folder / "transactions_2023.csv").write_text(DLD_TRANSACTIONS)
        (folder / "transactions_2024.csv").write_text(
            DLD_TRANSACTIONS.replace("1-2024-100", "1-2023-500").replace("1-2024-101", "1-2023-501")
        )
        raw = tmp_path / "raw"
        main([str(folder), "--raw", str(raw)])

        parts = sorted(p.name for p in raw.glob("transactions__*.csv"))
        assert len(parts) == 2, f"both years should land, got {parts}"

    def test_a_slimmer_view_alongside_a_full_extract_is_still_kept(self, tmp_path) -> None:
        """Keeping both is safe where dropping one is not: etl.clean dedupes by transaction id,
        so an overlapping slimmer view costs nothing, while discarding a year loses it."""
        folder = tmp_path / "d"
        folder.mkdir()
        (folder / "slim.csv").write_text(
            "INSTANCE_DATE,AREA_NAME_EN,ACTUAL_WORTH\n01-03-2024,Marsa Dubai,2450000\n"
        )
        (folder / "full.csv").write_text(DLD_TRANSACTIONS)
        raw = tmp_path / "raw"
        main([str(folder), "--raw", str(raw)])

        landed = "".join(p.read_text() for p in raw.glob("transactions*.csv"))
        assert "PROCEDURE_NAME_EN" in landed, "the full extract must be there"
        assert len(list(raw.glob("transactions*.csv"))) == 2

    def test_a_single_file_still_lands_under_the_plain_name(self, tmp_path) -> None:
        """One extract is the common case and should not acquire a part suffix."""
        folder = tmp_path / "d"
        folder.mkdir()
        (folder / "Transactions.csv").write_text(DLD_TRANSACTIONS)
        raw = tmp_path / "raw"
        main([str(folder), "--raw", str(raw)])
        assert (raw / "transactions.csv").exists()


class TestCleaningReadsEveryPart:
    """The intake writing several parts is only half of it; the reader has to pick them all up."""

    def test_rows_from_every_part_reach_the_warehouse(self, tmp_path) -> None:

        from etl.clean import main as clean_main

        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "transactions__000.csv").write_text(DLD_TRANSACTIONS)
        (raw / "transactions__001.csv").write_text(
            DLD_TRANSACTIONS.replace("1-2024-100", "9-2019-900").replace("1-2024-101", "9-2019-901")
        )
        (raw / "rent_contracts.csv").write_text(DLD_RENTS)

        db = tmp_path / "y.duckdb"
        # --out into tmp_path, or this writes a REAL-provenance result built from two fixture rows
        # straight into docs/results/, which is the exact contamination the guard exists to stop.
        clean_main(
            [
                "--raw",
                str(raw),
                "--db",
                str(db),
                "--provenance",
                "REAL",
                "--out",
                str(tmp_path / "clean.json"),
            ]
        )

        import duckdb

        con = duckdb.connect(str(db))
        ids = {r[0] for r in con.execute("select transaction_id from transactions").fetchall()}
        con.close()
        assert {"1-2024-100", "9-2019-900"} <= ids, (
            f"rows from both parts should be present, got {sorted(ids)}"
        )

    def test_a_single_plain_file_is_still_read(self, tmp_path) -> None:
        from etl.clean import main as clean_main

        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "transactions.csv").write_text(DLD_TRANSACTIONS)
        db = tmp_path / "y.duckdb"
        assert (
            clean_main(
                [
                    "--raw",
                    str(raw),
                    "--db",
                    str(db),
                    "--provenance",
                    "REAL",
                    "--out",
                    str(tmp_path / "clean.json"),
                ]
            )
            == 0
        )
