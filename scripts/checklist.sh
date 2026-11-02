#!/usr/bin/env bash
# Usage: checklist.sh < pr-body.md
# Prints "<unmet> <human>": unticked boxes outside / inside the "## Human verification" section.
# The gate fails a round on unmet > 0; human > 0 waits for a person (status:needs-device-check).
awk '/^#+ /{hv = (tolower($0) ~ /^#+ human verification/)} /^[[:space:]]*- \[ \]/{if (hv) h++; else u++} END{print u+0, h+0}'
