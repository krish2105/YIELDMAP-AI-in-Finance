"""The ingest workflow has to fail loudly when it fails.

It runs unattended, nightly, where nobody is watching a log, and every step that talks to the
network is `continue-on-error` so one blocked host does not lose the rest of the run. That
combination is what let a total failure to publish read as a green job on 2026-09-07: the archive
step committed its work, could not push it four times over, printed a line, and exited zero.

These assertions are on the workflow file rather than on a run, because the failure mode is a
shell script's exit status and there is no way to observe it from Python otherwise.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ingest.yml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def steps(workflow) -> list[dict]:
    return workflow["jobs"]["ingest"]["steps"]


def _pushing_steps(steps: list[dict]) -> list[dict]:
    return [s for s in steps if "git push origin" in (s.get("run") or "")]


class TestPushingBack:
    def test_there_are_steps_that_push(self, steps):
        """If this fails the rest of the class is vacuous rather than passing."""
        assert len(_pushing_steps(steps)) >= 2

    def test_every_rebase_autostashes(self, steps):
        """Earlier steps write tracked files these commits do not claim.

        The probe rewrites docs/results/source_probe.json on every run, including the scheduled
        one where the reports commit is skipped. `git pull --rebase` then refuses with "you have
        unstaged changes" — which is deterministic, so the retry loop around it just failed four
        times and gave up.
        """
        for step in _pushing_steps(steps):
            run = step["run"]
            assert "git pull --rebase" in run
            assert "--autostash" in run, f"{step.get('name')!r} rebases without --autostash"

    def test_a_push_that_never_lands_fails_the_step(self, steps):
        for step in _pushing_steps(steps):
            run = step["run"]
            assert "::error::" in run, f"{step.get('name')!r} gives up without an annotation"
            assert run.rstrip().endswith("exit 1"), (
                f"{step.get('name')!r} exits zero after giving up, so the job goes green "
                "having published nothing"
            )


class TestRedeployGate:
    """A redeploy is worth it only when there is something new to serve."""

    @pytest.fixture(scope="class")
    def redeploy(self, steps) -> dict:
        found = [s for s in steps if "Redeploy" in (s.get("name") or "")]
        assert len(found) == 1, "expected exactly one redeploy step"
        return found[0]

    def test_it_is_not_gated_on_the_probe_verdict(self, redeploy):
        """A verdict describes what answered; only a file says a redeploy would serve anything.

        The two came apart on 2026-09-07: the probe read `reachable` because documentation
        answered, and nothing at all downloaded.
        """
        assert "verdict" not in str(redeploy.get("if", ""))

    def test_it_checks_for_a_drop_before_firing_the_hook(self, redeploy):
        run = redeploy["run"]
        assert "data/raw/" in run
        hook_line = run.index("${HOOK}")
        assert run.index("data/raw/") < hook_line, "the drop check must come first"
