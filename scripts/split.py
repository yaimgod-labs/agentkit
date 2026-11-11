#!/usr/bin/env python3
"""The split proposal refine posts for a large task (Slack mode). Python 3.9+, stdlib only. Agent text is
untrusted: it is validated here and escaped before it reaches a comment.

  split.py eligible < verdict-json
      `true` when the task is one the mode splits: size m or l, and type feature, bug, chore or debt (never research or rfc: a question or
      a design is answered in one doc, never split). Otherwise, or on unreadable input, `false`.
  split.py proposal [--questions] < verdict-json
      The verdict's `split` key: 2-8 objects, each with a non-empty string `title` and a string `why` (other keys are
      ignored), on an eligible verdict. Prints the proposal comment: one line per sub-task, whitespace collapsed,
      `<!--` escaped to `&lt;!--`, at most 200 characters after its number. --questions (the plan comment asks
      questions) adds a line asking to answer them first. Missing or invalid (or not eligible): nothing, and a
      ::warning:: on stderr, so the workflow falls back to posting the plan alone.
"""
import json
import sys

BUTTON = "Answer with the Comment button on this issue's card in Slack."
ITEM_MAX = 200
QUESTIONS = "Answer the questions above first if they change the split."


def is_eligible(v):
    return isinstance(v, dict) and v.get("size") in ("m", "l") and v.get("type") in ("feature", "bug", "chore", "debt")


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
    if not is_eligible(v):
        raise ValueError("only a size m or l task that is not research or an RFC is split")
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


def proposal(verdict, questions=False):
    size, lines = items(verdict)
    return "\n".join([f"**Proposed split** (size {size}):", *lines, *([QUESTIONS] if questions else []),
                      "Reply `approve` to create these sub-tasks, or say what to change.", BUTTON])


def main(argv):
    if argv not in (["eligible"], ["proposal"], ["proposal", "--questions"]):
        print(__doc__, file=sys.stderr)
        return 2
    text = sys.stdin.buffer.read().decode("utf-8", "replace")
    if argv[0] == "eligible":
        try:
            ok = is_eligible(json.loads(text))
        except Exception:
            ok = False
        print("true" if ok else "false")
        return 0
    # anything that goes wrong reading agent text (RecursionError on deep nesting, on Python <= 3.13) means no split
    try:
        print(proposal(text, questions=len(argv) == 2))
    except Exception as e:
        print(f"::warning::no split proposal, posting the plan alone: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
