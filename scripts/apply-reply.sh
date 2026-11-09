#!/usr/bin/env bash
# Usage: apply-reply.sh <owner/repo> <issue> <action> <arg> <login>
# Carries out one Slack reply (Claude Code + Slack mode): <action> and <arg> come from reply.py, <login> is the person
# who answered, or the kit's bot (<app-slug>[bot]) when an agent starts research itself. Env COMMENT_ID, the id of the
# person's issue comment this reply is, for `retry`/`guide` with the agent PR (the reset-rounds marker names it, and the
# review gate counts a reset only for a write-access person's comment, once). Env KEYWORDS
# (space-separated) and FREE_TEXT (true|false, default false), both from reply.py, for
# `hint`; AGENTKIT_BOT (<app-slug>[bot]) for `approve-research`, which reads the kit's own recommendation comment.
#   answer              with the agent PR open (a question asked in a fix round): status:changes-requested;
#                       without: status:refining
#   unblock, split-feedback  status:refining
#   research <q>        new type:research issue (status:refining) linked as a blocker; a block comment; status:blocked
#   block <reason>      a block comment; status:blocked
#   replace <b>         #b (an open issue here, not this one) becomes a blocker; status:ready
#   retry, guide <t>    with the agent PR: a reset-rounds comment on it (and the guidance), status:changes-requested;
#                       without: status:refining (the guidance is the person's own comment, which refine reads)
#   verified            ticks the boxes under the PR's Human verification heading (dispatch then approves it)
#   failed-check <t>    the text on the PR; status:changes-requested
#   approve-research    status:approved, then merges the research PR; its parent (`<!-- agentkit:research-for #p -->`) gets the
#                       recommendation and status:refining
#   override-research <t>  unlinks the research from its parent, closes its PR and the issue (not planned), the parent
#                       gets the answer and status:refining
#   decide <accept [why]|reject why>  a /decide comment on the RFC PR (a bare accept notes no reason given)
#   approve-split       a /plan comment
#   done                clears its status, then closes the issue as completed
#   close <why>         a comment with the person's reason, clears its status, then closes the issue: completed when
#                       the reason starts with "done" or "already" (the work exists), not planned otherwise
#   hint [word]         a comment listing the valid keywords; no label change
#   none, or anything else: nothing.
# The person's text is data: it reaches gh only on stdin (--body-file -, --input -) or through jq --arg/env. It can
# never forge a kit marker: `<!--` in it is escaped, and it never starts a line of a kit comment (it is quoted as a
# blockquote, or collapsed onto the kit's own line). A reply over 60000 characters gets one comment and nothing else.
# Every read comes before the first write and any error stops the script (fail closed); a read helper returns
# non-zero on a failed read, so `x=$(helper)` stops the script too.
set -euo pipefail
repo=$1 n=$2 action=$3 arg=${4:-} login=${5:-}
here=$(cd "$(dirname "$0")" && pwd)
button="Answer with the Comment button on this issue's card in Slack."
case "$action" in
  answer | research | block | unblock | replace | retry | guide | verified | failed-check | approve-research | \
    override-research | decide | approve-split | split-feedback | done | close | hint) ;;
  none) exit 0 ;;
  *) echo "apply-reply.sh: unknown action '$action'; nothing done" >&2; exit 0 ;;
esac
usage() { echo "apply-reply.sh: $1" >&2; exit 2; }
[[ $n =~ ^[1-9][0-9]*$ ]] || usage "issue must be a number, got '$n'"
[[ $login =~ ^[A-Za-z0-9][A-Za-z0-9-]*(\[bot\])?$ ]] || usage "invalid login '$login'"

# the person's text on one line, or as a blockquote; `<!--` escaped in both
one_line() { jq -rn --arg t "$1" '$t | gsub("<!--"; "&lt;!--") | gsub("\\s+"; " ") | sub("^ "; "") | sub(" $"; "")'; }
quoted() { jq -rn --arg t "$1" '$t | gsub("<!--"; "&lt;!--") | split("\n") | map("> " + .) | join("\n")'; }
unmark() { jq -rn --arg t "$1" '$t | gsub("<!--"; "&lt;!--")'; }
chars() { jq -rn --arg t "$1" '$t | length'; }
larg=$(one_line "$arg")
qarg=$(quoted "$arg")
case "$action" in
  research | block | guide | failed-check | override-research | decide | close) [ -n "$larg" ] || usage "$action needs text" ;;
