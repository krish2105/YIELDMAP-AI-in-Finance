"""The report and the deck must not be able to launder generated figures.

CLAUDE.md's rule is that generated data cannot reach a Term 4 artefact, and
`scripts/guard_synthetic.py` is the mechanism. These documents are the artefacts it exists to
stop, so the interesting tests are the refusals rather than the happy path.

The stamping matters as much as the refusal. A draft that generates but labels nothing is worse
than no draft: it looks finished.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("docx", reason="artefact generation needs the `docs` extra")
pytest.importorskip("pptx", reason="artefact generation needs the `docs` extra")

from scripts import build_deck, build_report  # noqa: E402
from scripts.term4.artefacts import collect  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "AI217_YIELDMAP_report.docx"
DECK = ROOT / "docs" / "AI217_YIELDMAP_deck.pptx"


def _auto_shape(shape):
    """The autoshape kind, or None. python-pptx raises on a text box rather than returning None."""
    try:
        return shape.auto_shape_type
    except (ValueError, AttributeError):
        return None


class TestTheGuardIsLoadBearing:
    """Generation is refused while the guard blocks, unless the caller says --draft."""

    @pytest.mark.parametrize("module", [build_report, build_deck])
    def test_it_refuses_without_draft_while_the_guard_blocks(self, module, tmp_path, capsys):
        out = tmp_path / "refused.bin"

        code = module.main(["--out", str(out)])

        assert code == 1, "generated a graded artefact from data the guard rejects"
        assert not out.exists(), "wrote the file anyway"
        assert "provenance guard is blocking" in capsys.readouterr().err

    @pytest.mark.parametrize(("module", "suffix"), [(build_report, ".docx"), (build_deck, ".pptx")])
    def test_draft_generates_a_readable_file(self, module, suffix, tmp_path):
        out = tmp_path / f"draft{suffix}"

        assert module.main(["--draft", "--out", str(out)]) == 0
        assert out.exists() and out.stat().st_size > 10_000
        with zipfile.ZipFile(out) as archive:
            assert archive.testzip() is None


class TestNothingIsRestatedFromMemory:
    def test_every_row_names_the_file_it_came_from(self):
        bundle = collect()
        rows = (
            bundle.rows_models
            + bundle.rows_retrieval
            + bundle.rows_engineering
            + bundle.rows_governance
        )
        assert rows, "the loader found no results at all"
        for row in rows:
            assert row.source.endswith(".json"), f"{row.label!r} cites no artefact"
            assert (ROOT / "docs" / "results" / row.source).exists() or (
                ROOT / "docs" / "results" / "synthetic" / row.source
            ).exists(), f"{row.label!r} cites {row.source}, which is not in docs/results/"

    def test_provenance_is_read_from_the_file_not_guessed(self):
        bundle = collect()
        for row in bundle.rows_models:
            body = json.loads((ROOT / "docs" / "results" / "synthetic" / row.source).read_text())
            assert row.provenance == body["provenance"]

    def test_a_missing_model_becomes_a_row_that_says_so_rather_than_a_number(self):
        from scripts.term4.artefacts import MISSING, num, pct

        assert num(None) == MISSING
        assert pct(None) == MISSING


class TestTheDraftIsStamped:
    """Three places, because one is a place a reader can skip."""

    def test_the_report_carries_the_banner_the_column_and_the_section(self):
        from docx import Document

        doc = Document(REPORT)
        text = "\n".join(p.text for p in doc.paragraphs)
        assert "DRAFT" in "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells), (
            "no draft banner on the cover"
        )
        assert "How provenance is enforced" in text, "no section explaining the guard"

        model_table = next(
            t
            for t in doc.tables
            if any(c.text.strip() == "hedonic" for r in t.rows for c in r.cells)
        )
        headers = [c.text for c in model_table.rows[0].cells]
        assert "Data" in headers, "the model table has no provenance column"
        assert any("stand-in" in c.text for r in model_table.rows[1:] for c in r.cells), (
            "no row is marked as a stand-in"
        )

    def test_the_deck_names_the_stand_in_on_the_opening_slide(self):
        from pptx import Presentation

        prs = Presentation(DECK)
        first = " ".join(
            s.text_frame.text for s in prs.slides[0].shapes if s.has_text_frame
        ).upper()
        assert "STAND-IN" in first

    def test_every_slide_has_speaker_notes(self):
        from pptx import Presentation

        for i, slide in enumerate(Presentation(DECK).slides, start=1):
            assert slide.has_notes_slide, f"slide {i} has no notes"
            assert len(slide.notes_slide.notes_text_frame.text) > 80, f"slide {i} notes are thin"


class TestTheLayoutDefectsARendererFound:
    """Everything here was invisible until the documents were rendered and looked at.

    LibreOffice could not open a .docx in this environment at first — only libreoffice-core was
    installed, with no Writer or Impress import filter, so even a one-paragraph file failed.
    Installing the filters turned "I cannot check this" into five real defects.
    """

    def test_the_cover_ends_with_a_page_break(self):
        """add_break() defaults to a LINE break, so the cover, the contents and section 1 all
        shared page one."""
        from docx import Document
        from docx.oxml.ns import qn

        doc = Document(REPORT)
        breaks = [br.get(qn("w:type")) for p in doc.paragraphs for br in p._p.iter(qn("w:br"))]
        assert breaks.count("page") >= 2, "the cover and the contents need page breaks after them"

    def test_every_table_header_repeats_across_a_page(self):
        """A table that breaks across pages left its continuation with no column labels."""
        from docx import Document
        from docx.oxml.ns import qn

        doc = Document(REPORT)
        for i, table in enumerate(doc.tables):
            if len(table.rows) < 2:
                continue  # the cover's callout box is one cell, not a data table
            header = table.rows[0]._tr
            assert header.find(qn("w:trPr")) is not None, f"table {i} header has no properties"
            assert header.find(qn("w:trPr")).find(qn("w:tblHeader")) is not None, (
                f"table {i} header does not repeat on a page break"
            )

    def test_no_row_may_split_across_a_page(self):
        """A split row orphaned the tail of one cell from the label that says what it measures."""
        from docx import Document
        from docx.oxml.ns import qn

        doc = Document(REPORT)
        for i, table in enumerate(doc.tables):
            if len(table.rows) < 2:
                continue  # the cover callout is a one-cell layout box, not a data table
            for j, row in enumerate(table.rows):
                properties = row._tr.find(qn("w:trPr"))
                assert properties is not None and properties.find(qn("w:cantSplit")) is not None, (
                    f"table {i} row {j} may split across a page"
                )

    def test_the_architecture_arrows_are_shapes_not_glyphs(self):
        """The arrow rendered as a dot: the glyph is missing from the substituted font."""
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE

        slide = Presentation(DECK).slides[3]
        arrows = [s for s in slide.shapes if _auto_shape(s) == MSO_SHAPE.RIGHT_ARROW]
        assert len(arrows) == 4, "expected an arrow between each of the five stages"
        assert not any("→" in s.text_frame.text for s in slide.shapes if s.has_text_frame), (
            "an arrow glyph is back in the text"
        )

    def test_the_arrows_fit_the_gap_they_are_drawn_into(self):
        """They were wider than the gap, so each card overdrew the arrow before it."""
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE

        slide = Presentation(DECK).slides[3]
        cards, arrows = [], []
        for shape in slide.shapes:
            kind = _auto_shape(shape)
            if kind == MSO_SHAPE.ROUNDED_RECTANGLE:
                cards.append(shape)
            elif kind == MSO_SHAPE.RIGHT_ARROW:
                arrows.append(shape)
        row = sorted([c for c in cards if c.top < 914400 * 3], key=lambda c: c.left)
        gap = row[1].left - (row[0].left + row[0].width)
        assert gap > 0, "the cards touch, so there is nowhere for an arrow"
        for arrow in arrows:
            assert arrow.width <= gap, "the arrow is wider than the gap between cards"


class TestTheDocumentsFitTheirPages:
    """The defect a renderer would show, caught by arithmetic instead."""

    def test_no_table_is_wider_than_the_text_column(self):
        from docx import Document

        doc = Document(REPORT)
        section = doc.sections[0]
        text_cm = section.page_width.cm - section.left_margin.cm - section.right_margin.cm
        for i, table in enumerate(doc.tables):
            width = sum(c.width.cm for c in table.rows[0].cells if c.width)
            assert width <= text_cm + 0.01, (
                f"table {i} is {width:.2f}cm in a {text_cm:.2f}cm column"
            )

    def test_no_shape_falls_off_a_slide(self):
        from pptx import Presentation

        prs = Presentation(DECK)
        for i, slide in enumerate(prs.slides, start=1):
            for shape in slide.shapes:
                if shape.left is None:
                    continue
                assert shape.left >= 0 and shape.top >= 0, f"slide {i}: shape starts off-slide"
                assert shape.left + shape.width <= prs.slide_width, f"slide {i}: shape overruns"
                assert shape.top + shape.height <= prs.slide_height, f"slide {i}: shape overruns"
