# agentkit

Turns a GitHub repo into an agent-driven project. Tasks are issues; status is a `status:*` label; GitHub Actions move each issue forward. You make two moves: label an issue **ready**, and **merge** an approved PR.

## Lifecycle

```
backlog ──(you)──▶ refining ──refine──▶ ready ──dispatch──▶ in-progress ──implement──▶ review ──gate──▶ approved ──(you merge)──▶ closed
                      │   ▲               ▲                     ▲                    │    │
                      ▼   │ (you answer)  │ (you, skipping      └─ changes-requested ┘    └─▶ needs-verification ──(you tick)──▶ approved
                   needs-info             │  refine)                after 3 failed rounds ▶ needs-human + reason:*
```

| Step | Trigger | What runs |
|---|---|---|
| refine | `status:refining`, or your comment on a `status:needs-info` issue | Claude (read-only) posts a plan, criteria and questions; the workflow sets `size:*`, `type:*`, `mode:*` and moves the issue to `ready` (size xs/s, nothing unclear) or `needs-info` (assigned to you) |
| dispatch | every 30 min, any `status:*` label, PR merged or edited | promotes the top unblocked `ready` issue (priority, then oldest; skips `mode:human`, `size:m`, `size:l`) while in-flight < WIP (default 2); mirrors labels to the board's **Stage** field; approves a `needs-verification` PR once its Human verification boxes are all ticked |
| implement | `status:in-progress` or `status:changes-requested` | Claude (implementer) commits on `agent/<n>-<slug>`; the workflow pushes, opens the PR (`Closes #n`), sets `status:review` |
| review | PR opened / pushed / ready for review | in parallel: `review (code)`, `review (security)` — fresh Claude sessions, read-only — `docs`, and `integration` (`.agentkit/test.sh`, or each changed `suite`) |
| gate | after the checks; again on other CI apps' results and every 30 min | every check run and commit status on the PR's head commit counts, other CI included; all green → `status:approved` (auto-merge only if repo var `AUTO_MERGE=true`), or `status:needs-verification` while the PR has unticked items under `## Human verification`; otherwise back to the implementer, max 3 rounds |
| plan | `/plan` comment on an issue | the issue becomes an epic with sub-issues, all `status:backlog` |
| digest | daily, 07:00 UTC | lists open issues per label in its `statuses` input (default: needs-info, needs-human, needs-verification, approved, blocked), least recently updated first, in Slack and the run summary; nothing waiting, no post |
| retro | weekly, Monday 08:00 UTC | counts the week (cycle time, fix rounds, handover reasons, debt share); a read-only Claude reads the issues behind them and proposes at most 3 changes; posted as a Discussion (`category`, default General; `days`, default 7) |
| decide | `/decide accept <why>` or `/decide reject <why>` on an RFC's PR, by someone with write access | the issue goes back to the implementer, which sets the RFC's status and writes the decision record; the review checks both against your comment |

Every handover to `needs-human` also sets one `reason:*` label (`unclear-spec`, `env`, `flaky`, `too-big`, `agent-error`, `manual-check`); the next status change clears it. Labels go through `scripts/set-status.sh`, which keeps exactly one `status:*`.

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

Tech debt: label it `type:debt` (or let refine). The dispatcher takes one debt issue in every 4 it starts (`debt-every` on the dispatch job; 0 ranks debt like anything else; `debt-label` uses another label).

Per project, all of this is set in the caller: the crons under `schedule:`, and the labels, headings, counts and category as `with:` inputs (commented examples in the template). `gh agentkit upgrade` keeps both.

Dependencies: `.github/dependabot.yml` (added by `init`/`upgrade`) opens weekly update PRs for GitHub Actions; add your package managers. They get the same review jobs and never auto-merge. Dependabot's runs only see Dependabot secrets, so also add `AGENTKIT_APP_KEY` and `CLAUDE_CODE_OAUTH_TOKEN` under **Settings → Secrets and variables → Dependabot**.

### Slack

