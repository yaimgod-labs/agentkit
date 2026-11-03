#!/usr/bin/env bash
# Usage: blockers.sh <owner/repo> <issue> open|dropped|dropped-titles
# Prints the number of each blocker of the issue, one per line (nothing when there are none).
#   open:           blockers that are still open.
#   dropped:        blockers that are closed but not as "completed" (not planned, duplicate, ...).
#   dropped-titles: the dropped ones as "<number> <title>".
# state and state_reason come from the API response, so a blocker in another repo is classified
# correctly without looking its number up in this one.
set -euo pipefail
repo=$1 n=$2 mode=$3
dropped='.[] | select(.state == "closed" and .state_reason != "completed")'
case "$mode" in
  open) filter='.[] | select(.state == "open") | .number' ;;
  dropped) filter="$dropped | .number" ;;
  dropped-titles) filter="$dropped | \"\\(.number) \\(.title)\"" ;;
  *) echo "usage: blockers.sh <owner/repo> <issue> open|dropped|dropped-titles" >&2; exit 2 ;;
esac
gh api "repos/$repo/issues/$n/dependencies/blocked_by" --paginate --jq "$filter"
