"""bot/core.py and scripts/card.py: trust mapping, button values, the dispatch body, the card and its length lint."""
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bot")); sys.path.insert(0, str(ROOT / "scripts"))
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
bad = dict(c); bad["blocks"] = [{"type": "section", "text": {"type": "mrkdwn", "text": "*" + "t" * 90 + "*\n" + "a" * 200 + "\n<http://a|1> <http://b|2>"}}, c["blocks"][1]]
expect("lint flags title, ask and two links", len(card.lint(bad)) == 3, card.lint(bad))

stuck = "**Stuck on:** which `library`?\n**Why I can't decide alone:** w\n**Checked:** c\n**Options:** Allow web | Use memory\n\nReply with an answer"
expect("derive: stuck message gives ask and options", card.derive(["x", stuck]) == ("which library?", ["Allow web", "Use memory"]))
expect("derive: recommendation gives its first line", card.derive(["<!-- agentkit:recommendation -->\n> Adopt **option A**: one file per module.\n>\n> Reasons"]) == ("Adopt option A: one file per module.", []))
expect("derive: any other comment gives its first line", card.derive(["<!-- m -->\nagentkit: all checks passed; 1 item needs a person."]) == ("agentkit: all checks passed; 1 item needs a person.", []))
expect("derive: a recommendation line ending in : takes the next line", card.derive(["<!-- agentkit:recommendation -->\n> Adopt **C**:\n>\n> 1. Keep each constant in its module.\n> 2. More"]) == ("Adopt C: 1. Keep each constant in its module.", []))
refine = "## Plan\n- do x\n\n## Questions\n1. Should `negate` throw for non-numbers? — default if unanswered: no check.\n2. Other?\n\nReply with an answer"
expect("derive: refine questions give the first question", card.derive([refine]) == ("Should negate throw for non-numbers?", []), card.derive([refine]))
expect("derive: nothing gives nothing", card.derive([]) == (None, []))
c2 = card.build({"repo": "o/r", "number": 7, "title": "t", "labels": ["status:needs-human"], "comments": [stuck]})
expect("build uses derived ask and options", "which library?" in c2["text"] and [e["text"]["text"] for e in c2["blocks"][1]["elements"]][:2] == ["Allow web", "Use memory"])

d = card.done({"number": 96, "title": "RFC: where to put shared constants", "url": "https://github.com/o/r/pull/97",
               "body": "## Summary\nI added RFC 0002, `docs/rfcs/0002-shared-constants.md`, in proposed status. It compares four ways.\n\n## Changes\n- x"})
expect("done card: title, first Summary line, link, no buttons", len(d["blocks"]) == 1 and "✓ RFC: where" in d["text"] and "I added RFC 0002" in d["text"] and "pull/97|#96" in d["blocks"][0]["text"]["text"], d)
expect("done card within budget", card.lint(d) == [], card.lint(d))
expect("done card without a Summary says Merged.", "Merged." in card.done({"number": 1, "title": "t", "url": "u", "body": None})["text"])

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
sys.exit(1 if fails else 0)
