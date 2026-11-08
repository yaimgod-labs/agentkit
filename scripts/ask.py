#!/usr/bin/env python3
"""How an agent asks the person (Claude Code + Slack mode): the implementer's STUCK line, refine's research key, and
the stuck message the kit posts. Python 3.9+, stdlib only. Agent text is untrusted: it is validated here and escaped
before it reaches a comment.

  ask.py stuck < claude-final-message
      The last line that starts with `STUCK: `, as compact JSON, when it is an object with `kind` "question" or
      "research", a non-empty string `text`, and `why`/`checked` strings when present. Each field is at most 2000
      characters, and a research `text` at most 300 (refine's rule). Optional `options`: 1-3 strings of at most 40
      characters, the answers the Slack card offers as buttons. Otherwise nothing: an invalid STUCK line, or
      one that cannot be parsed at all (deep nesting), is treated as absent, and the command never fails on it.
  ask.py research < verdict-json
      Refine's optional `research` key: 1-3 non-empty strings of at most 300 characters. Prints each on one line
      (whitespace collapsed). Absent: nothing. Invalid: nothing, and a ::warning:: on stderr.
  ask.py message < stuck-json
      The stuck message for the issue (for either kind): each field on one line, `<!--` escaped to `&lt;!--`.
  ask.py nested < issue-json ({labels, body}, as `gh issue view --json labels,body` prints it)
      `true` when the issue is research already (label type:research, or the kit's `<!-- agentkit:research-for #`
      marker in its body), else `false`. Such an issue files no further research: its research questions go to a
      person as stuck messages, so research stays one level deep. Unreadable or unexpected input prints `true` (fail safe).
"""
import json
import sys

KINDS = ("question", "research")
BUTTON = "Answer with the Comment button on this issue's card in Slack."
REPLY = "Reply with an answer, `research <what to find out>`, or `block <reason>`."
FIELD_MAX = 2000
RESEARCH_MAX = 300
MARKER = "<!-- agentkit:research-for #"


def one_line(s):
    return " ".join(s.replace("<!--", "&lt;!--").split())


def valid_stuck(d):
    return (isinstance(d, dict) and d.get("kind") in KINDS
            and isinstance(d.get("text"), str) and d["text"].strip() != ""
            and len(d["text"]) <= (RESEARCH_MAX if d["kind"] == "research" else FIELD_MAX)
            and all(isinstance(d[k], str) and len(d[k]) <= FIELD_MAX for k in ("why", "checked") if k in d)
            and ("options" not in d or valid_options(d["options"])))


def valid_options(o):
    """The answers an agent offers as buttons: 1-3 non-empty strings of at most 40 characters."""
    return isinstance(o, list) and 1 <= len(o) <= 3 and all(isinstance(x, str) and x.strip() and len(x) <= 40 for x in o)


def stuck(text):
    lines = [l[len("STUCK: "):] for l in text.splitlines() if l.startswith("STUCK: ")]
    if not lines:
        return None
    # anything that goes wrong reading agent text (RecursionError on deep nesting, on Python <= 3.13) means absent
    try:
        d = json.loads(lines[-1])
        return d if valid_stuck(d) else None
    except Exception:
        return None


def nested(text):
    try:
        issue = json.loads(text)
        labels, body = issue.get("labels") or [], issue.get("body") or ""
        if not isinstance(labels, list) or not isinstance(body, str):
            return True  # not the shape gh prints: fail safe
        names = [l.get("name") if isinstance(l, dict) else l for l in labels]
        return "type:research" in names or MARKER in body
    except Exception:
        return True


def research(verdict):
    """The questions, or None when the key is absent; raises ValueError when it is invalid."""
    try:
        v = json.loads(verdict)
    except Exception:
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
        return one_line(d.get(k) or "") or "(not given)"
    return "\n".join([
        f"**Stuck on:** {field('text')}",
        f"**Why I can't decide alone:** {field('why')}",
        f"**Checked:** {field('checked')}",
        *([ "**Options:** " + " | ".join(one_line(o).replace("|", "/") for o in d["options"]) ] if "options" in d else []),
        "",
        REPLY,
        BUTTON,
    ])


def main(argv):
    if len(argv) != 1 or argv[0] not in ("stuck", "research", "message", "nested"):
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
        except Exception as e:
            print(f"::warning::ignoring the verdict's research key: {e}", file=sys.stderr)
            qs = None
        for q in qs or []:
            print(q)
    elif argv[0] == "nested":
        print("true" if nested(text) else "false")
    else:
        try:
            d = json.loads(text)
        except Exception:
            d = None
        if not valid_stuck(d):
            print("ask.py: not a valid STUCK object", file=sys.stderr)
            return 2
        print(message(d))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
