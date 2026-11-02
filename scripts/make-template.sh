#!/usr/bin/env bash
# Build the agentkit-template repo contents from templates/ (the single source).
# Usage: scripts/make-template.sh <empty-dir>
set -euo pipefail
out=${1:?target dir}; kit=$(cd "$(dirname "$0")/.." && pwd)
kit_repo=$(git -C "$kit" remote get-url origin | sed -E 's#^(https://github.com/|git@github.com:)##; s#\.git$##')
mkdir -p "$out"
cp -Rp "$kit/templates/." "$out/"
# the template repo is generated per kit, so its files name this kit instead of the your-org/agentkit placeholder
grep -rlF "your-org/agentkit" "$out" | while IFS= read -r f; do sed -i.bak "s#your-org/agentkit#$kit_repo#g" "$f" && rm "$f.bak"; done
cat >"$out/README.md" <<MD
# New agentkit project

Created from \`${kit_repo%/*}/agentkit-template\`. One-time setup (from a machine with \`gh agentkit\` installed):

    gh agentkit setup <owner>/<repo>
    gh agentkit secrets <owner>/<repo>
    gh agentkit doctor <owner>/<repo>

Then fill in **Commands** in \`CLAUDE.md\` and \`.agentkit/test.sh\`. See ${kit_repo} for the lifecycle.
MD
echo "template written to $out"
