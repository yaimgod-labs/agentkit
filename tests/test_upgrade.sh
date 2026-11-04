#!/usr/bin/env bash
# gh agentkit upgrade, file edits only: an old marketplace name is renamed in settings and caller.
# shellcheck disable=SC2034  # out and dfail are read by the eval in check
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
# shellcheck source=../cli/gh-agentkit/gh-agentkit
source "$here/../cli/gh-agentkit/gh-agentkit"
# shellcheck disable=SC2034  # read by the sourced functions
KIT_REPO=acme/agentkit  # as if the CLI were cloned from acme/agentkit
cd "$tmp" && git init -q && mkdir -p .claude .github/workflows
cat >.claude/settings.json <<'J'
{"extraKnownMarketplaces": {"acme-agentkit": {"source": {"source": "github", "repo": "acme/agentkit"}},
                            "mine": {"source": {"source": "github", "repo": "me/plugins"}}},
 "enabledPlugins": {"agentkit@acme-agentkit": true, "z@mine": true}}
J
sed -e 's#your-org/agentkit#acme/agentkit#g' "$KIT/templates/.github/workflows/agentkit.yml" \
  | sed 's#^    uses: \(.*implement.yml@v1\)$#    uses: \1\n    with:\n      plugins: |\n        ponytail@acme-agentkit\n        z@mine#' >.github/workflows/agentkit.yml
sync_checkout o/r >/dev/null
fail=0
check() { if eval "$2"; then echo "ok: $1"; else echo "FAIL: $1"; fail=1; fi; }
check "old marketplace key removed" "! jq -e '.extraKnownMarketplaces[\"acme-agentkit\"]' .claude/settings.json >/dev/null"
check "kit marketplace under agentkit" "jq -e '.extraKnownMarketplaces.agentkit.source.repo == \"acme/agentkit\"' .claude/settings.json >/dev/null"
check "enabled plugin renamed, others kept" "jq -e '.enabledPlugins == {\"agentkit@agentkit\": true, \"z@mine\": true}' .claude/settings.json >/dev/null"
check "caller plugin ref renamed" "grep -qx '        ponytail@agentkit' .github/workflows/agentkit.yml"
check "other marketplace refs kept" "grep -qx '        z@mine' .github/workflows/agentkit.yml"
check "kit files added" "[ -f docs/glossary.md ] && [ -x .agentkit/test.sh ]"

# renamed labels and Stage options move in place: a stub gh records what upgrade asks for
gh() {
  case "$*" in
    "label list"*) printf '%s\n' status:needs-device-check reason:device reason:manual-check ;;
    "label edit"*|"label create"*) echo "$*" >>"$tmp/calls" ;;
    "project field-list"*) echo FID ;;
    "api graphql --input -") cat >>"$tmp/calls" ;;
    "api graphql"*) echo '[{"id":"a","name":"Backlog","color":"GRAY","description":""},{"id":"b","name":"Needs device check","color":"GRAY","description":""}]' ;;
  esac
}
var_get() { echo 7; }
setup_labels o/r >/dev/null
setup_board o/r >/dev/null
check "old label renamed" "grep -qx 'label edit status:needs-device-check --repo o/r --name status:needs-verification' '$tmp/calls'"
check "label not renamed onto an existing one" "! grep -q 'label edit reason:device' '$tmp/calls'"
check "stage renamed with its id kept" "tr -d ' \\n' <'$tmp/calls' | grep -q '\"id\":\"b\",\"name\":\"Needsverification\"'"
check "new label created" "grep -q 'label create action:required --repo o/r' '$tmp/calls'"
check "needs-approval label created" "grep -q 'label create status:needs-approval --repo o/r' '$tmp/calls'"
check "stage option added" "tr -d ' \\n' <'$tmp/calls' | grep -q '\"name\":\"Needsapproval\"'"

# --interface claude-slack: sets the variables and prints the Slack lines; doctor checks it only when on
gh() { case "$*" in "variable set"*) echo "$*" >>"$tmp/vars" ;; esac; }
out=$(enable_interface o/r)
check "interface variable set" "grep -qx 'variable set AGENTKIT_INTERFACE --repo o/r --body claude-slack' '$tmp/vars'"
check "auto-merge variable set" "grep -qx 'variable set AUTO_MERGE --repo o/r --body true' '$tmp/vars'"
check "subscribe line printed" "grep -qF '/github subscribe o/r issues comments +label:\"action:required\"' <<<\"\$out\""
check "unsubscribe line printed" "grep -qF '/github unsubscribe o/r pulls commits releases deployments' <<<\"\$out\""
check "signin reminder printed" "grep -qF '/github signin' <<<\"\$out\""
check "unknown interface refused" "! (parse_interface nope) 2>/dev/null"
ok() { echo "  ok    $*"; }
bad() { echo "  FAIL  $*"; dfail=1; }
warn() { echo "  warn  $*"; }
var_get() { case $2 in AGENTKIT_INTERFACE) echo "$IFACE" ;; AUTO_MERGE) echo "$AM" ;; esac; }
IFACE="" AM=""; out=$(doctor_interface o/r "" ""; true)
check "doctor silent with the mode off" "[ -z \"\$out\" ]"
IFACE=claude-slack AM=""; dfail=0; out=$(doctor_interface o/r "" "x" 2>&1; echo "dfail=\$dfail")
check "doctor fails without AUTO_MERGE" "grep -q 'FAIL  .*AUTO_MERGE' <<<\"\$out\""
check "doctor warns without the webhook" "grep -q 'warn  .*SLACK_WEBHOOK_URL' <<<\"\$out\""
check "doctor warns without the label" "grep -q 'warn  .*action:required' <<<\"\$out\""
check "doctor prints the signin reminder" "grep -q '/github signin' <<<\"\$out\""
check "doctor warns without the reply job" "grep -q 'warn  .*reply' <<<\"\$out\""
check "doctor warns without the triage job" "grep -q 'warn  .*triage' <<<\"\$out\""
jobs="    uses: x/agentkit/.github/workflows/reply.yml@v1
    uses: x/agentkit/.github/workflows/triage.yml@v1"
IFACE=claude-slack AM=true; out=$(doctor_interface o/r SLACK_WEBHOOK_URL "action:required" "$jobs" 2>&1)
check "doctor clean when the mode is set up" "! grep -qE 'FAIL|warn' <<<\"\$out\""
out=$(doctor_interface o/r SLACK_WEBHOOK_URL "action:required" "${jobs%%$'\n'*}" 2>&1)
check "doctor warns about the missing triage job only" "grep -q 'warn  .*triage' <<<\"\$out\" && ! grep -q 'warn  .*reply' <<<\"\$out\""
exit $fail
