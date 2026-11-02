#!/usr/bin/env bash
# set-status.sh against a fake gh: the edit must drop every other status:* label and add the new one.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cat >"$tmp/gh" <<'EOF'
#!/usr/bin/env bash
case "$1 $2" in
  "issue view") printf '%s\n' $FAKE_LABELS ;;
  "issue edit") shift 2; echo "$*" >"$FAKE_OUT" ;;
esac
EOF
chmod +x "$tmp/gh"
export PATH="$tmp:$PATH" FAKE_OUT="$tmp/out"
fail=0
check() {  # labels-before new-status expected-edit-args [reason]
  rm -f "$FAKE_OUT"
  FAKE_LABELS=$1 "$here/../scripts/set-status.sh" o/r 7 "$2" "${4:-}"
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
exit $fail
