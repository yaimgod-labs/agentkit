---
name: refine-issue
description: Triage and clarify one GitHub issue before work starts — size, type, mode (agent, human or pair), a short plan, verifiable acceptance criteria and the questions a person must answer. Use when asked to refine, triage, groom or clarify an issue, or when the agentkit refine workflow runs.
---

# Refine an issue

Input: an issue number. Read it with its comments: `gh issue view <n> --json title,body,labels,comments`.
On a re-run the latest comments are a person's answers to your earlier questions: build on them and ask only what is still open.

1. Read the repo's `CLAUDE.md`, then use the `find-knowledge` skill for docs, decisions and earlier issues on the same topic, and read the code the issue touches.
2. Decide:
   - **type**: `feature`, `bug`, `chore`, `debt` (cleanup that makes later work cheaper; the dispatcher takes one in every few issues), `research` (a question to answer; the output is a doc) or `rfc` (a design to propose for a person to decide; the output is a doc, no code). Research and RFCs are usually `mode:agent`.
   - **size**: `xs` (under an hour, one file) · `s` (one PR, at most a day) · `m` (several PRs) · `l` (an epic).
   - **mode**: `agent` (the spec is clear and every criterion can be checked by tests or commands in CI) · `pair` (an agent builds it, but a person must check something: a real device, visual taste, hardware; name those checks so the implementer lists them under `## Human verification`) · `human` (needs credentials, accounts, payments, legal or product judgement; the dispatcher never takes it).
   - **status**: `ready` only when size is `xs` or `s`, every acceptance criterion is verifiable, and no question blocks the work. Otherwise `needs-info`. For `m` or `l`, say it must be split first and propose the split (a person can then comment `/plan`).
   2a. **dependencies**: search open issues for work this issue needs first (`gh issue list --state open --search "<terms>" --json number,title`, with terms from the issue's nouns and the code it touches). Only real prerequisites count: work that must be merged before this one can be built or checked. Never related issues, never "nice to do first". List them under `## Depends on`, one line each saying why, and put their numbers in `blocked_by` in the VERDICT. The workflow records them, and the dispatcher will not start this issue until they are done. Leave the section and the key out when there are none. Never propose a blocker the person unlinked: a comment `<!-- agentkit:unlinked #<b> -->` on the issue means they removed #<b> on purpose.
3. Never contradict an accepted record in `docs/decisions/`. If the issue requires it, that is a blocking question.

Your final message is posted, as it is, as a comment on the issue, so write it for the person who will answer, start directly with `## Plan` (no preface, no note about who applies it), in this shape only:

```
## Plan
- <3–6 bullets: files or modules, approach, tests>

## Depends on
- #<n> — <one line: why this must be done first>

## Acceptance criteria
- [ ] <verifiable criterion>   (only if the issue's own criteria are missing or not verifiable; these become the contract)

## Questions
1. <only what blocks the work> — default if unanswered: <your assumption>

VERDICT: {"status":"needs-info","size":"s","type":"feature","mode":"agent","blocked_by":[12]}
```

Leave out a section that has nothing in it. The last line must be the `VERDICT:` line with exactly those four keys, plus `blocked_by` (an array of issue numbers in this repo) when there are dependencies. Do not edit files, labels or comments yourself: in CI the workflow applies the verdict; locally, show it to the person and let them decide.
