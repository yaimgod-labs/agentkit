#!/usr/bin/env bash
# One ephemeral runner slot: register with a just-in-time config, run exactly one
# job in a fresh container, repeat. Needs ORG, LABEL, PAT (fine-grained, org
# "Self-hosted runners: read and write") in /etc/agentkit-runner.env.
set -euo pipefail
slot=${1:?slot}
group_id=$(curl -fsS -H "Authorization: Bearer $PAT" "https://api.github.com/orgs/$ORG/actions/runner-groups" \
  | jq -r '.runner_groups[] | select(.default) | .id')
while true; do
  name="agentkit-$(hostname -s)-$slot-$(date +%s)"
  jit=$(curl -fsS -X POST -H "Authorization: Bearer $PAT" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/orgs/$ORG/actions/runners/generate-jitconfig" \
    -d "$(jq -n --arg n "$name" --arg l "$LABEL" --argjson g "$group_id" '{name:$n, runner_group_id:$g, labels:[$l]}')" \
    | jq -r .encoded_jit_config) || { sleep 60; continue; }
  docker run --rm --name "$name" --memory "${MEMORY:-6g}" --cpus "${CPUS:-2}" agentkit-runner:latest \
    ./run.sh --jitconfig "$jit" || sleep 10
done
