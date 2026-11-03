"""plugins/agentkit/scripts/board.py: the shared task order, cycle-time estimates and the markdown board."""
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "plugins/agentkit/scripts/board.py"
fails = 0


def run(*args, stdin=None):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], input=json.dumps(stdin).encode(), capture_output=True)
    assert r.returncode == 0, r.stderr.decode()
    return r.stdout.decode("utf-8")


def order(issues, due="false", every="4", label="type:debt"):
    out = run("order", "--debt-due", due, "--debt-every", every, "--debt-label", label, stdin=issues)
    return [i["number"] for i in json.loads(out)]


def expect(name, cond, detail=""):
    global fails
    print(("ok: " if cond else "FAIL: ") + name + ("" if cond else f"\n{detail}"))
    fails += not cond


def issue(n, *labels, rank=None, author="alice", title=None):
    return {"number": n, "author": author, "labels": list(labels), "rank": rank, "title": title or f"task {n}"}


# test_order_matches_dispatch_today
issues = [issue(1), issue(2, "priority:low"), issue(3, "priority:high"), issue(4, "type:debt", "priority:high"),
          issue(5, "priority:medium"), issue(6, "mode:human", "priority:high"), issue(7, "size:m"), issue(8, "size:l")]
expect("order matches dispatch today (debt not due)", order(issues) == [3, 5, 2, 1, 4], order(issues))
expect("order: debt first when due", order(issues, due="true") == [4, 3, 5, 2, 1], order(issues, due="true"))
expect("order: debt-every 0 ranks debt like any issue", order(issues, every="0") == [3, 4, 5, 2, 1], order(issues, every="0"))
out = json.loads(run("order", "--debt-due", "false", "--debt-every", "4", "--debt-label", "type:debt", stdin=issues))
expect("order keeps number and author", all("number" in i and "author" in i for i in out))

# test_rank_beats_priority_and_debt
issues = [issue(1, "priority:high"), issue(2, "type:debt"), issue(3, "priority:low", rank=1), issue(4, "priority:low", rank=0.5)]
expect("rank beats priority and debt", order(issues, due="true") == [4, 3, 2, 1], order(issues, due="true"))

# test_order_without_rank: a null rank on every issue is today's sort; an explicit null and a missing key agree
issues = [issue(5, "priority:medium"), issue(2, "priority:low"), issue(9, "type:debt"), issue(3)]
bare = [{k: v for k, v in i.items() if k != "rank"} for i in issues]
expect("order without rank", order(issues) == [5, 2, 3, 9] and order(bare) == [5, 2, 3, 9], order(issues))

# equal ranks fall back to debt/priority/number
issues = [issue(7, "priority:low", rank=2), issue(8, "priority:high", rank=2), issue(6, rank=2)]
expect("equal ranks fall back to priority", order(issues) == [8, 7, 6], order(issues))


# test_debt_due_*: debt goes first when none of the last EVERY-1 issues taken into work was debt
def debt_due(open_, closed, every="4", label="type:debt"):
    return run("debt-due", "--every", every, "--debt-label", label, stdin={"open": open_, "closed": closed}).strip()


def done(*labels, at="2026-10-01T00:00:00Z", reason="completed"):
    return {"labels": list(labels), "closed_at": at, "state_reason": reason}


none_debt = [["status:in-progress"], ["status:review", "priority:high"]]
expect("debt due when none of the recent was debt",
       debt_due(none_debt, [done(), done("type:debt")]) == "true", debt_due(none_debt, [done(), done("type:debt")]))  # test_debt_due_none_recent_is_due
expect("debt not due when a recent one was debt (open)",
       debt_due([["status:in-progress", "type:debt"]], [done(), done()]) == "false")  # test_debt_due_recent_debt_not_due
expect("debt not due when a recent one was debt (closed)", debt_due([], [done(), done("type:debt"), done()]) == "false")
expect("only the first EVERY-1 count: an older debt is out of the window", debt_due([], [done(), done(), done(), done("type:debt")]) == "true")
expect("open issues fill the window before closed ones",
       debt_due([["status:approved"], ["status:needs-verification"], ["status:review"]], [done("type:debt")]) == "true"
       and debt_due([["status:approved"], ["status:needs-verification"]], [done("type:debt")]) == "false")
expect("open issues not in flight are ignored", debt_due([["status:ready", "type:debt"], ["status:blocked", "type:debt"]], []) == "true")
expect("closed as not planned is ignored", debt_due([], [done("type:debt", reason="not_planned")]) == "true")
expect("another debt label", debt_due([], [done("chore")], label="chore") == "false" and debt_due([], [done("chore")]) == "true")
expect("nothing taken into work yet is due", debt_due([], []) == "true")
expect("debt every 0 is never due",
       debt_due(none_debt, [done()], every="0") == "false" and debt_due([], [], every="0") == "false")  # test_debt_due_every_zero
