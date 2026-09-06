#!/usr/bin/env python
"""Fail if any document still carries an unfilled placeholder.

Term 4 artefacts are generated from docs/, so a stray marker would end up in a graded report. This
runs in CI on every push and again by hand before any artefact is generated.

Two details stop it crying wolf. Markers are matched on word boundaries, because "XX" appears
constantly inside base64 and hashes and means nothing there. And notebooks are parsed rather than
grepped, so only the cells a human wrote are scanned — an executed notebook embeds megabytes of
base64 image data that is not prose and cannot contain a placeholder.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Word-bounded so they match markers rather than coincidences inside encoded data.
MARKERS = re.compile(r"\b(TODO|FIXME|TBD|XX+)\b|\[insert\b", re.IGNORECASE)

SCANNED_SUFFIXES = {".md", ".ipynb", ".json", ".txt", ".yaml", ".yml"}
# Retrieval reports record whatever the publisher served, including its own text.
SKIP_NAMES = {"source_probe.json", "source_discovery.json", "spa_discovery.json"}


def notebook_prose(path: Path) -> list[tuple[int, str]]:
    """The lines a human wrote in a notebook: cell sources only, never outputs."""
    try:
        nb = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    lines: list[tuple[int, str]] = []
    for index, cell in enumerate(nb.get("cells", []), start=1):
        source = cell.get("source", [])
        text = source if isinstance(source, str) else "".join(source)
        for offset, line in enumerate(text.splitlines(), start=1):
            lines.append((index * 1000 + offset, line))
    return lines


def plain_lines(path: Path) -> list[tuple[int, str]]:
    try:
        return list(enumerate(path.read_text().splitlines(), start=1))
    except OSError:
        return []


def scan(target: Path) -> list[str]:
    if not target.exists():
        return []
    hits: list[str] = []
    files = [target] if target.is_file() else sorted(target.rglob("*"))
    for path in files:
        if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        if path.name in SKIP_NAMES:
            continue
        lines = notebook_prose(path) if path.suffix == ".ipynb" else plain_lines(path)
        for number, line in lines:
            if match := MARKERS.search(line):
                where = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
                hits.append(f"{where}:{number}: {match.group(0)}  ->  {line.strip()[:120]}")
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", type=Path, default=ROOT / "docs")
    args = parser.parse_args(argv)

    if not args.target.exists():
        print(f"placeholder scan: {args.target} does not exist yet — nothing to check")
        return 0

    hits = scan(args.target)
    if hits:
        print(f"placeholder scan FAILED — unfilled markers in {args.target}:")
        for hit in hits:
            print(f"  {hit}")
        return 1

    print(f"placeholder scan clean: {args.target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
