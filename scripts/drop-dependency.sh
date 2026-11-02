#!/usr/bin/env bash
# Usage: drop-dependency.sh <owner/repo> <closed-issue> <closed-title>
# A dropped blocker (closed, not completed) can never unblock its dependents: every open issue it blocks gets a
# block comment naming it and moves to status:blocked (block-dependent.sh). A dependent already in work
# (in-progress, review, changes-requested, approved, needs-verification) gets the comment only, and one that already
# has the comment for this blocker is skipped. Prints the affected issue numbers, one per line.
set -euo pipefail
repo=$1 n=$2 title=$3
here=$(cd "$(dirname "$0")" && pwd)
# Only dependents in this repo are touched: a number from another repo would address an unrelated issue here.
# The repo goes to jq through the environment, not into the filter.
# Output lines: "own <n> flight|wait" or "skip <owner/repo>#<n>".
# capture first so an API error stops the script (fail closed)
deps=$(DROP_REPO="$repo" gh api --paginate "repos/$repo/issues/$n/dependencies/blocking" --jq '.[] | select(.state == "open")
  | if ((.repository_url // "") | ascii_downcase | endswith("/repos/" + (env.DROP_REPO | ascii_downcase)))
    then "own \(.number) \(if any(.labels[]?.name; IN("status:in-progress", "status:review", "status:changes-requested",
                                                     "status:approved", "status:needs-verification"))
                          then "flight" else "wait" end)"
    else "skip \((.repository_url // "?") | sub(".*/repos/"; ""))#\(.number)" end')
while read -r kind dep state; do
  case "$kind" in
    own) ;;
    skip) echo "skip $dep: other repo" >&2; continue ;;
    *) continue ;;
  esac
  if [ "$state" = flight ]; then
    "$here/block-dependent.sh" "$repo" "$dep" "$n" "$title" --comment-only
  else
    "$here/block-dependent.sh" "$repo" "$dep" "$n" "$title"
  fi
done <<<"$deps"
