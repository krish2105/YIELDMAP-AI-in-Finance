"""Coverage-gate tests.

A gate that cannot fail is decoration. These check each way it is meant to refuse, including the
one that is easy to get wrong: a rule-enforcing module that disappears from the report entirely,
which reads as a pass to anything that only compares numbers it found.
"""

from __future__ import annotations

import json

import pytest

from scripts.coverage_gate import CRITICAL, CRITICAL_FLOOR, OVERALL_FLOOR, main, summarise


def _report(overall: float = 90.0, **modules: float) -> dict:
    """A coverage report in the shape pytest-cov's JSON writer produces."""
    files = {}
    for path in CRITICAL:
        percent = modules.get(path.replace("/", "_").replace(".py", ""), 95.0)
        files[path] = {
            "summary": {"percent_covered": percent, "num_statements": 100},
            "missing_lines": list(range(int(100 - percent))),
        }
    return {
        "files": files,
        "totals": {"percent_covered": overall, "num_statements": 1000, "missing_lines": 100},
    }


class TestTheFloors:
    def test_a_healthy_report_passes(self):
        assert summarise(_report())["failures"] == []

    def test_overall_coverage_below_the_floor_fails(self):
        failures = summarise(_report(overall=OVERALL_FLOOR - 0.1))["failures"]
        assert any("overall coverage" in f for f in failures)

    def test_a_rule_enforcing_module_below_its_higher_floor_fails(self):
        failures = summarise(_report(api_auth=CRITICAL_FLOOR - 1))["failures"]
        assert any("api/auth.py" in f for f in failures)

    def test_the_failure_names_the_rule_the_module_enforces(self):
        """Whoever sees this in a CI log needs to know what stopped being guarded, not only that
        a percentage moved."""
        failures = summarise(_report(api_auth=10.0))["failures"]
        assert any("asserted by the server" in f for f in failures)

    def test_the_higher_floor_is_higher(self):
        assert CRITICAL_FLOOR > OVERALL_FLOOR

    def test_a_critical_module_exactly_at_its_floor_passes(self):
        assert summarise(_report(api_auth=CRITICAL_FLOOR))["failures"] == []


class TestAModuleThatVanishes:
    """The failure mode this gate exists to avoid: a rename leaves a rule unguarded, and every
    check that iterates over what it found still passes."""

    def test_a_missing_critical_module_is_a_failure_not_a_pass(self):
        report = _report()
        del report["files"]["api/auth.py"]
        failures = summarise(report)["failures"]
        assert any("api/auth.py" in f and "not measured" in f for f in failures)

    def test_it_is_still_a_failure_when_everything_else_is_perfect(self):
        report = _report(overall=100.0)
        del report["files"]["rag/quota.py"]
        assert summarise(report)["failures"]


class TestTheCriticalListIsHonest:
    def test_every_named_module_exists(self):
        from scripts.coverage_gate import ROOT

        for path in CRITICAL:
            assert (ROOT / path).exists(), f"{path} is on the critical list but not in the tree"

    def test_every_entry_says_which_rule_it_enforces(self):
        for path, rule in CRITICAL.items():
            assert len(rule) > 20, path


class TestTheCommand:
    def test_it_writes_a_report_and_returns_zero_when_the_floors_hold(self, tmp_path):
        coverage = tmp_path / "coverage.json"
        coverage.write_text(json.dumps(_report()))
        out = tmp_path / "coverage_result.json"

        assert main(["--coverage", str(coverage), "--out", str(out), "--gate"]) == 0
        assert json.loads(out.read_text())["provenance"] == "REAL"

    def test_it_returns_non_zero_when_gating_on_a_breach(self, tmp_path):
        coverage = tmp_path / "coverage.json"
        coverage.write_text(json.dumps(_report(overall=10.0)))
        assert main(["--coverage", str(coverage), "--out", str(tmp_path / "r.json"), "--gate"]) == 1

    def test_without_the_gate_flag_it_reports_without_failing(self, tmp_path):
        """Publishing the measurement and enforcing it are separate: a local run should be able to
        see the numbers without being stopped by them."""
        coverage = tmp_path / "coverage.json"
        coverage.write_text(json.dumps(_report(overall=10.0)))
        out = tmp_path / "r.json"
        assert main(["--coverage", str(coverage), "--out", str(out)]) == 0
        assert json.loads(out.read_text())["failures"]

    def test_a_missing_coverage_report_is_an_error_rather_than_a_silent_pass(self, tmp_path):
        assert main(["--coverage", str(tmp_path / "absent.json"), "--gate"]) == 1


class TestThePublishedFigure:
    def test_the_committed_report_declares_real_provenance_and_no_failures(self):
        """docs/results/coverage.json is read by the README. It must be a passing measurement."""
        from scripts.coverage_gate import ROOT

        path = ROOT / "docs" / "results" / "coverage.json"
        if not path.exists():
            pytest.skip("coverage has not been measured in this checkout")
        body = json.loads(path.read_text())
        assert body["provenance"] == "REAL"
        assert body["failures"] == []
        assert body["overall_percent"] >= body["overall_floor"]


class TestDriftFromThePublishedFigure:
    """The committed figure is what the README quotes. It is allowed to lag the current run
    slightly — CI runs a Postgres suite a laptop skips — but not to become a different claim."""

    def test_a_small_difference_is_tolerated(self, tmp_path):
        from scripts.coverage_gate import PUBLISHED_TOLERANCE, compare_to_published

        published = tmp_path / "coverage.json"
        published.write_text(json.dumps({"overall_percent": 80.0}))
        fresh = {"overall_percent": 80.0 + PUBLISHED_TOLERANCE - 0.1}
        assert compare_to_published(fresh, published) == []

    def test_a_large_drift_is_reported_in_either_direction(self, tmp_path):
        from scripts.coverage_gate import PUBLISHED_TOLERANCE, compare_to_published

        published = tmp_path / "coverage.json"
        published.write_text(json.dumps({"overall_percent": 80.0}))
        for fresh_value in (80.0 + PUBLISHED_TOLERANCE + 1, 80.0 - PUBLISHED_TOLERANCE - 1):
            failures = compare_to_published({"overall_percent": fresh_value}, published)
            assert failures and "drift" in failures[0]

    def test_a_missing_published_file_is_reported(self, tmp_path):
        from scripts.coverage_gate import compare_to_published

        assert compare_to_published({"overall_percent": 80.0}, tmp_path / "absent.json")

    def test_an_unreadable_published_file_is_reported_rather_than_raised(self, tmp_path):
        from scripts.coverage_gate import compare_to_published

        published = tmp_path / "coverage.json"
        published.write_text("{not json")
        failures = compare_to_published({"overall_percent": 80.0}, published)
        assert failures and "not readable" in failures[0]

    def test_the_comparison_reads_the_committed_file_before_overwriting_it(self, tmp_path):
        """The command writes its report to the same path it compares against. If it wrote first
        the check would compare the run to itself and never fail."""
        out = tmp_path / "coverage_result.json"
        out.write_text(json.dumps({"provenance": "REAL", "overall_percent": 10.0}))
        coverage = tmp_path / "coverage.json"
        coverage.write_text(json.dumps(_report(overall=90.0)))

        code = main(
            ["--coverage", str(coverage), "--out", str(out), "--gate", "--compare-published"]
        )
        assert code == 1
        assert json.loads(out.read_text())["overall_percent"] == 90.0
