#!/usr/bin/env python3
"""The Slack "task done" text for a merged agent PR (Slack mode). Python 3.9+, stdlib only.

  done.py < {"number": <issue>, "title": <issue title>, "body": <PR body or null>, "url": <PR URL>}
      `Task #<n> done: <title>`, a blank line, the PR body's `## Summary` section (up to the next `## ` heading, at
      most 1500 characters), a blank line, the URL. No Summary (or an empty one): the first line and the URL. The PR
      body and the title are agent text: the title is put on one line, and Slack's control characters (& < >) are
      escaped everywhere, which escapes `<!--` to `&lt;!--` too. Bad input exits 2.
"""
import json
import sys

SUMMARY_MAX = 1500


def slack(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def summary(body):
    out, inside = [], False
    for line in (body or "").splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line.rstrip() == "## Summary"
            continue
        if inside:
            out.append(line)
    s = "\n".join(out).strip()
    return s if len(s) <= SUMMARY_MAX else s[:SUMMARY_MAX - 1] + "…"


def text(d):
    first = f"Task #{d['number']} done: {' '.join(d['title'].split())}"
    parts = [first, summary(d.get("body")), d["url"]]
    return slack("\n\n".join(p for p in parts if p))


def main(argv):
    try:
        d = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        ok = (isinstance(d, dict) and isinstance(d.get("number"), int) and not isinstance(d["number"], bool)
              and isinstance(d.get("title"), str) and isinstance(d.get("url"), str) and isinstance(d.get("body"), (str, type(None))))
    except Exception:
        ok = False
    if argv or not ok:
        print(__doc__, file=sys.stderr)
        return 2
    print(text(d))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
