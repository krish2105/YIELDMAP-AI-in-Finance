"""Which commits deserve a front-end build.

The nightly ingest commits its own output — probe results, archived source pages — and every one
of those triggered a full Next.js build producing a byte-identical deployment. On a Hobby plan
those minutes are finite.

The risk runs the other way too, and it is the worse one: a gate that skips a build it should have
run ships stale code, silently. So these tests check both directions, and the "must build" cases
matter more than the "may skip" ones.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "vercel_should_build.sh"

SKIP, BUILD = 1, 0


def gate(changed: list[str]) -> int:
    """Run the gate's path rules over a list of changed files.

    The script asks git what changed between two commits; here the answer is supplied directly, so
    the rules are tested rather than a particular pair of commits in this repository's history.
    """
    script = SCRIPT.read_text()
    # Replace the git call with the fixture, leaving every rule below it intact.
    stubbed = script.replace(
        'CHANGED=$(git diff --name-only "$BEFORE" "$HEAD_REF")',
        "CHANGED=$(printf '%s\\n' " + " ".join(f"'{c}'" for c in changed) + ")",
    ).replace(
        'if [ -z "$BEFORE" ] || ! git cat-file -e "$BEFORE^{commit}" 2>/dev/null; then',
        "if false; then",
    )
    return subprocess.run(  # noqa: S603 - generated from this file, no external input
        ["bash", "-c", stubbed], cwd=ROOT, capture_output=True, text=True
    ).returncode


class TestItSkipsWhatTheBrowserNeverLoads:
    @pytest.mark.parametrize(
        "changed",
        [
            ["docs/results/source_probe.json"],
            ["docs/sources/dld_fees.html", "docs/sources/dld_fees.txt"],
            ["corpus/dld_fees.md", "corpus/ejari.md"],
            ["finance/hedonic.py", "tests/test_hedonic.py"],
            ["README.md"],
            ["render.yaml", "pyproject.toml", "uv.lock"],
            [".github/workflows/ci.yml"],
        ],
        ids=["probe", "archive", "corpus", "python", "readme", "api-deploy", "ci"],
    )
    def test_a_change_the_front_end_cannot_see_skips_the_build(self, changed) -> None:
        assert gate(changed) == SKIP, changed


class TestItBuildsWhenItMatters:
    """The expensive direction to get wrong: a skipped build ships stale code."""

    @pytest.mark.parametrize(
        "changed",
        [
            ["web/app/page.tsx"],
            ["web/components/Charts.tsx"],
            ["web/lib/api.ts"],
            ["package.json"],
            ["package-lock.json"],
            ["vercel.json"],
            ["web/next.config.ts"],
            # kpi.ts imports this at build time, so a threshold change must reach the bundle.
            ["config/kpi_thresholds.json"],
            # One relevant file among many irrelevant ones still builds.
            ["docs/results/x.json", "README.md", "web/app/ask/page.tsx"],
        ],
        ids=[
            "page",
            "component",
            "lib",
            "package",
            "lockfile",
            "vercel-config",
            "next-config",
            "kpi-thresholds",
            "mixed",
        ],
    )
    def test_a_change_the_front_end_uses_builds(self, changed) -> None:
        assert gate(changed) == BUILD, changed

    def test_an_empty_diff_skips(self) -> None:
        assert gate([]) == SKIP


def test_no_previous_deployment_builds() -> None:
    """A first deployment has nothing to compare against, so it must not be skipped."""
    result = subprocess.run(  # noqa: S603 - fixed argv
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "VERCEL_GIT_PREVIOUS_SHA": ""},
    )
    assert result.returncode == BUILD
    assert "no comparable previous deployment" in result.stdout
