"""Check the committed red-team results still match what the harness measures.

The /security page shows `docs/results/redteam.json`. If that file says a control held and the
harness now says otherwise, the page is publishing a claim. Only the verdicts are compared — the
timestamp and the free-text detail change on every run and comparing them would make this fail for
no reason.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "docs" / "results" / "redteam.json"


def verdicts(payload: dict) -> dict[str, bool]:
    return {o["id"]: o["held"] for o in payload["outcomes"]}


def main() -> int:
    if not PUBLISHED.exists():
        print(f"{PUBLISHED.relative_to(ROOT)} is missing; run the harness and commit it")
        return 1

    published = verdicts(json.loads(PUBLISHED.read_text()))

    # A real file, not /dev/stdout. The API now logs JSON to stdout, and those lines interleave
    # with the report, so parsing the stream means parsing whichever object arrived first.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "redteam.json"
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            [sys.executable, "-m", "security.redteam", "--out", str(out)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        fresh = verdicts(json.loads(out.read_text()))

    if missing := set(fresh) - set(published):
        print(f"attacks not in the published file: {sorted(missing)}")
        return 1
    if stale := set(published) - set(fresh):
        print(f"published file names attacks the harness no longer runs: {sorted(stale)}")
        return 1

    disagree = [k for k in fresh if fresh[k] != published[k]]
    if disagree:
        for key in disagree:
            print(f"{key}: published held={published[key]}, measured held={fresh[key]}")
        print(
            "\nregenerate with: uv run python -m security.redteam --out docs/results/redteam.json"
        )
        return 1

    print(f"{len(fresh)} attack verdicts match the published file")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
