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
    expect(f"{k}: in a known group", e.get("group") in {g for g, _ in settings.GROUPS}, e.get("group"))
    expect(f"{k}: a short summary unless advanced", e.get("advanced") or 0 < len(e.get("summary", "")) <= 60, e.get("summary"))

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


def core_like(v):
    kind, repo, raw = v.split("|", 2)
    return repo, json.loads(raw)


def all_text(msg):
    return json.dumps(msg, ensure_ascii=False)


fixture = (ROOT / "tests/fixture-callers/current.yml").read_text()
q = "Can I change the working hours? " * 5
msg = settings.card(entries, "o/r", q, json.dumps(
    {"match": "nudge-hours", "answer": "Yes: nudges.", "options": ["08-18", "25-99", "10-19", "09-20", "07-16"]}),
    {"now": {"nudge-hours": "10-19"}})
head = msg["blocks"][0]["text"]["text"]
expect("card: the setting's title, what it does and its value now, not the model's words",
       head.startswith("*Nudge hours*\nThe hours") and "*Now:* `10-19` · default `09-20`" in head
       and "Yes: nudges" not in all_text(msg) and "Can I change" not in all_text(msg), head)
els = elements(msg)
buttons = [e for e in els if e["type"] == "button"]
expect("card: only valid options, at most 3, the current one ticked, then Other…",
       [b["text"]["text"] for b in buttons] == ["08-18", "10-19 ✓", "09-20", "Other…"], buttons)
expect("card: a button's value names repo, key and value", buttons[0]["value"] == "set|o/r|nudge-hours|08-18", buttons[0])
expect("card: Other… carries no value yet", buttons[-1]["value"] == "set|o/r|nudge-hours|" and buttons[-1]["action_id"] == "setting_other")
expect("card: action ids are unique", len({e["action_id"] for e in els}) == len(els), els)
sel = [e for e in els if e["type"] == "external_select"]
acts = next(b for b in msg["blocks"] if b["type"] == "actions")
expect("card: hours come with a timezone search over every zone", len(sel) == 1 and sel[0]["action_id"] == "setting_zone"
       and acts.get("block_id") == "zone|o/r|timezone", (sel, acts.get("block_id")))
expect("card: every value within Slack's 2000", all(len(e.get("value", "")) <= 2000 for e in els))
expect("card: a personal setting says it is just yours", "Just for you" in all_text(msg), all_text(msg))
msg = settings.card(entries, "o/r", "hours?", '{"match": "nudge-hours"}')
expect("card: without the bot's values, the default (not a guessed value now)",
       "*Default:* `09-20`" in msg["blocks"][0]["text"]["text"] and "✓" not in all_text(msg), msg["blocks"][0])
msg = settings.card(entries, "o/r", "hours?", '{"match": "nudge-hours"}', {"now": {}})
expect("card: a personal setting not set is its default now", "*Now:* `09-20` (the default)" in all_text(msg), all_text(msg))

msg = settings.card(entries, "o/r", "how many tasks at once?", '{"match": "wip", "options": ["lots"]}', {"vars": {"AGENTKIT_WIP": "3"}})
expect("card: no valid option from the model: the registry's own; a variable's value now",
       [b["text"]["text"] for b in elements(msg)] == ["1", "2", "3 ✓", "Other…"] and "*Now:* `3`" in all_text(msg), elements(msg))
expect("card: a project setting says it needs admin and links the repo",
       "admin" in all_text(msg) and "<https://github.com/o/r|r>" in all_text(msg), all_text(msg))
msg = settings.card(entries, "o/r", "merge by itself?", '{"match": "auto-merge", "options": [true]}')
expect("card: a bool option is a true/false button", [b["value"] for b in elements(msg)] == ["set|o/r|auto-merge|true"], elements(msg))
msg = settings.card(entries, "o/r", "channel?", '{"match": "card-channel"}', {"vars": {}})
expect("card: an empty default reads not set", "*Now:* not set" in all_text(msg) and "default" not in msg["blocks"][0]["text"]["text"],
       msg["blocks"][0])

