"""bot/core.py and scripts/card.py: trust mapping, button values, the dispatch body, the card and its length lint,
the App Home board, the Add task dispatch and the nudge rules."""
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot")); sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "plugins/agentkit/scripts"))
import core, card  # noqa: E402

fails = 0
def expect(name, cond, detail=""):
    global fails
    print(("ok: " if cond else "FAIL: ") + name + ("" if cond else f" {detail}"))
    fails += not cond

users = {"U1": "alice", "U2": "bob"}
perm = {"alice": "write", "bob": "read"}.get
expect("mapped writer is allowed", core.authorize("U1", users, perm) == ("alice", None))
expect("unmapped user refused", core.authorize("U9", users, perm)[0] is None)
expect("reader refused", core.authorize("U2", users, perm)[0] is None)
expect("lost access refused", core.authorize("U1", users, lambda l: None)[0] is None)
expect("button value round trip", core.parse_value("o/r#12|approve") == ("o/r", 12, "approve"))
expect("text may hold |", core.parse_value("o/r#1|a|b")[2] == "a|b")
for bad in ["o/r#0|x", "o/r#x|x", "../r#1|x", "o/..#1|x", "nohash|x"]:
    try: core.parse_value(bad); expect("bad value rejected: " + bad, False)
    except ValueError: expect("bad value rejected: " + bad, True)
body = core.dispatch("o/r", 3, "yes", "alice")[1]
expect("dispatch body", body == {"event_type": "agentkit-slack-reply", "client_payload": {"issue": 3, "text": "yes", "login": "alice"}})
with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
    json.dump({"U1": "a b"}, f); f.flush()
    try: core.load_users(f.name); expect("bad login in users.json rejected", False)
    except ValueError: expect("bad login in users.json rejected", True)

issue = {"repo": "o/r", "number": 7, "title": "Research: which rounding rule", "ask": "Allow web access?",
         "labels": ["status:needs-approval", "type:research"], "options": ["Allow web", "Use memory"]}
c = card.build(issue)
els = c["blocks"][1]["elements"]
labels = [e["text"]["text"] for e in els]
expect("options first, then keywords, then Other", labels == ["Allow web", "Use memory", "Approve", "Other…"], labels)
expect("approve is a direct reply, Block would be a modal", els[2]["value"] == "o/r#7|approve" and els[2]["action_id"].startswith("reply"))
expect("card within budget", card.lint(c) == [], card.lint(c))
long = card.build({**issue, "title": "t" * 200, "ask": "a" * 500})
expect("long title and ask are clipped to budget", card.lint(long) == [])
many = card.build({**issue, "options": list("abcdef")})
expect("at most 3 answer buttons", len([e for e in many["blocks"][1]["elements"] if e["text"]["text"] != "Other…"]) == 3)
nokw = card.build({"repo": "o/r", "number": 7, "title": "t", "labels": ["status:needs-info"]})
expect("needs-info: Research… and Block… open modals", [e["action_id"].split("_")[0] for e in nokw["blocks"][1]["elements"]][:2] == ["modal", "modal"])
expect("no ask falls back", "Needs your input" in nokw["text"])
nkw = [(e["text"]["text"], e["value"], e["action_id"].split("_")[0]) for e in nokw["blocks"][1]["elements"]]
expect("needs-info: Close… comes last of the keywords, a modal", nkw[2:] == [("Close…", "o/r#7|close", "modal"), ("Other…", "o/r#7|", "modal")], nkw)
withopts = card.build({"repo": "o/r", "number": 7, "title": "t", "labels": ["status:needs-info"], "options": ["A", "B"]})
expect("options come before keywords; Close… is cut first", [e["text"]["text"] for e in withopts["blocks"][1]["elements"]] == ["A", "B", "Research…", "Other…"])
bad = dict(c); bad["blocks"] = [{"type": "section", "text": {"type": "mrkdwn", "text": "*" + "t" * 90 + "*\n" + "a" * 200 + "\n<http://a|1> <http://b|2>"}}, c["blocks"][1]]
expect("lint flags title, ask and two links", len(card.lint(bad)) == 3, card.lint(bad))

