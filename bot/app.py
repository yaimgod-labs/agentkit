"""agentkit Slack bot (Socket Mode): a click on a card becomes a `repository_dispatch` to the project's reply workflow;
the Home tab is the board (with `+ Add task`); a background loop sends each person at most two "N waiting" nudges a day;
a DM to the bot (or App Home -> Settings) asks about a setting, and a click on the answer applies it (scripts/settings.py).
Everything it decides is in core.py. Env: SLACK_BOT_TOKEN and SLACK_APP_TOKEN (or the same name with _FILE, a path
to a file holding the value), GITHUB_CLIENT_ID, GITHUB_APP_KEY_FILE, USERS_FILE, AGENTKIT_REPOS (comma-separated
owner/repo allowlist); optional AGENTKIT_PREFS (nudge settings and history, default /data/prefs.json),
AGENTKIT_KIT_BOT (the kit App's slug: its comments give a waiting item on the board its question) and
AGENTKIT_SLACK_APP_ID (this Slack app's id: the nudge links to the Home tab). Never turn on debug logging of Bolt or
the Slack SDK: it logs payloads."""
import base64
import http.client
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# the kit's card builder and task order: copied into kit/ in the image, next door in a checkout of the kit
HERE = Path(__file__).resolve().parent
for d in (HERE.parent / "plugins/agentkit/scripts", HERE.parent / "scripts", HERE / "kit"):
    if d.is_dir():
        sys.path.insert(0, str(d))
import card  # noqa: E402
import core  # noqa: E402
import settings  # noqa: E402


def secret(name):
    """A secret from NAME_FILE (a mounted file) when set, else from NAME."""
    path = os.environ.get(name + "_FILE")
    return open(path).read().strip() if path else os.environ[name]


REPOS = list(dict.fromkeys(r.strip() for r in os.environ["AGENTKIT_REPOS"].split(",") if r.strip()))  # in order
USERS = core.load_users(os.environ["USERS_FILE"])
PREFS = os.environ.get("AGENTKIT_PREFS", "/data/prefs.json")
KIT_BOT = os.environ.get("AGENTKIT_KIT_BOT", "").strip()
SLACK_APP_ID = os.environ.get("AGENTKIT_SLACK_APP_ID", "").strip()
NUDGE_EVERY = 600  # seconds
SENT_FOR = 900  # seconds a reply sent from the Home tab shows there instead of its buttons
DISPATCH = {"contents": "write", "metadata": "read"}  # repository_dispatch and the permission check
READ = {"issues": "read", "metadata": "read"}  # the board and the nudge count
CONTENTS = {"contents": "read", "metadata": "read"}  # the caller workflow, for the project's timezone
ZONES = {}  # owner/repo -> (its Project timezone, when read)
SENT = {}  # slack user -> {"owner/repo#n": (reply, time)}
PREFS_LOCK = threading.Lock()  # the nudge loop and a settings click both write the prefs file
REGISTRY = settings.load()
app = App(token=secret("SLACK_BOT_TOKEN"))
log = logging.getLogger("agentkit-bot")


