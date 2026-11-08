# Slack bot (slack-bot interface): deploy notes

The bot is one container with no inbound port (Slack Socket Mode connects outbound). It turns a button click into a
`repository_dispatch` event `agentkit-slack-reply`; the project's `reply` job does the rest. Design: `docs/superpowers/specs/2026-11-08-slack-bot-interface-design.md`.

## Slack app

Create a Slack app from a manifest with Socket Mode on, Interactivity on, and bot scope `chat:write` (plus `chat:write.public`
if the queue channel is public). Install it. Keep two tokens: the bot token (`xoxb-…`) and an app-level token (`xapp-…`,
scope `connections:write`).

## Server files (never in a repo)

| File | Content |
|---|---|
| `users.json` | `{"<Slack user id>": "<github login>"}`, one per person who may answer |
| `app.pem` | the agentkit GitHub App's private key |

## Run

```
docker build -t agentkit-bot bot/
docker run -d --restart unless-stopped --name agentkit-bot \
  -e SLACK_BOT_TOKEN -e SLACK_APP_TOKEN -e GITHUB_CLIENT_ID \
  -e AGENTKIT_REPOS=owner/repo1,owner/repo2 \
  -e GITHUB_APP_KEY_FILE=/secrets/app.pem -e USERS_FILE=/secrets/users.json \
  -v /srv/agentkit-bot:/secrets:ro agentkit-bot
```

## Post a card (slice 1, by hand)

```
echo '{"repo":"owner/repo","number":7,"title":"…","ask":"…","labels":["status:needs-approval","type:research"]}' \
  | SLACK_BOT_TOKEN=… SLACK_CHANNEL=C… python3 scripts/card.py post
```

Workflows post cards by themselves in the next slice.

## Checks on every click

The bot maps the Slack user to a login, asks GitHub for that login's permission **now**, and refuses unless it is write,
maintain or admin. `reply.yml` checks the login again, then writes a **signed record** of the reply on the issue
(`scripts/slackrec.py`, HMAC under the App key). `people.sh` and the review gate count that record as the person's own
comment, so retry, guidance and RFC accept/reject work from Slack. A bot comment without a valid signature never counts.
