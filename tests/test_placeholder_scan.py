"""Placeholder-scan tests.

The scan gates Term 4 artefact generation, so it has to be right in both directions: it must catch
a real leftover marker, and it must not fire on the base64 an executed notebook is full of. A guard
that cries wolf gets switched off, which is worse than not having one.
"""

from __future__ import annotations

import json

from scripts.placeholder_scan import scan


def notebook(cells: list[dict]) -> str:
    return json.dumps({"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5})


def md_cell(text: str) -> dict:
    return {"cell_type": "markdown", "source": text, "metadata": {}}


def code_cell(source: str, image_b64: str = "") -> dict:
    outputs = (
        [{"output_type": "display_data", "data": {"image/png": image_b64}, "metadata": {}}]
        if image_b64
        else []
    )
    return {
        "cell_type": "code",
        "source": source,
        "outputs": outputs,
        "execution_count": 1,
        "metadata": {},
    }


class TestCatchesRealMarkers:
    def test_finds_a_leftover_todo_in_markdown(self, tmp_path):
        (tmp_path / "report.md").write_text("# Report\n\nTODO: write the conclusion\n")
        assert len(scan(tmp_path)) == 1

    def test_finds_a_bracketed_insert_marker(self, tmp_path):
        (tmp_path / "report.md").write_text("The median was [insert figure here].\n")
        assert len(scan(tmp_path)) == 1

    def test_finds_a_row_of_x_placeholders(self, tmp_path):
        (tmp_path / "report.md").write_text("Yield was XXX% last year.\n")
        assert len(scan(tmp_path)) == 1

    def test_finds_a_marker_in_a_notebook_cell(self, tmp_path):
        (tmp_path / "nb.ipynb").write_text(notebook([md_cell("## Results\n\nTODO: add the chart")]))
        assert len(scan(tmp_path)) == 1

    def test_reports_the_file_and_the_offending_text(self, tmp_path):
        (tmp_path / "report.md").write_text("nothing\nFIXME: this line\n")
        hit = scan(tmp_path)[0]
        assert "report.md" in hit
        assert "FIXME" in hit


class TestDoesNotCryWolf:
    def test_ignores_base64_image_data_in_notebook_outputs(self, tmp_path):
        """An executed notebook embeds megabytes of base64 that is full of XX by chance."""
        blob = "iVBORw0KGgoAAAANSUhEUgAAArIAAAGGCAYAAACXXemKmAAAAOnRFWHRTb2Z0d2FyZQ" * 200
        (tmp_path / "nb.ipynb").write_text(notebook([code_cell("print('hello')", image_b64=blob)]))
        assert scan(tmp_path) == []

    def test_ignores_xx_inside_a_longer_word(self, tmp_path):
        (tmp_path / "notes.md").write_text("The file hash was a3fXXbeef and the run succeeded.\n")
        assert scan(tmp_path) == []

    def test_ignores_todo_inside_a_longer_word(self, tmp_path):
        (tmp_path / "notes.md").write_text("The mastodon dataset is unrelated.\n")
        assert scan(tmp_path) == []

    def test_skips_the_retrieval_reports(self, tmp_path):
        """Those record whatever the publisher served, including its own wording."""
        (tmp_path / "source_probe.json").write_text('{"sample": "TODO list of datasets"}')
        assert scan(tmp_path) == []

    def test_ignores_file_types_that_are_not_prose(self, tmp_path):
        (tmp_path / "script.py").write_text("# TODO: refactor this later\n")
        assert scan(tmp_path) == []

    def test_a_clean_directory_passes(self, tmp_path):
        (tmp_path / "report.md").write_text("# Report\n\nThe median net yield was 3.43%.\n")
        assert scan(tmp_path) == []


class TestRobustness:
    def test_a_missing_directory_is_not_a_failure(self, tmp_path):
        assert scan(tmp_path / "absent") == []

    def test_a_malformed_notebook_does_not_crash_the_scan(self, tmp_path):
        (tmp_path / "broken.ipynb").write_text("{not valid json")
        (tmp_path / "report.md").write_text("TODO: still found\n")
        assert len(scan(tmp_path)) == 1

    def test_scans_nested_directories(self, tmp_path):
        nested = tmp_path / "results" / "deep"
        nested.mkdir(parents=True)
        (nested / "notes.md").write_text("TODO: buried\n")
        assert len(scan(tmp_path)) == 1

    def test_the_shipped_docs_directory_is_clean(self):
        from scripts.placeholder_scan import ROOT

        assert scan(ROOT / "docs") == []
