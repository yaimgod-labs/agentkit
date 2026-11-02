#!/usr/bin/env bash
# Usage: set-status.sh <owner/repo> <issue> [status:<name>] [reason:<name>]
# Leaves exactly one status:* label on the issue (or none when no status is given),
# and at most one reason:* label (the given one; any old reason is dropped).
# Every other status:*/reason:* label is removed in the same edit that adds the new ones.
set -euo pipefail
repo=$1 n=$2 status=${3:-} reason=${4:-}
args=()
while IFS= read -r l; do
  [ -z "$l" ] || [ "$l" = "$status" ] || [ "$l" = "$reason" ] || args+=(--remove-label "$l")
done < <(gh issue view "$n" --repo "$repo" --json labels --jq '.labels[].name | select(startswith("status:") or startswith("reason:"))')
[ -z "$status" ] || args+=(--add-label "$status")
[ -z "$reason" ] || args+=(--add-label "$reason")
if [ ${#args[@]} -gt 0 ]; then gh issue edit "$n" --repo "$repo" "${args[@]}" >/dev/null; fi