cv = settings.caller_value
expect("caller value: an input there", cv("jobs:\n  dispatch:\n    uses: x\n    with:\n      debt-every: 6  # less\n", by_key["debt-every"]) == 6)
expect("caller value: quoted text", cv('jobs:\n  retro:\n    uses: x\n    with:\n      category: "Retros"\n', by_key["retro-category"]) == "Retros")
expect("caller value: not set is the default", cv("jobs:\n  dispatch:\n    uses: x\n    with:\n      wip: 2\n", by_key["debt-every"]) == 4)
expect("caller value: commented out is not set", cv("jobs:\n  dispatch:\n    uses: x\n    with:\n      # debt-every: 9\n", by_key["debt-every"]) == 4)
expect("caller value: under secrets is not an input", cv("jobs:\n  dispatch:\n    uses: x\n    secrets:\n      debt-every: 9\n", by_key["debt-every"]) == 4)
expect("caller value: an expression is not known", cv("jobs:\n  dispatch:\n    with:\n      debt-every: ${{ vars.X }}\n", by_key["debt-every"]) is None)
expect("caller value: the template's own", cv(fixture, by_key["debt-every"]) == 4)
msg = settings.card(entries, "o/r", "debt?", '{"match": "debt-every"}', {"caller": "jobs:\n  dispatch:\n    with:\n      debt-every: 3\n"})
expect("card: a caller input's value now", "*Now:* `3` · default `4`" in all_text(msg) and "3 ✓" in all_text(msg), all_text(msg))

msg = settings.card(entries, "o/r", "can it paint my house?", '{"match": "paint", "answer": "Sure!", "options": ["red"]}')
expect("card: an unknown key is no match", msg["text"] == settings.NO_MATCH and "Sure" not in all_text(msg), msg)
fb = elements(msg)
expect("card: no match offers a feature request with the question",
       len(fb) == 1 and fb[0]["action_id"] == "setting_feature" and fb[0]["value"] == "feature|o/r|can it paint my house?", fb)
expect("card: no match points to the list", "what can you change?" in all_text(msg), msg)

msg = settings.card(entries, "o/r", "what can you change?", '{"match": "list", "options": []}')
sections = [b["text"]["text"] for b in msg["blocks"] if b["type"] == "section"]
expect("list: one section per group, each setting on its own line with what it does",
       len(sections) == len({e["group"] for e in entries if not e.get("advanced")})
       and "• *Nudge hours*: The hours the bot may DM you, like 09-20" in sections[0]
       and all(f"• *{e['title']}*: " in all_text(msg) for e in entries if not e.get("advanced"))
       and not any(f"*{e['title']}*" in all_text(msg) for e in entries if e.get("advanced")), sections)
expect("list: every section within Slack's 3000", all(len(t) <= 3000 for t in sections), [len(t) for t in sections])
menu = elements(msg)
expect("list: a menu of every setting, by group, valued pick|repo|key",
       len(menu) == 1 and menu[0]["action_id"] == "setting_pick"
       and sorted(o["value"] for g in menu[0]["option_groups"] for o in g["options"]) == sorted(f"pick|o/r|{k}" for k in by_key)
       and all(len(o["text"]["text"]) <= 75 for g in menu[0]["option_groups"] for o in g["options"])
       and sum(len(g["options"]) for g in menu[0]["option_groups"]) <= 100, menu)
expect("list: within Slack's 50 blocks", len(msg["blocks"]) <= 50)
msg = settings.card(entries, "o/r", "x\n" * 300, "")
expect("card: the feature request title is one line of at most 256",
       len(elements(msg)[0]["value"].split("|", 2)[2]) <= 256 and "\n" not in elements(msg)[0]["value"], elements(msg))

msg = settings.card(entries, "o/r", "which repos?", '{"match": "bot-repos"}', {"now": {"bot-repos": "o/a,o/b"}})
expect("card: a server setting only explains, with its value now",
       not elements(msg) and "restart the bot" in all_text(msg) and "AGENTKIT_REPOS" in all_text(msg)
       and "*Now:* `o/a,o/b`" in all_text(msg), msg)
# schedules: in words, their value now from the caller, and a click that changes them (the line and the job's if:)
for c, w in [("0 10 * * 4", "Thursdays at 10:00"), ("0 7 * * *", "Every day at 07:00"), ("0 7 * * 1-5", "Weekdays at 07:00"),
             ("30 8 * * 1,4", "Mondays and Thursdays at 08:30"), ("*/30 * * * *", "Every 30 minutes"), ("0 * * * *", "Every hour"),
             ("0 9 1 * *", "0 9 1 * *"), ("bad", "bad")]:
    expect(f"cron words: {c!r}", settings.cron_words(c) == w, settings.cron_words(c))
