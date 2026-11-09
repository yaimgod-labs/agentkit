#!/usr/bin/env python3
"""PreToolUse guard: block pushes to main/master (and the kit's base branch, env AGENTKIT_BASE such as
origin/develop), force pushes, hard resets, and file edits outside the current worktree. Exit 2 blocks the tool call."""
import json, os, re, subprocess, sys

PROTECTED = ("main", "master", os.environ.get("AGENTKIT_BASE", "").removeprefix("origin/").removeprefix("refs/heads/") or "main")


def block(reason):
    print(f"agentkit guard: {reason}", file=sys.stderr)
    sys.exit(2)


def git(*args, cwd):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def check_bash(cmd, cwd):
    for part in re.split(r"&&|\|\||;|\n|\|", cmd):
        words = part.split()
        if "git" not in words:
            continue
        rest = words[words.index("git") + 1:]
        # skip git global options such as -C <dir>
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in ("-C", "-c") else rest[1:]
        if not rest:
            continue
        sub, args = rest[0], rest[1:]
        if sub == "reset" and "--hard" in args:
            block("git reset --hard is not allowed")
        if sub == "push":
            if any(a in ("-f", "--force", "--force-with-lease", "--mirror", "--delete", "-d") or a.startswith("--force") or a.startswith("+") for a in args):
                block("force, mirror and delete pushes are not allowed")
            refs = [a for a in args if not a.startswith("-")][1:]  # drop remote
            targets = [r.split(":")[-1].removeprefix("refs/heads/") for r in refs]
            current = git("symbolic-ref", "--short", "HEAD", cwd=cwd)  # works on unborn branches too
            targets = [current if t == "HEAD" else t for t in targets] or [current]
            if any(t in PROTECTED for t in targets):
                block("pushing to the base branch is not allowed; push a feature branch and open a PR")


def check_path(path, root):
    full = os.path.realpath(os.path.join(root, path))
    if full != root and not full.startswith(root + os.sep):
        block(f"{path} is outside the task worktree {root}")


def main():
    data = json.load(sys.stdin)
    tool, inp = data.get("tool_name", ""), data.get("tool_input", {}) or {}
    cwd = data.get("cwd") or os.getcwd()
    if tool == "Bash":
        check_bash(inp.get("command", ""), cwd)
        return
    path = inp.get("file_path") or inp.get("notebook_path")
    if path:
        project = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
        root = os.path.realpath(git("rev-parse", "--show-toplevel", cwd=cwd) or project)
        check_path(path, root)


if __name__ == "__main__":
    main()
