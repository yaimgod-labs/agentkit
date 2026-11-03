#!/usr/bin/env bash
# apply-reply.sh against a fake gh: each Slack reply action makes its key call(s), and nothing else is written.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# The fake gh logs every call; a body read from stdin (`--body-file -`, `--input -`) follows its call, each line
# prefixed "> ". `--jq` filters run with real jq over the canned JSON:
#   issue view: {labels, body} from $FAKE_LABELS (space-separated) and $FAKE_BODY
#   pr list: $FAKE_PRS (default [])          pr view: {body} from $FAKE_PR_BODY
#   api .../comments: $FAKE_COMMENTS ([])    api .../dependencies/blocked_by: $FAKE_BLOCKED_BY ([]), {} on a write
#   api repos/o/r/issues (create): $FAKE_CREATED   api repos/o/r/issues/<n>: $FAKE_ISSUE
# A call whose command line contains $FAKE_FAIL fails like an API error; issue $FAKE_MISSING answers HTTP 404.
cat >"$tmp/gh" <<'EOF2'
#!/usr/bin/env bash
echo "$*" >>"$FAKE_LOG"
args=("$@")
i=0 filter= ep= stdin=0 write=0 method=GET
while [ "$i" -lt "${#args[@]}" ]; do
  case "${args[$i]}" in
    --jq) i=$((i + 1)); filter=${args[$i]} ;;
    --body-file|--input) [ "${args[$i]}" != --input ] || write=1; i=$((i + 1)); [ "${args[$i]}" != - ] || stdin=1 ;;
    -X) i=$((i + 1)); method=${args[$i]} ;;
    -F|-f) write=1 ;;
    repos/*) ep=${args[$i]} ;;
  esac
  i=$((i + 1))
done
if [ "$stdin" = 1 ]; then sed 's/^/> /' >>"$FAKE_LOG"; fi
if [ -n "${FAKE_FAIL:-}" ]; then case "$*" in *"$FAKE_FAIL"*) echo "gh: Bad Gateway (HTTP 502)" >&2; exit 1 ;; esac; fi
if [ -n "${FAKE_MISSING:-}" ] && [ "$ep" = "repos/o/r/issues/$FAKE_MISSING" ]; then echo "gh: Not Found (HTTP 404)" >&2; exit 1; fi
created='{"number":50,"id":5000}'
issue='{"id":4200,"state":"open","repository_url":"https://api.github.com/repos/o/r"}'
case "$1 $2" in
  "issue view") json=$(jq -n --arg l "${FAKE_LABELS:-}" --arg b "${FAKE_BODY:-}" \
                  '{labels: ($l | split(" ") | map(select(. != "") | {name: .})), body: $b}') ;;
  "pr list") json=${FAKE_PRS:-[]} ;;
  "pr view") json=$(jq -n --arg b "${FAKE_PR_BODY:-}" '{body: $b}') ;;
  api*)
    case "$method $ep" in
      DELETE*) exit 0 ;;
      *"/comments") json=${FAKE_COMMENTS:-[]} ;;
      *"/dependencies/blocked_by") if [ "$write" = 1 ]; then json='{}'; else json=${FAKE_BLOCKED_BY:-[]}; fi ;;
      "GET repos/o/r/issues") json=${FAKE_CREATED:-$created} ;;
      "GET repos/o/r/issues/"*) json=${FAKE_ISSUE:-$issue} ;;
      *) echo "fake gh: no answer for $method $ep" >&2; exit 1 ;;
    esac ;;
  *) exit 0 ;;
esac
if [ -n "$filter" ]; then printf '%s' "$json" | jq -r "$filter"; else printf '%s\n' "$json"; fi
EOF2
chmod +x "$tmp/gh"
export PATH="$tmp:$PATH" FAKE_LOG="$tmp/log" AGENTKIT_BOT="agentkit-bot[bot]"
unset AGENTKIT_INTERFACE KEYWORDS
fail=0
ok() {  # name command...: passes when the command succeeds
  name=$1; shift
  if "$@"; then echo "ok: $name"; else echo "FAIL: $name ($(tr '\n' '|' <"$FAKE_LOG"))"; fail=1; fi
}
logs() { grep -q -- "$1" "$FAKE_LOG"; }
logsF() { local s; for s in "$@"; do grep -qF -- "$s" "$FAKE_LOG" || return 1; done; }   # every string is logged
nolog() { local s; for s in "$@"; do ! grep -q -- "$s" "$FAKE_LOG" || return 1; done; }   # no pattern is
count() { [ "$(grep -c -- "$1" "$FAKE_LOG")" = "$2" ]; }
at() { grep -m1 -n -- "$1" "$FAKE_LOG" | cut -d: -f1; }       # line of the first call matching
before() {  # pattern...: the first call matching each comes in this order
  local a b
  a=$(at "$1"); shift
  for p in "$@"; do b=$(at "$p"); [ -n "$a" ] && [ -n "$b" ] && [ "$a" -lt "$b" ] || return 1; a=$b; done
}
writes='^(issue (comment|edit|close|create)|pr (comment|edit|merge|close)) |^api .*(-X DELETE|-F |--input)'
nowrites() { ! grep -qE -- "$writes" "$FAKE_LOG"; }
apply() { : >"$FAKE_LOG"; "$here/../scripts/apply-reply.sh" o/r 7 "$@"; }
jqe() { jq -e "$@" >/dev/null; }
rc() { if "$@" >/dev/null 2>&1; then echo 0; else echo $?; fi; }
pr12='[{"number":12,"headRefName":"agent/7-fix-login"}]'
button="Answer with the Comment button on this issue's card in Slack."

# none and unknown actions write nothing
apply none "" alice
ok "none: writes nothing" nowrites
apply frobnicate "x" alice 2>/dev/null
ok "unknown action: writes nothing" nowrites

# answer / unblock / split-feedback: back to refining
for a in answer unblock split-feedback; do
  apply "$a" "the second one" alice
  ok "$a: status:refining" count '^issue edit 7 .*--add-label status:refining' 1
  ok "$a: no comment" nolog '^issue comment'
done

# block: the block comment, then status:blocked
apply block "waiting on legal" alice
ok "block: comment on 7" count '^issue comment 7 .*--body-file -' 1
ok "block: comment has the marker" logsF '> <!-- agentkit:block -->'
ok "block: comment names the person and reason" logsF '> **Blocked by @alice:** waiting on legal'
ok "block: status:blocked" count '^issue edit 7 .*--add-label status:blocked' 1
ok "block: comment before status" before '^issue comment 7' '^issue edit 7'

# research: a new type:research issue, linked as a blocker of 7, then 7 blocked
evil='why "it" drops $(touch '"$tmp"'/pwned) `touch '"$tmp"'/pwned2` \n'
apply research "$evil" alice
created=$(sed -n 's/^> {/{/p' "$FAKE_LOG")
ok "research: creates the issue through the API" logs '^api repos/o/r/issues --input -'
ok "research: title" jqe --arg q "$evil" '.title == "Research: " + ($q[:80] | sub(" $"; ""))' <<<"$created"
ok "research: labels" [ "$(jq -c .labels <<<"$created")" = '["type:research","status:refining"]' ]
ok "research: body passes the text unchanged" jqe --arg q "$evil" '.body == "## Question\n\($q)\n\nAsked by @alice on #7.\n\n## Acceptance criteria\n- [ ] The doc answers the question with a recommendation and its confidence\n- [ ] It names what was checked (sources, code, measurements)\n\n<!-- agentkit:research-for #7 -->"' <<<"$created"
ok "research: nothing expanded" test ! -e "$tmp/pwned" -a ! -e "$tmp/pwned2"
ok "research: links #50 as a blocker of 7" logs '^api repos/o/r/issues/7/dependencies/blocked_by -F issue_id=5000'
ok "research: block comment" logsF '> **Blocked:** waiting on research #50'
ok "research: comment has the marker" logsF '> <!-- agentkit:block -->'
ok "research: status:blocked" count '^issue edit 7 .*--add-label status:blocked' 1
ok "research: create, link, comment, status in order" before '^api repos/o/r/issues --input' 'dependencies/blocked_by -F' '^issue comment 7' '^issue edit 7'
long=$(printf 'x%.0s' $(seq 1 100))
apply research "$long
second line" alice
ok "research: title cut to 80 characters of the question, on one line" \
  [ "$(sed -n 's/^> {/{/p' "$FAKE_LOG" | jq -r .title)" = "Research: $(printf 'x%.0s' $(seq 1 80))" ]
ok "research: no text, no write" [ "$(rc apply research "" alice)" != 0 ]
ok "research: no text writes nothing" nowrites
ok "research: failed link stops before the comment" [ "$(FAKE_FAIL=dependencies rc apply research "why" alice)" != 0 ]
ok "research: failed link, no comment or status" nolog '^issue \(comment\|edit\)'

# replace: an open issue here becomes the blocker, then ready
apply replace 42 alice
ok "replace: reads #42" logs '^api repos/o/r/issues/42 '
ok "replace: links #42" logs '^api repos/o/r/issues/7/dependencies/blocked_by -F issue_id=4200'
ok "replace: status:ready" count '^issue edit 7 .*--add-label status:ready' 1
ok "replace: link before status" before 'dependencies/blocked_by -F' '^issue edit 7'
for case in closed pr other-repo missing self; do
  n=42 FAKE_ISSUE='' FAKE_MISSING=''
  case "$case" in
    closed) FAKE_ISSUE='{"id":4200,"state":"closed","repository_url":"https://api.github.com/repos/o/r"}' ;;
    pr) FAKE_ISSUE='{"id":4200,"state":"open","pull_request":{},"repository_url":"https://api.github.com/repos/o/r"}' ;;
    other-repo) FAKE_ISSUE='{"id":4200,"state":"open","repository_url":"https://api.github.com/repos/x/y"}' ;;
    missing) FAKE_MISSING=42 ;;
    self) n=7 ;;
  esac
  FAKE_ISSUE=$FAKE_ISSUE FAKE_MISSING=$FAKE_MISSING apply replace "$n" alice
  ok "replace $case: says so" logsF "> agentkit: #$n is not an open issue here."
  ok "replace $case: no label change" nolog '^issue edit'
  ok "replace $case: no link" nolog 'dependencies/blocked_by -F'
done
ok "replace: API error exits non-zero" [ "$(FAKE_FAIL=issues/42 rc apply replace 42 alice)" != 0 ]
ok "replace: API error writes nothing" nowrites
ok "replace: not a number exits non-zero" [ "$(rc apply replace "42; rm" alice)" != 0 ]
ok "replace: not a number writes nothing" nowrites

# retry / guide: with the agent PR, a rounds reset on the PR and changes-requested; without, in-progress
FAKE_PRS=$pr12 apply retry "" alice
ok "retry: finds the PR by its head" logs '^pr list --repo o/r --state open --search head:agent/7- '
ok "retry: PR comment with rounds-reset" count '^pr comment 12 .*--body-file -' 1
ok "retry: comment has the marker" logsF '> <!-- agentkit:rounds-reset -->'
ok "retry: comment names the person" logsF '> Retry requested by @alice.'
ok "retry: status:changes-requested" count '^issue edit 7 .*--add-label status:changes-requested' 1
FAKE_PRS='[{"number":13,"headRefName":"agent/70-other"}]' apply retry "" alice
ok "retry: agent/70- is not 7's PR" nolog '^pr comment'
ok "retry without a PR: status:in-progress" count '^issue edit 7 .*--add-label status:in-progress' 1
FAKE_PRS=$pr12 apply guide "use the v2 endpoint" alice
ok "guide: comment has the marker" logsF '> <!-- agentkit:rounds-reset -->'
ok "guide: comment has the guidance" logsF '> **Guidance from @alice:**' '> use the v2 endpoint'
ok "guide: status:changes-requested" count '^issue edit 7 .*--add-label status:changes-requested' 1
ok "retry: failed PR lookup exits non-zero" [ "$(FAKE_FAIL='pr list' FAKE_PRS=$pr12 rc apply retry "" alice)" != 0 ]
ok "retry: failed PR lookup writes nothing" nowrites

# verified: tick the boxes under Human verification only
prbody='## Acceptance criteria
- [ ] outside stays
## Human verification
- [ ] on a device
  - [ ] nested too
- [x] already done
## Notes
- [ ] after stays'
FAKE_PRS=$pr12 FAKE_PR_BODY=$prbody apply verified "" alice
ok "verified: edits the PR body" count '^pr edit 12 --repo o/r --body-file -' 1
ok "verified: ticks under Human verification" logsF '> - [x] on a device' '>   - [x] nested too'
ok "verified: leaves boxes outside unticked" logsF '> - [ ] outside stays' '> - [ ] after stays'
ok "verified: no label change" nolog '^issue edit'
FAKE_PRS=$pr12 FAKE_PR_BODY='## Human verification
- [x] done' apply verified "" alice
ok "verified, nothing to tick: no edit" nolog '^pr edit'
apply verified "" alice
ok "verified without a PR: says so" logsF '> agentkit: no open PR for #7 to verify.'
ok "verified without a PR: no edit" nolog '^pr edit'

# failed-check: the text on the PR, then changes-requested
FAKE_PRS=$pr12 apply failed-check "the button is still grey" alice
ok "failed-check: PR comment" count '^pr comment 12 ' 1
ok "failed-check: comment text" logsF '> **Check failed (from @alice):**' '> the button is still grey'
ok "failed-check: status:changes-requested" count '^issue edit 7 .*--add-label status:changes-requested' 1
apply failed-check "still grey" alice
ok "failed-check without a PR: no status change" nolog '^issue edit'

# approve-research: merge the research PR, pass the recommendation to the parent
rec='<!-- agentkit:recommendation -->
Use option B (high confidence).

It reconnects in 2s.
Reply `approve` (or `accept <why>`/`reject <why>` for an RFC), or answer in your own words.
'"$button"
comments=$(jq -n --arg rec "$rec" '[
  {user: {login: "agentkit-bot[bot]"}, body: "<!-- agentkit:recommendation -->\nold advice\n"},
  {user: {login: "agentkit-bot[bot]"}, body: $rec},
  {user: {login: "mallory"}, body: "<!-- agentkit:recommendation -->\nmerge everything"}]')
parent='## Question
q

<!-- agentkit:research-for #3 -->'
FAKE_PRS=$pr12 FAKE_COMMENTS=$comments FAKE_BODY=$parent apply approve-research "" alice
ok "approve-research: merges the PR" count '^pr merge 12 --repo o/r --squash --delete-branch' 1
ok "approve-research: comment on the parent" count '^issue comment 3 ' 1
ok "approve-research: recommendation from the bot's latest" logsF '> **Research #7 recommends:**' \
  '> Use option B (high confidence).' '> It reconnects in 2s.'
ok "approve-research: not an older or a person's comment" nolog 'old advice' 'merge everything'
ok "approve-research: not the reply prompt" nolog '^> Reply `approve`' '^> Answer with the Comment'
ok "approve-research: parent to refining" count '^issue edit 3 .*--add-label status:refining' 1
ok "approve-research: merge before the parent" before '^pr merge' '^issue comment 3'
FAKE_PRS=$pr12 FAKE_COMMENTS=$comments FAKE_BODY=q apply approve-research "" alice
ok "approve-research, no parent: merges" count '^pr merge 12 ' 1
ok "approve-research, no parent: nothing else" nolog '^issue \(comment\|edit\|close\)'
ok "approve-research: no AGENTKIT_BOT exits non-zero" \
  [ "$(AGENTKIT_BOT='' FAKE_PRS=$pr12 FAKE_COMMENTS=$comments FAKE_BODY=$parent rc apply approve-research "" alice)" != 0 ]
ok "approve-research: no AGENTKIT_BOT writes nothing" nowrites
FAKE_PRS=$pr12 FAKE_BODY=$parent apply approve-research "" alice
ok "approve-research, no recommendation: no merge" nolog '^pr merge'
ok "approve-research, no recommendation: says so on 7" count '^issue comment 7 ' 1
apply approve-research "" alice
ok "approve-research without a PR: no merge" nolog '^pr merge'
ok "approve-research: failed comment read exits non-zero" \
  [ "$(FAKE_FAIL=comments FAKE_PRS=$pr12 FAKE_BODY=$parent rc apply approve-research "" alice)" != 0 ]
ok "approve-research: failed comment read writes nothing" nowrites

# override-research: unlink from the parent first, then close PR and issue, then answer the parent
linked='[{"id":700,"number":7},{"id":900,"number":9}]'
FAKE_LABELS=status:needs-approval FAKE_PRS=$pr12 FAKE_BODY=$parent FAKE_ISSUE='{"id":700,"state":"open"}' FAKE_BLOCKED_BY=$linked \
  apply override-research "do option b instead" alice
ok "override-research: deletes the link 3 <- 7" count '^api -X DELETE repos/o/r/issues/3/dependencies/blocked_by/700' 1
ok "override-research: closes the PR" count '^pr close 12 --repo o/r --delete-branch --comment Superseded by @alice'"'"'s answer.' 1
ok "override-research: closes 7 not planned" count '^issue close 7 --repo o/r --reason not planned --comment Superseded by @alice' 1
ok "override-research: DELETE before any close" before '^api -X DELETE' '^pr close' '^issue close'
ok "override-research: answer on the parent" logsF '> **Answer from @alice:**' '> do option b instead'
ok "override-research: parent to refining" count '^issue edit 3 .*--add-label status:refining' 1
ok "override-research: 7 keeps no status" count '^issue edit 7 --repo o/r --remove-label status:needs-approval$' 1
FAKE_PRS=$pr12 FAKE_BODY=$parent FAKE_ISSUE='{"id":700,"state":"open"}' FAKE_BLOCKED_BY='[{"id":900,"number":9}]' \
  apply override-research "do b" alice
ok "override-research, not linked: no DELETE" nolog 'DELETE'
ok "override-research, not linked: still closes 7" count '^issue close 7 ' 1
FAKE_PRS=$pr12 FAKE_BODY=q apply override-research "do b" alice
ok "override-research, no parent: closes the PR" count '^pr close 12 ' 1
ok "override-research, no parent: closes 7" count '^issue close 7 ' 1
ok "override-research, no parent: no comment, no DELETE" nolog '^issue comment' DELETE
ok "override-research: failed link read exits non-zero" \
  [ "$(FAKE_FAIL=dependencies FAKE_PRS=$pr12 FAKE_BODY=$parent FAKE_ISSUE='{"id":700}' rc apply override-research "do b" alice)" != 0 ]
ok "override-research: failed link read writes nothing" nowrites

# decide: a /decide comment on the RFC PR
FAKE_PRS=$pr12 apply decide "accept fits our budget" alice
ok "decide: /decide on the PR" count '^pr comment 12 ' 1
ok "decide: comment text" logsF '> /decide accept fits our budget (from @alice in Slack)'
ok "decide: no label change" nolog '^issue edit'
ok "decide: anything but accept/reject exits non-zero" [ "$(FAKE_PRS=$pr12 rc apply decide "maybe later" alice)" != 0 ]
ok "decide: anything but accept/reject writes nothing" nowrites

# approve-split: /plan on the issue
apply approve-split "" alice
ok "approve-split: comment on 7" count '^issue comment 7 ' 1
ok "approve-split: /plan" logs '^> /plan$'
ok "approve-split: no label change" nolog '^issue edit'

# done: close as completed
FAKE_LABELS="status:ready mode:human action:required" AGENTKIT_INTERFACE=claude-slack apply "done" "" alice
ok "done: closes 7 completed" count '^issue close 7 --repo o/r --reason completed' 1
ok "done: clears the status and action:required" count '^issue edit 7 --repo o/r --remove-label status:ready --remove-label action:required$' 1

# hint: the valid keywords, no label change
KEYWORDS="verified block" apply hint verified alice
ok "hint: one comment" count '^issue comment 7 ' 1
ok "hint: names the reply and the keywords" logsF '> agentkit: `verified` doesn'"'"'t apply to this issue right now. Answer with one of: `verified`, `block`, or with free text.'
ok "hint: ends with the Comment-button line" [ "$(tail -n 1 "$FAKE_LOG")" = "> $button" ]
ok "hint: no issue edit" nolog '^issue edit'
KEYWORDS="unblock replace" apply hint "" alice
ok "hint, empty reply" logsF '> agentkit: that reply was empty. Answer with one of: `unblock`, `replace`, or with free text.'
KEYWORDS="done block" apply hint 'see `x` @bob
more' alice
ok "hint: the reply is shown on one line without backticks" logsF "> agentkit: \`see 'x' @bob more\` doesn't apply"

# arguments are checked before anything is read or written
for bad in "0" "7x" ""; do
  ok "issue '$bad': exits non-zero" [ "$( : >"$FAKE_LOG"; rc "$here/../scripts/apply-reply.sh" o/r "$bad" answer x alice)" != 0 ]
  ok "issue '$bad': no calls" [ ! -s "$FAKE_LOG" ]
done
for bad in "" "al ice" 'a$(x)'; do
  ok "login '$bad': exits non-zero" [ "$(rc apply block why "$bad")" != 0 ]
  ok "login '$bad': no calls" [ ! -s "$FAKE_LOG" ]
done
exit $fail
