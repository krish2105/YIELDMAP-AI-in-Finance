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


class TestTheSchemaName:
    """The schema name is interpolated into DDL because Postgres identifiers cannot be bound as
    parameters, so it is validated rather than trusted. It arrives from an environment variable,
    which is exactly the kind of place that ends up holding whatever someone pasted.
    """

    def test_the_default_is_the_projects_own_schema(self):
        from agents.store import DEFAULT_SCHEMA, schema_name

        assert schema_name("") == DEFAULT_SCHEMA
        assert DEFAULT_SCHEMA != "public", (
            "the default must not be public: this database is shared with another project"
        )

    def test_an_explicit_name_is_used(self):
        from agents.store import schema_name

        assert schema_name("yieldmap_test") == "yieldmap_test"

    def test_it_reads_the_environment_when_given_nothing(self, monkeypatch):
        from agents.store import schema_name

        monkeypatch.setenv("DATABASE_SCHEMA", "somewhere_else")
        assert schema_name() == "somewhere_else"

    @pytest.mark.parametrize(
        "name",
        [
            "public; drop schema public cascade",
            'yieldmap"',
            "yield map",
            "1yieldmap",
            "Yieldmap",  # upper case would need quoting to resolve, so it is refused outright
            "a" * 64,
            "-",
        ],
    )
    def test_a_name_that_would_need_quoting_or_carries_sql_is_refused(self, name):
        from agents.store import schema_name

        with pytest.raises(ValueError):
            schema_name(name)


@pytest.mark.skipif(not DSN, reason="needs a Postgres")
class TestTheStoreStaysInsideItsSchema:
    """This database is shared with another project. The isolation is the whole reason a schema
    was chosen over a second Supabase project, so it is asserted rather than assumed.
    """

    def test_the_tables_are_created_in_the_configured_schema(self):
        from agents.store import PostgresMemoStore

        store = PostgresMemoStore(DSN, schema="yieldmap_isolation_test")
        try:
            with store._pool.connection() as conn:  # noqa: SLF001 - inspecting the fixture
                found = conn.execute(
                    "select table_schema from information_schema.tables where table_name = 'memo'"
                    " and table_schema = 'yieldmap_isolation_test'"
                ).fetchone()
            assert found is not None
        finally:
            with store._pool.connection() as conn:  # noqa: SLF001
                conn.execute("drop schema if exists yieldmap_isolation_test cascade")
            store.close()

    def test_it_does_not_read_a_same_named_table_in_public(self):
        """The failure this guards against: a pooled connection whose search_path was never set
        resolves `memo` to whatever `public.memo` happens to be — in a shared database, somebody
        else's table, and a write into it."""
        from agents.store import PostgresMemoStore, StoredMemo, new_id

        store = PostgresMemoStore(DSN, schema="yieldmap_isolation_test")
        try:
            with store._pool.connection() as conn:  # noqa: SLF001
                conn.execute("create table if not exists public.memo (id text primary key)")
                conn.execute(
                    "insert into public.memo (id) values ('a-decoy') on conflict do nothing"
                )

            store.save(
                StoredMemo(
                    id=new_id(),
                    run_id="r1",
                    area_key="marsa dubai",
                    memo_md="body",
                    citations=[],
                    disagreements=[],
                    findings=[],
                    audit={},
                    budget={},
                    status="succeeded",
                    provenance="SYNTHETIC",
                )
            )

            with store._pool.connection() as conn:  # noqa: SLF001
                decoys = conn.execute("select count(*) from public.memo").fetchone()[0]
                mine = conn.execute("select count(*) from yieldmap_isolation_test.memo").fetchone()[
                    0
                ]
            assert decoys == 1, "the store wrote into public.memo, which is not its table"
            assert mine == 1
        finally:
            with store._pool.connection() as conn:  # noqa: SLF001
                conn.execute("drop table if exists public.memo")
                conn.execute("drop schema if exists yieldmap_isolation_test cascade")
            store.close()

    def test_it_works_when_the_session_search_path_is_not_its_own(self):
        """Supabase's transaction pooler hands each transaction a different server connection, so
        session state set once at checkout cannot be relied on. Every statement names the schema,
        and this proves it by pointing search_path somewhere else entirely."""
        from agents.store import PostgresMemoStore, StoredMemo, new_id

        store = PostgresMemoStore(DSN, schema="yieldmap_isolation_test")
        try:
            with store._pool.connection() as conn:  # noqa: SLF001
                conn.execute("set search_path to pg_catalog")
                conn.commit()

            memo = StoredMemo(
                id=new_id(),
                run_id="r1",
                area_key="marsa dubai",
                memo_md="body",
                citations=[],
                disagreements=[],
                findings=[],
                audit={},
                budget={},
                status="succeeded",
                provenance="SYNTHETIC",
            )
            store.save(memo)
            assert store.get(memo.id) is not None
            assert any(m.id == memo.id for m in store.list(limit=10))
        finally:
            with store._pool.connection() as conn:  # noqa: SLF001
                conn.execute("drop schema if exists yieldmap_isolation_test cascade")
            store.close()
