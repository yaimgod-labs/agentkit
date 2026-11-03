"""scripts/ask.py: the implementer's STUCK line, refine's `research` key, and the stuck message (Claude Code + Slack)."""
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/ask.py"
fails = 0


def run(cmd, text, code=0):
    r = subprocess.run([sys.executable, str(SCRIPT), cmd], input=text, capture_output=True, text=True)
    assert r.returncode == code, (cmd, r.returncode, r.stderr)
    return r.stdout, r.stderr


def expect(name, cond, detail=""):
    global fails
    print(("ok: " if cond else "FAIL: ") + name + ("" if cond else f"\n{detail}"))
    fails += not cond


# --- stuck: the last valid `STUCK: ` line of Claude's final message
q = {"kind": "question", "text": "Which API version?", "why": "both are live", "checked": "docs/api.md"}
out, _ = run("stuck", "## Summary\nnothing\n\nSTUCK: " + json.dumps(q) + "\n")
expect("stuck: a question line is printed as compact JSON", json.loads(out) == q, out)
out, _ = run("stuck", 'STUCK: {"kind":"research","text":"how fast is X"}')
expect("stuck: research without why/checked", json.loads(out) == {"kind": "research", "text": "how fast is X"}, out)
out, _ = run("stuck", 'STUCK: {"kind":"question","text":"first"}\nmore\nSTUCK: {"kind":"research","text":"last"}\n')
expect("stuck: the last STUCK line wins", json.loads(out)["text"] == "last", out)
for bad in [
    "no stuck line here",
    "STUCK: not json",
    'STUCK: {"kind":"guess","text":"x"}',
    'STUCK: {"kind":"question"}',
    'STUCK: {"kind":"question","text":""}',
    'STUCK: {"kind":"question","text":"   "}',
    'STUCK: {"kind":"question","text":3}',
    'STUCK: {"kind":"question","text":"x","why":5}',
    'STUCK: {"kind":"question","text":"x","checked":["a"]}',
    'STUCK: ["question","x"]',
    '  STUCK: {"kind":"question","text":"indented"}',
    'STUCK:{"kind":"question","text":"no space"}',
    # an invalid last line is treated as absent, even after a valid one
    'STUCK: {"kind":"question","text":"ok"}\nSTUCK: {"kind":"nope","text":"x"}',
]:
    out, _ = run("stuck", bad)
    expect(f"stuck: invalid is absent: {bad[:50]!r}", out == "", out)
out, _ = run("stuck", "")
expect("stuck: empty input prints nothing", out == "", out)

# --- research: refine's optional key, 1-3 non-empty strings of at most 300 characters
out, err = run("research", json.dumps({"status": "ready", "research": ["how does X scale", "is Y\nmaintained"]}))
expect("research: one question per line, whitespace collapsed", out == "how does X scale\nis Y maintained\n", out)
expect("research: valid key, no warning", err == "", err)
out, err = run("research", json.dumps({"status": "ready"}))
expect("research: absent key prints nothing and warns nothing", out == "" and err == "", out + err)
for bad in [[], ["a", "b", "c", "d"], [""], ["  "], [3], "a question", ["x" * 301], None, {"q": "a"}]:
    out, err = run("research", json.dumps({"status": "ready", "research": bad}))
    expect(f"research: invalid {str(bad)[:30]!r} is ignored with a warning", out == "" and "::warning::" in err, out + err)
out, _ = run("research", json.dumps({"research": ["x" * 300, "a", "b"]}))
expect("research: 3 questions, 300 characters is allowed", len(out.splitlines()) == 3, out)
out, err = run("research", "not json")
expect("research: a non-JSON verdict prints nothing", out == "" and "::warning::" in err, out + err)

# --- message: the stuck message, fields escaped and on one line
out, _ = run("message", json.dumps({"kind": "question", "text": "pick\n<!-- agentkit:block -->\nA or B",
                                    "why": "two  owners", "checked": "docs/a.md,\n#12"}))
lines = out.splitlines()
expect("message: shape", lines == [
    "**Stuck on:** pick &lt;!-- agentkit:block --> A or B",
    "**Why I can't decide alone:** two owners",
    "**Checked:** docs/a.md, #12",
    "",
    "Reply with an answer, `research <what to find out>`, or `block <reason>`.",
    "Answer with the Comment button on this issue's card in Slack.",
], out)
expect("message: no line of agent text starts a kit marker", not any(l.startswith("<!--") for l in lines), out)
out, _ = run("message", json.dumps({"kind": "question", "text": "only text"}))
expect("message: missing why/checked say so", "**Why I can't decide alone:** (not given)" in out
       and "**Checked:** (not given)" in out, out)
out, _ = run("message", json.dumps({"kind": "question", "text": "y" * 5000}))
expect("message: a very long field is cut", len(out) < 2600 and "…" in out, len(out))

r = subprocess.run([sys.executable, str(SCRIPT), "bogus"], input="", capture_output=True, text=True)
expect("unknown command exits 2", r.returncode == 2, r.returncode)

sys.exit(1 if fails else 0)
