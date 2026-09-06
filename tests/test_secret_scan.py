"""The secret scanner has to catch a secret.

A pattern list is easy to write and easy to write wrong: a scanner that finds nothing looks
identical whether the tree is clean or the regexes are broken. These cases are real credential
shapes with invented values, so a change that loosens a pattern fails here rather than in public.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import scan_secrets

ROOT = Path(__file__).resolve().parents[1]

PLANTED = [
    ("gemini", 'GEMINI_API_KEY = "AIza' + "B" * 35 + '"'),
    ("groq", 'key = "gsk_' + "c" * 44 + '"'),
    ("anthropic", 'ANTHROPIC_API_KEY="sk-ant-' + "d" * 40 + '"'),
    ("github", 'token = "ghp_' + "e" * 36 + '"'),
    ("private key", "-----BEGIN OPENSSH PRIVATE KEY-----"),
    ("assignment", 'password = "' + "f" * 30 + '"'),
]


@pytest.mark.parametrize(("name", "line"), PLANTED, ids=[p[0] for p in PLANTED])
def test_a_planted_credential_is_found(name: str, line: str) -> None:
    hits = [label for label, pattern in scan_secrets.PATTERNS if pattern.search(line)]
    assert hits, f"{name} was not matched by any pattern: {line[:40]}"


NOT_SECRETS = [
    "GEMINI_API_KEY=",
    "Set GEMINI_API_KEY in the environment before running.",
    'api_key = os.environ["GEMINI_API_KEY"]',
    "# the key is never committed",
    'sql_hash = "a3f19c2b8e4d"',
]


@pytest.mark.parametrize("line", NOT_SECRETS)
def test_talking_about_a_key_is_not_a_finding(line: str) -> None:
    """The scanner blocks CI, so a false positive is expensive."""
    hits = [label for label, pattern in scan_secrets.PATTERNS if pattern.search(line)]
    assert not hits, f"false positive ({hits}) on: {line}"


def test_the_working_tree_is_clean() -> None:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "scripts/scan_secrets.py"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout


def test_it_would_fail_on_a_tree_that_had_one(tmp_path: Path, monkeypatch) -> None:
    """End to end: a file with a key in it makes the script exit non-zero."""
    planted = tmp_path / "leaked.py"
    planted.write_text('GEMINI_API_KEY = "AIza' + "Z" * 35 + '"\n')
    monkeypatch.setattr(scan_secrets, "ROOT", tmp_path)
    monkeypatch.setattr(scan_secrets, "tracked_files", lambda: [planted])
    assert scan_secrets.main() == 1