stuck = "**Stuck on:** which `library`?\n**Why I can't decide alone:** w\n**Checked:** c\n**Options:** Allow web | Use memory\n\nReply with an answer"
expect("derive: stuck message gives ask and options", card.derive(["x", stuck]) == ("which library?", ["Allow web", "Use memory"]))
expect("derive: recommendation gives its first line", card.derive(["<!-- agentkit:recommendation -->\n> Adopt **option A**: one file per module.\n>\n> Reasons"]) == ("Adopt option A: one file per module.", []))
expect("derive: any other comment gives its first line", card.derive(["<!-- m -->\nagentkit: all checks passed; 1 item needs a person."]) == ("agentkit: all checks passed; 1 item needs a person.", []))
expect("derive: a recommendation line ending in : takes the next line", card.derive(["<!-- agentkit:recommendation -->\n> Adopt **C**:\n>\n> 1. Keep each constant in its module.\n> 2. More"]) == ("Adopt C: 1. Keep each constant in its module.", []))
refine = "## Plan\n- do x\n\n## Questions\n1. Should `negate` throw for non-numbers? — default if unanswered: no check.\n2. Other?\n\nReply with an answer"
expect("derive: refine questions give the first question", card.derive([refine]) == ("Should negate throw for non-numbers?", [("Use the default", "Use the default: no check.")]), card.derive([refine]))
stuck_q = ("## Questions\n1. **Stuck on:** The greeting format. **Why:** a product choice. **Checked:** docs. "
           "Default if unanswered: `greet(name)` returns `Hello, ${name}!`.\n\nReply with an answer")
expect("derive: refine's Stuck on question, its default a one-click answer", card.derive([stuck_q]) ==
       ("The greeting format.", [("Use the default", "Use the default: greet(name) returns Hello, ${name}!.")]), card.derive([stuck_q]))
expect("derive: a question without a default has no options", card.derive(["## Questions\n1. Which colour?\n"]) == ("Which colour?", []))
c = card.build({"repo": "o/r", "number": 9, "title": "t", "labels": ["status:needs-info"], "comments": [stuck_q]})
expect("build: a (label, text) option is a labelled button that sends its text",
       (c["blocks"][1]["elements"][0]["text"]["text"], c["blocks"][1]["elements"][0]["value"]) ==
       ("Use the default", "o/r#9|Use the default: greet(name) returns Hello, ${name}!."), c["blocks"][1]["elements"][0])
expect("derive: nothing gives nothing", card.derive([]) == (None, []))
c2 = card.build({"repo": "o/r", "number": 7, "title": "t", "labels": ["status:needs-human"], "comments": [stuck]})
expect("build uses derived ask and options", "which library?" in c2["text"] and [e["text"]["text"] for e in c2["blocks"][1]["elements"]][:2] == ["Allow web", "Use memory"])

# Verify: needs-verification asks for the unticked items of the kit's latest comment; Verified and Failed… (free text)
ping = ("agentkit: all checks passed; 2 item(s) under **Human verification** in the PR need a person to check them. "
        "Reply `verified` when they pass, or say what failed. PR: https://github.com/o/r/pull/12\n\n**Not verified yet:**\n"
        "- [ ] Open the app on `iOS 17`\n- [ ] Log in with a **new** account\n- [x] already ticked\n\nAnswer with the Comment button")
NVL = ["status:needs-verification", "action:required"]
v = card.build({"repo": "o/r", "number": 7, "title": "t", "labels": NVL, "comments": ["<!-- agentkit:card channel=C1 ts=1.2 -->", ping]})
vb = [(e["text"]["text"], e["value"], e["action_id"].split("_")[0]) for e in v["blocks"][1]["elements"]]
expect("verify: ask is the unticked items, one line", v["blocks"][0]["text"]["text"].split("\n")[1] == "Open the app on iOS 17 · Log in with a new account", v["blocks"][0]["text"]["text"])
expect("verify: Verified and Failed…", vb == [("Verified", "o/r#7|verified", "reply"), ("Failed…", "o/r#7|", "modal")], vb)
expect("verify: within budget", card.lint(v) == [], card.lint(v))
many_items = ping.replace("- [x] already ticked", "\n".join(f"- [ ] check number {i} of the many things to look at" for i in range(6)))
vm = card.build({"repo": "o/r", "number": 7, "title": "t", "labels": NVL, "comments": [many_items]})
vm_ask = vm["blocks"][0]["text"]["text"].split("\n")[1]
expect("verify: at most 3 items, clipped to the ask budget", vm_ask.count(" · ") <= 2 and len(vm_ask) <= card.ASK_MAX and card.lint(vm) == [], vm_ask)
v_old = card.build({"repo": "o/r", "number": 7, "title": "t", "labels": NVL, "comments": ["- [ ] an old item", "agentkit: all checks passed; check them."]})
expect("verify: a latest comment without items gives its first line", "agentkit: all checks passed; check them." in v_old["text"], v_old["text"])
expect("lint: a free-text modal is not an answer button", card.lint({"blocks": [v["blocks"][0], {"type": "actions", "elements": [
    {"text": {"text": x}, "value": "o/r#7|" + y} for x, y in [("A", "a"), ("B", "b"), ("C", "c"), ("Failed…", "")]]}]}) == [])

