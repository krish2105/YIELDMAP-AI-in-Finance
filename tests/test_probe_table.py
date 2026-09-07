"""The reachability table in docs/datasets.md is generated, not typed.

CLAUDE.md's rule is that every number shown anywhere traces to a query or an artefact. That table
was the exception: prose, typed from a run someone had read. It drifted exactly as you would
expect — by 2026-09-07 it called a host reachable that the artefact recorded as ok=false with a
404 — and nothing failed, because nothing was comparing them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.render_probe_table import BEGIN, END, main, render, rows, splice

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "datasets.md"
PROBE = ROOT / "docs" / "results" / "source_probe.json"


@pytest.fixture
def report() -> dict:
    return {
        "generated_at": "2026-09-07T02:20:00+00:00",
        "runner": "github-actions",
        "n_candidates": 3,
        "n_reachable": 1,
        "n_catalogues": 2,
        "n_catalogues_reachable": 0,
        "verdict": "blocked",
        "candidates": [
            {"url": "https://a.example/one", "kind": "page", "ok": True, "status": 200},
            {"url": "https://b.example/x", "kind": "catalogue", "ok": False, "status": 404},
            {
                "url": "https://b.example/y",
                "kind": "catalogue",
                "ok": False,
                "status": None,
                "error": "ConnectTimeout: timed out",
            },
        ],
    }


class TestTheDocumentMatchesTheArtefact:
    def test_it_is_up_to_date(self):
        """The whole point. Regenerate with: uv run python -m scripts.render_probe_table"""
        assert main(["--check"]) == 0

    def test_the_markers_are_present(self):
        doc = DOC.read_text()
        assert doc.count(BEGIN) == 1
        assert doc.count(END) == 1
        assert doc.index(BEGIN) < doc.index(END)

    def test_every_host_in_the_artefact_appears_in_the_document(self):
        from urllib.parse import urlparse

        probe = json.loads(PROBE.read_text())
        hosts = {urlparse(c["url"]).netloc for c in probe["candidates"]}
        table = DOC.read_text().split(BEGIN)[1].split(END)[0]
        for host in hosts:
            assert f"`{host}`" in table, f"{host} was probed but is not in the table"


class TestRendering:
    def test_rows_are_one_per_host_with_counts(self, report):
        by_host = {r["host"]: r for r in rows(report)}
        assert by_host["a.example"] == {
            "host": "a.example",
            "tried": 1,
            "answered": 1,
            "observed": "200",
        }
        assert by_host["b.example"]["tried"] == 2
        assert by_host["b.example"]["answered"] == 0

    def test_an_exception_stands_in_for_a_status_code(self, report):
        by_host = {r["host"]: r for r in rows(report)}
        assert "ConnectTimeout" in by_host["b.example"]["observed"]
        assert "timed out" not in by_host["b.example"]["observed"], "the class, not the detail"

    def test_the_word_reachable_is_not_used_of_a_host(self, report):
        """The ambiguity that caused the drift: it meant two different things in two places."""
        table = render(report)
        body = table.split("| Host |")[1]
        assert "reachable" not in body.lower()

    def test_the_catalogue_count_is_what_the_verdict_rests_on(self, report):
        assert "0 of 2 catalogues" in render(report)
        assert "**blocked**" in render(report)

    def test_an_artefact_without_catalogue_counts_says_so_rather_than_printing_zero(self, report):
        del report["n_catalogues"]
        del report["n_catalogues_reachable"]
        report["verdict"] = "reachable"

        out = render(report)

        assert "0 of 0" not in out, "that reads as 'there are no catalogues'"
        assert "predates the catalogue-aware verdict" in out


class TestTheCheck:
    def test_check_fails_when_the_document_is_stale(self, report, monkeypatch, tmp_path):
        import scripts.render_probe_table as mod

        probe = tmp_path / "source_probe.json"
        probe.write_text(json.dumps(report))
        doc = tmp_path / "datasets.md"
        doc.write_text(f"before\n\n{BEGIN}\nstale\n{END}\n\nafter\n")
        monkeypatch.setattr(mod, "PROBE", probe)
        monkeypatch.setattr(mod, "DOC", doc)

        assert mod.main(["--check"]) == 1, "a stale table must fail rather than be rewritten"
        assert "stale" in doc.read_text(), "--check must not write"

        assert mod.main([]) == 0
        assert "stale" not in doc.read_text()
        assert mod.main(["--check"]) == 0

    def test_splice_leaves_everything_outside_the_markers_alone(self, report):
        doc = f"KEEP BEFORE\n{BEGIN}\nold\n{END}\nKEEP AFTER\n"
        out = splice(doc, render(report))
        assert out.startswith("KEEP BEFORE\n")
        assert out.endswith("\nKEEP AFTER\n")
        assert "old" not in out

    def test_a_document_without_markers_is_an_error_not_a_silent_pass(self, report):
        with pytest.raises(SystemExit, match="markers"):
            splice("no markers here", render(report))
