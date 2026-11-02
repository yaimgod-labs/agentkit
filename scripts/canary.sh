#!/usr/bin/env bash
# Canary: run one known issue through the full lifecycle on a repo whose caller
# workflow tracks this kit's main branch (agentkit-scratch). Move v1 only after a pass.
# Usage: scripts/canary.sh [owner/repo] [timeout-minutes] [start-label]
# start-label defaults to status:ready; status:refining also runs the refine stage first.
# Exit 0 when the issue reaches status:approved; the canary PR and issue are then closed.
set -euo pipefail
repo=${1:-$(gh repo view --json owner --jq .owner.login)/agentkit-scratch}  # default: <kit owner>/agentkit-scratch
deadline=$(( $(date +%s) + ${2:-45} * 60 ))
start=${3:-status:ready}
body='Add `divide(a, b)` next to `multiply` and export it.

## Acceptance criteria
- [ ] `divide(6, 3)` returns `2`
- [ ] `divide(1, 0)` throws an `Error` with message `division by zero`
- [ ] tests cover both cases and `npm test` passes'
url=$(gh issue create --repo "$repo" --title "canary: divide $(date -u +%Y%m%dT%H%MZ)" --body "$body" --label "$start")
n=${url##*/}
echo "canary issue: $url"
gh workflow run agentkit.yml --repo "$repo" >/dev/null  # dispatch now instead of waiting for the schedule

status=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  status=$(gh issue view "$n" --repo "$repo" --json labels --jq '[.labels[].name | select(startswith("status:"))] | join(",")')
  echo "$(date -u +%H:%M:%S) #$n $status"
  case "$status" in
    status:approved|status:needs-human|status:needs-info) break ;;
  esac
  sleep 30
done

pr=$(gh pr list --repo "$repo" --state open --search "head:agent/$n-" --json url --jq '.[0].url // empty')
echo "pr: ${pr:-none}"
if [ "$status" = status:approved ]; then
  [ -z "$pr" ] || gh pr close "$pr" --repo "$repo" --delete-branch --comment "canary passed; closing" >/dev/null
  gh issue close "$n" --repo "$repo" --reason "not planned" --comment "canary passed" >/dev/null
  echo "CANARY PASS"
  exit 0
fi
echo "CANARY FAIL: #$n ended at '${status:-no status}' (left open for inspection)"
exit 1