# Attention: needs-human after a failed run (reason:env, reason:agent-error): one line of why, Retry, Block…, Logs
failed = ("agentkit: implement run failed or timed out (https://github.com/o/r/actions/runs/123). Needs a human.\n\n"
          "Answer with the Comment button on this issue's card in Slack.")
a = card.build({"repo": "o/r", "number": 7, "title": "t", "labels": ["status:needs-human", "reason:agent-error", "action:required"],
                "comments": [failed, "<!-- agentkit:card channel=C1 ts=1.2 -->"]})
ab = a["blocks"][1]["elements"]
expect("attention: the why without the link", a["blocks"][0]["text"]["text"].split("\n")[1] == "agentkit: implement run failed or timed out. Needs a human.", a["blocks"][0]["text"]["text"])
expect("attention: Retry, Block…, Logs; no Other…", [e["text"]["text"] for e in ab] == ["Retry", "Block…", "Logs"], ab)
expect("attention: Retry replies, Block… opens a modal", (ab[0]["value"], ab[1]["value"], ab[1]["action_id"].split("_")[0]) == ("o/r#7|retry", "o/r#7|block", "modal"), ab)
expect("attention: Logs links the run and has no value", ab[2].get("url") == "https://github.com/o/r/actions/runs/123" and "value" not in ab[2], ab[2])
expect("attention: within budget", card.lint(a) == [], card.lint(a))
timeout = ("agentkit: checks lint gave no result after 30 minutes. A person must check that they run for this branch and re-run them. "
           "Reply `retry` to send it back to the implementer. PR: https://github.com/o/r/pull/12\n\nAnswer with the Comment button")
a2 = card.build({"repo": "o/r", "number": 7, "title": "t", "labels": ["status:needs-human", "reason:env"], "comments": [timeout]})
expect("attention: no run link, Logs is the issue", a2["blocks"][1]["elements"][-1]["url"] == "https://github.com/o/r/issues/7", a2["blocks"][1]["elements"][-1])
expect("attention: no PR link in the ask", "http" not in a2["blocks"][0]["text"]["text"].split("\n")[1] and card.lint(a2) == [], a2["blocks"][0]["text"]["text"])
nr = card.build({"repo": "o/r", "number": 7, "title": "t", "labels": ["status:needs-human"], "comments": [failed]})
expect("needs-human without a failure reason stays a Decide card", [e["text"]["text"] for e in nr["blocks"][1]["elements"]] == ["Retry", "Research…", "Block…", "Other…"], nr)
url_btn = {"type": "button", "text": {"text": "Logs"}, "url": "https://x"}
three = [{"text": {"text": x}, "value": "o/r#7|" + x} for x in "abc"]
expect("lint: a link button is not an answer button", card.lint({"blocks": [a["blocks"][0], {"type": "actions", "elements": three + [url_btn]}]}) == [])
expect("lint: 4 answers and a link button is over", len(card.lint({"blocks": [a["blocks"][0], {"type": "actions", "elements": three + three[:1] + [url_btn]}]})) == 1)

d = card.done({"number": 96, "title": "RFC: where to put shared constants", "url": "https://github.com/o/r/pull/97",
               "body": "## Summary\nI added RFC 0002, `docs/rfcs/0002-shared-constants.md`, in proposed status. It compares four ways.\n\n## Changes\n- x"})
expect("done card: title, first Summary line, link, no buttons", len(d["blocks"]) == 1 and "✓ RFC: where" in d["text"] and "I added RFC 0002" in d["text"] and "pull/97|#96" in d["blocks"][0]["text"]["text"], d)
expect("done card within budget", card.lint(d) == [], card.lint(d))
expect("done card without a Summary says Merged.", "Merged." in card.done({"number": 1, "title": "t", "url": "u", "body": None})["text"])