expect("caller crons: the template's three", settings.caller_crons(fixture) == ["*/30 * * * *", "0 7 * * *", "0 8 * * 1"],
       settings.caller_crons(fixture))
expect("caller cron: by the job's if:", settings.caller_cron(fixture, by_key["retro-cron"]) == "0 8 * * 1"
       and settings.caller_cron(fixture, by_key["digest-cron"]) == "0 7 * * *")
expect("caller cron: the dispatcher's is the one no job names", settings.caller_cron(fixture, by_key["dispatch-cron"]) == "*/30 * * * *")
expect("caller zone: UTC without one", settings.caller_zone(fixture) == "UTC")
out = settings.edit_caller(fixture, by_key["retro-cron"], "0 10 * * 4")
diff = [(a, b) for a, b in zip(fixture.splitlines(), out.splitlines()) if a != b]
expect("schedule edit: the cron line and the retro's if:, nothing else",
       len(out.splitlines()) == len(fixture.splitlines()) and len(diff) == 2
       and '- cron: "0 10 * * 4"  # retro: Thursdays at 10:00' in out and "github.event.schedule == '0 10 * * 4'" in out
       and "'0 8 * * 1'" not in out and settings.caller_cron(out, by_key["retro-cron"]) == "0 10 * * 4", diff)
try:
    settings.edit_caller(fixture, by_key["retro-cron"], "0 7 * * *"); expect("schedule edit: refuses another job's time", False)
except ValueError as e:
    expect("schedule edit: refuses another job's time", "another schedule" in str(e), str(e))
out = settings.edit_caller(fixture, by_key["project-timezone"], "Asia/Jerusalem")
expect("timezone edit: under every cron line", out.count('      timezone: "Asia/Jerusalem"') == 3
       and settings.caller_zone(out) == "Asia/Jerusalem" and len(out.splitlines()) == len(fixture.splitlines()) + 3, out[:400])
again = settings.edit_caller(out, by_key["project-timezone"], "Europe/London")
expect("timezone edit: replaces, never stacks", again.count("timezone:") == 3 and "Asia/Jerusalem" not in again)
both = settings.edit_caller(settings.edit_caller(fixture, by_key["project-timezone"], "Asia/Jerusalem"), by_key["retro-cron"], "0 10 * * 4")
expect("timezone and schedule edits together", settings.caller_cron(both, by_key["retro-cron"]) == "0 10 * * 4"
       and both.count("timezone:") == 3, both[:400])
r = subprocess.run([sys.executable, str(SCRIPT), "card", "o/r"], input=json.dumps({"question": "retro thursday 10?",
                   "result": '{"matches": [{"match": "retro-cron", "options": ["0 10 * * 4"]}]}'}), capture_output=True, text=True)
expect("cli: card reads its stdin", r.returncode == 0 and "Thursdays at 10:00" in r.stdout, r.stdout + r.stderr)
msg = settings.card(entries, "o/r", "retro thursday 10?", '{"matches": [{"match": "retro-cron", "options": ["0 10 * * 4"]}]}',
                    {"caller": settings.edit_caller(fixture, by_key["project-timezone"], "Asia/Jerusalem")})
expect("card: a schedule in words, in the project's timezone, with its new time as a button",
       "*Now:* Mondays at 08:00 (Asia/Jerusalem) · `0 8 * * 1` (the default)" in all_text(msg)
       and [b["text"]["text"] for b in elements(msg)][:2] == ["Thursdays at 10:00", "Other…"]
       and elements(msg)[0]["value"] == "set|o/r|retro-cron|0 10 * * 4" and "Asia/Jerusalem, the project's timezone" in all_text(msg), msg)
expect("validate: the person's timezone may be not set (the project's)", settings.validate(by_key["timezone"], "") is None
       and settings.validate(by_key["project-timezone"], "") is not None)
msg = settings.card(entries, "o/r", "my tz?", '{"match": "timezone"}', {"now": {}})
expect("card: the person's timezone not set is the project's", "*Now:* the project's timezone" in all_text(msg), all_text(msg))

