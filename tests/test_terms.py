"""Retired wording (docs/glossary.md) stays retired: none of it in any tracked file, and the digest's headings match
board.py's one table of status names."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugins/agentkit/scripts"))
import board  # noqa: E402

RETIRED = ("Claude Code + Slack mode", "Needs a human", "--interface claude-slack", "/agentkit:next", "/agentkit:research",
           "/agentkit:rfc", "Next up", "Handed over to you", "gh agentkit migrate", "Ask the owner to add you")
SKIP = ("docs/superpowers/", "docs/glossary.md", "tests/test_terms.py")  # old specs, and the two files that name the words

failed = 0
for f in subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).split():
    if f.startswith(SKIP) or not (ROOT / f).is_file():
        continue
    text = (ROOT / f).read_text(errors="replace")
    for word in RETIRED:
        if word in text:
            failed += 1
            print(f"FAIL: {f} says {word!r}")

digest = (ROOT / ".github/workflows/digest.yml").read_text()
for status in ("needs-info", "needs-human", "needs-verification", "needs-approval", "blocked"):
    line = f"status:{status}|{board.SAYS[status]}"
    if line not in digest:
        failed += 1
        print(f"FAIL: digest.yml's default statuses lack {line!r}")

print("ok: retired terms" if not failed else f"{failed} failed")
sys.exit(1 if failed else 0)
