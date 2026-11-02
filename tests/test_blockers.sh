#!/usr/bin/env bash
# blockers.sh against a fake gh: classifies dependency blockers as open or dropped from the API response alone.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# The fake gh applies the --jq filter to $FAKE_JSON with real jq and records the endpoint it was asked for.
cat >"$tmp/gh" <<'EOF2'
#!/usr/bin/env bash
[ "$1" = api ] || exit 1
echo "$*" >>"$FAKE_CALLS"
filter=
while [ $# -gt 0 ]; do
  if [ "$1" = --jq ]; then filter=$2; fi
  shift
done
printf '%s' "$FAKE_JSON" | jq -r "$filter"
EOF2
chmod +x "$tmp/gh"
export PATH="$tmp:$PATH" FAKE_CALLS="$tmp/calls"
fail=0
check() {  # name json mode expected-output
  : >"$FAKE_CALLS"
  got=$(FAKE_JSON=$2 "$here/../scripts/blockers.sh" o/r 7 "$3" | tr '\n' ' ')
  if [ "$got" = "$4" ]; then echo "ok: $1"; else echo "FAIL: $1: got '$got', want '$4'"; fail=1; fi
}
mixed='[{"number":3,"state":"open"},{"number":4,"state":"closed","state_reason":"completed"},{"number":5,"state":"closed","state_reason":"not_planned"}]'
check "open blockers" "$mixed" open "3 "
check "dropped blockers" "$mixed" dropped "5 "
check "no blockers, open" '[]' open ""
check "no blockers, dropped" '[]' dropped ""
# A closed blocker with no state_reason (null) was not completed, so it counts as dropped.
check "closed without reason is dropped" '[{"number":6,"state":"closed","state_reason":null}]' dropped "6 "
test_blockers_cross_repo() {
  cross='[{"number":9,"state":"open","repository_url":"https://api.github.com/repos/x/y"}]'
  check "blockers_cross_repo" "$cross" open "9 "
  # One call for the dependency list only; the number is never looked up in this or any other repo.
  calls=$(wc -l <"$FAKE_CALLS" | tr -d ' ')
  if [ "$calls" = 1 ] && grep -q 'repos/o/r/issues/7/dependencies/blocked_by' "$FAKE_CALLS"; then
    echo "ok: blockers_cross_repo makes a single lookup"
  else echo "FAIL: blockers_cross_repo made $calls calls: $(cat "$FAKE_CALLS")"; fail=1; fi
}
test_blockers_cross_repo
exit $fail
