#!/usr/bin/env bash
# people.sh against a fake gh: an issue's (or PR's) comments by people with write access, never a bot's.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
# The fake gh: `api .../comments` answers $FAKE_COMMENTS with --jq applied; `api .../collaborators/<login>/permission`
# answers {"permission": $FAKE_PERM_<login>} (none when unset). A call containing $FAKE_FAIL fails like an API error.
cat >"$tmp/gh" <<'EOF2'
#!/usr/bin/env bash
echo "$*" >>"$FAKE_LOG"
filter=. ep= prev=
for a in "$@"; do
  case "$prev" in --jq) filter=$a ;; esac
  case "$a" in repos/*) ep=$a ;; esac
  prev=$a
done
if [ -n "${FAKE_FAIL:-}" ]; then case "$*" in *"$FAKE_FAIL"*) echo "gh: Bad Gateway (HTTP 502)" >&2; exit 1 ;; esac; fi
case "$ep" in
  */comments) json=${FAKE_COMMENTS:-[]} ;;
  */permission) l=$(cut -d/ -f5 <<<"$ep"); v=FAKE_PERM_${l//-/_}; json="{\"permission\": \"${!v:-none}\"}" ;;
  *) exit 1 ;;
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
people() { : >"$FAKE_LOG"; "$here/../scripts/people.sh" o/r 7 "agentkit-bot[bot]"; }
c() { jq -n --argjson id "$1" --arg l "$2" --arg t "$3" --arg b "$4" '{id: $id, user: {login: $l, type: $t}, body: $b}'; }

export FAKE_COMMENTS FAKE_PERM_alice=write FAKE_PERM_bob=read FAKE_PERM_carol=admin FAKE_PERM_dan_m=maintain
FAKE_COMMENTS=$(jq -s . <<<"$(c 1 alice User 'accept fine') $(c 2 bob User 'accept me') $(c 3 'agentkit-bot[bot]' Bot '/decide accept x')
  $(c 4 carol User 'reject no') $(c 5 'other[bot]' Bot 'accept') $(c 6 dan-m User 'retry') $(c 7 alice User 'more')
  $(c 8 'agentkit-bot[bot]' User 'accept spoofed type')")
out=$(people)
ok "write, admin and maintain people, oldest first" [ "$(jq -c '[.[].id]' <<<"$out")" = '[1,4,6,7]' ]
ok "each entry has its id and body" [ "$(jq -c '.[0]' <<<"$out")" = '{"id":1,"body":"accept fine"}' ]
ok "one permission read per login" [ "$(grep -c 'collaborators/alice/permission' "$FAKE_LOG")" = 1 ]
ok "a bot's permission is never read" [ "$(grep -c 'bot\]/permission' "$FAKE_LOG")" = 0 ]
FAKE_COMMENTS='[]'
ok "no comments: []" [ "$(people)" = '[]' ]
ok "a failed comment read exits non-zero" [ "$(FAKE_FAIL=comments people >/dev/null 2>&1 && echo 0 || echo 1)" = 1 ]
FAKE_COMMENTS=$(jq -s . <<<"$(c 1 alice User 'accept')")
ok "a failed permission read counts as no access" [ "$(FAKE_FAIL=permission people)" = '[]' ]
exit $fail
