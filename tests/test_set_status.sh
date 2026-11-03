#!/usr/bin/env bash
# set-status.sh against a fake gh: the edit must drop every other status:* label and add the new one.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat >"$tmp/gh" <<'EOF'
#!/usr/bin/env bash
case "$1 $2" in
  "issue view")  # apply the --jq filter the script passed, over a JSON array built from FAKE_LABELS
    while [ "$1" != --jq ]; do shift; done
    printf '%s\n' $FAKE_LABELS | jq -R '{name: .}' | jq -s '{labels: .}' | jq -r "$2" ;;
  "issue edit") shift 2; echo "$*" >"$FAKE_OUT" ;;
esac
EOF
chmod +x "$tmp/gh"
export PATH="$tmp:$PATH" FAKE_OUT="$tmp/out"
fail=0
check() {  # labels-before new-status expected-edit-args [reason] [AGENTKIT_INTERFACE]
  rm -f "$FAKE_OUT"
  AGENTKIT_INTERFACE=${5:-} FAKE_LABELS=$1 "$here/../scripts/set-status.sh" o/r 7 "$2" "${4:-}"
  got=$(cat "$FAKE_OUT" 2>/dev/null || echo "<no edit>")
  if [ "$got" = "$3" ]; then echo "ok: $1 -> ${2:-none}"; else echo "FAIL: $1 -> ${2:-none}: got '$got', want '$3'"; fail=1; fi
}
check "status:review status:approved" status:changes-requested \
  "7 --repo o/r --remove-label status:review --remove-label status:approved --add-label status:changes-requested"
check "status:ready" status:in-progress "7 --repo o/r --remove-label status:ready --add-label status:in-progress"
check "" status:review "7 --repo o/r --add-label status:review"
check "status:review status:approved" "" "7 --repo o/r --remove-label status:review --remove-label status:approved"
check "status:review" status:review "7 --repo o/r --add-label status:review"
check "" "" "<no edit>"
check "status:review" status:needs-human "7 --repo o/r --remove-label status:review --add-label status:needs-human --add-label reason:flaky" reason:flaky
check "status:needs-human reason:flaky" status:in-progress \
  "7 --repo o/r --remove-label status:needs-human --remove-label reason:flaky --add-label status:in-progress"
check "status:needs-human reason:env" status:needs-human "7 --repo o/r --remove-label reason:env --add-label status:needs-human --add-label reason:agent-error" reason:agent-error
S=claude-slack
check "status:review" status:needs-info "7 --repo o/r --remove-label status:review --add-label status:needs-info --add-label action:required" "" $S
check "status:needs-info action:required" status:refining \
  "7 --repo o/r --remove-label status:needs-info --remove-label action:required --add-label status:refining" "" $S
check "mode:human status:refining" status:ready "7 --repo o/r --remove-label status:refining --add-label status:ready --add-label action:required" "" $S
check "status:refining" status:ready "7 --repo o/r --remove-label status:refining --add-label status:ready" "" $S
check "status:needs-info action:required" status:needs-human \
  "7 --repo o/r --remove-label status:needs-info --add-label status:needs-human" "" $S
check "status:needs-info action:required" "" "7 --repo o/r --remove-label status:needs-info --remove-label action:required" "" $S
check "mode:human status:in-progress" status:review "7 --repo o/r --remove-label status:in-progress --add-label status:review" "" $S
check "status:review" status:needs-approval "7 --repo o/r --remove-label status:review --add-label status:needs-approval --add-label action:required" "" $S
check "status:review" status:needs-info "7 --repo o/r --remove-label status:review --add-label status:needs-info"
check "status:needs-info action:required" status:refining "7 --repo o/r --remove-label status:needs-info --add-label status:refining"
check "status:review" status:needs-info "7 --repo o/r --remove-label status:review --add-label status:needs-info" "" other
exit $fail
