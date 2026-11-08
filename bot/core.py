"""The bot's decisions, apart from Slack: who a click is, whether they may act, what goes to GitHub, what the App Home
board shows and when a person gets a nudge. Python 3.9+, stdlib only (the board also uses the kit's
plugins/agentkit/scripts/board.py); bot/app.py is the thin Slack and HTTP layer around it."""
import json
import os
import re
import tempfile
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

LOGIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
REPO = re.compile(r"^[A-Za-z0-9-]+/(?!\.\.?$)[A-Za-z0-9._-]+$")
WRITE = {"write", "maintain", "admin"}
EVENT = "agentkit-slack-reply"


def load_users(path):
    """users.json: {"<slack user id>": "<github login>"}. A bad entry is an error, not skipped: a typo must not
    silently map a person to someone else."""
    users = json.load(open(path))
    for slack_id, login in users.items():
        if not (isinstance(login, str) and LOGIN.match(login)):
            raise ValueError(f"users.json: bad login for {slack_id}")
    return users


def authorize(slack_id, users, permission_of):
    """(login, None) when this Slack user is mapped and has write access now, else (None, reason for the person).
    `permission_of(login)` asks GitHub; it is called on every interaction, never cached."""
    login = users.get(slack_id)
    if login is None:
        return None, "Your Slack account is not linked to a GitHub login. Ask the owner to add you."
    if permission_of(login) not in WRITE:
        return None, f"{login} no longer has write access to this repository."
    return login, None


def parse_value(value):
    """`<owner/repo>#<n>|<text>` from a card button -> (repo, n, text)."""
    ref, _, text = value.partition("|")
    repo, _, n = ref.partition("#")
    if not (REPO.match(repo) and n.isdigit() and int(n) > 0):
        raise ValueError("bad button value")
    return repo, int(n), text


def dispatch(repo, n, text, login):
    """The repository_dispatch body: the workflow checks the login again and maps the text with reply.py."""
    return repo, {"event_type": EVENT, "client_payload": {"issue": n, "text": text, "login": login}}


# --- App Home: the board -------------------------------------------------------------------------------------------

SECTIONS = (("waiting", "Waiting on you"), ("in_progress", "In progress"), ("next", "Next up"), ("done", "Done this week"))
# (waiting items, items in each other section) per repo, tried in order until the view fits Slack's 100 blocks
CAPS = ((8, 5), (5, 4), (4, 3), (3, 2), (2, 1), (1, 1), (1, 0))
VIEW_MAX = 100
QUERY = {"waiting": "is:issue is:open label:action:required",
         "in_progress": "is:issue is:open label:status:in-progress,status:review",
         "next": "is:issue is:open label:status:ready",
         "done": "is:issue is:closed reason:completed closed:>={since}"}


