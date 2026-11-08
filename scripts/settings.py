#!/usr/bin/env python3
"""The settings registry (config/settings.json): every knob the kit has, with its options and rule. Python 3.9+, stdlib only.

  settings.py validate <key> <value>   exit 0 when the value passes the entry's rule, else 1 and the reason
  settings.py show [query]             the entries (all, or those whose key, title, description or variable
                                       contains the query): title, default, options and how to change it

The bot imports load() and validate(entry, value); validate returns None when the value is fine, else the reason.
Values may come as JSON types or as strings (repo variables and the command line are strings).
"""
import json
import re
import sys
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent.parent / "config/settings.json"
TYPES = ("bool", "int", "string", "enum", "hours", "timezone", "cron")
CRON_FIELD = re.compile(r"^(\*|\d+(-\d+)?)(/\d+)?(,(\*|\d+(-\d+)?)(/\d+)?)*$")


def load(path=REGISTRY):
    return json.loads(Path(path).read_text())


def find(entries, key):
    return next((e for e in entries if e["key"] == key), None)


def validate(entry, value):
    t, rule = entry["type"], entry.get("validate", {})
    if t == "bool":
        if not isinstance(value, (bool, str)) or value not in (True, False, "true", "false"):
            return "must be true or false"
    elif t == "int":
        if isinstance(value, bool) or not (isinstance(value, int) or (isinstance(value, str) and re.fullmatch(r"\d+", value))):
            return "must be a whole number"
        n = int(value)
        if "min" in rule and n < rule["min"]:
            return f"must be at least {rule['min']}"
        if "max" in rule and n > rule["max"]:
            return f"must be at most {rule['max']}"
    elif t == "hours":
        m = re.fullmatch(r"(\d\d)-(\d\d)", value) if isinstance(value, str) else None
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 24 or m.group(1) == m.group(2):
            return "must be HH-HH, for example 09-20"
    elif t == "timezone":
        try:
            import zoneinfo
            zoneinfo.ZoneInfo(value)
        except Exception:
            return "must be a timezone name, for example Europe/Berlin or UTC"
    elif t == "cron":
        fields = value.split() if isinstance(value, str) else []
        if len(fields) != 5 or not all(CRON_FIELD.match(f) for f in fields):
            return "must be a 5-field cron line, for example 0 7 * * *"
    elif not isinstance(value, str):
        return "must be text"
    if "enum" in rule and str(value) not in [str(o) for o in rule["enum"]]:
        return "must be one of " + ", ".join(map(str, rule["enum"]))
    if "regex" in rule and not re.fullmatch(rule["regex"], str(value)):
        return rule.get("hint", "has the wrong form")
    if rule.get("json") and value != "":
        try:
            ok = isinstance(json.loads(value), list)
        except ValueError:
            ok = False
        if not ok:
            return "must be a JSON list (or empty)"
    return None


def how(e):
    a = e["apply"]
    if a["via"] == "prefs":
        return "your own setting: ask the bot (applies at once)"
    if a["via"] == "variable":
        return f"gh variable set {a['name']} --body <value>"
    if a["via"] == "server":
        return f"set {a['name']} in the bot's environment on the server, then restart the bot"
    jobs = a["job"] if isinstance(a["job"], list) else [a["job"]]
    where = f"the `{a['input']}:` input under `with:`" if "input" in a else "the cron line under `schedule:` and the job's `if:`"
    return f"edit {where} of the {'/'.join(jobs)} job in .github/workflows/agentkit.yml (a PR)"


def show(entries, query=""):
    q = query.lower()
    hits = [e for e in entries
            if q in " ".join([e["key"], e["title"], e["description"], e["apply"].get("name", ""), e["apply"].get("input", "")]).lower()]
    def text(v):
        return (v or "(empty)").replace("\n", "\\n") if isinstance(v, str) else json.dumps(v)

    for e in hits:
        opts = [text(o) for o in e["options"]] + (["other…"] if e.get("other") else [])
        print(f"{e['key']} ({e['scope']}{', advanced' if e.get('advanced') else ''}): {e['title']}")
        print(f"  {e['description']}")
        print(f"  default: {text(e['default'])}" + (f" · options: {', '.join(opts)}" if opts else ""))
        print(f"  change: {how(e)}")
    if not hits:
        print(f"no setting matches {query!r}")
    return 0 if hits else 1


def main(argv):
    entries = load()
    if len(argv) == 3 and argv[0] == "validate":
        e = find(entries, argv[1])
        err = validate(e, argv[2]) if e else f"{argv[1]} is not a setting (settings.py show lists them)"
        print(err or "ok")
        return 1 if err else 0
    if 1 <= len(argv) <= 2 and argv[0] == "show":
        return show(entries, argv[1] if len(argv) == 2 else "")
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
