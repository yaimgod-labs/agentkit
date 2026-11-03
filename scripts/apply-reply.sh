#!/usr/bin/env bash
# Usage: apply-reply.sh <owner/repo> <issue> <action> <arg> <login>
# Carries out one Slack reply (Claude Code + Slack mode): <action> and <arg> come from reply.py, <login> is the person
# who answered. Env KEYWORDS (space-separated, from reply.py) for `hint`; AGENTKIT_BOT (<app-slug>[bot]) for
# `approve-research`, which reads the kit's own recommendation comment.
#   answer, unblock, split-feedback  status:refining
#   research <q>        new type:research issue (status:refining) linked as a blocker; a block comment; status:blocked
#   block <reason>      a block comment; status:blocked
#   replace <b>         #b (an open issue here, not this one) becomes a blocker; status:ready
#   retry, guide <t>    with the agent PR: a rounds-reset comment on it (and the guidance), status:changes-requested;
#                       without: status:in-progress
#   verified            ticks the boxes under the PR's Human verification heading (dispatch then approves it)
#   failed-check <t>    the text on the PR; status:changes-requested
#   approve-research    merges the research PR; its parent (`<!-- agentkit:research-for #p -->`) gets the
#                       recommendation and status:refining
#   override-research <t>  unlinks the research from its parent, closes its PR and the issue (not planned), the parent
#                       gets the answer and status:refining
#   decide <accept|reject why>  a /decide comment on the RFC PR
#   approve-split       a /plan comment
#   done                closes the issue as completed (and clears its status)
#   hint [word]         a comment listing the valid keywords; no label change
#   none, or anything else: nothing.
# The person's text is data: it reaches gh only on stdin (--body-file -, --input -) or through jq --arg/env.
# Every read comes before the first write and any error stops the script (fail closed).
set -euo pipefail
repo=$1 n=$2 action=$3 arg=${4:-} login=${5:-}
here=$(cd "$(dirname "$0")" && pwd)
button="Answer with the Comment button on this issue's card in Slack."
case "$action" in
  answer | research | block | unblock | replace | retry | guide | verified | failed-check | approve-research | \
    override-research | decide | approve-split | split-feedback | done | hint) ;;
  none) exit 0 ;;
  *) echo "apply-reply.sh: unknown action '$action'; nothing done" >&2; exit 0 ;;
esac
usage() { echo "apply-reply.sh: $1" >&2; exit 2; }
[[ $n =~ ^[1-9][0-9]*$ ]] || usage "issue must be a number, got '$n'"
[[ $login =~ ^[A-Za-z0-9][A-Za-z0-9-]*$ ]] || usage "invalid login '$login'"
case "$action" in
  research | block | guide | failed-check | override-research | decide) [ -n "$arg" ] || usage "$action needs text" ;;
esac

status() { "$here/set-status.sh" "$repo" "$1" "$2"; }
comment() { printf '%s\n' "$2" | gh issue comment "$1" --repo "$repo" --body-file - >/dev/null; }
pr_comment() { printf '%s\n' "$2" | gh pr comment "$1" --repo "$repo" --body-file - >/dev/null; }
# the open agent PR of the issue (the search is fuzzy, so the head prefix is checked exactly)
agent_pr() {
  gh pr list --repo "$repo" --state open --search "head:agent/$n-" --json number,headRefName \
    --jq '[.[]|select(.headRefName|startswith("agent/'"$n"'-"))][0].number // empty'
}
# the issue a research issue answers, from its body marker; empty when there is none
parent() {
  local p
  p=$(gh issue view "$n" --repo "$repo" --json body \
    --jq '[.body | capture("<!-- agentkit:research-for #(?<p>[1-9][0-9]*) -->")][0].p // empty')
  [ "$p" = "$n" ] || echo "$p"
}

case "$action" in
  answer | unblock | split-feedback) status "$n" status:refining ;;

  block)
    comment "$n" "<!-- agentkit:block -->