def esc(s):
    """Text for Slack mrkdwn: no link, mention or markup can be smuggled in through an issue title."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def more_url(repo, key, since=""):
    """The GitHub search behind a board section, for its "and N more" link."""
    return f"https://github.com/{repo}/issues?q=" + urllib.parse.quote_plus(QUERY[key].format(since=since))


def next_up(ready):
    """status:ready issues in the dispatcher's order (board.py's, without the Projects Rank and the debt quota, which
    the dispatcher reads from elsewhere), then the ones it never takes, each with a note saying why."""
    import board  # the kit's one task order (plugins/agentkit/scripts/board.py)
    held = sorted((i for i in ready if board.not_taken(i)), key=lambda i: i["number"])
    return board.order(ready) + [{**i, "note": "not taken: " + board.not_taken(i)} for i in held]


def _section(text, **extra):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}, **extra}


def _context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _cap(key, caps):
    return caps[0] if key == "waiting" else caps[1]


def _size(board, caps):
    """How many blocks _repo() makes for this board with these caps (a waiting item is its card: two blocks)."""
    if board.get("error"):
        return 2
    n = 1 + len(SECTIONS)
    for key, _ in SECTIONS:
        items, cap = board.get(key) or [], _cap(key, caps)
        n += min(len(items), cap) * (2 if key == "waiting" else 1) + (len(items) > cap)
    return n


def _item(repo, key, issue, card_blocks, sent):
    n, url = issue["number"], f"https://github.com/{repo}/issues/{issue['number']}"
    title = esc(clip(issue["title"], 80))
    if key == "waiting":
        blocks = card_blocks({**issue, "repo": repo})
        reply = sent.get(f"{repo}#{n}")
        if reply is None:
            return blocks
        return blocks[:1] + [_context(f"✓ Sent: {esc(clip(reply, 80))} · the board updates when GitHub does")]
    if key == "in_progress":
        stage = next((l[len("status:"):].replace("-", " ") for l in issue.get("labels", []) if l.startswith("status:")), "")
        return [_section(f"<{url}|#{n}> {title}" + (f" · {stage}" if stage else ""))]
    if key == "next":
        return [_section(f"<{url}|#{n}> {title}" + (f" · {issue['note']}" if issue.get("note") else ""))]
    return [_section(f"✓ <{url}|#{n}> {title}")]


def _repo(board, caps, card_blocks, sent):
    repo = board["repo"]
    head = _section(f"*<https://github.com/{repo}|{esc(repo)}>*", accessory={
        "type": "button", "action_id": "add_task", "value": repo, "text": {"type": "plain_text", "text": "+ Add task"}})
    if board.get("error"):
        return [head, _context(esc(board["error"]))]
    blocks = [head]
    for key, name in SECTIONS:
        items, cap = board.get(key) or [], _cap(key, caps)
        blocks.append(_section(f"*{name}* ({len(items)})"))
        for issue in items[:cap]:
            blocks += _item(repo, key, issue, card_blocks, sent)
        if len(items) > cap:
            blocks.append(_context(f"<{more_url(repo, key, board.get('since', ''))}|and {len(items) - cap} more on GitHub>"))
    return blocks


def home_view(boards, card_blocks, sent=None, notice=None):
    """The App Home board. boards = [{"repo", "waiting", "in_progress", "next", "done": [issue], "since": "YYYY-MM-DD"}
    or {"repo", "error"}], one per repo the person may act on; an issue is {"number", "title", "labels", ...}.
    card_blocks(issue) gives a waiting item's blocks (its Slack card), called only for the items shown. sent maps
    "owner/repo#n" to a reply just sent from here: that item shows it instead of its buttons. Each section is capped
    so the view fits Slack's 100 blocks, with an "and N more" link to the GitHub search."""
    sent = sent or {}
    top = [_section(esc(notice))] if notice else []
    if not boards:
        return {"type": "home", "blocks": top + [_section(
            "You have write access to none of the repositories this bot serves, so there is nothing to show.")]}
    boards = list(boards)

    def fits(caps):
        return len(top) + sum(_size(b, caps) for b in boards) + len(boards) - 1 <= VIEW_MAX

    caps = next((c for c in CAPS if fits(c)), None)
    while caps is None and len(boards) > 1:  # ponytail: only with about eight or more repos; the rest are left out
        boards.pop()
        caps = next((c for c in CAPS if fits(c)), None)
    blocks = list(top)
    for i, b in enumerate(boards):
        blocks += ([{"type": "divider"}] if i else []) + _repo(b, caps or CAPS[-1], card_blocks, sent)
    return {"type": "home", "blocks": blocks}


def unmapped_view(slack_id):
    return {"type": "home", "blocks": [_section(
        f"Your Slack account is not linked to a GitHub login, so there is no board to show. Ask the bot's owner to add "
        f"your Slack member ID `{esc(slack_id)}` to the bot's users.json.")]}


# --- + Add task ----------------------------------------------------------------------------------------------------

TASK_EVENT = "agentkit-slack-task"
TASK_TITLE_MAX, TASK_BODY_MAX = 256, 3000  # GitHub's title limit; Slack's limit on a modal text input


