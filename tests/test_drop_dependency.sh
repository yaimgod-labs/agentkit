#!/usr/bin/env bash
# drop-dependency.sh against a fake gh: a dropped blocker's open dependents get a block comment and status:blocked.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# The fake gh logs every call; `api` applies the --jq filter to $FAKE_JSON with real jq, `issue view` lists $FAKE_LABELS.
cat >"$tmp/gh" <<'EOF2'
#!/usr/bin/env bash
echo "$*" >>"$FAKE_LOG"
case "$1 $2" in
  "issue view") printf '%s\n' ${FAKE_LABELS:-} ;;
  "issue comment"|"issue edit") ;;
  *)
    [ "$1" = api ] || exit 1
    filter=.
    while [ $# -gt 0 ]; do
      if [ "$1" = --jq ]; then filter=$2; fi
      shift
    done
    printf '%s' "$FAKE_JSON" | jq -r "$filter" ;;
esac
EOF2
chmod +x "$tmp/gh"
export PATH="$tmp:$PATH" FAKE_LOG="$tmp/log"
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
out=$(FAKE_JSON='[{"number":7,"state":"open"},{"number":8,"state":"closed"}]' "$here/../scripts/drop-dependency.sh" o/r 3 "Old idea")
ok "prints the affected number" [ "$out" = 7 ]
ok "lists the closed issue's dependents" logs 'repos/o/r/issues/3/dependencies/blocking'
ok "one comment on 7" count '^issue comment 7 ' 1
ok "comment carries the block marker" logs 'agentkit:block'
ok "comment names the dropped blocker" logs 'dropped dependency: #3 (Old idea)'
ok "7 moves to status:blocked" count '^issue edit 7 .*--add-label status:blocked' 1
ok "nothing for the closed dependent" nolog '^issue [a-z]* 8 '
# An already-blocked dependent gets the comment, but its label is left alone.
: >"$FAKE_LOG"
FAKE_LABELS=status:blocked FAKE_JSON='[{"number":7,"state":"open"}]' "$here/../scripts/drop-dependency.sh" o/r 3 "Old idea" >/dev/null
ok "already blocked: still commented" count '^issue comment 7 ' 1
ok "already blocked: no label removed" nolog '--remove-label'
# No dependents: no output, no writes.
: >"$FAKE_LOG"
out=$(FAKE_JSON='[]' "$here/../scripts/drop-dependency.sh" o/r 3 "Old idea")
ok "no dependents prints nothing" [ -z "$out" ]
ok "no dependents writes nothing" nolog '^issue '
exit $fail
