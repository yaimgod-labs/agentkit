#!/usr/bin/env bash
# Usage: drop-dependency.sh <owner/repo> <closed-issue> <closed-title>
# A dropped blocker (closed, not completed) can never unblock its dependents: every open issue it blocks gets a
# block comment naming it and moves to status:blocked. Prints the affected issue numbers, one per line.
set -euo pipefail
repo=$1 n=$2 title=$3
here=$(cd "$(dirname "$0")" && pwd)
# capture first so an API error stops the script (fail closed)
deps=$(gh api --paginate "repos/$repo/issues/$n/dependencies/blocking" --jq '.[] | select(.state == "open") | .number')
while IFS= read -r dep; do
  [ -n "$dep" ] || continue
  gh issue comment "$dep" --repo "$repo" --body "<!-- agentkit:block -->
**Blocked:** dropped dependency: #$n ($title)" >/dev/null
  "$here/set-status.sh" "$repo" "$dep" status:blocked
  echo "$dep"
done <<<"$deps"