**Blocked by @$login:** $arg"
    status "$n" status:blocked ;;

  research)
    req=$(jq -nc --arg q "$arg" --arg login "$login" --argjson n "$n" '{
      title: ("Research: " + ($q | gsub("\\s+"; " ") | .[:80] | sub(" $"; ""))),
      body: "## Question\n\($q)\n\nAsked by @\($login) on #\($n).\n\n## Acceptance criteria\n- [ ] The doc answers the question with a recommendation and its confidence\n- [ ] It names what was checked (sources, code, measurements)\n\n<!-- agentkit:research-for #\($n) -->",
      labels: ["type:research", "status:refining"]}')
    # one call creates the issue and returns both its number and its id (the dependency API takes the id)
    created=$(printf '%s\n' "$req" | gh api "repos/$repo/issues" --input - --jq '"\(.number) \(.id)"')
    read -r r rid <<<"$created"
    [[ $r =~ ^[0-9]+$ && $rid =~ ^[0-9]+$ ]] || { echo "apply-reply.sh: unexpected create answer '$created'" >&2; exit 1; }
    gh api "repos/$repo/issues/$n/dependencies/blocked_by" -F issue_id="$rid" >/dev/null
    comment "$n" "<!-- agentkit:block -->
**Blocked:** waiting on research #$r"
    status "$n" status:blocked ;;

  replace)
    [[ $arg =~ ^[1-9][0-9]*$ ]] || usage "replace needs an issue number, got '$arg'"
    id=
    if [ "$arg" != "$n" ]; then
      err=$(mktemp)
      trap 'rm -f "$err"' EXIT
      # only an open issue (not a PR) of this repo; a transferred issue answers from its new repo and is refused
      if ! id=$(REPLY_REPO="$repo" gh api "repos/$repo/issues/$arg" --jq 'select(.state == "open" and .pull_request == null
            and ((.repository_url // "") | ascii_downcase | endswith("/repos/" + (env.REPLY_REPO | ascii_downcase)))) | .id' 2>"$err"); then
        grep -qE 'HTTP (404|410)' "$err" || { cat "$err" >&2; exit 1; }
        id=
      fi
    fi
    if [ -z "$id" ]; then comment "$n" "agentkit: #$arg is not an open issue here."; exit 0; fi
    [[ $id =~ ^[0-9]+$ ]] || { echo "apply-reply.sh: unexpected id '$id' for #$arg" >&2; exit 1; }
    gh api "repos/$repo/issues/$n/dependencies/blocked_by" -F issue_id="$id" >/dev/null
    status "$n" status:ready ;;

  retry | guide)
    pr=$(agent_pr)
    if [ -z "$pr" ]; then status "$n" status:in-progress; exit 0; fi
    if [ "$action" = guide ]; then
      pr_comment "$pr" "<!-- agentkit:rounds-reset -->
**Guidance from @$login:**

$arg"
    else
      pr_comment "$pr" "<!-- agentkit:rounds-reset -->
Retry requested by @$login."
    fi
    status "$n" status:changes-requested ;;

  verified)
    pr=$(agent_pr)
    [ -n "$pr" ] || { comment "$n" "agentkit: no open PR for #$n to verify."; exit 0; }
    body=$(gh pr view "$pr" --repo "$repo" --json body --jq .body)
    # the section rule of checklist.sh, which the dispatch step uses to approve: a heading starting
    # "human verification" (any level, any case) up to the next heading
    new=$(printf '%s\n' "$body" | awk '/^#+ /{hv = (tolower($0) ~ /^#+ human verification/)}
                                       hv && /^[[:space:]]*- \[ \]/{sub(/- \[ \]/, "- [x]")} {print}')
    if [ "$new" = "$body" ]; then comment "$n" "agentkit: PR #$pr has no unticked Human verification items."; exit 0; fi
    printf '%s\n' "$new" | gh pr edit "$pr" --repo "$repo" --body-file - >/dev/null ;;

  failed-check)
    pr=$(agent_pr)
    [ -n "$pr" ] || { comment "$n" "agentkit: no open PR for #$n to send the failed check to."; exit 0; }
    pr_comment "$pr" "**Check failed (from @$login):**

$arg"
    status "$n" status:changes-requested ;;

  approve-research)
    : "${AGENTKIT_BOT:?set AGENTKIT_BOT to the bot login of the kit (<app-slug>[bot])}"
    # the kit's latest recommendation comment (only its own: anyone can post the marker); one JSON string per line
    latest=$(gh api --paginate "repos/$repo/issues/$n/comments" \
      --jq '.[] | select(.user.login == env.AGENTKIT_BOT and (.body | contains("<!-- agentkit:recommendation -->"))) | .body | tojson')
    rec=
    if [ -n "$latest" ]; then
      rec=$(tail -n 1 <<<"$latest" | jq -r . | awk 'stop {next} f && (/^Reply `approve`/ || /^Answer with the Comment button/) {stop = 1; next}
                                                    f {print} index($0, "<!-- agentkit:recommendation -->") {f = 1}' | sed '/./,$!d')
    fi
    p=$(parent)
    pr=$(agent_pr)
    [ -n "$pr" ] || { comment "$n" "agentkit: no open PR for #$n to merge."; exit 0; }
    if [ -n "$p" ] && [ -z "$rec" ]; then
      comment "$n" "agentkit: found no recommendation from the kit on #$n, so nothing was merged."; exit 0
    fi
    gh pr merge "$pr" --repo "$repo" --squash --delete-branch >/dev/null
    [ -n "$p" ] || exit 0
    comment "$p" "**Research #$n recommends:**

$rec"
    status "$p" status:refining ;;

  override-research)
    p=$(parent)
    pr=$(agent_pr)
    linked=
    if [ -n "$p" ]; then
      id=$(gh api "repos/$repo/issues/$n" --jq .id)
      [[ $id =~ ^[0-9]+$ ]] || { echo "apply-reply.sh: unexpected id '$id' for #$n" >&2; exit 1; }
      linked=$(ID=$id gh api --paginate "repos/$repo/issues/$p/dependencies/blocked_by" \
        --jq '.[] | select(.id == (env.ID | tonumber)) | .id')
    fi
    # unlink first: closing the research as not planned must not count as a dropped dependency of the parent
    [ -z "$linked" ] || gh api -X DELETE "repos/$repo/issues/$p/dependencies/blocked_by/$id" >/dev/null
    [ -z "$pr" ] || gh pr close "$pr" --repo "$repo" --delete-branch --comment "Superseded by @$login's answer." >/dev/null
    gh issue close "$n" --repo "$repo" --reason "not planned" --comment "Superseded by @$login's answer." >/dev/null
    status "$n" ""
    [ -n "$p" ] || exit 0
    comment "$p" "**Answer from @$login:**

