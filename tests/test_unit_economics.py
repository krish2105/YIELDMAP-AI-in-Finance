"""Unit-economics tests.

This module produces the only figures in the project that are about the project rather than about
Dubai property: what a unit of work costs and where the free tiers stop. Those numbers appear in
docs/limits.md and on the site, so they fall under the same rule as every other number — they have
to be reproducible, and the published copy has to be the one the code still computes.

It had no tests at all, which is how the one module that makes the "this costs nothing" claim was
also the one nothing checked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from finance.unit_economics import OPERATIONS, TIERS, Usage, capacity, headroom, report

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "docs" / "results" / "unit_economics.json"
LIMITS_DOC = ROOT / "docs" / "limits.md"


@pytest.fixture(scope="module")
def published() -> dict:
    return json.loads(PUBLISHED.read_text())


class TestADaysWork:
    def test_requests_are_the_sum_of_what_each_operation_spends(self) -> None:
        usage = Usage(asks=10, memos=2, pages=100)
        assert usage.model_requests() == 10 * 1 + 2 * 6
        assert usage.embedding_requests() == 10 * 1 + 2 * 2

    def test_serving_pages_spends_no_model_quota(self) -> None:
        """The site is a SQL front end. Reading it must never touch a provider allowance."""
        usage = Usage(pages=50_000)
        assert usage.model_requests() == 0
        assert usage.embedding_requests() == 0
        assert usage.cpu_seconds() > 0

    def test_cpu_seconds_count_every_operation_including_pages(self) -> None:
        usage = Usage(asks=1, memos=1, pages=2)
        assert usage.cpu_seconds() == pytest.approx(0.8 + 4.5 + 2 * 0.15)


class TestWhichTierBindsFirst:
    """The useful output is not the cost — it is which allowance runs out first."""

    def test_the_binding_constraint_is_the_tier_with_the_largest_share(self) -> None:
        # A day of nothing but questions spends one generation and one embedding request each,
        # against allowances of 1500 and 1000. The smaller allowance binds.
        result = headroom(Usage(asks=900))
        assert result["binding_constraint"] == "Gemini embeddings"
        shares = {r["tier"]: r["share_of_free_tier"] for r in result["tiers"]}
        assert shares["Gemini embeddings"] > shares["Gemini 2.5 Flash (generation)"]

    def test_memos_shift_the_binding_constraint_to_generation(self) -> None:
        """A crew run spends six generation requests to two embeddings, so memo-heavy days flip
        which tier is scarce. If this ever stopped being true the advice about what to cache
        first would be wrong."""
        assert headroom(Usage(memos=200))["binding_constraint"] == "Gemini 2.5 Flash (generation)"

    def test_a_day_inside_every_allowance_exhausts_nothing(self) -> None:
        rows = headroom(Usage(asks=20, memos=3, pages=200))["tiers"]
        assert all(r["exhausted"] is False for r in rows)
        assert all(r["share_of_free_tier"] < 1 for r in rows)

    def test_exhaustion_is_flagged_only_once_the_allowance_is_passed(self) -> None:
        embedding = next(t for t in TIERS if t.name.startswith("Gemini embeddings"))
        limit = int(embedding.free_per_day)

        at_the_limit = {r["tier"]: r for r in headroom(Usage(asks=limit))["tiers"]}
        assert at_the_limit["Gemini embeddings"]["exhausted"] is False

        one_over = {r["tier"]: r for r in headroom(Usage(asks=limit + 1))["tiers"]}
        assert one_over["Gemini embeddings"]["exhausted"] is True


class TestCapacity:
    def test_an_operation_is_capped_by_its_tighter_allowance(self) -> None:
        """A question costs one of each. 1500 generations and 1000 embeddings means 1000
        questions, not 1500 — taking the looser limit would overstate capacity by half."""
        assert capacity()["ask"]["per_day_on_the_free_tier"] == 1000

    def test_a_memo_is_capped_by_generation_requests(self) -> None:
        # 1500 // 6 = 250 generation-bound; 1000 // 2 = 500 embedding-bound.
        assert capacity()["memo"]["per_day_on_the_free_tier"] == 250

    def test_an_operation_that_spends_no_quota_reports_no_ceiling_and_says_why(self) -> None:
        page = capacity()["page"]
        assert page["per_day_on_the_free_tier"] is None
        assert "rate limiter" in page["note"]


class TestTheReport:
    def test_it_declares_real_provenance(self) -> None:
        """The guard reads this field. A result that declares nothing is treated as generated,
        and this one is real: it describes this system, not the property data."""
        assert report()["provenance"] == "REAL"

    def test_the_monthly_cost_is_zero(self) -> None:
        """The project's central claim, asserted rather than written down."""
        assert report()["monthly_cost_usd"] == 0.0

    def test_every_tier_carries_a_note_saying_what_happens_when_it_runs_out(self) -> None:
        for tier in report()["tiers"]:
            assert tier["note"].strip(), tier["name"]

    def test_the_vercel_terms_limit_is_stated_rather_than_buried(self) -> None:
        """Hobby prohibits commercial use. That is the one tier note whose absence would be a
        misrepresentation rather than an omission, so it is checked."""
        vercel = next(t for t in report()["tiers"] if t["name"].startswith("Vercel"))
        assert "COMMERCIAL" in vercel["note"].upper()

    def test_a_ledger_reading_is_carried_through_when_one_is_supplied(self) -> None:
        assert report({"gemini": 4})["observed"] == {"gemini": 4}

    def test_scenarios_span_from_inside_the_free_tier_to_past_it(self) -> None:
        """Three shapes of day locate the cliff. If they all sat on one side of it, the report
        would describe the cost without finding the limit, which is the part worth knowing."""
        scenarios = report()["scenarios"]
        worst = {
            name: max(t["share_of_free_tier"] for t in s["tiers"]) for name, s in scenarios.items()
        }
        assert min(worst.values()) < 1.0
        assert max(worst.values()) > 1.0


