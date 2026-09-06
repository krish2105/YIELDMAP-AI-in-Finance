"""Fetch open data from the publisher, and record exactly what was fetched.

This module is designed to run on a GitHub Actions runner, not in the development sandbox, because
the sandbox's network policy blocks every government domain (evidence in ``CLAUDE.md``). It has
three modes:

``probe``      try every candidate source and write a reachability report. This is the go/no-go
               for real data — it answers "can we get DLD data at all", with evidence.
``discover``   ask the catalogue which resources actually exist, so filenames are never guessed.
``fetch``      stream a resource to disk, recording SHA-256, byte count and retrieval time.

Every download writes a manifest entry. Nothing downstream trusts a file that is not in a manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from etl.sources import ALL_CANDIDATES, REFERENCE_DOCS, WANTED_DATASETS, Candidate

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
RESULTS_DIR = ROOT / "docs" / "results"

USER_AGENT = (
    "YIELDMAP/0.1 (SP Jain MAIB AI217 academic project; open-data client; "
    "+https://github.com/krish2105/YIELDMAP-AI-in-Finance)"
)
TIMEOUT = httpx.Timeout(60.0, connect=30.0)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _client() -> httpx.Client:
    # follow_redirects because open-data portals hop between www and CDN hosts.
    return httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )


# --------------------------------------------------------------------------- probe


def probe_one(client: httpx.Client, cand: Candidate) -> dict[str, Any]:
    """Try one candidate and describe what happened, success or failure."""
    started = time.monotonic()
    row: dict[str, Any] = {**asdict(cand), "checked_at": _now()}
    try:
        # A ranged GET rather than HEAD: some portals answer HEAD with 405 while serving GET fine.
        resp = client.get(cand.url, headers={"Range": "bytes=0-4095"})
        body = resp.content[:4096]
        row.update(
            ok=resp.status_code < 400,
            status=resp.status_code,
            content_type=resp.headers.get("content-type", ""),
            content_length=resp.headers.get("content-length"),
            final_url=str(resp.url),
            sample=body[:400].decode("utf-8", errors="replace"),
        )
    except Exception as exc:  # noqa: BLE001 - a probe reports failures, it does not raise
        row.update(ok=False, status=None, error=f"{type(exc).__name__}: {exc}")
    row["elapsed_s"] = round(time.monotonic() - started, 2)
    return row


def probe(out: Path | None = None) -> dict[str, Any]:
    """Check every candidate source and write a reachability report."""
    rows: list[dict[str, Any]] = []
    with _client() as client:
        for cand in (*ALL_CANDIDATES, *REFERENCE_DOCS):
            row = probe_one(client, cand)
            state = "ok " if row.get("ok") else "FAIL"
            print(f"[{state}] {row.get('status')!s:>5}  {cand.key:<28} {cand.url}", flush=True)
            if not row.get("ok") and row.get("error"):
                print(f"         {row['error']}", flush=True)
            rows.append(row)

    reachable = [r for r in rows if r.get("ok")]
    report = {
        "generated_at": _now(),
        "runner": "github-actions" if _on_actions() else "local",
        "n_candidates": len(rows),
        "n_reachable": len(reachable),
        "any_catalogue_reachable": any(r["kind"] == "catalogue" and r.get("ok") for r in rows),
        "verdict": "reachable" if reachable else "blocked",
        "candidates": rows,
    }
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\nwrote {out}", flush=True)
    print(f"\nverdict: {report['verdict']} ({len(reachable)}/{len(rows)} reachable)", flush=True)
    return report


def _on_actions() -> bool:
    import os

    return os.environ.get("GITHUB_ACTIONS") == "true"


# ----------------------------------------------------------------------- discover


def extract_resources(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull downloadable resources out of a CKAN ``package_search`` or ``package_show`` payload.

    Kept separate from the HTTP call so it can be tested against a recorded payload offline.
    """
    result = payload.get("result", payload)
    packages: list[dict[str, Any]]
    if isinstance(result, dict) and "results" in result:
        packages = result["results"]
    elif isinstance(result, dict) and "resources" in result:
        packages = [result]
    elif isinstance(result, list):
        packages = [p for p in result if isinstance(p, dict)]
    else:
        packages = []

    out: list[dict[str, Any]] = []
    for pkg in packages:
        pkg_id = str(pkg.get("name") or pkg.get("id") or "")
        pkg_title = str(pkg.get("title") or pkg_id)
        for res in pkg.get("resources", []) or []:
            url = res.get("url")
            if not url:
                continue
            out.append(
                {
                    "dataset_id": pkg_id,
                    "dataset_title": pkg_title,
                    "resource_id": res.get("id"),
                    "name": res.get("name"),
                    "format": (res.get("format") or "").upper(),
                    "url": url,
                    "size": res.get("size"),
                    "last_modified": res.get("last_modified") or res.get("created"),
                    "matches": match_wanted(f"{pkg_id} {pkg_title} {res.get('name') or ''}"),
                }
            )
    return out


