#!/usr/bin/env bash
# gh agentkit upgrade, file edits only: an old marketplace name is renamed in settings and caller.
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
    "label edit"*) echo "$*" >>"$tmp/calls" ;;
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
exit $fail