# resolve: every marked card is edited to the outcome, without buttons
sent, real_slack = [], card.slack
card.slack = lambda method, payload: sent.append((method, payload)) or {"ok": True}
res_issue = {"repo": "o/r", "number": 5, "title": "t", "state": "OPEN", "labels": ["status:changes-requested"],
             "comments": ["<!-- agentkit:card channel=C1 ts=1.2 -->", "other", "<!-- agentkit:card channel=C1 ts=3.4 -->x"]}
expect("resolve edits only exact marker comments", card.resolve(res_issue) == 1 and sent[0][0] == "chat.update" and sent[0][1]["ts"] == "1.2")
expect("resolved card has no buttons and says the new status", len(sent[0][1]["blocks"]) == 1 and "now changes-requested" in sent[0][1]["text"])
expect("closed as completed reads Closed as done", card.outcome({"state": "CLOSED", "stateReason": "COMPLETED"}) == "Closed as done")
card.slack = real_slack

# chief of staff, no re-asking: a person's say after the kit's latest ask means the reply job has it
K = lambda i, b: {"id": i, "body": b}
own = "<!-- agentkit:card channel=C1 ts=1.2 -->"
rec = "<!-- agentkit:slack-reply login=alice nonce=" + "0" * 32 + " sig=" + "0" * 64 + " -->\n\n**Slack reply by @alice:**\n\nuse A"
expect("answered: a person after the kit's latest ask", card.answered([K(1, "Which?"), K(2, own)], [K(3, "use A")]))
expect("answered: a person before the latest ask is not an answer", not card.answered([K(1, "old ask"), K(5, "new ask")], [K(3, "x")]))
expect("answered: a / command is not an answer (the reply job skips it)", not card.answered([K(1, "ask")], [K(3, "/plan")]))
expect("answered: a Slack reply record is the person's, not the kit's ask", card.answered([K(1, "ask"), K(4, rec)], [K(4, "use A")]))
expect("answered: no ask from the kit, nothing to answer", not card.answered([K(2, own)], [K(3, "x")]))

# chief of staff, dedup: the card an issue's latest wait is on
fold_m = "<!-- agentkit:card channel=C1 ts=1.2 of=4 -->"
expect("current: own card", card.current(["ask", own]) == ("C1", "1.2", None))
expect("current: folded into #4's card", card.current(["ask", fold_m]) == ("C1", "1.2", 4))
expect("current: a later ask has no card yet", card.current(["ask", own, "new ask"]) is None)
expect("current: a Slack reply record is not a new ask", card.current(["ask", own, rec]) == ("C1", "1.2", None))
expect("current: only an exact marker", card.current(["ask", own + "x"]) is None)
EPIC, B2 = "https://github.com/o/r/issues/1", "https://github.com/o/r/issues/2"
P = {"number": 4, "title": "Pick a format", "labels": ["status:needs-info", "action:required"], "comments": [stuck, own],
     "parent": EPIC, "blockers": []}
f = card.fold_into({"repo": "o/r", "number": 9, "parent": EPIC, "blockers": [], "waiting": [P]})
expect("fold: same parent epic folds into its card", f and (f["channel"], f["ts"], f["of"]) == ("C1", "1.2", 4), f)
expect("fold: the marker on #9 points at #4's card", f["marker"] == "<!-- agentkit:card channel=C1 ts=1.2 of=4 -->", f)
orig = card.build({**P, "repo": "o/r"})
expect("fold: the card keeps its buttons and ask", f["card"]["blocks"][1] == orig["blocks"][1] and
       f["card"]["blocks"][0]["text"]["text"].startswith(orig["blocks"][0]["text"]["text"]), f["card"])
expect("fold: adds Also affects #9, within budget", f["card"]["blocks"][0]["text"]["text"].endswith("\nAlso affects #9") and card.lint(f["card"]) == [])
expect("fold: a marker is not built into the card", card.MARKER.match(f["marker"]) is None)
shared = card.fold_into({"repo": "o/r", "number": 9, "parent": None, "blockers": [B2], "waiting": [{**P, "parent": None, "blockers": [B2, EPIC]}]})
expect("fold: a shared blocker folds", shared and shared["of"] == 4, shared)
for name, mine, theirs in [("different parents", EPIC, {"parent": B2}), ("no parent on either", None, {"parent": None}),
                           ("own card replaced by a later ask", EPIC, {"comments": [stuck, own, "a newer ask"]}),
                           ("a folded issue is not a card to fold into", EPIC, {"comments": [stuck, fold_m]})]:
    expect("fold: none when " + name, card.fold_into({"repo": "o/r", "number": 9, "parent": mine, "blockers": [], "waiting": [{**P, **theirs}]}) is None)
