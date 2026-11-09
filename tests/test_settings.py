"""config/settings.json and scripts/settings.py: every knob the kit reads is in the registry, and validate() holds."""
import re, subprocess, sys, tempfile
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
# a variable's fallback in the workflows (`vars.X || 'D'`) is the registry's default
drift = sorted({f"{v}: workflow {d!r}, registry {var_entries[v]['default']!r}"
                for p in files for v, q, n in re.findall(r"\bvars\.([A-Za-z0-9_]+) \|\| (?:'([^']*)'|(\d+)\b)", p.read_text(errors="ignore"))
                for d in [q or n]
                if v in var_entries and str(var_entries[v]["default"]).lower() != d.lower() and var_entries[v]["key"] != "integration-timeout"})
expect("a variable's workflow fallback is its registry default", not drift, drift)

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

# asking from Slack: the model's answer becomes a card; only registry values that pass validate() become buttons
import json  # noqa: E402

expect("answer: plain JSON", settings.parse_answer('{"match": "wip", "answer": "a", "options": [3]}')["match"] == "wip")
expect("answer: JSON in a fence after prose",
       settings.parse_answer('Sure.\n```json\n{"match": null, "answer": "no"}\n```')["answer"] == "no")
expect("answer: garbage is empty", settings.parse_answer("no idea") == {} and settings.parse_answer("[1, 2]") == {})


def elements(msg):
    return [e for b in msg["blocks"] if b["type"] == "actions" for e in b["elements"]]


def all_text(msg):
    return json.dumps(msg)


q = "Can I change the working hours? " * 5
msg = settings.card(entries, "o/r", q, json.dumps(
    {"match": "nudge-hours", "answer": "Yes: nudges. For which hours? " * 10, "options": ["08-18", "25-99", "10-19", "09-20", "07-16"]}))
head = msg["blocks"][0]["text"]["text"]
title, answer = head.split("\n")
expect("card: the title is the question, clipped to 80", title.startswith("*Can I change") and len(title.strip("*")) <= 80, title)
expect("card: the answer is at most 160", len(answer) <= 160, answer)
els = elements(msg)
buttons = [e for e in els if e["type"] == "button"]
expect("card: only valid options, at most 3, then Other…",
       [b["text"]["text"] for b in buttons] == ["08-18", "10-19", "09-20", "Other…"], buttons)
expect("card: a button's value names repo, key and value", buttons[0]["value"] == "set|o/r|nudge-hours|08-18", buttons[0])
expect("card: Other… carries no value yet", buttons[-1]["value"] == "set|o/r|nudge-hours|" and buttons[-1]["action_id"] == "setting_other")
expect("card: action ids are unique", len({e["action_id"] for e in els}) == len(els), els)
sel = [e for e in els if e["type"] == "external_select"]
acts = next(b for b in msg["blocks"] if b["type"] == "actions")
expect("card: hours come with a timezone search over every zone", len(sel) == 1 and sel[0]["action_id"] == "setting_zone"
       and acts.get("block_id") == "zone|o/r|timezone", (sel, acts.get("block_id")))
expect("card: every value within Slack's 2000", all(len(e.get("value", "")) <= 2000 for e in els))

msg = settings.card(entries, "o/r", "how many tasks at once?", '{"match": "wip", "answer": "Yes.", "options": ["lots"]}')
expect("card: no valid option from the model: the registry's own",
       [b["text"]["text"] for b in elements(msg)] == ["1", "2", "3", "Other…"], elements(msg))
expect("card: a project setting says it needs admin", "admin" in all_text(msg), all_text(msg))
msg = settings.card(entries, "o/r", "merge by itself?", '{"match": "auto-merge", "answer": "Yes.", "options": [true]}')
expect("card: a bool option is a true/false button", [b["value"] for b in elements(msg)] == ["set|o/r|auto-merge|true"], elements(msg))

msg = settings.card(entries, "o/r", "can it paint my house?", '{"match": "paint", "answer": "Sure!", "options": ["red"]}')
expect("card: an unknown key is no match", "Not something the kit can change yet." in msg["text"] and "Sure" not in all_text(msg), msg)
fb = elements(msg)
expect("card: no match offers a feature request with the question",
       len(fb) == 1 and fb[0]["action_id"] == "setting_feature" and fb[0]["value"] == "feature|o/r|can it paint my house?", fb)
expect("card: no match points to the list", "what can you change?" in all_text(msg), msg)
msg = settings.card(entries, "o/r", "what can you change?", '{"match": "list", "answer": "x", "options": []}')
expect("card: list names the person's and the project's settings, not advanced ones",
       "Nudge hours" in all_text(msg) and "Claude model" in all_text(msg) and "Repos the Slack bot serves" in all_text(msg)
       and not any(t["title"] in all_text(msg) for t in entries if t.get("advanced")), msg)
expect("card: list has no buttons", not elements(msg), elements(msg))
msg = settings.card(entries, "o/r", "x\n" * 300, "")
expect("card: the feature request title is one line of at most 256",
       len(elements(msg)[0]["value"].split("|", 2)[2]) <= 256 and "\n" not in elements(msg)[0]["value"], elements(msg))

