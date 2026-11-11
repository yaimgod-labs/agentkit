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

# --interface slack: sets the variables and prints the Slack lines; doctor checks it only when on
gh() { case "$*" in "variable set"*) echo "$*" >>"$tmp/vars" ;; esac; }
out=$(enable_interface o/r)
check "interface variable set" "grep -qx 'variable set AGENTKIT_INTERFACE --repo o/r --body slack' '$tmp/vars'"
check "auto-merge variable set" "grep -qx 'variable set AUTO_MERGE --repo o/r --body true' '$tmp/vars'"
check "subscribe line printed" "grep -qF '/github subscribe o/r issues comments +label:\"action:required\"' <<<\"\$out\""
check "unsubscribe line printed" "grep -qF '/github unsubscribe o/r pulls commits releases deployments' <<<\"\$out\""
check "signin reminder printed" "grep -qF '/github signin' <<<\"\$out\""
check "unknown interface refused" "! (parse_interface nope) 2>/dev/null"
check "slack interface accepted" "(parse_interface slack)"
check "old claude-slack flag refused" "! (parse_interface claude-slack) 2>/dev/null"
ok() { echo "  ok    $*"; }
bad() { echo "  FAIL  $*"; dfail=1; }
warn() { echo "  warn  $*"; }
var_get() { case $2 in AGENTKIT_INTERFACE) echo "$IFACE" ;; AUTO_MERGE) echo "$AM" ;; esac; }
IFACE="" AM=""; out=$(doctor_interface o/r "" ""; true)
check "doctor silent with the mode off" "[ -z \"\$out\" ]"
IFACE=slack AM=""; dfail=0; out=$(doctor_interface o/r "" "x" 2>&1; echo "dfail=\$dfail")
check "doctor fails without AUTO_MERGE" "grep -q 'FAIL  .*AUTO_MERGE' <<<\"\$out\""
check "doctor warns without the webhook" "grep -q 'warn  .*SLACK_WEBHOOK_URL' <<<\"\$out\""
check "doctor warns without the label" "grep -q 'warn  .*action:required' <<<\"\$out\""
check "doctor prints the signin reminder" "grep -q '/github signin' <<<\"\$out\""
check "doctor warns without the reply job" "grep -q 'warn  .*reply' <<<\"\$out\""
check "doctor warns without the triage job" "grep -q 'warn  .*triage' <<<\"\$out\""
jobs="    uses: x/agentkit/.github/workflows/reply.yml@v1
    uses: x/agentkit/.github/workflows/triage.yml@v1"
IFACE=slack AM=true; out=$(doctor_interface o/r SLACK_WEBHOOK_URL "action:required" "$jobs" 2>&1)
check "doctor clean when the mode is set up" "! grep -qE 'FAIL|warn' <<<\"\$out\""
out=$(doctor_interface o/r SLACK_WEBHOOK_URL "action:required" "${jobs%%$'\n'*}" 2>&1)
IFACE=claude-slack AM=true; old=$(doctor_interface o/r SLACK_WEBHOOK_URL "action:required" "$jobs" 2>&1)
check "doctor warns about the old claude-slack value" "grep -q 'warn  .*old value claude-slack' <<<\"\$old\""
caller_takes_slack() { [ "$TAKES" = yes ]; }
IFACE=claude-slack TAKES=no; check "old value kept while the caller does not know slack" "[ \"\$(interface_value o/r 2>/dev/null)\" = claude-slack ]"
IFACE=claude-slack TAKES=yes; check "old value becomes slack once the caller knows it" "[ \"\$(interface_value o/r 2>/dev/null)\" = slack ]"
IFACE="" TAKES=no; check "a project new to the mode gets slack" "[ \"\$(interface_value o/r 2>/dev/null)\" = slack ]"
IFACE=slack
check "doctor warns about the missing triage job only" "grep -q 'warn  .*triage' <<<\"\$out\" && ! grep -q 'warn  .*reply' <<<\"\$out\""

