"""Authentication tests.

The case that matters most is the one the first red team missed: not a clever forgery, but simply
asking for a role. The old API took `X-Yieldmap-Role: admin` at face value, and the attack that
was supposed to catch that tested malformed values instead — so it passed while the door stood
open. Every test here is written against that failure.
"""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from api import auth
from api.limits import limiter
from api.main import create_app

PASSWORD = "correct-horse-battery-staple"
EMAIL = "analyst@yieldmap.test"


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    """A service with one analyst account and a fixed signing key."""
    monkeypatch.setenv("AUTH_SECRET", "a-test-signing-key-that-is-not-real")
    monkeypatch.setenv("YIELDMAP_USERS", f"{EMAIL}:analyst:{auth.hash_password(PASSWORD)}")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    # Buckets are process-global, so one test's requests would otherwise exhaust the next's.
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client(configured) -> TestClient:
    with TestClient(create_app()) as c:
        yield c


def sign_in(client: TestClient, password: str = PASSWORD) -> str:
    response = client.post("/auth/token", json={"email": EMAIL, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


class TestTheRoleCannotBeClaimed:
    """The exact bypass that used to work, from every angle a caller controls."""

    @pytest.mark.parametrize("role", ["analyst", "admin", "ADMIN", "analyst "])
    def test_the_old_header_grants_nothing(self, client: TestClient, role: str) -> None:
        response = client.post(
            "/memos", json={"area_key": "dubai-marina"}, headers={"X-Yieldmap-Role": role}
        )
        assert response.status_code == 401, (
            f"a caller claiming {role!r} in a header reached the write endpoint"
        )

    def test_a_role_in_the_body_grants_nothing(self, client: TestClient) -> None:
        response = client.post("/memos", json={"area_key": "dubai-marina", "role": "admin"})
        assert response.status_code == 401

    def test_a_role_in_the_query_string_grants_nothing(self, client: TestClient) -> None:
        assert (
            client.post("/memos?role=admin", json={"area_key": "dubai-marina"}).status_code == 401
        )

    def test_no_credential_is_refused(self, client: TestClient) -> None:
        assert client.post("/memos", json={"area_key": "dubai-marina"}).status_code == 401


class TestTokens:
    def test_a_correct_password_opens_the_write_endpoint(self, client: TestClient) -> None:
        token = sign_in(client)
        response = client.post(
            "/memos",
            json={"area_key": "dubai-marina"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text

    def test_a_wrong_password_is_refused(self, client: TestClient) -> None:
        assert (
            client.post("/auth/token", json={"email": EMAIL, "password": "no"}).status_code == 401
        )

    def test_an_unknown_account_is_indistinguishable_from_a_wrong_password(
        self, client: TestClient
    ) -> None:
        """Same status and same message, so the response cannot be used to enumerate accounts."""
        unknown = client.post("/auth/token", json={"email": "nobody@x.test", "password": "no"})
        wrong = client.post("/auth/token", json={"email": EMAIL, "password": "no"})
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["detail"] == wrong.json()["detail"]

    def test_a_forged_token_is_refused(self, client: TestClient) -> None:
        forged = jwt.encode(
            {"sub": EMAIL, "role": "admin", "iss": "yieldmap", "iat": 0, "exp": 2**31},
            "the-wrong-key",
            algorithm="HS256",
        )
        response = client.post(
            "/memos",
            json={"area_key": "dubai-marina"},
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert response.status_code == 401

    def test_an_unsigned_token_is_refused(self, client: TestClient) -> None:
        """`alg: none` is the oldest JWT attack; the decoder pins one algorithm to shut it."""
        unsigned = jwt.encode(
            {"sub": EMAIL, "role": "admin", "iss": "yieldmap", "iat": 0, "exp": 2**31},
            key="",
            algorithm="none",
        )
        assert auth_refuses(unsigned)

    def test_an_expired_token_is_refused(self, client: TestClient) -> None:
        expired = jwt.encode(
            {
                "sub": EMAIL,
                "role": "analyst",
                "iss": "yieldmap",
                "iat": int(time.time()) - 7200,
                "exp": int(time.time()) - 60,
            },
            auth.signing_key(),
            algorithm="HS256",
        )
        assert auth_refuses(expired)

    def test_a_token_from_another_issuer_is_refused(self, client: TestClient) -> None:
        foreign = jwt.encode(
            {"sub": EMAIL, "role": "admin", "iss": "somewhere-else", "iat": 0, "exp": 2**31},
            auth.signing_key(),
            algorithm="HS256",
        )
        assert auth_refuses(foreign)

    def test_a_token_escalating_its_own_role_is_still_only_what_was_signed(
        self, client: TestClient
    ) -> None:
        """Editing the payload breaks the signature, which is the whole point of signing it."""
        token = sign_in(client)
        header, payload, signature = token.split(".")
        tampered = jwt.encode(
            {"sub": EMAIL, "role": "admin", "iss": "yieldmap", "iat": 0, "exp": 2**31},
            auth.signing_key(),
            algorithm="HS256",
        )
        # Same key, so this one verifies — the point is that it took the key to make it.
        assert auth.read_token(tampered).role == "admin"
        # And a payload swapped onto someone else's signature does not.
        assert auth_refuses(f"{header}.{tampered.split('.')[1]}.{signature}")


def auth_refuses(token: str) -> bool:
    try:
        auth.read_token(token)
    except auth.AuthError:
        return True
    return False


class TestReadsStayPublic:
    """Requiring a login to read published open data would be theatre pointing the wrong way."""

    @pytest.mark.parametrize("path", ["/areas", "/market", "/health", "/ask/sources"])
    def test_anonymous_callers_can_read(self, client: TestClient, path: str) -> None:
        assert client.get(path).status_code == 200

    def test_anonymous_is_a_viewer_and_says_so(self, client: TestClient) -> None:
        body = client.get("/auth/me").json()
        assert body == {"subject": "anonymous", "role": "viewer", "authenticated": False}

    def test_a_signed_in_caller_is_reported_accurately(self, client: TestClient) -> None:
        token = sign_in(client)
        body = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert body == {"subject": EMAIL, "role": "analyst", "authenticated": True}


class TestConfiguration:
    def test_an_unconfigured_deployment_is_reported(self, monkeypatch) -> None:
        monkeypatch.delenv("AUTH_SECRET", raising=False)
        monkeypatch.setenv("YIELDMAP_USERS", "")
        problems = auth.require_configured()
        assert len(problems) == 2
        assert not auth.is_configured()

    def test_production_refuses_to_start_unconfigured(self, monkeypatch) -> None:
        """The unsafe states are silent ones, so they have to be loud at startup."""
        monkeypatch.delenv("AUTH_SECRET", raising=False)
        monkeypatch.setenv("YIELDMAP_USERS", "")
        monkeypatch.setenv("YIELDMAP_ENV", "production")
        with pytest.raises(RuntimeError, match="AUTH_SECRET"), TestClient(create_app()):
            pass

    def test_passwords_are_hashed_not_stored(self, monkeypatch) -> None:
        monkeypatch.setenv("YIELDMAP_USERS", f"{EMAIL}:analyst:{auth.hash_password(PASSWORD)}")
        user = auth.authenticate(EMAIL, PASSWORD)
        assert user is not None
        assert PASSWORD not in user.password_hash
        assert user.password_hash.startswith("$argon2id$")

    def test_a_malformed_user_entry_is_ignored_rather_than_trusted(self, monkeypatch) -> None:
        """A typo in configuration must not create an account, least of all a privileged one."""
        monkeypatch.setenv("YIELDMAP_USERS", "broken-entry;also:bad;x@y.z:sudo:$argon2id$fake")
        assert auth.authenticate("x@y.z", "anything") is None
        assert not auth._directory()