Q = {"number": 7, "title": "q", "labels": [], "comments": ["ask", fold_m], "parent": None, "blockers": []}
older = {**P, "number": 3, "comments": ["ask", "<!-- agentkit:card channel=C1 ts=0.5 -->"]}
f2 = card.fold_into({"repo": "o/r", "number": 9, "parent": EPIC, "blockers": [], "waiting": [P, Q, older]})
expect("fold: the oldest card wins", f2["of"] == 3 and f2["ts"] == "0.5", f2)
f3 = card.fold_into({"repo": "o/r", "number": 9, "parent": EPIC, "blockers": [], "waiting": [P, Q]})
expect("fold: lists every waiting issue already folded in", f3["card"]["blocks"][0]["text"]["text"].endswith("\nAlso affects #7, #9"), f3)
many_q = [{**Q, "number": 100 + i} for i in range(40)]
f4 = card.fold_into({"repo": "o/r", "number": 9, "parent": EPIC, "blockers": [], "waiting": [P] + many_q})
expect("fold: a long Also line is clipped", len(f4["card"]["blocks"][0]["text"]["text"].split("\n")[3]) <= card.TITLE_MAX and card.lint(f4["card"]) == [])
f5 = card.fold_into({"repo": "o/r", "number": 9, "parent": EPIC, "blockers": [], "waiting": [{**P, "comments": [stuck, own, rec]}]})
expect("fold: the card is rebuilt from what it was posted from", f5["card"]["blocks"][0] == f["card"]["blocks"][0], f5)
expect("orphans: waiting issues folded into the resolved issue's cards",
       card.orphans({"comments": [stuck, own], "waiting": [Q, {**Q, "number": 8, "comments": ["ask", fold_m.replace("1.2", "9.9")]}, P]}) == [7])

# App Home: the board
def iss(n, *labels, title=None):
    return {"number": n, "title": title or f"task {n}", "labels": list(labels)}

def texts(view):
    out = []
    for b in view["blocks"]:
        if b["type"] == "section":
            out.append(b["text"]["text"])
        elif b["type"] == "context":
            out += [e["text"] for e in b["elements"]]
    return out

cards = lambda i: card.build({**i, "repo": "o/r"})["blocks"]
board = {"repo": "o/r", "since": "2026-11-02",
         "waiting": [iss(3, "status:needs-info", "action:required")],
         "in_progress": [iss(4, "status:in-progress"), iss(5, "status:review")],
         "next": [iss(6, "status:ready")], "done": [iss(1, title="shipped <it> & more")]}
v = core.home_view([board], cards)
t = texts(v)
expect("home: a home view", v["type"] == "home")
expect("home: the four sections in order", [s.split("*")[1] for s in t if s.startswith("*") and "(" in s] ==
       ["Waiting on you", "In progress", "Next up", "Done this week"], t)
acts = [b for b in v["blocks"] if b["type"] == "actions"]
expect("home: a waiting item has its card's buttons", len(acts) == 1 and acts[0]["elements"][0]["value"].startswith("o/r#3|"), acts)
expect("home: in progress names the stage", any("#5>" in s and "review" in s for s in t), t)
expect("home: titles are escaped", any("shipped &lt;it&gt; &amp; more" in s for s in t), t)
addb = [b["accessory"] for b in v["blocks"] if b.get("accessory")]
expect("home: a Settings button on top", addb[0]["action_id"] == "settings_ask", addb)
addb = [a for a in addb if a["action_id"] == "add_task"]
expect("home: + Add task button per repo", addb and addb[0]["value"] == "o/r", addb)
expect("home: within Slack's 100 blocks", len(v["blocks"]) <= 100)

big = {"repo": "o/r", "since": "2026-11-02", "waiting": [iss(n, "status:needs-info") for n in range(1, 41)],
       "in_progress": [iss(n, "status:review") for n in range(41, 81)], "next": [iss(n, "status:ready") for n in range(81, 121)],
       "done": [iss(n) for n in range(121, 161)]}
