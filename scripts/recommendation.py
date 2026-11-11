#!/usr/bin/env python3
"""The recommendation of a research or RFC doc, quoted for the kit's needs-approval comment (Slack mode).
Python 3.9+, stdlib only.

  recommendation.py research|rfc [MAX_CHARS] < doc.md
      Prints the doc's recommendation as a Markdown blockquote: every line starts with `>`, and `<!--` is escaped
      to `&lt;!--`, so the agent-written doc can never forge a kit marker or a line of the kit's comment.
      rfc: the section under the first heading that starts with "Recommend" (Recommendation, Recommended option).
      research: the first heading that starts with "Answer" (the implement-issue skill's fixed heading); without
      one, the first that starts with "Recommend" or "Conclusion".
      A section runs to the next heading of the same or a higher level; headings inside code fences don't count.
      No such heading, or an empty section: the whole doc, front matter dropped.
      Over MAX_CHARS (default 4000) the text is cut at a line and ends with `> …`. An empty doc prints nothing.
"""
import re
import sys

# heading prefixes in order of preference: the first group that matches a heading wins
NAMES = {"rfc": [("recommend",)], "research": [("answer",), ("recommend", "conclusion")]}
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def body(lines):
    """The doc without its YAML front matter."""
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return lines[i + 1:]
    return lines


def section(lines, names):
    start = level = None
    fence = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        m = None if fence else HEADING.match(line)
        if not m:
            continue
        if start is None:
            title = re.sub(r"^[^A-Za-z]+", "", m.group(2)).lower()  # "2. Recommendation", "**Answer**"
            if title.startswith(names):
                start, level = i + 1, len(m.group(1))
        elif len(m.group(1)) <= level:
            return lines[start:i]
    return lines[start:] if start is not None else []


def trim(lines):
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def recommendation(text, kind, limit=4000):
    lines = body(text.splitlines())
    picked = next((s for s in (trim(section(lines, names)) for names in NAMES[kind]) if s), None) or trim(lines)
    out, size = [], 0
    for line in picked:
        line = line.rstrip().replace("<!--", "&lt;!--")
        if size + len(line) + 1 > limit:
            if not out:  # one very long first line: cut inside it
                out.append(line[:limit])
            out.append("…")
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(("> " + l) if l else ">" for l in out)


def main(argv):
    if not argv or argv[0] not in NAMES or len(argv) > 2 or (len(argv) == 2 and not argv[1].isdigit()):
        print(__doc__, file=sys.stderr)
        return 2
    text = sys.stdin.buffer.read().decode("utf-8", "replace")
    out = recommendation(text, argv[0], int(argv[1]) if len(argv) == 2 else 4000)
    if out:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
