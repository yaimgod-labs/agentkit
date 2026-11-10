# Claude Code + Slack as the only human interface

Date: 2026-11-02. Status: draft for approval.

## Intent

The owner never opens GitHub. GitHub stays the agents' workspace (issues, labels, PRs, Actions, board). The person works in two places:

- **Claude Code**: where they look at the board, add work, read details and reorder.
- **Slack**: where GitHub-side agents reach them, for questions, research approval, split approval, verification and "done" notes. They answer with the **Comment** button on the message (see Spike result).

Questions follow where the person is. In an interactive Claude Code session the model asks in chat. An agent running on GitHub asks through Slack.

## Goals

1. **Stuck message.** When a GitHub agent can't continue, Slack shows the task (title + link), what it is stuck on, why it can't decide alone, and what it already checked in docs/decisions/research.
2. **Three replies** to a stuck message, each sent with the message's Comment button:
   - **Answer**: free text. The agent continues with it.
   - **Research**: `research <what to find out>`. A research task is filed and linked as a blocker of the stuck task.
   - **Block**: `block <reason>`. The task goes to `status:blocked` with the reason recorded. The person returns to it later.
3. **Research loop with approval.** An agent can start research itself, at refine or mid-implementation, on GitHub only, by filing a research sub-task and blocking on it. Research started from a reply works the same way. When the recommendation is ready, Slack shows the question, the recommendation, the confidence and a link.
   - `approve` merges the research doc, posts the recommendation as the answer on the blocked task, and resumes that task.
   - Any other reply is the person's own answer. It wins: the research PR is closed, the answer is posted on the blocked task, and the task resumes.
4. **Split approval, configurable.** Refine no longer waits for a manual `/plan` on `size:m`/`size:l`. It proposes the split.
   - Default: Slack shows the proposed sub-tasks. `approve` creates them. Any other reply is feedback, and the split is proposed again.
   - Repo variable `AUTO_SPLIT=true` creates the sub-tasks without asking, for users who want that.
5. **Done message.** When a task's PR merges, Slack says "task X done" with a short summary: what changed, how, and the PR link. Merging is automatic (`AUTO_MERGE=true`) once checks pass.
6. **Verification and RFC decisions from Slack.**
   - On a `needs-verification` ping, `verified` ticks the Human verification boxes and the gate approves.
   - On an RFC ping, `accept <why>` / `reject <why>` acts like today's `/decide`.
7. **Claude Code commands:**
   - `/task <what you want>`: runs refine interactively in the chat. Questions are asked there, and the issue is filed already refined. If it needs research, a research sub-task is filed on GitHub. If it is big, the split is proposed in the chat for the person's OK.
   - `/board`: open tasks with status and stage, time estimate, "waiting on you" items, and the top 5 todo in the order the dispatcher will take them.
   - `/board <n>`: full detail of one task (description, plan, comments, PR).
   - Reorder ("move #12 to top") and unblock (`blocked` → back into the flow) from Claude Code. The dispatcher respects that order.
8. **New tasks from Slack too.** The GitHub Slack app's `/github open <repo>` creates an issue. A new issue by a trusted person with no `status:*` label gets `status:refining` automatically.
9. **Ask less.** Before any question, an agent searches docs, decisions and past research (`find-knowledge`). If they settle it, it proceeds and cites them. A question it does ask names what it checked.

## Dependencies: foolproof

The person's rule: a task can never start while a task it depends on isn't done. Dependencies are GitHub's native issue dependencies (`blocked_by`), as `/plan` already uses them. This applies in both modes, since it's a correctness fix, not an interface change.

- **Checked where work starts.** The implement workflow checks open blockers before running Claude. If there are any, it doesn't start: it sets the task back to `ready`, comments which blocker holds it, and spends no tokens. That catches every route into `in-progress`, including manual labels and `/board`. The dispatcher keeps its own check, so it doesn't pick blocked tasks in the first place. `/next` stays as it is (local, already checks).
- **Done means completed.** A blocker counts as done only when it's closed with reason `completed`. Its fix merged into the base branch closes it that way already.
- **Dropped blocker.** If a blocker is closed with any other reason (not planned, duplicate):
  - every task waiting on it goes to `status:blocked`, reason "dropped dependency: #A (title)";
  - a task that's already blocked keeps its old reason and gets this one added;
  - the dependency link stays as history but no longer holds or releases anything;
  - the task leaves `blocked` only on `unblock` or a reply naming a replacement;
  - one Slack ping per drop lists the affected tasks (the author's guess that this is worth a ping; the person didn't object).
