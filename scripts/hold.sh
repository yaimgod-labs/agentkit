#!/usr/bin/env bash
# Usage: hold.sh <owner/repo> <issue>
# Whether the issue may start now. Both the dispatcher and implement's check job ask this. Prints one line:
#   open <b>...     open blockers hold it; nothing is written.
#   blocked <b>...  dropped blockers (closed, not completed) hold it. The issue had no block comment for them yet, so it
#                   now has one each and is status:blocked (block-dependent.sh). This does not rely on the
#                   `issues: closed` event having reached drop-dependency.sh.
#   go              nothing holds it. A dropped blocker that already has its block comment does not hold:
#                   the person has seen it, and `/board unblock` put the issue back into the flow.
# An API error exits non-zero (fail closed); a failed read of the blockers or comments writes nothing.
set -euo pipefail
repo=$1 n=$2
here=$(cd "$(dirname "$0")" && pwd)
open=$("$here/blockers.sh" "$repo" "$n" open)
if [ -n "$open" ]; then echo "open $(tr '\n' ' ' <<<"$open" | sed 's/ *$//')"; exit 0; fi
dropped=$("$here/blockers.sh" "$repo" "$n" dropped-titles)
held=
while read -r b title; do
  [ -n "$b" ] || continue
  acted=$("$here/block-dependent.sh" "$repo" "$n" "$b" "$title")
  [ -z "$acted" ] || held="$held $b"
done <<<"$dropped"
if [ -n "$held" ]; then echo "blocked${held}"; else echo go; fi
