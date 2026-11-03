---
description: Add work: refine it with you in chat, then file the issue already refined
argument-hint: <what you want>
---

Refining happens here, in this chat. `REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)` and `T=$(mktemp -d)`. `$ARGUMENTS` is the request. If it is empty, ask what they want and stop until they say.

## 1. Refine in chat

Use `agentkit:refine-issue` on the request text, not on an issue number: skip its `gh issue view` step and treat the text as the issue body. Do not edit labels or comments yourself.

- Put its `## Questions` to the user in chat, one message, with each default. Fold the answers into the request text and run the skill again.
- Stop when the verdict has no blocking question, or when the user says to file it anyway. Do not loop forever: if a re-run asks the same thing, ask the user whether to file it anyway.
- Decide whether the plan needs a research question answered first (a library to compare, a feasibility check). If so, write it as a `## Question` (the question and the decision it feeds) and `## Acceptance criteria` (what the answer must cover, as `- [ ]` lines).
- Show the user the `## Plan`, `## Acceptance criteria`, the verdict (size, type, mode, blockers) and the research question if any, before filing. Let them change any of it.

## 2. The status it will get

Decide it now; it is set last, in step 6, in one edit:

- The user said "file it anyway" and a question is still open: `status:refining`. CI refine then asks the question on the issue.
- Otherwise, size `m` or `l`: `status:backlog` until the split is decided (step 7).
- Otherwise: `status:ready`, also when it waits on blockers or on research. The dispatcher does not start it until every `blocked_by` is closed as completed.

Never any other `status:refining`: what the user approved here is not refined again in CI.

## 3. File the issue

Bodies always go through a file, never `--body "<...>"` (a quote or `$` in the text would break or run). Write the body with a quoted heredoc, so nothing in it expands:

```
cat >"$T/body.md" <<'EOF'
<the request, with the answers folded in>

## Plan
<from the refine output>

## Acceptance criteria
<from the refine output>

<!-- agentkit:filed-by-task -->
EOF
gh issue create --repo "$REPO" --title "<short title>" --body-file "$T/body.md" \
  --label size:<size> --label type:<type> --label mode:<mode>
```

No `status:*` label yet: an issue labelled `status:ready` before its blockers are linked could be started in the gap. Every body this command files ends with the `<!-- agentkit:filed-by-task -->` line: in the Claude Code + Slack mode a new issue without a status refines on its own, and that line tells the kit this one is refined already and gets its status from this command (step 6). Keep the issue number (`<n>`) from the URL `gh` prints.

## 4. Dependencies

For each number `<b>` in `blocked_by`:

`gh api "repos/$REPO/issues/<n>/dependencies/blocked_by" -F issue_id="$(gh api "repos/$REPO/issues/<b>" --jq .id)"`

## 5. Research

Only if step 1 found a research question. File it in the `/research` format, body through a file as in step 3:

```
cat >"$T/research.md" <<'EOF'
## Question
<the question and the decision it feeds>

## Acceptance criteria
- [ ] <what the answer must cover>

<!-- agentkit:filed-by-task -->
EOF
gh issue create --repo "$REPO" --title "<short question>" --body-file "$T/research.md" \
  --label type:research --label status:refining
```

Then link it as a blocker of `<n>`, as in step 4 (`<b>` = the research issue). The research issue goes through CI refine like any `/research` question; `<n>` waits for its answer.

## 6. Set the status

One edit: `gh issue edit <n> --repo "$REPO" --add-label status:<status>`, with the status from step 2.

## 7. Large work

If the size is `m` or `l`, propose the split in chat: the sub-tasks as titles, each with one line, and their order. Ask whether to go ahead.

- On the user's OK: use `agentkit:plan-feature` with `<n>` as the epic, and give it the sub-issue status. In the Claude Code + Slack mode (`gh variable get AGENTKIT_INTERFACE --repo "$REPO"` prints `claude-slack`) that is `status:refining`: each sub-issue then refines on its own in CI. Outside the mode it is `status:backlog`, as today. Never `status:ready`. Then remove the status, since epics never carry one: `gh issue edit <n> --repo "$REPO" --remove-label status:backlog`.
- Without an OK: leave `<n>` at `status:backlog`, and say so.

## 8. Reply

Reply with the URLs only, each with its title: the new issue, then the research issue and the sub-issues if any. Say which status the new issue has, and in a few words why when it is not `status:ready` (or when it is ready but waits on a blocker or the research).
