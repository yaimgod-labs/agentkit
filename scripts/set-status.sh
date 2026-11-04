#!/usr/bin/env bash
# Usage: set-status.sh <owner/repo> <issue> [status:<name>] [reason:<name>]
# Leaves exactly one status:* label on the issue (or none when no status is given),
# and at most one reason:* label (the given one; any old reason is dropped).
# Every other status:*/reason:* label is removed in the same edit that adds the new ones.
# With AGENTKIT_INTERFACE=claude-slack the same edit also keeps action:required in step with the status:
# present for a waiting status (needs-info, needs-human, needs-verification, needs-approval, and ready on a mode:human
# issue), absent otherwise. Without it, action:required is never touched.
set -euo pipefail
repo=$1 n=$2 status=${3:-} reason=${4:-}
slack=0 want_wait=0 has_wait=0 human=0
[ "${AGENTKIT_INTERFACE:-}" != claude-slack ] || slack=1
filter='.labels[].name | select(startswith("status:") or startswith("reason:"))'
[ "$slack" -eq 0 ] || filter='.labels[].name | select(startswith("status:") or startswith("reason:") or . == "action:required" or . == "mode:human")'
# capture first so a failed read stops the script before the edit (fail closed)
labels=$(gh issue view "$n" --repo "$repo" --json labels --jq "$filter")
args=()
while IFS= read -r l; do
  case "$l" in
    action:required) has_wait=1; continue ;;
    mode:human) human=1; continue ;;
  esac
  [ -z "$l" ] || [ "$l" = "$status" ] || [ "$l" = "$reason" ] || args+=(--remove-label "$l")
done <<<"$labels"
if [ "$slack" -eq 1 ]; then
  case "$status" in
    status:needs-info | status:needs-human | status:needs-verification | status:needs-approval) want_wait=1 ;;
    status:ready) want_wait=$human ;;
  esac
  [ "$has_wait" -eq 0 ] || [ "$want_wait" -eq 1 ] || args+=(--remove-label action:required)
fi
[ -z "$status" ] || args+=(--add-label "$status")
[ -z "$reason" ] || args+=(--add-label "$reason")
[ "$want_wait" -eq 0 ] || [ "$has_wait" -eq 1 ] || args+=(--add-label action:required)
if [ ${#args[@]} -gt 0 ]; then gh issue edit "$n" --repo "$repo" "${args[@]}" >/dev/null; fi
