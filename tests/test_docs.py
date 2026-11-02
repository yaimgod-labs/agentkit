"""docs.py against a throwaway git repo: schema, links, index, drift and the Stop hook."""
import os, subprocess, sys, tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "plugins/agentkit/scripts/docs.py"
fails = 0


def run(*args, stdin=""):
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True)


def sh(*args):
    subprocess.run(args, check=True, capture_output=True)


def expect(name, cond, detail=""):
    global fails
    print(("ok: " if cond else "FAIL: ") + name + ("" if cond else f"\n{detail}"))
    fails += not cond


def write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text)


with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    expect("no docs/ is a no-op", run("check").returncode == 0)
    sh("git", "init", "-q", "-b", "main")
    sh("git", "config", "user.email", "t@t"); sh("git", "config", "user.name", "t")
    # line budgets: CLAUDE.md files and .claude/rules, default 150, a marker sets a file's own
    write("CLAUDE.md", "x\n" * 151)
    write("app/CLAUDE.md", "<!-- agentkit: max-lines 3 -->\na\nb\nc\n")
    write(".claude/rules/net.md", "<!-- agentkit: max-lines 200 -->\n" + "x\n" * 160)
    sh("git", "add", "-A")
    r = run("check")
    expect("budget checked without docs/", r.returncode == 1 and "CLAUDE.md: 151 lines, budget 150" in r.stdout, r.stdout)
    expect("a file's own budget applies", "app/CLAUDE.md: 4 lines, budget 3" in r.stdout and "net.md" not in r.stdout, r.stdout)
    expect("hook blocks an over-budget CLAUDE.md", run("hook", stdin="{}").returncode == 2)
    write("CLAUDE.md", "x\n" * 150); write("app/CLAUDE.md", "<!-- agentkit: max-lines 4 -->\na\nb\nc\n")
    expect("within budget passes", run("check").returncode == 0)
    write("src/payments/retry.py", "a\n")
    write("src/api.ts", "a\n")
    write("docs/architecture/payments.md", "---\ntitle: Payments\nstatus: current\ndescription: Retries\ncovers:\n  - src/payments/**\n---\nSee [api](api.md).\n")
    write("docs/architecture/api.md", "---\ntitle: API\nstatus: current\ncovers: [src/api.ts]  # the server\n---\n[web](https://x.y) [anchor](#a)\n")
    expect("index writes README", run("index").returncode == 0 and "| [Payments](architecture/payments.md) | current | Retries |" in Path("docs/README.md").read_text())
    sh("git", "add", "-A"); sh("git", "commit", "-qm", "init")
    r = run("check"); expect("valid docs pass check", r.returncode == 0, r.stdout)
    expect("fresh index passes --check", run("index", "--check").returncode == 0)

    write("docs/bad.md", "---\ntitle: \nstatus: wip\ncovers: [gone/**]\n---\n[x](nope.md)\n")
    write("docs/none.md", "no front matter\n")
    out = run("check").stdout
    for frag in ["`title` is required", "`status` must be", "covers `gone/**` matches no tracked file", "broken link `nope.md`", "none.md: missing front matter"]:
        expect(f"check reports: {frag}", frag in out, out)
    expect("stale index fails --check", run("index", "--check").returncode == 1)
    os.remove("docs/bad.md"); os.remove("docs/none.md")

    # decisions flow: an accepted/rejected RFC needs a decision record linking it; supersedes targets must be superseded
    write("docs/rfcs/0001-cache.md", "---\ntitle: Cache\nstatus: accepted\n---\n")
    write("docs/rfcs/0002-queue.md", "---\ntitle: Queue\nstatus: proposed\n---\n")
    write("docs/decisions/0001-old.md", "---\ntitle: Old\nstatus: accepted\n---\n")
    write("docs/decisions/0002-new.md", "---\ntitle: New\nstatus: accepted\nsupersedes: [0001, 0009]\n---\n")
    out = run("check").stdout
    expect("accepted RFC without a decision record fails", "rfcs/0001-cache.md: `accepted` RFC has no decision record" in out, out)
    expect("proposed RFC needs no record", "0002-queue.md" not in out, out)
    expect("supersedes target must be marked superseded", "supersedes 0001, which is not `status: superseded`" in out, out)
    expect("supersedes target must exist", "supersedes 0009, which does not exist" in out, out)
    write("docs/decisions/0003-cache.md", "---\ntitle: Use a cache\nstatus: accepted\n---\nFrom [the RFC](../rfcs/0001-cache.md).\n")
    write("docs/decisions/0001-old.md", "---\ntitle: Old\nstatus: superseded\n---\n")
    write("docs/decisions/0002-new.md", "---\ntitle: New\nstatus: accepted\nsupersedes: [0001]\n---\n")
    r = run("check"); expect("linked record and superseded target pass", r.returncode == 0, r.stdout)
    for f in ["docs/rfcs/0001-cache.md", "docs/rfcs/0002-queue.md", "docs/decisions/0001-old.md", "docs/decisions/0002-new.md", "docs/decisions/0003-cache.md"]:
        os.remove(f)

    sh("git", "checkout", "-qb", "feature")
    write("src/payments/retry.py", "b\n")
    sh("git", "commit", "-qam", "change payments")
    r = run("drift", "main")
    expect("drift flags the doc whose code changed", r.returncode == 1 and "docs reviewed: docs/architecture/payments.md" in r.stdout, r.stdout)
    expect("drift ignores docs whose code did not change", "api.md" not in r.stdout, r.stdout)
    write("body.md", "## Docs\n- [x] docs reviewed: docs/architecture/payments.md — rename only\n")
    expect("ticked line in PR body clears drift", run("drift", "main", "--pr-body", "body.md").returncode == 0)
    os.remove("body.md")

    os.environ["AGENTKIT_BASE"] = "main"  # the workflow sets this; locally origin/HEAD is the default
    r = run("hook", stdin='{"stop_hook_active": false}')
    expect("hook exits 2 with a message", r.returncode == 2 and "docs/architecture/payments.md" in r.stderr, r.stderr)
    expect("hook skips when stop_hook_active", run("hook", stdin='{"stop_hook_active": true}').returncode == 0)
    write("docs/architecture/payments.md", Path("docs/architecture/payments.md").read_text() + "Updated.\n")
    r = run("hook", stdin="{}")
    expect("hook passes once the doc is updated", r.returncode == 0, r.stderr)

sys.exit(1 if fails else 0)