def gh(method, path, token, body=None):
    # a dropped connection (RemoteDisconnected, a reset, a timeout) is tried again, up to 3 times, for a read and for
    # minting a token. Never for a dispatch: the drop may have come after GitHub took it, and a retry would send it twice
    tries = 3 if method == "GET" or path.endswith("/access_tokens") else 1
    for attempt in range(1, tries + 1):
        req = urllib.request.Request("https://api.github.com" + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError:
            raise  # GitHub answered: retrying does not change the answer
        except (urllib.error.URLError, ConnectionError, TimeoutError, http.client.HTTPException):
            if attempt == tries:
                raise
            time.sleep(attempt)


def install_token(repo, permissions):
    """A short-lived installation token for this one repo and these permissions, minted per use (nothing cached,
    nothing stored)."""
    now = int(time.time())
    key = open(os.environ["GITHUB_APP_KEY_FILE"]).read()
    app_jwt = jwt.encode({"iat": now - 60, "exp": now + 300, "iss": os.environ["GITHUB_CLIENT_ID"]}, key, algorithm="RS256")
    inst = gh("GET", f"/repos/{repo}/installation", app_jwt)["id"]
    scope = {"repositories": [repo.split("/")[1]], "permissions": permissions}
    return gh("POST", f"/app/installations/{inst}/access_tokens", app_jwt, scope)["token"]


def permission_of(repo, token):
    def permission(login):
        try:
            return gh("GET", f"/repos/{repo}/collaborators/{login}/permission", token)["permission"]
        except Exception:
            return "none"
    return permission


def problem(e):
    """A short, token-free description of an error for the log or the board."""
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    err = getattr(e, "response", None)
    if err is not None and hasattr(err, "get"):
        return f"Slack said {err.get('error')}"
    return type(e).__name__


# --- clicks on a card or on the board -------------------------------------------------------------------------------

def act(slack_user, value, text, say_to, done):
    """Check, dispatch, then tell the person. say_to(msg) tells them why not; done(login, reply) shows it was sent."""
    try:
        repo, n, kw = core.parse_value(value)
    except ValueError:
        return say_to("That button is not valid.")
    if repo not in REPOS:
        return say_to("This repository is not managed by this bot.")
    token = install_token(repo, DISPATCH)
    login, refusal = core.authorize(slack_user, USERS, permission_of(repo, token))
    if refusal:
        return say_to(refusal)
    reply = f"{kw} {text}".strip() if kw and text else (kw or text)
    _, body = core.dispatch(repo, n, reply, login)
    gh("POST", f"/repos/{repo}/dispatches", token, body)
    done(login, reply)


def finish(client, channel, ts, blocks, login, reply):
    one_line = " ".join(reply.split())[:80]
    note = f"✓ {one_line} · @{login}"
    client.chat_update(channel=channel, ts=ts, text=note,
                       blocks=[blocks[0], {"type": "context", "elements": [{"type": "mrkdwn", "text": note}]}])


def from_home(body):
    return (body.get("view") or {}).get("type") == "home"


def home_replies(client, user, value):
    """say_to and done for a click on the board: the board is published again, with the message or the sent reply."""
    def done(login, reply):
        repo, n, _ = core.parse_value(value)
        SENT.setdefault(user, {})[f"{repo}#{n}"] = (reply, time.time())
        publish_home(client, user)
    return (lambda m: publish_home(client, user, notice=m)), done


@app.action(re.compile(r"^reply_\d+$"))
def on_reply(ack, body, client):
    ack()
    user, value = body["user"]["id"], body["actions"][0]["value"]
    if from_home(body):
        return act(user, value, "", *home_replies(client, user, value))
    ch, ts = body["channel"]["id"], body["message"]["ts"]
    act(user, value, "",
        lambda m: client.chat_postEphemeral(channel=ch, user=user, text=m),
        lambda login, reply: finish(client, ch, ts, body["message"]["blocks"], login, reply))


@app.action(re.compile(r"^modal_\d+$"))
def on_modal(ack, body, client):
    ack()
    meta = {"value": body["actions"][0]["value"]}
    if from_home(body):
        meta["home"] = True
    else:
        meta.update(ch=body["channel"]["id"], ts=body["message"]["ts"], blocks=body["message"]["blocks"][:1])
    client.views_open(trigger_id=body["trigger_id"], view={
        "type": "modal", "callback_id": "answer", "private_metadata": json.dumps(meta),
        "title": {"type": "plain_text", "text": "Your answer"}, "submit": {"type": "plain_text", "text": "Send"},
        "blocks": [{"type": "input", "block_id": "t", "label": {"type": "plain_text", "text": "Answer"},
                    "element": {"type": "plain_text_input", "action_id": "t", "multiline": True}}]})


@app.action("logs")
def on_logs(ack):
    ack()  # a link button: Slack opens the URL and still sends the click, which needs no answer


@app.view("answer")
def on_answer(ack, body, client, view):
    ack()
    meta, user = json.loads(view["private_metadata"]), body["user"]["id"]
    text = view["state"]["values"]["t"]["t"]["value"] or ""
    if meta.get("home"):
        return act(user, meta["value"], text, *home_replies(client, user, meta["value"]))
    act(user, meta["value"], text,
        lambda m: client.chat_postEphemeral(channel=meta["ch"], user=user, text=m),
        lambda login, reply: finish(client, meta["ch"], meta["ts"], meta["blocks"], login, reply))


# --- the Home tab: the board ----------------------------------------------------------------------------------------

def issues(repo, token, **query):
    """Issues (not pull requests) for a REST list query, the first 100."""
    q = urllib.parse.urlencode({**query, "per_page": 100})
    return [i for i in gh("GET", f"/repos/{repo}/issues?{q}", token) if "pull_request" not in i]


def slim(i):
    return {"number": i["number"], "title": i["title"], "labels": [l["name"] for l in i["labels"]]}


def read_board(repo, token, now):
    since = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    waiting = issues(repo, token, state="open", labels="action:required", sort="created", direction="asc")
    working = issues(repo, token, state="open", labels="status:in-progress") + \
        issues(repo, token, state="open", labels="status:review")
    ready = issues(repo, token, state="open", labels="status:ready")
    closed = issues(repo, token, state="closed", since=since, sort="updated", direction="desc")
    done = sorted((i for i in closed if i.get("state_reason") == "completed" and (i.get("closed_at") or "") >= since),
                  key=lambda i: i["closed_at"], reverse=True)
    return {"repo": repo, "since": since[:10], "waiting": [slim(i) for i in waiting],
            "in_progress": sorted((slim(i) for i in working), key=lambda i: i["number"]),
            "next": core.next_up([slim(i) for i in ready]), "done": [slim(i) for i in done]}


def card_blocks(tokens):
    """A waiting item's card, its question taken from the kit's own comments (only with AGENTKIT_KIT_BOT set: no
    one else's text becomes a question or a button)."""
    def build(issue):
        comments = []
        if KIT_BOT:
            try:
                # ponytail: the first 100 comments; an issue with more shows an older question
                raw = gh("GET", f"/repos/{issue['repo']}/issues/{issue['number']}/comments?per_page=100", tokens[issue["repo"]])
                comments = [c.get("body") or "" for c in raw if (c.get("user") or {}).get("login") == KIT_BOT + "[bot]"]
            except Exception as e:
                log.warning("board: comments of %s#%s: %s", issue["repo"], issue["number"], problem(e))
        return card.build({**issue, "comments": comments})["blocks"]
    return build


def publish_home(client, user, notice=None):
    """The board for this Slack user: only repos where their mapped login has write access now."""
    if user not in USERS:
        return client.views_publish(user_id=user, view=core.unmapped_view(user))
    now, boards, tokens = datetime.now(timezone.utc), [], {}
    for repo in sorted(REPOS):
        try:
            token = install_token(repo, READ)
            _, refusal = core.authorize(user, USERS, permission_of(repo, token))
        except Exception as e:
            log.warning("board: %s: %s", repo, problem(e))
            continue
        if refusal:
            continue
        try:
            boards.append(read_board(repo, token, now))
            tokens[repo] = token
        except Exception as e:
            log.warning("board: %s: %s", repo, problem(e))
            boards.append({"repo": repo, "error": f"Could not read {repo} ({problem(e)})."})
    mine = SENT.get(user, {})
    for ref in [r for r, (_, t) in mine.items() if time.time() - t > SENT_FOR]:
        del mine[ref]
    sent = {ref: reply for ref, (reply, _) in mine.items()}
    client.views_publish(user_id=user, view=core.home_view(boards, card_blocks(tokens), sent=sent, notice=notice))


@app.event("app_home_opened")
def on_home(event, client):
    if event.get("tab") == "home":
        log.info("home: opened by %s", event["user"])
        publish_home(client, event["user"])


# --- + Add task -----------------------------------------------------------------------------------------------------

@app.action("add_task")
def on_add_task(ack, body, client):
    ack()
    repo = body["actions"][0]["value"]
    client.views_open(trigger_id=body["trigger_id"], view={
        "type": "modal", "callback_id": "task", "private_metadata": repo,
        "title": {"type": "plain_text", "text": "Add task"}, "submit": {"type": "plain_text", "text": "File it"},
        "blocks": [
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"A new task in {core.esc(repo)}. agentkit plans it first."}]},
            {"type": "input", "block_id": "title", "label": {"type": "plain_text", "text": "Title"},
             "element": {"type": "plain_text_input", "action_id": "v", "max_length": core.TASK_TITLE_MAX}},
            {"type": "input", "block_id": "body", "optional": True, "label": {"type": "plain_text", "text": "Details"},
             "element": {"type": "plain_text_input", "action_id": "v", "multiline": True, "max_length": core.TASK_BODY_MAX}}]})


