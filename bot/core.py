"""The bot's decisions, apart from Slack: who a click is, whether they may act, and what goes to GitHub.
Python 3.9+, stdlib only; bot/app.py is the thin Slack and HTTP layer around it."""
import json
import re

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
