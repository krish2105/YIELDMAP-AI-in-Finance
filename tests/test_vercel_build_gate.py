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

# Vercel's convention, not a choice made here, and it is inverted from the shell habit of "0 means
# success": https://vercel.com/docs/project-configuration/vercel-json says "Exiting with code 0
# ignores the build, while code 1 continues it."
#
# The first version of this file had these the natural way round. The tests passed — they were
# asserting the same wrong belief the script held — and every commit the gate judged relevant was
# silently skipped by Vercel. Deployments came back CANCELED rather than failed, so nothing looked
# broken. Naming the constants after the platform's meaning is what keeps the two in step.
SKIP, BUILD = 0, 1


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


class TestTheDeploymentCanActuallyReachTheGate:
    """vercel.json names this script as its ignoreCommand, and .vercelignore decides what the
    build is allowed to see. Nothing connected the two, so excluding scripts/ from the upload
    deleted the script Vercel had been told to run and every deployment failed with "No such file
    or directory" — before a line of the app was built.

    The general form: a path vercel.json depends on must survive .vercelignore.
    """

    IGNORE = ROOT / ".vercelignore"
    CONFIG = ROOT / "vercel.json"

    @staticmethod
    def _patterns() -> list[str]:
        return [
            line.strip()
            for line in TestTheDeploymentCanActuallyReachTheGate.IGNORE.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    @staticmethod
    def _excluded(path: str) -> str | None:
        """The .vercelignore pattern that would remove `path` from the upload, if any.

        .vercelignore uses gitignore semantics, so a pattern without a leading slash matches at
        any depth. That is the trap this whole class exists for.
        """
        parts = path.split("/")
        for pattern in TestTheDeploymentCanActuallyReachTheGate._patterns():
            bare = pattern.strip("/")
            if pattern.startswith("/"):
                # Anchored: matches only from the repository root.
                if path == bare or path.startswith(bare + "/"):
                    return pattern
            elif bare in parts:
                # Unanchored: matches a segment of that name at any depth.
                return pattern
        return None

    def test_the_ignore_command_script_is_uploaded(self) -> None:
        import json
        import re

        command = json.loads(self.CONFIG.read_text())["ignoreCommand"]
        # e.g. "bash scripts/vercel_should_build.sh" — take the repo-relative path it runs.
        referenced = re.findall(r"[\w./-]+\.(?:sh|js|mjs|cjs)", command)
        assert referenced, f"no script path found in ignoreCommand: {command!r}"

        for path in referenced:
            assert (ROOT / path).exists(), f"ignoreCommand runs {path}, which is not in the tree"
            pattern = self._excluded(path)
            assert pattern is None, (
                f"vercel.json runs {path} but .vercelignore excludes it via {pattern!r}. "
                f"The ignore step runs against the filtered source, so the deployment fails "
                f"before it starts."
            )

    def test_the_helper_recognises_an_anchored_exclusion(self) -> None:
        """A guard whose matcher is wrong passes everything. Checked against a path this file
        genuinely does exclude."""
        assert self._excluded("tests/test_vercel_build_gate.py") == "/tests/"

    def test_the_helper_does_not_match_a_similar_prefix(self) -> None:
        assert self._excluded("api_client/thing.sh") is None

    def test_config_is_still_uploaded(self) -> None:
        """web/lib/kpi.ts reads config/kpi_thresholds.json at build time."""
        assert self._excluded("config/kpi_thresholds.json") is None


class TestTheExitCodesAreVercelsNotOurs:
    """The gate's whole contract is two integers, and they are the platform's, backwards from the
    shell convention. This pins them so an "obvious" cleanup cannot quietly invert the gate again.
    """

    def test_skip_is_zero_and_build_is_one(self) -> None:
        # https://vercel.com/docs/project-configuration/vercel-json:
        # "Exiting with code 0 ignores the build, while code 1 continues it."
        assert (SKIP, BUILD) == (0, 1)

    def test_the_script_documents_the_convention_it_implements(self) -> None:
        """A reader who checks this file against the shell habit will conclude it is a bug and
        "fix" it. The reason has to be in the script, not only here."""
        text = SCRIPT.read_text()
        assert "exit 0" in text and "IGNORE" in text
        assert "vercel.com/docs" in text

    def test_a_relevant_change_exits_one_so_vercel_proceeds(self) -> None:
        assert gate(["web/app/page.tsx"]) == 1

    def test_an_irrelevant_change_exits_zero_so_vercel_stops(self) -> None:
        assert gate(["docs/limits.md"]) == 0
