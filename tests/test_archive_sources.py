"""Archiving the pages the corpus cites.

A citation that points at a live URL is a promise the reader has to take on trust: the page can
change and the claim quietly stops being supported. These tests cover the parts that make the
archive worth having — that it records a hash, that it says so in the document a reader actually
opens, and that an unreachable publisher is recorded rather than papered over.
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from etl import archive_sources as archive

PAGE = b"""<html><head><title>Fees</title><style>body{color:red}</style></head>
<body><script>track()</script><h1>Transaction fees</h1>
<p>The transfer fee is 4% of the purchase price.</p>
<p>Half is customarily paid by each party.</p></body></html>"""


@pytest.fixture
def corpus(tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "dld_fees.md").write_text(
        "---\n"
        "id: dld_fees\n"
        "title: Transaction fees\n"
        "source_url: https://dubailand.gov.ae/en/services/\n"
        "status: unverified\n"
        "retrieved: not yet archived\n"
        "expect_terms: 4%, transfer fee\n"
        "lang: en\n"
        "---\n\n# Fees\n\nThe transfer fee is 4%.\n"
    )
    (d / "README.md").write_text("not a document")
    (d / "no_source.md").write_text("---\nid: local\ntitle: Local\nlang: en\n---\n\nbody\n")
    return d


class TestReadingTheCorpus:
    def test_it_finds_documents_that_name_a_source(self, corpus) -> None:
        assert archive.cited_sources(corpus) == [
            ("dld_fees", "https://dubailand.gov.ae/en/services/", ["4%", "transfer fee"])
        ]

    def test_the_readme_is_not_a_document(self, corpus) -> None:
        assert all(key != "README" for key, _, _ in archive.cited_sources(corpus))

    def test_a_document_with_no_source_url_is_skipped(self, corpus) -> None:
        """Not every document cites a page; the methodology describes this project."""
        assert all(key != "local" for key, _, _ in archive.cited_sources(corpus))


class TestExtraction:
    def test_script_and_style_do_not_reach_the_text(self) -> None:
        text = archive.readable(PAGE.decode())
        assert "track()" not in text
        assert "color:red" not in text

    def test_the_prose_survives(self) -> None:
        text = archive.readable(PAGE.decode())
        assert "The transfer fee is 4% of the purchase price." in text
        assert "Half is customarily paid by each party." in text

    def test_entities_are_decoded(self) -> None:
        assert "AT&T" in archive.readable("<p>AT&amp;T</p>")


class TestFetching:
    def test_a_page_is_stored_with_its_hash(self, tmp_path, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})

        transport = httpx.MockTransport(handler)
        original = httpx.Client
        monkeypatch.setattr(
            httpx, "Client", lambda **kw: original(**{**kw, "transport": transport})
        )

        result = archive.fetch("dld_fees", "https://example.test/fees", archive=tmp_path)
        assert result.ok
        assert result.sha256 == hashlib.sha256(PAGE).hexdigest()
        assert (tmp_path / "dld_fees.html").read_bytes() == PAGE
        # The extracted text is stored beside it, so a citation can quote what was served.
        assert "transfer fee is 4%" in (tmp_path / "dld_fees.txt").read_text()
        assert result.retrieved_at

    def test_an_unreachable_publisher_is_recorded_not_raised(self, tmp_path, monkeypatch) -> None:
        """The whole data story here is publishers that refuse automated clients."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out")

        transport = httpx.MockTransport(handler)
        original = httpx.Client
        monkeypatch.setattr(
            httpx, "Client", lambda **kw: original(**{**kw, "transport": transport})
        )

        result = archive.fetch("blocked", "https://example.test/x", archive=tmp_path)
        assert result.ok is False
        assert "ConnectTimeout" in result.error
        assert result.sha256 is None

    def test_a_non_200_is_a_failure_with_its_status(self, tmp_path, monkeypatch) -> None:
        transport = httpx.MockTransport(lambda r: httpx.Response(403, content=b"nope"))
        original = httpx.Client
        monkeypatch.setattr(
            httpx, "Client", lambda **kw: original(**{**kw, "transport": transport})
        )
        result = archive.fetch("cbuae", "https://example.test/x", archive=tmp_path)
        assert result.ok is False
        assert result.status == 403


