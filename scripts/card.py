#!/usr/bin/env python3
"""A Decide card for the kit's Slack bot (slack-bot interface): short, built from fields, never from raw comments.
Python 3.9+, stdlib only.

  card.py build < {"repo", "number", "title", "labels": [...], "ask"?, "options"?: [str], "comments"?: [str]}
      Prints the Slack message as JSON {"text", "blocks"}. `ask` and `options` come from `comments` (the kit's comment bodies, oldest first; see derive()) when not given;
      `ask` falls back to "Needs your input". Buttons come from
      reply.py's keyword table for the issue's status: a keyword without an argument is a button, one that needs an
      argument opens a modal (`Name…`), and free text is `Other…`. `options` (agent-written answers) come first.
  card.py lint < card-json
      Exit 1 and a message per breach: title over 80 chars, ask over 160, more than 3 answer buttons, or more than one link.
  card.py post < issue-json
      build + lint, then chat.postMessage to env SLACK_CHANNEL with env SLACK_BOT_TOKEN. Prints the message ts.

A button's value is `<owner/repo>#<n>|<text>` (text sent as the reply) or, for a modal, `<owner/repo>#<n>|<keyword>`.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reply  # noqa: E402

TITLE_MAX, ASK_MAX, BUTTONS_MAX = 80, 160, 3
FALLBACK_ASK = "Needs your input"
LABEL = {"approve": "Approve", "accept": "Accept", "verified": "Verified", "retry": "Retry", "unblock": "Unblock", "done": "Done"}


def clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def plain(line):
    """A markdown line as plain text for a card: no quote, heading, bold or code marks."""
    return " ".join(line.lstrip("> #-").replace("**", "").replace("`", "").split())


def derive(comments):
    """(ask, options) from the kit's comments on a waiting issue, oldest first: the latest one that says what it
    needs. A STUCK message: its `Stuck on` and `Options` lines. An RFC or research recommendation: its first line.
    Anything else: the first line of the latest comment. Missing: (None, [])."""
    for body in reversed(comments):
        if body.startswith("<!-- agentkit:recommendation -->"):
            line = next((l for l in body.splitlines()[1:] if plain(l)), "")
            return plain(line) or None, []
        m = re.search(r"^\*\*Stuck on:\*\* (.+)$", body, re.M)
        if m:
            o = re.search(r"^\*\*Options:\*\* (.+)$", body, re.M)
            return plain(m.group(1)), [x.strip() for x in o.group(1).split(" | ")][:BUTTONS_MAX] if o else []
        line = next((l for l in body.splitlines() if plain(l) and not l.startswith("<!--")), "")
        if plain(line):
            return plain(line), []
    return None, []


def build(issue):
    if "comments" in issue and not issue.get("ask"):
        issue = {**issue, **dict(zip(("ask", "options"), derive(issue["comments"])))}
    repo, n = issue["repo"], issue["number"]
    ref = f"{repo}#{n}"
    parsed = reply.parse("", issue.get("labels", []))
    buttons = [(clip(o, 40), f"{ref}|{o}", "reply") for o in issue.get("options") or []][:BUTTONS_MAX]
    for kw in parsed["keywords"]:
        if len(buttons) >= BUTTONS_MAX:
            break
        if kw in reply.NEEDS_ARG:
            buttons.append((kw.capitalize() + "…", f"{ref}|{kw}", "modal"))
        else:
            buttons.append((LABEL.get(kw, kw.capitalize()), f"{ref}|{kw}", "reply"))
    if parsed["free_text"]:
        buttons.append(("Other…", f"{ref}|", "modal"))
    title = clip(issue["title"], TITLE_MAX)
    ask = clip(issue.get("ask") or FALLBACK_ASK, ASK_MAX)
    url = f"https://github.com/{repo}/issues/{n}"
    return {
        "text": f"{title}: {ask}",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\n{ask}\n<{url}|#{n}>"}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": label}, "action_id": f"{kind}_{i}", "value": value}
                for i, (label, value, kind) in enumerate(buttons)
            ]},
        ],
    }


def lint(card):
    bad = []
    text = card["blocks"][0]["text"]["text"]
    title, ask = text.split("\n")[0].strip("*"), text.split("\n")[1]
    if len(title) > TITLE_MAX:
        bad.append(f"title is {len(title)} chars, max {TITLE_MAX}")
    if len(ask) > ASK_MAX:
        bad.append(f"ask is {len(ask)} chars, max {ASK_MAX}")
    answers = [e for e in card["blocks"][1]["elements"] if e["text"]["text"] != "Other…"]
    if len(answers) > BUTTONS_MAX:
        bad.append(f"{len(answers)} answer buttons, max {BUTTONS_MAX}")
    if text.count("<http") > 1:
        bad.append("more than one link")
    return bad


def post(issue):
    card = build(issue)
    bad = lint(card)
    if bad:
        sys.exit("card.py: " + "; ".join(bad))
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=json.dumps({"channel": os.environ["SLACK_CHANNEL"], **card}).encode(),
        headers={"Authorization": "Bearer " + os.environ["SLACK_BOT_TOKEN"], "Content-Type": "application/json; charset=utf-8"},
    )
    # a network error (DNS, timeout, reset) is tried again; Slack's own answer is not
    for attempt in range(5):
        try:
            res = json.load(urllib.request.urlopen(req, timeout=20))
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == 4:
                sys.exit(f"card.py: Slack unreachable: {e}")
            time.sleep(10)
    if not res.get("ok"):
        sys.exit("card.py: Slack said " + str(res.get("error")))
    return res["ts"]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    data = json.load(sys.stdin)
    if cmd == "build":
        print(json.dumps(build(data)))
    elif cmd == "lint":
        bad = lint(data)
        print("\n".join(bad))
        sys.exit(1 if bad else 0)
    elif cmd == "post":
        print(post(data))
    else:
        sys.exit(__doc__)
