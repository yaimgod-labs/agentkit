#!/usr/bin/env python3
"""A Decide card for the kit's Slack bot (slack-bot interface): short, built from fields, never from raw comments.
Python 3.9+, stdlib only.

  card.py build < {"repo", "number", "title", "labels": [...], "ask"?, "options"?: [str], "comments"?: [str]}
      Prints the Slack message as JSON {"text", "blocks"}. `ask` and `options` come from `comments` (the kit's comment bodies, oldest first; see derive()) when not given;
      `ask` falls back to "Needs your input". Buttons come from
      reply.py's keyword table for the issue's status: a keyword without an argument is a button, one that needs an
      argument opens a modal (`Name…`), and free text is `Other…`. `options` (agent-written answers) come first.
      A Verify card (needs-verification) asks for the unticked `- [ ]` items of the kit's latest comment (up to 3,
      joined by " · ") and has `Verified` and `Failed…` (free text, a failed check) only. An Attention card
      (needs-human with reason:env or reason:agent-error: a failed run) asks the why without its links and has `Retry`,
      `Block…` and a `Logs` link button (the run in the kit's latest comment, else the issue).
  card.py lint < card-json
      Exit 1 and a message per breach: title over 80 chars, ask over 160, more than 3 answer buttons (the free-text
      modal and a link button are not), or more than one link in the text.
  card.py done < {"number", "title", "body", "url"}
      A Done card for a merged agent PR (title, the first line of the PR's `## Summary`, link; no buttons), linted and
      posted as `post` does. Prints the message ts.
  card.py resolve < {"repo", "number", "title", "state", "stateReason", "labels", "comments": [kit comment bodies]}
      Edits each card found through the issue's `<!-- agentkit:card channel=C ts=T -->` comments to the issue's
      outcome (closed, or its new status), without buttons. Prints how many.
  card.py marker < ts-json      the marker comment body for a card just posted (env SLACK_CHANNEL)
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
# a card kind other than Decide shows only some of its status's keywords, and names the free-text modal
KINDS = {"verify": (["verified"], "Failed…"), "attention": (["retry", "block"], None)}
FAILED = {"reason:env", "reason:agent-error"}  # the kit's handover after a failed run or step: an Attention card


def clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def plain(line):
    """A markdown line as plain text for a card: no quote, heading, bold or code marks."""
    return " ".join(line.lstrip("> #-").replace("**", "").replace("`", "").split())


def derive(comments):
    """(ask, options) from the kit's comments on a waiting issue, oldest first: the latest one that says what it
    needs. A STUCK message: its `Stuck on` and `Options` lines. An RFC or research recommendation: its first line.
    Refine's `## Questions`: the first question's `Stuck on` text, with a "Use the default" option when it names a
    default. An option is a string or a (label, text) pair.
    Anything else: the first line of the latest comment. Missing: (None, [])."""
    for body in reversed(comments):
        if body.startswith("<!-- agentkit:recommendation -->"):
            lines = [plain(l) for l in body.splitlines()[1:] if plain(l)]
            # a first line that ends in ":" introduces the next one: "Adopt C: 1. constants live in their module"
            ask = " ".join(lines[:2]) if lines and lines[0].endswith(":") else (lines[0] if lines else "")
            return ask or None, []
        m = re.search(r"^\*\*Stuck on:\*\* (.+)$", body, re.M)
        if m:
            o = re.search(r"^\*\*Options:\*\* (.+)$", body, re.M)
            return plain(m.group(1)), [x.strip() for x in o.group(1).split(" | ")][:BUTTONS_MAX] if o else []
        q = re.search(r"^## Questions\s*\n+\s*(?:1\.|-)\s*(.+)$", body, re.M)
        if q:  # refine's open questions: the first one's "Stuck on" part; its default, if any, is a one-click answer
            text, *default = re.split(r"\s*—?\s*default if unanswered:?\s*", q.group(1), maxsplit=1, flags=re.I)
            ask = re.split(r"\*\*(?:Why|Checked):\*\*", re.sub(r"^\*\*Stuck on:\*\*\s*", "", text))[0]
            default = plain(default[0]) if default else ""
            return plain(ask), [("Use the default", f"Use the default: {default}")] if default else []
        line = next((l for l in body.splitlines() if plain(l) and not l.startswith("<!--")), "")
        if plain(line):
            return plain(line), []
    return None, []


def latest(comments):
    """The kit's latest comment with visible text (a card marker has none), or ""."""
    return next((b for b in reversed(comments) if any(plain(l) for l in b.splitlines() if not l.startswith("<!--"))), "")


def unticked(comments):
    """The unticked `- [ ]` items of the kit's latest comment, plain (a needs-verification ping lists them)."""
    return [plain(m) for m in re.findall(r"^\s*- \[ \] (.+)$", latest(comments), re.M)]


