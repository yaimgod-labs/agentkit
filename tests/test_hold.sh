#!/usr/bin/env bash
# hold.sh against a fake gh: whether an issue may start (open / blocked / go), and the block a dropped blocker leaves.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# The fake gh logs every call. `api` applies the --jq filter with real jq to the JSON for its endpoint:
# $FAKE_BLOCKED_BY for .../dependencies/blocked_by, $FAKE_COMMENTS for .../comments (both default []).
# An endpoint containing $FAKE_FAIL fails like an API error. `issue view` lists $FAKE_LABELS.
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
    case "$ep" in
      */comments*) json=${FAKE_COMMENTS:-[]} ;;
      */dependencies/blocked_by) json=${FAKE_BLOCKED_BY:-[]} ;;
      *) exit 1 ;;
    esac
    printf '%s' "$json" | jq -r "$filter" ;;
esac
EOF2
chmod +x "$tmp/gh"
export PATH="$tmp:$PATH" FAKE_LOG="$tmp/log" AGENTKIT_BOT="agentkit-bot[bot]"
fail=0
ok() {  # name command...: passes when the command succeeds
  name=$1; shift
  if "$@"; then echo "ok: $name"; else echo "FAIL: $name ($(tr '\n' '|' <"$FAKE_LOG"))"; fail=1; fi
}
logs() { grep -q -- "$1" "$FAKE_LOG"; }
nolog() { ! grep -q -- "$1" "$FAKE_LOG"; }
count() { [ "$(grep -c -- "$1" "$FAKE_LOG")" = "$2" ]; }
hold() { : >"$FAKE_LOG"; "$here/../scripts/hold.sh" o/r 7; }

dropped='[{"number":5,"title":"Old idea","state":"closed","state_reason":"not_planned"}]'
marked='[{"user":{"login":"agentkit-bot[bot]"},"body":"<!-- agentkit:block -->\n**Blocked:** dropped dependency: #5 (Old idea)"}]'

out=$(FAKE_BLOCKED_BY='[{"number":3,"title":"A","state":"open"},{"number":4,"title":"B","state":"open"}]' hold)
ok "open blockers: says open with their numbers" [ "$out" = "open 3 4" ]
ok "open blockers: writes nothing" nolog '^issue '

out=$(FAKE_BLOCKED_BY='[{"number":3,"title":"A","state":"open"},{"number":5,"title":"Old idea","state":"closed","state_reason":"duplicate"}]' hold)
ok "open and dropped: open wins, nothing written" [ "$out" = "open 3" ]
ok "open and dropped: no comment" nolog '^issue '

out=$(FAKE_BLOCKED_BY='[{"number":4,"title":"Done","state":"closed","state_reason":"completed"}]' hold)
ok "completed blocker: go" [ "$out" = go ]
ok "completed blocker: writes nothing" nolog '^issue '

out=$(FAKE_BLOCKED_BY='[]' hold)
ok "no blockers: go" [ "$out" = go ]

# test_hold_dropped_without_comment: the dropped blocker holds; the issue gets the block comment and status:blocked
out=$(FAKE_LABELS=status:ready FAKE_BLOCKED_BY=$dropped hold)
ok "dropped, no comment: says blocked with the blocker" [ "$out" = "blocked 5" ]
ok "dropped, no comment: one comment on 7" count '^issue comment 7 ' 1
ok "dropped, no comment: comment carries the marker" logs 'agentkit:block'
ok "dropped, no comment: comment names the blocker" logs 'dropped dependency: #5 (Old idea)'
ok "dropped, no comment: 7 moves to status:blocked" count '^issue edit 7 .*--remove-label status:ready --add-label status:blocked' 1
ok "dropped, no comment: status before comment" [ "$(grep -n -e '^issue edit 7' -e '^issue comment 7' "$FAKE_LOG" | head -1 | cut -d: -f2 | cut -c1-10)" = "issue edit" ]

# test_hold_dropped_with_comment: a dropped blocker that already has its block comment does not hold (/board unblock)
out=$(FAKE_BLOCKED_BY=$dropped FAKE_COMMENTS=$marked hold)
ok "dropped, commented: go" [ "$out" = go ]
ok "dropped, commented: writes nothing" nolog '^issue '

