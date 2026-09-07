"""Regenerate the Term 4 notebook and execute every cell.

The notebook is a graded artefact and the one place where the analysis is presented as an argument
rather than as an API response. It is generated from scripts/build_notebook.py so it cannot drift
from the code, and it ships with its outputs stored so GitHub renders the charts.

Stored outputs are exactly how it rots. A function gets renamed, a results file changes shape, and
the notebook keeps rendering last week's figures perfectly — the cells that would now fail are
never run, so nothing goes red. `nbclient` has been a dependency since the notebook was written
and nothing imported it, which is that gap in its purest form.

This rebuilds and executes it, and fails on the first cell that raises. Run without --write to
check the committed notebook still executes without changing it, which is what CI wants: a fresh
execution in a clean checkout, no diff.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "docs" / "term4_yieldmap.ipynb"

# A cell may legitimately take a while: several of them fit models.
CELL_TIMEOUT_SECONDS = 600


def execute(path: Path, *, write: bool) -> tuple[bool, list[str]]:
    """Run every cell. Returns whether it succeeded and what went wrong."""
    import nbformat
    from nbclient import NotebookClient
    from nbclient.exceptions import CellExecutionError

    notebook = nbformat.read(path, as_version=4)
    client = NotebookClient(
        notebook,
        timeout=CELL_TIMEOUT_SECONDS,
        kernel_name="python3",
        # The notebook reads docs/results/ and data/ by relative path, so it has to run from the
        # repository root rather than from beside itself.
        resources={"metadata": {"path": str(ROOT)}},
        allow_errors=False,
    )

    try:
        client.execute()
    except CellExecutionError as exc:
        return False, [str(exc).strip().splitlines()[-1] if str(exc).strip() else repr(exc)]
    except Exception as exc:  # noqa: BLE001 - a kernel that will not start is a failure to report
        return False, [f"{type(exc).__name__}: {exc}"]

    # allow_errors=False raises on the first failure, so reaching here means every cell ran. The
    # sweep is belt and braces against a future change to that flag.
    problems = [
        f"cell {i}: {out.get('ename')}: {out.get('evalue')}"
        for i, cell in enumerate(notebook.cells)
        for out in cell.get("outputs", [])
        if out.get("output_type") == "error"
    ]

    if write and not problems:
        nbformat.write(notebook, path)
    return not problems, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="regenerate the notebook from scripts/build_notebook.py first",
    )
    parser.add_argument(
        "--write", action="store_true", help="save the executed outputs back into the notebook"
    )
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    args = parser.parse_args(argv)

    if args.rebuild:
        from scripts import build_notebook

        build_notebook.main() if hasattr(build_notebook, "main") else None

    if not args.notebook.exists():
        print(f"no notebook at {args.notebook}")
        return 1

    ok, problems = execute(args.notebook, write=args.write)

    cells = json.loads(args.notebook.read_text())["cells"]
    code_cells = sum(1 for c in cells if c["cell_type"] == "code")
    # --notebook accepts a path anywhere, so relative_to() is not safe to assume.
    try:
        shown = args.notebook.relative_to(ROOT)
    except ValueError:
        shown = args.notebook
    print(f"{shown}: {len(cells)} cells, {code_cells} of them code")

    if ok:
        print("every cell executed")
        return 0

    print("the notebook does not execute:", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
