"""Discover download links on a JavaScript-rendered open-data page.

The DLD open-data page answers with 200 and almost no HTML: the dataset list and its download
links are built client-side. A plain HTTP fetch therefore finds nothing, which is exactly what the
first discovery run reported. This module drives a real browser so the page can build itself, then
records both the links it rendered and the network calls it made — the latter matter because the
API the page talks to is usually a better ingest path than the button it draws.

Runs on a GitHub Actions runner, where Chromium and open egress are both available.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

DATA_LIKE = re.compile(r"\.(csv|xlsx?|zip|json|parquet)(\?|$)", re.IGNORECASE)
API_LIKE = re.compile(r"/(api|gateway|service|odata|rest|data)/", re.IGNORECASE)


def discover_spa(urls: list[str], *, timeout_ms: int = 45_000) -> dict[str, Any]:
    """Load each page in a browser and record what it renders and what it calls."""
    from playwright.sync_api import sync_playwright

    pages: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36 YIELDMAP/0.1 (academic open-data client)"
            )
        )
        for url in urls:
            record: dict[str, Any] = {"url": url, "requests": [], "links": [], "error": None}
            page = context.new_page()

            def on_request(req, record=record):
                if DATA_LIKE.search(req.url) or API_LIKE.search(req.url):
                    record["requests"].append({"method": req.method, "url": req.url})

            page.on("request", on_request)
            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                page.wait_for_timeout(3_000)
                record["title"] = page.title()
                record["links"] = page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => ({href: e.href, text: (e.textContent||'').trim().slice(0,80)}))",
                )
                record["html_len"] = len(page.content())
            except Exception as exc:  # noqa: BLE001 - a page that fails is a finding, not a crash
                record["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                page.close()

            record["data_links"] = [
                link for link in record["links"] if DATA_LIKE.search(link.get("href", ""))
            ]
            print(
                f"{url}: {len(record['links'])} links, "
                f"{len(record['data_links'])} data links, "
                f"{len(record['requests'])} api/data requests"
                + (f" — {record['error']}" if record["error"] else ""),
                flush=True,
            )
            pages.append(record)
        browser.close()

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_pages": len(pages),
        "n_data_links": sum(len(p["data_links"]) for p in pages),
        "n_api_requests": sum(len(p["requests"]) for p in pages),
        "pages": pages,
    }


DEFAULT_URLS = [
    "https://dubailand.gov.ae/en/open-data/real-estate-data/",
    "https://dubailand.gov.ae/en/open-data/",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", dest="urls", default=None)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "docs" / "results" / "spa_discovery.json"
    )
    args = parser.parse_args(argv)

    report = discover_spa(args.urls or DEFAULT_URLS)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(
        f"wrote {args.out}: {report['n_data_links']} data links, {report['n_api_requests']} calls"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
