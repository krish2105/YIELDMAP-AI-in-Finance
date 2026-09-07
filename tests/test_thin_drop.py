"""Every model stage on a drop too short to model.

This is not hypothetical. Dubai Pulse — which publishes the bulk history — is not answering, and
the Land Department's own portal exports a *date range* instead. So the realistic real drop is a
recent window, and three stages died on exactly that:

* `finance.index` raised, because no unit sells twice inside a short window;
* `finance.hedonic` raised, because it holds out a final year and needs history before it;
* `finance.developers` raised a TypeError formatting a median of None, having already written its
  result correctly — a cosmetic summary line.

`scripts.build_all` turns a non-zero exit into SystemExit, so any one of them took every later
stage with it and left a half-built warehouse behind a stack trace. The rule this project applies
to a thin *cell* — say "insufficient" rather than publish a number — is the same one a thin
*dataset* deserves.
"""

from __future__ import annotations

import duckdb
import polars as pl
import pytest

STAGES = ["hedonic", "index", "yields", "forecast", "risk", "developers"]


@pytest.fixture(scope="module")
def thin(tmp_path_factory):
    """Three months of sales, no unit sold twice, no project clearing the league's minimum."""
    tmp = tmp_path_factory.mktemp("thin")
    rows = [
        {
            "ts": f"2025-0{m}-1{d}",
            "area_name": "Marsa Dubai",
            "area_key": "marsa dubai",
            "price_aed": 2_000_000.0 + i * 1000,
            "building_name": f"Tower {i}",
            "project_name": f"Project {i}",
            "procedure": "Sell",
            "property_sub_type": "Flat",
            "property_type": "unit",
            "rooms": "2 B/R",
            "area_sqm": 100.0 + i,
            "is_offplan": False,
            "transaction_id": f"t{i}",
            "provenance": "SYNTHETIC",
            "price_per_sqm": 20_000.0,
        }
        for i, (m, d) in enumerate([(1, 1), (2, 2), (3, 3)])
    ]
    tx = pl.DataFrame(rows).with_columns(pl.col("ts").str.to_date())
    rent = pl.DataFrame(
        {
            "contract_id": ["E-1"],
            "start": ["2025-02-01"],
            "end": ["2026-01-31"],
            "area_name": ["Marsa Dubai"],
            "area_key": ["marsa dubai"],
            "building_name": ["Tower 0"],
            "project_name": ["Project 0"],
            "property_type": ["unit"],
            "rooms": ["2 B/R"],
            "area_sqm": [100.0],
            "annual_rent_aed": [120_000.0],
            "contract_type": ["New"],
            "provenance": ["SYNTHETIC"],
        }
    ).with_columns(pl.col("start").str.to_date(), pl.col("end").str.to_date())

    path = tmp / "thin.duckdb"
    con = duckdb.connect(str(path))
    con.register("tx", tx)
    con.register("rent", rent)
    con.execute("create table transactions as select * from tx")
    con.execute("create table rent_contracts as select * from rent")
    con.close()
    return path


@pytest.fixture(autouse=True)
def _results_in_tmp(tmp_path, monkeypatch):
    """Never let a stage write into docs/results while under test."""
    from etl import results as results_module

    monkeypatch.setattr(results_module, "RESULTS_DIR", tmp_path)


@pytest.mark.parametrize("stage", STAGES)
def test_the_stage_exits_zero_on_a_thin_drop(stage, thin):
    """Not "produces a good answer" — produces *an* answer, and does not take the build down."""
    module = __import__(f"finance.{stage}", fromlist=["main"])
    assert module.main(["--db", str(thin)]) == 0


@pytest.mark.parametrize("stage", ["hedonic", "index"])
def test_a_stage_that_cannot_model_says_so_in_its_result(stage, thin):
    """Declining has to be legible to whatever reads the result, not just to a person watching
    the terminal. `estimated: false` with a reason is what the page branches on."""
    module = __import__(f"finance.{stage}", fromlist=["run"])
    payload = module.run(thin)["payload"]
    assert payload["estimated"] is False
    assert payload["reason"]
    assert payload["note"]


@pytest.mark.parametrize("stage", ["hedonic", "index"])
def test_the_declined_payload_keeps_the_shape_of_a_successful_one(stage, thin):
    module = __import__(f"finance.{stage}", fromlist=["run"])
    payload = module.run(thin)["payload"]
    assert payload["method_id"]
    assert payload["sql"]


def test_the_whole_stage_list_is_covered():
    """A stage added later should be added here, or it is unguarded on the case that broke three."""
    from pathlib import Path

    finance = Path(__file__).resolve().parents[1] / "finance"
    with_a_db_cli = {
        p.stem
        for p in finance.glob("*.py")
        if '"--db"' in p.read_text() and "def main(" in p.read_text()
    }
    missing = with_a_db_cli - set(STAGES) - {"portfolio"}
    assert missing == set(), f"these stages take a --db and are not covered here: {missing}"
