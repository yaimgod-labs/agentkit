"""scripts/done.py: the Slack "task done" text for a merged agent PR (Slack mode)."""
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/done.py"
fails = 0


def run(d, code=0):
    text = d if isinstance(d, str) else json.dumps(d)
    r = subprocess.run([sys.executable, str(SCRIPT)], input=text, capture_output=True, text=True)
    assert r.returncode == code, (r.returncode, r.stderr)
    return r.stdout


def expect(name, cond, detail=""):
    global fails
    print(("ok: " if cond else "FAIL: ") + name + ("" if cond else f"\n{detail}"))
    fails += not cond


URL = "https://github.com/o/r/pull/9"
PR = {"number": 7, "title": "Add the endpoint", "url": URL,
      "body": "Closes #7\n\n## Summary\nAdds `/share`.\n- tests in api/\n\n## Human verification\n- [x] looked\n"}

out = run(PR)
expect("done: first line, Summary, URL", out == f"Task #7 done: Add the endpoint\n\nAdds `/share`.\n- tests in api/\n\n{URL}\n", out)
out = run({**PR, "body": "## Summary\nlast section\n"})
expect("done: a Summary that ends the body", out == f"Task #7 done: Add the endpoint\n\nlast section\n\n{URL}\n", out)
out = run({**PR, "body": "## Summary   \nx\n### Detail\ny\n## Next\nz"})
expect("done: Summary runs to the next `## `, not `### `", "x\n### Detail\ny\n\n" in out and "z" not in out, out)
for body in ("no summary here", "", None, "## Summary\n\n   \n## Other\nx", "## Summaryish\nx"):
    out = run({**PR, "body": body})
    expect(f"done: no Summary in {str(body)[:20]!r} gives the first line and the URL",
           out == f"Task #7 done: Add the endpoint\n\n{URL}\n", out)

# untrusted agent text: `<!--` escaped, and Slack's control characters (& < >) escaped everywhere
out = run({**PR, "title": "a <b> & c\nd", "body": "## Summary\n<!-- agentkit:block -->\n<!here> & <https://x|y>\n"})
expect("done: the title on one line, escaped", out.splitlines()[0] == "Task #7 done: a &lt;b&gt; &amp; c d", out)
expect("done: the Summary escaped", "&lt;!-- agentkit:block --&gt;\n&lt;!here&gt; &amp; &lt;https://x|y&gt;" in out, out)
expect("done: no raw < left", "<" not in out, out)

out = run({**PR, "body": "## Summary\n" + "s" * 3000})
summary = out.split("\n\n")[1]
expect("done: the Summary is cut to 1500 characters", len(summary) == 1500 and summary.endswith("…"), len(summary))

for bad in ("not json", "[]", json.dumps({**PR, "number": "7"}), json.dumps({**PR, "url": None}),
            json.dumps({k: v for k, v in PR.items() if k != "title"})):
    run(bad, code=2)
    expect(f"done: bad input {bad[:30]!r} exits 2", True)

sys.exit(1 if fails else 0)
