#!/usr/bin/env bash
# Canary: run one known issue through the full lifecycle on a repo whose caller
# workflow tracks this kit's main branch (a scratch repo). Move v1 only after a pass.
# Usage: scripts/canary.sh <owner/repo> [timeout-minutes] [start-label]   (owner/repo may come from AGENTKIT_CANARY)
# start-label defaults to status:ready; status:refining also runs the refine stage first.
# Exit 0 (CANARY PASS) when the issue reaches status:approved (its PR and issue are then closed unmerged), or, with
# AUTO_MERGE=true where approved lasts only a moment, when the gate merged its agent PR and the issue closed as completed.
# The task changes every run (a new stamp in src/canary.js), so it is never already done, and repeated auto-merged
# runs replace one file instead of piling up code. A failed GitHub read is retried, not fatal.
set -euo pipefail
repo=${1:-${AGENTKIT_CANARY:?usage: scripts/canary.sh <owner/repo> (or set AGENTKIT_CANARY)}}
deadline=$(( $(date +%s) + ${2:-45} * 60 ))
start=${3:-status:ready}
stamp=$(date -u +%Y%m%dT%H%MZ)
body="Set \`src/canary.js\` to export \`CANARY = '$stamp'\` (an ES module, like \`src/math.js\`). Create the file if it is
missing and replace any earlier value; change nothing else.

## Acceptance criteria
- [ ] \`src/canary.js\` exports \`CANARY\` equal to \`'$stamp'\`
- [ ] \`test/canary.test.js\` checks that value and \`npm test\` passes"

# a read that GitHub fails (network, 5xx) is tried again, up to 5 times over ~40 s
retry() { local _; for _ in 1 2 3 4 5; do "$@" && return 0; sleep 10; done; return 1; }

url=$(gh issue create --repo "$repo" --title "canary: $stamp" --body "$body" --label "$start")
n=${url##*/}
echo "canary issue: $url"
retry gh workflow run agentkit.yml --repo "$repo" >/dev/null  # dispatch now instead of waiting for the schedule

status="" closed=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  if ! info=$(retry gh issue view "$n" --repo "$repo" --json state,stateReason,labels); then
    echo "$(date -u +%H:%M:%S) #$n GitHub unreachable; trying again"; sleep 30; continue
  fi
  status=$(jq -r '[.labels[].name | select(startswith("status:"))] | join(",")' <<<"$info")
  closed=$(jq -r 'select(.state == "CLOSED") | .stateReason' <<<"$info")
  echo "$(date -u +%H:%M:%S) #$n ${status:-no status}${closed:+ (closed: $closed)}"
  [ -z "$closed" ] || break
  case "$status" in
    status:approved|status:needs-human|status:needs-info) break ;;
  esac
  sleep 30
done

if [ "$status" = status:approved ] && [ -z "$closed" ]; then
  pr=$(retry gh pr list --repo "$repo" --state open --search "head:agent/$n-" --json url --jq '.[0].url // empty')
  echo "pr: ${pr:-none}"
  [ -z "$pr" ] || gh pr close "$pr" --repo "$repo" --delete-branch --comment "canary passed; closing" >/dev/null
  gh issue close "$n" --repo "$repo" --reason "not planned" --comment "canary passed" >/dev/null
  echo "CANARY PASS"
  exit 0
fi
if [ "$closed" = COMPLETED ]; then
  pr=$(retry gh pr list --repo "$repo" --state merged --search "head:agent/$n-" --json url --jq '.[0].url // empty')
  echo "pr: ${pr:-none}"
  if [ -n "$pr" ]; then echo "CANARY PASS (merged by the gate)"; exit 0; fi
fi
echo "CANARY FAIL: #$n ended at '${status:-no status}'${closed:+, closed as $closed} (left for inspection)"
exit 1