# several settings in one answer: one message, an Apply all for the values asked for
msg = settings.card(entries, "o/r", "timezone israel, retro thu 10", json.dumps({"matches": [
    {"match": "project-timezone", "options": ["Asia/Jerusalem"]}, {"match": "retro-cron", "options": ["0 10 * * 4"]},
    {"match": "retro-cron", "options": []}, {"match": "paint", "options": ["red"]}, {"match": "bot-repos", "options": ["x/y"]}]}))
sections = [b["text"]["text"] for b in msg["blocks"] if b["type"] == "section"]
apply_btn = [e for e in elements(msg) if e["action_id"] == "setting_all"]
expect("several: each known setting once, in order", [t.split("\n")[0] for t in sections[:3]]
       == ["*Project timezone*", "*Retro time*", "*Repos the Slack bot serves*"], sections)
expect("several: Apply all with the asked values, not the server one",
       len(apply_btn) == 1 and core_like(apply_btn[0]["value"]) == ("o/r", [["project-timezone", "Asia/Jerusalem"], ["retro-cron", "0 10 * * 4"]])
       and "Project timezone → `Asia/Jerusalem`; Retro time → Thursdays at 10:00" in all_text(msg), apply_btn)
expect("several: within Slack's limits", len(msg["blocks"]) <= 50 and all(len(t) <= 3000 for t in sections))
expect("several: no repo menu on a several-settings answer", not any(e["action_id"] == "setting_repo" for e in elements(msg)))
msg = settings.card(entries, "o/r", "x", json.dumps({"matches": [{"match": "wip", "options": []}, {"match": "nudge", "options": []}]}))
expect("several: no Apply all without asked values", not any(e["action_id"] == "setting_all" for e in elements(msg))
       and msg["blocks"][-1]["type"] != "divider", msg["blocks"][-1])
# the repo menu on a project card, when the bot serves more than one repo
msg = settings.card(entries, "o/r", "wip?", '{"match": "wip"}', {"repos": ["o/r", "o/s"]})
menu = [e for e in elements(msg) if e["action_id"] == "setting_repo"]
expect("repo menu: on a project card, the current repo picked", len(menu) == 1
       and [o["value"] for o in menu[0]["options"]] == ["repo|o/r|wip", "repo|o/s|wip"]
       and menu[0]["initial_option"]["value"] == "repo|o/r|wip", menu)
expect("repo menu: not for one repo, nor a personal setting",
       not any(e["action_id"] == "setting_repo" for e in elements(settings.card(entries, "o/r", "w", '{"match": "wip"}', {"repos": ["o/r"]})))
       and not any(e["action_id"] == "setting_repo" for e in elements(settings.card(entries, "o/r", "n", '{"match": "nudge"}', {"repos": ["o/r", "o/s"]}))))
expect("prompt: asks for several settings and values in the entry's form",
       '"matches"' in settings.prompt(entries, "q") and "Asia/Jerusalem" in settings.prompt(entries, "q"))
msg = settings.card(entries, "o/r", "a <b>", '{"match": "wip"}', {"vars": {"AGENTKIT_WIP": "<!channel> & co"}})
expect("card: values are escaped", "&lt;!channel&gt; &amp; co" in all_text(msg) and "<!channel>" not in all_text(msg))
expect("prompt: the model words nothing the person sees", '"answer"' not in settings.prompt(entries, "q"))

# the answer replaces the bot's placeholder; a failed replace (or none named) posts
import card as slack_client  # noqa: E402
made, real = [], slack_client.slack
def fake(method, payload):
    made.append((method, payload))
    if method == "chat.update" and payload["ts"] == "bad":
        raise SystemExit("card.py: Slack said message_not_found")
    return {"ts": "9.9"}
slack_client.slack = fake
settings.dm("U1", {"text": "t"}, "D1", "1.2")
expect("dm: replaces the placeholder, blocks and all", made == [("chat.update", {"channel": "D1", "ts": "1.2", "blocks": [], "text": "t"})], made)
made.clear(); settings.dm("U1", {"text": "t"}, "D1", "bad")
expect("dm: a failed replace posts instead", [m for m, _ in made] == ["chat.update", "chat.postMessage"] and made[1][1]["channel"] == "U1", made)
made.clear(); settings.dm("U1", {"text": "t"})
expect("dm: no placeholder: posts", [m for m, _ in made] == ["chat.postMessage"], made)
slack_client.slack = real

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
