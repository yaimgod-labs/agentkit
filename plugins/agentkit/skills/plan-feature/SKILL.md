---
name: plan-feature
description: Turn a short PRD (an issue body or a description in chat) into an epic issue plus small sub-issues with acceptance criteria and dependencies, all labelled status:backlog. Use when asked to plan, break down or slice a feature.
---

# Plan a feature into GitHub issues

Input: a PRD — an issue number (read it with `gh issue view <n>`), an accepted RFC in `docs/rfcs/` (plan its recommended option and link the RFC and its decision record from the epic), or text from the user.

1. Read the repo's `CLAUDE.md` and the code the feature touches. Ask the user (locally) about anything the PRD leaves ambiguous; in CI, state the assumption in the epic body instead.
2. Slice the work into sub-issues. Each one:
   - is finishable in one PR, at most 1–2 days of work;
   - has a title in the imperative ("Add share-contact endpoint");
   - has this body:
     ```
     ## Context
     <2–4 lines: why, and links to the epic and relevant files>

     ## Acceptance criteria
     - [ ] <verifiable statement: a test, a command, an observable behaviour>

     ## Out of scope
     <optional>
     ```
   - gets labels `status:backlog`, one `type:*` (feature, bug, chore), one `priority:*` (high, medium, low).
3. Create the epic: if the PRD is already an issue, it is the epic; otherwise `gh issue create` with the PRD as body and label `type:epic`. Epics never get a `status:*` label.
4. Create each sub-issue with `gh issue create`, then attach it to the epic:
   `gh api repos/{owner}/{repo}/issues/<epic>/sub_issues -F sub_issue_id=$(gh api repos/{owner}/{repo}/issues/<n> --jq .id)`
5. For each real ordering constraint, add a dependency (the dispatcher skips blocked issues):
   `gh api repos/{owner}/{repo}/issues/<blocked>/dependencies/blocked_by -F issue_id=$(gh api repos/{owner}/{repo}/issues/<blocker> --jq .id)`
6. Reply with a table: number, title, priority, blocked by. Never label anything `status:ready` — the human picks what is ready.
