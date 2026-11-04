#!/usr/bin/env python3
"""agentkit checks: which configured suites or external checks a change needs, and the gate's verdict.

  checks.py select CONFIG_JSON < changed-files
      CONFIG_JSON is a list of {"name", "paths": [globs], ...}; prints the entries with a path that
      matches a changed file (an entry without `paths` always matches). Globs are fnmatch: `*` also
      matches `/`, so `server/**` and `server/*` both cover everything under server/.
  checks.py gate < {"check_runs", "statuses", "required", "since", "now", "timeout"}
      check_runs and statuses as the GitHub API returns them for one commit; required: names that must
      report (a name also matches "<caller job> / <name>"); since/now: ISO times; timeout: minutes a
      check may stay pending or missing.
      Prints {"verdict": pass|fail|wait|timeout, "failed": [{name, detail}], "pending": [names]}.
  checks.py rounds BOT < {"comments": [{"user", "body"}, ...], "people": [comment ids]}
      A PR's comments, oldest first; prints how many failed review rounds count: the comments by BOT (the kit)
      that start with `<!-- agentkit:round` after its latest reset. A reset is a BOT comment that starts with
      `<!-- agentkit:reset-rounds <id> -->`, where <id> is in `people` (the ids of the issue's comments by people
      with write access: a Slack retry or guidance) and no earlier reset named it. Nobody else's comment counts or
      resets, a marker inside a comment (quoted check output) is not one, and an agent that can comment as the kit
      can neither invent a reset nor replay one. A bare comment list means no people.
  checks.py decided < {"pr": [bodies], "issue": [{"id", "body"}], "after": id or null}
      `true` when a person decided an RFC: `pr` holds the PR's comments and `issue` the issue's comments, both
      already limited to people with write access (never a bot); `after` is the id of the kit's latest
      `<!-- agentkit:recommendation -->` comment on the issue. A PR comment that starts with `/decide accept|reject`,
      or an issue comment (a Slack reply) after the recommendation whose first word is accept or reject; with no
      recommendation, issue comments never count. Else, or on unreadable input, `false`. The kit's own relayed
      /decide never counts by itself.
"""
import fnmatch
import json
import re
import sys
from datetime import datetime

FAILED = {"failure", "timed_out", "action_required", "startup_failure", "stale"}


def select(config, files):
    entries = json.loads(config) if config.strip() else []
    return [e for e in entries
            if "paths" not in e or any(fnmatch.fnmatchcase(f, p) for f in files for p in e["paths"])]


def iso(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def link(url):
    return f" ({url})" if url else ""


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
            failed.append({"name": name, "detail": f"{c['conclusion']}: {detail or 'no summary'}{link(c.get('html_url'))}"})
        # success, neutral, skipped pass; cancelled means a newer run superseded it
    for s in doc.get("statuses", []):  # the combined status API already returns the latest per context
        seen.add(s["context"])
        if s["state"] == "pending":
            pending.append(s["context"])
        elif s["state"] in ("failure", "error"):
            failed.append({"name": s["context"], "detail": f"{s['state']}: {s.get('description') or 'no description'}{link(s.get('target_url'))}"})
    # a required name is a check name, or a job name under a caller job ("review / docs" reports "docs")
    pending += [n for n in doc.get("required", []) if not any(s == n or s.endswith(" / " + n) for s in seen)]
    if failed:
        verdict = "fail"
    elif pending:
        age = (iso(doc["now"]) - iso(doc["since"])).total_seconds() / 60
        verdict = "timeout" if age > doc["timeout"] else "wait"
    else:
        verdict = "pass"
    return {"verdict": verdict, "failed": failed, "pending": pending}


RESET = re.compile(r"<!-- agentkit:reset-rounds ([1-9][0-9]*) -->")


def rounds(doc, bot):
    comments, people = (doc, []) if isinstance(doc, list) else (doc.get("comments", []), doc.get("people", []))
    people, used, n = {str(p) for p in people}, set(), 0
    for c in comments:
        body = c.get("body") or ""
        if c.get("user") != bot:
            continue
        m = RESET.match(body)
        if m:
            if m.group(1) in people and m.group(1) not in used:
                used.add(m.group(1))
                n = 0
        elif body.startswith("<!-- agentkit:round"):
            n += 1
    return n


def decided(doc):
    if not isinstance(doc, dict):
        return False
    pr, issue, after = doc.get("pr", []), doc.get("issue", []), doc.get("after")
    if not (isinstance(pr, list) and all(isinstance(b, str) for b in pr) and isinstance(issue, list)
            and all(isinstance(c, dict) and isinstance(c.get("id"), int) and isinstance(c.get("body"), str) for c in issue)):
        return False
    if any(re.match(r"/decide (accept|reject)\b", b, re.I) for b in pr):
        return True
    # a Slack reply answers the kit's latest recommendation: only comments after it count, none without one
    if not isinstance(after, int) or isinstance(after, bool):
        return False
    return any(c["id"] > after and (c["body"].split(None, 1) or [""])[0].rstrip(".,:!").lower() in ("accept", "reject")
               for c in issue)


def main(argv):
    if argv[:1] == ["select"]:
        print(json.dumps(select(argv[1] if len(argv) > 1 else "", sys.stdin.read().split())))
    elif argv[:1] == ["gate"]:
        print(json.dumps(gate(json.load(sys.stdin))))
    elif argv[:1] == ["rounds"] and len(argv) == 2 and argv[1]:
        print(rounds(json.load(sys.stdin), argv[1]))
    elif argv == ["decided"]:
        try:
            ok = decided(json.load(sys.stdin))
        except Exception:
            ok = False
        print("true" if ok else "false")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
