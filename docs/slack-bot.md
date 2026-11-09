# Slack bot (slack-bot interface): deploy notes

The bot is one container with no inbound port (Slack Socket Mode connects outbound). It turns a button click into a
`repository_dispatch` event `agentkit-slack-reply`; the project's `reply` job does the rest. Design: `docs/superpowers/specs/2026-11-08-slack-bot-interface-design.md`.

## Slack app

Create a Slack app with Socket Mode on and Interactivity on, two bot events (`app_home_opened`, for the board; see
[App Home, Add task and nudges](#app-home-add-task-and-nudges); and `message.im`, for
[Settings from Slack](#settings-from-slack)), and two bot scopes: `chat:write` (no `chat:write.public`) and
`im:history` (to read a DM sent to the bot). Keep two tokens: the bot token (`xoxb-…`) and an app-level token (`xapp-…`, scope
`connections:write`). Use a **private** channel for the cards and invite the bot; who may act is decided by `users.json`,
not by who can see the channel.

## GitHub App

Give the bot **its own GitHub App** if you can: it needs only `contents: write` (for `repository_dispatch`),
`issues: read` (the board and the nudge count) and `metadata: read` (the permission check), nothing else. The workflows sign the reply record with the lifecycle App's key, so the bot
never holds that key. Set the repo variable `AGENTKIT_SLACK_BOT_APP` to this App's slug: the workflows act only on a
Slack event (`repository_dispatch`) sent by `<slug>[bot]`, since anyone with write access can send one and name
someone else in it. If the bot shares the lifecycle App instead, leave the variable unset; the bot's key can then do
everything the lifecycle App can. Install it only on the repos in `AGENTKIT_REPOS`, and protect the default branch there (rulesets),
since `contents: write` can push to an unprotected branch. The bot mints a token per click for that one repo, limited to
`contents: write` and `metadata: read`; for reads (the board, nudges) a token limited to `issues: read` and
`metadata: read`.

## Server files (never in a repo)

| File | Content |
|---|---|
| `users.json` | `{"<Slack user id>": "<github login>"}`: the allowlist of people who may act |
| `app.pem` | the bot's GitHub App private key |
| `slack_bot_token`, `slack_app_token` | one token per file |

`AGENTKIT_REPOS` (comma-separated `owner/repo`) is the second allowlist: the bot refuses any other repository.

## Run

The image pins its base by digest and installs from a hashed lockfile (`bot/requirements.txt`, made from
`requirements.in` with `uv pip compile --universal --python-version 3.12 --generate-hashes`). It runs as a non-root
user and works on a read-only filesystem, apart from one writable volume for the nudge settings and history
(`/data`, below). It is built from the kit's root (it copies the kit's `scripts/card.py`, `scripts/reply.py`,
`scripts/settings.py` with `config/settings.json`, and `plugins/agentkit/scripts/board.py`, so the board's cards and
order and the settings rules are the workflows' own); `bot/Dockerfile.dockerignore`
keeps the build context to those files.

```yaml
services:
  agentkit-bot:
    build: {context: /srv/agentkit, dockerfile: bot/Dockerfile}  # a checkout of the kit
    restart: unless-stopped
    read_only: true
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    environment:
      AGENTKIT_REPOS: owner/repo1,owner/repo2
      GITHUB_CLIENT_ID: Iv1.xxxxxxxx
      GITHUB_APP_KEY_FILE: /run/secrets/app_pem
      USERS_FILE: /run/secrets/users_json
      SLACK_BOT_TOKEN_FILE: /run/secrets/slack_bot_token
      SLACK_APP_TOKEN_FILE: /run/secrets/slack_app_token
      AGENTKIT_PREFS: /data/prefs.json      # the default
      AGENTKIT_KIT_BOT: your-kit-app-slug   # the kit's lifecycle App (its slug, without [bot])
      AGENTKIT_SLACK_APP_ID: A0123456789    # this Slack app's App ID
    volumes:
      - /srv/agentkit-bot/data:/data        # writable by the container's uid 10001 (see below)
    secrets: [app_pem, users_json, slack_bot_token, slack_app_token]
secrets:
  app_pem: {file: /srv/agentkit-bot/app.pem}
  users_json: {file: /srv/agentkit-bot/users.json}
  slack_bot_token: {file: /srv/agentkit-bot/slack_bot_token}
  slack_app_token: {file: /srv/agentkit-bot/slack_app_token}
```

**Prebuilt image.** `.github/workflows/bot-image.yml` builds the image on a GitHub-hosted runner, scans it with Trivy
(a fixable HIGH or CRITICAL finding fails the run), and on `main` pushes it to
`ghcr.io/<owner>/<repo>-bot` with a build-provenance attestation. Instead of `build:`, a server can use
`image: ghcr.io/<owner>/<repo>-bot@sha256:<digest>` and check it first with
`gh attestation verify oci://ghcr.io/<owner>/<repo>-bot@sha256:<digest> --repo <owner>/<repo>`. The first push creates a
private package: make it public, or log the server in to GHCR. Until the first run on `main`, build the image on the server.
A release tag (`v1.2.3`) gets its own image (`:v1.2.3`) and its digest and the verify line in its release notes. The
image pushed is the one Trivy scanned: the workflow builds once.

Secret files must be readable, and `/data` writable, by the container's uid 10001. With rootful Docker that is host uid
10001 (`chown 10001:10001`). Under rootless Docker it is a mapped host uid: the start of your range in `/etc/subuid`
plus 10000 (container uid 0 is you, uid 1 the range's start). Never enable debug logging for Bolt or the Slack SDK: it logs payloads. The bot logs one INFO line per action (Home opened, task sent, DM received, settings question sent):
who and which repo, never message text. A click with no line did not reach the bot; no `dm:` line after a DM means Slack
is not sending `message.im`.

## Turn it on for a repo

```
gh agentkit upgrade owner/repo --interface slack-bot --card-channel C0123456789   # also on setup and init
gh secret set SLACK_BOT_TOKEN --repo owner/repo        # the same xoxb- token the bot uses (input hidden)
```

`--interface slack-bot` is the Claude Code + Slack mode (`AGENTKIT_INTERFACE=claude-slack`, `AUTO_MERGE=true`) plus
`AGENTKIT_SLACK_BOT=true` and `AGENTKIT_CARD_CHANNEL`. The channel id is at the bottom of the channel's details (`C…`, or
`G…` for an old private channel); without `--card-channel` the value already set is kept, or you are asked for it. The
CLI never reads the token: it prints the `gh secret set` line for you to run. Merge the upgrade PR, so the caller has the
`repository_dispatch` trigger and the `reply` and `card` jobs, then check with `gh agentkit doctor owner/repo`.

With the bot on, `doctor` checks the variables, the `SLACK_BOT_TOKEN` secret (by name) and the caller. Export
`SLACK_BOT_TOKEN` in your shell first and it also asks Slack: `auth.test` (the token works) and `conversations.info` (the
channel exists and the bot is in it). That second call needs `channels:read` (`groups:read` for a private channel),
which the bot does not otherwise need; without it `doctor` says it can't check and carries on. Two things it cannot
check: whether the bot server is connected (Slack has no API for a Socket Mode connection; look at the container's log)
and the server's `users.json`.

When an issue starts waiting on a person (label `action:required`), the `card` job posts one short card to the
channel: the question from the agent's `STUCK:` message (with its `options` as buttons), the first line of an RFC or
research recommendation, or the first line of the kit's latest comment. A `needs-verification` issue gets a **Verify**
card instead: the PR's unticked Human verification items (up to 3), `Verified` and `Failed…` (what failed, sent as a
failed check). A `needs-human` issue after a failed run (`reason:env` or `reason:agent-error`) gets an **Attention**
card: one line of why, `Retry`, `Block…` and a `Logs` link to the run. It waits up to a minute for the kit's explaining
comment to land after the label. When the gate merges an agent PR, the channel gets a short **Done** card (title, the first line of the PR's
`## Summary`, link; no buttons) instead of the long "task done" message the webhook sends without the bot. The caller's
`dispatch` job needs the `SLACK_BOT_TOKEN` secret for it. The card job also leaves a hidden marker comment naming the card; when the issue gets a new
status without `action:required`, or closes, every card it has is edited to the outcome and loses its buttons.

To post a card by hand (for example to test), send the same JSON to `scripts/card.py post` with `SLACK_BOT_TOKEN` and
`SLACK_CHANNEL` set; add `"comments": [...]` to derive the ask, or `"ask"` and `"options"` to give them.

## Fewer cards (chief of staff)

Before a card is posted, `scripts/card.sh` holds it back in two cases. It never answers for anyone.

- **Already answered.** A person with write access (or a signed Slack reply record) commented on the issue after the
  kit's latest ask, and not a `/` command: the reply job has it, so no card.
- **Same blocker chain.** Another waiting issue with a live card has the same parent issue (sub-issues) or a
  `blocked_by` issue in common: that card gets a line `Also affects #n` (same ask, same buttons, which answer its own
  issue) and this issue a hidden marker pointing at it. When the card's own issue stops waiting, its card is resolved
  as usual and each folded issue that still waits gets its own card (or folds into another). When a folded issue stops
  waiting first, the shared card is left alone; its `Also affects` line may name it until the card is next rebuilt.

## Checks on every click

The bot maps the Slack user to a login, asks GitHub for that login's permission **now**, and refuses unless it is write,
maintain or admin. `reply.yml` checks the login again, then writes a **signed record** of the reply on the issue
(`scripts/slackrec.py`, HMAC under the App key). `people.sh` and the review gate count that record as the person's own
comment, so retry, guidance and RFC accept/reject work from Slack. A bot comment without a valid signature never counts.

## App Home, Add task and nudges

**The board.** The bot's Home tab shows, per repo in `AGENTKIT_REPOS` where the person's mapped login has write access
now: **Waiting on you** (open `action:required` issues, oldest first, each as its card with the same buttons),
**In progress** (`status:in-progress`, `status:review`), **Next up** (`status:ready` in the dispatcher's order from
`board.py`, without the Projects `Rank` and the debt quota; the ones the dispatcher never takes come last, saying why)
and **Done this week** (closed as completed in the last 7 days). Sections are capped to fit Slack's 100 blocks, with an
"and N more" link to the GitHub search. A Slack user who is not in `users.json` sees one line with their member ID to
send the owner. A button on the board works as on a card: the same checks, the same `agentkit-slack-reply`.
A waiting item's question comes only from the kit's own comments, so set `AGENTKIT_KIT_BOT` to the kit App's slug;
without it the board shows "Needs your input" and the status's buttons.

**+ Add task.** Each repo on the board has a `+ Add task` button: a modal (title, details) sends
`repository_dispatch` `agentkit-slack-task` `{title, body, login}` after the same mapping and write check as a click.
The `task` job in `reply.yml` checks the login, the lengths (title one line, at most 256 characters; body at most 3000)
and the person's write access again, then files the issue with the kit's App token, its body ending in
"Filed by @login from Slack.", with `status:refining`, so refine picks it up as it does a trusted author's new issue.
The project's caller needs the new event type: run `gh agentkit upgrade owner/repo`.

**Nudges.** Every 10 minutes the bot counts, per mapped person, the open `action:required` issues across the repos they
can write to. With one or more, it sends one DM, "N waiting", with a link to the Home tab (the link needs
`AGENTKIT_SLACK_APP_ID`). At most 2 a day, never twice within 4 hours, and only inside the person's nudge hours. The
settings live in `AGENTKIT_PREFS` (default `/data/prefs.json`), keyed by Slack user id, with the settings registry's
keys; the file also keeps when each nudge was sent, and is written atomically:

```json
{"prefs": {"U0123456789": {"nudge": "on", "nudge-hours": "09-20", "nudges-per-day": 2, "timezone": "Europe/Berlin"}},
 "history": {}}
```

Defaults: `nudge` `on`, `nudge-hours` `09-20`, `nudges-per-day` 2 (2 is also the most), `timezone` `UTC`. The bot reads
the file on every round, so an edit applies without a restart. If the file cannot be read or written (no volume, a
broken edit), the bot logs it and sends no nudges until it is fixed and the bot restarted; the board and clicks are
unaffected.

**What the owner changes to turn these on:**

1. Slack app settings: **Event Subscriptions** on, bot event `app_home_opened` (Socket Mode delivers it; no request URL).
   **App Home**: Home tab on, and Messages tab on (the nudge is a message there; "Allow users to send messages" may stay
   off). No new scope: `chat:write` posts the nudge to a person's DM with the app. Reinstall the app if Slack asks.
2. The bot's GitHub App: add the repository permission **Issues: read**, and accept the new permission on each
   installation.
3. Server: a writable volume at `/data` (the container's uid 10001; see [Run](#run)), and the env `AGENTKIT_KIT_BOT` and `AGENTKIT_SLACK_APP_ID`
   (both optional), as in the compose file above. The build context is now the kit's root.
4. Redeploy the bot (rebuild or pull the new image, then restart the container).

## Settings from Slack

**Asking.** DM the bot ("can I change the working hours?"), or use **Settings** at the top of its Home tab. The DM is
the one place the bot reads free text: only a person's own new message in their DM with it (not edits, threads or other
bots). The bot cannot match the question itself (the server has no model key), so it sends `repository_dispatch`
`agentkit-slack-settings` `{question, login, slack_user}` to the **first** repo in `AGENTKIT_REPOS` the person can write
to (the same mapping and check as a click), and says it is looking. The `settings` job in `reply.yml` checks the login
again, then runs Claude with only the question and the registry (`config/settings.json`, without how each setting is
applied): no checkout, no tools, one turn, a token that can only read Actions. It answers
`{"match": key|null, "answer": "…", "options": [...]}`; `scripts/settings.py card` keeps a known key only and only
options that pass the registry's rule, and the job DMs the card:

> **Can I change the working hours?** Yes: when the bot may nudge you. For which hours?
> `09-20` · `08-18` · `10-22` · `Other…` · `Your timezone ▾`

At most 3 options, `Other…` (a modal, validated as you type it in) where the setting allows free input, and for nudge
hours a timezone choice. No match: "Not something the kit can change yet." and **File as a feature request**, which
files the question as an issue in that repo through the `+ Add task` path. A setting only the server owner can change,
or a cron, is explained (and `/agentkit:settings` in Claude Code named) without buttons.

**Applying.** A click is validated against the registry again, in the bot; the model never writes a setting.

| Setting | Who | What happens |
|---|---|---|
| yours (`nudge`, `nudge-hours`, `nudges-per-day`, `timezone`) | any mapped person | the bot writes `prefs.json` at once (atomically) and edits the card: "Nudge hours: 08-18 (was 09-20)." with **Undo** |
| a repo variable (`wip`, `auto-merge`, …) | **admin** on the repo | `repository_dispatch` `agentkit-slack-setting` `{key, value, login, slack_user}`; the `setting` job checks admin and the value again, runs `gh variable set` and DMs what changed, with **Undo** |
| a `with:` input of the caller (`model`, `max-rounds`, …) | **admin** on the repo | the same event; the job opens a PR on `.github/workflows/agentkit.yml` titled "agentkit: set <key> to <value>" and DMs the link. Merging stays the owner's call. A multi-line input (`plugins: \|`) is left to `/agentkit:settings` in Claude Code |
| the bot's env, crons | the owner | explained only |

**What the owner changes to turn this on:**

1. Slack app settings: **Event Subscriptions**, add the bot event `message.im`; **OAuth & Permissions**, add the bot
   scope `im:history` (so the bot can read DMs sent to it); **App Home**, turn on "Allow users to send Slash commands
   and messages from the messages tab". Reinstall the app when Slack asks.
2. The kit's lifecycle GitHub App (the one `AGENTKIT_CLIENT_ID` names, not the bot's own App): add the repository
   permissions **Variables: write** (repo variables) and, for the caller PRs, **Workflows: write** with **Contents:
   write** and **Pull requests: write**; accept the new permissions on each installation. Without them that path fails
   and the person gets no DM; the rest works.
3. Each project: `gh agentkit upgrade owner/repo` and merge its PR, so the caller has the two new event types and its
   `reply` job passes `CLAUDE_CODE_OAUTH_TOKEN` and `SLACK_BOT_TOKEN`. `gh agentkit doctor owner/repo` warns until then.
4. Redeploy the bot: the image now also takes `scripts/settings.py` and `config/settings.json`.