def build(issue):
    labels = issue.get("labels", [])
    status = next((l[len("status:"):] for l in labels if l.startswith("status:")), "")
    kind = ("verify" if status == "needs-verification" else
            "attention" if status == "needs-human" and FAILED & set(labels) else "decide")
    items = unticked(issue.get("comments", [])) if kind == "verify" else []
    if items and not issue.get("ask"):
        issue = {**issue, "ask": " · ".join(items[:3])}
    if "comments" in issue and not issue.get("ask"):
        issue = {**issue, **dict(zip(("ask", "options"), derive(issue["comments"])))}
    repo, n = issue["repo"], issue["number"]
    ref = f"{repo}#{n}"
    url = f"https://github.com/{repo}/issues/{n}"
    links = []
    if kind == "attention":  # the why without its links; the run's link is the Logs button (else the issue's)
        issue = {**issue, "ask": re.sub(r"\s*(?:PR: )?\(?https?://[^\s)]+\)?", "", issue.get("ask") or "")}
        run = re.search(r"https://\S+?/actions/runs/[0-9]+", latest(issue.get("comments", [])))
        links = [{"type": "button", "text": {"type": "plain_text", "text": "Logs"}, "action_id": "logs",
                  "url": run.group(0) if run else url}]
    parsed = reply.parse("", labels)
    shown, other = KINDS.get(kind, (parsed["keywords"], "Other…"))
    # an option is its text, or a (label, text) pair when the text is too long for a button
    pairs = [(o, o) if isinstance(o, str) else tuple(o) for o in issue.get("options") or []]
    buttons = [(clip(label, 40), f"{ref}|{text}"[:2000], "reply") for label, text in pairs][:BUTTONS_MAX]  # Slack: value ≤ 2000
    for kw in [k for k in parsed["keywords"] if k in shown]:
        if len(buttons) >= BUTTONS_MAX:
            break
        if kw in reply.NEEDS_ARG:
            buttons.append((kw.capitalize() + "…", f"{ref}|{kw}", "modal"))
        else:
            buttons.append((LABEL.get(kw, kw.capitalize()), f"{ref}|{kw}", "reply"))
    if parsed["free_text"] and other:
        buttons.append((other, f"{ref}|", "modal"))
    title = clip(issue["title"], TITLE_MAX)
    ask = clip(issue.get("ask") or FALLBACK_ASK, ASK_MAX)
    return {
        "text": f"{title}: {ask}",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*\n{ask}\n<{url}|#{n}>"}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": label}, "action_id": f"{how}_{i}", "value": value}
                for i, (label, value, how) in enumerate(buttons)
            ] + links},
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
    # the free-text modal (its value ends in "|") and a link button (no value) are not answers
    answers = [e for e in (card["blocks"][1]["elements"] if len(card["blocks"]) > 1 else []) if not e.get("value", "|").endswith("|")]
    if len(answers) > BUTTONS_MAX:
        bad.append(f"{len(answers)} answer buttons, max {BUTTONS_MAX}")
    if text.count("<http") > 1:
        bad.append("more than one link")
    return bad


def done(d):
    """A Done card for a merged agent PR: title, the first line of the PR body's `## Summary`, a link to the PR.
    No buttons. d = {"number", "title", "body", "url"} (as done.py takes)."""
    import done as done_text  # the long done message's Summary rule, one definition
    line = next((plain(l) for l in done_text.summary(d.get("body")).splitlines() if plain(l)), "Merged.")
    title = clip("✓ " + str(d["title"]), TITLE_MAX)
    return {"text": f"{title}: {clip(line, ASK_MAX)}",
            "blocks": [{"type": "section", "text": {"type": "mrkdwn",
                        "text": f"*{title}*\n{clip(line, ASK_MAX)}\n<{d['url']}|#{d['number']}>"}}]}


def post(issue):
    return send(build(issue))


def slack(method, payload):
    """One Slack Web API call with env SLACK_BOT_TOKEN. A network error (DNS, timeout, reset) is tried again; Slack's
    own error answer is not."""
    req = urllib.request.Request(
        "https://slack.com/api/" + method, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + os.environ["SLACK_BOT_TOKEN"], "Content-Type": "application/json; charset=utf-8"},
    )
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
    return res


def send(card):
    """Lint, then chat.postMessage to env SLACK_CHANNEL. Returns the message ts."""
    bad = lint(card)
    if bad:
        sys.exit("card.py: " + "; ".join(bad))
    return slack("chat.postMessage", {"channel": os.environ["SLACK_CHANNEL"], **card})["ts"]


MARKER = re.compile(r"^<!-- agentkit:card channel=([A-Z0-9]+) ts=([0-9]+\.[0-9]+) -->$")


def marker(ts):
    """The hidden comment the card job leaves on the issue, so the card can be found and resolved later."""
    return f"<!-- agentkit:card channel={os.environ['SLACK_CHANNEL']} ts={ts} -->"


def outcome(issue):
    if issue.get("state") == "CLOSED":
        return "Closed" + (" as done" if issue.get("stateReason") == "COMPLETED" else "")
    status = next((l[len("status:"):] for l in issue.get("labels", []) if l.startswith("status:")), "")
    return f"No longer waiting: now {status}" if status else "No longer waiting"


def resolve(issue):
    """Edit every card the kit posted for this issue (its marker comments) to the issue's outcome, without buttons.
    issue = {"repo", "number", "title", "state", "stateReason", "labels", "comments": [kit comment bodies]}."""
    title = clip(issue["title"], TITLE_MAX)
    url = f"https://github.com/{issue['repo']}/issues/{issue['number']}"
    text = f"*{title}*\n{outcome(issue)}\n<{url}|#{issue['number']}>"
    done = 0
    for body in issue.get("comments", []):
        m = MARKER.match(body.strip())
        if m:
            slack("chat.update", {"channel": m.group(1), "ts": m.group(2), "text": f"{title}: {outcome(issue)}",
                                  "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]})
            done += 1
    return done


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
    elif cmd == "marker":
        print(marker(data))
    elif cmd == "resolve":
        print(resolve(data))
    elif cmd == "done":
        print(send(done(data)))
    else:
        sys.exit(__doc__)
