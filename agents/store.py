"""Where memos and runs are kept.

Two implementations behind one interface, chosen by whether `DATABASE_URL` is set.

`PostgresMemoStore` is the durable one and the one a deployment should use. `FileMemoStore` writes
JSON to disk and is the fallback — correct locally, and **ephemeral on a container**: a free-tier
instance has no persistent disk and sleeps after fifteen minutes, so every memo written there is
lost on the next restart, silently. That was the deployed behaviour until this module gained a
second implementation, and `GET /health` now reports `store.durable` so the difference is visible
from outside rather than being something you have to know.

This is the only surface in the whole API that writes anything, and it writes memos. It cannot
touch a property, a listing or a payment, because no such concept exists in the codebase.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = ROOT / ".cache" / "memos"

MAX_MEMOS = 500


@dataclass
class StoredMemo:
    id: str
    run_id: str
    area_key: str
    memo_md: str | None
    citations: list[dict[str, Any]]
    disagreements: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    audit: dict[str, Any]
    budget: dict[str, Any]
    status: str
    provenance: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    user_id: str | None = None

    @property
    def citation_coverage(self) -> float:
        """Share of stated figures carrying a citation.

        The memo is generated one sentence per finding with a citation appended, so this is one by
        construction. It is computed rather than assumed so that a change to the generator that
        broke the property would show up here rather than silently.
        """
        stated = [f for f in self.findings if f.get("value") is not None]
        if not stated:
            return 1.0
        return min(len(self.citations) / len(stated), 1.0)

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "citation_coverage": round(self.citation_coverage, 4)}

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "area_key": self.area_key,
            "status": self.status,
            "provenance": self.provenance,
            "created_at": self.created_at,
            "citations": len(self.citations),
            "citation_coverage": round(self.citation_coverage, 4),
            "disagreements": len(self.disagreements),
            "audit_severity": self.audit.get("worst_severity"),
            "blocked": self.audit.get("blocked", False),
        }


class FileMemoStore:
    durable = False

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(os.environ.get("MEMO_STORE", str(DEFAULT_STORE)))
        self.path.mkdir(parents=True, exist_ok=True)

    def save(self, memo: StoredMemo) -> StoredMemo:
        (self.path / f"{memo.id}.json").write_text(
            json.dumps(memo.as_dict(), indent=2, default=str)
        )
        self._prune()
        return memo

    def get(self, memo_id: str) -> StoredMemo | None:
        # Reject anything that is not a plain identifier, so a path cannot be traversed.
        if not memo_id.isalnum():
            return None
        file = self.path / f"{memo_id}.json"
        if not file.exists():
            return None
        body = json.loads(file.read_text())
        body.pop("citation_coverage", None)
        return StoredMemo(**body)

    def list(self, *, limit: int = 50) -> list[StoredMemo]:
        memos = []
        for file in sorted(self.path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                body = json.loads(file.read_text())
                body.pop("citation_coverage", None)
                memos.append(StoredMemo(**body))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
            if len(memos) >= limit:
                break
        return memos

    def _prune(self) -> None:
        """Keep the store bounded; the oldest memos go first."""
        files = sorted(self.path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for stale in files[MAX_MEMOS:]:
            stale.unlink(missing_ok=True)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# The schema these tables live in.
#
# This database is shared with another project: YIELDMAP's app tables sit in their own namespace so
# that neither can collide with, shadow or accidentally drop the other's. `public` is left entirely
# alone. Overridable for a dedicated database, where `public` is a reasonable answer.
DEFAULT_SCHEMA = "yieldmap"

# Postgres identifiers are not parameterisable, so the schema name is interpolated — which means it
# has to be checked rather than trusted. It arrives from the environment, and an environment
# variable is exactly the kind of thing that ends up holding whatever someone pasted.
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def schema_name(value: str | None = None) -> str:
    name = (value if value is not None else os.environ.get("DATABASE_SCHEMA", "")).strip()
    name = name or DEFAULT_SCHEMA
    if not _SCHEMA_NAME.match(name):
        raise ValueError(
            f"{name!r} is not a usable Postgres schema name: lower-case letters, digits and "
            f"underscores, starting with a letter or underscore"
        )
    return name


SCHEMA = """
create schema if not exists {schema};
create table if not exists {schema}.memo (
    id            text primary key,
    run_id        text not null,
    area_key      text not null,
    memo_md       text,
    citations     jsonb not null default '[]'::jsonb,
    disagreements jsonb not null default '[]'::jsonb,
    findings      jsonb not null default '[]'::jsonb,
    audit         jsonb not null default '{}'::jsonb,
    budget        jsonb not null default '{}'::jsonb,
    status        text not null,
    -- REAL or SYNTHETIC, carried with the memo so a figure written from generated data still says
    -- so wherever the memo is read, including from another service.
    provenance    text not null,
    user_id       text,
    created_at    timestamptz not null default now()
);
create index if not exists memo_created_idx on {schema}.memo (created_at desc);
"""

_COLUMNS = (
    "id, run_id, area_key, memo_md, citations, disagreements, findings, "
    "audit, budget, status, provenance, user_id, created_at"
)


class PostgresMemoStore:
    """Memos in Postgres, so a restart does not lose them.

    A connection pool rather than a connection: the API is threaded, and one shared connection
    would serialise every request behind whichever one is writing.
    """

    durable = True

    def __init__(self, dsn: str, schema: str | None = None) -> None:
        from psycopg_pool import ConnectionPool

        self.dsn = dsn
        self.schema = schema_name(schema)
        # Every statement names the schema explicitly. search_path below is set as well, but a
        # transaction pooler — which is what a free-tier deployment usually gets — hands each
        # transaction a different server connection, so session state set once cannot be relied
        # on. Qualifying the name is what makes this correct under either pooler; the search_path
        # is the second line of defence.
        self.table = f"{self.schema}.memo"

        # Every pooled connection starts with the search path already pointing here, so the
        # unqualified table names in the statements below can only ever resolve inside this
        # schema. Without it a pooled connection could reach a same-named table in public — which
        # in a shared database is somebody else's.
        def configure(conn) -> None:
            # `execute` opens a transaction, and the pool requires a connection handed back to it
            # to be idle — psycopg discards one left INTRANS, so every checkout times out. Commit.
            conn.execute(f"set search_path to {self.schema}")
            conn.commit()

        self._pool = ConnectionPool(
            dsn, min_size=1, max_size=4, open=True, timeout=10, configure=configure
        )
        with self._pool.connection() as conn:
            # str.replace rather than str.format: the DDL contains '{}'::jsonb defaults, and
            # format reads those braces as placeholders.
            conn.execute(SCHEMA.replace("{schema}", self.schema))

    def close(self) -> None:
        self._pool.close()

    def save(self, memo: StoredMemo) -> StoredMemo:
        from psycopg.types.json import Json

        with self._pool.connection() as conn:
            conn.execute(
                """
                insert into {table} (id, run_id, area_key, memo_md, citations, disagreements,
                                  findings, audit, budget, status, provenance, user_id, created_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do update set
                    memo_md = excluded.memo_md,
                    status = excluded.status,
                    audit = excluded.audit
                """.replace("{table}", self.table),
                (
                    memo.id,
                    memo.run_id,
                    memo.area_key,
                    memo.memo_md,
                    Json(memo.citations),
                    Json(memo.disagreements),
                    Json(memo.findings),
                    Json(memo.audit),
                    Json(memo.budget),
                    memo.status,
                    memo.provenance,
                    memo.user_id,
                    memo.created_at,
                ),
            )
            # Bounded the same way as the file store, so a long-running deployment cannot fill a
            # free tier's disk with memos nobody will read.
            conn.execute(
                f"delete from {self.table} where id in ("  # noqa: S608 - validated identifier
                f"  select id from {self.table} order by created_at desc offset %s"
                ")",
                (MAX_MEMOS,),
            )
        return memo

    def _row(self, row: tuple[Any, ...]) -> StoredMemo:
        created = row[12]
        return StoredMemo(
            id=row[0],
            run_id=row[1],
            area_key=row[2],
            memo_md=row[3],
            citations=row[4],
            disagreements=row[5],
            findings=row[6],
            audit=row[7],
            budget=row[8],
            status=row[9],
            provenance=row[10],
            user_id=row[11],
            created_at=created.isoformat(timespec="seconds")
            if hasattr(created, "isoformat")
            else str(created),
        )

    def get(self, memo_id: str) -> StoredMemo | None:
        if not memo_id.isalnum():
            return None
        with self._pool.connection() as conn:
            row = conn.execute(
                f"select {_COLUMNS} from {self.table} where id = %s",  # noqa: S608 - fixed columns
                (memo_id,),
            ).fetchone()
        return self._row(row) if row else None

    def list(self, *, limit: int = 50) -> list[StoredMemo]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                f"select {_COLUMNS} from {self.table} order by created_at desc limit %s",  # noqa: S608
                (limit,),
            ).fetchall()
        return [self._row(r) for r in rows]


def build_store(dsn: str | None = None) -> FileMemoStore | PostgresMemoStore:
    """The durable store when one is configured, the ephemeral one otherwise.

    A bad DSN is a startup failure rather than a silent fallback: falling back would give a
    deployment that looks healthy and quietly loses every memo, which is the failure this whole
    module exists to end.
    """
    dsn = dsn if dsn is not None else os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        return FileMemoStore()
    return PostgresMemoStore(dsn)


def store_schema() -> str:
    """The schema a Postgres store would use, for /health to report without connecting."""
    return schema_name()


# The name the rest of the codebase imports. Kept so call sites read as "a memo store" rather than
# naming an implementation they should not care about.
MemoStore = FileMemoStore
