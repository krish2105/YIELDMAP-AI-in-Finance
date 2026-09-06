"""The KPI contract is the mechanism behind Rule 3, so it gets tested first."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.kpi import Kpi, confidence_for, make_kpi, sql_hash

ROOT = Path(__file__).resolve().parent.parent


def _kpi(**over):
    args = {
        "id": "net_yield.jvc.apartment.1br",
        "label": "Net yield",
        "value": 6.42,
        "unit": "%",
        "format": "percent",
        "n": 1284,
        "asof": date(2026, 9, 1),
        "method_id": "net_yield_v1",
        "sql": "select median(gross_yield) from yield_point where area_id = ?",
        "cv": 0.2,
    }
    args.update(over)
    return make_kpi(**args)


class TestConfidence:
    def test_suppresses_small_samples(self):
        assert confidence_for(4, 0.1) == "insufficient"
        assert confidence_for(0, 0.0) == "insufficient"

    def test_large_tight_sample_is_high(self):
        assert confidence_for(120, 0.2) == "high"

    def test_large_but_dispersed_sample_is_demoted(self):
        assert confidence_for(120, 0.9) == "low"

    def test_mid_sample_is_medium(self):
        assert confidence_for(15, 0.5) == "medium"

    def test_unknown_dispersion_judges_on_n_alone(self):
        assert confidence_for(50, None) == "high"
        assert confidence_for(6, None) == "low"

    def test_monotone_in_n(self):
        rank = {"insufficient": 0, "low": 1, "medium": 2, "high": 3}
        ranks = [rank[confidence_for(n, 0.3)] for n in (1, 5, 10, 30, 100)]
        assert ranks == sorted(ranks)

    def test_thresholds_are_shared_with_the_web_layer(self):
        """One file drives both languages, so the UI and API cannot disagree."""
        shared = json.loads((ROOT / "config" / "kpi_thresholds.json").read_text())
        ts = (ROOT / "web" / "lib" / "kpi.ts").read_text()
        assert 'from "../../config/kpi_thresholds.json"' in ts
        assert {"min_n", "high", "medium"} <= set(shared)


class TestKpiConstruction:
    def test_carries_its_own_sql_and_hash(self):
        k = _kpi()
        assert k.sql_hash == sql_hash(k.sql)
        assert len(k.sql_hash) == 16

    def test_a_kpi_cannot_exist_without_sql(self):
        """Rule 3 is enforced by the type, not by discipline."""
        with pytest.raises(ValidationError, match="Rule 3"):
            Kpi(
                id="x",
                label="x",
                value=1.0,
                unit="%",
                format="percent",
                n=10,
                asof=date(2026, 1, 1),
                method_id="m",
                sql="   ",
            )

    def test_hash_ignores_whitespace_but_not_content(self):
        assert sql_hash("select  1") == sql_hash("select 1")
        assert sql_hash("select 1") != sql_hash("select 2")

    def test_thin_sample_blanks_the_value_before_it_leaves_the_api(self):
        k = _kpi(n=3)
        assert k.value is None
        assert k.confidence == "insufficient"
        assert k.suppressed

    def test_non_finite_values_become_null(self):
        assert _kpi(value=float("inf")).value is None
        assert _kpi(value=float("nan")).value is None

    def test_defaults_to_a_sql_source_naming_the_method(self):
        assert _kpi().sources[0].kind == "sql"
        assert _kpi().sources[0].ref == "net_yield_v1"

    def test_synthetic_provenance_is_visible(self):
        assert _kpi(provenance="SYNTHETIC").synthetic is True
        assert _kpi().synthetic is False
