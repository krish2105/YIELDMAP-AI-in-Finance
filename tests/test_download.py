"""Downloader tests.

Everything here runs offline. The network side is exercised on a GitHub Actions runner, whose
result is recorded in docs/results/source_probe.json; what is tested locally is the logic that
decides *what* to download and *what was* downloaded.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from etl.download import extract_resources, fetch, match_wanted, write_manifest
from etl.sources import ALL_CANDIDATES, REFERENCE_DOCS

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def ckan_payload() -> dict:
    return json.loads((FIXTURES / "ckan_package_search.json").read_text())


class TestCatalogueParsing:
    def test_pulls_every_resource_that_has_a_url(self, ckan_payload):
        res = extract_resources(ckan_payload)
        assert len(res) == 3  # the fourth has no url and is dropped
        assert all(r["url"] for r in res)

    def test_carries_dataset_identity_onto_each_resource(self, ckan_payload):
        res = extract_resources(ckan_payload)
        by_name = {r["resource_id"]: r for r in res}
        assert by_name["res-1"]["dataset_id"] == "dld_transactions"
        assert by_name["res-3"]["dataset_title"] == "DLD Rent Contracts (Ejari)"

    def test_normalises_format_case(self, ckan_payload):
        formats = {r["format"] for r in extract_resources(ckan_payload)}
        assert formats == {"CSV", "PDF"}

    def test_tags_resources_against_the_datasets_we_want(self, ckan_payload):
        res = {r["resource_id"]: r for r in extract_resources(ckan_payload)}
        assert "transactions" in res["res-1"]["matches"]
        assert "rent_contracts" in res["res-3"]["matches"]

    def test_handles_package_show_shape(self, ckan_payload):
        """package_show returns a single package, not a results list."""
        single = {"result": ckan_payload["result"]["results"][0]}
        assert len(extract_resources(single)) == 2

    def test_handles_an_empty_or_odd_payload_without_raising(self):
        assert extract_resources({}) == []
        assert extract_resources({"result": None}) == []
        assert extract_resources({"result": {"count": 0, "results": []}}) == []


class TestWantedMatching:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("dld_transactions Transactions CSV", "transactions"),
            ("Ejari rent contracts", "rent_contracts"),
            ("DLD Valuation records", "valuation"),
            ("Buildings register", "buildings"),
        ],
    )
    def test_matches_expected_dataset(self, text, expected):
        assert expected in match_wanted(text)

    def test_returns_nothing_for_an_unrelated_dataset(self):
        assert match_wanted("Dubai bus timetable") == []


class TestCandidates:
    def test_every_candidate_is_https(self):
        for cand in (*ALL_CANDIDATES, *REFERENCE_DOCS):
            assert cand.url.startswith("https://"), cand.key

    def test_candidate_keys_are_unique(self):
        keys = [c.key for c in (*ALL_CANDIDATES, *REFERENCE_DOCS)]
        assert len(keys) == len(set(keys))

    def test_a_catalogue_endpoint_is_tried_before_guessing_filenames(self):
        assert any(c.kind == "catalogue" for c in ALL_CANDIDATES)


class TestFetchManifest:
    def test_records_hash_and_size_so_a_download_is_checkable(self, tmp_path, monkeypatch):
        body = b"area_name_en,price_aed\nJVC,1250000\n" * 50
        dest = tmp_path / "sample.csv"

        class _Resp:
            headers = {"content-type": "text/csv"}

            def raise_for_status(self):
                return None

            def iter_bytes(self, chunk_size=0):
                yield body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class _Client:
            def stream(self, method, url):
                return _Resp()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr("etl.download._client", lambda: _Client())
        entry = fetch("https://example.invalid/sample.csv", dest)

        assert dest.read_bytes() == body
        assert entry["bytes"] == len(body)
        assert entry["sha256"] == hashlib.sha256(body).hexdigest()
        assert entry["truncated"] is False
        assert entry["retrieved_at"].endswith("+00:00")

    def test_manifest_is_written_as_readable_json(self, tmp_path):
        out = tmp_path / "manifest.json"
        write_manifest([{"url": "u", "sha256": "abc", "bytes": 1}], out)
        loaded = json.loads(out.read_text())
        assert loaded["files"][0]["sha256"] == "abc"
        assert "generated_at" in loaded
