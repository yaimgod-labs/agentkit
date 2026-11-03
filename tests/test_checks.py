"""scripts/checks.py: which suites/external checks a change needs, and the gate verdict over a commit's checks."""
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/checks.py"
fails = 0


def run(*args, stdin=""):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def expect(name, cond, detail=""):
    global fails
    print(("ok: " if cond else "FAIL: ") + name + ("" if cond else f"\n{detail}"))
    fails += not cond


suites = json.dumps([
    {"name": "server", "paths": ["server/**"], "runs-on": "ubuntu-latest", "run": "npm test"},
    {"name": "app", "paths": ["app/**", "shared/*.json"], "runs-on": "macos-latest", "run": "make test"},
    {"name": "all", "run": "true"},  # no paths: always runs
])
names = lambda r: [s["name"] for s in r]
expect("only suites whose paths changed", names(run("select", suites, stdin="server/a/b.ts\nREADME.md\n")) == ["server", "all"])
expect("glob on a second pattern", names(run("select", suites, stdin="shared/x.json\n")) == ["app", "all"])
expect("empty config selects nothing", run("select", "", stdin="server/a\n") == [])


def gate(runs=(), statuses=(), required=(), age_min=5, timeout=60):
    doc = {"check_runs": list(runs), "statuses": list(statuses), "required": list(required),
           "since": "2026-11-02T10:00:00Z", "now": f"2026-11-02T{10 + age_min // 60:02d}:{age_min % 60:02d}:00Z", "timeout": timeout}
    return run("gate", stdin=json.dumps(doc))


def cr(name, status="completed", conclusion="success", id=1, summary=""):
    return {"id": id, "name": name, "status": status, "conclusion": conclusion, "app": {"slug": "x"},
            "html_url": f"https://ci/{name}", "output": {"title": "", "summary": summary}}


expect("all green passes", gate([cr("review / review (code)"), cr("lint", conclusion="skipped")])["verdict"] == "pass")
r = gate([cr("review / review (code)"), cr("mobile", conclusion="failure", summary="2 tests failed")])
expect("a failed check fails", r["verdict"] == "fail" and r["failed"][0]["name"] == "mobile" and "2 tests failed" in r["failed"][0]["detail"], r)
expect("the newest run of a name wins", gate([cr("ci", conclusion="failure", id=1), cr("ci", id=2)])["verdict"] == "pass")
expect("the gate's own check is ignored", gate([cr("review / gate", status="in_progress", conclusion=None)])["verdict"] == "pass")
expect("cancelled is ignored (superseded run)", gate([cr("ci", conclusion="cancelled")])["verdict"] == "pass")
r = gate([cr("ci", status="in_progress", conclusion=None)])
expect("an in-progress check waits", r["verdict"] == "wait" and r["pending"] == ["ci"], r)
r = gate(required=["mobile-ci"])
expect("a required check that has not reported waits", r["verdict"] == "wait" and r["pending"] == ["mobile-ci"], r)
r = gate(required=["mobile-ci"], age_min=61)
expect("and times out after the timeout", r["verdict"] == "timeout" and r["pending"] == ["mobile-ci"], r)
expect("a required check that passed is fine", gate([cr("mobile-ci")], required=["mobile-ci"])["verdict"] == "pass")
st = lambda ctx, state, d="": {"context": ctx, "state": state, "description": d, "target_url": f"https://j/{ctx}"}
r = gate(statuses=[st("jenkins", "failure", "build broke")])
expect("a failed commit status fails", r["verdict"] == "fail" and "build broke" in r["failed"][0]["detail"], r)
expect("no empty link when a status has no URL", not gate(statuses=[{"context": "x", "state": "error"}])["failed"][0]["detail"].endswith("()"))
expect("a pending status waits", gate(statuses=[st("jenkins", "pending")])["verdict"] == "wait")
expect("a status satisfies a required name", gate(statuses=[st("jenkins", "success")], required=["jenkins"])["verdict"] == "pass")
r = gate([cr("a", conclusion="failure"), cr("b", status="queued", conclusion=None)])
expect("failure wins over pending", r["verdict"] == "fail", r)
# the kit's own checks are required by job name; the caller's job name prefixes them ("review / docs")
own = ["review (code)", "review (security)", "docs", "integration"]
r = gate(required=own)
expect("no checks at all never passes (a conflicted PR gets no runs)", r["verdict"] == "wait" and r["pending"] == own, r)
expect("a required job name matches its prefixed check run",
       gate([cr("review / " + n, id=i) for i, n in enumerate(own)], required=own)["verdict"] == "pass")
expect("a required name matches only a whole job name", gate([cr("review / xdocs")], required=["docs"])["pending"] == ["docs"])