def match_wanted(text: str) -> list[str]:
    """Which of the datasets we want does this text look like?"""
    low = text.lower()
    return [key for key, needles in WANTED_DATASETS.items() if any(n in low for n in needles)]


def discover(out: Path | None = None) -> dict[str, Any]:
    """Ask the catalogue what exists, rather than guessing filenames."""
    from etl.sources import CATALOGUE_CANDIDATES

    resources: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with _client() as client:
        for cand in CATALOGUE_CANDIDATES:
            if cand.kind != "catalogue":
                continue
            try:
                resp = client.get(cand.url)
                resp.raise_for_status()
                found = extract_resources(resp.json())
                print(f"[ok ] {cand.key}: {len(found)} resources", flush=True)
                resources.extend(found)
            except Exception as exc:  # noqa: BLE001
                errors.append({"key": cand.key, "error": f"{type(exc).__name__}: {exc}"})
                print(f"[FAIL] {cand.key}: {exc}", flush=True)

    # Deduplicate on url, keep the richest record.
    by_url: dict[str, dict[str, Any]] = {}
    for r in resources:
        by_url.setdefault(r["url"], r)

    report = {
        "generated_at": _now(),
        "n_resources": len(by_url),
        "errors": errors,
        "wanted": {
            key: [r for r in by_url.values() if key in r["matches"]] for key in WANTED_DATASETS
        },
        "resources": sorted(by_url.values(), key=lambda r: (r["dataset_id"], r["name"] or "")),
    }
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"wrote {out}", flush=True)
    return report


# -------------------------------------------------------------------------- fetch


def fetch(url: str, dest: Path, *, max_bytes: int | None = None) -> dict[str, Any]:
    """Stream a URL to disk, recording enough to make the download citable and checkable."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    started = time.monotonic()
    with _client() as client, client.stream("GET", url) as resp:
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=1 << 20):
                fh.write(chunk)
                digest.update(chunk)
                size += len(chunk)
                if max_bytes and size >= max_bytes:
                    print(f"  stopped at the {max_bytes} byte cap", flush=True)
                    break
        content_type = resp.headers.get("content-type", "")
    entry = {
        "url": url,
        "path": str(dest.relative_to(ROOT)) if dest.is_relative_to(ROOT) else str(dest),
        "sha256": digest.hexdigest(),
        "bytes": size,
        "content_type": content_type,
        "retrieved_at": _now(),
        "elapsed_s": round(time.monotonic() - started, 2),
        "truncated": bool(max_bytes and size >= max_bytes),
    }
    print(f"  {size:,} bytes  sha256={entry['sha256'][:16]}…  -> {entry['path']}", flush=True)
    return entry


def write_manifest(entries: list[dict[str, Any]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"generated_at": _now(), "files": entries}, indent=2, ensure_ascii=False)
    )
    print(f"wrote {out}", flush=True)


# ---------------------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_probe = sub.add_parser("probe", help="check which sources are reachable from here")
    p_probe.add_argument("--out", type=Path, default=RESULTS_DIR / "source_probe.json")

    p_disc = sub.add_parser("discover", help="enumerate resources from the catalogue")
    p_disc.add_argument("--out", type=Path, default=RESULTS_DIR / "source_discovery.json")

    p_fetch = sub.add_parser("fetch", help="download one resource")
    p_fetch.add_argument("url")
    p_fetch.add_argument("--out", type=Path, required=True)
    p_fetch.add_argument("--max-bytes", type=int, default=None)

    args = parser.parse_args(argv)

    if args.cmd == "probe":
        # A blocked probe is information, not a crash: the workflow reads the verdict and decides.
        probe(args.out)
        return 0
    if args.cmd == "discover":
        report = discover(args.out)
        return 0 if report["n_resources"] else 1
    if args.cmd == "fetch":
        entry = fetch(args.url, args.out, max_bytes=args.max_bytes)
        write_manifest([entry], RAW_DIR / "manifest.json")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
