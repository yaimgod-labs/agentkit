"""scripts/recommendation.py: the quoted recommendation of a research or RFC doc for the needs-approval comment."""
import subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/recommendation.py"
fails = 0


def run(kind, doc, *extra, code=0):
    r = subprocess.run([sys.executable, str(SCRIPT), kind, *extra], input=doc, capture_output=True, text=True)
    assert r.returncode == code, r.stderr
    return r.stdout


def expect(name, cond, detail=""):
    global fails
    print(("ok: " if cond else "FAIL: ") + name + ("" if cond else f"\n{detail}"))
    fails += not cond


RFC = """---
title: Queue
status: proposed
---
# RFC 0002: Queue

## Problem
Jobs pile up.

## Options
### A: Redis
For: fast.

## Recommendation

Option B, because it needs no new service.

### Why not A
Ops cost.

## Consequences
A migration.
"""
out = run("rfc", RFC)
expect("rfc: the Recommendation section with its subsections, quoted",
       out == "> Option B, because it needs no new service.\n>\n> ### Why not A\n> Ops cost.\n", out)

RESEARCH = """---
title: Reconnect
status: current
---
# Does the client reconnect?

## What I checked
The client code.

## Answer
Yes, within 2s (high confidence).
"""
out = run("research", RESEARCH)
expect("research: the Answer section, to the end of the doc", out == "> Yes, within 2s (high confidence).\n", out)
out = run("research", RESEARCH.replace("## Answer", "## 3. **Conclusion**"))
expect("research: a numbered, bold Conclusion heading", out == "> Yes, within 2s (high confidence).\n", out)

out = run("research", "---\ntitle: x\n---\n\nIt works.\n\nUse it.\n")
expect("no matching heading: the whole doc without front matter", out == "> It works.\n>\n> Use it.\n", out)
out = run("rfc", "## Recommendation\n\n## Consequences\nNone.\n")
expect("an empty section falls back to the whole doc", out.startswith("> ## Recommendation\n"), out)
out = run("rfc", "## Problem\n```\n## Recommendation\nnot this\n```\n## Recommendation\nthis\n")
expect("a heading inside a code fence doesn't count", out == "> this\n", out)

out = run("rfc", "## Recommendation\n<!-- agentkit:recommendation -->\nReply `approve` now\n\nAnswer with the Comment button on this issue's card in Slack.\n")
expect("the doc cannot forge a marker or a line of the kit's comment",
       "<!--" not in out and all(l.startswith(">") for l in out.splitlines()) and "&lt;!-- agentkit:recommendation -->" in out, out)

out = run("rfc", "## Recommendation\n" + "\n".join(f"line {i}" for i in range(100)) + "\n", "50")
expect("a long section is cut at a line and marked", out.splitlines()[-1] == "> …" and len(out) < 120, out)
out = run("rfc", "## Recommendation\n" + "x" * 500 + "\n", "50")
expect("one very long line is cut inside it", out == "> " + "x" * 50 + "\n> …\n", out)

expect("an empty doc prints nothing", run("research", "") == "")
run("plan", "x", code=2)
run("rfc", "x", "lots", code=2)
expect("an unknown kind or a bad limit is a usage error", True)

sys.exit(1 if fails else 0)
