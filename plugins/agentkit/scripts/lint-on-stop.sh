#!/usr/bin/env bash
# Stop hook: run the project's .agentkit/lint.sh when there are uncommitted
# changes (or always in CI). On failure, exit 2 so Claude keeps going and fixes it.
set -u
input=$(cat)
[ "$(jq -r '.stop_hook_active // false' <<<"$input")" = "true" ] && exit 0
root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
lint="$root/.agentkit/lint.sh"
[ -x "$lint" ] || exit 0
if [ -z "${CI:-}" ] && git -C "$root" diff --quiet HEAD 2>/dev/null; then exit 0; fi
if ! out=$(cd "$root" && "$lint" 2>&1); then
  printf 'agentkit lint failed (.agentkit/lint.sh). Fix these before stopping:\n%s\n' "$(tail -n 60 <<<"$out")" >&2
  exit 2
fi
