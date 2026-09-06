"""Logs and error tracking.

Before this, the service had no logging of any kind. A production failure produced a 500 to the
caller and nothing anywhere else: no way to know it happened, let alone why. That is the state
that makes an outage last as long as it takes someone to notice by hand.

Logs are JSON on stdout because that is what the platform collects and what a person can grep
without a tool. Each line carries a request id, which is echoed to the caller in `x-request-id`,
so a user reporting "it broke" hands over the one string that finds their request.

Sentry is optional and off unless `SENTRY_DSN` is set. A service that requires an account with a
third party to start is a service that cannot be run by whoever clones it.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Values that must never reach a log line, whatever the caller sent. Passwords arrive in a request
# body and tokens in a header; both would otherwise be one careless `extra={...}` from being
# written to disk in plain text.
REDACTED = "[redacted]"
SENSITIVE_KEYS = {"password", "authorization", "token", "access_token", "secret", "api_key"}


def scrub(value: Any) -> Any:
    """Recursively replace anything that looks like a credential."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if k.lower() in SENSITIVE_KEYS else scrub(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "context", None)
        if isinstance(extra, dict):
            payload.update(scrub(extra))
        return json.dumps(payload, default=str)


def configure_logging() -> logging.Logger:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    # Replace rather than append: uvicorn installs its own handlers, and keeping both prints every
    # line twice, once as JSON and once not.
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(noisy).handlers = []
        logging.getLogger(noisy).propagate = True

    # Libraries that log every outbound call at INFO. Their lines are this service's own traffic
    # seen from the inside, and at one line per request they bury the ones that carry meaning.
    for chatty in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(chatty).setLevel(logging.WARNING)

    return logging.getLogger("yieldmap")


log = logging.getLogger("yieldmap")


def configure_sentry() -> bool:
    """Turn on error tracking if a DSN is configured. Returns whether it was."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("YIELDMAP_ENV", "development"),
        # Traces cost money above the free tier's allowance. A small sample is enough to see the
        # shape of latency without risking a bill on a project whose whole claim is that it has no
        # bill.
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
        send_default_pii=False,
        max_request_body_size="never",
    )
    return True


class RequestLogMiddleware(BaseHTTPMiddleware):
    """One log line per request, and a request id the caller can quote back."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming[:64] if incoming else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            # Logged here with the traceback, then re-raised so the error handler still produces
            # the response. Without this the only record of a crash would be the 500 itself.
            log.exception(
                "request failed",
                extra={
                    "context": {
                        "method": request.method,
                        "path": request.url.path,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                },
            )
            request_id_var.reset(token)
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers["x-request-id"] = request_id
        # A 5xx is the service's fault and a 4xx is the caller's; logging them at the same level
        # means a real fault is invisible among a hundred validation errors.
        level = logging.ERROR if response.status_code >= 500 else logging.INFO
        log.log(
            level,
            "request",
            extra={
                "context": {
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                }
            },
        )
        request_id_var.reset(token)
        return response
