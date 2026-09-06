"""Signing in, and asking who you are."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api import auth
from api.limits import AUTH, limit
from api.observability import log

router = APIRouter(tags=["auth"])


class TokenRequest(BaseModel):
    # A bounded string rather than EmailStr on purpose. The identity is whatever key the directory
    # holds, and a format check would answer a malformed address with 422 while a well-formed
    # unknown one gets 401 — a difference an attacker can measure. Both are 401 here.
    email: str = Field(min_length=3, max_length=254)
    # Bounded so a very long string cannot be used to make Argon2 do arbitrary work.
    password: str = Field(min_length=1, max_length=256)


@router.post("/auth/token", dependencies=[limit("auth", AUTH)])
def token(req: TokenRequest, request: Request) -> dict[str, Any]:
    """Exchange an email and password for a signed token.

    The same message and status for an unknown account as for a wrong password, because saying
    which it was tells an attacker which addresses are worth guessing against.
    """
    user = auth.authenticate(req.email, req.password)
    if user is None:
        log.warning(
            "sign-in refused",
            extra={
                "context": {
                    "email": req.email,
                    "client": request.client.host if request.client else None,
                }
            },
        )
        raise auth.AuthError("the email or password is wrong")

    log.info("sign-in", extra={"context": {"email": user.email, "role": user.role}})
    return auth.issue_token(user)


@router.get("/auth/me")
def me(principal: auth.PrincipalDep) -> dict[str, Any]:
    """Who this request is, as the service sees it.

    Useful to a person debugging, and the honest answer for an anonymous caller is `viewer` with
    `authenticated: false` — the interface shows that rather than pretending nobody is there.
    """
    return {
        "subject": principal.subject,
        "role": principal.role,
        "authenticated": principal.authenticated,
    }