@app.view("task")
def on_task(ack, body, client, view):
    user, values = body["user"]["id"], view["state"]["values"]
    title, text = values["title"]["v"]["value"] or "", values["body"]["v"]["value"] or ""
    errors = core.task_errors(title, text)
    if errors:
        return ack(response_action="errors", errors=errors)
    ack()
    repo = view["private_metadata"]
    if repo not in REPOS:
        return publish_home(client, user, notice="This repository is not managed by this bot.")
    try:
        token = install_token(repo, DISPATCH)
        login, refusal = core.authorize(user, USERS, permission_of(repo, token))
        if refusal:
            return publish_home(client, user, notice=refusal)
        gh("POST", f"/repos/{repo}/dispatches", token, core.task(repo, title, text, login)[1])
        log.info("task: sent to %s for %s", repo, login)
    except Exception as e:  # the modal is already closed: say so on Home, or the person sees nothing happen
        log.warning("task: %s: %s", repo, problem(e))
        return publish_home(client, user, notice=f"Could not send “{core.clip(title, 80)}” to {repo} ({problem(e)}). "
                                                 "Try again in a bit.")
    publish_home(client, user, notice=f"Sent “{core.clip(title, 80)}” to {repo}: it becomes a task in a minute "
                                      "and is planned first.")


