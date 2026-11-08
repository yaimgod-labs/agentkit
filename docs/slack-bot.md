# Slack bot (slack-bot interface): deploy notes

The bot is one container with no inbound port (Slack Socket Mode connects outbound). It turns a button click into a
`repository_dispatch` event `agentkit-slack-reply`; the project's `reply` job does the rest. Design: `docs/superpowers/specs/2026-11-08-slack-bot-interface-design.md`.

## Slack app

Create a Slack app with Socket Mode on and Interactivity on, **no event subscriptions**, and one bot scope: `chat:write`
(no `chat:write.public`). Keep two tokens: the bot token (`xoxb-…`) and an app-level token (`xapp-…`, scope
`connections:write`). Use a **private** channel for the cards and invite the bot; who may act is decided by `users.json`,
not by who can see the channel.

## GitHub App

Give the bot **its own GitHub App** if you can: it needs only `contents: write` (for `repository_dispatch`) and
`metadata: read` (the permission check). The workflows sign the reply record with the lifecycle App's key, so the bot
never holds that key. Install it only on the repos in `AGENTKIT_REPOS`, and protect the default branch there (rulesets),
since `contents: write` can push to an unprotected branch. The bot mints a token per click for that one repo, limited to
those two permissions.

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
user and works on a read-only filesystem.

```yaml
services:
  agentkit-bot:
    build: ./bot
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
    secrets: [app_pem, users_json, slack_bot_token, slack_app_token]
secrets:
  app_pem: {file: /srv/agentkit-bot/app.pem}
  users_json: {file: /srv/agentkit-bot/users.json}
  slack_bot_token: {file: /srv/agentkit-bot/slack_bot_token}
  slack_app_token: {file: /srv/agentkit-bot/slack_app_token}
```

**Prebuilt image.** `.github/workflows/bot-image.yml` builds the image on a GitHub-hosted runner, scans it with Trivy
(a fixable HIGH or CRITICAL finding fails the run), and on `main` pushes it to
`ghcr.io/<owner>/<repo>-bot` with a build-provenance attestation. Instead of `build: ./bot`, a server can use
`image: ghcr.io/<owner>/<repo>-bot@sha256:<digest>` and check it first with
`gh attestation verify oci://ghcr.io/<owner>/<repo>-bot@sha256:<digest> --repo <owner>/<repo>`. The first push creates a
private package: make it public, or log the server in to GHCR. Until the first run on `main`, build the image on the server.

Secret files must be readable by uid 10001. Never enable debug logging for Bolt or the Slack SDK: it logs payloads.

## Turn it on for a repo

On top of `AGENTKIT_INTERFACE=claude-slack`, set on the repo:

```
gh variable set AGENTKIT_SLACK_BOT --repo owner/repo --body true
gh variable set AGENTKIT_CARD_CHANNEL --repo owner/repo --body C0123456789
gh secret set SLACK_BOT_TOKEN --repo owner/repo        # the same xoxb- token the bot uses
```

and run `gh agentkit upgrade owner/repo` so the caller has the `repository_dispatch` trigger and the `reply` and `card`
jobs. When an issue starts waiting on a person (label `action:required`), the `card` job posts one short card to the
channel: the question from the agent's `STUCK:` message (with its `options` as buttons), the first line of an RFC or
research recommendation, or the first line of the kit's latest comment. It waits up to a minute for the kit's explaining
comment to land after the label. When the gate merges an agent PR, the channel gets a short **Done** card (title, the first line of the PR's
`## Summary`, link; no buttons) instead of the long "task done" message the webhook sends without the bot. The caller's
`dispatch` job needs the `SLACK_BOT_TOKEN` secret for it. The card is posted once per `action:required` label; it is not yet edited when the
issue is answered or closed somewhere else.

To post a card by hand (for example to test), send the same JSON to `scripts/card.py post` with `SLACK_BOT_TOKEN` and
`SLACK_CHANNEL` set; add `"comments": [...]` to derive the ask, or `"ask"` and `"options"` to give them.

## Checks on every click

The bot maps the Slack user to a login, asks GitHub for that login's permission **now**, and refuses unless it is write,
maintain or admin. `reply.yml` checks the login again, then writes a **signed record** of the reply on the issue
(`scripts/slackrec.py`, HMAC under the App key). `people.sh` and the review gate count that record as the person's own
comment, so retry, guidance and RFC accept/reject work from Slack. A bot comment without a valid signature never counts.
