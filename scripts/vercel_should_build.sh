#!/usr/bin/env bash
# Decide whether a commit needs a front-end build.
#
# Vercel runs this before every deployment: exit 1 to skip the build, 0 to run it. Without it, the
# nightly ingest's own commits — probe results, archived source pages, none of which the browser
# ever sees — each triggered a full Next.js build. On a Hobby plan those minutes are finite, and
# the deployment they produce is byte-identical to the one before it.
#
# Deliberately conservative: anything not clearly irrelevant builds. A skipped build that should
# have run ships stale code, which is far worse than a wasted minute.
set -euo pipefail

# Vercel provides the previous deployment's SHA. On a first deployment there is nothing to compare
# against, so build.
BEFORE="${VERCEL_GIT_PREVIOUS_SHA:-}"
if [ -z "$BEFORE" ] || ! git cat-file -e "$BEFORE^{commit}" 2>/dev/null; then
  echo "no comparable previous deployment — building"
  exit 0
fi

# The commit being deployed. Vercel sets it; overridable so this is testable against real
# history rather than only against whatever happens to be checked out.
HEAD_REF="${VERCEL_GIT_COMMIT_SHA:-HEAD}"
CHANGED=$(git diff --name-only "$BEFORE" "$HEAD_REF")
if [ -z "$CHANGED" ]; then
  echo "no files changed — skipping"
  exit 1
fi

# Paths the browser never loads. docs/ is prose and measurements; the Python half is the API,
# which deploys separately to Render. config/ is NOT here: web/lib/kpi.ts reads
# config/kpi_thresholds.json at build time, so a threshold change must rebuild.
IRRELEVANT='^(docs/|corpus/|etl/|finance/|rag/|agents/|api/|security/|tests/|scripts/|db/|\.github/|README\.md$|CLAUDE\.md$|render\.yaml$|pyproject\.toml$|uv\.lock$)'

RELEVANT=$(printf '%s\n' "$CHANGED" | grep -Ev "$IRRELEVANT" || true)

if [ -z "$RELEVANT" ]; then
  echo "only paths the front end does not use changed — skipping the build:"
  printf '  %s\n' $CHANGED | head -20
  exit 1
fi

echo "front-end relevant changes — building:"
printf '  %s\n' $RELEVANT | head -20
exit 0