# --- settings: ask in a DM or from the Home tab, apply with a click -------------------------------------------------

PLACEHOLDER = "⏳ Looking that up…"
NOT_LINKED = core.NOT_LINKED


def known(user):
    """For an answer's "Now": the values the workflow cannot see, this person's own settings and the bot's server
    ones (none is a secret: the registry holds no secret)."""
    try:
        mine = prefs()["prefs"].get(user, {})
    except PrefsBroken:
        mine = {}
    now = {e["key"]: mine[e["key"]] for e in REGISTRY if e["apply"]["via"] == "prefs" and e["key"] in mine}
    now.update({e["key"]: os.environ[e["apply"]["name"]] for e in REGISTRY
                if e["apply"]["via"] == "server" and os.environ.get(e["apply"]["name"])})
    return now


def remembered(user):
    """The repo this person last asked about, while the bot still serves it."""
    try:
        r = prefs()["repo"].get(user)
    except PrefsBroken:
        return None
    return r if r in REPOS else None


def remember(user, repo):
    try:
        with PREFS_LOCK:
            data = prefs()
            if data["repo"].get(user) != repo:
                data["repo"][user] = repo
                prefs(save=data)
    except PrefsBroken as e:
        log.warning("settings: cannot remember the repo (%s)", e)


def say_in(client, user, msg, reply_to=None):
    """A message in the person's DM, in place of `reply_to` (channel, ts) when given."""
    if reply_to:
        return client.chat_update(channel=reply_to[0], ts=reply_to[1], **{"blocks": [], **msg})
    return client.chat_postMessage(channel=user, **msg)