built = []
v = core.home_view([big, {**big, "repo": "o/s"}, {**big, "repo": "o/t"}], lambda i: built.append(i["number"]) or cards(i))
t = texts(v)
expect("home: a big board stays within 100 blocks", len(v["blocks"]) <= 100, len(v["blocks"]))
expect("home: capped sections say how many more, with a link", any("and " in s and " more" in s and "issues?q=" in s for s in t), t)
expect("home: only shown waiting items are built", len(built) == len([b for b in v["blocks"] if b["type"] == "actions"]), built)
more = core.more_url("o/r", "waiting")
expect("home: the more link searches the label", more.startswith("https://github.com/o/r/issues?q=") and "action%3Arequired" in more, more)
expect("home: done this week searches closed as completed since", "closed%3A%3E%3D2026-11-02" in core.more_url("o/r", "done", "2026-11-02"))

v = core.home_view([board], cards, sent={"o/r#3": "approve"})
expect("home: a sent item shows what was sent instead of buttons",
       not [b for b in v["blocks"] if b["type"] == "actions"] and any("Sent: approve" in s for s in texts(v)), texts(v))
v = core.home_view([board], cards, notice="Filed.")
expect("home: a notice comes first", texts(v)[0] == "Filed.", texts(v))
v = core.home_view([{"repo": "o/r", "error": "could not read o/r (HTTP 403)"}], cards)
expect("home: a repo that could not be read says so", any("could not read o/r" in s for s in texts(v)), texts(v))
v = core.home_view([], cards)
expect("home: no repos with write access says so", "write access" in texts(v)[0], texts(v))
v = core.unmapped_view("U123")
expect("home: an unmapped user gets one line on how to get mapped",
       len(v["blocks"]) == 1 and "U123" in texts(v)[0] and "users.json" in texts(v)[0], v)

nxt = core.next_up([iss(9), iss(8, "priority:high"), iss(7, "size:m"), iss(6)])
expect("next up: the dispatcher's order, then what it does not take", [i["number"] for i in nxt] == [8, 6, 9, 7], nxt)
expect("next up: an issue it does not take says why", nxt[-1].get("note") == "not taken: size:m", nxt[-1])

# Add task
body = core.task("o/r", " Fix the thing ", "details", "alice")[1]
expect("task: dispatch body", body == {"event_type": "agentkit-slack-task",
                                       "client_payload": {"title": "Fix the thing", "body": "details", "login": "alice"}}, body)
expect("task: a title is needed", "title" in core.task_errors("  ", ""))
expect("task: a long title is refused", "title" in core.task_errors("t" * 257, ""))
expect("task: a title is one line", "title" in core.task_errors("a\nb", ""))
expect("task: a long body is refused", "body" in core.task_errors("t", "b" * 3001))
expect("task: a good one passes", core.task_errors("t", "b") == {})

# Settings: asking, and a click on an answer's button
import settings  # noqa: E402
expect("settings: a project setting needs admin, not write",
       core.authorize("U1", users, perm, core.ADMIN)[0] is None and "admin" in core.authorize("U1", users, perm, core.ADMIN)[1])
expect("settings: an admin may", core.authorize("U1", users, {"alice": "admin"}.get, core.ADMIN) == ("alice", None))
expect("settings: a question is needed", core.ask_error("  ") and core.ask_error("x" * 501) and core.ask_error("hours?") is None)
body = core.settings_ask("o/r", " can I change the hours? ", "alice", "U1")[1]
expect("settings: ask body", body == {"event_type": "agentkit-slack-settings", "client_payload": {
    "question": "can I change the hours?", "login": "alice", "slack_user": "U1"}}, body)
body = core.settings_ask("o/r", "Tasks in flight", "alice", "U1", ("D1", "1.2"), {"nudge": "off"}, "wip")[1]
expect("settings: ask body with the placeholder, the bot's values and a picked key", body["client_payload"] == {
    "question": "Tasks in flight", "login": "alice", "slack_user": "U1", "slack_channel": "D1", "slack_ts": "1.2",
    "now": {"nudge": "off"}, "key": "wip"} and len(body["client_payload"]) <= 10, body)  # GitHub's cap: 10 keys
expect("settings: a pick round trip", core.parse_pick("pick|o/r|wip") == ("o/r", "wip"))
for bad in ["pick|../r|wip", "pick|o/r|Bad Key", "pick|o/r|wip|x", "set|o/r|wip", "pick|o/r"]:
    try: core.parse_pick(bad); expect("settings: bad pick rejected: " + bad, False)
    except ValueError: expect("settings: bad pick rejected: " + bad, True)
