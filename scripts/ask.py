#!/usr/bin/env python3
"""How an agent asks the person (Claude Code + Slack mode): the implementer's STUCK line, refine's research key, and
the stuck message the kit posts. Python 3.9+, stdlib only. Agent text is untrusted: it is validated here and escaped
before it reaches a comment.

  ask.py stuck < claude-final-message
      The last line that starts with `STUCK: `, as compact JSON, when it is an object with `kind` "question" or
      "research", a non-empty string `text`, and `why`/`checked` strings when present. Otherwise nothing (an invalid
      STUCK line is treated as absent).
  ask.py research < verdict-json
      Refine's optional `research` key: 1-3 non-empty strings of at most 300 characters. Prints each on one line
      (whitespace collapsed). Absent: nothing. Invalid: nothing, and a ::warning:: on stderr.
  ask.py message < stuck-json
      The stuck message for the issue: each field on one line, `<!--` escaped to `&lt;!--`, cut at 2000 characters.
"""
import json
import sys

KINDS = ("question", "research")
BUTTON = "Answer with the Comment button on this issue's card in Slack."
REPLY = "Reply with an answer, `research <what to find out>`, or `block <reason>`."
FIELD_MAX = 2000


def one_line(s, limit=None):
    s = " ".join(s.replace("<!--", "&lt;!--").split())
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + " …"
    return s


def valid_stuck(d):
    return (isinstance(d, dict) and d.get("kind") in KINDS
            and isinstance(d.get("text"), str) and d["text"].strip() != ""
            and all(isinstance(d[k], str) for k in ("why", "checked") if k in d))


def stuck(text):
    lines = [l[len("STUCK: "):] for l in text.splitlines() if l.startswith("STUCK: ")]
    if not lines:
        return None
    try:
        d = json.loads(lines[-1])
    except ValueError:
        return None
    return d if valid_stuck(d) else None


def research(verdict):
    """The questions, or None when the key is absent; raises ValueError when it is invalid."""
    try:
        v = json.loads(verdict)
    except ValueError:
        raise ValueError("the verdict is not JSON")
    if not isinstance(v, dict) or "research" not in v:
        return None
    r = v["research"]
    if not (isinstance(r, list) and 1 <= len(r) <= 3
            and all(isinstance(q, str) and q.strip() and len(q) <= 300 for q in r)):
        raise ValueError("research must be 1-3 non-empty strings of at most 300 characters")
    return [one_line(q) for q in r]


def message(d):
    def field(k):
        return one_line(d.get(k) or "", FIELD_MAX) or "(not given)"
    return "\n".join([
        f"**Stuck on:** {field('text')}",
        f"**Why I can't decide alone:** {field('why')}",
        f"**Checked:** {field('checked')}",
        "",
        REPLY,
        BUTTON,
    ])


def main(argv):
    if len(argv) != 1 or argv[0] not in ("stuck", "research", "message"):
        print(__doc__, file=sys.stderr)
        return 2
    text = sys.stdin.buffer.read().decode("utf-8", "replace")
    if argv[0] == "stuck":
        d = stuck(text)
        if d is not None:
            print(json.dumps(d, separators=(",", ":")))
    elif argv[0] == "research":
        try:
            qs = research(text)
        except ValueError as e:
            print(f"::warning::ignoring the verdict's research key: {e}", file=sys.stderr)
            qs = None
        for q in qs or []:
            print(q)
    else:
        d = json.loads(text)
        if not valid_stuck(d):
            print("ask.py: not a valid STUCK object", file=sys.stderr)
            return 2
        print(message(d))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
