"""Memo store, export and endpoint tests.

The memo is the product, so the tests are about what must survive the trip out of the application:
the citations, the provenance warning and the advice notice. An export that loses its caveats is
worse than no export, because it looks authoritative and is no longer checkable.
"""

from __future__ import annotations

import io
import os
import zipfile

import pytest
from fastapi.testclient import TestClient

from agents.export import to_docx, to_html, to_markdown
from agents.store import MemoStore, StoredMemo, new_id
from api.main import create_app

PASSWORD = "memo-test-password"
EMAIL = "analyst@yieldmap.test"
VIEWER_EMAIL = "viewer@yieldmap.test"


@pytest.fixture(scope="module")
def _account():
    """One analyst account, for the whole module."""
    from api import auth

    previous = {k: os.environ.get(k) for k in ("AUTH_SECRET", "YIELDMAP_USERS")}
    os.environ["AUTH_SECRET"] = "memo-test-signing-key"
    os.environ["YIELDMAP_USERS"] = (
        f"{EMAIL}:analyst:{auth.hash_password(PASSWORD)};"
        f"{VIEWER_EMAIL}:viewer:{auth.hash_password(PASSWORD)}"
    )
    yield
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="module")
def client(_account) -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def ANALYST(client) -> dict[str, str]:
    """A real bearer token. The role is no longer something a header can assert."""
    token = client.post("/auth/token", json={"email": EMAIL, "password": PASSWORD}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def VIEWER(client) -> dict[str, str]:
    """A real token for an account that is only a viewer."""
    token = client.post("/auth/token", json={"email": VIEWER_EMAIL, "password": PASSWORD}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _fresh_limits():
    """Writes are rate limited to six an hour, and this module makes more than six."""
    from api.limits import limiter

    limiter.reset()
    yield
    limiter.reset()


def a_memo(**over) -> dict:
    body = {
        "id": new_id(),
        "run_id": "run123",
        "area_key": "marsa dubai",
        "memo_md": "# Investment memo — marsa dubai\n\n## What the registry shows\n\n"
        "Median price per sqm is 25,320 AED/sqm, from 160 records [1].\n\n"
        "- A bullet point about something\n",
        "citations": [
            {
                "n": 1,
                "title": "Median price per sqm",
                "source": "registry query",
                "agent": "Valuer",
                "n_records": 160,
            }
        ],
        "disagreements": [],
        "findings": [{"agent": "Valuer", "label": "Median price per sqm", "value": 25_320.0}],
        "audit": {"blocked": False, "worst_severity": "info", "findings": []},
        "budget": {"requests_used": 0},
        "status": "succeeded",
        "provenance": "REAL",
    }
    body.update(over)
    return body


class TestStore:
    def test_a_memo_round_trips(self, tmp_path):
        store = MemoStore(tmp_path)
        saved = store.save(StoredMemo(**a_memo()))
        loaded = store.get(saved.id)
        assert loaded is not None
        assert loaded.memo_md == saved.memo_md

    def test_an_unknown_id_returns_nothing(self, tmp_path):
        assert MemoStore(tmp_path).get("deadbeef") is None

    def test_a_path_traversal_attempt_is_refused(self, tmp_path):
        """The identifier goes into a filename, so it must not be able to escape the directory."""
        assert MemoStore(tmp_path).get("../../etc/passwd") is None
        assert MemoStore(tmp_path).get("a/b") is None

    def test_memos_are_listed_newest_first(self, tmp_path):
        store = MemoStore(tmp_path)
        first = store.save(StoredMemo(**a_memo(area_key="first")))
        second = store.save(StoredMemo(**a_memo(area_key="second")))
        listed = [m.id for m in store.list()]
        assert listed.index(second.id) < listed.index(first.id)

    def test_a_corrupt_file_does_not_break_the_listing(self, tmp_path):
        store = MemoStore(tmp_path)
        store.save(StoredMemo(**a_memo()))
        (tmp_path / "broken.json").write_text("{not json")
        assert len(store.list()) == 1

    def test_coverage_is_one_when_every_figure_is_cited(self):
        assert StoredMemo(**a_memo()).citation_coverage == 1.0

    def test_coverage_falls_when_a_figure_is_uncited(self):
        memo = StoredMemo(
            **a_memo(
                findings=[
                    {"agent": "Valuer", "label": "A", "value": 1.0},
                    {"agent": "Valuer", "label": "B", "value": 2.0},
                ],
                citations=[{"n": 1, "title": "A", "source": "s"}],
            )
        )
        assert memo.citation_coverage == 0.5

    def test_a_memo_stating_nothing_is_trivially_covered(self):
        memo = StoredMemo(**a_memo(findings=[], citations=[]))
        assert memo.citation_coverage == 1.0

    def test_a_finding_with_no_value_does_not_need_a_citation(self):
        """ "Could not be established" is not a claim requiring a source."""
        memo = StoredMemo(
            **a_memo(
                findings=[{"agent": "YieldAnalyst", "label": "Yield", "value": None}],
                citations=[],
            )
        )
        assert memo.citation_coverage == 1.0


class TestExport:
    def test_markdown_carries_the_sources(self):
        out = to_markdown(a_memo())
        assert "## Sources" in out
        assert "Median price per sqm" in out
        assert "160 records" in out

    def test_markdown_carries_the_advice_notice(self):
        assert "not advice" in to_markdown(a_memo()).lower()

    def test_a_generated_memo_carries_its_warning_into_the_export(self):
        out = to_markdown(a_memo(provenance="SYNTHETIC"))
        assert "generated data, not the Dubai registry" in out

    def test_a_real_memo_carries_no_such_warning(self):
        assert "generated data" not in to_markdown(a_memo())

    def test_a_withheld_memo_says_so_rather_than_exporting_blank(self):
        assert "withheld by the audit" in to_markdown(a_memo(memo_md=None))

    def test_audit_findings_travel_with_the_export(self):
        out = to_markdown(
            a_memo(
                audit={
                    "blocked": False,
                    "worst_severity": "warn",
                    "findings": [
                        {"severity": "warn", "rule": "budget_steps", "detail": "used every step"}
                    ],
                }
            )
        )
        assert "budget_steps" in out

    def test_html_is_a_complete_document(self):
        out = to_html(a_memo())
        assert out.startswith("<!doctype html>")
        assert "</html>" in out
        assert "<h1>" in out and "<ul>" in out

    def test_html_escapes_content_rather_than_rendering_it(self):
        """A memo is generated text, but escaping it is free and removes a whole class of bug."""
        out = to_html(a_memo(memo_md="# Title\n\n<script>alert(1)</script> is not markup [1]."))
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out

    def test_docx_is_a_valid_zip_with_the_expected_parts(self):
        archive = zipfile.ZipFile(io.BytesIO(to_docx(a_memo())))
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "[Content_Types].xml",
            "_rels/.rels",
            "word/document.xml",
        }

    def test_docx_contains_the_memo_text_and_the_notice(self):
        document = zipfile.ZipFile(io.BytesIO(to_docx(a_memo()))).read("word/document.xml").decode()
        assert "Investment memo" in document
        assert "not advice" in document.lower()

    def test_docx_escapes_characters_that_would_break_the_xml(self):
        document = (
            zipfile.ZipFile(io.BytesIO(to_docx(a_memo(memo_md="# A < B & C > D"))))
            .read("word/document.xml")
            .decode()
        )
        assert "&lt;" in document and "&amp;" in document

    def test_headings_bullets_and_paragraphs_all_survive(self):
        document = zipfile.ZipFile(io.BytesIO(to_docx(a_memo()))).read("word/document.xml").decode()
        assert "Heading1" in document
        assert "•" in document


class TestEndpoints:
    def test_nobody_can_create_a_memo_without_signing_in(self, client):
        """The only write in the API, and the only thing that spends a budget."""
        r = client.post("/memos", json={"area_key": "marsa dubai"})
        # 401, not 403: there is nobody here to refuse. The two say different things to a reader —
        # sign in, versus this account may not do that — and the interface shows the difference.
        assert r.status_code == 401
        assert "sign in" in r.json()["detail"]

    def test_a_signed_in_viewer_is_still_refused(self, client, VIEWER):
        """A real credential for an account that is not an analyst. This is the role check."""
        r = client.post("/memos", json={"area_key": "marsa dubai"}, headers=VIEWER)
        assert r.status_code == 403
        assert "analyst" in r.json()["detail"]

    def test_an_analyst_can_create_a_memo(self, client, ANALYST):
        r = client.post("/memos", json={"area_key": "marsa dubai"}, headers=ANALYST)
        assert r.status_code == 200
        body = r.json()
        assert body["citation_coverage"] == 1.0
        assert body["memo_md"]

    def test_a_created_memo_can_be_read_back(self, client, ANALYST):
        memo_id = client.post("/memos", json={"area_key": "business bay"}, headers=ANALYST).json()[
            "id"
        ]
        assert client.get(f"/memos/{memo_id}").json()["id"] == memo_id

    def test_an_unknown_memo_is_a_clear_404(self, client):
        assert client.get("/memos/abc123abc123").status_code == 404

    def test_memos_can_be_listed(self, client, ANALYST):
        client.post("/memos", json={"area_key": "marsa dubai"}, headers=ANALYST)
        body = client.get("/memos").json()
        assert body["count"] >= 1
        assert "citation_coverage" in body["memos"][0]

    @pytest.mark.parametrize(
        ("fmt", "media"),
        [("md", "text/markdown"), ("html", "text/html"), ("docx", "application/vnd.openxml")],
    )
    def test_every_export_format_works(self, client, ANALYST, fmt, media):
        memo_id = client.post("/memos", json={"area_key": "marsa dubai"}, headers=ANALYST).json()[
            "id"
        ]
        r = client.get(f"/memos/{memo_id}/export", params={"fmt": fmt})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(media)
        assert "attachment" in r.headers["content-disposition"]
        assert len(r.content) > 500

    def test_an_unknown_export_format_is_refused(self, client, ANALYST):
        memo_id = client.post("/memos", json={"area_key": "marsa dubai"}, headers=ANALYST).json()[
            "id"
        ]
        assert client.get(f"/memos/{memo_id}/export", params={"fmt": "pdf"}).status_code == 422

    def test_a_run_can_be_streamed(self, client, ANALYST):
        with client.stream(
            "POST", "/runs/stream", json={"area_key": "marsa dubai"}, headers=ANALYST
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            events = [
                line.removeprefix("event: ")
                for line in response.iter_lines()
                if line.startswith("event: ")
            ]
        assert events[0] == "start"
        assert events[-1] == "done"
        assert "finding" in events

    def test_streaming_also_requires_the_analyst_role(self, client, VIEWER):
        assert client.post("/runs/stream", json={"area_key": "marsa dubai"}).status_code == 401
        assert (
            client.post(
                "/runs/stream", json={"area_key": "marsa dubai"}, headers=VIEWER
            ).status_code
            == 403
        )

    def test_an_absurd_budget_is_refused_by_the_schema(self, client, ANALYST):
        r = client.post(
            "/memos", json={"area_key": "marsa dubai", "max_requests": 100_000}, headers=ANALYST
        )
        assert r.status_code == 422
