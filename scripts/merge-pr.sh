#!/usr/bin/env bash
# Usage: merge-pr.sh <pr> <owner/repo>
# Merges an approved PR the way the project chose: AGENTKIT_MERGE_METHOD (squash, merge or rebase; default squash),
# deleting its branch unless AGENTKIT_DELETE_BRANCH=false. The one place the kit merges (the gate, dispatch's
# verification path and an approved research reply all call it).
set -euo pipefail
method=${AGENTKIT_MERGE_METHOD:-squash}
case $method in
  squash | merge | rebase) ;;
  *) echo "::warning::AGENTKIT_MERGE_METHOD=$method is not squash, merge or rebase; merging with squash" >&2; method=squash ;;
esac
args=("--$method")
[ "${AGENTKIT_DELETE_BRANCH:-true}" = false ] || args+=(--delete-branch)
exec gh pr merge "$1" --repo "$2" "${args[@]}"
