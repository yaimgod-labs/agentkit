---
name: implement-issue
description: Implement one GitHub issue end to end against its acceptance criteria, test-first, with small commits. Use when asked to implement, build or fix a specific issue number, or when the agentkit implement workflow runs.
---

# Implement an issue

1. `gh issue view <n> --json title,body,comments` (plain `--comments` prints only the comments when piped). The acceptance criteria are the contract, including any added in the refine comment (`## Plan` / `## Acceptance criteria`) and the answers to its questions. Comments from the review loop (if any) are additional required fixes.
2. Read the repo's `CLAUDE.md`: its build, test and lint commands and its rules override anything here.
3. Stay inside the current working tree. Locally, work in a git worktree on branch `agent/<n>-<slug>`; in CI the branch is already checked out.
4. For each acceptance criterion: write or extend a test that fails, make it pass, commit. Commit format: `<type>: <description> (#<n>)` with type in feat, fix, refactor, test, docs, chore.
5. Docs: before designing, use the `find-knowledge` skill for relevant docs and decisions. If you change code that a doc in `docs/` covers (its `covers:` globs), update that doc in the same change, or, if it is still accurate, add a ticked `docs reviewed` line (below) with the reason. A new or changed doc needs valid front matter, and `docs/README.md` must be regenerated: `python3 .agentkit-kit/plugins/agentkit/scripts/docs.py index` in CI (locally: `scripts/docs.py` in the agentkit plugin). Never contradict an accepted record in `docs/decisions/`; if the issue requires it, stop and say so.
6. A `type:research` or `type:rfc` issue produces a doc, not code (its acceptance criteria are about the doc):
   - research → `docs/research/<slug>.md`, `status: current`: the question, what you checked (sources, code, measurements) and the answer, with its confidence.
   - rfc → `docs/rfcs/NNNN-slug.md` (next free number), `status: proposed`, sections: Problem · Options (at least two, each with for and against) · Recommendation · Consequences · Rejected options and why · Open questions · Threat model (when it touches auth, data, secrets or the network). No implementation.
   - A fix round whose feedback has a `/decide accept <why>` or `/decide reject <why>` comment: set the RFC's status to `accepted` or `rejected` and add `docs/decisions/NNNN-slug.md` (MADR: context, decision, consequences, the person's reason) that links the RFC; a decision that replaces an earlier one gets `supersedes: [NNNN]` and the earlier record `status: superseded`. Never decide an RFC yourself.
7. Spend tokens on the change, not on reading: search (`rg`, Grep, Glob) before opening files, read only the line ranges you need, do not re-read a file you just edited, and run tests with their quietest useful output (failures only).
8. Touch only what the issue needs. Unrelated problems you notice go into your final summary as follow-ups, not into the diff.
9. Before finishing, run the full build, lint and test commands from `CLAUDE.md` and fix what fails. You may delegate this to the `integration-tester` agent, but in the foreground: wait for its result in the same turn, never run it in the background. Do not write the final summary until you have the result.
10. Never push, never open a PR, never change labels: in CI the workflow does that; locally the human decides.
11. Your final message becomes the PR description, so write it for a reviewer, in plain full sentences even if a terse-prose mode is active, and in this shape only:
   ```
   ## Acceptance criteria
   - [x] <criterion> — <evidence: test name, command and result, or file:line>
   - [ ] <criterion> — not verified: <why>

   ## Human verification
   - [ ] <what a person must check, and how: e.g. "on the staging build, the dialog closes on Escape">   (only for criteria CI cannot check)

   ## Docs
   - [x] docs reviewed: <docs/path.md> — <why it is still accurate>   (only for covered docs you did not edit)

   ## Follow-ups
   - <only if any>
   ```
   No narration of your process, and nothing about pushing, PRs or labels. Never tick a criterion you could not verify. A criterion only a person can check (a real device, visual taste, hardware) goes unticked under `## Human verification`, never under `## Acceptance criteria`; never tick those yourself. The gate waits for a person on them instead of failing the round.
