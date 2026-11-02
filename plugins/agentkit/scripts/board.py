#!/usr/bin/env python3
"""The kit's one task order, cycle-time estimates and markdown board. Python 3.8+, stdlib only.

The dispatcher (`.github/workflows/dispatch.yml`) and the `/board` command both call this, so what the
board calls "Up next" is exactly what the dispatcher takes next.

  board.py order --debt-due true|false [--debt-every N] [--debt-label L]
      stdin:  [{"number": 7, "author": "alice", "labels": ["priority:high"], "rank": 2 | null}, ...]
      stdout: the same issues (every field kept), filtered and sorted, as JSON.
      Dropped: mode:human, size:m, size:l (people's work, and work that must be split first).
      Sort key: (rank is null, rank, d, p, number)
        rank  the manual `Rank` number on the Projects board; a ranked issue always goes before unranked ones
        d     debt flag: debt-every > 0 and (has the debt label != debt-due), so debt goes first only when it is
              due and last otherwise (false sorts before true)
        p     priority:high 0, priority:medium 1, priority:low 2, none 3
        number
      A missing "rank" is the same as null. With no rank anywhere this is the dispatcher's order from before ranks.

  board.py debt-due --every N --debt-label L
      stdin:  {"open": [["status:in-progress", "type:debt", ...], ...],
               "closed": [{"labels": [...], "closed_at": ISO, "state_reason": "completed"}, ...]}
      stdout: `true` or `false`: whether debt goes first now (the `--debt-due` input of `order`).
      "open" is the label names of every open issue (not pull requests); this script keeps the ones in flight
      (in-progress, review, changes-requested, approved, needs-verification). "closed" is the caller's closed issues,
      newest closed_at first; this script keeps the completed ones, in the order given.
      The window is the first EVERY-1 issues taken into work: the in-flight open ones, then the most recently closed.
      Due when none of them has the debt label. With --every 0 the quota is off and the answer is `false`.

  board.py estimate
      stdin:  {"closed": [{"size": "s", "started_at": ISO, "closed_at": ISO}, ...], "open": [{"number": 7, "size": "s"}, ...]}
      stdout: {"7": "~3h–6h" | "~2–4 days" | default, ...} as JSON.
      Per size, the last 20 closed issues (by closed_at) give cycle times in hours; with 5 or more, the estimate is
      their 25th–75th percentile ("~Q1h–Q3h", whole hours; "~X–Y days" once Q3 is 24 h or more). Fewer than 5 samples:
      xs "<1h", s "≤1 day", m "several days", l "an epic". An open issue with no size gets no entry.

  board.py render
      stdin:  {"issues": [{"number": 7, "title": "...", "labels": ["status:ready", ...], "rank": 2 | null,
                           "author": "alice", "block_reasons": ["reason", ...]}, ...],
               "deps": {"7": {"waiting_on": [4], "holds_up": [9]}},   # waiting_on = open blockers, by issue number
               "estimates": {"7": "~3h–6h"},                          # the output of `estimate`
               "order": {"debt_due": false, "debt_every": 0, "debt_label": "type:debt"}}   # optional, as for `order`
      stdout: markdown, one section each for Waiting on you, In progress, Up next (top 5) and Blocked (with the
      issue's block_reasons), every line `- #n title — stage — estimate — waiting on #b`. An issue is shown
      once, in the first section it fits. Issues in any other status (backlog, ...) are not shown.
"""
import argparse
import json
import statistics
import sys
from datetime import datetime

DEFAULT_ESTIMATE = {"xs": "<1h", "s": "≤1 day", "m": "several days", "l": "an epic"}
MIN_SAMPLES, MAX_SAMPLES = 5, 20
UP_NEXT = 5
DEBT_WINDOW_STATUS = ("status:in-progress", "status:review", "status:changes-requested", "status:approved", "status:needs-verification")

WAITING = ("status:needs-info", "status:needs-human", "status:needs-verification", "status:needs-approval")
IN_PROGRESS = ("status:in-progress", "status:review", "status:changes-requested", "status:approved", "status:refining")
STAGE = {
    "backlog": "Backlog", "ready": "Ready", "in-progress": "In progress", "review": "Review",
    "changes-requested": "Changes requested", "approved": "Approved", "blocked": "Blocked", "needs-human": "Needs human",
    "refining": "Refining", "needs-info": "Needs info", "needs-verification": "Needs verification",
    "needs-approval": "Needs approval",
}


def sort_key(issue, due, every, debt):
    labels = issue.get("labels") or []
    rank = issue.get("rank")
    priority = 0 if "priority:high" in labels else 1 if "priority:medium" in labels else 2 if "priority:low" in labels else 3
    d = every > 0 and ((debt in labels) != due)
    return (rank is None, rank if rank is not None else 0, d, priority, issue["number"])