No bot of our own: the [GitHub app for Slack](https://github.com/integrations/slack), one channel per project.

1. In the channel: `/github subscribe <owner/repo> issues pulls discussions releases`, then `/github unsubscribe <owner/repo> commits deployments`.
2. Cut the agents' churn: `/github subscribe <owner/repo> +label:"status:needs-human"`. The app keeps one label filter per subscription, so the daily digest covers the other statuses that wait on you.
3. Reply to an issue from its Slack thread; it lands on the issue, so an answer on a `needs-info` issue re-runs refine.
4. For the digest: create a Slack incoming webhook for the channel and `gh secret set SLACK_WEBHOOK_URL --repo <owner/repo>`. The retro arrives through the Discussions subscription.

Repo variables: `AGENTKIT_WIP` (2), `AGENTKIT_BASE` (PR target if not the default branch), `AGENTKIT_RUNNER`, `AUTO_MERGE`, plus `AGENTKIT_CLIENT_ID` / `AGENTKIT_PROJECT` set by the CLI.

## GitHub Free limits

Org secrets don't reach private repos and private repos can't have branch protection, so `secrets` runs per repo and the checks are advisory — merging stays manual. GitHub Team removes both limits.

## Upgrading

Every reusable workflow looks up, in its own run's record, which repo and commit the caller's `uses:` resolved to, and loads the plugin, `scripts/` and the `trusted` action from exactly that commit. So the `@ref` in `uses:` decides the workflows, prompts and skills together, and the kit never names its own owner (a fork works unchanged). `agentkit-ref` overrides it for testing a branch. `gh agentkit` writes the kit's repo into project files from its own git remote.

Release flow:

1. Merge to `main`. A scratch repo (`<owner>/agentkit-scratch`) is the canary: its caller uses `@main`.
2. Run `scripts/canary.sh`. It files a known issue on scratch and waits until the issue reaches `status:approved` (pass) or `status:needs-human` (fail).
3. Only after a pass: tag `v1.x.y` and move `v1` to it. Projects pick it up on their next run.

When a release adds labels, caller jobs or board stages, run `gh agentkit upgrade <owner/repo>` for each project: it adds the labels and the missing **Stage** options (cards keep their stage), and renames labels and stages a release renamed (issues and cards keep them; e.g. `status:needs-device-check` → `status:needs-verification`), and opens one PR that syncs the caller with the template, keeping the project's `with:` settings, `@ref` pins and extra jobs. `gh agentkit doctor` warns about missing stages.

## Monorepos and other CI

By default one `integration` job runs `.agentkit/test.sh`. A repo whose parts need different machines sets `suites` on the caller's `review` job; only suites with a changed path run, each on its own `runs-on`:

```yaml
    with:
      suites: >-
        [{"name": "api", "paths": ["api/**"], "runs-on": "ubuntu-latest", "run": "cd api && npm ci && npm test"},
         {"name": "cli", "paths": ["cli/**"], "runs-on": "macos-latest", "run": "cd cli && make test"}]
      external-checks: >-
        [{"name": "mobile-ci", "paths": ["mobile/**"]}]
      check-timeout: 60
```

Tests that run elsewhere (a hosted mobile CI, Jenkins, …) report back as check runs or commit statuses; name them in `external-checks` and the gate waits for them when their paths changed. The gate judges every check on the PR's head commit, so a failure anywhere sends the PR back, with each failed check's summary in the round comment the implementer reads. A check still pending or missing `check-timeout` minutes after the push moves the issue to `status:needs-human` + `reason:env`. Late results re-run the gate (`check_run` and `status` triggers, plus the 30-minute schedule). Reading commit statuses needs the App's **Commit statuses: read** permission (`doctor` warns when it is missing); without it the gate sees check runs only. Globs are fnmatch: `*` also matches `/`.

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
| `check` | CI `docs` job, Stop hook | title/status present and valid, every `covers` glob matches a tracked file, relative links resolve, every accepted or rejected RFC has a decision record linking it, `supersedes` targets exist and are `superseded` |
| `index [--check]` | you / the agent (write), CI (check) | `docs/README.md` is the generated index |
| `drift BASE [--pr-body F]` | CI `docs` job, Stop hook | docs whose covered code changed but the doc did not; a ticked `- [x] docs reviewed: <path> — <why>` line in the PR description clears one |

### Knowledge flow

Loose ideas start in Discussions (**Ideas**; `setup` enables Discussions). When one needs work:

| Question | Issue | Output | Then |
|---|---|---|---|
| "what is true / what are the options?" | `type:research` (`/research <question>` or the Research form) | `docs/research/<slug>.md` | feeds an RFC or a feature |
| "how should we build it?" | `type:rfc` (`/rfc <problem>` or the RFC form) | `docs/rfcs/NNNN-slug.md`, `status: proposed`: options with for and against, recommendation, consequences, rejected options, open questions, threat model when security is involved | you `/decide` on the PR, merge, then `/plan` the accepted RFC into feature issues |

Both run through the normal lifecycle (refine → implement → review); the agent writes docs only and never decides an RFC. Decision records in `docs/decisions/` are what later agents and reviewers hold the code to.

A failed `docs` job fails the review round like any other check and posts what to fix on the PR; the implementer gets it in its fix-round feedback. Repos without `docs/` skip all of it. Search is the `find-knowledge` skill (docs index → decisions → `rg` → repowise when available → issues, PRs, Discussions).

### Agent context

Everything an agent loads on every session costs attention, so it stays short:

| What | Where | Loaded |
|---|---|---|
| facts and hard rules: what the project is, layout, commands, rules | `CLAUDE.md` (root, plus one per folder with its own rules) | always (a folder's when working there) |
| rules for part of the tree | `.claude/rules/*.md` with `paths:` | when those paths are touched |
| procedures (release, migrations, …) | skills: agentkit's, plus the project's in `.claude/skills/` | when used |
| explanations, designs, decisions | `docs/` | searched (`find-knowledge`), never preloaded |

`docs.py check` (CI `docs` job and the Stop hook) fails any `CLAUDE.md` or `.claude/rules/*.md` over its line budget: 150 lines, or what the file sets with `<!-- agentkit: max-lines N -->` (the template's root file says 120). When review keeps catching the same mistake, the weekly retro proposes the one line to add.

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
