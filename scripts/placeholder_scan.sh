#!/usr/bin/env bash
# Fails if any document still carries an unfilled placeholder.
#
# Term 4 artefacts are generated from docs/, so a stray marker would end up in a graded report.
# This runs in CI on every push and again by hand before any artefact is generated.
set -uo pipefail

target="${1:-docs}"

if [ ! -d "$target" ]; then
  echo "placeholder scan: '$target' does not exist yet — nothing to check"
  exit 0
fi

# Deliberately matches the same markers the project brief names.
pattern='TODO|FIXME|XX+|\[insert'

hits=$(grep -rInE "$pattern" "$target" --include='*.md' --include='*.ipynb' --include='*.json' 2>/dev/null || true)

if [ -n "$hits" ]; then
  echo "placeholder scan FAILED — unfilled markers found in $target:"
  echo "$hits"
  exit 1
fi

echo "placeholder scan clean: $target"
