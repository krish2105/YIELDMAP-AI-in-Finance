"""Every measurement this project writes has to survive as far as a reader.

A results file that git ignores is a number nobody can check, and it fails silently: the code
writes it, the guard reads it locally, CI reads a file that was never committed, and the README
quotes a figure the repository does not contain.

This has now happened twice from the same cause — an unanchored ignore pattern matching at a depth
it was never meant to reach. `api/` in .vercelignore also matched web/app/api and took the runtime
proxy out of a production deploy; `coverage.json` in .gitignore, meant for the pytest-cov dump at
the root, also matched docs/results/coverage.json. Both patterns looked correct in isolation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs" / "results"


def _ignored(path: Path) -> str | None:
    """The ignore rule matching this path, if any. `git check-ignore -v` names the rule."""
    proc = subprocess.run(
        ["git", "check-ignore", "-v", str(path.relative_to(ROOT))],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() or None


def _results() -> list[Path]:
    return sorted(RESULTS.rglob("*.json"))


class TestNoMeasurementIsInvisible:
    def test_there_are_results_to_check(self) -> None:
        assert _results(), "no results found; this test would otherwise pass vacuously"

    @pytest.mark.parametrize("path", _results(), ids=lambda p: str(p.relative_to(RESULTS)))
    def test_a_results_file_is_not_git_ignored(self, path: Path) -> None:
        rule = _ignored(path)
        assert rule is None, (
            f"{path.relative_to(ROOT)} is ignored by {rule}. An ignore pattern without a leading "
            f"slash matches at any depth — anchor it."
        )


class TestIgnorePatternsThatCouldReachTheResults:
    """A pattern that would match a results filename is anchored, or it is a bug waiting."""

    def test_bare_filename_patterns_are_anchored_or_directory_scoped(self) -> None:
        lines = [
            line.strip()
            for line in (ROOT / ".gitignore").read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        loose = [
            line
            for line in lines
            # A pattern with no slash at all matches at every depth. That is fine for build
            # artefacts named things nothing else is called (.venv, __pycache__), and dangerous
            # for a plain filename that a results directory might reasonably use.
            if "/" not in line and line.endswith(".json")
        ]
        assert loose == [], (
            f"{loose} match any .json at any depth, including docs/results. Anchor with a leading "
            f"slash if the intent is the repository root."
        )
