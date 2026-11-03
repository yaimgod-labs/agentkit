#!/usr/bin/env python3
"""Maps a person's reply on a waiting issue to the action a workflow applies (Claude Code + Slack mode).
Python 3.9+, stdlib only.

  reply.py
      stdin:  {"body": "approve", "labels": ["status:needs-approval", "type:research", ...], "has_pr": false}
      stdout: {"action": "approve-research", "arg": ""} as one JSON object. Invalid JSON on stdin: message on
              stderr, exit 2. `has_pr` is accepted and not used yet.

The reply is matched case-insensitively, after strip(), on its first word with trailing `.,:!` removed. A
keyword valid for the issue's status gives that status's action; `arg` is the rest of the text after the keyword.
Any other text is free text: the status's free-text action, `arg` the whole body. A keyword that is not valid
for the status gives `hint` with the keyword as `arg`, and so does a keyword that needs an argument and has none
(research, block, replace, accept, reject). `replace` takes `#42` or `42`; `arg` is the digits. An empty body
is `hint` with an empty `arg`. A status the table does not list (and `ready` without `mode:human`) gives
`none`: the workflow does nothing.

The status is the issue's `status:*` label. needs-approval is split by `type:*`: research, rfc, or any other
type (a split proposal).
"""
import json
import re
import sys

KEYWORDS = {"approve", "research", "block", "unblock", "replace", "verified", "accept", "reject", "retry", "done"}
NEEDS_ARG = {"research", "block", "replace", "accept", "reject"}

# (status, kind) -> ({keyword: action}, free-text action)
TABLE = {
    ("needs-info", ""): ({"research": "research", "block": "block"}, "answer"),
    ("needs-human", ""): ({"retry": "retry", "research": "research", "block": "block"}, "guide"),
    ("needs-verification", ""): ({"verified": "verified", "block": "block"}, "failed-check"),
    ("needs-approval", "research"): ({"approve": "approve-research", "block": "block"}, "override-research"),
    ("needs-approval", "rfc"): ({"accept": "decide", "reject": "decide", "block": "block"}, "hint"),
    ("needs-approval", "split"): ({"approve": "approve-split", "block": "block"}, "split-feedback"),
    ("blocked", ""): ({"unblock": "unblock", "replace": "replace"}, "hint"),
    ("ready", "human"): ({"done": "done", "block": "block"}, "hint"),
}


def out(action, arg=""):
    return {"action": action, "arg": arg}


def table_key(labels):
    status = next((l[len("status:"):] for l in labels if l.startswith("status:")), "")
    if status == "needs-approval":
        types = {l[len("type:"):] for l in labels if l.startswith("type:")}
        return (status, "research" if "research" in types else "rfc" if "rfc" in types else "split")
    if status == "ready":
        return (status, "human" if "mode:human" in labels else "none")
    return (status, "")


def parse(body, labels):
    entry = TABLE.get(table_key(labels))
    if entry is None:
        return out("none")
    keywords, free = entry
    text = (body or "").strip()
    if not text:
        return out("hint")
    first, *more = text.split(None, 1)
    word = first.rstrip(".,:!").lower()
    rest = more[0].strip() if more else ""
    if word not in KEYWORDS:
        return out(free, text)
    if word not in keywords or (word in NEEDS_ARG and not rest):
        return out("hint", word)
    if word == "replace":
        m = re.fullmatch(r"#?(\d+)", rest)
        return out("replace", m.group(1)) if m else out("hint", word)
    if keywords[word] == "decide":
        return out("decide", f"{word} {rest}")
    return out(keywords[word], rest)


def main():
    try:
        data = json.load(sys.stdin)
        body, labels = data.get("body", ""), list(data.get("labels", []))
    except (ValueError, AttributeError, TypeError) as e:
        print(f"reply.py: invalid input: {e}", file=sys.stderr)
        return 2
    print(json.dumps(parse(body, labels)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