- **Chains need no cascade.** If C waits on B and B waits on dropped A, B goes blocked and stays open, so C is still held.
- **Refine finds dependencies.** Refine (CI, Slack-started or `/task`) searches open tasks for ones this task needs and records them as `blocked_by`. It lists what it added, and the person can remove a wrong one. Refine's token is read-only, so the workflow applies them from the verdict, like labels today.
- **Visible.** `/board` shows "waiting on #B" on held tasks and "holds up #C, #D" on blockers.
- Constraint: `set-status.sh` keeps at most one `reason:*` label, so several block reasons live in comments (and on `/board`), not as several labels. The builder decides the exact record.

## Non-goals

- No GitHub UI for the person, ever, after one-time setup (setup stays the `gh agentkit` CLI, which can run from Claude Code).
- No inline research agent in Claude Code. Agent-started research is always a GitHub research task.
- No answering stuck messages from Claude Code (Slack is the reply channel). `/board` links to them.
- No custom Slack bot or hosted server.

## Anti-goals (failure even if it works)

- **Slack noise.** Messages the person doesn't need to act on, beyond the done message: refine plans, review rounds, label churn, pushes. If the channel is worth muting, this failed.
- Questions whose answer is already in `docs/`, `docs/decisions/` or `docs/research/`.
- Having to open GitHub to unblock anything.

## Constraints (from the current kit)

- **Replies must reach GitHub with no server.** The only no-server path from Slack to GitHub is the GitHub app for Slack: its **Comment** button on an issue message posts an issue comment as the person's linked GitHub account (a plain thread reply does not reach GitHub; see Spike result). That keeps the existing trust check (write access) working. Incoming webhooks are one-way: fine for the done message and digest, useless for anything that needs a reply.
- **Slack swallows leading `/`.** A Slack message starting with `/` is treated as a slash command and isn't sent. Reply keywords are plain words at the start of the reply: `approve`, `research …`, `block …`, `verified`, `accept …`, `reject …`. On GitHub, `/plan` and `/decide` keep working as before.
- **The app's label filter.** The GitHub Slack app keeps one label filter per subscription, and filtered subscriptions only post about issues carrying that label. So "waiting on you" must be one label: `action:required` (the person's choice of name), added by `scripts/set-status.sh` when the status enters `needs-info`, `needs-human`, `needs-verification` or a pending research/split approval, and removed on leaving. The channel subscribes with `+label:"action:required"` only. The broad `issues pulls discussions releases` subscription goes away.
- **All label changes go through `scripts/set-status.sh`.** It keeps exactly one `status:*`. It is the natural owner of `action:required`.
- Writes use the `agentkit-bot` App token. Claude gets read-only or downscoped tokens. Only trusted authors/commenters are acted on. All new comment commands go through `.github/actions/trusted`.
- GitHub Free: no branch protection on private repos, and merging stays the gate's `gh pr merge` when `AUTO_MERGE=true`.

## How it fits the existing pieces

| Need | Existing piece | Change |
|---|---|---|
| Stuck ping | refine `needs-info` comment, `needs-human` handovers | `action:required` label + message shape (task, stuck on, why, checked) |
| Answer → continue | comment on `needs-info` re-runs refine | also covers mid-implementation questions (below) |
| `research` / `block` / `approve` / `verified` / `accept` / `reject` replies | `/plan`, `/decide` comment parsing in caller + dispatch | one comment-command handler for issue comments |
| Research task | `type:research` → `docs/research/<slug>.md` PR | link as blocker (`blocked_by`), hold the merge for approval, resume parent |
| Split | `plan.yml` on `/plan` | refine triggers it for m/l; `AUTO_SPLIT` decides ask vs auto |
| Done message | PR merge closes issue | post summary to Slack (webhook) on merge |
| Board | Projects board, **Stage** field mirrored from labels | `/board` command reads it; rank stored on the board |
| Order | dispatcher: priority label, then number | dispatcher reads rank first |
| Estimates | `scripts/retro.py` cycle time; refine `size:*` | range per size from recent closed issues |

## Opt-in per project (the person's decision)

The mode is off unless a project turns it on with the repo variable `AGENTKIT_INTERFACE=claude-slack` (the variable's name is the author's call). Off means `v1` behaves exactly as today, so existing projects see no change on their next run.

