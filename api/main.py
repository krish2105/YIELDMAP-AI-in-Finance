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

from api.routes import ask, market, simulate

VERSION = "0.1.0"

NOT_ADVICE = (
    "YIELDMAP explains, compares and simulates using published Dubai Land Department data. It is "
    "information, not financial advice, and it cannot execute a transaction of any kind."
)


def _origins() -> list[str]:
    raw = os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="YIELDMAP",
        version=VERSION,
        description=NOT_ADVICE,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins(),
        # Credentials are deliberately not allowed: the API holds no session, so permitting them
        # would widen the surface for nothing.
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Yieldmap-Role"],
        max_age=600,
    )

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

    app.include_router(market.router)
    app.include_router(simulate.router)
    app.include_router(ask.router)

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
        }

    return app


app = create_app()
