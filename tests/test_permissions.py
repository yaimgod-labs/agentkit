"""A reusable workflow's job may not ask for more than the caller grants (the template's `permissions:`),
or GitHub rejects the whole run at startup. actionlint cannot see this; the kit's writes go through the App token."""
import re, sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
grant = {"contents: read"}
bad = []
for wf in sorted((root / ".github/workflows").glob("*.yml")):
    if "workflow_call:" not in wf.read_text():  # only reusable workflows are bound by the caller's grant
        continue
    lines = wf.read_text().splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^    permissions:\s*$", line):
            for item in lines[i + 1:]:
                if not item.startswith("      "):
                    break
                p = re.sub(r"\s+#.*$", "", item).strip()
                if p and p not in grant:
                    bad.append(f"{wf.name}:{i + 1}: `{p}` exceeds the caller's grant")
    # a job that acts on a repository_dispatch payload checks first that the Slack bot sent it (anyone with write
    # access can send one): a `sender` step before the kit loads and before anything acts
    for job in re.split(r"(?m)^  (?=[a-z][a-z0-9-]*:$)", wf.read_text())[1:]:
        if "client_payload" in job and not re.search(r"- id: sender\n(?:.*\n)*?\s+- name: Load agentkit", job):
            bad.append(f"{wf.name}: job `{job.split(':')[0]}` reads client_payload without a sender check first")
print("\n".join(bad) or "ok: kit jobs ask for no more than the caller grants, and check who sent a Slack event")
sys.exit(1 if bad else 0)