menu = [e for b in settings.card(settings.load(), "o/r", "list?", '{"match": "list"}')["blocks"]
        if b["type"] == "actions" for e in b["elements"]][0]
expect("settings: every menu value parses", all(core.parse_pick(o["value"])[0] == "o/r"
                                              for g in menu["option_groups"] for o in g["options"]), menu)
# answered without the model, the repo a question names, Apply all
reg, served = settings.load(), ["o/sandbox", "o/shop"]
for q, want in [("what can you change?", "list"), ("what are all the setting you can change", "list"),
                ("what changes to setting can you do", "list"), ("change my nudge hours", "nudge-hours"),
                ("Repos the Slack bot serves", "bot-repos"), ("Tasks in flight on shop", "wip"), ("set retro time", "retro-cron"),
                ("nudge hours to 08-18", None), ("retro time and project timezone", None), ("change the timezone to israel", None),
                ("why is the sky blue", None)]:
    expect(f"quick: {q!r} -> {want}", core.quick(q, reg, served) == want, core.quick(q, reg, served))
for q, want in [("tasks in flight on shop", "o/shop"), ("on o/sandbox please", "o/sandbox"),
                ("shop or sandbox?", None), ("the shops", None), ("nudge hours", None)]:
    expect(f"named repo: {q!r} -> {want}", core.named_repo(q, served) == want, core.named_repo(q, served))
v = settings.apply_all_value("o/r", [("timezone", "Asia/Jerusalem"), ("auto-merge", True)])
expect("apply all: round trip", core.parse_all(v) == ("o/r", [("timezone", "Asia/Jerusalem"), ("auto-merge", "true")]), v)
for bad in ["all|o/r|[]", "all|../r|[[\"wip\",\"3\"]]", "all|o/r|[[\"Bad\",\"3\"]]", "all|o/r|not json",
            "all|o/r|" + json.dumps([["wip", "3"]] * 6), "set|o/r|[[\"wip\",\"3\"]]", "all|o/r|[[\"wip\",3]]"]:
    try: core.parse_all(bad); expect("apply all: bad value rejected: " + bad, False)
    except ValueError: expect("apply all: bad value rejected: " + bad, True)
body = core.settings_changes("o/r", [("wip", "3"), ("retro-cron", "0 10 * * 4")], "alice", "U1")[1]
expect("apply all: one setting event with the changes", body == {"event_type": "agentkit-slack-setting", "client_payload": {
    "changes": [{"key": "wip", "value": "3"}, {"key": "retro-cron", "value": "0 10 * * 4"}], "login": "alice", "slack_user": "U1"}}, body)
expect("repo menu: parses", core.parse_pick("repo|o/shop|wip", "repo") == ("o/shop", "wip"))
try: core.parse_pick("pick|o/shop|wip", "repo"); expect("repo menu: a pick is not a repo switch", False)
except ValueError: expect("repo menu: a pick is not a repo switch", True)
body = core.settings_ask("o/r", "q", "alice", "U1", ("D1", "1.2"), {}, None, served)[1]
expect("settings: ask carries the repos to switch to", body["client_payload"]["repos"] == served and len(body["client_payload"]) <= 10, body)
body = core.setting("o/r", "wip", "3", "alice", "U1")[1]
expect("settings: apply body", body == {"event_type": "agentkit-slack-setting", "client_payload": {
    "key": "wip", "value": "3", "login": "alice", "slack_user": "U1"}}, body)
expect("settings: value round trip", core.parse_setting("set|o/r|digest-statuses|a|b") == ("o/r", "digest-statuses", "a|b"))
for bad in ["set|../r|wip|3", "set|o/r|Bad Key|3", "set|o/r", "reply|o/r|wip|3"]:
    try: core.parse_setting(bad); expect("settings: bad value rejected: " + bad, False)
    except ValueError: expect("settings: bad value rejected: " + bad, True)
btn = [e for b in settings.card(settings.load(), "o/r", "hours?", '{"match": "nudge-hours"}')["blocks"]
       if b["type"] == "actions" for e in b["elements"] if e["type"] == "button"][0]
expect("settings: a card's button parses", core.parse_setting(btn["value"]) == ("o/r", "nudge-hours", "09-20"), btn)
expect("settings: a feature request round trip", core.parse_feature("feature|o/r|can it paint?") == ("o/r", "can it paint?"))

