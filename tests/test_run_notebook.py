"""Tests for the notebook executor.

The notebook is a graded artefact that ships with its outputs stored, which is exactly how it
rots: a renamed function or a changed results file leaves it rendering last week's figures
perfectly, because the cells that would now fail are never run. This is the check that runs them,
so it has to actually fail when a cell does.
"""

from __future__ import annotations

import json

import pytest

from scripts.run_notebook import execute, main


def notebook(sources: list[str]) -> str:
    return json.dumps(
        {
            "cells": [
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    "source": source,
                }
                for source in sources
            ],
            "metadata": {
                "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}
            },
            "nbformat": 4,
            "nbformat_minor": 5,
        }
    )


class TestExecution:
    def test_a_notebook_whose_cells_all_run_passes(self, tmp_path):
        path = tmp_path / "ok.ipynb"
        path.write_text(notebook(["x = 1 + 1", "assert x == 2"]))
        ok, problems = execute(path, write=False)
        assert ok is True
        assert problems == []

    def test_a_cell_that_raises_fails_the_check(self, tmp_path):
        """The whole point. A stored output that no longer reproduces is a stale claim."""
        path = tmp_path / "broken.ipynb"
        path.write_text(notebook(["x = 1", "raise ValueError('the results file moved')"]))
        ok, problems = execute(path, write=False)
        assert ok is False
        assert problems
        assert "the results file moved" in problems[0]

    def test_an_import_that_no_longer_resolves_is_caught(self, tmp_path):
        """The realistic rot: a module gets renamed and the notebook still has the old name."""
        path = tmp_path / "moved.ipynb"
        path.write_text(notebook(["from finance.a_module_that_was_renamed import thing"]))
        ok, problems = execute(path, write=False)
        assert ok is False

    def test_without_write_the_notebook_on_disk_is_unchanged(self, tmp_path):
        """CI checks the committed notebook still runs; it must not then produce a diff."""
        path = tmp_path / "ok.ipynb"
        path.write_text(notebook(["print('hello')"]))
        before = path.read_text()
        execute(path, write=False)
        assert path.read_text() == before

    def test_with_write_the_outputs_are_saved(self, tmp_path):
        path = tmp_path / "ok.ipynb"
        path.write_text(notebook(["print('hello')"]))
        execute(path, write=True)
        cells = json.loads(path.read_text())["cells"]
        assert cells[0]["outputs"], "executing with --write should store what the cell printed"

    def test_a_failing_notebook_is_not_written_back(self, tmp_path):
        """Saving a half-executed notebook would replace good stored outputs with an error."""
        path = tmp_path / "broken.ipynb"
        path.write_text(notebook(["print('fine')", "raise RuntimeError('boom')"]))
        before = path.read_text()
        execute(path, write=True)
        assert path.read_text() == before


class TestTheCommand:
    def test_it_returns_zero_when_the_notebook_runs(self, tmp_path):
        path = tmp_path / "ok.ipynb"
        path.write_text(notebook(["x = 1"]))
        assert main(["--notebook", str(path)]) == 0

    def test_it_returns_non_zero_when_a_cell_fails(self, tmp_path):
        path = tmp_path / "broken.ipynb"
        path.write_text(notebook(["raise SystemError('nope')"]))
        assert main(["--notebook", str(path)]) == 1

    def test_a_missing_notebook_is_an_error_rather_than_a_silent_pass(self, tmp_path):
        assert main(["--notebook", str(tmp_path / "absent.ipynb")]) == 1


class TestTheCommittedNotebook:
    def test_it_still_executes(self):
        """The artefact itself, run end to end — about five seconds, so it earns its place in the
        default suite rather than behind a marker nobody remembers to pass."""
        from scripts.run_notebook import NOTEBOOK

        if not NOTEBOOK.exists():
            pytest.skip("no notebook in this checkout")
        ok, problems = execute(NOTEBOOK, write=False)
        assert ok, problems
