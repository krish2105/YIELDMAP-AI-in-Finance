"""Archive the published documents the corpus cites, with a hash and a date.

Every document in `corpus/` carries a `source_url`, and until now every one also carried
`status: unverified` and `retrieved: not yet archived`. A citation pointing at a live URL is a
promise the reader has to take on trust: the page can change, and the claim it was supposed to
support quietly stops being supported.

This fetches each cited page, stores the bytes, records a SHA-256 and the moment it was taken, and
extracts the readable text. A citation then points at a fixed thing. When the page changes the
hash changes, which is information rather than a problem — it says the rule may have moved and the
figure derived from it needs re-checking.

Only the pages the corpus already cites, fetched once. This is document retrieval, not portal
scraping: the bulk datasets are a separate path and are covered by `docs/loading_real_data.md`.

Runs where the publisher is reachable, which is a GitHub Actions runner rather than this sandbox —
`docs/results/source_probe.json` records which hosts answer from where.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
ARCHIVE = ROOT / "docs" / "sources"
MANIFEST = ROOT / "docs" / "results" / "source_archive.json"

# A browser-shaped user agent, because several government sites answer an unlabelled client with a
# challenge page. This is not evasion — the request is for a public page, once, and the archive
# records exactly what came back.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36 YIELDMAP/0.1 (+https://github.com/krish2105/YIELDMAP-AI-in-Finance)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,ar;q=0.8",
}

SCRIPT_OR_STYLE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")
WHITESPACE = re.compile(r"[ \t\r\f\v]+")
BLANK_LINES = re.compile(r"\n{3,}")


@dataclass
class Archived:
    key: str
    url: str
    ok: bool
    status: int | None = None
    sha256: str | None = None
    bytes: int | None = None
    content_type: str | None = None
    retrieved_at: str | None = None
    text_chars: int = 0
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def readable(html: str) -> str:
    """The prose out of a page, good enough to cite and to index.

    A parser dependency would read better structure, but the point here is provenance rather than
    presentation: what matters is that the words in the archive are the words that were served.
    """
    body = SCRIPT_OR_STYLE.sub(" ", html)
    body = re.sub(r"<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", body, flags=re.I)
    body = TAG.sub(" ", body)
    body = (
        body.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    body = WHITESPACE.sub(" ", body)
    body = "\n".join(line.strip() for line in body.splitlines())
    return BLANK_LINES.sub("\n\n", body).strip()


def cited_sources(corpus: Path = CORPUS) -> list[tuple[str, str]]:
    """The (id, source_url) of every corpus document that names one."""
    out: list[tuple[str, str]] = []
    for path in sorted(corpus.glob("*.md")):
        if path.name == "README.md":
            continue
        head = path.read_text()[:1200]
        doc_id = re.search(r"^id:\s*(\S+)", head, re.M)
        url = re.search(r"^source_url:\s*(\S+)", head, re.M)
        if doc_id and url and url.group(1).startswith("http"):
            out.append((doc_id.group(1), url.group(1)))
    return out


def fetch(key: str, url: str, *, timeout: float = 30.0, archive: Path = ARCHIVE) -> Archived:
    archive.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(
            follow_redirects=True, timeout=timeout, headers=HEADERS, verify=True
        ) as client:
            response = client.get(url)
    except Exception as exc:  # noqa: BLE001 - an unreachable publisher is a recorded fact
        return Archived(key=key, url=url, ok=False, error=f"{type(exc).__name__}: {exc}")

    if response.status_code != 200:
        return Archived(
            key=key,
            url=url,
            ok=False,
            status=response.status_code,
            error=f"HTTP {response.status_code}",
        )

    payload = response.content
    digest = hashlib.sha256(payload).hexdigest()
    content_type = response.headers.get("content-type", "")
    suffix = ".pdf" if "pdf" in content_type else ".html"
    (archive / f"{key}{suffix}").write_bytes(payload)

    text = ""
    if "pdf" not in content_type:
        text = readable(payload.decode(response.encoding or "utf-8", errors="replace"))
        (archive / f"{key}.txt").write_text(text)

    return Archived(
        key=key,
        url=url,
        ok=True,
        status=200,
        sha256=digest,
        bytes=len(payload),
        content_type=content_type,
        retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
        text_chars=len(text),
        notes=["binary archived; text not extracted"] if "pdf" in content_type else [],
    )


def stamp_corpus(results: list[Archived], corpus: Path = CORPUS) -> list[str]:
    """Write the hash and retrieval date into the document that cites the page.

    The front matter is where a reader looks to decide whether to believe a citation, so that is
    where the evidence goes — rather than in a manifest they would have to know to open.
    """
    updated: list[str] = []
    by_key = {r.key: r for r in results if r.ok}
    for path in sorted(corpus.glob("*.md")):
        head = path.read_text()
        doc_id = re.search(r"^id:\s*(\S+)", head, re.M)
        if not doc_id or doc_id.group(1) not in by_key:
            continue
        record = by_key[doc_id.group(1)]
        body = head
        body = re.sub(r"^status:.*$", "status: archived", body, count=1, flags=re.M)
        replacement = (
            f"retrieved: {record.retrieved_at} · sha256 {record.sha256[:16]} · "
            f"docs/sources/{record.key}"
        )
        if re.search(r"^retrieved:.*$", body, re.M):
            body = re.sub(r"^retrieved:.*$", replacement, body, count=1, flags=re.M)
        else:
            body = body.replace("\nlang:", f"\n{replacement}\nlang:", 1)
        if body != head:
            path.write_text(body)
            updated.append(path.name)
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--out", type=Path, default=MANIFEST)
    parser.add_argument(
        "--stamp",
        action="store_true",
        help="write the hash and date into each corpus document's front matter",
    )
    args = parser.parse_args(argv)

    sources = cited_sources(args.corpus)
    if not sources:
        print("no corpus document names a source_url")
        return 1

    results = [fetch(key, url, archive=args.archive) for key, url in sources]
    reached = [r for r in results if r.ok]

    updated = stamp_corpus(results, args.corpus) if args.stamp else []

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {
                "provenance": "REAL",
                "note": (
                    "Each page the corpus cites, fetched once and stored with a SHA-256 so a "
                    "citation points at a fixed thing rather than at a URL that can change. A "
                    "changed hash later is information, not a fault: it says the rule may have "
                    "moved and the figures derived from it want re-checking."
                ),
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "attempted": len(results),
                "archived": len(reached),
                "corpus_documents_stamped": updated,
                "sources": [r.as_dict() for r in results],
            },
            indent=2,
        )
        + "\n"
    )

    for r in results:
        mark = f"{r.sha256[:12]}  {r.bytes:>8,}b" if r.ok else f"FAILED  {r.error}"
        print(f"{r.key:24} {mark}")
    print(f"\n{len(reached)}/{len(results)} archived → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