def order(issues, due=False, every=0, debt="type:debt"):
    kept = [i for i in issues if not any(l in ("mode:human", "size:m", "size:l") for l in i.get("labels") or [])]
    return sorted(kept, key=lambda i: sort_key(i, due, every, debt))


def debt_due(doc, every, debt):
    if every <= 0:
        return False
    flight = [l for l in doc.get("open") or [] if any(x in DEBT_WINDOW_STATUS for x in l)]
    done = [c.get("labels") or [] for c in doc.get("closed") or [] if c.get("state_reason") == "completed"]
    return not any(debt in l for l in (flight + done)[:every - 1])


def hours(sample):
    def t(s):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (t(sample["closed_at"]) - t(sample["started_at"])).total_seconds() / 3600


def span(q1, q3):
    if q3 >= 24:
        lo, hi = max(1, round(q1 / 24)), max(1, round(q3 / 24))
        return f"~{lo} days" if lo == hi else f"~{lo}–{hi} days"
    lo, hi = round(q1), round(q3)
    return f"~{lo}h" if lo == hi else f"~{lo}h–{hi}h"


def estimate(doc):
    by_size = {}
    for c in sorted((c for c in doc.get("closed") or [] if c.get("closed_at") and c.get("started_at")), key=lambda c: c["closed_at"]):
        size = str(c.get("size") or "").replace("size:", "")
        try:
            by_size.setdefault(size, []).append(hours(c))
        except ValueError:
            continue
    out = {}
    for o in doc.get("open") or []:
        size = str(o.get("size") or "").replace("size:", "")
        data = by_size.get(size, [])[-MAX_SAMPLES:]
        if len(data) >= MIN_SAMPLES:
            q = statistics.quantiles(data, n=4, method="inclusive")
            out[str(o["number"])] = span(q[0], q[2])
        elif size in DEFAULT_ESTIMATE:
            out[str(o["number"])] = DEFAULT_ESTIMATE[size]
    return out


def status_of(issue):
    return next((l for l in issue.get("labels") or [] if l.startswith("status:")), "")


def render(doc):
    issues = doc.get("issues") or []
    deps = doc.get("deps") or {}
    est = doc.get("estimates") or {}
    o = doc.get("order") or {}

    def line(i):
        n = i["number"]
        parts = [f"#{n} {i.get('title', '')}", STAGE.get(status_of(i).replace("status:", ""), status_of(i) or "No status")]
        if str(n) in est:
            parts.append(est[str(n)])
        waiting = (deps.get(str(n)) or {}).get("waiting_on") or []
        if waiting:
            parts.append("waiting on " + ", ".join(f"#{b}" for b in waiting))
        return "- " + " — ".join(parts)

    def has(i, label):
        return label in (i.get("labels") or [])

    ready = [i for i in issues if has(i, "status:ready")]
    ordered = order(ready, bool(o.get("debt_due")), int(o.get("debt_every") or 0), o.get("debt_label") or "type:debt")
    by_number = lambda items: sorted(items, key=lambda i: i["number"])

    waiting_on_you = by_number(i for i in issues if status_of(i) in WAITING or (has(i, "status:ready") and has(i, "mode:human")))
    shown = {i["number"] for i in waiting_on_you}
    in_progress = by_number(i for i in issues if status_of(i) in IN_PROGRESS and i["number"] not in shown)
    shown |= {i["number"] for i in in_progress}
    up_next = [i for i in ordered if i["number"] not in shown][:UP_NEXT]
    blocked = by_number(i for i in issues if has(i, "status:blocked") and i["number"] not in shown)

    out = []
    for title, items in (("Waiting on you", waiting_on_you), ("In progress", in_progress), ("Up next", up_next), ("Blocked", blocked)):
        out += [f"## {title}", ""]
        for i in items:
            out.append(line(i))
            if title == "Blocked":
                out += [f"  - {r}" for r in i.get("block_reasons") or []]
        if not items:
            out.append("_none_")
        out.append("")
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    po = sub.add_parser("order")
    po.add_argument("--debt-due", choices=("true", "false"), default="false")
    po.add_argument("--debt-every", type=int, default=0)
    po.add_argument("--debt-label", default="type:debt")
    pd = sub.add_parser("debt-due")
    pd.add_argument("--every", type=int, default=0)
    pd.add_argument("--debt-label", default="type:debt")
    sub.add_parser("estimate")
    sub.add_parser("render")
    args = p.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    doc = json.load(sys.stdin)
    if args.cmd == "order":
        print(json.dumps(order(doc, args.debt_due == "true", args.debt_every, args.debt_label), separators=(",", ":")))
    elif args.cmd == "debt-due":
        print("true" if debt_due(doc, args.every, args.debt_label) else "false")
    elif args.cmd == "estimate":
        print(json.dumps(estimate(doc)))
    else:
        print(render(doc))


if __name__ == "__main__":
    main()
