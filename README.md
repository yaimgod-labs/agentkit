# agentkit

Turns a GitHub repo into a project agents work on. You say what you want as a **task**; an agent plans it, another builds it on a branch and opens a PR, others review it, and it comes back to you only when it needs you: a question, an approval, a check on a real device, or the merge.

Each task is a GitHub issue, its status a `status:*` label, and GitHub Actions move it forward. Nothing to host, unless you want the Slack bot or your own runner.

- **In Claude Code:** `/task` adds work, `/board` shows where everything stands.
- **In Slack** ([Slack mode](#slack-mode)): what waits on you arrives as a card, and you answer there.
- **On GitHub:** it is all issues, labels, PRs and one project board, so nothing is hidden.

The words this README uses for people (task, agent, Needs you, …) are in [docs/glossary.md](docs/glossary.md). The reference half ([How it works](#how-it-works) onward) names the workflows as they are in the code: `refine` plans, `dispatch` starts work, `implement` builds, `review` and its `gate` check.

## Set up

### Once per account

1. `cd cli/gh-agentkit && gh extension install .` (from a clone of this repo) and `gh auth refresh -s project,admin:org`.
2. `gh agentkit app-create <org>` → confirm on GitHub → `gh agentkit app-convert <code>` → install the App on the org.
3. `claude setup-token` (keep the token for step 4).
4. Optional self-hosted runner (Ubuntu + Docker): `sudo ORG=<org> PAT=<fine-grained PAT, org "Self-hosted runners: read and write"> runner/install.sh 3 self-hosted`.

### Per project

| Situation | Do |
|---|---|
| New repo | "Use this template" on `agentkit-template`, then `gh agentkit setup`, `gh agentkit secrets`, `gh agentkit doctor` |
| Existing repo | `gh agentkit init <owner/repo>` (labels, board, variables, branch protection, one PR with the kit files) and `gh agentkit secrets <owner/repo>` |
| Self-hosted runner | `gh variable set AGENTKIT_RUNNER --repo <owner/repo> --body self-hosted` |

Then fill in **Commands** in `CLAUDE.md` and `.agentkit/test.sh`, and run `gh agentkit doctor <owner/repo>`.

Tech debt: label it `type:debt` (or let the planning agent). Agents take one tech-debt task in every 4 they start (`debt-every` on the dispatch job; 0 ranks debt like anything else; `debt-label` uses another label).

Per project, all of this is set in `.github/workflows/agentkit.yml`: the crons under `schedule:`, and the labels, headings, counts and category as `with:` inputs (commented examples in the template). `gh agentkit upgrade` keeps both.

Dependencies: `.github/dependabot.yml` (added by `init`/`upgrade`) opens weekly update PRs for GitHub Actions; add your package managers. They get the same review jobs and never auto-merge. Dependabot's runs only see Dependabot secrets, so also add `AGENTKIT_APP_KEY` and `CLAUDE_CODE_OAUTH_TOKEN` under **Settings → Secrets and variables → Dependabot**.

Digest in Slack: create an incoming webhook for the channel and `gh secret set SLACK_WEBHOOK_URL --repo <owner/repo>`. To answer agents from Slack, see [Slack mode](#slack-mode).

Repo variables: `AGENTKIT_WIP` (2), `AGENTKIT_BASE` (PR target if not the default branch), `AGENTKIT_RUNNER`, `AUTO_MERGE`, plus `AGENTKIT_CLIENT_ID` / `AGENTKIT_PROJECT` set by the CLI. The full list is in [Settings](#settings).

## Daily use

Add work with `/task <what you want>` in Claude Code, **+ Add task** in Slack (with the Slack bot), or a new issue on GitHub. Then `/board` shows where it stands, in these words:

| It says | Means | Your move |
|---|---|---|
| Needs your answer | the agent asked a question (`needs-info`) | answer it |
| Needs your approval | a research answer, an RFC or a split of a big task waits for your yes (`needs-approval`, Slack mode) | `approve`, or say what to change |
| Needs your check | all checks passed; the PR lists things only a person can verify (`needs-verification`) | tick the boxes, or `verified` |
| Needs you | the agent stopped; a `reason:*` label says why (`needs-human`) | `retry`, or say what to change |
| Blocked | stopped until you unblock it (`blocked`) | `unblock` |
| Being planned | an agent is writing the plan and acceptance criteria (`refining`) | — |
| Up next | planned; an agent starts it when there is room (`ready`) | reorder with `/board move` |
| Being built | an agent is writing it (`in-progress`) | — |
| In review | PR open, checks running or the agent fixing a failed one (`review`, `changes-requested`) | — |
| Approved | every check passed (`approved`) | merge it, unless it merges by itself (`AUTO_MERGE`) |

Outside the Slack mode a new issue waits in the backlog until you label it `status:refining` (plan it first) or `status:ready` (it is clear enough to build); `/task` sets that for you. You answer on GitHub: a comment on a `needs-info` issue, a "Request changes" review on the PR, a ticked box, a label. In the Slack mode the words in the last column are replies ([below](#slack-mode)).

### Commands

In Claude Code (the agentkit plugin):

| Command | Does |
|---|---|
| `/board` | waiting on you, in progress, the next 5 in the order agents take them (with the ones that wait on another task or are too big to take), blocked with reasons; estimates from recent cycle times |
| `/board <n>` | one task in full: status, what it is, where it stands, what it needs from you |
| `/board move <n> <pos>` | reorders Up next by writing the board's **Rank** number field, which is read first when the next task is picked (`gh agentkit upgrade` adds the field to an older board) |
| `/board unblock <n>` | a `blocked` task goes back to being planned |
| `/board replace <n> <b>` | #b takes the place of the closed task #n waited on; #n goes back to Up next |
| `/board unlink <n> <b>` | #n no longer waits on #b; the planning agent will not add it back |
| `/board done <n>` | closes a task that was yours to do (`mode:human`) |
| `/task <what you want>` | a question is filed as research and a design problem as an RFC; anything else it plans with you in the chat, then files: Up next (what it waits on and any research question linked first), or backlog while the split of a big task (size m/l) waits for your OK |

Reading and writing the board's Rank needs the `project` scope: `gh auth refresh -s project`.

### Dependencies

A task can wait on another (GitHub's issue dependencies, `blocked_by`). It never starts while the one it waits on is open: it is skipped when the next task is picked, and a build run refuses it (back to Up next, with a comment) however it got started. The other task counts as done only when closed as completed. Closed any other way (not planned, duplicate), every task waiting on it gets a comment and becomes Blocked (one already being built gets the comment only), and stays Blocked until `/board unblock` or `/board replace`. The planning agent records the dependencies it finds. The `closed` trigger on the `issues:` event in agentkit.yml announces this at once; the schedule catches it anyway, and `gh agentkit upgrade` adds the trigger to an older agentkit.yml.

## Slack mode

Opt-in per project: you steer from Claude Code (`/task`, `/board`) and answer agents from Slack, and approved PRs merge by themselves. Off unless the repo variable `AGENTKIT_INTERFACE=slack` is set; off, everything above behaves as before.

```
gh agentkit upgrade <owner/repo> --interface slack   # also on setup and init
```

(`--interface slack-bot --card-channel C…` is the same mode with the Slack bot's cards on top: `docs/slack-bot.md`.)

It sets `AGENTKIT_INTERFACE` and `AUTO_MERGE=true`, adds the `action:required` label and the **Needs approval** stage, and prints the Slack lines. The mode turns on:

- a new task by a trusted author is planned at once, with no label from you;
- the planning agent proposes a split for a big task (size m/l), and files research when knowledge is missing;
- research and RFC PRs are held until you answer;
- reply keywords (below), and the `action:required` label on every task that waits on you;
- the done message in Slack when a task's PR merges;
- `AUTO_MERGE=true` is required (`approved` is never a waiting state); `gh agentkit doctor` fails without it.

`AUTO_SPLIT=true` (repo variable) creates a split's sub-tasks without asking; unset, the split waits for your `approve`. New sub-tasks are planned one by one.

**Slack.** In the channel, once: `/github signin`, then

```
/github subscribe <owner/repo> issues comments +label:"action:required"
/github unsubscribe <owner/repo> pulls commits releases deployments
```

and `gh secret set SLACK_WEBHOOK_URL --repo <owner/repo>` for the done message, digest and retro line.

**Replying.** Use the **Comment** button on the issue's card in Slack. A plain thread reply stays in Slack and never reaches GitHub. The first word of the comment is a keyword (plain words, no leading `/`); anything else is free text. `approve` and `accept` mean the same wherever either is listed. A reply that does not fit gets a comment listing the ones that do.

| Waiting as | Keywords | Free text |
|---|---|---|
| Needs your answer | `research <q>`, `block <reason>`, `close <why>` | your answer; planning continues (with the agent's PR open: the agent's next attempt) |
| Needs you | `retry`, `research <q>`, `block <reason>`, `close <why>` | what to change; the agent runs again with it (with no PR yet, `retry` and your text go back to planning) |
| Needs your check | `verified`, `block <reason>` | what failed; the PR goes back to the agent |
| Needs your approval, research | `approve`, `block <reason>` | your own answer; it wins over the recommendation |
| Needs your approval, RFC | `accept [why]` (the record notes when no reason is given), `reject <why>`, `block <reason>` | none |
| Needs your approval, split | `approve`, `block <reason>` | what to change; the split is proposed again |
| Blocked | `unblock`, `replace #N` | none |
| yours to do (`mode:human`, Up next) | `done`, `block <reason>` | none |

`close <why>` closes the task with your reason recorded: as completed when the reason starts with `done` or `already` (`close already done in #12`), as not planned otherwise.

`/board` and `/task` work in either mode, in Claude Code (see above). A task that is Blocked because the one it waited on was closed without being done gets no Slack card: handle it in Claude Code with `/board unblock <n>`, or `/board replace <n> <b>` when #b takes the closed one's place.

An RFC merges only on a person's decision: your `accept`/`reject` reply (or a `/decide` on the PR) by someone with write access. The kit's relayed `/decide` alone never counts, and neither does a rounds reset the kit did not post for a person's reply, since the agents comment as the kit too. The implementer's Claude has no comment token at all.

## Settings

`config/settings.json` lists everything you can change, one entry each: what it does in plain words, its default, the common choices, the rule a value must pass, and how a change is applied (just for you: your own Slack bot setting; for the whole project: a repo variable, a `with:` input or cron in agentkit.yml, or the bot's server env). `tests/test_settings.py` fails when a repo variable, an agentkit.yml input or cron, or a bot env var the kit reads is missing from it.

Besides the basics it covers each job's time limit, the planner's and retro's turns, a model per job (overriding the shared `model` for that job only), the merge method and branch deletion, the one automatic retry, whether a missing test script fails review, the test script's path, and how much the digest and retro list. Each is a repo variable whose unset value is the old fixed one, so nothing changes until you set it, and the workflows themselves stay as they are. The dispatcher's stuck-run sweep waits 30 minutes past the implement time limit, so raising one moves the other. Left fixed on purpose: label names, the agent branch prefix and which reviews run (workflow logic), token permissions, trust checks, tool lists and input caps (security), and the bot's 2-a-day nudge cap.

- `python3 scripts/settings.py show [word]`: the entries, with options and the exact way to change each.
- `python3 scripts/settings.py validate <key> <value>`: exit 0, or the reason the value is refused.
- `/agentkit:settings <question>` in Claude Code: "can I change X?" answered from the registry with its options; it prints the `gh variable set` command or proposes the agentkit.yml edit as a PR, and never invents a setting.
- With the Slack bot: DM it the question (or App Home → Settings) and click an option: your own settings apply at once, a whole-project one needs admin access. See [Settings from Slack](docs/slack-bot.md#settings-from-slack).

## How it works

The reference: every workflow by its name in the code, what starts it and what it does.

```
backlog ──(you)──▶ refining ──refine──▶ ready ──dispatch──▶ in-progress ──implement──▶ review ──gate──▶ approved ──(you merge)──▶ closed
                    │ │   ▲               ▲                     ▲                    │    │
                    │ ▼   │ (you answer)  │ (you, skipping      └─ changes-requested ┘    └─▶ needs-verification ──(you tick)──▶ approved
                    │ needs-info          │  refine)                after 3 failed rounds ▶ needs-human + reason:*
                    └─▶ needs-approval   (Slack mode only: refine's split proposal, or the gate's passing research or RFC PR;
                        your answer moves it on)
```

In the Slack mode ([below](#slack-mode)) a new issue starts at `refining` by itself, and refine can stop at `needs-approval` (a research recommendation, an RFC decision or a split proposal) until you answer.

| Step | Trigger | What runs |
|---|---|---|
| refine | `status:refining`, or your comment on a `status:needs-info` issue (in the Slack mode your reply sets `status:refining` instead, below) | Claude (read-only) posts a plan, criteria and questions; the workflow sets `size:*`, `type:*`, `mode:*` and moves the issue to `ready` (size xs/s, nothing unclear) or `needs-info` (assigned to you). An issue whose agent PR is open is not re-planned: the comment gets a pointer to the PR |
| dispatch | every 30 min, any `status:*` label, PR merged or edited, a person's "Request changes" review | promotes the top unblocked `ready` issue (board **Rank**, then the debt quota and priority, then oldest; skips `mode:human`, `size:m`, `size:l`) while open agent issues not yet merged (`in-progress` through `approved`) < WIP (default 2), so PRs never pile up faster than people merge them; mirrors labels to the board's **Stage** field; approves a `needs-verification` PR once its Human verification boxes are all ticked (and merges it if `AUTO_MERGE=true`); sends a PR back to the implementer when a person with write access requests changes (not a failed round), also from `needs-info`; on the schedule, retries an issue left in `in-progress` or `changes-requested` over 90 min with no unfinished run titled like it (a lost runner), like a failed implement run |
| implement | `status:in-progress` or `status:changes-requested` | Claude (implementer) commits on `agent/<n>-<slug>` (an existing branch first gets the base merged in; Claude resolves any conflicts); the workflow pushes, opens the PR (`Closes #n`), sets `status:review`. A fix round gets this round's feedback: everything people wrote on the PR, the bots' comments since its head commit, and the failed jobs' log lines. A run with no commits goes to `needs-human` + `reason:agent-error`, except a fix round a person's "Request changes" started: then the PR gets the agent's question, @-mentioning the reviewer, and the issue goes to `needs-info` until the next "Request changes" review. A failed run (not a timeout) is retried once, marked `reason:retry`; a second failure goes to a person (`scripts/retry.sh`, shared with dispatch's stuck-run sweep) |
| review | PR opened / pushed / ready for review | in parallel: `review (code)`, `review (security)` — fresh Claude sessions, read-only; in a fix round they first check the earlier findings were fixed and fail settled code only for an unmet criterion (code) or a high finding (security) — `docs`, and `integration` (`.agentkit/test.sh`, or each changed `suite`) |
| gate | after the checks; again on other CI apps' results and every 30 min | every check run and commit status on the PR's head commit counts, other CI included, and the kit's own (`review (code)`, `review (security)`, `docs`, integration) must have reported; a PR that conflicts with its base goes back to the implementer (not a failed round); all green → `status:approved` (auto-merge only if repo var `AUTO_MERGE=true`; a merge that fails goes to `needs-human`), or `status:needs-verification` while the PR has unticked items under `## Human verification`; otherwise back to the implementer, max 3 rounds |
| plan | `/plan` comment on an issue | the issue becomes an epic with sub-issues, all `status:backlog` |
| digest | daily, 07:00 UTC | lists open issues per label in its `statuses` input (default: needs-info, needs-human, needs-verification, needs-approval, approved, blocked; in the Slack mode `approved` is skipped, since a merge is automatic), least recently updated first, in Slack and the run summary; nothing waiting, no post |
| retro | weekly, Monday 08:00 UTC | counts the week (cycle time, fix rounds, handover reasons, retries, debt share, and turns, minutes and estimated cost per Claude job, from the `agentkit-usage-*` artifact each Claude run leaves); a read-only Claude reads the issues behind them and proposes at most 3 changes; posted as a Discussion (`category`, default General; `days`, default 7); in the Slack mode also one line with its link to `SLACK_WEBHOOK_URL` |
| decide | `/decide accept <why>` or `/decide reject <why>` on an RFC's PR, by someone with write access | the issue goes back to the implementer, which sets the RFC's status and writes the decision record; the review checks both against your comment |

Every handover to `needs-human` also sets one `reason:*` label (`unclear-spec`, `env`, `flaky`, `too-big`, `agent-error`, `manual-check`); the next status change clears it. `reason:retry` is not a handover: it marks the one automatic retry of a failed implement run. Labels go through `scripts/set-status.sh`, which keeps exactly one `status:*`.

Guardrails: every write uses the `agentkit-bot` App token (so events chain); Claude itself gets a downscoped token and cannot push. Only issues and comments by people with write access to the repo (or by agentkit itself) are acted on. Fork PRs never get secrets. Private repos use the self-hosted runner once `AGENTKIT_RUNNER` is set; public repos always use GitHub-hosted runners. Plugin hooks block pushes to main, force pushes, `reset --hard`, and edits outside the worktree.

## GitHub Free limits

Org secrets don't reach private repos and private repos can't have branch protection, so `secrets` runs per repo and the checks are advisory — merging stays manual. GitHub Team removes both limits.

## Upgrading

Every reusable workflow looks up, in its own run's record, which repo and commit the caller's `uses:` resolved to, and loads the plugin, `scripts/` and the `trusted` action from exactly that commit. So the `@ref` in `uses:` decides the workflows, prompts and skills together, and the kit never names its own owner (a fork works unchanged). `agentkit-ref` overrides it for testing a branch. `gh agentkit` writes the kit's repo into project files from its own git remote.

Release flow:

1. Merge to `main`. A scratch repo of your own is the canary: its caller uses `@main`.
2. Run `scripts/canary.sh <owner/scratch-repo>` (or set `AGENTKIT_CANARY`). It files a known issue on scratch and waits until the issue reaches `status:approved` (pass) or `status:needs-human` (fail).
3. Only after a pass: tag `v1.x.y` and move `v1` to it. Projects pick it up on their next run.

When a release adds labels, caller jobs or board stages, run `gh agentkit upgrade <owner/repo>` for each project: it adds the labels and the missing **Stage** options (cards keep their stage), and renames labels and stages a release renamed (issues and cards keep them; e.g. `status:needs-device-check` → `status:needs-verification`), and opens one PR that syncs the caller with the template, keeping the project's `with:` settings, `@ref` pins and extra jobs. `gh agentkit doctor` warns about missing stages.

## Monorepos and other CI

By default one `integration` job runs `.agentkit/test.sh`. A repo whose parts need different machines sets `suites` on the caller's `review` job; only suites with a changed path run, each on its own `runs-on`, and the `integration` check then passes only when every suite that ran passed (so the branch protection `setup` adds covers suites too):

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
| "what is true / what are the options?" | `type:research` (`/task <question>` or the Research form) | `docs/research/<slug>.md` | feeds an RFC or a feature |
| "how should we build it?" | `type:rfc` (`/task <problem to design for>` or the RFC form) | `docs/rfcs/NNNN-slug.md`, `status: proposed`: options with for and against, recommendation, consequences, rejected options, open questions, threat model when security is involved | you `/decide` on the PR, merge, then `/plan` the accepted RFC into feature issues |

Both run through the normal lifecycle (refine → implement → review); the agent writes docs only and never decides an RFC. Research runs alone get web search and fetch, to check primary sources. Decision records in `docs/decisions/` are what later agents and reviewers hold the code to.

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

`tests/run.sh` (shellcheck, hook tests, migration tests) and `actionlint`. Wording people read follows [docs/glossary.md](docs/glossary.md); `tests/test_terms.py` fails on a retired term. `scripts/make-template.sh <dir>` builds the template repo from `templates/`.
