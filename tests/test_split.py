"""scripts/split.py: refine's `split` key and the split proposal comment (Claude Code + Slack mode)."""
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/split.py"
fails = 0


def run(verdict, cmd="proposal", code=0):
    text = verdict if isinstance(verdict, str) else json.dumps(verdict)
    r = subprocess.run([sys.executable, str(SCRIPT), *cmd.split()], input=text, capture_output=True, text=True)
    assert r.returncode == code, (cmd, r.returncode, r.stderr)
    return r.stdout, r.stderr


def expect(name, cond, detail=""):
    global fails
    print(("ok: " if cond else "FAIL: ") + name + ("" if cond else f"\n{detail}"))
    fails += not cond


V = {"status": "needs-info", "size": "m", "type": "feature", "mode": "agent"}
two = [{"title": "Add the endpoint", "why": "the API first"}, {"title": "Add the UI", "why": "uses the endpoint"}]

out, err = run({**V, "split": two})
expect("proposal: shape", out.splitlines() == [
    "**Proposed split** (size m):",
    "1. Add the endpoint — the API first",
    "2. Add the UI — uses the endpoint",
    "Reply `approve` to create these sub-tasks, or say what to change.",
    "Answer with the Comment button on this issue's card in Slack.",
], out)
expect("proposal: valid split, no warning", err == "", err)
out, _ = run({**V, "size": "l", "split": two})
expect("proposal: the size is the verdict's", out.startswith("**Proposed split** (size l):\n"), out)

# agent text is untrusted: one line per item, `<!--` escaped, at most 200 characters
out, _ = run({**V, "split": [{"title": "Add\n<!-- agentkit:block -->\nX", "why": "a  b\nc"}, {"title": "T", "why": ""}]})
lines = out.splitlines()
expect("proposal: an item stays on one line, escaped", lines[1] == "1. Add &lt;!-- agentkit:block --> X — a b c", out)
expect("proposal: an empty why leaves just the title", lines[2] == "2. T", out)
expect("proposal: no line starts a kit marker", not any(l.startswith("<!--") for l in lines), out)
out, _ = run({**V, "split": [{"title": "t" * 300, "why": "w" * 300}, {"title": "u", "why": "v"}]})
item = out.splitlines()[1]
expect("proposal: an item is cut to 200 characters", item.startswith("1. ttt") and len(item[len("1. "):]) == 200
       and item.endswith("…"), item)
out, _ = run({**V, "split": [{"title": "a", "why": "b", "extra": 1}] * 8})
expect("proposal: 8 items and extra keys are fine", len(out.splitlines()) == 11, out)

for bad in [
    None, [], [two[0]], [two[0]] * 9, "two tasks", {"title": "x"},
    [{"title": "", "why": "x"}, two[1]], [{"title": "  ", "why": "x"}, two[1]],
    [{"why": "x"}, two[1]], [{"title": "x"}, two[1]], [{"title": 3, "why": "x"}, two[1]],
    [{"title": "x", "why": None}, two[1]], ["a", "b"],
]:
    out, err = run({**V, "split": bad})
    expect(f"proposal: invalid split {str(bad)[:40]!r} prints nothing and warns", out == "" and "::warning::" in err, out + err)
out, err = run(V)
expect("proposal: a missing split prints nothing and warns", out == "" and "::warning::" in err, out + err)
for size in ("xs", "s", None):
    out, err = run({**V, "size": size, "split": two})
    expect(f"proposal: size {size!r} is not split", out == "" and "::warning::" in err, out + err)
out, err = run("not json")
expect("proposal: a non-JSON verdict prints nothing and warns", out == "" and "::warning::" in err, out + err)
out, err = run("[]")
expect("proposal: a non-object verdict prints nothing and warns", out == "" and "::warning::" in err, out + err)
deep = "[" * 100000 + "]" * 100000
out, err = run('{"size":"m","split":' + deep + "}")
expect("proposal: deeply nested split is ignored, not a crash", out == "" and "::warning::" in err, out + err)

# a research question or an RFC is never split: it keeps today's m/l behavior
for typ in ("research", "rfc"):
    out, err = run({**V, "type": typ, "split": two})
    expect(f"proposal: a {typ} is not split", out == "" and "::warning::" in err, out + err)


def eligible(v):
    r = subprocess.run([sys.executable, str(SCRIPT), "eligible"], input=v if isinstance(v, str) else json.dumps(v),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


for typ in ("feature", "bug", "chore", "debt"):
    for size in ("m", "l"):
        expect(f"eligible: {typ} {size}", eligible({**V, "type": typ, "size": size}) == "true\n")
for v in [{**V, "type": "research"}, {**V, "type": "rfc", "size": "l"}, {**V, "size": "s"}, {**V, "size": "xs"},
          {"size": "m"}, [], "not json"]:
    expect(f"eligible: not {str(v)[:40]!r}", eligible(v) == "false\n")
expect("eligible: needs no split list", eligible({**V, "split": None}) == "true\n")

# open questions in the plan come before the split
out, _ = run({**V, "split": two}, cmd="proposal --questions")
expect("proposal --questions: the questions line before the reply line", out.splitlines()[3:] == [
    "Answer the questions above first if they change the split.",
    "Reply `approve` to create these sub-tasks, or say what to change.",
    "Answer with the Comment button on this issue's card in Slack.",
], out)

run("", cmd="bogus", code=2)
expect("unknown command exits 2", True)

sys.exit(1 if fails else 0)
