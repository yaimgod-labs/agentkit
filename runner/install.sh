#!/usr/bin/env bash
# Install N ephemeral agentkit runner slots on an Ubuntu host with Docker + systemd.
# Usage: sudo ORG=<org> PAT=github_pat_... ./install.sh [slots=3] [label=self-hosted]
set -euo pipefail
: "${ORG:?set ORG}" "${PAT:?set PAT (fine-grained, org permission Self-hosted runners: read and write)}"
slots=${1:-3}; label=${2:-self-hosted}
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
command -v docker >/dev/null || { echo "install Docker first"; exit 1; }
command -v systemctl >/dev/null || { echo "systemd is required"; exit 1; }
here=$(cd "$(dirname "$0")" && pwd)

docker build -t agentkit-runner:latest "$here"
install -m 755 "$here/runner-loop.sh" /usr/local/bin/agentkit-runner-loop
(umask 077; printf 'ORG=%s\nLABEL=%s\nPAT=%s\n' "$ORG" "$label" "$PAT" >/etc/agentkit-runner.env)

cat >/etc/systemd/system/agentkit-runner@.service <<UNIT
[Unit]
Description=agentkit ephemeral runner slot %i
After=docker.service
Requires=docker.service

[Service]
EnvironmentFile=/etc/agentkit-runner.env
ExecStart=/usr/local/bin/agentkit-runner-loop %i
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
for i in $(seq 1 "$slots"); do systemctl enable --now "agentkit-runner@$i"; done
echo "started $slots slot(s) with label '$label'. Then: gh variable set AGENTKIT_RUNNER --repo <owner/repo> --body $label"
