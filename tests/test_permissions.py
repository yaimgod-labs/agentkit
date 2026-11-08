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
print("\n".join(bad) or "ok: kit jobs ask for no more than the caller grants")
sys.exit(1 if bad else 0)
