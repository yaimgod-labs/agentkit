#!/usr/bin/env bash
# drop-dependency.sh against a fake gh: a dropped blocker's open dependents get a block comment and status:blocked.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# The fake gh logs every call. `api` applies the --jq filter with real jq to $FAKE_COMMENTS (default []) for an
# issue's comments and to $FAKE_JSON for anything else; an endpoint containing $FAKE_FAIL fails like an API error.
# `issue view` lists $FAKE_LABELS.
cat >"$tmp/gh" <<'EOF2'
#!/usr/bin/env bash
echo "$*" >>"$FAKE_LOG"
case "$1 $2" in
  "issue view") printf '%s\n' ${FAKE_LABELS:-} ;;
  "issue comment"|"issue edit") ;;
  *)
    [ "$1" = api ] || exit 1
    filter=. ep=
    while [ $# -gt 0 ]; do
      case "$1" in --jq) filter=$2; shift ;; repos/*) ep=$1 ;; esac
      shift
    done
    if [ -n "${FAKE_FAIL:-}" ]; then case "$ep" in *"$FAKE_FAIL"*) echo "HTTP 502: Bad Gateway" >&2; exit 1 ;; esac; fi
    case "$ep" in */comments*) json=${FAKE_COMMENTS:-[]} ;; *) json=$FAKE_JSON ;; esac
    printf '%s' "$json" | jq -r "$filter" ;;
esac
EOF2
chmod +x "$tmp/gh"
export PATH="$tmp:$PATH" FAKE_LOG="$tmp/log" AGENTKIT_BOT="agentkit-bot[bot]"
fail=0
ok() {  # name command...: passes when the command succeeds
  name=$1; shift
  if "$@"; then echo "ok: $name"; else echo "FAIL: $name"; fail=1; fi
}
logs() { grep -q -- "$1" "$FAKE_LOG"; }          # the log has a line matching
nolog() { ! grep -q -- "$1" "$FAKE_LOG"; }       # the log has none
count() { [ "$(grep -c -- "$1" "$FAKE_LOG")" = "$2" ]; }
# The logged comment body spans lines: the call is on the first, the marker and the reason follow.
: >"$FAKE_LOG"
out=$(FAKE_JSON='[{"number":7,"state":"open","repository_url":"https://api.github.com/repos/o/r"},{"number":8,"state":"closed","repository_url":"https://api.github.com/repos/o/r"}]' "$here/../scripts/drop-dependency.sh" o/r 3 "Old idea")
ok "prints the affected number" [ "$out" = 7 ]
ok "lists the closed issue's dependents" logs 'repos/o/r/issues/3/dependencies/blocking'
ok "one comment on 7" count '^issue comment 7 ' 1
ok "comment carries the block marker" logs 'agentkit:block'
ok "comment names the dropped blocker" logs 'dropped dependency: #3 (Old idea)'
ok "7 moves to status:blocked" count '^issue edit 7 .*--add-label status:blocked' 1
ok "nothing for the closed dependent" nolog '^issue [a-z]* 8 '
# An already-blocked dependent gets the comment, but its label is left alone.
: >"$FAKE_LOG"
FAKE_LABELS=status:blocked FAKE_JSON='[{"number":7,"state":"open","repository_url":"https://api.github.com/repos/o/r"}]' "$here/../scripts/drop-dependency.sh" o/r 3 "Old idea" >/dev/null
ok "already blocked: still commented" count '^issue comment 7 ' 1
ok "already blocked: no label removed" nolog '--remove-label'
# No dependents: no output, no writes.
: >"$FAKE_LOG"
out=$(FAKE_JSON='[]' "$here/../scripts/drop-dependency.sh" o/r 3 "Old idea")
ok "no dependents prints nothing" [ -z "$out" ]
ok "no dependents writes nothing" nolog '^issue '
# A dependent in another repo is never addressed by its bare number here (the "cross-repo:" checks);
# the repo compares case-insensitively, and the skip is logged on stderr only.
: >"$FAKE_LOG"
out=$(FAKE_JSON='[{"number":9,"state":"open","repository_url":"https://api.github.com/repos/x/y"},{"number":7,"state":"open","repository_url":"https://api.github.com/repos/O/R"}]' \
  "$here/../scripts/drop-dependency.sh" o/r 3 "Old idea" 2>"$tmp/err")
ok "cross-repo: stdout lists only the same-repo number" [ "$out" = 7 ]
ok "cross-repo: nothing commented on 9" nolog '^issue comment 9 '
ok "cross-repo: nothing edited on 9" nolog '^issue edit 9 '
ok "cross-repo: nothing viewed on 9" nolog '^issue view 9 '
ok "cross-repo: same repo in other case still handled" count '^issue comment 7 ' 1
ok "cross-repo: skip logged on stderr" grep -qx 'skip x/y#9: other repo' "$tmp/err"
# A dependent that already has the block comment for this blocker is skipped: a retry or a re-close never posts
# twice, and a person's `/board unblock` sticks.
: >"$FAKE_LOG"
out=$(FAKE_COMMENTS='[{"user":{"login":"agentkit-bot[bot]"},"body":"<!-- agentkit:block -->\n**Blocked:** dropped dependency: #3 (Old idea)"}]' \
  FAKE_JSON='[{"number":7,"state":"open","repository_url":"https://api.github.com/repos/o/r"}]' "$here/../scripts/drop-dependency.sh" o/r 3 "Old idea")
ok "already commented: not printed" [ -z "$out" ]
ok "already commented: no second comment" nolog '^issue comment 7 '
ok "already commented: status left alone" nolog '^issue edit 7 '
# A comment for another blocker (#30) does not count for #3.
: >"$FAKE_LOG"
out=$(FAKE_COMMENTS='[{"user":{"login":"agentkit-bot[bot]"},"body":"<!-- agentkit:block -->\n**Blocked:** dropped dependency: #30 (Other)"}]' \
  FAKE_JSON='[{"number":7,"state":"open","repository_url":"https://api.github.com/repos/o/r"}]' "$here/../scripts/drop-dependency.sh" o/r 3 "Old idea")
ok "comment for #30: 7 still handled" [ "$out" = 7 ]
# test_drop_dependency_in_flight: a dependent already in work gets the comment only; its status is left to the flow
for s in in-progress review changes-requested approved needs-verification; do
  : >"$FAKE_LOG"
  out=$(FAKE_JSON='[{"number":7,"state":"open","labels":[{"name":"status:'"$s"'"}],"repository_url":"https://api.github.com/repos/o/r"}]' \
    "$here/../scripts/drop-dependency.sh" o/r 3 "Old idea")
  ok "in flight ($s): printed" [ "$out" = 7 ]
  ok "in flight ($s): commented" count '^issue comment 7 ' 1
  ok "in flight ($s): status not changed" nolog '^issue edit 7 '
done
# A failed read stops with non-zero exit before any write (fail closed).
for ep in dependencies/blocking comments; do
  : >"$FAKE_LOG"
  if FAKE_FAIL=$ep FAKE_JSON='[{"number":7,"state":"open","repository_url":"https://api.github.com/repos/o/r"}]' \
    "$here/../scripts/drop-dependency.sh" o/r 3 "Old idea" >/dev/null 2>&1; then rc=0; else rc=$?; fi
  ok "api error on $ep: non-zero exit" [ "$rc" != 0 ]
  ok "api error on $ep: writes nothing" nolog '^issue \(comment\|edit\)'
done
exit $fail
