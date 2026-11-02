#!/usr/bin/env bash
# Feeds PreToolUse payloads to guard.py; exit 2 = blocked.
set -u
guard="$(cd "$(dirname "$0")/.." && pwd)/plugins/agentkit/scripts/guard.py"
repo=$(mktemp -d); git -C "$repo" init -q -b feature/x
fail=0
expect() { # expect <code> <json>
  out=$(cd "$repo" && CLAUDE_PROJECT_DIR="$repo" python3 "$guard" <<<"$2" 2>&1); code=$?
  [ "$code" = "$1" ] || { echo "FAIL want $1 got $code: $2 ($out)"; fail=1; }
}
bash() { printf '{"tool_name":"Bash","cwd":"%s","tool_input":{"command":"%s"}}' "$repo" "$1"; }
edit() { printf '{"tool_name":"Edit","cwd":"%s","tool_input":{"file_path":"%s"}}' "$repo" "$1"; }
expect 2 "$(bash 'git push origin main')"
expect 2 "$(bash 'git push origin HEAD:refs/heads/master')"
expect 2 "$(bash 'npm test && git push --force origin feature/x')"
expect 2 "$(bash 'git push origin +feature/x')"
expect 2 "$(bash 'git -C . reset --hard HEAD~1')"
expect 0 "$(bash 'git push -u origin feature/x')"
expect 0 "$(bash 'git status && echo main')"
expect 2 "$(edit '/etc/passwd')"
expect 2 "$(edit "$repo/../escape.txt")"
expect 0 "$(edit "$repo/src/a.ts")"
expect 0 "$(edit 'src/relative.ts')"
git -C "$repo" checkout -q -b main
expect 2 "$(bash 'git push')"
rm -rf "$repo"
[ $fail = 0 ] && echo "guard: ok"
exit $fail
