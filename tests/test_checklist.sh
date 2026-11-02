#!/usr/bin/env bash
# checklist.sh: unticked boxes outside / inside the "## Human verification" section.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
fail=0
check() {  # name expected body
  got=$(printf '%s' "$3" | "$here/../scripts/checklist.sh")
  if [ "$got" = "$2" ]; then echo "ok: $1"; else echo "FAIL: $1: got '$got', want '$2'"; fail=1; fi
}
check "empty body" "0 0" ""
check "all ticked" "0 0" $'## Acceptance criteria\n- [x] a\n- [X] b\n'
check "unmet criterion" "1 0" $'## Acceptance criteria\n- [x] a\n- [ ] b\n'
check "human items only" "0 2" $'## Acceptance criteria\n- [x] a\n\n## Human verification\n- [ ] on device\n  - [ ] dark mode\n'
check "section ends at next heading" "1 1" $'## Human verification\n- [ ] device\n## Docs\n- [ ] docs reviewed: x\n'
check "heading case-insensitive" "0 1" $'### human Verification\n- [ ] look\n'
check "ticked human items" "0 0" $'## Human verification\n- [x] checked on iPhone\n'
exit $fail
