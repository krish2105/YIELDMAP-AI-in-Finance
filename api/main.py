"""The YIELDMAP API.

A read-only analytics service. It has no endpoint that buys, sells, lists or finances anything, and
it never will: the boundary is architectural rather than a matter of policy, because the only
write-capable surface is the memo store.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agents.store import store_schema
from api import auth as auth_module
from api.limits import READS, enforce_by_address
from api.observability import RequestLogMiddleware, configure_logging, configure_sentry
from api.routes import ask, auth, market, memos, simulate
from rag.provider import LLMProvider

VERSION = "0.1.0"

NOT_ADVICE = (
    "YIELDMAP explains, compares and simulates using published Dubai Land Department data. It is "
    "information, not financial advice, and it cannot execute a transaction of any kind."
)


def _origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _llm_state() -> tuple[list[str], str | None]:
    """The chain as configured, and the first backend in it that could answer right now.

    Never raises: an unreachable provider is a degraded service, not a failed start, and a
    deployment that cannot report its own configuration is worse than one running degraded.
    """
    try:
        provider = LLMProvider.from_env()
        chain = list(provider.chain)
        answering = next((b["backend"] for b in provider.describe() if b["available"]), None)
    except Exception:  # pragma: no cover - defensive; from_env does not raise today
        return [], None
    return chain, answering


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure observability, then refuse to start if the deployment is unsafe.

    The check is a startup failure rather than a warning when YIELDMAP_ENV=production, because the
    unsafe states are silent ones: an unset AUTH_SECRET means every restart invalidates every
    token, and an empty user directory means the write endpoints are unreachable. Both look like
    a working service until someone tries to use it.
    """
    log = configure_logging()
    sentry = configure_sentry()

    problems = auth_module.require_configured()
    production = os.environ.get("YIELDMAP_ENV", "development").lower() == "production"
    if problems and production:
        for problem in problems:
            log.error("refusing to start", extra={"context": {"problem": problem}})
        raise RuntimeError("; ".join(problems))
    for problem in problems:
        log.warning("authentication is not configured", extra={"context": {"problem": problem}})

    # Backend names only, never a key. Setting GEMINI_API_KEY without also setting LLM_PROVIDER
    # leaves the chain pinned to the offline backend, and the only symptom is that answers stay
    # fixture text. The deploy log is where that has to be visible, because it is readable when
    # the service itself is not.
    chain, answering = _llm_state()
    log.info(
        "started",
        extra={
            "context": {
                "version": VERSION,
                "sentry": sentry,
                "auth_configured": auth_module.is_configured(),
                "durable_store": bool(os.environ.get("DATABASE_URL")),
                "llm_chain": chain,
                "llm_answering": answering,
            }
        },
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="YIELDMAP",
        version=VERSION,
        description=NOT_ADVICE,
        lifespan=lifespan,
    )

    # Outermost, so a request is logged and carries an id even when something below it throws.
    app.add_middleware(RequestLogMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins(),
        # Credentials are deliberately not allowed: the API holds no session, so permitting them
        # would widen the surface for nothing.
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        max_age=600,
    )

    @app.middleware("http")
    async def global_rate_limit(request: Request, call_next):
        """A ceiling on every request from one address.

        Deliberately generous: it is here to stop a scraper, not a person. The endpoints that
        actually cost something carry their own, much tighter, limits on top of this one.
        """
        if request.method == "OPTIONS" or request.url.path in {"/health", "/"}:
            return await call_next(request)
        allowed, wait = enforce_by_address("global", READS, request)
        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": (
                        f"rate limit reached: {READS.burst} requests per "
                        f"{int(READS.per_seconds)}s from one address."
                    )
                },
                headers={"Retry-After": str(max(1, int(wait)))},
            )
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        # The API serves JSON only, so nothing it returns should ever be treated as a page.
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response

    @app.exception_handler(FileNotFoundError)
    async def missing_database(_: Request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": str(exc)},
        )

    app.include_router(auth.router)
    app.include_router(market.router)
    app.include_router(simulate.router)
    app.include_router(ask.router)
    app.include_router(memos.router)

    @app.get("/", tags=["meta"])
    def root() -> dict[str, Any]:
        return {
            "service": "YIELDMAP",
            "version": VERSION,
            "notice": NOT_ADVICE,
            "docs": "/docs",
        }

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, Any]:
        from api.deps import db_path

        path = db_path()
        return {
            "status": "ok",
            "version": VERSION,
            "database": {"path": str(path), "present": path.exists()},
            # Named so a deployment can be checked from outside without reading its environment.
            # Booleans only: which store, not its address; whether auth is on, not its secret.
            "auth": {
                "configured": auth_module.is_configured(),
                # Counts and role names only, never an address or a hash. "Configured" alone
                # cannot distinguish a variable that is set from one that parsed the account you
                # meant — a malformed entry is skipped, and skipping silently is its own failure.
                **auth_module.directory_status(),
            },
            # The schema, not the connection string: this database is shared with another
            # project, so which namespace the memos land in is worth being able to check from
            # outside. It is a name, not a credential.
            "store": {
                "durable": bool(os.environ.get("DATABASE_URL")),
                "schema": store_schema() if os.environ.get("DATABASE_URL") else None,
            },
        }

    return app


app = create_app()
