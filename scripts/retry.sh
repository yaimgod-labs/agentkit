#!/usr/bin/env bash
# Usage: retry.sh <owner/repo> <issue> <status-label> <cause>
# One automatic retry of an implement run: comments "<cause>. Retrying once." and re-adds <status-label>
# (removed first, so the App token's `labeled` event starts implement again) with reason:retry, which the next
# status change clears. When reason:retry is already there, or the re-add fails, hands over instead:
# status:needs-human + reason:agent-error first, then the comment (with AGENTKIT_INTERFACE=claude-slack it ends with
# the Comment-button line; Slack threads a comment under the card only once the label is there).
set -euo pipefail
repo=$1 n=$2 label=$3 cause=$4
if ! gh issue view "$n" --repo "$repo" --json labels --jq '.labels[].name' | grep -qx reason:retry; then
  gh issue comment "$n" --repo "$repo" --body "agentkit: $cause. Retrying once." >/dev/null
  if gh issue edit "$n" --repo "$repo" --remove-label "$label" >/dev/null \
    && gh issue edit "$n" --repo "$repo" --add-label "$label" --add-label reason:retry >/dev/null; then exit 0; fi
fi
rc=0
"$(dirname "$0")/set-status.sh" "$repo" "$n" status:needs-human reason:agent-error || rc=$?
msg="agentkit: $cause. Needs a human."
[ "${AGENTKIT_INTERFACE:-}" != claude-slack ] || msg+=$'\n\n'"Answer with the Comment button on this issue's card in Slack."
gh issue comment "$n" --repo "$repo" --body "$msg" >/dev/null
exit "$rc"
