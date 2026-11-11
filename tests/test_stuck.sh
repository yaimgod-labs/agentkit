#!/usr/bin/env bash
# stuck.sh and retry.sh against a fake gh: which issues a dead implement run left behind, and retry-once-then-hand-over.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# The fake gh logs every call and applies --jq with real jq: `api .../actions/runs` to $FAKE_RUNS,
# `api .../issues/<n>/events` to $FAKE_EVENTS_<n>, `issue list --label status:in-progress` to $FAKE_INPROG
# (status:changes-requested: $FAKE_CR). `issue view` lists $FAKE_LABELS; an edit fails when $FAKE_EDIT_FAIL is set.
cat >"$tmp/gh" <<'EOF2'
#!/usr/bin/env bash
echo "$*" >>"$FAKE_LOG"
filter=. ep= label= prev=
for a in "$@"; do
  case "$prev" in --jq) filter=$a ;; --label) label=$a ;; esac
  case "$a" in repos/*) ep=$a ;; esac
  prev=$a
done
case "$1 $2" in
  "issue view") printf '%s\n' ${FAKE_LABELS:-}; exit ;;
  "issue comment") exit ;;
  "issue edit") [ -z "${FAKE_EDIT_FAIL:-}" ]; exit ;;
  "issue list") if [ "$label" = status:in-progress ]; then json=${FAKE_INPROG:-[]}; else json=${FAKE_CR:-[]}; fi ;;
  *) case "$ep" in
       */actions/runs*) json=${FAKE_RUNS:-'{"workflow_runs":[]}'} ;;
       */events) v=FAKE_EVENTS_$(cut -d/ -f5 <<<"$ep"); json=${!v:-[]} ;;
       *) exit 1 ;;
     esac ;;
esac
printf '%s' "$json" | jq -r "$filter"
EOF2
chmod +x "$tmp/gh"
export PATH="$tmp:$PATH" FAKE_LOG="$tmp/log"
fail=0
ok() {  # name command...: passes when the command succeeds
  name=$1; shift
  if "$@"; then echo "ok: $name"; else echo "FAIL: $name ($(tr '\n' '|' <"$FAKE_LOG"))"; fail=1; fi
}
logs() { grep -qF -- "$1" "$FAKE_LOG"; }
nolog() { ! grep -qF -- "$1" "$FAKE_LOG"; }
stuck() { : >"$FAKE_LOG"; "$here/../scripts/stuck.sh" o/r; }
retry() { : >"$FAKE_LOG"; "$here/../scripts/retry.sh" o/r 7 status:in-progress "run died"; }

old=2020-01-01T00:00:00Z
new=$(date -u +%Y-%m-%dT%H:%M:%SZ)
ev() { echo "[{\"event\":\"labeled\",\"label\":{\"name\":\"$1\"},\"created_at\":\"$2\"},{\"event\":\"labeled\",\"label\":{\"name\":\"$3\"},\"created_at\":\"$4\"}]"; }
export FAKE_INPROG='[{"number":7,"title":"Add x"},{"number":8,"title":"Fix y"}]' FAKE_CR='[{"number":9,"title":"Z"}]'
FAKE_EVENTS_7=$(ev status:in-progress "$old" status:ready "$new")        # in progress for long; another label since
FAKE_EVENTS_8=$(ev status:in-progress "$old" status:in-progress "$new")  # re-added just now: the latest counts
FAKE_EVENTS_9=$(ev status:changes-requested "$old" status:review "$new")
export FAKE_EVENTS_7 FAKE_EVENTS_8 FAKE_EVENTS_9

out=$(stuck)
ok "old in-progress and changes-requested are stuck" [ "$out" = "7 status:in-progress
9 status:changes-requested" ]
ok "reads only, never writes" nolog "issue edit"

out=$(FAKE_RUNS='{"workflow_runs":[{"status":"in_progress","display_title":"Add x"},{"status":"completed","display_title":"Z"}]}' stuck)
ok "an unfinished run titled like the issue skips it; a finished one does not" [ "$out" = "9 status:changes-requested" ]

out=$(FAKE_EVENTS_7='[]' FAKE_CR='[]' stuck)
ok "no labeled event: not stuck" [ -z "$out" ]

FAKE_LABELS="status:in-progress" retry
ok "first time: retries" logs "issue comment 7 --repo o/r --body agentkit: run died. Retrying once."
ok "first time: re-adds the label with reason:retry" logs "issue edit 7 --repo o/r --add-label status:in-progress --add-label reason:retry"
ok "first time: no hand over" nolog "status:needs-human"

FAKE_LABELS="status:in-progress reason:retry" retry
ok "already retried: hands over" logs "issue edit 7 --repo o/r --remove-label status:in-progress --remove-label reason:retry --add-label status:needs-human --add-label reason:agent-error"
ok "already retried: says so" logs "agentkit: run died. Needs you."
ok "already retried: no second retry" nolog "Retrying once"
at() { grep -m1 -n -- "$1" "$FAKE_LOG" | cut -d: -f1; }
ok "already retried: status before the comment" [ "$(at "add-label status:needs-human")" -lt "$(at "Needs you")" ]
ok "already retried, mode off: no Comment-button line" nolog "Comment button"
FAKE_LABELS="status:in-progress reason:retry" AGENTKIT_INTERFACE=slack retry
ok "already retried, Slack mode: the comment ends with the Comment-button line" \
  [ "$(tail -n 1 "$FAKE_LOG")" = "Answer with the Comment button on this issue's card in Slack." ]

FAKE_LABELS="status:in-progress" FAKE_EDIT_FAIL=1 retry || true
ok "re-add fails: tries to hand over" logs "agentkit: run died. Needs you."
ok "re-add fails: exits non-zero" [ "$(FAKE_LABELS="status:in-progress" FAKE_EDIT_FAIL=1 retry >/dev/null 2>&1 && echo 0 || echo 1)" = 1 ]
exit $fail