class TestThePublishedFiguresAreTheOnesTheCodeComputes:
    """docs/limits.md and the site quote this file. Same rule as the red-team results: a committed
    number that the code no longer produces is a claim, not a measurement."""

    def test_the_file_is_committed(self, published: dict) -> None:
        assert published["provenance"] == "REAL"

    def test_the_operation_costs_still_match(self, published: dict) -> None:
        assert published["operations"] == OPERATIONS

    def test_the_capacity_figures_still_match(self, published: dict) -> None:
        assert published["capacity_per_day"] == capacity()

    def test_every_scenario_still_reaches_the_same_verdict(self, published: dict) -> None:
        fresh = report()["scenarios"]
        assert set(published["scenarios"]) == set(fresh)
        for name, was in published["scenarios"].items():
            now = fresh[name]
            assert was["model_requests"] == now["model_requests"], name
            assert was["embedding_requests"] == now["embedding_requests"], name
            assert was["binding_constraint"] == now["binding_constraint"], name
            assert was["tiers"] == now["tiers"], name

    def test_the_cliff_is_where_the_documentation_says_it_is(self, published: dict) -> None:
        """docs/limits.md states that a hundred daily users is the point the free tier stops, at
        104% of the embedding allowance. That sentence is checked against the number here."""
        cliff = published["scenarios"]["a hundred daily users"]
        assert cliff["binding_constraint"] == "Gemini embeddings"
        embeddings = next(t for t in cliff["tiers"] if t["tier"] == "Gemini embeddings")
        assert embeddings["share_of_free_tier"] == pytest.approx(1.04, abs=0.005)
        assert embeddings["exhausted"] is True


class TestTheDocumentationQuotesTheComputation:
    """docs/limits.md prints a table of these figures in prose. Rule 3 says a number shown anywhere
    traces to a computation, and a markdown table is the easiest place for that to quietly stop
    being true — nothing breaks when the code changes and the sentence does not."""

    ROW = re.compile(
        r"^\|\s*\**([^|—]+?)\**\s*—[^|]*\|\s*\**([\d,]+)\**\s*\|\s*\**([\d.]+)%\**\s*\|"
        r"\s*\**(\w+)\**\s*\|",
        re.MULTILINE,
    )

    # The table names each day the way a reader would; the report keys it the way the code does.
    NAMES = {
        "A demo day": "a demo day",
        "A busy course week, per day": "a busy course week, per day",
        "A hundred daily users": "a hundred daily users",
    }

    @staticmethod
    def _rows() -> dict[str, tuple[int, float, str]]:
        found = {}
        for label, requests, share, binds in TestTheDocumentationQuotesTheComputation.ROW.findall(
            LIMITS_DOC.read_text()
        ):
            found[label.strip()] = (int(requests.replace(",", "")), float(share), binds.strip())
        return found

    def test_the_table_is_still_where_this_test_looks(self) -> None:
        assert set(self._rows()) == set(self.NAMES), (
            "the free-tier table in docs/limits.md no longer parses; this test is now vacuous"
        )

    def test_every_row_matches_what_the_code_computes(self) -> None:
        scenarios = report()["scenarios"]
        for label, (requests, share, binds) in self._rows().items():
            computed = scenarios[self.NAMES[label]]
            assert requests == computed["model_requests"], label
            worst = max(t["share_of_free_tier"] for t in computed["tiers"])
            assert share == pytest.approx(worst * 100, abs=0.1), label
            assert binds in computed["binding_constraint"].lower(), label


class TestTheCommandThatWritesTheFile:
    def test_it_writes_a_readable_report_where_it_is_told_to(self, tmp_path) -> None:
        from finance.unit_economics import main

        out = tmp_path / "nested" / "unit_economics.json"
        assert main(["--out", str(out)]) == 0

        body = json.loads(out.read_text())
        assert body["provenance"] == "REAL"
        assert body["scenarios"]["a hundred daily users"]["binding_constraint"]

    def test_it_reads_the_quota_ledger_when_one_exists(self, tmp_path, monkeypatch) -> None:
        """The report carries what the ledger actually recorded, so the model of what this costs
        can be checked against what it spent rather than only asserted."""
        import finance.unit_economics as ue

        cache = tmp_path / ".cache"
        cache.mkdir()
        (cache / "quota.json").write_text(json.dumps({"gemini": {"requests": 12}}))
        monkeypatch.setattr(ue, "ROOT", tmp_path)

        out = tmp_path / "report.json"
        ue.main(["--out", str(out)])
        assert json.loads(out.read_text())["observed"] == {"gemini": {"requests": 12}}

    def test_an_unreadable_ledger_does_not_stop_the_report(self, tmp_path, monkeypatch) -> None:
        import finance.unit_economics as ue

        cache = tmp_path / ".cache"
        cache.mkdir()
        (cache / "quota.json").write_text("{not json")
        monkeypatch.setattr(ue, "ROOT", tmp_path)

        out = tmp_path / "report.json"
        assert ue.main(["--out", str(out)]) == 0
        assert json.loads(out.read_text())["observed"] is None