BOT = "agentkit-x[bot]"
def rounds(*comments, people=(555, 556)):
    r = subprocess.run([sys.executable, str(SCRIPT), "rounds", BOT], capture_output=True, text=True,
                       input=json.dumps({"comments": [{"user": u, "body": b} for u, b in comments], "people": list(people)}))
    assert r.returncode == 0, r.stderr
    return int(r.stdout)
RND = "<!-- agentkit:round abc -->\nagentkit: review round failed"
def reset(cid=555):
    return f"<!-- agentkit:reset-rounds {cid} -->\nRetry requested by @alice."
RESET = reset()
expect("no comments, no rounds", rounds() == 0)
expect("the kit's round comments count", rounds((BOT, RND), ("alice", "lgtm"), (BOT, RND)) == 2)
expect("only rounds after the latest reset count", rounds((BOT, RND), (BOT, RND), (BOT, RESET), (BOT, RND)) == 1)
expect("a reset with no round after it is 0", rounds((BOT, RND), (BOT, RESET)) == 0)
expect("a person's round marker never counts", rounds(("alice", RND), (BOT, RND)) == 1)
expect("a person's reset marker never resets", rounds((BOT, RND), ("alice", RESET), (BOT, RND)) == 2)
expect("a marker inside a comment is not one", rounds((BOT, RND + "\n" + RESET), (BOT, "see " + RND)) == 1)
expect("another bot's comments are ignored", rounds(("other[bot]", RND), ("other[bot]", RESET)) == 0)
# a reset counts only for a write-access person's issue comment (its id in `people`), and each comment resets once,
# so an agent with a comment token can neither invent one nor replay one
expect("a reset without a comment id never resets", rounds((BOT, RND), (BOT, "<!-- agentkit:reset-rounds -->\nx"), (BOT, RND)) == 2)
expect("a reset naming no person's comment never resets", rounds((BOT, RND), (BOT, reset(999)), (BOT, RND)) == 2)
expect("a replayed reset never resets again",
       rounds((BOT, RND), (BOT, RESET), (BOT, RND), (BOT, RND), (BOT, RESET), (BOT, RND)) == 3)
expect("a second person's comment resets again",
       rounds((BOT, RND), (BOT, RESET), (BOT, RND), (BOT, reset(556)), (BOT, RND)) == 1)
expect("no people: no reset", rounds((BOT, RND), (BOT, RESET), (BOT, RND), people=()) == 2)
expect("a reset id must be the whole number", rounds((BOT, RND), (BOT, "<!-- agentkit:reset-rounds 5555 -->"), (BOT, RND)) == 2)
r = subprocess.run([sys.executable, str(SCRIPT), "rounds", BOT], capture_output=True, text=True,
                   input=json.dumps([{"user": BOT, "body": RND}]))
expect("rounds also takes a bare comment list (no people)", r.returncode == 0 and r.stdout.strip() == "1", r.stderr)
r = subprocess.run([sys.executable, str(SCRIPT), "rounds"], capture_output=True, text=True, input="[]")
expect("rounds without a bot login is a usage error", r.returncode == 2)

def decided(pr=(), issue=()):
    r = subprocess.run([sys.executable, str(SCRIPT), "decided"], capture_output=True, text=True,
                       input=json.dumps({"pr": list(pr), "issue": list(issue)}))
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()
expect("decided: nothing is undecided", decided() == "false")
expect("decided: a person's /decide on the PR", decided(pr=["/decide accept fits the budget"]) == "true")
expect("decided: /decide reject, any case", decided(pr=["/Decide REJECT too slow"]) == "true")
expect("decided: /decide must start the comment", decided(pr=["see /decide accept x"]) == "false")
expect("decided: /decide anything else is not one", decided(pr=["/decide maybe"]) == "false")
expect("decided: a person's Slack accept on the issue", decided(issue=["accept it fits"]) == "true")
expect("decided: reject, any case, trailing punctuation", decided(issue=["  Reject: too risky"]) == "true")
expect("decided: accept must be the first word", decided(issue=["I accept"]) == "false")
expect("decided: acceptance is not accept", decided(issue=["acceptance tests pass"]) == "false")
expect("decided: an issue /decide is not a Slack reply", decided(issue=["/decide accept x"]) == "false")
for bad in ("[]", '{"pr": "x"}', '{"pr": [1]}', "nope"):
    r = subprocess.run([sys.executable, str(SCRIPT), "decided"], capture_output=True, text=True, input=bad)
    expect(f"decided: bad input {bad!r} is false", r.returncode == 0 and r.stdout.strip() == "false", r.stderr)

sys.exit(1 if fails else 0)
