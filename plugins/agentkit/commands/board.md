---
description: Show the project board (status, estimates, next 5 tasks in dispatch order) and reorder it
argument-hint: [n | move <n> <pos> | unblock <n> | unlink <n> <b> | done <n>]
---

`$ARGUMENTS` picks the mode. The person never opens GitHub: print what they need to act on, nothing more.

## Preamble (every mode)

Shell variables do not carry over between Bash calls, so start every Bash call with:

```
REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
OWNER=${REPO%/*}
PROJ=$(gh variable get AGENTKIT_PROJECT 2>/dev/null || true)
B="${CLAUDE_PLUGIN_ROOT}/scripts/board.py"
T=$(mktemp -d)   # once; reuse the same directory in later calls
read -r EVERY DEBT < <(python3 "$B" debt-config "$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.github/workflows/agentkit.yml")
```

`EVERY` and `DEBT` are the dispatcher's `debt-every` and `debt-label`: the dispatch job's `with:` in the project's caller when set there, else `4` and `type:debt`.

## Common data (no argument and `move`)

Run in one Bash call.

1. Open issues: `gh issue list --state open --limit 500 --json number,title,labels,author --jq 'map({number,title,author:.author.login,labels:[.labels[].name]})' >"$T/open.json"`
2. Ranks (the board's `Rank` number): if `PROJ` is empty, or the board has no Rank field, every rank is null and `ranks.json` is `{}`. Otherwise
   `gh project item-list "$PROJ" --owner "$OWNER" --limit 1000 --format json | jq -c --arg repo "$REPO" '[.items[]|select(.content.type=="Issue" and .content.repository==$repo and .rank!=null)|{key:(.content.number|tostring),value:.rank}]|from_entries' >"$T/ranks.json"`.
   If that command fails while `PROJ` is set, `ranks.json` is `{}` and the warning is `could not read the board's Rank field, so Up next ignores the manual order: run gh auth refresh -s project` (render's `warnings`; `move` prints it and stops).
3. Debt due, the dispatcher's rule:
   ```
   open=$(gh api "repos/$REPO/issues?state=open&per_page=100" --jq '[.[] | select(.pull_request | not) | [.labels[].name]]')
   closed=$(gh api "repos/$REPO/issues?state=closed&sort=updated&direction=desc&per_page=50" --jq '[.[] | select(.pull_request | not)] | sort_by(.closed_at) | reverse | map({labels: [.labels[].name], closed_at, state_reason})')
   due=$(jq -n --argjson open "$open" --argjson closed "$closed" '{open: $open, closed: $closed}' | python3 "$B" debt-due --every "$EVERY" --debt-label "$DEBT")
   ```
4. Issues with ranks: `jq 'map(. + {rank: ($r[0][.number|tostring] // null)})' --slurpfile r "$T/ranks.json" "$T/open.json" >"$T/ranked.json"`

Up next is the dispatcher's pick order with one difference: it skips the dispatcher's author-trust filter, so an issue by someone without write access can show here while the dispatcher passes over it (rare on your own repo).

## No argument

Also gather (same Bash call), then print the output of `render` exactly as it is: no summary, no extra text.

- Dependencies, for each open issue that has a `status:` label other than `status:backlog`: `gh api "repos/$REPO/issues/$n/dependencies/blocked_by" --jq '[.[]|select(.state=="open")|.number]'` is `waiting_on`; `.../dependencies/blocking` with `--jq '[.[]|select(.state=="open")|.number]'` is `holds_up`. A failed call counts as none. `deps` is `{"<n>": {"waiting_on": [...], "holds_up": [...]}}`.
- Block reasons, for each issue labelled `status:blocked`: `gh api "repos/$REPO/issues/$n/comments?per_page=100" --paginate | jq -sc '[.[][]|select(.body|contains("<!-- agentkit:block -->"))|.body|sub("<!-- agentkit:block -->";"")|sub("^\\s+";"")|sub("\\s+$";"")]|.[-2:]'` is the issue's `block_reasons` (the latest 2, marker stripped).
- Closed samples: `SINCE` = now minus 60 days (`python3 -c 'import datetime as d;print((d.datetime.now(d.timezone.utc)-d.timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ"))'`). `gh api --paginate "repos/$REPO/issues?state=closed&since=$SINCE&per_page=100" | jq -sc --arg s "$SINCE" '[.[][]|select((.pull_request|not) and .state_reason=="completed" and .closed_at>=$s)|{number,closed_at,size:(([.labels[].name|select(startswith("size:"))]|first)//null)}|select(.size)]|sort_by(.closed_at)|reverse|group_by(.size)|map(.[:30])|add // []'`. For each, `started_at` is the first `status:in-progress` event: `gh api "repos/$REPO/issues/$n/events?per_page=100" --paginate | jq -sc '[.[][]|select(.event=="labeled" and .label.name=="status:in-progress")|.created_at]|sort|first'`. Drop the ones with none.
- `estimate` input: `{"closed": [{"size","started_at","closed_at"}...], "open": [{"number","size"}...]}`, `open` from the open issues (`size` is the `size:*` label or null). `estimates=$(python3 "$B" estimate)`.
- `render` input: `{"issues": [{number,title,labels,rank,author,block_reasons}...], "deps": ..., "estimates": ..., "order": {"debt_due": $due, "debt_every": $EVERY, "debt_label": $DEBT}, "warnings": [...]}`. `python3 "$B" render`. Up next leaves out a ready issue with open blockers (listed after it as `Held`) and a `size:m`/`size:l` one (`Not taken`), as the dispatcher does.

## `<n>`

`gh issue view <n> --json title,body,labels,comments`, and the linked PR: `gh pr list --state all --search "<n> in:body" --json number,title,state,body --limit 5`, the one whose body has `Closes #<n>`. Summarize under the headings Status, What it is, Where it stands, What is needed from you. Add its estimate: gather the closed samples as in "No argument" and run `python3 "$B" estimate` with `open` = `[{"number": <n>, "size": <its size: label or null>}]`; no entry means no estimate. Latest 2 `<!-- agentkit:block -->` comments are the block reasons.

## `move <n> <pos>`

If `PROJ` is empty: print `no board configured: run gh agentkit setup` and change nothing. Likewise if the board has no Rank field (`gh project field-list "$PROJ" --owner "$OWNER" --format json --jq '.fields[]|select(.name=="Rank").id'` is empty): print `board has no Rank field: run gh agentkit upgrade $REPO` and stop.

1. Do the common data, but only for issues labelled `status:ready`, and give each one its open blockers: `waiting_on` from `gh api "repos/$REPO/issues/$n/dependencies/blocked_by" --jq '[.[]|select(.state=="open")|.number]'` (a failed call counts as none), merged into `ranked.json`. `python3 "$B" order --debt-due "$due" --debt-every "$EVERY" --debt-label "$DEBT" <"$T/ranked.json"` is the current order, the same list Up next shows: ranked first, then the rest. If `<n>` is not in it (not ready, `mode:human`, `size:m`, `size:l`, or waiting on an open blocker), say which and stop.
2. New list = the order without `<n>`, with `<n>` inserted at `<pos>` (1-based, capped at the end). `k = max(pos, ranked)`, where `ranked` is the number of issues in the list that have a rank, counting `<n>`; k is capped at the list length. Rank values `1..k` go to the first k issues of the new list, so everything above `<n>` keeps its relative order and the rest follow it. Skip an issue whose rank already equals its new value.
3. Ids: project `gh project view "$PROJ" --owner "$OWNER" --format json --jq .id`; Rank field `gh project field-list "$PROJ" --owner "$OWNER" --format json --jq '.fields[]|select(.name=="Rank").id'`; items `gh project item-list "$PROJ" --owner "$OWNER" --limit 1000 --format json --jq '.items[]|select(.content.type=="Issue" and .content.repository=="'"$REPO"'")|{id,number:.content.number}'`. An issue not on the board yet: `gh project item-add "$PROJ" --owner "$OWNER" --url <issue url> --format json --jq .id`.
4. Write each: `gh project item-edit --id <item-id> --project-id <project-id> --field-id <rank-field-id> --number <v>`.
5. Print "#<n> is now <pos> in Up next" (or the real position if capped) and the first 5 of the new order as `#n title`.

## `unblock <n>`

This repeats `scripts/set-status.sh`'s rule (exactly one `status:*`, at most one `reason:*`) because that script ships with the kit's CI scripts, not the plugin.

1. `gh issue view <n> --json labels --jq '[.labels[].name]'`. If `status:blocked` is not among them, print "#<n> is not blocked (status: <its status:* label, or none>)" and change nothing.
2. Otherwise ONE edit: `gh issue edit <n>` with `--remove-label <l>` for every `status:*` label present except `status:refining`, every `reason:*` label and `waiting:you` if present, plus `--add-label status:refining` unless it is already there. Print "#<n> unblocked: back to refining".

A dropped dependency's block comment stays on the issue, and that comment is what tells the dispatcher the person has seen it, so the dropped blocker no longer holds the issue.

## `unlink <n> <b>`

`#<b>` is not a real prerequisite of `#<n>` (for example one refine added).

1. `id=$(gh api "repos/$REPO/issues/<b>" --jq .id)`, then `gh api -X DELETE "repos/$REPO/issues/<n>/dependencies/blocked_by/$id"`. If that fails, say `#<b> is not a blocker of #<n>` (or the error) and stop.
2. Record it, so CI refine never adds it back: `gh issue comment <n> --body "<!-- agentkit:unlinked #<b> -->
#<b> is no longer a blocker of this issue."`
3. Print "#<n> no longer waits on #<b>".

## `done <n>`

Only for `mode:human`: check `gh issue view <n> --json labels --jq '[.labels[].name]|index("mode:human")'` is not null, otherwise say the issue is not a human task and stop. Then `gh issue close <n> --reason completed`. Print "#<n> closed".
