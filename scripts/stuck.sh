#!/usr/bin/env bash
# Usage: stuck.sh <owner/repo> [minutes]   (default 90)
# Prints "<issue> <label>" for each open issue whose status:in-progress or status:changes-requested label was
# added more than <minutes> ago and that has no unfinished `issues` run titled like it: its implement run
# died with the runner, so no step was left to hand it over.
set -euo pipefail
repo=$1 max=${2:-90}
# a caller run started by an issue event is titled with the issue's title; any unfinished one (implement, or
# a short dispatch run) skips the issue until the next sweep
# ponytail: only the newest 100 `issues` runs; an older one still queued is missed on a very busy repo
active=$(gh api "repos/$repo/actions/runs?event=issues&per_page=100" --jq '.workflow_runs[] | select(.status != "completed") | .display_title')
for label in status:in-progress status:changes-requested; do
  while IFS=$'\t' read -r n title; do
    [ -n "$n" ] || continue
    if [ -n "$active" ] && grep -qxF -- "$title" <<<"$active"; then continue; fi
    since=$(L=$label gh api --paginate "repos/$repo/issues/$n/events" \
      --jq '[.[] | select(.event == "labeled" and .label.name == env.L)] | last | .created_at // empty' | tail -n 1)
    [ -n "$since" ] || continue
    if jq -en --arg t "$since" --argjson m "$max" '(now - ($t | fromdateiso8601)) > $m * 60' >/dev/null; then echo "$n $label"; fi
  done < <(gh issue list --repo "$repo" --state open --label "$label" --limit 200 --json number,title --jq '.[] | "\(.number)\t\(.title)"')
done
