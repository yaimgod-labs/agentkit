#!/usr/bin/env python3
"""agentkit retro metrics: one week of issues in, a markdown summary out.

  retro.py < {"since": ISO, "issues": [{number, title, closed_at, state_reason, labels: [names],
                                        events: [{event, label: {name}, created_at}]}],
              "usage": [{job, model, turns, cost_usd, minutes, error}]}

Cycle time is first `status:in-progress` to close; fix rounds count `status:changes-requested`;
handovers count `reason:*` labels added since `since`, except `reason:retry` (an automatic retry);
usage is one entry per Claude run (.github/actions/usage), summed per job.
"""
import json
import statistics
import sys
from collections import Counter
from datetime import datetime


def iso(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def added(issue, name=None, prefix=None):
    return [e for e in issue.get("events", []) if e.get("event") == "labeled"
            and (e["label"]["name"] == name or (prefix and e["label"]["name"].startswith(prefix)))]


def usage(runs):
    by = {}
    for r in runs:
        by.setdefault(r["job"], []).append(r)
    if not by:
        return "- **Claude runs:** no usage recorded"
    parts = []
    for job, rs in sorted(by.items(), key=lambda kv: -sum(r["cost_usd"] for r in kv[1])):
        failed = sum(bool(r["error"]) for r in rs)
        parts.append(f"{job} ×{len(rs)} ({'/'.join(sorted({r['model'] for r in rs}))}): "
                     f"median {statistics.median(r['turns'] for r in rs):g} turns, "
                     f"{statistics.median(r['minutes'] for r in rs):g} min, est. ${sum(r['cost_usd'] for r in rs):.2f}"
                     + (f", {failed} failed" if failed else ""))
    return "- **Claude runs** (most est. cost first): " + "; ".join(parts)


def metrics(doc):
    since = iso(doc["since"])
    issues = doc["issues"]
    done = [i for i in issues if i.get("closed_at") and i.get("state_reason") == "completed" and iso(i["closed_at"]) >= since]
    hours, rounds = [], {}
    for i in done:
        start = added(i, "status:in-progress")
        if start:
            hours.append((iso(i["closed_at"]) - iso(start[0]["created_at"])).total_seconds() / 3600)
        rounds[i["number"]] = len(added(i, "status:changes-requested"))
    reasons = Counter()
    for i in issues:
        for e in added(i, prefix="reason:"):
            if iso(e["created_at"]) >= since:
                reasons[e["label"]["name"].split(":", 1)[1]] += 1
    retries = reasons.pop("retry", 0)
    debt = sum("type:debt" in i.get("labels", []) for i in done)
    lines = [f"- **Closed:** {len(done)} ({debt} debt)",
             f"- **Cycle time** (in-progress → closed): median {statistics.median(hours):.1f} h, max {max(hours):.1f} h"
             if hours else "- **Cycle time:** no agent-built issue closed",
             f"- **Fix rounds:** {sum(rounds.values())} over {len(done)} issues"
             + (" — 2 or more: " + ", ".join(f"#{n} ({r})" for n, r in sorted(rounds.items()) if r >= 2)
                if any(r >= 2 for r in rounds.values()) else ""),
             "- **Handovers to a person:** " + (", ".join(f"{r} ×{c}" for r, c in reasons.most_common()) or "none"),
             f"- **Automatic retries** (failed implement runs): {retries}",
             usage(doc.get("usage", []))]
    return "\n".join(lines)


if __name__ == "__main__":
    print(metrics(json.load(sys.stdin)))
