"""Arabic survives the round trip, or the file is refused.

Every fixture in this project is ASCII, so nothing had ever put a non-Latin character through the
loader — while the actual Dubai registry is full of them. Area names are the columns at stake, and
they become area keys, and every figure on the site is grouped by area key. A character that does
not survive the read does not produce an error; it produces a second area that looks like a real
one.

Three encodings, because these are the three a person actually ends up with: UTF-8, UTF-8 with the
byte-order mark Excel writes, and Windows-1256, the legacy Arabic codepage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etl.clean import utf8_problem

HEADER = (
    "TRANSACTION_NUMBER,INSTANCE_DATE,PROCEDURE_NAME_EN,GROUP_EN,IS_OFFPLAN_EN,AREA_NAME_EN,"
    "BUILDING_NAME_EN,PROJECT_NAME_EN,PROPERTY_TYPE_EN,PROPERTY_SUB_TYPE_EN,ROOMS_EN,"
    "PROCEDURE_AREA,ACTUAL_WORTH,METER_SALE_PRICE\n"
)
ARABIC_AREA = "مرسى دبي"
ROW = (
    f"1-2024-100,01-03-2024,Sell,Sales,Existing Properties,{ARABIC_AREA},MARINA GATE 1,"
    "Marina Gate,Unit,Flat,2 B/R,102.5,2450000,23902\n"
)


def write(path: Path, encoding: str) -> Path:
    if encoding == "cp1256":
        path.write_bytes((HEADER + ROW).encode("cp1256"))
    else:
        path.write_text(HEADER + ROW, encoding=encoding)
    return path


class TestTheEncodingCheck:
    def test_utf8_is_accepted(self, tmp_path):
        assert utf8_problem(write(tmp_path / "a.csv", "utf-8")) is None

    def test_a_byte_order_mark_is_accepted(self, tmp_path):
        """Excel writes UTF-8 with a BOM, and a person who opens a CSV to look at it before
        uploading has just re-saved it that way."""
        assert utf8_problem(write(tmp_path / "b.csv", "utf-8-sig")) is None

    def test_a_legacy_codepage_is_refused(self, tmp_path):
        problem = utf8_problem(write(tmp_path / "c.csv", "cp1256"))
        assert problem is not None
        assert "not UTF-8" in problem

    def test_the_refusal_names_the_file_and_the_fix(self, tmp_path):
        """An error that says "invalid utf-8 sequence" and stops is not actionable."""
        problem = utf8_problem(write(tmp_path / "transactions.csv", "cp1256"))
        assert "transactions.csv" in problem
        assert "iconv" in problem

    def test_it_says_why_it_does_not_simply_decode(self, tmp_path):
        """Guessing the codepage is the tempting fix and the wrong one: a wrong guess does not
        fail, it regroups every figure under a different area name."""
        problem = utf8_problem(write(tmp_path / "c.csv", "cp1256"))
        assert "grouped by area" in problem

    def test_a_plain_ascii_file_is_fine(self, tmp_path):
        path = tmp_path / "d.csv"
        path.write_text(HEADER + ROW.replace(ARABIC_AREA, "Marsa Dubai"))
        assert utf8_problem(path) is None

    def test_a_multibyte_character_split_by_the_sample_boundary_is_not_a_failure(self, tmp_path):
        """The check reads a fixed prefix, so it can land mid-character on a large file. That is
        an artefact of sampling, not a broken file, and reporting it would refuse valid data."""
        from etl.clean import ENCODING_SAMPLE_BYTES

        path = tmp_path / "big.csv"
        # Pad with ASCII so the Arabic lands exactly across the sample boundary.
        padding = "x" * (ENCODING_SAMPLE_BYTES - 1)
        path.write_text(padding + ARABIC_AREA, encoding="utf-8")
        assert utf8_problem(path) is None


class TestArabicSurvivesTheRoundTrip:
    """The refusal is only half of it. What comes back out has to be the same string."""

    @pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
    def test_the_area_name_is_unchanged_in_the_warehouse(self, encoding, tmp_path):
        import duckdb

        from etl.clean import main

        raw = tmp_path / "raw"
        raw.mkdir()
        write(raw / "transactions.csv", encoding)

        db = tmp_path / "y.duckdb"
        main(
            [
                "--raw",
                str(raw),
                "--db",
                str(db),
                "--provenance",
                "SYNTHETIC",
                "--out",
                str(tmp_path / "clean.json"),
            ]
        )

        con = duckdb.connect(str(db))
        names = [r[0] for r in con.execute("select area_name from transactions").fetchall()]
        con.close()
        assert names == [ARABIC_AREA], (
            f"the area name changed passing through the loader: {names!r}"
        )

    @pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
    def test_the_loader_identifies_it_whatever_the_encoding(self, encoding, tmp_path):
        from scripts.ingest_upload import identify

        verdict = identify(write(tmp_path / "t.csv", encoding))
        assert verdict is not None
        assert verdict[0] == "transactions"
