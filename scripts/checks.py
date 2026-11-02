#!/usr/bin/env python3
"""agentkit checks: which configured suites or external checks a change needs, and the gate's verdict.

  checks.py select CONFIG_JSON < changed-files
      CONFIG_JSON is a list of {"name", "paths": [globs], ...}; prints the entries with a path that
      matches a changed file (an entry without `paths` always matches). Globs are fnmatch: `*` also
      matches `/`, so `server/**` and `server/*` both cover everything under server/.
  checks.py gate < {"check_runs", "statuses", "required", "since", "now", "timeout"}
      check_runs and statuses as the GitHub API returns them for one commit; required: names that must
      report; since/now: ISO times; timeout: minutes a check may stay pending or missing.
      Prints {"verdict": pass|fail|wait|timeout, "failed": [{name, detail}], "pending": [names]}.
"""
import fnmatch
import json
import sys
from datetime import datetime

FAILED = {"failure", "timed_out", "action_required", "startup_failure", "stale"}


def select(config, files):
    entries = json.loads(config) if config.strip() else []
    return [e for e in entries
            if "paths" not in e or any(fnmatch.fnmatchcase(f, p) for f in files for p in e["paths"])]


def iso(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def gate(doc):
    failed, pending, seen = [], [], set()
    latest = {}
    for c in doc.get("check_runs", []):
        if c["name"].split(" / ")[-1] == "gate":  # the gate itself, in this or another run
            continue
        if c["name"] not in latest or c["id"] > latest[c["name"]]["id"]:
            latest[c["name"]] = c
    for name, c in sorted(latest.items()):
        seen.add(name)
        if c["status"] != "completed":
            pending.append(name)
        elif c["conclusion"] in FAILED:
            out = c.get("output") or {}
            detail = " — ".join(x for x in (out.get("title"), out.get("summary")) if x)[:1500]
            failed.append({"name": name, "detail": f"{c['conclusion']}: {detail or 'no summary'} ({c.get('html_url', '')})"})
        # success, neutral, skipped pass; cancelled means a newer run superseded it
    for s in doc.get("statuses", []):  # the combined status API already returns the latest per context
        seen.add(s["context"])
        if s["state"] == "pending":
            pending.append(s["context"])
        elif s["state"] in ("failure", "error"):
            failed.append({"name": s["context"], "detail": f"{s['state']}: {s.get('description') or 'no description'} ({s.get('target_url') or ''})"})
    pending += [n for n in doc.get("required", []) if n not in seen]
    if failed:
        verdict = "fail"
    elif pending:
        age = (iso(doc["now"]) - iso(doc["since"])).total_seconds() / 60
        verdict = "timeout" if age > doc["timeout"] else "wait"
    else:
        verdict = "pass"
    return {"verdict": verdict, "failed": failed, "pending": pending}


def main(argv):
    if argv[:1] == ["select"]:
        print(json.dumps(select(argv[1] if len(argv) > 1 else "", sys.stdin.read().split())))
    elif argv[:1] == ["gate"]:
        print(json.dumps(gate(json.load(sys.stdin))))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