On turns on:
- new issues auto-refining;
- refine proposing splits (with `AUTO_SPLIT`);
- research and RFC merge holds;
- Slack reply keywords;
- the `action:required` label;
- the done message;
- the `AUTO_MERGE=true` requirement.

`gh agentkit upgrade --interface claude-slack` (or `init`) sets the variable, `AUTO_MERGE`, and the labels, and prints the Slack subscription lines. Doctor checks the mode's requirements only where the mode is on. `/board` and `/task` work in either mode, since they only read the board or file issues.

## Settled after review (author's calls, not the person's)

- **Issue templates** label new issues `status:backlog` today. In this mode they start at `refining` (or with no status, which auto-refining handles).
- **New sub-tasks enter at `status:refining`.** That covers a split approved in Slack, under `AUTO_SPLIT`, or in `/task`. Refine then sizes each one and writes its criteria, so nothing waits for a manual "ready". An issue filed by `/task` lands at `ready` (xs/s, nothing open) or goes through the split. `status:backlog` keeps one meaning: parked on purpose. `plan-feature` and `plan.yml` change to match.
- **Replies outside answer / research / block:**
  - On `needs-verification`, a free-text reply (not `verified`) is a failed check. The PR goes to `changes-requested` with that text as the feedback.
  - On `needs-human` (failed rounds, `reason:env`, `reason:agent-error`), a free-text reply re-runs the implementer on the existing branch with the reply as guidance, and resets the review-round counter. `retry` re-runs without guidance.
  - On a `mode:human` task, `done` closes it, from Slack or `/board`. These tasks carry `action:required` while ready.
- **`AUTO_MERGE=true` is required in this mode.** Setup and upgrade set it, and doctor fails without it. `approved` is never a waiting state.
- **RFC PRs are held like research PRs.** The gate doesn't merge an RFC until `accept`/`reject`. The pending decision is a `action:required` state.
- **Manual rank beats everything.** A ranked issue goes ahead of the debt quota and priority. The quota and priority only order the unranked rest. `/board`'s top 5 uses the same sort as `dispatch.yml`, from one shared definition.

## Left to the builder

- **Mid-implementation questions.** The implementer has no "ask" exit today; it either finishes or hands over to `needs-human`. Pick how it stops with a question, and how the answer resumes the work without losing the branch. Reusing refine → ready → implement on the existing `agent/<n>-…` branch is one option.
- **Rank storage.** Default: a number field on the board, read by the dispatcher before priority. With no board configured, fall back to today's order.
- **Estimate formula.** Default: per size, the 25th–75th percentile cycle time of the last ~20 closed issues of that size. Below ~5 samples, show size-based defaults (xs <1h, s ≤1 day).
- Exact message wording, within the content listed in Goals.
- Whether the daily digest stays (default: keep it; it skips empty days and is one message), and whether the weekly retro posts one Slack line with a link instead of going through the Discussions subscription (default: yes).
- Labels and Stage options added via `gh agentkit upgrade`. README and template updates.

## Risks to check first

- **Does the GitHub Slack app post when a filtered label is added to an issue,** and are the agent's later comments threaded under it so replies land on the right issue? Spike this on the scratch repo before building on it. If it doesn't, the fallback is a small Slack app of our own, which needs a hosted endpoint for replies. That would be a separate decision.
- Slack ↔ GitHub account linking (`/github signin`) is required for replies to count as the person's. Doctor should check it, or the docs must say it.

## Spike result (2026-11-03, scratch repo, test channel)

Subscription: `/github subscribe <owner>/<scratch-repo> issues comments +label:"action:required"`, defaults (`pulls commits releases deployments`) unsubscribed.

| Question | Answer |
|---|---|
| Does adding the label post a message? | Yes. The App adding `action:required` posted one issue card ("Issue created by …", label shown) within the minute, even though the issue was opened earlier. |
| Does the App's comment appear in that message's thread? | Yes, under the card, with Markdown (bold, code) kept. |
| Does a reply from a linked account land as an issue comment by that account? | A plain thread reply: **no**, it stays in Slack. The card's **Comment** button: **yes**. The comment is by the person's account (`user.type` User, `author_association` MEMBER, `performed_via_github_app` slack), so the trusted-commenter check works unchanged. |
| Does a reply starting with a plain word post normally? | Yes (`research …` posted both ways). |

**Decision (the person's):** replies go through the Comment button, not thread replies. No server of our own. Every message that waits on the person ends with one line telling them to answer with the Comment button. The fallback (our own Slack app with a hosted endpoint) is not needed.
