"""Refuse to ship a key that is committed to the tree.

Every other audit in CI is advisory: a new advisory in a dependency is worth a warning and a fix,
not a blocked branch. This one blocks, because a key that reaches a public repository is already
leaked and no later commit un-leaks it.

The patterns are for real credential shapes, not for the word "key". Example files, the
`.env.example` template and documentation that shows a variable name without a value are expected
to mention keys and are not findings.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Prefixes published by the providers whose keys this project can hold.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Google/Gemini API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Groq API key", re.compile(r"\bgsk_[0-9A-Za-z]{40,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[0-9A-Za-z_\-]{20,}\b")),
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[0-9A-Za-z]{36,}\b")),
    (
        "Supabase service role JWT",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\."),
    ),
    ("private key block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    # An assignment with a long literal on the right, which is the shape of a pasted secret.
    (
        "assigned credential literal",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*[\"'][A-Za-z0-9_\-/+]{24,}[\"']"
        ),
    ),
]

# Files whose whole job is to describe secrets without containing one. Kept as short as it can
# be: an allowlisted file is a place a real key could sit unnoticed, so the tests assemble their
# credential shapes at runtime rather than asking to be listed here.
ALLOWED = {
    ".env.example",
    "scripts/scan_secrets.py",
    "docs/security.md",
}

BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".parquet",
    ".duckdb",
    ".zip",
    ".pdf",
    ".docx",
    ".pptx",
}


def tracked_files() -> list[Path]:
    out = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [ROOT / line for line in out.stdout.splitlines() if line]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED or path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS:
                if match := pattern.search(line):
                    shown = match.group(0)[:12]
                    findings.append(f"{rel}:{line_no}: {label} starting {shown!r}")

    if findings:
        print("credentials found in tracked files:")
        for finding in findings:
            print(f"  {finding}")
        print("\nRotate the key first — it is already exposed — then remove it from the history.")
        return 1

    print(f"no credentials in {len(tracked_files())} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