# nudges
from datetime import datetime, timedelta, timezone
now = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)
expect("hours: 09-20", core.parse_hours("09-20") == (9, 20))
for bad in ["9", "20-09", "00-25", "a-b", ""]:
    try: core.parse_hours(bad); expect("hours rejected: " + bad, False)
    except ValueError: expect("hours rejected: " + bad, True)
expect("nudge: due by default in hours", core.due({}, {}, now, 3))
expect("nudge: nothing waiting, no nudge", not core.due({}, {}, now, 0))
expect("nudge: off is off", not core.due({"nudge": "off"}, {}, now, 3))
expect("nudge: on is on", core.due({"nudge": "on"}, {}, now, 3))
expect("nudge: hours from the registry key", not core.due({"nudge-hours": "11-12"}, {}, now, 3))
expect("nudge: not before 09 UTC", not core.due({}, {}, now.replace(hour=8, minute=59), 3))
expect("nudge: not at 20 UTC", not core.due({}, {}, now.replace(hour=20), 3))
expect("nudge: hours are in the person's timezone (10 UTC is 05 in New York)", not core.due({"timezone": "America/New_York"}, {}, now, 3))
expect("nudge: 14 UTC is 09 in New York", core.due({"timezone": "America/New_York"}, {}, now.replace(hour=14), 3))
expect("nudge: a bad timezone falls back to UTC", core.due({"timezone": "Nowhere/Else"}, {}, now, 3))
h1 = core.record({}, now - timedelta(hours=3))
expect("nudge: never twice within 4 hours", not core.due({}, h1, now, 5))
expect("nudge: again after 4 hours", core.due({}, h1, now + timedelta(hours=1), 5))
h2 = core.record(core.record({}, now - timedelta(hours=9, minutes=30)), now - timedelta(hours=5))
expect("nudge: at most 2 a day (local day)", not core.due({}, h2, now + timedelta(hours=5), 5))
expect("nudge: nudges-per-day 1", not core.due({"nudges-per-day": 1}, core.record({}, now - timedelta(hours=5)), now, 5))
expect("nudge: nudges-per-day is capped at 2", not core.due({"nudges-per-day": 9}, h2, now + timedelta(hours=5), 5))
expect("nudge: a new day starts over", core.due({}, h2, now + timedelta(days=1), 5))
old = core.record({"sent": [(now - timedelta(days=5)).isoformat()]}, now)
expect("nudge: history keeps only recent sends", len(old["sent"]) == 1, old)
expect("nudge: text says how many and links the board",
       core.nudge_text(3, "slack://app?team=T1&id=A1&tab=home") == "3 waiting · <slack://app?team=T1&id=A1&tab=home|Open the board>")
expect("nudge: text without a link", core.nudge_text(1, None) == "1 waiting")

with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "sub" / "prefs.json"
    expect("prefs: a missing file is empty", core.load_prefs(p) == {"prefs": {}, "history": {}, "repo": {}})
    p.parent.mkdir()
    core.save_prefs(p, {"prefs": {"U1": {"nudge-hours": "08-18"}}, "history": {}})
    expect("prefs: saved and read back", core.load_prefs(p)["prefs"]["U1"]["nudge-hours"] == "08-18")
    expect("prefs: no temp file left", [f.name for f in p.parent.iterdir()] == ["prefs.json"], list(p.parent.iterdir()))
    p.write_text("{oops")
    try: core.load_prefs(p); expect("prefs: a broken file is an error, not reset", False)
    except ValueError: expect("prefs: a broken file is an error, not reset", True)

# post: a network error is retried, Slack's answer is used
import io, os, urllib.error
os.environ.update(SLACK_CHANNEL="C1", SLACK_BOT_TOKEN="x")
calls = []
def flaky(req, timeout):
    calls.append(1)
    if len(calls) < 3:
        raise urllib.error.URLError("Temporary failure in name resolution")
    return io.BytesIO(b'{"ok": true, "ts": "1.2"}')
card.urllib.request.urlopen, card.time.sleep = flaky, lambda s: None
expect("post retries a network error", card.post({"repo": "o/r", "number": 1, "title": "t", "labels": ["status:needs-info"]}) == "1.2" and len(calls) == 3)

# the timezone picker searches every zone by part of its name
expect("zones: a city finds its zone", "Asia/Jerusalem" in core.zones("jerus"))
expect("zones: a space is an underscore", "America/New_York" in core.zones("new york"))
expect("zones: at most 100 for Slack", len(core.zones("a")) == 100)
sys.exit(1 if fails else 0)
