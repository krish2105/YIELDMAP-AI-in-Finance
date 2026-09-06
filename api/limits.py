"""Rate limiting on the surfaces that cost something.

Without this, `POST /memos` is an unauthenticated stranger's button for running an agent crew:
model quota on a free tier that cannot be topped up, and CPU on an instance with one worker. One
script would exhaust a day's allowance in a minute, and the first anyone would know is that the
site had stopped answering.

Buckets are held in this process. A single free-tier instance is exactly one process, so that is
not an approximation today — but it would become one the moment a second instance existed, because
two processes would each grant the full allowance. The fix then is a shared counter, and
`RateLimiter` is deliberately narrow enough for that to be a swap.

A token bucket rather than a fixed window: a fixed window lets a caller spend the whole allowance
in the last second of one window and again in the first second of the next, which is the burst it
was meant to prevent.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, status

# Imported at module level, not inside `limit()`. A deferred import leaves the annotation
# unresolvable when FastAPI inspects the signature, and it silently reads `principal` as a
# query parameter — every limited route then answers 422 instead of running.
from api.auth import Principal, PrincipalDep, client_key


@dataclass(frozen=True)
class Rule:
    """`burst` requests immediately, refilling to that ceiling over `per_seconds`."""

    burst: int
    per_seconds: float

    @property
    def refill_per_second(self) -> float:
        return self.burst / self.per_seconds


# Read endpoints are cheap and public; the limit is there to stop a scraper, not a person.
READS = Rule(burst=120, per_seconds=60)
# Retrieval spends a model request per question.
ASK = Rule(burst=12, per_seconds=60)
# A crew run is the expensive one: several model requests, seconds of CPU, and a write.
MEMOS = Rule(burst=6, per_seconds=3600)
# Failed sign-ins, to make password guessing impractical without locking anyone out permanently.
AUTH = Rule(burst=10, per_seconds=900)


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, name: str, key: str, rule: Rule) -> tuple[bool, float]:
        """Spend a token. Returns (allowed, seconds until one is available)."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get((name, key))
            if bucket is None:
                bucket = _Bucket(tokens=float(rule.burst), updated=now)
                self._buckets[(name, key)] = bucket

            elapsed = now - bucket.updated
            bucket.tokens = min(float(rule.burst), bucket.tokens + elapsed * rule.refill_per_second)
            bucket.updated = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0.0

            missing = 1.0 - bucket.tokens
            return False, missing / rule.refill_per_second

    def prune(self, older_than: float = 3600.0) -> int:
        """Drop buckets nobody has touched, so a scan of many addresses cannot grow this forever."""
        cutoff = time.monotonic() - older_than
        with self._lock:
            stale = [k for k, b in self._buckets.items() if b.updated < cutoff]
            for key in stale:
                del self._buckets[key]
        return len(stale)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


limiter = RateLimiter()


@dataclass
class _PruneState:
    last: float = field(default_factory=time.monotonic)


_prune_state = _PruneState()


def enforce(name: str, rule: Rule, request: Request, principal: Principal) -> None:
    """Raise 429 if this caller has spent their allowance for `name`."""
    now = time.monotonic()
    if now - _prune_state.last > 600:
        _prune_state.last = now
        limiter.prune()

    key = client_key(request, principal)
    allowed, wait = limiter.check(name, key, rule)
    if allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"rate limit reached for {name}: {rule.burst} requests per "
            f"{int(rule.per_seconds)}s. Try again in {wait:.0f}s."
        ),
        headers={"Retry-After": str(max(1, int(wait)))},
    )


def enforce_by_address(name: str, rule: Rule, request: Request) -> tuple[bool, float]:
    """The global check, keyed on the client address alone.

    Middleware runs before dependency injection, so there is no principal to key on here. That is
    the right key anyway for the limit this serves: it exists to stop a scraper hammering the
    public read endpoints, and a scraper does not sign in. The per-route limits below key on the
    account when there is one.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    client = forwarded.split(",")[0].strip() if forwarded else ""
    if not client and request.client:
        client = request.client.host
    return limiter.check(name, f"ip:{client or 'unknown'}", rule)


def limit(name: str, rule: Rule):
    """Dependency factory applying a rule to a route."""

    def _check(request: Request, principal: PrincipalDep) -> None:
        enforce(name, rule, request, principal)

    return Depends(_check)