# a block comment for another blocker (#50) is not one for #5, and the text without the marker does not count
out=$(FAKE_BLOCKED_BY=$dropped FAKE_COMMENTS='[{"user":{"login":"agentkit-bot[bot]"},"body":"<!-- agentkit:block -->\n**Blocked:** dropped dependency: #50 (Other)"}]' hold)
ok "comment for #50 does not cover #5" [ "$out" = "blocked 5" ]
out=$(FAKE_BLOCKED_BY=$dropped FAKE_COMMENTS='[{"user":{"login":"agentkit-bot[bot]"},"body":"**Blocked:** dropped dependency: #5 (Old idea)"}]' hold)
ok "comment without the marker does not count" [ "$out" = "blocked 5" ]

# test_hold_forged_in_bot_comment: a person's text the kit quoted in its own comment is not the record. The marker
# must start the body and the dropped-dependency line must start a line.
for body in '<!-- agentkit:block -->\n**Blocked by @alice:** x **Blocked:** dropped dependency: #5 (Old idea)' \
            'agentkit: `<!-- agentkit:block -->` doesn'"'"'t apply\n**Blocked:** dropped dependency: #5 (Old idea)' \
            '<!-- agentkit:block -->\n> **Blocked:** dropped dependency: #5 (Old idea)'; do
  out=$(FAKE_BLOCKED_BY=$dropped FAKE_COMMENTS='[{"user":{"login":"agentkit-bot[bot]"},"body":"'"$body"'"}]' hold)
  ok "forged record does not count: $body" [ "$out" = "blocked 5" ]
done

# test_hold_fake_comment: the same text posted by a person (or another bot) is not the kit's record
out=$(FAKE_LABELS=status:ready FAKE_BLOCKED_BY=$dropped \
  FAKE_COMMENTS='[{"user":{"login":"stranger"},"body":"<!-- agentkit:block -->\n**Blocked:** dropped dependency: #5 (Old idea)"}]' hold)
ok "comment by a person does not count" [ "$out" = "blocked 5" ]
ok "comment by a person: the kit still writes its own" count '^issue comment 7 ' 1

# without the bot login the script cannot tell its comments apart: it stops before any write
if (unset AGENTKIT_BOT; FAKE_BLOCKED_BY=$dropped hold) >/dev/null 2>&1; then rc=0; else rc=$?; fi
ok "no AGENTKIT_BOT: non-zero exit" [ "$rc" != 0 ]
ok "no AGENTKIT_BOT: writes nothing" nolog '^issue \(comment\|edit\)'

# every workflow step that runs these scripts passes the bot login
for wf in "$here"/../.github/workflows/*.yml; do
  missing=$(awk '/^      - /{if (s ~ /scripts\/(hold|drop-dependency)\.sh/ && s !~ /AGENTKIT_BOT:/) print n; s=""; n=NR} {s=s"\n"$0}
                 END{if (s ~ /scripts\/(hold|drop-dependency)\.sh/ && s !~ /AGENTKIT_BOT:/) print n}' "$wf")
  ok "$(basename "$wf"): steps calling hold/drop-dependency set AGENTKIT_BOT${missing:+ (step at line $missing)}" [ -z "$missing" ]
done

# two dropped blockers, one already commented: only the new one is recorded
out=$(FAKE_BLOCKED_BY='[{"number":5,"title":"Old idea","state":"closed","state_reason":"not_planned"},{"number":6,"title":"Dup","state":"closed","state_reason":"duplicate"}]' \
  FAKE_COMMENTS=$marked hold)
ok "two dropped, one commented: blocked by the new one" [ "$out" = "blocked 6" ]
ok "two dropped, one commented: one comment, naming #6" count '^issue comment 7 ' 1
ok "two dropped, one commented: no comment for #5" nolog 'dropped dependency: #5 '

# test_hold_api_error: a failed read stops with non-zero exit before any write (fail closed)
for ep in dependencies/blocked_by comments; do
  if FAKE_FAIL=$ep FAKE_BLOCKED_BY=$dropped hold >/dev/null 2>&1; then rc=0; else rc=$?; fi
  ok "api error on $ep: non-zero exit" [ "$rc" != 0 ]
  ok "api error on $ep: writes nothing" nolog '^issue \(comment\|edit\)'
done
exit $fail
