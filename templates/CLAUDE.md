# CLAUDE.md — {{REPO}}

## Commands
<!-- the integration-tester agent runs these; keep .agentkit/test.sh in sync -->
- Build: TODO
- Test: TODO
- Lint: TODO

## Project rules
<!-- rules specific to this repo -->

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
Docs, decisions and research live in `docs/` (index: `docs/README.md`). Search them with the `agentkit:find-knowledge` skill before designing.
A doc lists the code it describes in `covers:`; change that code → update the doc (CI and the Stop hook check this).

## Task flow
Tasks are GitHub issues; status is the `status:*` label (the board mirrors it).
backlog → ready (human) → in-progress → review → approved → merged (human).
Use `/agentkit:plan` to break a PRD into issues and `/agentkit:next` to work the top ready issue locally.
