# agentkit

Turns a GitHub repo into an agent-driven project. Tasks are issues; status is a `status:*` label; GitHub Actions move each issue forward. You make two moves: label an issue **ready**, and **merge** an approved PR.

## Lifecycle

```
backlog ──(you)──▶ refining ──refine──▶ ready ──dispatch──▶ in-progress ──implement──▶ review ──gate──▶ approved ──(you merge)──▶ closed
                      │   ▲               ▲                     ▲                    │    │
                      ▼   │ (you answer)  │ (you, skipping      └─ changes-requested ┘    └─▶ needs-device-check ──(you tick)──▶ approved
                   needs-info             │  refine)                after 3 failed rounds ▶ needs-human + reason:*
```

| Step | Trigger | What runs |
|---|---|---|
| refine | `status:refining`, or your comment on a `status:needs-info` issue | Claude (read-only) posts a plan, criteria and questions; the workflow sets `size:*`, `type:*`, `mode:*` and moves the issue to `ready` (size xs/s, nothing unclear) or `needs-info` (assigned to you) |
| dispatch | every 30 min, any `status:*` label, PR merged or edited | promotes the top unblocked `ready` issue (priority, then oldest; skips `mode:human`, `size:m`, `size:l`) while in-flight < WIP (default 2); mirrors labels to the board's **Stage** field; approves a `needs-device-check` PR once its Human verification boxes are all ticked |
| implement | `status:in-progress` or `status:changes-requested` | Claude (implementer) commits on `agent/<n>-<slug>`; the workflow pushes, opens the PR (`Closes #n`), sets `status:review` |
| review | PR opened / pushed / ready for review | three checks in parallel: `review (code)`, `review (security)` — fresh Claude sessions, read-only — and `integration` (`.agentkit/test.sh`) |
| gate | after the checks | all green → `status:approved` (auto-merge only if repo var `AUTO_MERGE=true`), or `status:needs-device-check` while the PR has unticked items under `## Human verification`; otherwise back to the implementer, max 3 rounds |
| plan | `/plan` comment on an issue | the issue becomes an epic with sub-issues, all `status:backlog` |

Every handover to `needs-human` also sets one `reason:*` label (`unclear-spec`, `env`, `flaky`, `too-big`, `agent-error`, `device`); the next status change clears it. Labels go through `scripts/set-status.sh`, which keeps exactly one `status:*`.

Guardrails: every write uses the `agentkit-bot` App token (so events chain); Claude itself gets a downscoped token and cannot push. Only issues and comments by people with write access to the repo (or by agentkit itself) are acted on. Fork PRs never get secrets. Private repos use the self-hosted runner once `AGENTKIT_RUNNER` is set; public repos always use GitHub-hosted runners. Plugin hooks block pushes to main, force pushes, `reset --hard`, and edits outside the worktree.

## One-time setup (per account)

1. `cd cli/gh-agentkit && gh extension install .` (from a clone of this repo) and `gh auth refresh -s project,admin:org`.
2. `gh agentkit app-create <org>` → confirm on GitHub → `gh agentkit app-convert <code>` → install the App on the org.
3. `claude setup-token` (keep the token for step 4).
4. Optional self-hosted runner (Ubuntu + Docker): `sudo ORG=<org> PAT=<fine-grained PAT, org "Self-hosted runners: read and write"> runner/install.sh 3 self-hosted`.

## Per project

| Situation | Do |
|---|---|
| New repo | "Use this template" on `agentkit-template`, then `gh agentkit setup`, `gh agentkit secrets`, `gh agentkit doctor` |
| Existing repo | `gh agentkit init <owner/repo>` (labels, board, variables, branch protection, one PR with the kit files) and `gh agentkit secrets <owner/repo>` |
| Self-hosted runner | `gh variable set AGENTKIT_RUNNER --repo <owner/repo> --body self-hosted` |

Then fill in **Commands** in `CLAUDE.md` and `.agentkit/test.sh`, and run `gh agentkit doctor <owner/repo>`.

Repo variables: `AGENTKIT_WIP` (2), `AGENTKIT_BASE` (PR target if not the default branch), `AGENTKIT_RUNNER`, `AUTO_MERGE`, plus `AGENTKIT_CLIENT_ID` / `AGENTKIT_PROJECT` set by the CLI.

## GitHub Free limits

Org secrets don't reach private repos and private repos can't have branch protection, so `secrets` runs per repo and the checks are advisory — merging stays manual. GitHub Team removes both limits.

## Upgrading

