"""agentkit Slack bot (Socket Mode): a click on a card becomes a `repository_dispatch` to the project's reply workflow;
the Home tab is the board (with `+ Add task`); a background loop sends each person at most two "N waiting" nudges a day.
Everything it decides is in core.py. Env: SLACK_BOT_TOKEN and SLACK_APP_TOKEN (or the same name with _FILE, a path
to a file holding the value), GITHUB_CLIENT_ID, GITHUB_APP_KEY_FILE, USERS_FILE, AGENTKIT_REPOS (comma-separated
owner/repo allowlist); optional AGENTKIT_PREFS (nudge settings and history, default /data/prefs.json),
AGENTKIT_KIT_BOT (the kit App's slug: its comments give a waiting item on the board its question) and
AGENTKIT_SLACK_APP_ID (this Slack app's id: the nudge links to the Home tab). Never turn on debug logging of Bolt or
the Slack SDK: it logs payloads."""
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


def secret(name):
    """A secret from NAME_FILE (a mounted file) when set, else from NAME."""
    path = os.environ.get(name + "_FILE")
    return open(path).read().strip() if path else os.environ[name]


REPOS = {r.strip() for r in os.environ["AGENTKIT_REPOS"].split(",") if r.strip()}
USERS = core.load_users(os.environ["USERS_FILE"])
PREFS = os.environ.get("AGENTKIT_PREFS", "/data/prefs.json")
KIT_BOT = os.environ.get("AGENTKIT_KIT_BOT", "").strip()
SLACK_APP_ID = os.environ.get("AGENTKIT_SLACK_APP_ID", "").strip()
NUDGE_EVERY = 600  # seconds
SENT_FOR = 900  # seconds a reply sent from the Home tab shows there instead of its buttons
DISPATCH = {"contents": "write", "metadata": "read"}  # repository_dispatch and the permission check
READ = {"issues": "read", "metadata": "read"}  # the board and the nudge count
SENT = {}  # slack user -> {"owner/repo#n": (reply, time)}
app = App(token=secret("SLACK_BOT_TOKEN"))
log = logging.getLogger("agentkit-bot")


def gh(method, path, token, body=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


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
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"A new issue in {core.esc(repo)}, refined by the kit."}]},
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
    token = install_token(repo, DISPATCH)
    login, refusal = core.authorize(user, USERS, permission_of(repo, token))
    if refusal:
        return publish_home(client, user, notice=refusal)
    _, payload = core.task(repo, title, text, login)
    gh("POST", f"/repos/{repo}/dispatches", token, payload)
    publish_home(client, user, notice=f"Sent “{core.clip(title, 80)}” to {repo}: it becomes an issue in a minute "
                                      "and goes to refinement.")


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


def nudge_once(client, link):
    now = datetime.now(timezone.utc)
    data = prefs()  # read each time: the owner may edit the prefs by hand
    # only people a nudge could reach now are counted, so a night costs no GitHub calls
    users = [u for u in USERS if core.due(data["prefs"].get(u), data["history"].get(u), now, 1)]
    for user, count in waiting_counts(users).items():
        if core.due(data["prefs"].get(user), data["history"].get(user), now, count):
            client.chat_postMessage(channel=user, text=core.nudge_text(count, link))
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
    start_nudges(app.client)
    SocketModeHandler(app, secret("SLACK_APP_TOKEN")).start()