expect("debt every 1 is always due (window is empty)", debt_due([["status:in-progress", "type:debt"]], [done("type:debt")], every="1") == "true")


# test_estimate_percentiles
def est(closed, open_):
    return json.loads(run("estimate", stdin={"closed": closed, "open": open_}))


def sample(size, hours):
    return {"size": size, "started_at": "2026-10-01T00:00:00Z", "closed_at": f"2026-10-{1 + hours // 24:02d}T{hours % 24:02d}:00:00Z"}


s8 = [sample("s", h) for h in range(1, 9)]
expect("estimate percentiles", est(s8, [{"number": 10, "size": "s"}]) == {"10": "~3h–6h"}, est(s8, [{"number": 10, "size": "s"}]))
expect("estimate falls back to defaults under 5 samples",
       est(s8[:2], [{"number": 10, "size": "s"}, {"number": 11, "size": "xs"}, {"number": 12, "size": "m"}, {"number": 13, "size": "l"}])
       == {"10": "≤1 day", "11": "<1h", "12": "several days", "13": "an epic"})
expect("estimate: sizes are separate samples", est(s8, [{"number": 1, "size": "xs"}]) == {"1": "<1h"})
days = [sample("m", h) for h in (48, 72, 72, 96, 120, 144)]  # 2..6 days, quartiles 72h..120h
expect("estimate in days from 24h up", est(days, [{"number": 1, "size": "m"}]) == {"1": "~3–5 days"}, est(days, [{"number": 1, "size": "m"}]))
# only the last 20 by closed_at count: 20 recent 10h samples outweigh 5 old 100h ones
old = [{"size": "s", "started_at": "2026-09-01T00:00:00Z", "closed_at": "2026-09-05T04:00:00Z"} for _ in range(5)]
new = [{"size": "s", "started_at": f"2026-10-{d:02d}T00:00:00Z", "closed_at": f"2026-10-{d:02d}T10:00:00Z"} for d in range(1, 21)]
expect("estimate uses the last 20 samples", est(old + new, [{"number": 1, "size": "s"}]) == {"1": "~10h"}, est(old + new, [{"number": 1, "size": "s"}]))

# test_board_waiting_on_includes_open_blockers
board = {"issues": [dict(issue(3, "status:in-progress"), block_reasons=[])], "deps": {"3": {"waiting_on": [4], "holds_up": []}}, "estimates": {}}
md = run("render", stdin=board)
expect("board shows waiting on an open blocker even when in progress", "waiting on #4" in md and "#3 task 3" in md, md)

# test_render_sections_and_top5
ready = [issue(n, "status:ready", rank=r) for n, r in [(11, None), (12, 3), (13, 1), (14, None), (15, 2), (16, None), (17, None)]]
board = {"issues": ready + [
    issue(20, "status:needs-info"), issue(21, "status:ready", "mode:human"), issue(22, "status:needs-approval"),
    issue(23, "status:needs-human"), issue(24, "status:needs-verification"),
    issue(30, "status:in-progress"), issue(31, "status:review"), issue(32, "status:changes-requested"),
    issue(33, "status:approved"), issue(34, "status:refining"),
    dict(issue(40, "status:blocked"), block_reasons=["waiting on legal", "needs a key"]),
], "deps": {}, "estimates": {"13": "~2h–4h"}}
md = run("render", stdin=board)
sec = {}
cur = None
for line in md.splitlines():
    if line.startswith("## "):
        cur = line[3:].strip()
        sec[cur] = []
    elif cur and line.strip():
        sec[cur].append(line)
nums = lambda name: [int(l.split("#")[1].split()[0]) for l in sec[name] if l.startswith("- #")]
expect("sections in order", list(sec) == ["Waiting on you", "In progress", "Up next", "Blocked"], list(sec))
expect("up next is the top 5 in order", nums("Up next") == [13, 15, 12, 11, 14], md)
expect("waiting on you statuses", sorted(nums("Waiting on you")) == [20, 21, 22, 23, 24], md)
expect("in progress statuses", sorted(nums("In progress")) == [30, 31, 32, 33, 34], md)
expect("blocked lists reasons", nums("Blocked") == [40] and any("waiting on legal" in l for l in sec["Blocked"])
       and any("needs a key" in l for l in sec["Blocked"]), md)
expect("line has stage and estimate", any(l.startswith("- #13 task 13 — Ready — ~2h–4h") for l in sec["Up next"]), md)

# an empty board still renders every section
md = run("render", stdin={"issues": [], "deps": {}, "estimates": {}})
expect("empty board renders", all(h in md for h in ("## Waiting on you", "## In progress", "## Up next", "## Blocked")), md)

