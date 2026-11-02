#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
shellcheck -x -S warning cli/gh-agentkit/gh-agentkit runner/*.sh scripts/*.sh tests/*.sh \
  plugins/agentkit/scripts/lint-on-stop.sh templates/.agentkit/*.sh
echo "shellcheck: ok"
# macOS ships bash 3.2, which parses some quoting that shellcheck accepts differently
/bin/bash -n cli/gh-agentkit/gh-agentkit && echo "bash 3.2 parse: ok"
tests/test_guard.sh
tests/test_set_status.sh
tests/test_checklist.sh
python3 tests/test_marketplace.py
python3 tests/test_docs.py
python3 tests/test_caller.py
python3 -m py_compile plugins/agentkit/scripts/guard.py plugins/agentkit/scripts/docs.py cli/gh-agentkit/caller.py
