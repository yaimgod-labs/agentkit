#!/usr/bin/env python3
"""The split proposal refine posts for a large task (Claude Code + Slack mode). Python 3.9+, stdlib only. Agent text is
untrusted: it is validated here and escaped before it reaches a comment.

  split.py proposal < verdict-json
      The verdict's `split` key: 2-8 objects, each with a non-empty string `title` and a string `why` (other keys are
      ignored), on a verdict of size m or l. Prints the proposal comment: one line per sub-task, whitespace collapsed,
      `<!--` escaped to `&lt;!--`, at most 200 characters after its number. Missing or invalid (or another size):
      nothing, and a ::warning:: on stderr, so the workflow falls back to posting the plan alone.
"""
import json
import sys

BUTTON = "Answer with the Comment button on this issue's card in Slack."
ITEM_MAX = 200


def one_line(s):
    return " ".join(s.replace("<!--", "&lt;!--").split())


def cut(s, n):
    return s if len(s) <= n else s[:n - 1] + "…"


def items(verdict):
    """The proposal's item lines; raises ValueError when the verdict has no valid split."""
    try:
        v = json.loads(verdict)
    except Exception:
        raise ValueError("the verdict is not JSON")
    if not isinstance(v, dict):
        raise ValueError("the verdict is not an object")
    if v.get("size") not in ("m", "l"):
        raise ValueError("only a size m or l verdict is split")
    s = v.get("split")
    if s is None:
        raise ValueError("the verdict has no split list")
    if not (isinstance(s, list) and 2 <= len(s) <= 8
            and all(isinstance(t, dict) and isinstance(t.get("title"), str) and t["title"].strip()
                    and isinstance(t.get("why"), str) for t in s)):
        raise ValueError("split must be 2-8 objects with a non-empty string title and a string why")
    out = []
    for i, t in enumerate(s, 1):
        title, why = one_line(t["title"]), one_line(t["why"])
        out.append(f"{i}. " + cut(f"{title} — {why}" if why else title, ITEM_MAX))
    return v["size"], out


def proposal(verdict):
    size, lines = items(verdict)
    return "\n".join([f"**Proposed split** (size {size}):", *lines,
                      "Reply `approve` to create these sub-tasks, or say what to change.", BUTTON])


def main(argv):
    if argv != ["proposal"]:
        print(__doc__, file=sys.stderr)
        return 2
    text = sys.stdin.buffer.read().decode("utf-8", "replace")
    # anything that goes wrong reading agent text (RecursionError on deep nesting, on Python <= 3.13) means no split
    try:
        print(proposal(text))
    except Exception as e:
        print(f"::warning::no split proposal, posting the plan alone: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