def ask(client, user, question, key=None, repo=None, reply_to=None):
    """Answer a settings question. The list, and one personal or server setting named as such, are answered here at
    once (core.quick); everything else goes to a repo's workflow, where a read-only model picks the settings (none
    for a known `key`) and its answer replaces the placeholder. The repo: `repo`, else one the question names, else
    the one the person last asked about, else the first in AGENTKIT_REPOS they can write to; it is remembered."""
    err = core.ask_error(question)
    if err:
        return say_in(client, user, {"text": err}, reply_to)
    if user not in USERS:
        return say_in(client, user, {"text": NOT_LINKED}, reply_to)
    if repo is None:
        repo = core.named_repo(question, REPOS)
        if repo:
            remember(user, repo)
    key = key or core.quick(question, REGISTRY, REPOS)
    here = repo or remembered(user) or REPOS[0]
    if key == "list":
        return say_in(client, user, settings.list_card(REGISTRY, here), reply_to)
    entry = settings.find(REGISTRY, key) if key else None
    if entry and entry["apply"]["via"] in ("prefs", "server"):
        return say_in(client, user, settings.entry_card(REGISTRY, entry, here, state={"now": known(user)}), reply_to)
    if not reply_to:
        held = client.chat_postMessage(channel=user, text=PLACEHOLDER)
        reply_to = (held["channel"], held["ts"])
    for r in [repo] if repo else list(dict.fromkeys([here] + REPOS)):
        try:
            token = install_token(r, DISPATCH)
            login, _ = core.authorize(user, USERS, permission_of(r, token))
            if login:
                gh("POST", f"/repos/{r}/dispatches", token,
                   core.settings_ask(r, question, login, user, reply_to, known(user), key, REPOS)[1])
                remember(user, r)
                log.info("settings: question sent through %s for %s", r, login)
                return
        except Exception as e:
            log.warning("settings: %s: %s", r, problem(e))
    client.chat_update(channel=reply_to[0], ts=reply_to[1], blocks=[],
                       text=f"You have no write access to {repo}, so I cannot look it up." if repo else
                       "You have write access to none of the repositories this bot serves, so I cannot look it up.")


@app.event("message")
def on_message(event, client):
    # the one place the bot reads free text: a person's own new message in their DM with it
    if event.get("channel_type") != "im" or event.get("subtype") or event.get("bot_id") or event.get("thread_ts"):
        return
    log.info("dm: message from %s", event["user"])
    ask(client, event["user"], event.get("text") or "")


@app.action("settings_ask")
def on_settings_ask(ack, body, client):
    ack()
    client.views_open(trigger_id=body["trigger_id"], view={
        "type": "modal", "callback_id": "settings", "title": {"type": "plain_text", "text": "Settings"},
        "submit": {"type": "plain_text", "text": "Ask"},
        "blocks": [{"type": "input", "block_id": "q", "label": {"type": "plain_text", "text": "What would you like to change?"},
                    "element": {"type": "plain_text_input", "action_id": "v", "max_length": core.ASK_MAX,
                                "placeholder": {"type": "plain_text", "text": "Can I change the nudge hours?"}}}]})


@app.view("settings")
def on_settings(ack, body, client, view):
    ack()
    ask(client, body["user"]["id"], view["state"]["values"]["q"]["v"]["value"] or "")


