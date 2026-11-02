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

sys.exit(1 if fails else 0)
