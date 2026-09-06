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

    def test_the_fuller_extract_wins_when_two_files_match(self, tmp_path) -> None:
        """Portals publish both a full extract and slimmer views; the full one is the better source."""
        folder = tmp_path / "d"
        folder.mkdir()
        (folder / "slim.csv").write_text(
            "INSTANCE_DATE,AREA_NAME_EN,ACTUAL_WORTH\n01-03-2024,Marsa Dubai,2450000\n"
        )
        (folder / "full.csv").write_text(DLD_TRANSACTIONS)
        raw = tmp_path / "raw"
        main([str(folder), "--raw", str(raw)])
        # The full extract has more mapped columns, so it is the one that landed.
        assert "PROCEDURE_NAME_EN" in (raw / "transactions.csv").read_text()
