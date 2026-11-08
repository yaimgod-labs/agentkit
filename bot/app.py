"""agentkit Slack bot (Socket Mode): a click on a card becomes a `repository_dispatch` to the project's reply workflow.
Everything it decides is in core.py. Env: SLACK_BOT_TOKEN and SLACK_APP_TOKEN (or the same name with _FILE, a path
to a file holding the value), GITHUB_CLIENT_ID, GITHUB_APP_KEY_FILE, USERS_FILE, AGENTKIT_REPOS (comma-separated
owner/repo allowlist). Never turn on debug logging of Bolt or the Slack SDK: it logs payloads."""
import json
import os
import re
import time
import urllib.request

import jwt
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import core

def secret(name):
    """A secret from NAME_FILE (a mounted file) when set, else from NAME."""
    path = os.environ.get(name + "_FILE")
    return open(path).read().strip() if path else os.environ[name]


REPOS = {r.strip() for r in os.environ["AGENTKIT_REPOS"].split(",") if r.strip()}
USERS = core.load_users(os.environ["USERS_FILE"])
app = App(token=secret("SLACK_BOT_TOKEN"))


def gh(method, path, token, body=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def install_token(repo):
    """A short-lived installation token for this repo, minted per interaction (nothing cached, nothing stored)."""
    now = int(time.time())
    key = open(os.environ["GITHUB_APP_KEY_FILE"]).read()
    app_jwt = jwt.encode({"iat": now - 60, "exp": now + 300, "iss": os.environ["GITHUB_CLIENT_ID"]}, key, algorithm="RS256")
    inst = gh("GET", f"/repos/{repo}/installation", app_jwt)["id"]
    # only this repo, and only what the dispatch and the permission check need
    scope = {"repositories": [repo.split("/")[1]], "permissions": {"contents": "write", "metadata": "read"}}
    return gh("POST", f"/app/installations/{inst}/access_tokens", app_jwt, scope)["token"]


def act(slack_user, value, text, say_to, done):
    """Check, dispatch, then tell the person. say_to(msg) is an ephemeral reply; done(login) edits the card."""
    try:
        repo, n, kw = core.parse_value(value)
    except ValueError:
        return say_to("That button is not valid.")
    if repo not in REPOS:
        return say_to("This repository is not managed by this bot.")
    token = install_token(repo)

    def permission(login):
        try:
            return gh("GET", f"/repos/{repo}/collaborators/{login}/permission", token)["permission"]
        except Exception:
            return "none"

    login, refusal = core.authorize(slack_user, USERS, permission)
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


@app.action(re.compile(r"^reply_\d+$"))
def on_reply(ack, body, client):
    ack()
    ch, ts, user = body["channel"]["id"], body["message"]["ts"], body["user"]["id"]
    act(user, body["actions"][0]["value"], "",
        lambda m: client.chat_postEphemeral(channel=ch, user=user, text=m),
        lambda login, reply: finish(client, ch, ts, body["message"]["blocks"], login, reply))


@app.action(re.compile(r"^modal_\d+$"))
def on_modal(ack, body, client):
    ack()
    meta = {"value": body["actions"][0]["value"], "ch": body["channel"]["id"], "ts": body["message"]["ts"],
            "blocks": body["message"]["blocks"][:1]}
    client.views_open(trigger_id=body["trigger_id"], view={
        "type": "modal", "callback_id": "answer", "private_metadata": json.dumps(meta),
        "title": {"type": "plain_text", "text": "Your answer"}, "submit": {"type": "plain_text", "text": "Send"},
        "blocks": [{"type": "input", "block_id": "t", "label": {"type": "plain_text", "text": "Answer"},
                    "element": {"type": "plain_text_input", "action_id": "t", "multiline": True}}]})


@app.view("answer")
def on_answer(ack, body, client, view):
    ack()
    meta, user = json.loads(view["private_metadata"]), body["user"]["id"]
    text = view["state"]["values"]["t"]["t"]["value"] or ""
    act(user, meta["value"], text,
        lambda m: client.chat_postEphemeral(channel=meta["ch"], user=user, text=m),
        lambda login, reply: finish(client, meta["ch"], meta["ts"], meta["blocks"], login, reply))


if __name__ == "__main__":
    SocketModeHandler(app, secret("SLACK_APP_TOKEN")).start()
