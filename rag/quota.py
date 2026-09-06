"""Request-count budgets.

Quotas on the free tiers this project uses are counted in requests, not tokens, so that is what is
counted here. The ledger is durable across processes because a nightly job and an interactive
session share the same daily allowance, and a counter that resets when a process restarts would
let the same allowance be spent twice.

Exceeding a budget is never an exception that reaches a user. Every caller degrades: the retriever
falls back to lexical search, the reranker falls back to lexical ordering, and Ask says plainly
that it is answering without a model rather than pretending otherwise.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = ROOT / ".cache" / "quota.json"


class QuotaExceeded(RuntimeError):
    """Raised inside the provider chain so it can move to the next tier, never surfaced raw."""


@dataclass
class QuotaLedger:
    """A durable count of requests made per backend per day."""

    path: Path = DEFAULT_LEDGER
    daily_limit: int = field(
        default_factory=lambda: int(os.environ.get("LLM_MAX_REQUESTS_PER_DAY", "1000"))
    )
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            # A corrupt ledger must not stop the application; it starts a fresh day's count.
            return {}

    def _write(self, body: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, indent=2))
        tmp.replace(self.path)

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    def used(self, backend: str, *, day: str | None = None) -> int:
        return int(self._read().get(day or self._today(), {}).get(backend, 0))

    def remaining(self, backend: str) -> int:
        return max(self.daily_limit - self.used(backend), 0)

    def would_exceed(self, backend: str, *, cost: int = 1) -> bool:
        return self.used(backend) + cost > self.daily_limit

    def record(self, backend: str, *, cost: int = 1, kind: str = "generate") -> int:
        """Count a request. Returns the new total for that backend today."""
        with self._lock:
            body = self._read()
            today = self._today()
            day = body.setdefault(today, {})
            total = int(day.get(backend, 0)) + cost
            day[backend] = total
            day.setdefault("_by_kind", {})
            day["_by_kind"][f"{backend}:{kind}"] = (
                int(day["_by_kind"].get(f"{backend}:{kind}", 0)) + cost
            )
            body["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            # Keep a fortnight so the /data page can chart usage without the file growing forever.
            for stale in sorted(k for k in body if k.count("-") == 2)[:-14]:
                body.pop(stale, None)
            self._write(body)
            return total

    def spend(self, backend: str, *, cost: int = 1, kind: str = "generate") -> None:
        """Record a request, refusing when it would breach the day's allowance."""
        if self.would_exceed(backend, cost=cost):
            raise QuotaExceeded(f"{backend} has used its {self.daily_limit} requests for today")
        self.record(backend, cost=cost, kind=kind)

    def report(self) -> dict[str, Any]:
        """Usage per backend per day, for the data page and the cost claim in the report."""
        body = self._read()
        days = {k: v for k, v in body.items() if k.count("-") == 2}
        return {
            "daily_limit": self.daily_limit,
            "today": days.get(self._today(), {}),
            "history": days,
            "spend_aed": 0.0,
            "note": "Every backend in the chain is a free tier. Cost is zero by construction.",
        }
