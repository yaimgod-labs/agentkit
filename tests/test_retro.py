"""scripts/retro.py: a week of issues becomes cycle time, fix rounds and handover counts."""
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/retro.py"


def ev(label, t):
    return {"event": "labeled", "label": {"name": label}, "created_at": f"2026-11-0{t}"}


doc = {"since": "2026-11-02T00:00:00Z", "issues": [
    {"number": 1, "closed_at": "2026-11-03T10:00:00Z", "state_reason": "completed", "labels": ["type:debt"],
     "events": [ev("status:in-progress", "3T08:00:00Z"), ev("status:changes-requested", "3T09:00:00Z"), ev("status:changes-requested", "3T09:30:00Z")]},
    {"number": 2, "closed_at": "2026-11-04T04:00:00Z", "state_reason": "completed", "labels": [],
     "events": [ev("status:in-progress", "4T00:00:00Z")]},
    {"number": 3, "closed_at": "2026-11-01T00:00:00Z", "state_reason": "completed", "labels": [], "events": []},  # before the week
    {"number": 4, "closed_at": None, "labels": [],
     "events": [ev("reason:env", "3T00:00:00Z"), ev("reason:env", "1T00:00:00Z"), ev("reason:flaky", "5T00:00:00Z")]},
]}
out = subprocess.run([sys.executable, str(SCRIPT)], input=json.dumps(doc), capture_output=True, text=True, check=True).stdout
want = ["**Closed:** 2 (1 debt)", "median 3.0 h, max 4.0 h", "**Fix rounds:** 2 over 2 issues — 2 or more: #1 (2)",
        "**Handovers to a person:** env ×1, flaky ×1"]
fails = [w for w in want if w not in out]
for w in want:
    print(("FAIL: " if w in fails else "ok: ") + w)
if fails:
    print(out)
sys.exit(1 if fails else 0)
