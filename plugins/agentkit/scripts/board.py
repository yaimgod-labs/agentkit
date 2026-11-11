#!/usr/bin/env python3
"""The kit's one task order, cycle-time estimates and markdown board. Python 3.8+, stdlib only.

The dispatcher (`.github/workflows/dispatch.yml`) and the `/board` command both call this, so what the
board calls "Up next" is exactly what the dispatcher takes next.

  board.py order --debt-due true|false [--debt-every N] [--debt-label L]
      stdin:  [{"number": 7, "author": "alice", "labels": ["priority:high"], "rank": 2 | null, "waiting_on": [4]}, ...]
      stdout: the same issues (every field kept), filtered and sorted, as JSON.
      Dropped: mode:human, size:m, size:l (people's work, and work that must be split first), and an issue whose
      optional `waiting_on` (its open blockers) is non-empty. /board sends `waiting_on`; the dispatcher does not,
      because it asks scripts/hold.sh about each candidate in this order instead.
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

  board.py debt-config <caller.yml>
      stdout: `<debt-every> <debt-label>` as the dispatcher gets them: the dispatch job's `with:` inputs in the
      project's caller (.github/workflows/agentkit.yml) when set there, else the defaults `4 type:debt`.
      A commented line, a missing file and a `${{ }}` expression all give the default.

  board.py estimate
      stdin:  {"closed": [{"size": "s", "started_at": ISO, "closed_at": ISO}, ...], "open": [{"number": 7, "size": "s"}, ...]}
      stdout: {"7": "~3h–6h" | "~2–4 days" | default, ...} as JSON.
      Per size, the last 20 closed issues (by closed_at) give cycle times in hours; with 5 or more, the estimate is
      their 25th–75th percentile ("~Q1h–Q3h", whole hours; "~X–Y days" once Q1 is 24 h or more, "~Xh–Y days" when only
      Q3 is; "1 day", not "1 days"). Fewer than 5 samples:
      xs "<1h", s "≤1 day", m "several days", l "an epic". An open issue with no size gets no entry.

  board.py render
      stdin:  {"issues": [{"number": 7, "title": "...", "labels": ["status:ready", ...], "rank": 2 | null,
                           "author": "alice", "block_reasons": ["reason", ...]}, ...],
               "deps": {"7": {"waiting_on": [4], "holds_up": [9]}},   # waiting_on = open blockers, by issue number
               "estimates": {"7": "~3h–6h"},                          # the output of `estimate`
               "order": {"debt_due": false, "debt_every": 0, "debt_label": "type:debt"},  # optional, as for `order`
               "warnings": ["..."]}                                    # optional, printed first as `> warning: ...`
      stdout: markdown, one section each for Waiting on you, In progress, Up next (top 5) and Blocked (with the
      issue's block_reasons), every line `- #n title — stage — estimate — waiting on #b — holds up #c, #d`. An issue
      is shown once, in the first section it fits. Up next is `order` over the ready issues with their waiting_on,
      so it is the dispatcher's pick order; after it come the ready issues `order` leaves out, as
      `- Held: #n title — waiting on #b` and `- Not taken: #n title — split first (size:m)` (mode:human ones are under
      Waiting on you). Issues in any other status (backlog, ...) are not shown.
"""
import argparse
import json
import re
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
    "changes-requested": "Changes requested", "approved": "Approved", "blocked": "Blocked", "needs-human": "Needs you",
    "refining": "Refining", "needs-info": "Needs info", "needs-verification": "Needs verification",
    "needs-approval": "Needs approval",
}
# what a status is called when a person reads it (/board, the Slack board and cards, the digest's headings); STAGE
# above is the board's own Stage option
SAYS = {
    "needs-info": "Needs your answer", "needs-approval": "Needs your approval", "needs-verification": "Needs your check",
    "needs-human": "Needs you", "blocked": "Blocked", "approved": "Approved", "backlog": "Backlog", "refining": "Being planned",
    "ready": "Up next", "in-progress": "Being built", "review": "In review", "changes-requested": "In review",
}


def sort_key(issue, due, every, debt):
    labels = issue.get("labels") or []
    rank = issue.get("rank")
    priority = 0 if "priority:high" in labels else 1 if "priority:medium" in labels else 2 if "priority:low" in labels else 3
    d = every > 0 and ((debt in labels) != due)
    return (rank is None, rank if rank is not None else 0, d, priority, issue["number"])


