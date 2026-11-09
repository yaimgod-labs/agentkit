#!/usr/bin/env bash
# Usage: card.sh <owner/repo> <issue> post|refold
# Slack bot mode, the GitHub side of scripts/card.py (the chief of staff: it only holds a card back or folds it, and
# never answers for anyone). Env: AGENTKIT_BOT (<app-slug>[bot]), SLACK_CHANNEL, SLACK_BOT_TOKEN, AGENTKIT_APP_KEY
# (people.sh counts verified Slack reply records with it).
#   post    the card for an issue that waits (open, action:required). Nothing when a person with write access already
#           commented after the kit's latest ask (the reply job has it). Else, when another waiting issue in the same
#           blocker chain (same parent issue, or a blocked_by issue in common) has a live card, that card gets an
#           "Also affects #n" line and the issue a fold marker naming it; else a card of its own and its marker.
#   refold  after the issue's cards were resolved: `post` for each waiting issue that was folded into one of them.
# Only the kit's own comments count as asks and markers. A failed chain read means no fold (a card of its own).
set -euo pipefail
repo=$1 n=$2 mode=$3
here=$(cd "$(dirname "$0")" && pwd)
: "${AGENTKIT_BOT:?set AGENTKIT_BOT to the bot login of the kit (<app-slug>[bot])}"
[[ $n =~ ^[1-9][0-9]*$ ]] || { echo "card.sh: issue must be a number, got '$n'" >&2; exit 2; }

kit() {  # the kit's comments on an issue, oldest first, as a JSON array [{id, body}]
  gh api --paginate "repos/$repo/issues/$1/comments" --jq '[.[] | select(.user.login == env.AGENTKIT_BOT) | {id, body}]' | jq -sc 'add // []'
}
# the open waiting issues with their kit comment bodies (gh issue list names an App by its slug, without [bot])
waiting() {
  gh issue list --repo "$repo" --label action:required --state open --limit 100 --json number,title,labels,comments \
    --jq '[.[] | {number, title, labels: [.labels[].name],
                 comments: [.comments[] | select(.author.login + "[bot]" == env.AGENTKIT_BOT or .author.login == env.AGENTKIT_BOT) | .body]}]'
}

if [ "$mode" = refold ]; then
  mine=$(kit "$n" | jq -c 'map(.body)')
  for o in $(jq -nc --argjson c "$mine" --argjson w "$(waiting)" '{comments: $c, waiting: $w}' | python3 "$here/card.py" orphans); do
    echo "#$o was folded into #$n's card"
    "$here/card.sh" "$repo" "$o" post
  done
  exit 0
fi
[ "$mode" = post ] || { echo "usage: card.sh <owner/repo> <issue> post|refold" >&2; exit 2; }

issue=$(gh issue view "$n" --repo "$repo" --json state,title,labels)
[ "$(jq -r .state <<<"$issue")" = OPEN ] || { echo "#$n is closed; no card"; exit 0; }
jq -e '[.labels[].name] | index("action:required")' <<<"$issue" >/dev/null || { echo "#$n no longer waits; no card"; exit 0; }
mine=$(kit "$n")

# no re-asking: a person's comment after the kit's latest ask is the reply job's. A failed read asks anyway
people=$("$here/people.sh" "$repo" "$n" "$AGENTKIT_BOT") || { echo "::warning::#$n: could not read people's comments"; people='[]'; }
if [ "$(jq -nc --argjson kit "$mine" --argjson people "$people" '{kit: $kit, people: $people}' | python3 "$here/card.py" answered)" = true ]; then
  echo "#$n: a person already answered the kit's latest ask; no card"; exit 0
fi

chain() {  # {parent, blockers} of an issue, as URLs. A missing parent is a 404; any failed read is an empty chain
  local p b
  p=$(gh api "repos/$repo/issues/$1/parent" --jq .html_url 2>/dev/null) || p=
  b=$(gh api --paginate "repos/$repo/issues/$1/dependencies/blocked_by" --jq '.[].html_url' | jq -Rsc 'split("\n") - [""]') || b='[]'
  jq -nc --arg p "$p" --argjson b "$b" '{parent: (if $p == "" then null else $p end), blockers: $b}'
}
# the chain of every other waiting issue that has a card marker (only those can be folded into or listed)
others='[]'
while read -r w; do
  [ -n "$w" ] || continue
  others=$(jq -c --argjson w "$w" --argjson c "$(chain "$(jq -r .number <<<"$w")")" '. + [$w + $c]' <<<"$others")
done < <(waiting | N=$n jq -c '.[] | select(.number != (env.N | tonumber) and any(.comments[]; startswith("<!-- agentkit:card ")))')
fold=$(jq -nc --arg repo "$repo" --argjson n "$n" --argjson c "$(chain "$n")" --argjson w "$others" \
  '{repo: $repo, number: $n, waiting: $w} + $c' | python3 "$here/card.py" fold)

if [ "$fold" != null ]; then
  of=$(jq -r .of <<<"$fold")
  # the marker first, so a resolve of #$of that starts now finds this issue and gives it its own card
  jq -r .marker <<<"$fold" | gh issue comment "$n" --repo "$repo" --body-file - >/dev/null
  jq -c '{channel, ts, card}' <<<"$fold" | python3 "$here/card.py" update
  # #$of may have stopped waiting meanwhile, its resolve run before the marker: resolve its cards again (the update
  # put its buttons back) and post this issue's own card below. Worst case two cards for one issue, never none
  p=$(gh issue view "$of" --repo "$repo" --json state,stateReason,title,labels,comments)
  if [ "$(jq -r .state <<<"$p")" = OPEN ] && jq -e '[.labels[].name] | index("action:required")' <<<"$p" >/dev/null; then
    echo "#$n folded into #$of's card"; exit 0
  fi
  jq -c --arg repo "$repo" --argjson n "$of" '{repo: $repo, number: $n, title, state, stateReason, labels: [.labels[].name],
      comments: [.comments[] | select(.author.login + "[bot]" == env.AGENTKIT_BOT or .author.login == env.AGENTKIT_BOT) | .body]}' <<<"$p" \
    | python3 "$here/card.py" resolve >/dev/null
fi

ts=$(jq -c --arg repo "$repo" --argjson n "$n" --argjson kit "$mine" \
  '{repo: $repo, number: $n, title, labels: [.labels[].name], comments: [$kit[].body]}' <<<"$issue" \
  | python3 "$here/card.py" post)
jq -n --arg ts "$ts" '$ts' | python3 "$here/card.py" marker | gh issue comment "$n" --repo "$repo" --body-file - >/dev/null
echo "#$n: card posted"
