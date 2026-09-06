"""Memo storage.

Both implementations are held to the same contract, so switching between them cannot change
behaviour. The Postgres tests run against a real Postgres — a service container in CI — and skip
when there isn't one, because a mocked database proves the mock works.
"""

from __future__ import annotations

import os

import pytest

from agents.store import FileMemoStore, StoredMemo, build_store, new_id

DSN = os.environ.get("TEST_DATABASE_URL", "").strip()


def a_memo(**overrides) -> StoredMemo:
    body = {
        "id": new_id(),
        "run_id": "run-1",
        "area_key": "dubai-marina",
        "memo_md": "Median price per square metre was 14,200 AED [1].",
        "citations": [{"n": 1, "title": "median price", "source": "sql"}],
        "disagreements": [],
        "findings": [{"label": "median price", "value": 14200.0}],
        "audit": {"blocked": False, "worst_severity": "info"},
        "budget": {"requests_used": 3},
        "status": "succeeded",
        "provenance": "SYNTHETIC",
    }
    body.update(overrides)
    return StoredMemo(**body)


@pytest.fixture
def file_store(tmp_path) -> FileMemoStore:
    return FileMemoStore(tmp_path / "memos")


@pytest.fixture
def pg_store():
    if not DSN:
        pytest.skip("TEST_DATABASE_URL is not set; the Postgres path runs in CI")
    from agents.store import PostgresMemoStore

    store = PostgresMemoStore(DSN)
    with store._pool.connection() as conn:  # noqa: SLF001 - test fixture housekeeping
        conn.execute("truncate table memo")
    yield store
    store.close()


@pytest.fixture(params=["file_store", "pg_store"])
def store(request):
    return request.getfixturevalue(request.param)


class TestTheContractBothStoresMeet:
    def test_a_saved_memo_comes_back_whole(self, store) -> None:
        memo = a_memo()
        store.save(memo)
        loaded = store.get(memo.id)
        assert loaded is not None
        assert loaded.memo_md == memo.memo_md
        assert loaded.citations == memo.citations
        assert loaded.findings == memo.findings
        assert loaded.status == "succeeded"

    def test_provenance_travels_with_the_memo(self, store) -> None:
        """A memo written from generated data must still say so wherever it is read."""
        store.save(a_memo(provenance="SYNTHETIC"))
        assert store.list(limit=1)[0].provenance == "SYNTHETIC"

    def test_listing_is_newest_first(self, store) -> None:
        older = a_memo(created_at="2026-01-01T00:00:00+00:00")
        newer = a_memo(created_at="2026-06-01T00:00:00+00:00")
        store.save(older)
        store.save(newer)
        assert [m.id for m in store.list(limit=2)] == [newer.id, older.id]

    def test_an_unknown_id_is_none_not_an_error(self, store) -> None:
        assert store.get("deadbeefcafe") is None

    @pytest.mark.parametrize("bad", ["../secrets", "a/b", "..", "a-b", ""])
    def test_a_path_shaped_id_is_refused(self, store, bad: str) -> None:
        """The id reaches a filesystem path in one implementation and a query in the other."""
        assert store.get(bad) is None

    def test_saving_the_same_id_twice_updates_rather_than_duplicates(self, store) -> None:
        memo = a_memo()
        store.save(memo)
        memo.status = "blocked"
        memo.memo_md = None
        store.save(memo)
        assert len(store.list(limit=10)) == 1
        assert store.get(memo.id).status == "blocked"


class TestDurabilityIsDeclared:
    def test_the_file_store_admits_it_is_not_durable(self, file_store) -> None:
        assert file_store.durable is False

    def test_no_database_url_gives_the_file_store(self) -> None:
        assert isinstance(build_store(""), FileMemoStore)

    @pytest.mark.skipif(not DSN, reason="needs a Postgres")
    def test_a_database_url_gives_the_durable_store(self) -> None:
        store = build_store(DSN)
        try:
            assert store.durable is True
        finally:
            store.close()

    def test_a_broken_dsn_fails_loudly_rather_than_falling_back(self) -> None:
        """A silent fallback is a deployment that looks healthy and loses every memo."""
        with pytest.raises(Exception, match=r".*"):
            build_store("postgresql://nobody@127.0.0.1:1/nothing")
