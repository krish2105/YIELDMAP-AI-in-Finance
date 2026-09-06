"""Authentication: who the caller is, asserted by this service rather than claimed by them.

The interface used to send `X-Yieldmap-Role: analyst` and the API believed it. That is not access
control — it is a client-side preference with a server-side name. Anyone with curl could write.

What replaces it:

* A caller proves identity once, at `POST /auth/token`, with an email and a password.
* The service issues a short-lived token it signed itself. The role lives in the token's claims,
  so it is a statement this service made, not one the caller made.
* Every protected route reads the role from that signature. No header, query parameter or body
  field can influence it.

Reads stay open. The Land Department data is published, the site is a public demonstration, and
requiring a login to look at open data would be security theatre pointing the wrong way. What is
protected is the surface that *spends* something: creating a memo runs the agent crew, which costs
model quota and CPU. So anonymous callers are viewers, and only a real token can be more.

Users come from the environment rather than a table because this deployment has no signup. That is
a deliberate limit, not an oversight: when signup exists, `UserDirectory` gains a database-backed
implementation and nothing above it changes.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

Role = Literal["viewer", "analyst", "admin"]
ROLE_ORDER: dict[str, int] = {"viewer": 0, "analyst": 1, "admin": 2}

ALGORITHM = "HS256"
ISSUER = "yieldmap"
TOKEN_TTL = timedelta(hours=int(os.environ.get("AUTH_TOKEN_TTL_HOURS", "12")))

# Argon2id at the library's defaults, which are chosen to be safe without tuning. bcrypt would
# also do, but its cost parameter is a decision this project has no basis to make well.
_hasher = PasswordHasher()


class AuthError(HTTPException):
    def __init__(self, detail: str, status_code: int = status.HTTP_401_UNAUTHORIZED) -> None:
        super().__init__(
            status_code=status_code, detail=detail, headers={"WWW-Authenticate": "Bearer"}
        )


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError):
        return False
    return True


def signing_key() -> str:
    """The key this service signs tokens with.

    Absent, a random one is generated per process. That is the right failure mode for a developer
    running locally — tokens work, and they stop working on restart — and the wrong one for a
    deployment, where two instances would issue tokens the other rejects. `require_configured()`
    is what makes the deployment case loud instead of subtly broken.
    """
    configured = os.environ.get("AUTH_SECRET")
    if configured:
        return configured
    if not hasattr(signing_key, "_ephemeral"):
        signing_key._ephemeral = secrets.token_urlsafe(48)  # type: ignore[attr-defined]
    return signing_key._ephemeral  # type: ignore[attr-defined,return-value]


def is_configured() -> bool:
    return bool(os.environ.get("AUTH_SECRET")) and bool(_directory())


@dataclass(frozen=True)
class Principal:
    """Who the caller is, according to this service."""

    subject: str
    role: Role
    authenticated: bool

    @property
    def is_anonymous(self) -> bool:
        return not self.authenticated


ANONYMOUS = Principal(subject="anonymous", role="viewer", authenticated=False)


@dataclass(frozen=True)
class User:
    email: str
    password_hash: str
    role: Role


def _directory() -> dict[str, User]:
    """Accounts, read from the environment.

    `YIELDMAP_USERS` is a semicolon-separated list of `email:role:argon2-hash`. The hash is stored,
    never the password, so the environment of a running service does not contain a credential that
    would work anywhere else — and `scripts/scan_secrets.py` blocks a hash from reaching the
    repository either way.

    Generate one with:  uv run python -m api.auth hash 'the-password'
    """
    raw = os.environ.get("YIELDMAP_USERS", "").strip()
    users: dict[str, User] = {}
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        # rsplit from the right twice: an Argon2 hash contains ':' characters, an email does not.
        parts = entry.split(":", 2)
        if len(parts) != 3:
            continue
        email, role, password_hash = (p.strip() for p in parts)
        if role not in ROLE_ORDER or not email or not password_hash:
            continue
        users[email.lower()] = User(email=email.lower(), password_hash=password_hash, role=role)  # type: ignore[arg-type]
    return users


def authenticate(email: str, password: str) -> User | None:
    """Check a password. Constant work whether or not the account exists.

    Verifying against a dummy hash for an unknown email costs the same as a real check, so response
    time does not reveal which addresses have accounts.
    """
    user = _directory().get(email.strip().lower())
    reference = user.password_hash if user else _DUMMY_HASH
    ok = verify_password(password, reference)
    return user if (ok and user) else None


# Computed once at import: a real Argon2 hash of a value nothing can match, used to keep the
# unknown-account path the same cost as the known one.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def issue_token(user: User) -> dict[str, Any]:
    now = datetime.now(UTC)
    expires = now + TOKEN_TTL
    claims = {
        "iss": ISSUER,
        "sub": user.email,
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    token = jwt.encode(claims, signing_key(), algorithm=ALGORITHM)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires.isoformat(timespec="seconds"),
        "role": user.role,
    }


def read_token(token: str) -> Principal:
    """Decode a token this service signed, or refuse.

    `algorithms` is pinned to one value on purpose. Accepting the algorithm named in the token's
    own header is the classic JWT flaw: a token claiming `alg: none`, or an RS256 verifier tricked
    into treating a public key as an HMAC secret, both start there.
    """
    try:
        claims = jwt.decode(
            token,
            signing_key(),
            algorithms=[ALGORITHM],
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("the token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("the token is not valid") from exc

    role = claims.get("role")
    if role not in ROLE_ORDER:
        raise AuthError("the token carries no usable role")
    return Principal(subject=str(claims["sub"]), role=role, authenticated=True)


_bearer = HTTPBearer(auto_error=False)


def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """The caller, as this service understands them.

    No credential means anonymous, which means viewer. A credential that does not verify is an
    error rather than a downgrade: silently treating a bad token as anonymous would hide an
    expired session behind an empty page instead of a prompt to sign in again.
    """
    if credentials is None or not credentials.credentials:
        return ANONYMOUS
    return read_token(credentials.credentials)


PrincipalDep = Annotated[Principal, Depends(current_principal)]


def require(minimum: Role):
    """Dependency factory: refuse a caller below `minimum`.

    An anonymous caller gets 401 and an authenticated one 403, because the two mean different
    things to whoever is reading: sign in, versus this account cannot do that.
    """

    def _check(principal: PrincipalDep) -> Principal:
        if ROLE_ORDER[principal.role] >= ROLE_ORDER[minimum]:
            return principal
        if principal.is_anonymous:
            raise AuthError(f"this endpoint needs the {minimum} role; sign in at /auth/token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"this endpoint needs the {minimum} role; you have {principal.role}",
        )

    return Depends(_check)


def require_configured() -> list[str]:
    """Configuration problems that make authentication unsafe in a deployment.

    Returned rather than raised so the caller decides: `api.main` logs them as warnings when
    running locally and refuses to start when `YIELDMAP_ENV=production`.
    """
    problems: list[str] = []
    if not os.environ.get("AUTH_SECRET"):
        problems.append(
            "AUTH_SECRET is not set: tokens are signed with a per-process key, so they stop "
            "working on restart and two instances will reject each other's tokens"
        )
    if not _directory():
        problems.append(
            "YIELDMAP_USERS is empty: nobody can sign in, so every write endpoint is unreachable"
        )
    return problems


def client_key(request: Request, principal: Principal) -> str:
    """A stable identity for rate limiting: the account when known, otherwise the client address."""
    if principal.authenticated:
        return f"user:{principal.subject}"
    forwarded = request.headers.get("x-forwarded-for", "")
    # Render and Vercel both prepend the real client; the rest of the chain is theirs, not the
    # caller's, so only the first entry is worth keying on.
    client = forwarded.split(",")[0].strip() if forwarded else ""
    if not client and request.client:
        client = request.client.host
    return f"ip:{client or 'unknown'}"


def main(argv: list[str] | None = None) -> int:
    """`uv run python -m api.auth hash 'password'` — print a hash to put in YIELDMAP_USERS."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    h = sub.add_parser("hash", help="hash a password for YIELDMAP_USERS")
    h.add_argument("password")
    args = parser.parse_args(argv)

    if args.command == "hash":
        print(hash_password(args.password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