def task_errors(title, body):
    """{field: message} for the Add task modal; {} when both are fine."""
    errors = {}
    title = (title or "").strip()
    if not title:
        errors["title"] = "A title is needed."
    elif len(title) > TASK_TITLE_MAX or "\n" in title:
        errors["title"] = f"One line, at most {TASK_TITLE_MAX} characters."
    if len(body or "") > TASK_BODY_MAX:
        errors["body"] = f"At most {TASK_BODY_MAX} characters."
    return errors


def task(repo, title, body, login):
    """The repository_dispatch body for a new task: the workflow checks the login and the lengths again."""
    return repo, {"event_type": TASK_EVENT,
                  "client_payload": {"title": (title or "").strip(), "body": body or "", "login": login}}


# --- Nudges --------------------------------------------------------------------------------------------------------

# the user-scope keys of the kit's settings registry (config/settings.json), with its defaults
NUDGE_DEFAULTS = {"nudge": "on", "nudge-hours": "09-20", "timezone": "UTC", "nudges-per-day": 2}
NUDGE_PER_DAY_MAX = 2
NUDGE_GAP = timedelta(hours=4)
HISTORY_KEEP = timedelta(days=2)


def parse_hours(s):
    """"09-20" -> (9, 20): nudges from 09:00 until 20:00."""
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", str(s).strip())
    if not m or not 0 <= int(m.group(1)) < int(m.group(2)) <= 24:
        raise ValueError(f"bad nudge hours: {s!r} (want HH-HH, like 09-20)")
    return int(m.group(1)), int(m.group(2))


def zone(name):
    """The person's timezone; an unknown name is UTC."""
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def due(prefs, history, now, count):
    """Whether a person with `count` waiting items gets a nudge at `now` (an aware datetime).
    prefs = {"nudge": "on"|"off", "nudge-hours": "09-20", "timezone": "Europe/Berlin", "nudges-per-day": 2} (the
    settings registry's keys); a missing or bad value takes the default, and only "off" turns nudges off.
    history = {"sent": [ISO times]}. Only inside the hours, in the person's timezone; at most nudges-per-day (never
    more than 2) in their local day; never twice within 4 hours."""
    p = {**NUDGE_DEFAULTS, **(prefs or {})}
    if count <= 0 or p["nudge"] == "off":
        return False
    try:
        start, end = parse_hours(p["nudge-hours"])
    except ValueError:
        start, end = parse_hours(NUDGE_DEFAULTS["nudge-hours"])
    tz = zone(p["timezone"])
    local = now.astimezone(tz)
    if not start <= local.hour < end:
        return False
    per_day = p["nudges-per-day"] if type(p["nudges-per-day"]) is int else NUDGE_DEFAULTS["nudges-per-day"]
    sent = [datetime.fromisoformat(t) for t in (history or {}).get("sent", [])]
    if sum(t.astimezone(tz).date() == local.date() for t in sent) >= min(per_day, NUDGE_PER_DAY_MAX):
        return False
    return not sent or now - max(sent) >= NUDGE_GAP


def record(history, now):
    """The history after a nudge sent at `now`; sends older than two days are dropped."""
    kept = [t for t in (history or {}).get("sent", []) if now - datetime.fromisoformat(t) < HISTORY_KEEP]
    return {**(history or {}), "sent": kept + [now.isoformat()]}


def nudge_text(count, link):
    return f"{count} waiting" + (f" · <{link}|Open the board>" if link else "")


def load_prefs(path):
    """{"prefs": {slack id: prefs}, "history": {slack id: history}}. A missing file is empty; a broken one is an
    error (never silently reset: that would drop everyone's settings)."""
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a JSON object")
    return {"prefs": data.get("prefs") or {}, "history": data.get("history") or {}}


def save_prefs(path, data):
    """Write atomically: a temp file in the same directory, then a rename over the old one."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".prefs-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=1, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
