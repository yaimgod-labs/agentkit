#!/usr/bin/env python3
"""Merge a project's agentkit caller workflow with the kit's template.

  caller.py <template.yml> <existing.yml>   prints the merged caller

The template supplies the triggers and every kit job (its `if:` and `secrets:`).
The project keeps, per job, its `uses:` ref and its whole `with:` block, its
leading header comment, and any job the template does not have (appended last).
Plain text, no YAML library: callers follow the template's two-space layout.
"""
import re
import sys

JOB = re.compile(r"^  ([A-Za-z_][\w-]*):\s*$")


def split(text):
    lines = text.splitlines(keepends=True)
    i = next((k for k, l in enumerate(lines) if l.rstrip() == "jobs:"), len(lines) - 1)
    jobs, cur = {}, None
    for line in lines[i + 1:]:
        m = JOB.match(line)
        if m:
            cur = m.group(1)
            jobs[cur] = []
        if cur:
            jobs[cur].append(line)
    return lines[:i + 1], jobs


def with_block(job):
    for k, line in enumerate(job):
        if line.rstrip() == "    with:":
            end = k + 1
            while end < len(job) and job[end].startswith("      "):
                end += 1
            return k, end
    return None


def ref(job):
    for line in job:
        m = re.search(r"uses: \S+@(\S+)", line)
        if m:
            return m.group(1)
    return None


def merge_job(tpl, ex):
    keep, r = with_block(ex), ref(ex)
    skip = with_block(tpl) if keep else None
    out, after_uses = [], False
    for k, line in enumerate(tpl):
        if skip and skip[0] <= k < skip[1]:
            continue
        if keep and after_uses and line.lstrip().startswith("#"):
            continue  # the template's commented `with:` examples; the project has its own
        if "uses:" in line:
            if r:
                line = re.sub(r"@\S+", "@" + r, line)
            out.append(line)
            if keep:
                out += ex[keep[0]:keep[1]]
            after_uses = True
            continue
        out.append(line)
    return out


def leading_comments(lines):
    n = 0
    while n < len(lines) and lines[n].startswith("#"):
        n += 1
    return n


def merge(template, existing):
    t_head, t_jobs = split(template)
    e_head, e_jobs = split(existing)
    n = leading_comments(e_head)
    head = (e_head[:n] + t_head[leading_comments(t_head):]) if n else t_head
    out = list(head)
    # a kit job the project does not have yet follows the project's pin (e.g. a canary on @main)
    refs = [r for r in (ref(j) for n, j in e_jobs.items() if n in t_jobs) if r]
    kit_refs = [m.group(1) for j in e_jobs.values() for m in (re.match(r"^      agentkit-ref: (\S+)", l) for l in j) if m]
    for name, job in t_jobs.items():
        if name in e_jobs:
            out += merge_job(job, e_jobs[name])
        elif refs:
            pin = [f"    uses: x@{max(set(refs), key=refs.count)}\n"]
            if kit_refs:
                pin += ["    with:\n", f"      agentkit-ref: {max(set(kit_refs), key=kit_refs.count)}\n"]
            out += merge_job(job, pin)
        else:
            out += job
    for name, job in e_jobs.items():
        if name not in t_jobs:
            if out and out[-1].strip():
                out.append("\n")
            out += job
    return "".join(out)


if __name__ == "__main__":
    template, existing = (open(p, encoding="utf-8").read() for p in sys.argv[1:3])
    sys.stdout.write(merge(template, existing))
