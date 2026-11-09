#!/usr/bin/env bash
# scripts/merge-pr.sh: the project's merge method and branch deletion, with a safe default.
set -euo pipefail
cd "$(dirname "$0")/.."
bin=$(mktemp -d); trap 'rm -rf "$bin"' EXIT
printf '#!/usr/bin/env bash\necho "$*"\n' >"$bin/gh"; chmod +x "$bin/gh"
fails=0
check() { if [ "$2" = "$3" ]; then echo "ok: $1"; else echo "FAIL: $1: got '$2', want '$3'"; fails=1; fi; }
run() { env PATH="$bin:$PATH" "$@" scripts/merge-pr.sh 7 o/r 2>/dev/null; }
check "default: squash, delete the branch" "$(run)" "pr merge 7 --repo o/r --squash --delete-branch"
check "rebase" "$(run AGENTKIT_MERGE_METHOD=rebase)" "pr merge 7 --repo o/r --rebase --delete-branch"
check "keep the branch" "$(run AGENTKIT_MERGE_METHOD=merge AGENTKIT_DELETE_BRANCH=false)" "pr merge 7 --repo o/r --merge"
check "a bad method falls back to squash" "$(run 'AGENTKIT_MERGE_METHOD=--admin')" "pr merge 7 --repo o/r --squash --delete-branch"
exit $fails
