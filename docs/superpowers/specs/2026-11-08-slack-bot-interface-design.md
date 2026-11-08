# agentkit Slack bot: short cards, one front door

Date: 2026-11-08. Status: draft for approval. Supersedes the non-goal "No custom Slack bot or hosted server" in `2026-11-02-claude-code-and-slack-interface-design.md`. The state machine, gate, dependencies and retries in that spec do not change.

## Why

The engine works. The human interface does not:

1. **Messages are too long.** The Slack card is the raw GitHub comment, written by agents for agents.
2. **The interface is complicated.** A keyword grammar per status; thread replies are silently lost (only the Comment button works); one label filter per subscription; two front doors (Claude Code to steer, Slack to answer).
3. **The GitHub app for Slack is not a control surface.**

The old non-goal assumed a reply path needs a hosted endpoint. It does not: a Slack **Socket Mode** app connects outbound over a websocket and needs no public URL. It runs as one container on the owner's server.

## Decisions (the owner's)

- Own Slack bot (Socket Mode) replaces the GitHub app for Slack as the human interface.
- Two formats. Agents keep writing full comments on GitHub. Anything sent to the human is a short card with a hard budget.
- Three card kinds only: **Decide, Verify, Done**. `status:*` labels stay internal.
- Waiting items form a queue the owner clears in sessions, not a ping per event.
- One front door: Slack (board, intake, replies). Claude Code commands stay as optional power tools.
- A chief-of-staff layer: one voice, no duplicate or already-answered questions.
- Rejected: "default with a deadline". Not built.

## Architecture

```
Actions workflows ──chat.postMessage (bot token)──▶ Slack card
Slack button/modal ──Socket Mode──▶ bot container ──repository_dispatch "slack-reply"──▶ reply.yml
                                                                     reply.py ▶ apply-reply.sh (unchanged)
```

