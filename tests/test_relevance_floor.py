"""Tests for the relevance-floor calibration.

The calibration exists to answer a question with a measurement rather than a guess: is there a
retrieval score below which the corpus can be said not to cover a question? Its answer on this
corpus is no. That is a useful result only if the method that produced it is sound, so the
separation arithmetic is tested against cases where the answer is known.
"""

from __future__ import annotations

import json

import pytest

from scripts.calibrate_relevance import separation


class TestSeparation:
    def test_a_signal_that_separates_cleanly_is_reported_as_such(self):
        """In-scope values all above every out-of-scope value: a threshold exists between them."""
        result = separation(in_scope=[0.8, 0.9, 1.0], out_scope=[0.1, 0.2, 0.3])
        assert result["separates_cleanly"] is True
        assert 0.3 < result["threshold"] <= 0.8
        assert result["out_of_scope_refused"] == 1.0
        assert result["in_scope_wrongly_refused"] == 0.0

    def test_an_overlapping_signal_is_reported_as_overlapping(self):
        result = separation(in_scope=[0.2, 0.9, 1.0], out_scope=[0.1, 0.5, 0.8])
        assert result["separates_cleanly"] is False

    def test_the_cost_of_the_best_threshold_is_reported_not_just_the_benefit(self):
        """A threshold that catches every out-of-scope question by refusing half the real ones is
        not a usable signal, and a report showing only the catch rate would call it one."""
        result = separation(in_scope=[0.1, 0.2, 0.9, 1.0], out_scope=[0.3, 0.4])
        assert result["out_of_scope_refused"] > 0
        assert result["in_scope_wrongly_refused"] > 0

    def test_it_records_the_range_that_makes_the_overlap_visible(self):
        result = separation(in_scope=[0.4, 0.9], out_scope=[0.1, 0.6])
        assert result["in_scope_min"] == 0.4
        assert result["out_of_scope_max"] == 0.6
        assert result["in_scope_min"] < result["out_of_scope_max"]

    def test_a_single_value_on_each_side_does_not_raise(self):
        assert separation(in_scope=[0.5], out_scope=[0.1])["separates_cleanly"] is True


class TestThePublishedCalibration:
    @pytest.fixture(scope="class")
    def report(self) -> dict:
        from scripts.calibrate_relevance import ROOT

        path = ROOT / "docs" / "results" / "relevance_floor.json"
        if not path.exists():
            pytest.skip("the calibration has not been run in this checkout")
        return json.loads(path.read_text())

    def test_it_declares_real_provenance(self, report):
        """It measures this system's retrieval, not the property data."""
        assert report["provenance"] == "REAL"

    def test_all_three_signals_were_measured(self, report):
        assert set(report["signals"]) == {"lexical", "semantic", "coverage"}

    def test_the_verdict_follows_from_the_measurements(self, report):
        """The prose conclusion is derived, not written independently of the numbers."""
        clean = [n for n, v in report["signals"].items() if v["separates_cleanly"]]
        assert report["usable_signals"] == clean

    def test_every_signal_records_what_its_best_threshold_would_cost(self, report):
        for name, v in report["signals"].items():
            assert "in_scope_wrongly_refused" in v, name
            assert "out_of_scope_max" in v, name

    def test_the_out_of_scope_probes_are_the_eval_cases(self, report):
        """One source of truth: the questions used to calibrate are the ones the eval scores, so
        a case added to the eval is automatically part of the calibration."""
        from rag.evals.run import load_cases

        cases = load_cases()
        expected = {c["id"] for c in cases if not (c.get("expect_doc") or c.get("expect_area"))}
        assert {m["id"] for m in report["measurements"]["out_of_scope"]} == expected