$arg"
    status "$p" status:refining ;;

  decide)
    case "$arg" in "accept "?* | "reject "?*) ;; *) usage "decide needs 'accept <why>' or 'reject <why>'" ;; esac
    pr=$(agent_pr)
    [ -n "$pr" ] || { comment "$n" "agentkit: no open PR for #$n to decide on."; exit 0; }
    pr_comment "$pr" "/decide $arg (from @$login in Slack)" ;;

  approve-split) comment "$n" "/plan" ;;

  # a closed issue keeps no status (nor action:required), as when its PR merges
  done)
    gh issue close "$n" --repo "$repo" --reason completed >/dev/null
    status "$n" "" ;;

  hint)
    list='' kws=()
    read -ra kws <<<"${KEYWORDS:-}"
    for k in ${kws[@]+"${kws[@]}"}; do
      [[ $k =~ ^[a-z]+$ ]] || continue
      list="$list${list:+, }\`$k\`"
    done
    # the reply on one line, at most 80 characters, without backticks (so it stays inside its code span)
    shown=$(jq -rn --arg a "$arg" '$a | gsub("`"; "'"'"'") | gsub("\\s+"; " ") | .[:80] | sub("^ +"; "") | sub(" +$"; "")')
    if [ -n "$shown" ]; then msg="agentkit: \`$shown\` doesn't apply to this issue right now."; else msg="agentkit: that reply was empty."; fi
    if [ -n "$list" ]; then msg="$msg Answer with one of: $list, or with free text."; else msg="$msg Answer with free text."; fi
    comment "$n" "$msg

$button" ;;
esac