- **Outbound** needs no server: workflows post cards with the bot token. The card is built by one script (`scripts/card.py`) from the issue, so every status uses the same lint.
- **Inbound** is only interactions: buttons, modals, App Home. The bot does not read channel text.
- **One reply path.** A button is a reply keyword. The bot sends `{issue, text, slack_user}` to the repo as a `repository_dispatch` event; `reply.yml` runs the same `reply.py` and `apply-reply.sh` as for a Comment-button reply. Keyword grammar and actions live in one place (`reply.py`'s table), not in the bot.
- **Bot holds** the Slack bot token, the Slack app token, and the GitHub App key (to mint a short-lived token for the dispatch). All live on the server; the App key is also a repo secret already.

### Trust

Today trust is "the comment's author has write access". A bot post is by `agentkit-bot`, which the kit ignores on purpose ("agents cannot forge decisions"). So:

1. **Mapping.** The server holds `users.json`: Slack user id → GitHub login. Not in any repo.
2. **Bot check.** Before dispatching, the bot looks up the mapping and checks `collaborators/<login>/permission` is write, maintain or admin, on **every interaction**. Unmapped or unauthorized: ephemeral refusal, nothing dispatched.
3. **Workflow check, again.** `reply.yml` re-runs `.github/actions/trusted` on the login in the event payload. A bug or compromise in the bot cannot raise anyone above their real permission; it can only name a login that has write access. (A fully compromised bot holds the App key anyway, so this is defense in depth, not a boundary.)
4. **The record.** The reply workflow, not the bot, writes one comment on the issue: `Slack reply by @login:` + the text quoted, carrying `<!-- agentkit:slack-reply login=<login> id=<n> -->`. `people.sh` and the gate count a bot comment as a person's **only** when it has this marker, is by the kit's bot, and the login in it passes the write check. Agents cannot produce the marker: their text is already escaped (`<!--` → `&lt;!--`) and never starts a kit line.
5. **RFCs** still merge only on a real person's `accept`/`reject`, through the same record.

## Cards

Hard budget, linted: **title ≤ 80 chars, ask ≤ 160 chars, ≤ 3 buttons, 1 link**. `scripts/card.py lint` fails the docs job when a template or a sample card exceeds it. An agent never writes card text freely: the card is filled from the fields below.

| Kind | When | Content |
|---|---|---|
| **Decide** | `needs-info`, `needs-human` with a question, `needs-approval` (research, RFC, split) | title · one-line ask · 2–3 answer buttons · `Other…` (modal) · link |
| **Verify** | `needs-verification` | title · the 1–3 things to check, one line each · `Verified` · `Failed…` (modal) · link |
| **Done** | agent PR merged, issue closed | title · one line of what changed · link. No buttons. |
| *Attention* (a Decide variant) | `needs-human` with no question (failed run, `reason:env`, `reason:agent-error`) | title · one line of why · `Retry` · `Block…` · `Logs` (link) |

### Where the card text comes from

Agents already write the full comment. They add a small machine field the card is built from; the card never truncates prose.

- The implementer's `STUCK:` JSON gets `ask` (≤ 160) and `options` (2–3 strings ≤ 40, optional). Refine's questions get the same two fields per question (first open question becomes the card; the rest stay on GitHub).
- RFC and research recommendations already end in a one-line recommendation (`recommendation.py`); that line is the ask, and the buttons are `Accept` / `Reject…`.
- Missing `ask`: the card falls back to the title plus "Needs your input", with a link. The lint warns, not fails, so old comments still render.

### Buttons are existing keywords

| Button | Keyword → action (from `reply.py`) |
|---|---|
| Accept / Reject… | `accept` / `reject` → `decide` |
| Approve | `approve` → `approve-research` / `approve-split` |
| Verified / Failed… | `verified` / free text → `failed-check` |
| Retry | `retry` |
| Block… | `block <reason>` |
| An `options` button | free text = the option label → `answer` |
| Other… | modal → free text (`answer`, `guide`, `override-research`, `split-feedback` by status) |
| Research… | modal → `research <q>` |
| Done (mode:human) | `done` |

New keyword from the paper test: **`close <why>`** for `needs-info` and `needs-human`: closes the issue (completed if the work already exists, not planned otherwise) with the reason recorded. It covers "already done" and "don't build it" without free-text parsing. Added to `reply.py`'s table and the hint text; no other action changes.

## Batching

- Cards post to one **queue channel** with no @-mention, so they do not notify.
- The bot sends **one nudge** (DM) saying only "N waiting". Defaults, all per-person settings (see Settings): at most **2 per day**, never outside **nudge hours** (default 09:00-20:00 in the person's timezone), and only while the queue is non-empty. A card that arrives at night waits for the first allowed slot.
- **Verify and Decide nudge alike; neither bypasses the limit or the hours.** Done never nudges. Attention cards count.
- Cards resolve in place: after any button the card is edited to its outcome ("Accepted by @login") and its buttons removed. A card whose issue changed state elsewhere (answered in GitHub, closed) is edited the same way on the next event.

## App Home = the board

App Home replaces `/board`: waiting on you (Decide/Verify, oldest first, with the same buttons), in progress, next up (the dispatcher's order), done this week. One block per item, link out for detail. A `+ Add task` button opens a modal (title, body) that files an issue as a mapped, trusted person, which auto-enters `status:refining` as today. Reorder stays in Claude Code for now.

## Settings: ask the bot, get options

Goal: if something annoys the owner, they ask "can I change X?" and get an answer with choices the bot can apply. No docs to read, no variable names to know.

**Registry.** `config/settings.json` in the kit lists every configurable thing, one entry each: `key`, `scope` (`user` | `project`), plain-language `title` and `description`, `type`, `default`, `options` (the common choices, plus `other` for free input), `validate` rule, and `apply` (how a change is made). It covers real knobs only: nudge hours, nudges per day, timezone, `wip`, `debt-every`, `max-rounds`, `check-timeout`, `AUTO_MERGE`, `AUTO_SPLIT`, `model`, cron times for digest and retro, and so on. A test fails if a repo variable, caller `with:` input or bot env var used by the kit is missing from the registry, so the registry cannot rot.

**Two scopes, two ways to apply.**

| Scope | Examples | Stored | Applied by |
|---|---|---|---|
| `user` | nudge hours, nudges per day, timezone, queue vs DM | bot's `prefs.json`, keyed by Slack user | the bot, immediately |
| `project` | `wip`, `AUTO_MERGE`, `AUTO_SPLIT`, `debt-every`, `max-rounds` | repo variables | a repo variable write by `agentkit-bot` after the trust check (needs the App's `variables: write` permission) |
| `project`, in the caller file | `model`, `plugins`, crons, `suites` | `.github/workflows/agentkit.yml` | a PR from the bot; **merging stays the owner's OK** |

Changing a `project` setting needs admin permission on the repo (not just write), checked as in Trust. A `user` setting needs only a mapped user.

**Asking.** The owner DMs the bot (the one place it reads free text) or uses App Home → Settings. A read-only Claude run gets the question and the registry only (no repo access, no tokens) and returns JSON: `{match: <key>|null, answer, options[]}`. The bot renders it as a card:

> **Can I change the working hours?** Yes: nudges. For which hours?
> `09-20` · `08-18` · `Only weekdays` · `Other…` · timezone: `Europe/Berlin ▾`

A click validates against the registry's rule and applies it; the card then says what changed and how to undo it ("Back to 09-20"). `match: null` gets an honest "not configurable" plus `File as a feature request` (an issue by the owner in the kit repo's backlog). The model never writes settings: it only picks a registry entry and wording; the bot applies only values that pass `validate`.

**Also from Claude Code:** `/agentkit:settings` shows the same registry for those who prefer it. No second source of truth.

## Chief of staff (last slice)

**Changed when built:** one layer in the card job (`scripts/card.sh`, pure logic in `scripts/card.py`), before a card for issue N is posted. Checks run in this order:

- **No re-asking.** If a person with write access (`people.sh`, so verified Slack reply records count) commented on N after the kit's latest ask (the kit's latest comment with visible text that is not a Slack reply record), and the comment is not a `/` command, no card is posted: the reply job already has that answer. A failed read of people's comments posts the card.
- **Dedup.** Other open `action:required` issues are read with the kit's comments. One with a **live own card** (its latest marker is its own card's, and no kit ask came after it) in the same blocker chain as N (same parent via the sub-issues API `issues/{n}/parent`, or a `dependencies/blocked_by` issue in common, compared by URL) takes N in: the oldest such card is rebuilt from what it was posted from (its issue's kit comments before its marker, so the ask and buttons stay) plus a line `Also affects #a, #b` (every waiting issue folded into it, clipped to 80 characters), and `chat.update`d. N gets a fold marker `<!-- agentkit:card channel=C ts=T of=P -->`, which `resolve` does not match.
- **Resolving.** Only the card's own issue P resolves the shared card. After P's cards are resolved, every issue still waiting whose latest marker folds into one of them gets the same check and a card (`card.sh refold`). When a folded issue N stops waiting, the shared card is left as is: its `Also affects` line may still name N until the card is rebuilt by the next fold (the simplest correct choice; reading the card back would need `channels:history`).
- **Races.** N's fold marker is written before the update, and P's state is read again after it: if P stopped waiting meanwhile, P's cards are resolved again and N gets its own card. The worst case is two cards for one issue, never none. Two folds at once into one card can lose one `Also affects` entry (cosmetic; the fold marker still brings that issue its own card later).
- Only the kit's own comments count as asks and markers. A failed chain read means no fold.
- **Left out:** matching the same `ask` text across issues (or a research parent's decision record). Text matching is fuzzy, and a wrong match would hold back a question nobody answered, which is the one failure a suppress-only layer must not have. The exact check above (a person's say on N after the ask) cannot be wrong that way.
- Both are suppress-and-fold only; they never answer for the owner. Known limit: a person's comment that the reply job maps to no action leaves N waiting without a card.

## Mode flag and migration

**Changed in slice 2:** one extra boolean, not a third `AGENTKIT_INTERFACE` value. `AGENTKIT_INTERFACE=claude-slack` stays the mode (agents ask through Slack, waiting states carry `action:required`, `AUTO_MERGE=true`, the STUCK exit); `AGENTKIT_SLACK_BOT=true` on top of it turns on the bot: workflows post cards (`card.yml`) and the `reply` job accepts the bot's `repository_dispatch`. A third enum value would have touched about forty checks across the workflows for no gain. Retiring the GitHub app for Slack later means removing its subscription; nothing else changes. The "use the Comment button" line in GitHub comments is left as is for now.

Repo settings for the bot: variable `AGENTKIT_SLACK_BOT=true`, variable `AGENTKIT_CARD_CHANNEL` (the Slack channel id), secret `SLACK_BOT_TOKEN`. `gh agentkit setup|upgrade|init --interface slack-bot --card-channel C…` sets the three variables and prints the `gh secret set SLACK_BOT_TOKEN` line (the CLI never handles the token). `doctor` checks the variables, the secret by name and the caller's bot trigger and jobs; with `SLACK_BOT_TOKEN` exported locally it also runs `auth.test` and `conversations.info` for the channel (reported as "can't check" without `channels:read`). Not checked, and still to do if wanted: the `users.json` mapping for every person with write access who is meant to answer (a server file), and the bot connection (Slack has no API for a Socket Mode connection's state).

## Deploy

One Dockerfile, one container, on the owner's server. Env: Slack tokens, GitHub App id and key path, `users.json` path. No inbound port. Restart policy `unless-stopped`. Notes in `docs/slack-bot.md`.

## Build order (each slice through `scripts/canary.sh` on scratch)

1. Thin slice: bot container, one Decide card, `Accept`/answer button, mapping + permission check, dispatch → `reply.yml` → status change. No batching, no App Home.
2. Decide cards for all waiting states; `ask`/`options` fields; `close`; card lint.
3. Verify and Done.
4. App Home board and `+ Add task`.
5. Queue channel and nudges (per-user hours, 2 a day).
6. Settings: registry, registry-coverage test, DM/App Home Q&A, apply paths (user prefs, repo variables, caller PR).
7. Chief-of-staff dedup.
8. `gh agentkit` support and doctor.
9. Retire `claude-slack`.

## Evidence: paper test (2026-11-08)

Eight real waiting messages from `agentkit-scratch` were drafted as cards. Five were decidable from the card alone (RFC accept/reject, a library choice, two yes/no questions, a vague-review reply). Three exposed gaps, now in this spec: no keyword for "close as already done / do not build" (→ `close`), no options in `STUCK:` (→ `ask`/`options`), and failed runs cannot be decided from a card (→ Attention variant with a log link). Caveat: scratch issues are synthetic; check against a real project's messages before step 2.

## Decided by the owner (2026-11-08)

- Nudges: at most twice a day, not at night; Verify does not bypass. Attention cards count toward the nudge.
- Reordering stays in Claude Code for v1.
- Settings are asked and changed through the bot, with options (above).

## Open

- Where `users.json` and `prefs.json` live if there is ever more than one server (default: one server, local files).
- Whether the settings Q&A model reuses the repo's `model` setting or a cheaper one (default: cheaper, read-only, no tools).

## Not in scope

Reading channel text (DMs to the bot are read, for settings questions only), slash commands, a public endpoint, auto-answering for the owner, and any change to the state machine, gate, labels or dependency logic.
