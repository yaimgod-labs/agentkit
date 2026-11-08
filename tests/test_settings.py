"""config/settings.json and scripts/settings.py: every knob the kit reads is in the registry, and validate() holds."""
import re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/settings.py"
sys.path.insert(0, str(ROOT / "scripts"))
import settings  # noqa: E402

# secrets and keys are not settings
NOT_SETTINGS = {"GITHUB_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "GITHUB_APP_KEY_FILE"}
fails = 0


def expect(name, cond, detail=""):
    global fails
    print(("ok: " if cond else "FAIL: ") + name + ("" if cond else f"\n{detail}"))
    fails += not cond


def jobs_of(entry):
    j = entry["apply"].get("job", [])
    return [j] if isinstance(j, str) else j


def call_inputs(path):
    """{input: default} of a reusable workflow's `workflow_call` (a block scalar default is joined into one string)."""
    out, name, block, state = {}, None, None, 0
    for line in path.read_text().splitlines():
        if state == 0 and re.match(r"^  workflow_call:\s*$", line):
            state = 1
        elif state == 1 and re.match(r"^    inputs:\s*$", line):
            state = 2
        elif state == 2:
            if line.strip() and not line.startswith("      "):
                break
            if block is not None:
                if line.startswith("          "):
                    block.append(line[10:])
                    out[name] = "\n".join(block) + "\n"
                    continue
                block = None
            m = re.match(r"^      ([a-z0-9-]+):\s*$", line)
            if m:
                name = m.group(1)
                out[name] = None
                continue
            m = re.match(r"^        default:\s*(.*)$", line)
            if m and name:
                v = m.group(1).strip()
                if v == "|":
                    block = []
                else:
                    out[name] = v.strip('"')
    return out


def caller_jobs(path):
    """{job: (workflow file, {with-input: value})} of the caller template's uncommented `uses:` jobs."""
    jobs, job, in_with = {}, None, False
    for line in path.read_text().splitlines():
        m = re.match(r"^  ([a-z-]+):\s*$", line)
        if m:
            job, in_with = m.group(1), False
            continue
        m = re.match(r"^    uses: .*/\.github/workflows/([a-z-]+\.yml)@", line)
        if m and job:
            jobs[job] = (m.group(1), {})
            continue
        if re.match(r"^    with:\s*$", line):
            in_with = True
            continue
        if in_with:
            m = re.match(r"^      ([a-z0-9-]+):\s*(.*)$", line)
            if m and job in jobs:
                jobs[job][1][m.group(1)] = m.group(2)
            elif not line.startswith("      "):
                in_with = False
    return jobs


entries = settings.load()
by_key = {e["key"]: e for e in entries}
expect("keys are unique", len(by_key) == len(entries))

# schema
VIA = {"prefs", "variable", "caller", "server"}
for e in entries:
    k = e.get("key", "?")
    missing = [f for f in ("key", "scope", "title", "description", "type", "default", "options", "validate", "apply") if f not in e]
    expect(f"{k}: has every field", not missing, missing)
    if missing:
        continue
    expect(f"{k}: scope and type known", e["scope"] in ("user", "project") and e["type"] in settings.TYPES, e)
    expect(f"{k}: apply.via known", e["apply"].get("via") in VIA, e["apply"])
    expect(f"{k}: user settings live in prefs, project ones do not",
           (e["scope"] == "user") == (e["apply"]["via"] == "prefs"), e)
    expect(f"{k}: default passes its own rule", settings.validate(e, e["default"]) is None, settings.validate(e, e["default"]))
    bad = [o for o in e["options"] if settings.validate(e, o) is not None]
    expect(f"{k}: every option passes its own rule", not bad, bad)
    expect(f"{k}: at most 4 options", len(e["options"]) <= 4, e["options"])

# coverage: repo variables
WF = ROOT / ".github/workflows"
files = list(WF.glob("*.yml")) + list((ROOT / ".github/actions").rglob("*.yml")) + [p for p in (ROOT / "templates").rglob("*") if p.is_file()]
used_vars = {v for p in files for v in re.findall(r"\bvars\.([A-Za-z0-9_]+)", p.read_text(errors="ignore"))}
var_entries = {e["apply"]["name"]: e for e in entries if e["apply"]["via"] == "variable"}
expect("found the kit's repo variables", {"AGENTKIT_WIP", "AUTO_MERGE"} <= used_vars, used_vars)
expect("every repo variable is in the registry", used_vars <= set(var_entries), sorted(used_vars - set(var_entries)))

# coverage: every input of every reusable workflow the caller template uses (or the variable it is passed from)
caller = ROOT / "templates/.github/workflows/agentkit.yml"
jobs = caller_jobs(caller)
expect("found the caller's jobs", {"dispatch", "implement", "review", "digest", "retro"} <= set(jobs), jobs)
missing = []
for job, (wf, passed) in jobs.items():
    for name, default in call_inputs(WF / wf).items():
        via_var = re.search(r"\bvars\.([A-Za-z0-9_]+)", passed.get(name, ""))
        if via_var:
            if via_var.group(1) not in var_entries:
                missing.append(f"{job}.{name} (vars.{via_var.group(1)})")
            continue
        hit = [e for e in entries if e["apply"]["via"] == "caller" and e["apply"].get("input") == name and job in jobs_of(e)]
        if not hit:
            missing.append(f"{job}.{name}")
        elif default is not None and str(hit[0]["default"]).lower() != default.lower():
            missing.append(f"{job}.{name}: registry default {hit[0]['default']!r}, workflow default {default!r}")
expect("every caller input is in the registry with the workflow's default", not missing, missing)
caller_jobs_named = {j for e in entries if e["apply"]["via"] == "caller" for j in jobs_of(e)}
expect("caller entries name real jobs", caller_jobs_named <= set(jobs), caller_jobs_named - set(jobs))

# coverage: the caller's crons
crons = re.findall(r'^\s*- cron: "([^"]+)"', caller.read_text(), re.M)
cron_defaults = {e["default"] for e in entries if e["type"] == "cron"}
expect("found the caller's crons", len(crons) >= 3, crons)
expect("every caller cron is a registry default", set(crons) <= cron_defaults, set(crons) - cron_defaults)

# coverage: env vars the bot reads
bot_env = set()
for p in (ROOT / "bot").glob("*.py"):
    t = p.read_text()
    bot_env |= set(re.findall(r'os\.(?:environ(?:\.get)?\s*[\[(]|getenv\()\s*"([A-Z0-9_]+)"', t))
    bot_env |= set(re.findall(r'\bsecret\(\s*"([A-Z0-9_]+)"', t))
server = {e["apply"]["name"] for e in entries if e["apply"]["via"] == "server"}
expect("found the bot's env vars", {"AGENTKIT_REPOS", "SLACK_BOT_TOKEN"} <= bot_env, bot_env)
expect("every bot env var is in the registry", bot_env - NOT_SETTINGS <= server, sorted(bot_env - NOT_SETTINGS - server))
expect("no secret is a setting", not (NOT_SETTINGS & (server | set(var_entries))))

# the owner's decisions
expect("nudges: at most twice a day", by_key["nudges-per-day"]["validate"].get("max") == 2 and by_key["nudges-per-day"]["default"] == 2)
expect("nudge hours default 09-20", by_key["nudge-hours"]["default"] == "09-20")

# validate() by type
V = settings.validate
cases = [
    ({"type": "bool", "validate": {}}, [True, False, "true", "false"], [1, "yes", ""]),
    ({"type": "int", "validate": {"min": 1, "max": 10}}, [1, 10, "3"], [0, 11, "x", 2.5, True, ""]),
    ({"type": "string", "validate": {"regex": "[a-z]+"}}, ["abc"], ["ABC", "abc1", 3]),
    ({"type": "string", "validate": {"json": True}}, ["", '[{"name": "a"}]'], ["[", "{}"]),
    ({"type": "enum", "validate": {"enum": ["on", "off"]}}, ["on", "off"], ["maybe", ""]),
    ({"type": "hours", "validate": {}}, ["09-20", "00-24", "22-06"], ["9-20", "09-09", "09-25", "nine"]),
    ({"type": "timezone", "validate": {}}, ["UTC", "Europe/Berlin", "America/New_York"], ["Mars/Base", "../etc", ""]),
    ({"type": "cron", "validate": {}}, ["0 7 * * *", "*/30 * * * *", "0 8 * * 1-5"], ["0 7 * *", "every day", "0 7 * * * *"]),
]
for entry, good, bad in cases:
    entry = dict(entry, key="t")
    for v in good:
        expect(f"{entry['type']} accepts {v!r}", V(entry, v) is None, V(entry, v))
    for v in bad:
        expect(f"{entry['type']} refuses {v!r}", isinstance(V(entry, v), str))


# CLI
def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


r = cli("validate", "nudges-per-day", "2")
expect("cli: valid value exits 0", r.returncode == 0, r.stderr)
r = cli("validate", "nudges-per-day", "3")
expect("cli: invalid value exits 1 with a reason", r.returncode == 1 and "at most 2" in r.stdout + r.stderr, r.stdout + r.stderr)
r = cli("validate", "no-such-thing", "1")
expect("cli: unknown key exits 1", r.returncode == 1 and "not a setting" in r.stdout + r.stderr, r.stdout + r.stderr)
r = cli("show", "merge")
expect("cli: show finds by words", r.returncode == 0 and "auto-merge" in r.stdout and "gh variable set AUTO_MERGE" in r.stdout, r.stdout)
r = cli("show")
expect("cli: show lists everything", r.returncode == 0 and all(k in r.stdout for k in by_key), r.stdout[:500])
r = cli("show", "zzzz-nothing")
expect("cli: show with no match says so", r.returncode == 1 and "no setting" in r.stdout, r.stdout)
r = cli("bogus")
expect("cli: bad usage exits 2", r.returncode == 2)

sys.exit(1 if fails else 0)