def not_taken(issue):
    """The label that keeps the dispatcher from ever taking this issue, or None."""
    return next((l for l in ("mode:human", "size:m", "size:l") if l in (issue.get("labels") or [])), None)


def order(issues, due=False, every=0, debt="type:debt"):
    kept = [i for i in issues if not not_taken(i) and not i.get("waiting_on")]
    return sorted(kept, key=lambda i: sort_key(i, due, every, debt))


DEBT_DEFAULTS = (4, "type:debt")


def debt_config(path):
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return DEBT_DEFAULTS
    every, label = DEBT_DEFAULTS
    job = None  # indent of the `dispatch:` job line while inside it
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if job is not None and indent <= job:
            job = None
        if job is None:
            if re.match(r"^\s*dispatch:\s*$", line):
                job = indent
            continue
        m = re.match(r"^\s*(debt-every|debt-label):\s*(.*?)\s*(#.*)?$", line)
        if not m or "${{" in m.group(2):
            continue
        value = m.group(2).strip("'\"")
        if m.group(1) == "debt-every" and value.isdigit():
            every = int(value)
        elif m.group(1) == "debt-label" and value:
            label = value
    return every, label


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
    def days(d):
        return f"{d} day" if d == 1 else f"{d} days"
    if q3 >= 24:
        hi = max(1, round(q3 / 24))
        if q1 < 24:
            return f"~{round(q1)}h–{days(hi)}"
        lo = max(1, round(q1 / 24))
        return f"~{days(lo)}" if lo == hi else f"~{lo}–{days(hi)}"
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

    def line(i, section=""):
        n = i["number"]
        says = SAYS.get(status_of(i).replace("status:", ""), status_of(i) or "No status")
        parts = [f"#{n} {i.get('title', '')}"] + ([says] if says != section else [])  # not what the heading says already
        if str(n) in est:
            parts.append(est[str(n)])
        if waiting(i):
            parts.append("waiting on " + refs(waiting(i)))
        holds = (deps.get(str(n)) or {}).get("holds_up") or []
        if holds:
            parts.append("holds up " + refs(holds))
        return "- " + " — ".join(parts)

    def waiting(i):
        return (deps.get(str(i["number"])) or {}).get("waiting_on") or []

    def refs(numbers):
        return ", ".join(f"#{b}" for b in numbers)

    def has(i, label):
        return label in (i.get("labels") or [])

    ready = [dict(i, waiting_on=waiting(i)) for i in issues if has(i, "status:ready")]
    ordered = order(ready, bool(o.get("debt_due")), int(o.get("debt_every") or 0), o.get("debt_label") or "type:debt")
    by_number = lambda items: sorted(items, key=lambda i: i["number"])

    waiting_on_you = by_number(i for i in issues if status_of(i) in WAITING or (has(i, "status:ready") and has(i, "mode:human")))
    shown = {i["number"] for i in waiting_on_you}
    in_progress = by_number(i for i in issues if status_of(i) in IN_PROGRESS and i["number"] not in shown)
    shown |= {i["number"] for i in in_progress}
    up_next = [i for i in ordered if i["number"] not in shown][:UP_NEXT]
    blocked = by_number(i for i in issues if has(i, "status:blocked") and i["number"] not in shown)
    left_out = [f"- Not taken: #{i['number']} {i.get('title', '')} — split first ({not_taken(i)})"
                for i in by_number(ready) if not_taken(i) in ("size:m", "size:l")]
    left_out = [f"- Held: #{i['number']} {i.get('title', '')} — waiting on {refs(i['waiting_on'])}"
                for i in by_number(ready) if not not_taken(i) and i["waiting_on"]] + left_out

    out = [f"> warning: {w}" for w in doc.get("warnings") or []]
    if out:
        out.append("")
    for title, items in (("Waiting on you", waiting_on_you), ("In progress", in_progress), ("Up next", up_next), ("Blocked", blocked)):
        out += [f"## {title}", ""]
        for i in items:
            out.append(line(i, title))
            if title == "Blocked":
                out += [f"  - {r}" for r in i.get("block_reasons") or []]
        if not items:
            out.append("_none_")
        if title == "Up next":
            out += left_out
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
    pc = sub.add_parser("debt-config")
    pc.add_argument("caller")
    sub.add_parser("estimate")
    sub.add_parser("render")
    args = p.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    if args.cmd == "debt-config":
        print("%d %s" % debt_config(args.caller))
        return
    sys.stdin.reconfigure(encoding="utf-8")
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
