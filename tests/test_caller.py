"""caller.py merge: the template's jobs and triggers, the project's `with:` blocks, refs and extra jobs."""
import subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests/fixture-callers"
TEMPLATE = ROOT / "templates/.github/workflows/agentkit.yml"
fails = 0


FILLED = FIX / "template.filled.yml"  # what `gh agentkit` passes: placeholders filled in
FILLED.write_text(TEMPLATE.read_text().replace("your-org/agentkit", "example-org/agentkit"))


def merge(existing):
    return subprocess.run([sys.executable, str(ROOT / "cli/gh-agentkit/caller.py"), str(FILLED), str(existing)],
                          capture_output=True, text=True, check=True).stdout


def expect(name, cond, detail=""):
    global fails
    print(("ok: " if cond else "FAIL: ") + name + ("" if cond else f"\n{detail}"))
    fails += not cond


cur = (FIX / "current.yml").read_text()
out = merge(FIX / "current.yml")
def code(text):  # comments may differ: upgrade brings the template's explanatory comments along
    return [l for l in text.splitlines() if not l.lstrip().startswith("#")]
expect("an up-to-date caller is unchanged (comments aside)", code(out) == code(cur), out)

out = merge(FIX / "old.yml")
expect("old caller gains the refine job", "\n  refine:\n" in out and "refine.yml@main" in out, out)
expect("old caller gains the edited PR event", "ready_for_review, edited, closed]" in out, out)
expect("old caller gains the reply job on the project's pin", "\n  reply:\n" in out and "reply.yml@main" in out, out)
expect("old caller gains the PR review trigger", "  pull_request_review:\n    types: [submitted]\n" in out, out)
expect("project refs kept (no @v1 left)", not any("@v1" in l for l in out.splitlines() if "uses:" in l) and out.count("agentkit-ref: main") == 10, out)
expect("old caller gains the triage job on the project's pin", "\n  triage:\n" in out and "triage.yml@main" in out, out)
expect("old caller gains the card job on the project's pin", "\n  card:\n" in out and "card.yml@main" in out, out)
expect("old caller gains the bot's repository_dispatch trigger",
       "  repository_dispatch:\n    types: [agentkit-slack-reply, agentkit-slack-task]\n" in out, out)
expect("old caller's dispatch job gains SLACK_BOT_TOKEN",
       "SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}" in out.split("\n  dispatch:\n")[1].split("\n  triage:\n")[0], out)
expect("project plugins kept", "ponytail@agentkit" in out, out)
expect("template example comments dropped where the project has with:", "#   plugins:" not in out.split("\n  plan:")[0].split("\n  implement:")[1], out)
expect("project header comment kept", out.startswith("# agentkit CANARY caller"), out)

extra = FIX / "extra.yml"
extra.write_text(cur + "\n  deploy:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n")
out = merge(extra)
extra.unlink()
expect("project-only jobs kept at the end", out.rstrip().endswith("      - run: echo hi") and out.count("\n  deploy:\n") == 1, out)

tpl = TEMPLATE.read_text()
fresh = FIX / "fresh.yml"
fresh.write_text("name: agentkit\non: push\njobs:\n")
out = merge(fresh)
fresh.unlink()
expect("a caller with no kit jobs gets the template's jobs and @v1", "dispatch.yml@v1" in out and "\n  refine:\n" in out, out)

FILLED.unlink()
sys.exit(1 if fails else 0)