# --interface slack-bot: the Slack mode plus the bot's variables; the token is only ever named, never read
check "slack-bot interface accepted" "(parse_interface slack-bot)"
check "channel id C… valid" "valid_channel C0123ABC && valid_channel G01AB"
check "bad channel ids refused" "! valid_channel c0123 && ! valid_channel '#general' && ! valid_channel C && ! valid_channel 'C01 X'"
check "--card-channel given is used" "[ \"\$(card_channel o/r C0NEW </dev/null)\" = C0NEW ]"
check "--card-channel malformed refused" "! (card_channel o/r general </dev/null) 2>/dev/null"
var_get() { case $2 in AGENTKIT_CARD_CHANNEL) echo C0OLD ;; esac; }
check "existing channel kept without --card-channel" "[ \"\$(card_channel o/r '' </dev/null)\" = C0OLD ]"
var_get() { true; }
check "no channel and no terminal refused" "! (card_channel o/r '' </dev/null) 2>/dev/null"
gh() { case "$*" in "variable set"*) echo "$*" >>"$tmp/bvars" ;; secret*) echo "$*" >>"$tmp/secret-calls" ;; esac; }
out=$(SLACK_BOT_TOKEN=xoxb-secret-value enable_interface o/r slack-bot C0123ABC)
check "bot: interface variable set" "grep -qx 'variable set AGENTKIT_INTERFACE --repo o/r --body slack' '$tmp/bvars'"
check "bot: auto-merge variable set" "grep -qx 'variable set AUTO_MERGE --repo o/r --body true' '$tmp/bvars'"
check "bot: bot variable set" "grep -qx 'variable set AGENTKIT_SLACK_BOT --repo o/r --body true' '$tmp/bvars'"
check "bot: channel variable set" "grep -qx 'variable set AGENTKIT_CARD_CHANNEL --repo o/r --body C0123ABC' '$tmp/bvars'"
check "bot: secret command printed" "grep -qF 'gh secret set SLACK_BOT_TOKEN --repo o/r' <<<\"\$out\""
check "bot: secret never set or echoed" "[ ! -e '$tmp/secret-calls' ] && ! grep -q xoxb-secret-value <<<\"\$out\""
: >"$tmp/bvars"; out=$(enable_interface o/r slack "")
check "slack leaves the bot variables alone" "! grep -q 'SLACK_BOT\|CARD_CHANNEL' '$tmp/bvars'"

