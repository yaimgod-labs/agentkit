---
description: Show the project board (status, estimates, next 5 tasks in dispatch order) and reorder it
argument-hint: [n | move <n> <pos> | unblock <n> | done <n>]
---

`$ARGUMENTS` picks the mode. `B=${CLAUDE_PLUGIN_ROOT}/scripts/board.py`. The person never opens GitHub: print what they need to act on, nothing more.

## Common data (no argument and `move`)

Run in one Bash call, `$T` a fresh `mktemp -d`. `REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)`, `OWNER=${REPO%/*}`, `PROJ=$(gh variable get AGENTKIT_PROJECT 2>/dev/null || true)`.

1. Open issues: `gh issue list --state open --limit 500 --json number,title,labels,author --jq 'map({number,title,author:.author.login,labels:[.labels[].name]})' >$T/open.json`
2. Ranks (the board's `Rank` number): if `PROJ` is empty, or the command fails, or the board has no Rank field, every rank is null and `ranks.json` is `{}`. Otherwise
   `gh project item-list "$PROJ" --owner "$OWNER" --limit 1000 --format json | jq -c --arg repo "$REPO" '[.items[]|select(.content.type=="Issue" and .content.repository==$repo and .rank!=null)|{key:(.content.number|tostring),value:.rank}]|from_entries' >$T/ranks.json`
3. Debt due, the dispatcher's rule (`debt-every 4` and `type:debt` are the caller defaults; a project can override them in its caller `with:`, which `/board` cannot see):
   ```
   open=$(gh api "repos/$REPO/issues?state=open&per_page=100" --jq '[.[] | select(.pull_request | not) | [.labels[].name]]')
   closed=$(gh api "repos/$REPO/issues?state=closed&sort=updated&direction=desc&per_page=50" --jq '[.[] | select(.pull_request | not)] | sort_by(.closed_at) | reverse | map({labels: [.labels[].name], closed_at, state_reason})')
   due=$(jq -n --argjson open "$open" --argjson closed "$closed" '{open: $open, closed: $closed}' | python3 $B debt-due --every 4 --debt-label type:debt)
   ```
4. Issues with ranks: `jq 'map(. + {rank: ($r[0][.number|tostring] // null)})' --slurpfile r $T/ranks.json $T/open.json`

## No argument

Also gather (same Bash call), then print the output of `render` exactly as it is: no summary, no extra text.

- Dependencies, for each open issue that has a `status:` label other than `status:backlog`: `gh api "repos/$REPO/issues/$n/dependencies/blocked_by" --jq '[.[]|select(.state=="open")|.number]'` is `waiting_on`; `.../dependencies/blocking` with `--jq '[.[].number]'` is `holds_up`. A failed call counts as none. `deps` is `{"<n>": {"waiting_on": [...], "holds_up": [...]}}`.
- Block reasons, for each issue labelled `status:blocked`: `gh api "repos/$REPO/issues/$n/comments?per_page=100" --paginate | jq -sc '[.[][]|select(.body|contains("<!-- agentkit:block -->"))|.body|sub("<!-- agentkit:block -->";"")|sub("^\\s+";"")|sub("\\s+$";"")]|.[-2:]'` is the issue's `block_reasons` (the latest 2, marker stripped).
- Closed samples: `SINCE` = now minus 60 days (`python3 -c 'import datetime as d;print((d.datetime.now(d.timezone.utc)-d.timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"))'`). `gh api --paginate "repos/$REPO/issues?state=closed&since=$SINCE&per_page=100" | jq -sc --arg s "$SINCE" '[.[][]|select((.pull_request|not) and .state_reason=="completed" and .closed_at>=$s)|{number,closed_at,size:(([.labels[].name|select(startswith("size:"))]|first)//null)}|select(.size)]|sort_by(.closed_at)|reverse|group_by(.size)|map(.[:30])|add // []'`. For each, `started_at` is the first `status:in-progress` event: `gh api "repos/$REPO/issues/$n/events?per_page=100" --paginate | jq -sc '[.[][]|select(.event=="labeled" and .label.name=="status:in-progress")|.created_at]|sort|first'`. Drop the ones with none.
- `estimate` input: `{"closed": [{"size","started_at","closed_at"}...], "open": [{"number","size"}...]}`, `open` from the open issues (`size` is the `size:*` label or null). `estimates=$(python3 $B estimate)`.
- `render` input: `{"issues": [{number,title,labels,rank,author,block_reasons}...], "deps": ..., "estimates": ..., "order": {"debt_due": $due, "debt_every": 4, "debt_label": "type:debt"}}`. `python3 $B render`.

## `<n>`

`gh issue view <n> --json title,body,labels,comments`, and the linked PR: `gh pr list --state all --search "<n> in:body" --json number,title,state,body --limit 5`, the one whose body has `Closes #<n>`. Summarize under the headings Status, What it is, Where it stands, What is needed from you. Add the estimate if `render` knows it. Latest 2 `<!-- agentkit:block -->` comments are the block reasons.

## `move <n> <pos>`

If `PROJ` is empty: print `no board configured: run gh agentkit setup` and change nothing. Likewise if the board has no Rank field (`gh project field-list "$PROJ" --owner "$OWNER" --format json --jq '.fields[]|select(.name=="Rank").id'` is empty): print `board has no Rank field: run gh agentkit upgrade $REPO` and stop.

1. Do the common data, but only for issues labelled `status:ready`. `python3 $B order --debt-due "$due" --debt-every 4 --debt-label type:debt <issues-with-ranks.json` is the current order: ranked first, then the rest. If `<n>` is not in it (not ready, `mode:human`, `size:m` or `size:l`), say so and stop.
2. New list = the order without `<n>`, with `<n>` inserted at `<pos>` (1-based, capped at the end). `k = max(pos, ranked)`, where `ranked` is the number of issues in the list that have a rank, counting `<n>`; k is capped at the list length. Rank values `1..k` go to the first k issues of the new list, so everything above `<n>` keeps its relative order and the rest follow it. Skip an issue whose rank already equals its new value.
3. Ids: project `gh project view "$PROJ" --owner "$OWNER" --format json --jq .id`; Rank field `gh project field-list "$PROJ" --owner "$OWNER" --format json --jq '.fields[]|select(.name=="Rank").id'`; items `gh project item-list "$PROJ" --owner "$OWNER" --limit 1000 --format json --jq '.items[]|select(.content.type=="Issue" and .content.repository=="'"$REPO"'")|{id,number:.content.number}'`. An issue not on the board yet: `gh project item-add "$PROJ" --owner "$OWNER" --url <issue url> --format json --jq .id`.
4. Write each: `gh project item-edit --id <item-id> --project-id <project-id> --field-id <rank-field-id> --number <v>`.
5. Print "#<n> is now <pos> in Up next" (or the real position if capped) and the first 5 of the new order as `#n title`.

## `unblock <n>`

`gh issue edit <n> --remove-label status:blocked --remove-label waiting:you --add-label status:refining`. Print "#<n> unblocked: back to refining".

## `done <n>`

Only for `mode:human`: check `gh issue view <n> --json labels --jq '[.labels[].name]|index("mode:human")'` is not null, otherwise say the issue is not a human task and stop. Then `gh issue close <n> --reason completed`. Print "#<n> closed".
