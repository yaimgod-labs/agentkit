#!/usr/bin/env bash
# Usage: block-dependent.sh <owner/repo> <issue> <dropped-blocker> <blocker-title> [--comment-only]
# The one record that <issue> is held by a dropped blocker (closed, not completed): status:blocked, then a block
# comment naming the blocker. --comment-only posts the comment and leaves the status alone (an issue already in work).
# Does nothing when the issue already has a block comment for this blocker, so a retry never posts twice and a
# person's `/board unblock` sticks. Prints the issue number when it wrote anything.
# The status goes first, so a block comment on the issue always means the status was set (or deliberately left).
set -euo pipefail
repo=$1 n=$2 b=$3 title=$4 mode=${5:-}
here=$(cd "$(dirname "$0")" && pwd)
# Only the kit's own comments count: anyone who can comment could otherwise post this text first and let the issue start.
: "${AGENTKIT_BOT:?set AGENTKIT_BOT to the bot login of the kit (<app-slug>[bot])}"
# capture first so an API error stops the script before any write (fail closed)
seen=$(gh api --paginate "repos/$repo/issues/$n/comments" \
  --jq '.[] | select(.user.login == env.AGENTKIT_BOT and (.body | contains("<!-- agentkit:block -->"))) | .body')
if grep -qF "dropped dependency: #$b " <<<"$seen"; then exit 0; fi
[ "$mode" = --comment-only ] || "$here/set-status.sh" "$repo" "$n" status:blocked
gh issue comment "$n" --repo "$repo" --body "<!-- agentkit:block -->
**Blocked:** dropped dependency: #$b ($title)" >/dev/null
echo "$n"