esac
len=$(chars "$arg")
qlen=$(chars "$qarg")

status() { "$here/set-status.sh" "$repo" "$1" "$2"; }
comment() { printf '%s\n' "$2" | gh issue comment "$1" --repo "$repo" --body-file - >/dev/null; }
pr_comment() { printf '%s\n' "$2" | gh pr comment "$1" --repo "$repo" --body-file - >/dev/null; }
# the open agent PR of the issue (the search is fuzzy, so the head prefix is checked exactly)
agent_pr() {
  gh pr list --repo "$repo" --state open --search "head:agent/$n-" --json number,headRefName \
    --jq '[.[]|select(.headRefName|startswith("agent/'"$n"'-"))][0].number // empty'
}
# the issue a research issue answers, from the body's last marker (the kit appends it); empty when there is none
parent() {
  local p
  p=$(gh issue view "$n" --repo "$repo" --json body \
    --jq '[.body | scan("<!-- agentkit:research-for #([1-9][0-9]*) -->")] | last | .[0] // empty') || return 1
  [ "$p" = "$n" ] || echo "$p"
}

# the comment limit is 65536 characters; the quoted form is checked too, as "> " lengthens every line
if [ "$len" -gt 60000 ] || [ "$qlen" -gt 65000 ]; then
  comment "$n" "agentkit: that reply is too long (over 60000 characters); shorten it and answer again."
  exit 0
fi

case "$action" in
  answer)
    pr=$(agent_pr)
    if [ -n "$pr" ]; then status "$n" status:changes-requested; else status "$n" status:refining; fi ;;

  unblock | split-feedback) status "$n" status:refining ;;

  block)
    comment "$n" "<!-- agentkit:block -->
**Blocked by @$login:** $larg"
    status "$n" status:blocked ;;

  research)
    req=$(jq -nc --arg l "$larg" --arg q "$qarg" --arg login "$login" --argjson n "$n" '{
      title: ("Research: " + ($l | .[:80] | sub(" $"; ""))),
      body: "## Question\n\($q)\n\nAsked by @\($login) on #\($n).\n\n## Acceptance criteria\n- [ ] The doc answers the question with a recommendation and its confidence\n- [ ] It names what was checked (sources, code, measurements)\n\n<!-- agentkit:research-for #\($n) -->",
      labels: ["type:research", "status:refining"]}')
    # one call creates the issue and returns both its number and its id (the dependency API takes the id)
    created=$(printf '%s\n' "$req" | gh api "repos/$repo/issues" --input - --jq '"\(.number) \(.id)"')
    read -r r rid <<<"$created"
    [[ $r =~ ^[0-9]+$ && $rid =~ ^[0-9]+$ ]] || { echo "apply-reply.sh: unexpected create answer '$created'" >&2; exit 1; }
    # an unlinked research issue would not hold #n: close it again (best effort) and fail
    if ! gh api "repos/$repo/issues/$n/dependencies/blocked_by" -F issue_id="$rid" >/dev/null; then
      gh issue close "$r" --repo "$repo" --reason "not planned" --comment "agentkit: could not link this to #$n; closing." >/dev/null || true
      exit 1
    fi
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
    if [ -z "$pr" ]; then status "$n" status:refining; exit 0; fi
    cid=${COMMENT_ID:-}
    [[ $cid =~ ^[1-9][0-9]*$ ]] || usage "$action with a PR needs COMMENT_ID (the person's comment id), got '$cid'"
    if [ "$action" = guide ]; then
      pr_comment "$pr" "<!-- agentkit:reset-rounds $cid -->
**Guidance from @$login:**

$qarg"
    else
      pr_comment "$pr" "<!-- agentkit:reset-rounds $cid -->
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