def edit(client, ch, ts, m):
    client.chat_update(channel=ch, ts=ts, text=m, blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": core.esc(m)}}])


def set_pref(user, entry, val):
    """Write one of the person's own settings; returns the old value. PrefsBroken when the file cannot be written."""
    with PREFS_LOCK:
        data = prefs()
        mine = data["prefs"].setdefault(user, {})
        old = mine.get(entry["key"], entry["default"])
        mine[entry["key"]] = settings.typed(entry, val)
        prefs(save=data)
    return old


def apply_setting(client, user, value, ch, ts):
    """A click on an answer's option: validated against the registry, then applied. A user setting is written to the
    prefs file here; a project one (admin only) goes to the repo's `setting` job. The model never writes one."""
    try:
        repo, key, val = core.parse_setting(value)
    except ValueError:
        return edit(client, ch, ts, "That button is not valid.")
    entry = settings.find(REGISTRY, key)
    if entry is None or repo not in REPOS:
        return edit(client, ch, ts, "That setting or repository is not one this bot manages.")
    err = settings.validate(entry, val)
    if err:
        return edit(client, ch, ts, f"{entry['title']}: not changed, the value {err}.")
    via = entry["apply"]["via"]
    if via == "prefs":
        if user not in USERS:
            return edit(client, ch, ts, NOT_LINKED)
        try:
            old = set_pref(user, entry, val)
        except PrefsBroken as e:
            log.error("settings: %s cannot be read or written (%s)", PREFS, e)
            return edit(client, ch, ts, "Not changed: the bot cannot save settings now. Tell the owner.")
        return client.chat_update(channel=ch, ts=ts, **settings.changed(entry, repo, val, old))
    if via == "server":
        return edit(client, ch, ts, f"{entry['title']}: change it in Claude Code with /agentkit:settings, or {settings.how(entry)}.")
    token = install_token(repo, DISPATCH)
    login, refusal = core.authorize(user, USERS, permission_of(repo, token), core.ADMIN)
    if refusal:
        return edit(client, ch, ts, refusal)
    gh("POST", f"/repos/{repo}/dispatches", token, core.setting(repo, key, val, login, user)[1])
    edit(client, ch, ts, f"Sent: {entry['title']} on {repo} to {settings.text(val)}. "
                         + ("I'll DM you when it is set." if via == "variable" else "I'll DM you the pull request."))


@app.action(re.compile(r"^setting_(\d|select|zone|undo)$"))
def on_setting(ack, body, client):
    ack()
    a = body["actions"][0]
    value = a.get("value") or (a.get("selected_option") or {}).get("value") or ""
    apply_setting(client, body["user"]["id"], value, body["channel"]["id"], body["message"]["ts"])


@app.action("setting_pick")
def on_setting_pick(ack, body, client):
    """A setting picked from the list's menu: answered like a question naming it, without the model."""
    ack()
    try:
        repo, key = core.parse_pick(body["actions"][0]["selected_option"]["value"])
    except (KeyError, TypeError, ValueError):
        return
    entry = settings.find(REGISTRY, key)
    if entry is not None and repo in REPOS:
        ask(client, body["user"]["id"], entry["title"], key=key, repo=repo)


@app.action("setting_repo")
def on_setting_repo(ack, body, client):
    """A project card's repo menu: the same setting, looked up in the other repo, in place of the card; that repo
    is remembered."""
    ack()
    try:
        repo, key = core.parse_pick(body["actions"][0]["selected_option"]["value"], "repo")
    except (KeyError, TypeError, ValueError):
        return
    entry, user = settings.find(REGISTRY, key), body["user"]["id"]
    if entry is None or repo not in REPOS:
        return
    remember(user, repo)
    ask(client, user, entry["title"], key=key, repo=repo, reply_to=(body["channel"]["id"], body["message"]["ts"]))


@app.action("setting_all")
def on_setting_all(ack, body, client):
    """Apply all on an answer about several settings: each value is validated again; the person's own apply here,
    the project's go to the repo's `setting` job in one event (admin only): variables, and one caller pull request."""
    ack()
    user, ch, ts = body["user"]["id"], body["channel"]["id"], body["message"]["ts"]
    try:
        repo, changes = core.parse_all(body["actions"][0]["value"])
    except (KeyError, ValueError):
        return edit(client, ch, ts, "That button is not valid.")
    if repo not in REPOS:
        return edit(client, ch, ts, "That repository is not one this bot manages.")
    if user not in USERS:
        return edit(client, ch, ts, NOT_LINKED)
    lines, project = [], []
    for key, val in changes:
        entry = settings.find(REGISTRY, key)
        err = settings.validate(entry, val) if entry else "is not a setting"
        if err:
            lines.append(f"{entry['title'] if entry else key}: not changed, the value {err}.")
        elif entry["apply"]["via"] == "prefs":
            try:
                old = set_pref(user, entry, val)
                lines.append(f"{entry['title']}: {settings.text(val)} (was {settings.text(old)}).")
            except PrefsBroken as e:
                log.error("settings: %s cannot be read or written (%s)", PREFS, e)
                lines.append(f"{entry['title']}: not changed, the bot cannot save settings now. Tell the owner.")
        elif entry["apply"]["via"] in ("variable", "caller"):
            project.append((entry, val))
        else:
            lines.append(f"{entry['title']}: {settings.how(entry)}.")
    if project:
        try:
            token = install_token(repo, DISPATCH)
            login, refusal = core.authorize(user, USERS, permission_of(repo, token), core.ADMIN)
            if refusal:
                lines.append(refusal)
            else:
                gh("POST", f"/repos/{repo}/dispatches", token,
                   core.settings_changes(repo, [(e["key"], v) for e, v in project], login, user)[1])
                lines.append(f"Sent to {repo}: " + "; ".join(f"{e['title']} to {settings.text(v)}" for e, v in project)
                             + ". I'll DM you what changed, and the pull request for the caller's settings.")
        except Exception as e:
            log.warning("settings: %s: %s", repo, problem(e))
            lines.append(f"Not sent to {repo} ({problem(e)}). Try again in a bit.")
    edit(client, ch, ts, "\n".join(lines))


@app.action("setting_other")
def on_setting_other(ack, body, client):
    ack()
    try:
        repo, key, _ = core.parse_setting(body["actions"][0]["value"])
    except ValueError:
        return
    entry = settings.find(REGISTRY, key)
    if entry is None:
        return
    meta = {"repo": repo, "key": key, "ch": body["channel"]["id"], "ts": body["message"]["ts"]}
    element = {"type": "plain_text_input", "action_id": "v", "max_length": 1000}
    if entry["type"] == "timezone":  # ~600 names: search them as you type (on_zone_options)
        element = {"type": "external_select", "action_id": "zone", "min_query_length": 2,
                   "placeholder": {"type": "plain_text", "text": "Type a city or region"}}
    client.views_open(trigger_id=body["trigger_id"], view={
        "type": "modal", "callback_id": "setting_value", "private_metadata": json.dumps(meta),
        "title": {"type": "plain_text", "text": "Other value"}, "submit": {"type": "plain_text", "text": "Set"},
        "blocks": [{"type": "input", "block_id": "v", "label": {"type": "plain_text", "text": core.clip(entry["title"], 48)},
                    "hint": {"type": "plain_text", "text": core.clip(entry["description"], 150)},
                    "element": element}]})


@app.options("zone")
def on_zone_options(ack, payload):
    ack(options=[{"text": {"type": "plain_text", "text": z}, "value": z} for z in core.zones(payload.get("value"))])


@app.options("setting_zone")
def on_card_zone_options(ack, payload):
    """The timezone search next to an hours answer: its block id names the repo and the key (zone|repo|key); a pick
    is applied like any button, after the same checks."""
    _, repo, key = (payload.get("block_id") or "||").split("|", 2)
    ack(options=[{"text": {"type": "plain_text", "text": z}, "value": settings.value(repo, key, z)}
                 for z in core.zones(payload.get("value"))])


@app.view("setting_value")
def on_setting_value(ack, body, client, view):
    meta = json.loads(view["private_metadata"])
    field = next(iter(view["state"]["values"]["v"].values()))  # typed text, or the timezone picked
    val = (field.get("value") or (field.get("selected_option") or {}).get("value") or "").strip()
    entry = settings.find(REGISTRY, meta["key"])
    err = settings.validate(entry, val) if entry else "is not a setting"
    if err:
        return ack(response_action="errors", errors={"v": f"The value {err}."})
    ack()
    apply_setting(client, body["user"]["id"], settings.value(meta["repo"], meta["key"], val), meta["ch"], meta["ts"])


@app.action("setting_feature")
def on_setting_feature(ack, body, client):
    """No setting fits: the question becomes a feature request, through + Add task's path."""
    ack()
    user, ch, ts = body["user"]["id"], body["channel"]["id"], body["message"]["ts"]
    try:
        repo, title = core.parse_feature(body["actions"][0]["value"])
    except ValueError:
        return edit(client, ch, ts, "That button is not valid.")
    if repo not in REPOS or core.task_errors(title, ""):
        return edit(client, ch, ts, "That button is not valid.")
    token = install_token(repo, DISPATCH)
    login, refusal = core.authorize(user, USERS, permission_of(repo, token))
    if refusal:
        return edit(client, ch, ts, refusal)
    gh("POST", f"/repos/{repo}/dispatches", token,
       core.task(repo, title, "Asked the settings bot in Slack; agentkit has no setting for it yet.", login)[1])
    edit(client, ch, ts, f"Filed “{core.clip(title, 80)}” as a feature request in {repo}: it becomes a task in a minute.")


# --- nudges ---------------------------------------------------------------------------------------------------------

def waiting_counts(users):
    """{slack user: open action:required issues across the repos their login can write to}."""
    counts = dict.fromkeys(users, 0)
    for repo in sorted(REPOS):
        try:
            token = install_token(repo, READ)
            n = len(issues(repo, token, state="open", labels="action:required"))
            if n:
                permission = permission_of(repo, token)
                for user in users:
                    counts[user] += n if permission(USERS[user]) in core.WRITE else 0
        except Exception as e:
            log.warning("nudge: %s: %s", repo, problem(e))
    return counts


class PrefsBroken(Exception):
    pass


def prefs(save=None):
    """Read the prefs file, or write `save` to it; any failure is PrefsBroken."""
    try:
        return core.load_prefs(PREFS) if save is None else core.save_prefs(PREFS, save)
    except (OSError, ValueError) as e:
        raise PrefsBroken(problem(e)) from None


def project_zone(repo):
    """The repo's Project timezone (the `timezone:` of its caller's schedules), read at most every 15 minutes; the
    last one read (or UTC) when GitHub cannot be reached."""
    hit = ZONES.get(repo)
    if hit and time.time() - hit[1] < 900:
        return hit[0]
    zone = hit[0] if hit else "UTC"
    try:
        meta = gh("GET", f"/repos/{repo}/contents/.github/workflows/agentkit.yml", install_token(repo, CONTENTS))
        zone = settings.caller_zone(base64.b64decode(meta.get("content") or "").decode())
    except Exception as e:
        log.warning("nudge: %s timezone: %s", repo, problem(e))
    ZONES[repo] = (zone, time.time())
    return zone


def nudge_prefs(data, user):
    """The person's nudge settings; without a timezone of their own, the Project timezone of the repo they last
    asked about (else the first one served)."""
    p = dict(data["prefs"].get(user) or {})
    if not p.get("timezone"):
        last = data["repo"].get(user)
        p["timezone"] = project_zone(last if last in REPOS else REPOS[0])
    return p


def nudge_once(client, link):
    now = datetime.now(timezone.utc)
    data = prefs()  # read each time: the owner may edit the prefs by hand
    # only people a nudge could reach now are counted, so a night costs no GitHub calls
    users = [u for u in USERS if core.due(nudge_prefs(data, u), data["history"].get(u), now, 1)]
    for user, count in waiting_counts(users).items():
        if core.due(nudge_prefs(data, user), data["history"].get(user), now, count):
            client.chat_postMessage(channel=user, text=core.nudge_text(count, link))
            with PREFS_LOCK:  # read again: a settings click may have written meanwhile
                data = prefs()
                data["history"][user] = core.record(data["history"].get(user), now)
                prefs(save=data)


def nudge_loop(client):
    try:
        team = client.auth_test().get("team_id")
    except Exception as e:
        log.warning("nudge: no team id (%s); nudges carry no link", problem(e))
        team = None
    link = f"slack://app?team={team}&id={SLACK_APP_ID}&tab=home" if team and SLACK_APP_ID else None
    while True:
        try:
            nudge_once(client, link)
        except PrefsBroken as e:
            # without a history that sticks, the next tick would nudge again: stop instead
            log.error("nudges stopped: %s cannot be read or written (%s)", PREFS, e)
            return
        except Exception as e:
            log.warning("nudge: %s", problem(e))
        time.sleep(NUDGE_EVERY)


def start_nudges(client):
    try:
        prefs(save=prefs())  # fail now, not after the first nudge
    except PrefsBroken as e:
        log.error("nudges off: %s cannot be read and written (%s); mount a writable volume there", PREFS, e)
        return
    threading.Thread(target=nudge_loop, args=(client,), name="nudges", daemon=True).start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # one line per action (who, which repo; never message text or payloads), so a click that did nothing can be traced.
    # Bolt and the Slack SDK stay at WARNING: their debug logs carry payloads
    log.setLevel(logging.INFO)
    start_nudges(app.client)
    SocketModeHandler(app, secret("SLACK_APP_TOKEN")).start()
