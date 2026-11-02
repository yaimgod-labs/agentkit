---
description: Add work: refine it with you in chat, then file the issue already refined
argument-hint: <what you want>
---

Refining happens here, in this chat. `REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)`. `$ARGUMENTS` is the request. If it is empty, ask what they want and stop until they say.

## 1. Refine in chat

Use `agentkit:refine-issue` on the request text, not on an issue number: skip its `gh issue view` step and treat the text as the issue body. Do not edit labels or comments yourself.

- Put its `## Questions` to the user in chat, one message, with each default. Fold the answers into the request text and run the skill again.
- Stop when the verdict has no blocking question, or when the user says to file it anyway. Do not loop forever: if a re-run asks the same thing, file it as `status:refining`.
- Show the user the `## Plan`, `## Acceptance criteria` and the verdict (size, type, mode) before filing. Let them change any of it.

## 2. File the issue

The verdict is `{"status","size","type","mode"}` plus an optional `blocked_by`.

```
gh issue create --title "<short title>" --body "<body>" \
  --label size:<size> --label type:<type> --label mode:<mode> --label status:<status>
```

- Body: the request (with the answers folded in), then `## Plan` and `## Acceptance criteria` from the refine output.
- `status:ready` only when size is `xs` or `s` and no question is open. In every other case, including "file it anyway" with an open question, `status:refining`.
- Keep the issue number (`<n>`) from the URL `gh` prints.

## 3. Dependencies

For each number in `blocked_by`:

`gh api repos/{owner}/{repo}/issues/<n>/dependencies/blocked_by -F issue_id=$(gh api repos/{owner}/{repo}/issues/<b> --jq .id)`

## 4. Research

If the plan cannot be settled without an answer to a question (a library to compare, a feasibility check), file that question first, in the `/research` format:

`gh issue create --label type:research --label status:refining --title "<short question>" --body "<body>"`, with the body `## Question` (the question and the decision it feeds) and `## Acceptance criteria` (what the answer must cover, as `- [ ]` lines).

Then link it as a blocker of the new issue, as in step 3 (`<b>` = the research issue). If the new issue was `status:ready`, change it to `status:refining`: `gh issue edit <n> --remove-label status:ready --add-label status:refining`.

## 5. Large work

If the size is `m` or `l`, the issue stays `status:refining`. Propose the split in chat: the sub-tasks as titles, each with one line, and their order. Ask whether to go ahead.

- On the user's OK: use `agentkit:plan-feature` with the new issue as the epic. Do not label any sub-issue `status:ready`. plan-feature creates them in backlog today.
- Without an OK: leave the issue as it is, `status:refining`, and say so.

## 6. Reply

Reply with the URLs only, each with its title: the new issue, then the research issue and the sub-issues if any. Say which status the new issue has, and why in a few words if it is `status:refining`.