# doctor's bot checks: only with AGENTKIT_SLACK_BOT=true
bot_caller=$(sed -e 's#your-org/agentkit#x/agentkit#g' "$KIT/templates/.github/workflows/agentkit.yml")
var_get() { case $2 in AGENTKIT_SLACK_BOT) echo "$BOT" ;; AGENTKIT_INTERFACE) echo "$IFACE" ;; AGENTKIT_CARD_CHANNEL) echo "$CHAN" ;; esac; }
curl() { cat >"$tmp/curl-config"; echo "$*" >>"$tmp/curl-calls"; case "$*" in *auth.test*) echo "$AUTH" ;; *conversations.info*) echo "$CONV" ;; esac; }
BOT="" IFACE=slack CHAN=""; out=$(doctor_bot o/r "" ""; true)
check "doctor bot silent with the bot off" "[ -z \"\$out\" ]"
BOT=true IFACE="" CHAN=""; out=$(unset SLACK_BOT_TOKEN; doctor_bot o/r "" "name: agentkit" 2>&1)
check "doctor bot fails without the interface" "grep -q 'FAIL  .*AGENTKIT_INTERFACE.*gh agentkit upgrade o/r --interface slack-bot' <<<\"\$out\""
check "doctor bot fails without the channel" "grep -q 'FAIL  .*AGENTKIT_CARD_CHANNEL.*--card-channel' <<<\"\$out\""
check "doctor bot fails without the secret" "grep -q 'FAIL  .*SLACK_BOT_TOKEN.*gh secret set SLACK_BOT_TOKEN --repo o/r' <<<\"\$out\""
check "doctor bot flags the missing trigger" "grep -qE '(FAIL|warn)  .*repository_dispatch' <<<\"\$out\""
check "doctor bot flags the missing card job" "grep -qE '(FAIL|warn)  .*card job' <<<\"\$out\""
check "doctor bot flags dispatch without the token" "grep -qE '(FAIL|warn)  .*dispatch job' <<<\"\$out\""
check "doctor bot skips live checks without a local token" "[ ! -e '$tmp/curl-calls' ] && grep -q 'SLACK_BOT_TOKEN' <<<\"\$out\""
BOT=true CHAN=general; out=$(unset SLACK_BOT_TOKEN; doctor_bot o/r SLACK_BOT_TOKEN "$bot_caller" 2>&1)
check "doctor bot fails on a malformed channel" "grep -q 'FAIL  .*AGENTKIT_CARD_CHANNEL' <<<\"\$out\""
BOT=true IFACE=slack CHAN=C0123ABC; out=$(unset SLACK_BOT_TOKEN; doctor_bot o/r SLACK_BOT_TOKEN "$bot_caller" 2>&1)
check "doctor bot clean when set up" "! grep -qE 'FAIL|warn' <<<\"\$out\""
AUTH='{"ok":true,"user":"agentkit","team":"Acme"}' CONV='{"ok":true,"channel":{"name":"agentkit-cards","is_member":true}}'
out=$(SLACK_BOT_TOKEN=xoxb-secret-value doctor_bot o/r SLACK_BOT_TOKEN "$bot_caller" 2>&1)
check "doctor bot live: token and channel ok" "grep -q 'ok    .*auth.test' <<<\"\$out\" && grep -q 'ok    .*agentkit-cards' <<<\"\$out\" && ! grep -qE 'FAIL|warn' <<<\"\$out\""
check "doctor bot live: token only in curl's stdin config" "! grep -q xoxb-secret-value '$tmp/curl-calls' && grep -q xoxb-secret-value '$tmp/curl-config' && ! grep -q xoxb-secret-value <<<\"\$out\""
check "doctor bot live: channel id sent" "grep -q 'channel=C0123ABC' '$tmp/curl-calls'"
CONV='{"ok":true,"channel":{"name":"agentkit-cards","is_member":false}}'
out=$(SLACK_BOT_TOKEN=x doctor_bot o/r SLACK_BOT_TOKEN "$bot_caller" 2>&1)
check "doctor bot live: warns when the bot is not in the channel" "grep -q 'warn  .*not in #agentkit-cards' <<<\"\$out\""
CONV='{"ok":false,"error":"missing_scope","needed":"channels:read"}'
out=$(SLACK_BOT_TOKEN=x doctor_bot o/r SLACK_BOT_TOKEN "$bot_caller" 2>&1)
check "doctor bot live: missing scope is a can't-check, not a failure" "grep -q \"can't check.*needs channels:read\" <<<\"\$out\" && ! grep -q FAIL <<<\"\$out\""
CONV='{"ok":false,"error":"channel_not_found"}'
out=$(SLACK_BOT_TOKEN=x doctor_bot o/r SLACK_BOT_TOKEN "$bot_caller" 2>&1)
check "doctor bot live: unknown channel fails" "grep -q 'FAIL  .*channel_not_found' <<<\"\$out\""
AUTH='{"ok":false,"error":"invalid_auth"}'
out=$(SLACK_BOT_TOKEN=x doctor_bot o/r SLACK_BOT_TOKEN "$bot_caller" 2>&1)
check "doctor bot live: bad token fails" "grep -q 'FAIL  .*invalid_auth' <<<\"\$out\""
unset -f curl
exit $fail