Every reusable workflow looks up, in its own run's record, which repo and commit the caller's `uses:` resolved to, and loads the plugin, `scripts/` and the `trusted` action from exactly that commit. So the `@ref` in `uses:` decides the workflows, prompts and skills together, and the kit never names its own owner (a fork works unchanged). `agentkit-ref` overrides it for testing a branch. `gh agentkit` writes the kit's repo into project files from its own git remote.

Release flow:

1. Merge to `main`. A scratch repo (`<owner>/agentkit-scratch`) is the canary: its caller uses `@main`.
2. Run `scripts/canary.sh`. It files a known issue on scratch and waits until the issue reaches `status:approved` (pass) or `status:needs-human` (fail).
3. Only after a pass: tag `v1.x.y` and move `v1` to it. Projects pick it up on their next run.

When a release adds labels, caller jobs or board stages, run `gh agentkit upgrade <owner/repo>` for each project: it adds the labels and the missing **Stage** options (cards keep their stage), and opens one PR that syncs the caller with the template, keeping the project's `with:` settings, `@ref` pins and extra jobs. `gh agentkit doctor` warns about missing stages.

## Docs

Projects keep their knowledge in `docs/` (template: `templates/docs/`). Each doc starts with front matter:

```yaml
---
title: Payment retries
status: current          # draft | current | deprecated | proposed | accepted | rejected | superseded
description: one line for the index
covers:                  # code this doc describes; drives the drift check
  - src/payments/retry/**
---
```

`plugins/agentkit/scripts/docs.py` is the single implementation:

| Command | Runs in | Checks |
|---|---|---|
| `check` | CI `docs` job, Stop hook | title/status present and valid, every `covers` glob matches a tracked file, relative links resolve |
| `index [--check]` | you / the agent (write), CI (check) | `docs/README.md` is the generated index |
| `drift BASE [--pr-body F]` | CI `docs` job, Stop hook | docs whose covered code changed but the doc did not; a ticked `- [x] docs reviewed: <path> — <why>` line in the PR description clears one |

A failed `docs` job fails the review round like any other check and posts what to fix on the PR; the implementer gets it in its fix-round feedback. Repos without `docs/` skip all of it. Search is the `find-knowledge` skill (docs index → decisions → `rg` → repowise when available → issues, PRs, Discussions).

## Models, plugins and skills

- **Model:** each workflow takes `model` (default `claude-opus-5-5`), passed to Claude as `--model`. A change in the action's default model can never change agent behaviour silently.
- **Built in:** the implementer always runs with `ponytail` (minimal code, stdlib first) and `caveman` (terse prose, fewer output tokens; code, commits and PR text stay normal).
- **Plugins per job:** `implement`, `review`, `refine` and `plan` take `plugins`, a newline list of `NAME@MARKETPLACE` loaded next to `agentkit`. Each job in the caller sets its own list (see `templates/.github/workflows/agentkit.yml`).
- **Project plugins** (a language, framework or design skill set) belong to the project, not the kit: list them in the project's own `.claude-plugin/marketplace.json`, pinned to a commit `sha` the same way, and name them as `NAME@<that marketplace's name>`. Every job loads that marketplace from the checkout when it exists.
- **Generic third-party plugins** are listed in the kit's `.claude-plugin/marketplace.json` (marketplace `agentkit`), each pinned to a commit `sha`. CI never pulls an author's latest code, and `tests/test_marketplace.py` fails on an unpinned entry. To update one: read the diff between the old and new sha (hooks and scripts especially), bump the `sha` in a PR, then run the canary.
- **Project skills:** put them in `.claude/skills/<name>/SKILL.md` in the project. Claude finds them in the checkout; no workflow change is needed.
- **Skills for one subagent:** add a `skills:` list to the agent's frontmatter. That preloads the full skill text into that agent only. For a project-specific list, define the agent in the project's `.claude/agents/`.

### What may run in CI

Allowed:
- plugins that only add skills, agents or commands;
- hooks that only add text to the context or write local files, reviewed at the pinned sha (e.g. `ponytail`, `caveman`: local scripts, no network).

Not allowed in CI:
- anything that asks the user and waits: no human is there, so the job stalls until the turn limit (e.g. `superpowers`, whose brainstorming asks questions);
- anything that changes the structure of the PR body or review output: the gate parses the PR body (terse prose is fine; the checklists must stay intact);
- hooks that make network calls or run code fetched at runtime;
- MCP servers that need secrets beyond the job's own token.

When a single skill from a disallowed plugin is worth having, copy it into `plugins/agentkit/skills/` with its license and attribution.

## Development

`tests/run.sh` (shellcheck, hook tests, migration tests) and `actionlint`. `scripts/make-template.sh <dir>` builds the template repo from `templates/`.