msg = settings.card(entries, "o/r", "which repos?", '{"match": "bot-repos", "answer": "The bot serves a list."}')
expect("card: a server setting only explains", not elements(msg) and "restart the bot" in all_text(msg), msg)
msg = settings.card(entries, "o/r", "digest later?", '{"match": "digest-cron", "answer": "Yes.", "options": ["0 9 * * *"]}')
expect("card: a cron goes to Claude Code", not elements(msg) and "/agentkit:settings" in all_text(msg), msg)
msg = settings.card(entries, "o/r", "a <b>", '{"match": "wip", "answer": "<!channel> & co"}')
expect("card: question and answer are escaped", "&lt;!channel&gt; &amp; co" in all_text(msg) and "<b>" not in all_text(msg))

# what changed, and Undo
c = settings.changed(by_key["nudge-hours"], "o/r", "08-18", "09-20")
expect("changed: says what and what it was", c["text"] == "Nudge hours: 08-18 (was 09-20).", c["text"])
undo = elements(c)
expect("changed: Undo puts the old value back", len(undo) == 1 and undo[0]["value"] == "set|o/r|nudge-hours|09-20"
       and undo[0]["action_id"] == "setting_undo", undo)
c = settings.changed(by_key["wip"], "o/r", "3", None)
expect("changed: a project setting names the repo; no Undo without an old value",
       "o/r" in c["text"] and "not set" in c["text"] and not elements(c), c)
expect("typed: ints and bools for prefs", settings.typed(by_key["nudges-per-day"], "1") == 1
       and settings.typed(by_key["auto-merge"], "true") is True and settings.typed(by_key["nudge-hours"], "08-18") == "08-18")

# the caller PR: one `with:` input, nothing else
fixture = (ROOT / "tests/fixture-callers/current.yml").read_text()
out = settings.set_caller_input(fixture, by_key["debt-every"], "4")
diff = [l for l in out.splitlines() if l not in fixture.splitlines()]
expect("caller: an input added under the job's with:", diff == ["      debt-every: 4"]
       and out.split("\n  dispatch:\n")[1].split("\n  triage:")[0].count("    with:") == 1, diff)
again = settings.set_caller_input(out, by_key["debt-every"], "6")
expect("caller: an input there is replaced", "      debt-every: 6" in again and "debt-every: 4" not in again, again)
out = settings.set_caller_input(fixture, by_key["model"], "claude-sonnet-5-5")
jobs_n = len(jobs_of(by_key["model"]))
expect("caller: every job of the entry", out.count('      model: "claude-sonnet-5-5"') == jobs_n
       and len(out.splitlines()) == len(fixture.splitlines()) + jobs_n, out)
out = settings.set_caller_input("jobs:\n  digest:\n    uses: o/k/.github/workflows/digest.yml@v1\n    secrets: {}\n",
                                by_key["digest-statuses"], "a|b")
expect("caller: a with: made where missing", out == 'jobs:\n  digest:\n    uses: o/k/.github/workflows/digest.yml@v1\n'
       '    with:\n      statuses: "a|b"\n    secrets: {}\n', out)
for entry, v, why in [(by_key["plugins"], "x@y", "multi-line"), (by_key["retro-category"], "${{ secrets.X }}", "expression"),
                      (by_key["digest-cron"], "0 9 * * *", "cron"), (by_key["wip"], "3", "a variable")]:
    try:
        settings.set_caller_input(fixture, entry, v)
        expect(f"caller: refuses a {why}", False)
    except ValueError:
        expect(f"caller: refuses a {why}", True)
try:
    settings.set_caller_input("jobs:\n  other:\n    uses: x\n", by_key["debt-every"], "4")
    expect("caller: no such job is an error", False)
except ValueError:
    expect("caller: no such job is an error", True)

r = subprocess.run([sys.executable, str(SCRIPT), "card", "o/r"], input=json.dumps(
    {"question": "nudge hours?", "result": '{"match": "nudge-hours", "answer": "Yes."}'}), capture_output=True, text=True)
expect("cli: card prints the Slack message", r.returncode == 0 and json.loads(r.stdout)["blocks"][0]["type"] == "section", r.stderr)
r = subprocess.run([sys.executable, str(SCRIPT), "prompt"], input="Can I change the working hours?", capture_output=True, text=True)
expect("cli: the prompt holds the question and the registry, not how to apply",
       r.returncode == 0 and "Can I change the working hours?" in r.stdout and '"nudge-hours"' in r.stdout
       and "AGENTKIT_WIP" not in r.stdout, r.stdout[:300])
with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "agentkit.yml"
    f.write_text(fixture)
    r = cli("caller", "max-rounds", "5", str(f))
    expect("cli: caller edits the file", r.returncode == 0 and "      max-rounds: 5" in f.read_text(), r.stdout + r.stderr)
    r = cli("caller", "max-rounds", "99", str(f))
    expect("cli: caller refuses an invalid value", r.returncode == 1 and "at most 10" in r.stdout + r.stderr, r.stdout + r.stderr)
    r = cli("caller", "plugins", "x@y", str(f))
    expect("cli: caller refuses what it cannot edit", r.returncode == 1, r.stdout + r.stderr)

sys.exit(1 if fails else 0)
