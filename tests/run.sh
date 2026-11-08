#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
shellcheck -x -S warning cli/gh-agentkit/gh-agentkit runner/*.sh scripts/*.sh tests/*.sh \
  plugins/agentkit/scripts/lint-on-stop.sh templates/.agentkit/*.sh
echo "shellcheck: ok"
# macOS ships bash 3.2, which parses some quoting that shellcheck accepts differently
for f in cli/gh-agentkit/gh-agentkit scripts/*.sh; do /bin/bash -n "$f"; done && echo "bash 3.2 parse: ok"
tests/test_guard.sh
tests/test_set_status.sh
tests/test_stuck.sh
tests/test_blockers.sh
tests/test_drop_dependency.sh
tests/test_hold.sh
tests/test_apply_reply.sh
tests/test_people.sh
tests/test_checklist.sh
tests/test_upgrade.sh
python3 tests/test_marketplace.py
python3 tests/test_docs.py
python3 tests/test_caller.py
python3 tests/test_checks.py
python3 tests/test_retro.py
python3 tests/test_permissions.py
python3 tests/test_board.py
python3 tests/test_reply.py
python3 tests/test_recommendation.py
python3 tests/test_ask.py
python3 tests/test_split.py
python3 tests/test_done.py
python3 tests/test_bot_core.py
python3 tests/test_slackrec.py
python3 -m py_compile plugins/agentkit/scripts/guard.py plugins/agentkit/scripts/docs.py plugins/agentkit/scripts/board.py cli/gh-agentkit/caller.py scripts/checks.py scripts/retro.py scripts/reply.py scripts/recommendation.py scripts/ask.py scripts/split.py scripts/done.py
