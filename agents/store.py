"""Where memos and runs are kept.

A file-backed store rather than Postgres, for the same reason the analytics live in DuckDB: the
deployment target is a free tier, and a memo is a small document. The interface is narrow enough
that moving it behind the Supabase schema later is a swap rather than a rewrite.

This is the only surface in the whole API that writes anything, and it writes memos. It cannot
touch a property, a listing or a payment, because no such concept exists in the codebase.
"""

from __future__ import annotations

import json
import os
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


class MemoStore:
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
