<!-- agentkit: max-lines 120 -->
# CLAUDE.md — {{REPO}}

<!-- Loaded into every session: keep it to facts and hard rules. Procedures go in skills (.claude/skills/),
     rules for part of the tree in .claude/rules/*.md with `paths:`, explanations in docs/. -->

## Project
<!-- one paragraph: what this is, who uses it -->
TODO

## Layout
<!-- top-level folders and what lives where; a folder with its own rules gets its own CLAUDE.md -->
- TODO

## Commands
<!-- the integration-tester agent runs these; keep .agentkit/test.sh in sync -->
- Build: TODO
- Test: TODO
- Lint: TODO

## Project rules
<!-- hard rules specific to this repo; one line each -->

## Working rules (agentkit)
- Think before coding: state assumptions; if something is unclear, ask (locally) or write the assumption into the PR.
- Simplest change that solves the issue. No speculative features, abstractions or config.
- Surgical changes: touch only what the issue needs; no drive-by refactors or reformatting.
- One source of truth: never implement the same logic in two places.
- Done means verified: every acceptance criterion needs evidence (test, command output, file:line). Say what is unverified.
- Never delete files or data unless nothing needs them; prefer disabling or untracking.
- Commits: small and atomic, `<type>: <description> (#issue)`, types feat, fix, docs, style, refactor, test, chore.
- Never push to main, force-push or `git reset --hard` (the agentkit hooks block these). Never push unless asked.

## Knowledge
Docs, decisions, RFCs and research live in `docs/` (index: `docs/README.md`). Search them with the `agentkit:find-knowledge` skill before designing.
A doc lists the code it describes in `covers:`; change that code → update the doc (CI and the Stop hook check this).

## Task flow
Work comes from GitHub issues; status is the `status:*` label (the board mirrors it).
backlog → refining → ready → in-progress → review → approved → merged (a person merges).
Side exits: needs-info (questions for a person), needs-verification (a person checks the PR's Human verification items), needs-human (with a `reason:*`).
`type:research` and `type:rfc` issues produce a doc, not code; `type:debt` is cleanup the dispatcher takes in turn.
Use `/agentkit:task` to add work, `/agentkit:board` to see and reorder it, and `/agentkit:plan` to break a PRD into issues.