$qarg"
    status "$n" status:changes-requested ;;

  approve-research)
    : "${AGENTKIT_BOT:?set AGENTKIT_BOT to the bot login of the kit (<app-slug>[bot])}"
    # the kit's latest recommendation comment (only its own: anyone can post the marker); one JSON string per line
    latest=$(gh api --paginate "repos/$repo/issues/$n/comments" \
      --jq '.[] | select(.user.login == env.AGENTKIT_BOT and (.body | startswith("<!-- agentkit:recommendation -->"))) | .body | tojson')
    rec=
    if [ -n "$latest" ]; then
      rec=$(tail -n 1 <<<"$latest" | jq -r . | awk 'stop {next} f && (/^Reply `approve`/ || /^Answer with the Comment button/ || /^\*\*Not verified yet:\*\*/) {stop = 1; next}
                                                    f {print} index($0, "<!-- agentkit:recommendation -->") {f = 1}' | sed '/./,$!d')
      rec=$(unmark "$rec")
    fi
    p=$(parent)
    pr=$(agent_pr)
    [ -n "$pr" ] || { comment "$n" "agentkit: no open PR for #$n to merge."; exit 0; }
    if [ -n "$p" ] && [ -z "$rec" ]; then
      comment "$n" "agentkit: found no recommendation from the kit on #$n, so nothing was merged."; exit 0
    fi
    # approved first: the merge closes the issue, which must not happen while it still waits (an extra Slack card)
    status "$n" status:approved
    "$(dirname "$0")/merge-pr.sh" "$pr" "$repo" >/dev/null
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
    # the status goes first, so the issue never closes while it still waits (an extra Slack card)
    status "$n" ""
    gh issue close "$n" --repo "$repo" --reason "not planned" --comment "Superseded by @$login's answer." >/dev/null
    [ -n "$p" ] || exit 0
    comment "$p" "**Answer from @$login:**

$qarg"
    status "$p" status:refining ;;

  decide)
    case "$larg" in accept) larg="accept (no reason given)" ;; "accept "?* | "reject "?*) ;; *) usage "decide needs 'accept [why]' or 'reject <why>'" ;; esac
    pr=$(agent_pr)
    [ -n "$pr" ] || { comment "$n" "agentkit: no open PR for #$n to decide on."; exit 0; }
    pr_comment "$pr" "/decide $larg (from @$login in Slack)" ;;

  approve-split) comment "$n" "/plan" ;;

  # a closed issue keeps no status (nor action:required), as when its PR merges; cleared first, so the issue never
  # closes while it still waits (an extra Slack card)
  done)
    status "$n" ""
    gh issue close "$n" --repo "$repo" --reason completed >/dev/null ;;

  close)
    reason="not planned"
    case "$(printf '%s' "$larg" | tr '[:upper:]' '[:lower:]')" in done | done[!a-z]* | already | already[!a-z]*) reason=completed ;; esac
    comment "$n" "**Closed by @$login:** $larg"
    status "$n" ""
    gh issue close "$n" --repo "$repo" --reason "$reason" >/dev/null ;;

  hint)
    list='' kws=()
    read -ra kws <<<"${KEYWORDS:-}"
    for k in ${kws[@]+"${kws[@]}"}; do
      [[ $k =~ ^[a-z]+$ ]] || continue
      list="$list${list:+, }\`$k\`"
    done
    # the reply on one line, at most 80 characters, without backticks (so it stays inside its code span)
    shown=$(jq -rn --arg a "$larg" '$a | gsub("`"; "'"'"'") | gsub("\\s+"; " ") | .[:80] | sub("^ +"; "") | sub(" +$"; "")')
    if [ -n "$shown" ]; then msg="agentkit: \`$shown\` doesn't apply to this issue right now."; else msg="agentkit: that reply was empty."; fi
    free=
    [ "${FREE_TEXT:-false}" != true ] || free=1
    if [ -n "$list" ]; then msg="$msg Answer with one of: $list${free:+, or with free text}."
    elif [ -n "$free" ]; then msg="$msg Answer with free text."; fi
    comment "$n" "$msg

$button" ;;
esac
