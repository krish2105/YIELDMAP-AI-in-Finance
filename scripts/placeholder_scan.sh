#!/usr/bin/env bash
# Thin wrapper so CI and a developer can run the scan the same way.
set -euo pipefail
exec uv run python "$(dirname "$0")/placeholder_scan.py" "$@"