# test_order_drops_held: an issue with open blockers (`waiting_on`, sent by /board) is not taken; none sent is today's order
issues = [issue(1), dict(issue(2, "priority:high"), waiting_on=[9]), dict(issue(3), waiting_on=[])]
expect("order drops issues waiting on an open blocker", order(issues) == [1, 3], order(issues))


def sections(md):
    sec, cur = {}, None
    for line in md.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            sec[cur] = []
        elif cur and line.strip():
            sec[cur].append(line)
    return sec


# test_render_up_next_matches_dispatch: held and not-taken ready issues are listed apart, after the top 5
board = {"issues": [issue(n, "status:ready") for n in (1, 2, 3, 4, 5, 6, 7)] + [
    issue(8, "status:ready", "size:m"), issue(9, "status:ready", "size:l", "priority:high"), issue(10, "status:ready", "mode:human", "size:m")],
    "deps": {"1": {"waiting_on": [40, 41], "holds_up": []}, "2": {"waiting_on": [], "holds_up": [3]}}, "estimates": {}}
md = run("render", stdin=board)
up = sections(md)["Up next"]
expect("up next skips the held issue", [l for l in up if l.startswith("- #")][:5] == [
    "- #2 task 2 — Ready — holds up #3", "- #3 task 3 — Ready", "- #4 task 4 — Ready", "- #5 task 5 — Ready", "- #6 task 6 — Ready"], md)
expect("held issue listed with its blockers", "- Held: #1 task 1 — waiting on #40, #41" in up, md)
expect("not taken: size m and l, split first", "- Not taken: #8 task 8 — split first (size:m)" in up
       and "- Not taken: #9 task 9 — split first (size:l)" in up, md)
expect("mode:human is under Waiting on you, not Not taken", "#10" not in "\n".join(up) and any("#10 " in l for l in sections(md)["Waiting on you"]), md)

# test_render_holds_up
board = {"issues": [issue(4, "status:in-progress")], "deps": {"4": {"waiting_on": [], "holds_up": [7, 9]}}, "estimates": {}}
md = run("render", stdin=board)
expect("holds up its dependents", "- #4 task 4 — In progress — holds up #7, #9" in md, md)

# render warnings go first, one line each
md = run("render", stdin={"issues": [], "deps": {}, "estimates": {}, "warnings": ["could not read ranks"]})
expect("warning line first", md.splitlines()[0] == "> warning: could not read ranks", md)

# test_span_wording: one day is "day"; hours below a day and days above it are mixed
day1 = [sample("s", h) for h in (20, 22, 24, 26, 28)]          # quartiles 22h..26h -> 1 day hi, hours lo
expect("Q1 under a day, Q3 over: hours to days", est(day1, [{"number": 1, "size": "s"}]) == {"1": "~22h–1 day"}, est(day1, [{"number": 1, "size": "s"}]))
one = [sample("s", h) for h in (24, 24, 25, 26, 26)]
expect("one day says day", est(one, [{"number": 1, "size": "s"}]) == {"1": "~1 day"}, est(one, [{"number": 1, "size": "s"}]))
mix = [sample("m", h) for h in (5, 10, 40, 60, 70)]           # quartiles 10h..60h
expect("hours to days", est(mix, [{"number": 1, "size": "m"}]) == {"1": "~10h–2 days"}, est(mix, [{"number": 1, "size": "m"}]))


# test_debt_config: the dispatch job's `with:` in the caller, else the defaults
def debt_config(text):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "agentkit.yml"
        if text is not None:
            f.write_text(text)
        r = subprocess.run([sys.executable, str(SCRIPT), "debt-config", str(f)], capture_output=True)
        assert r.returncode == 0, r.stderr.decode()
        return r.stdout.decode().strip()


caller = """jobs:
  dispatch:
    uses: o/agentkit/.github/workflows/dispatch.yml@v1
    with:
      wip: 2
      {every}
      {label}
    secrets:
      X: y
  review:
    with:
      debt-every: 9
"""
expect("debt config: commented lines are defaults",
       debt_config(caller.format(every="# debt-every: 2", label="# debt-label: chore")) == "4 type:debt")
expect("debt config: set values win", debt_config(caller.format(every="debt-every: 0", label='debt-label: "type: cleanup"')) == "0 type: cleanup",
       debt_config(caller.format(every="debt-every: 0", label='debt-label: "type: cleanup"')))
expect("debt config: another job's inputs are ignored", debt_config(caller.format(every="", label="")) == "4 type:debt")
expect("debt config: an expression falls back to the default",
       debt_config(caller.format(every="debt-every: ${{ fromJSON(vars.X) }}", label="")) == "4 type:debt")
expect("debt config: no caller file is the defaults", debt_config(None) == "4 type:debt")

sys.exit(1 if fails else 0)
