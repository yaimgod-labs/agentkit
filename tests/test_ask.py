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
r = subprocess.run([sys.executable, str(SCRIPT), "message"], input=json.dumps({"kind": "question", "text": "y" * 2001}),
                   capture_output=True, text=True)
expect("message: an over-long field is refused", r.returncode == 2, r.returncode)
out, _ = run("message", json.dumps({"kind": "research", "text": "how fast is X"}))
expect("message: a research STUCK can be posted as a question", out.startswith("**Stuck on:** how fast is X\n"), out)

# --- deep nesting never crashes (RecursionError on Python 3.9-3.13): the line is absent
deep = "[" * 100000 + "]" * 100000
out, _ = run("stuck", "STUCK: " + deep)
expect("stuck: deeply nested JSON is absent, not a crash", out == "", out)
out, _ = run("stuck", 'STUCK: {"kind":"question","text":"x","why":' + deep + "}")
expect("stuck: deeply nested field is absent, not a crash", out == "", out)
out, err = run("research", '{"research":' + deep + "}")
expect("research: deeply nested key is ignored with a warning", out == "" and "::warning::" in err, out + err)
out, _ = run("nested", '{"labels":[],"body":' + deep + "}")
expect("nested: deeply nested issue JSON counts as nested (fail safe)", out == "true\n", out)

# --- length caps: research text at most 300, question fields at most 2000
out, _ = run("stuck", 'STUCK: ' + json.dumps({"kind": "research", "text": "r" * 300}))
expect("stuck: research text of 300 characters is valid", out != "", out)
out, _ = run("stuck", 'STUCK: ' + json.dumps({"kind": "research", "text": "r" * 301}))
expect("stuck: research text over 300 characters is absent", out == "", out)
out, _ = run("stuck", 'STUCK: ' + json.dumps({"kind": "question", "text": "q" * 2000, "why": "w" * 2000, "checked": "c" * 2000}))
expect("stuck: question fields of 2000 characters are valid", out != "", out)
for k in ("text", "why", "checked"):
    d = {"kind": "question", "text": "q"}
    d[k] = "z" * 2001
    out, _ = run("stuck", "STUCK: " + json.dumps(d))
    expect(f"stuck: question {k} over 2000 characters is absent", out == "", out)
d = {"kind": "research", "text": "r", "why": "w" * 2001}
out, _ = run("stuck", "STUCK: " + json.dumps(d))
expect("stuck: research why over 2000 characters is absent", out == "", out)

# --- nested: an issue that is research already (type:research, or the kit's research-for marker) files no research
def nested(issue):
    return run("nested", json.dumps(issue))[0]
expect("nested: type:research label", nested({"labels": [{"name": "type:research"}], "body": "q"}) == "true\n")
expect("nested: labels as plain names", nested({"labels": ["type:research"], "body": ""}) == "true\n")
expect("nested: research-for marker in the body",
       nested({"labels": [{"name": "type:feature"}], "body": "## Question\nx\n\n<!-- agentkit:research-for #7 -->"}) == "true\n")
expect("nested: an ordinary issue", nested({"labels": [{"name": "type:feature"}], "body": "do X"}) == "false\n")
expect("nested: null body and no labels", nested({"labels": None, "body": None}) == "false\n")
expect("nested: not JSON counts as nested (fail safe)", run("nested", "oops")[0] == "true\n")

r = subprocess.run([sys.executable, str(SCRIPT), "bogus"], input="", capture_output=True, text=True)
expect("unknown command exits 2", r.returncode == 2, r.returncode)

# --- options: the answers the Slack card offers as buttons
qo = {**q, "options": ["Allow web", "Use memory"]}
out, _ = run("stuck", "STUCK: " + json.dumps(qo))
expect("stuck: 1-3 short options are kept", json.loads(out) == qo, out)
for bad_opts in [[], ["a", "b", "c", "d"], ["x" * 41], [""], "yes", [1]]:
    out, _ = run("stuck", "STUCK: " + json.dumps({**q, "options": bad_opts}))
    expect(f"stuck: options {bad_opts!r} make the line invalid", out == "", out)
out, _ = run("message", json.dumps({**qo, "options": ["a | b", "c"]}))
expect("message: options on one line, | in an option becomes /", "**Options:** a / b | c\n" in out, out)
out, _ = run("message", json.dumps(q))
expect("message: no options line without options", "Options" not in out, out)

sys.exit(1 if fails else 0)