class TestStamping:
    def test_the_hash_lands_in_the_document_a_reader_opens(self, corpus) -> None:
        """Front matter, not a manifest: it is where someone looks to decide whether to believe."""
        record = archive.Archived(
            key="dld_fees",
            url="https://dubailand.gov.ae/en/services/",
            ok=True,
            sha256="a" * 64,
            retrieved_at="2026-09-06T19:00:00+00:00",
        )
        assert archive.stamp_corpus([record], corpus) == ["dld_fees.md"]

        head = (corpus / "dld_fees.md").read_text()
        assert "status: archived" in head
        assert "not yet archived" not in head
        assert "sha256 aaaaaaaaaaaaaaaa" in head
        assert "2026-09-06" in head

    def test_a_failed_fetch_leaves_the_document_honest(self, corpus) -> None:
        """An unarchived citation must keep saying so rather than quietly claiming otherwise."""
        record = archive.Archived(key="dld_fees", url="x", ok=False, error="ConnectTimeout")
        assert archive.stamp_corpus([record], corpus) == []
        assert "not yet archived" in (corpus / "dld_fees.md").read_text()


def test_the_manifest_declares_its_provenance(tmp_path, corpus, monkeypatch) -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})
    )
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(**{**kw, "transport": transport}))

    out = tmp_path / "manifest.json"
    assert (
        archive.main(
            [
                "--corpus",
                str(corpus),
                "--archive",
                str(tmp_path / "sources"),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    body = json.loads(out.read_text())
    # REAL: this describes what a publisher served, whatever the property data happens to be.
    assert body["provenance"] == "REAL"
    assert body["archived"] == 1


class TestCorroborationIsNotRetrieval:
    """A hash proves a URL served bytes. It proves nothing about what those bytes say.

    The publisher's pages are client-rendered, so a plain fetch returns the navigation and none of
    the substance — `dld_fees.txt` came back without "4%" or "transfer fee" in it. Stamping that
    "archived" beside a citation would be evidence that looks like corroboration and is not, which
    is the exact failure this project exists to avoid.
    """

    def _client(self, monkeypatch, body: bytes):
        transport = httpx.MockTransport(
            lambda r: httpx.Response(200, content=body, headers={"content-type": "text/html"})
        )
        original = httpx.Client
        monkeypatch.setattr(
            httpx, "Client", lambda **kw: original(**{**kw, "transport": transport})
        )

    def test_a_page_containing_the_terms_is_corroborated(self, tmp_path, monkeypatch) -> None:
        self._client(monkeypatch, PAGE)
        result = archive.fetch(
            "dld_fees", "https://x.test", expect_terms=["4%", "transfer fee"], archive=tmp_path
        )
        assert result.corroborated is True
        assert result.missing_terms == []

    def test_a_navigation_shell_is_archived_but_not_corroborated(
        self, tmp_path, monkeypatch
    ) -> None:
        """The real case: the page loads, and its substance is not in the HTML."""
        self._client(monkeypatch, b"<html><body><nav>Home About Contact</nav></body></html>")
        result = archive.fetch(
            "dld_fees", "https://x.test", expect_terms=["4%", "transfer fee"], archive=tmp_path
        )
        assert result.ok is True, "the fetch itself succeeded"
        assert result.corroborated is False
        assert set(result.missing_terms) == {"4%", "transfer fee"}
        assert any("client-rendered" in n for n in result.notes)

    def test_the_front_matter_says_which_it_was(self, corpus) -> None:
        uncorroborated = archive.Archived(
            key="dld_fees",
            url="x",
            ok=True,
            sha256="b" * 64,
            retrieved_at="2026-09-06T20:00:00+00:00",
            corroborated=False,
            missing_terms=["4%"],
        )
        archive.stamp_corpus([uncorroborated], corpus)
        head = (corpus / "dld_fees.md").read_text()
        assert "does not contain the cited terms" in head
        # It must not read as a clean tick.
        assert "status: archived and corroborated" not in head

    def test_a_corroborated_page_says_so(self, corpus) -> None:
        good = archive.Archived(
            key="dld_fees",
            url="x",
            ok=True,
            sha256="c" * 64,
            retrieved_at="2026-09-06T20:00:00+00:00",
            corroborated=True,
        )
        archive.stamp_corpus([good], corpus)
        assert "status: archived and corroborated" in (corpus / "dld_fees.md").read_text()
