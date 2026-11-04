# Claude Code + Slack Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** People run agentkit from Claude Code and Slack and never open GitHub. Tasks can't start before their dependencies are done.

**Architecture:** The plan has three parts, and each ships as its own PR:
- **Part A, dependencies:** applies in both modes.
- **Part B, Claude Code commands:** applies in both modes.
- **Part C, Slack mode:** opt-in through `AGENTKIT_INTERFACE=claude-slack`. It starts with a manual spike.

Logic goes into small scripts under `scripts/` (CI) or `plugins/agentkit/scripts/` (shared with local commands). Tests feed them JSON on stdin or run them against a fake `gh` on `PATH`, the way `tests/test_set_status.sh` and `tests/test_retro.py` do. Workflows stay thin and call the scripts.

**Tech Stack:** bash (must parse under macOS bash 3.2), python3 stdlib, jq, `gh` CLI, GitHub Actions reusable workflows, GitHub issue dependencies API, Projects v2, the GitHub app for Slack, Slack incoming webhook.

**Spec:** `docs/superpowers/specs/2026-11-02-claude-code-and-slack-interface-design.md`

## Global Constraints

- Mode switch: repo variable `AGENTKIT_INTERFACE=claude-slack`. When it's unset, every behavior from Part C is off and v1 behaves as today.
- `AUTO_SPLIT=true` creates sub-tasks without asking. Unset means ask.
- In the mode, `AUTO_MERGE=true` is required.
- Waiting label: `action:required`. Statuses that carry it: `needs-info`, `needs-human`, `needs-verification`, `needs-approval`, plus `ready` when the task has `mode:human`.
- New status `status:needs-approval` (board Stage "Needs approval"). Covers research recommendations, RFC decisions and split proposals.
- Replies reach GitHub only through the Slack card's **Comment** button (a plain thread reply stays in Slack; spec, Spike result). Every comment that sets `action:required` ends with the line `Answer with the Comment button on this issue's card in Slack.`
- Reply keywords are plain words at the start of a reply, never a leading `/`:
  - `approve`
  - `research <q>`
  - `block <reason>`
  - `unblock`
  - `replace #N`
  - `verified`
  - `accept <why>`
  - `reject <why>`
  - `retry`
  - `done`

  Anything else is free text.
- Only a blocker closed with `state_reason == "completed"` counts as done.
- Dropped-blocker reason text: `dropped dependency: #<n> (<title>)`.
- New sub-tasks start at `status:refining` in the mode. Outside the mode they start at `status:backlog`, as today.
- All status changes go through `scripts/set-status.sh`. All writes use the App token. Every comment command checks its commenter with `.github/actions/trusted`.
- Block reasons live in comments marked `<!-- agentkit:block -->`. `reason:*` labels stay at most one.
- `tests/run.sh` and `./actionlint` must pass after every task. Add each new test to `tests/run.sh` and each new `.sh` to its shellcheck line.
- Commits follow `<type>: <description>` and end with the attribution line from the session.
- Never push, merge or tag without the user's explicit OK, each time.

## Review Focus

1. **A blocker in another repo.** `blocked_by` can point across repos. The scripts must read `state` and `state_reason` from the API response, never look the number up in the current repo. Test: `test_blockers_cross_repo` (Task A1).
2. **A reply with leading whitespace, capitals or a trailing period** (`Approve.`, `  block waiting on legal`). It must parse as the keyword. Test: `test_keyword_case_and_punctuation` (Task C2).
3. **A keyword that doesn't fit the status** (`verified` on a `needs-info` issue). It must not change state. It answers with a one-line hint. Test: `test_keyword_wrong_status` (Task C2).
4. **A blocker reopened after its dependents started.** The implement check runs only when work starts, so the task keeps going. That's acceptable, and the board must still show "waiting on". Test: `test_board_waiting_on_includes_open_blockers` (Task B1).
5. **An issue with no board configured** (`AGENTKIT_PROJECT` unset). Rank falls back to today's order, and `/board` still lists tasks. Test: `test_order_without_rank` (Task B1).

---

# Part A: Foolproof dependencies (both modes)

### Task A1: Blocker classification script

**Files:**
- Create: `scripts/blockers.sh`
- Test: `tests/test_blockers.sh`
- Modify: `tests/run.sh`

**Interfaces:**
- Produces: `scripts/blockers.sh <owner/repo> <issue> open|dropped`. It prints one `<number>` per line:
  - `open`: blockers with `state == "open"`.
  - `dropped`: blockers that are closed with `state_reason != "completed"`.

  It reads `gh api repos/<repo>/issues/<n>/dependencies/blocked_by --paginate`. It exits 0 when there are none.

- [ ] **Step 1: Write `tests/test_blockers.sh`.** Use a fake `gh` that prints `$FAKE_JSON` for `api`. Cases:
  - `[{"number":3,"state":"open"},{"number":4,"state":"closed","state_reason":"completed"},{"number":5,"state":"closed","state_reason":"not_planned"}]`: `open` prints `3`, `dropped` prints `5`.
  - `[]`: both print nothing.
  - `test_blockers_cross_repo`: an item with `"repository_url":"https://api.github.com/repos/x/y"`, `number` 9, `state` `open` prints `9` (no second lookup).
- [ ] **Step 2: Run** `tests/test_blockers.sh`. Expected: it fails because the script is missing.
- [ ] **Step 3: Implement `scripts/blockers.sh`** as one `gh api … --jq` per mode. Copy `set -euo pipefail` and the usage comment style from `set-status.sh`.
- [ ] **Step 4: Run** `tests/test_blockers.sh && tests/run.sh`. Expected: all `ok`.
- [ ] **Step 5: Commit** with message `feat: blockers.sh classifies open and dropped dependencies`.

### Task A2: Dispatcher and implement both refuse open blockers

**Files:**
- Modify: `.github/workflows/dispatch.yml` (the "Promote next ready issue" step)
- Modify: `.github/workflows/implement.yml` (new `check` job before `implement`)

**Interfaces:**
- Consumes: `scripts/blockers.sh <repo> <n> open` (A1).
- Produces: a `check` job with `outputs.held` (`"true"` or `"false"`). `implement` gets `needs: check` and `if: needs.check.outputs.held != 'true'`.

- [ ] **Step 1:** In dispatch, replace the inline `gh api …/blocked_by --jq` count with `.agentkit-kit/scripts/blockers.sh "$REPO" "$n" open | grep -c .`.
- [ ] **Step 2:** Add a `check` job to implement. It needs an App token (issues: write) and "Load agentkit" (the same block as the other jobs). It runs only when the label is `status:in-progress`. If `blockers.sh … open` prints anything, it does three things:
  - comments `agentkit: not starting — waiting on #a, #b. It goes back to ready and starts when they are done.`;
  - runs `set-status.sh … status:ready`;
  - sets `held=true`.
- [ ] **Step 3: Run** `./actionlint -color && tests/run.sh`. Expected: clean.
- [ ] **Step 4: Commit** with message `fix: implement never starts an issue with open blockers`.

### Task A3: Dropped blocker moves its dependents to blocked

**Files:**
- Create: `scripts/drop-dependency.sh`
- Test: `tests/test_drop_dependency.sh`
- Modify: `.github/workflows/dispatch.yml` (new step + `SLACK_WEBHOOK_URL` optional secret)
- Modify: `templates/.github/workflows/agentkit.yml`:
  - add `closed` to `issues.types`;
  - add `(github.event_name == 'issues' && github.event.action == 'closed')` to the dispatch `if`;
  - pass `SLACK_WEBHOOK_URL`.
- Modify: `tests/fixture-callers/*.yml` and `tests/test_caller.py` if a fixture assertion pins the trigger list.

**Interfaces:**
- Produces: `scripts/drop-dependency.sh <repo> <closed-issue> <closed-title>`. For each open issue in `gh api repos/<repo>/issues/<n>/dependencies/blocking`, it:
  - comments `<!-- agentkit:block -->\n**Blocked:** dropped dependency: #<n> (<title>)`;
  - runs `set-status.sh <repo> <dep> status:blocked`.

  It prints the affected numbers, one per line. Already-blocked dependents get the comment too, and set-status leaves their label as it is.

- [ ] **Step 1: Write `tests/test_drop_dependency.sh`** with a fake `gh` that logs every call to `$FAKE_LOG`. With dependents `[{"number":7,"state":"open"},{"number":8,"state":"closed"}]`, the log has exactly:
  - one `issue comment 7` call whose body contains `dropped dependency: #3 (Old idea)`;
  - one `issue edit 7 … --add-label status:blocked`;
  - nothing for 8.

  stdout is `7`.
- [ ] **Step 2: Run it.** Expected: FAIL.
- [ ] **Step 3: Implement** the script. It calls `"$(dirname "$0")/set-status.sh"`.
- [ ] **Step 4: Add a dispatch step "Block dependents of a dropped issue".** Condition: `github.event_name == 'issues' && github.event.action == 'closed' && github.event.issue.state_reason != 'completed'`. It runs the script. If the script printed anything and `SLACK` is set, it posts one webhook message: `Dropped #<n> <title>. Blocked: #7 <title>, …` (copy the curl line from `digest.yml`).
- [ ] **Step 5: Run** `tests/test_drop_dependency.sh && ./actionlint -color && tests/run.sh`. Expected: clean.
- [ ] **Step 6: Commit** with message `feat: a dropped blocker moves its dependents to blocked`.

### Task A4: Refine finds and records dependencies

**Files:**
- Modify: `plugins/agentkit/skills/refine-issue/SKILL.md`
- Modify: `.github/workflows/refine.yml` ("Apply verdict" step)

**Interfaces:**
- Produces: the VERDICT JSON gains an optional key `"blocked_by": [<issue numbers in this repo>]`. The refine comment gains a `## Depends on` section listing them, each with one line of why.

- [ ] **Step 1: Skill.** Add a step 2a: search open issues (`gh issue list --state open --search "<terms>" --json number,title`) for work this issue needs first. List them under `## Depends on` and in `blocked_by`. Only real prerequisites count: never related, never "nice to do first". Update the example VERDICT line and the "exactly those four keys" sentence to say "those four keys, plus `blocked_by` when there are dependencies".
- [ ] **Step 2: Workflow validation.** The verdict may have `blocked_by`, but only as an array of integers. Drop the issue's own number. Add each one with `gh api repos/$REPO/issues/$N/dependencies/blocked_by -F issue_id=$(gh api repos/$REPO/issues/<b> --jq .id)`, skipping any that fail (closed, missing, already linked) with a `::warning::`.
- [ ] **Step 3: Run** `./actionlint -color && tests/run.sh`. Expected: clean.
- [ ] **Step 4: Commit** with message `feat: refine records the dependencies it finds`.

---

# Part B: Claude Code commands (both modes)

### Task B1: Shared order and board data

**Files:**
- Create: `plugins/agentkit/scripts/board.py`
- Test: `tests/test_board.py`
- Modify: `.github/workflows/dispatch.yml` ("List ready issues": replace the inline jq sort with `board.py order`)
- Modify: `tests/run.sh` (test + `py_compile`)

**Interfaces:**
- Produces: `board.py order --debt-due true|false --debt-every N --debt-label L`. Reads JSON `[{number, author, labels:[names], rank: number|null}]` on stdin and prints the same list, filtered and sorted:
  - drop `mode:human`, `size:m` and `size:l`;
  - sort key `(rank is null, rank, d, p, number)`, where `d` and `p` are today's debt flag and priority index from `dispatch.yml`.

  A ranked issue always goes before unranked ones.
- Produces: `board.py estimate`. Reads JSON `{"closed": [{size, started_at, closed_at}], "open": [{number, size}]}` and prints `{<number>: "~Xh–Yh" | "~X–Y days"}`:
  - with 5 or more samples of a size: the 25th–75th percentile of its last 20 cycle times;
  - otherwise the defaults `xs: "<1h"`, `s: "≤1 day"`, `m: "several days"`, `l: "an epic"`.
- Produces: `board.py render`. Reads `{"issues": [...], "deps": {<n>: {"waiting_on": [..], "holds_up": [..]}}, "estimates": {...}}` and prints the markdown board:
  - sections: Waiting on you · In progress · Up next (top 5) · Blocked (with the latest `<!-- agentkit:block -->` reasons);
  - each line: `#n title — stage — estimate — waiting on #b`.

- [ ] **Step 1: Write `tests/test_board.py`** with these cases:
  - `test_order_matches_dispatch_today`: no ranks, `debt_due=false`. A `priority:high` issue sorts before a lower-numbered unlabelled one, and a `type:debt` issue sorts last.
  - `test_rank_beats_priority_and_debt`: `rank: 1` on a `priority:low` issue puts it first, even with `debt_due=true` and a `type:debt` issue present.
  - `test_order_without_rank`: every `rank` is `null`, and the result equals today's sort.
  - `test_estimate_percentiles`: 8 `s` samples at 1..8 h give `"~3h–6h"`. 2 samples fall back to `"≤1 day"`.
  - `test_board_waiting_on_includes_open_blockers`: the render shows `waiting on #4` for an issue whose deps list 4, even when its status is `in-progress`.
  - `test_render_sections_and_top5`: 7 ready issues, only 5 shown under "Up next", in `order` order.
- [ ] **Step 2: Run** `python3 tests/test_board.py`. Expected: FAIL (no module).
- [ ] **Step 3: Implement `board.py`** with stdlib only: argparse subcommands and `statistics.quantiles`.
- [ ] **Step 4: Dispatch.** Build the input with a `rank` read from the board's `Rank` number field. When `AGENTKIT_PROJECT` is set, use one GraphQL query for the project items' `fieldValueByName(name:"Rank")`. Otherwise `null`. Pipe it through `.agentkit-kit/plugins/agentkit/scripts/board.py order …`.
- [ ] **Step 5: Run** `python3 tests/test_board.py && ./actionlint -color && tests/run.sh`. Expected: clean.
- [ ] **Step 6: Commit** with message `feat: one shared task order with manual rank first`.

### Task B2: `/board` command

**Files:**
- Create: `plugins/agentkit/commands/board.md`
- Modify: `cli/gh-agentkit/gh-agentkit` (`setup_board`: create a `Rank` NUMBER field if missing. `cmd_doctor`: warn if missing.)

**Interfaces:**
- Consumes: `board.py order|estimate|render` (B1), at `${CLAUDE_PLUGIN_ROOT}/scripts/board.py`.

- [ ] **Step 1: Write `board.md`** (frontmatter `description`, `argument-hint: [n | move <n> <pos> | unblock <n> | done <n>]`). The instructions:
  - **no argument:** gather open issues, deps (`blocked_by` and `blocking` per open issue), closed issues of the last 60 days with their first `status:in-progress` event, and Rank. Run `estimate` and `render`. Print the result as is.
  - **`<n>`:** `gh issue view <n> --json title,body,labels,comments` plus the linked PR's body. Summarize it under headings.
  - **`move <n> <pos>`:** recompute ranks 1..k so that `<n>` sits at `<pos>`, and write them with `gh project item-edit --number`.
  - **`unblock <n>`:** `gh issue edit <n> --remove-label status:blocked --remove-label action:required --add-label status:refining`.
  - **`done <n>`:** only for `mode:human`: `gh issue close <n> --reason completed`.
- [ ] **Step 2: CLI.** Add the `Rank` field next to `Stage` in `setup_board` (`gh project field-create … --name Rank --data-type NUMBER`, guarded by a field-list check).
- [ ] **Step 3: Verify.** Run `tests/run.sh`. Then, locally in a project with the kit, run `/board` and `/board move <n> 1`, then `/board` again. Expected: `<n>` is first under Up next.
- [ ] **Step 4: Commit** with message `feat: /board shows status, order and estimates, and reorders`.

### Task B3: `/task` command

**Files:**
- Create: `plugins/agentkit/commands/task.md`
- Modify: `plugins/agentkit/skills/implement-issue/SKILL.md` (PR body gets `## Summary` first: 2–3 sentences, what changed and how. Part C's done message uses it.)

- [ ] **Step 1: Write `task.md`** (`argument-hint: <what you want>`). The steps:
  1. Use `agentkit:refine-issue` on the text interactively. Its questions go to the user in chat, and the user's answers are folded in.
  2. Show the plan and verdict.
  3. File with `gh issue create`, using the verdict's labels and `status:ready` (xs/s with no open questions) or `status:refining`.
  4. Add its `blocked_by`.
  5. If the plan needs research, also file a `type:research` issue (`/research` format) and link it as a blocker.
  6. If the size is `m`/`l`, propose the split in chat. On the user's OK, use `agentkit:plan-feature` with the new issue as the epic.
  7. Reply with the URLs.
- [ ] **Step 2: Verify.** Run `tests/run.sh`, then try `/task` locally on a scratch repo with one clear request and one vague one. Expected: the clear one is filed ready, and the vague one gets questions in chat first.
- [ ] **Step 3: Commit** with message `feat: /task refines in chat and files the issue`.

---

# Part C: Slack mode (opt-in)

### Task C0: Spike — does the GitHub Slack app thread what we need? (manual, with the user) — DONE 2026-11-03: yes, with replies through the card's Comment button (see the spec's Spike result)

No code. Use the scratch repo and a test Slack channel.

- [ ] **Step 1:** `/github subscribe <scratch> issues comments +label:"action:required"` (unsubscribe everything else).
- [ ] **Step 2:** Create a `action:required` label. Add it to an open issue from the App token (`gh issue edit`). Then post a comment as the App.
- [ ] **Step 3: Record answers** to these in `docs/superpowers/specs/2026-11-02-claude-code-and-slack-interface-design.md` under a new `## Spike result` section:
  - Does adding the label post a message?
  - Does the App's comment appear in that message's thread?
  - Does a thread reply from a `/github signin`-linked account land as an issue comment by that account?
  - Does a reply starting with a plain word post normally?
- [ ] **Step 4: Decide.** If all four are yes, continue with C1. If any is no, stop and bring it to the user: the fallback is our own Slack app plus a hosted endpoint, which is a new decision.

### Task C1: `action:required` and `needs-approval`

**Files:**
- Modify: `scripts/set-status.sh`
- Modify: `tests/test_set_status.sh`
- Modify: `cli/gh-agentkit/gh-agentkit` (`LABELS`: add `status:needs-approval|0e8a16|Agent proposal waiting for your approve`, `action:required|d93f0b|Waiting on you (Slack pings these)`. `STAGES`: add `Needs approval` after `Needs verification`.)
- Modify: `.github/workflows/dispatch.yml` (Stage map: `status:needs-approval) echo "Needs approval"`)
- Modify: `.github/workflows/digest.yml` (default `statuses` adds `status:needs-approval|Needs your approval`. Drop the `approved` line only when the mode is on: pass `vars.AGENTKIT_INTERFACE` in, and skip `status:approved` if it equals `claude-slack`.)

**Interfaces:**
- Produces: when env `AGENTKIT_INTERFACE=claude-slack`, set-status's single edit also adds `action:required` for a waiting status (see Global Constraints) and removes it otherwise. The env var unset means no change from today. Every workflow that calls set-status gets `AGENTKIT_INTERFACE: ${{ vars.AGENTKIT_INTERFACE }}` in its job `env`.

- [ ] **Step 1: Extend `tests/test_set_status.sh`.** `check` gets an optional 5th argument for `AGENTKIT_INTERFACE`. Cases:
  - `"status:review" status:needs-info` in the mode → `… --remove-label status:review --add-label status:needs-info --add-label action:required`.
  - `"status:needs-info action:required" status:refining` in the mode → `… --remove-label status:needs-info --remove-label action:required --add-label status:refining`.
  - `"mode:human status:refining" status:ready` in the mode → adds `action:required`.
  - The same first case without the mode gives the old output exactly.
- [ ] **Step 2: Run it.** Expected: the new cases FAIL.
- [ ] **Step 3: Implement.** The label query also selects `action:required` and `mode:human`. Compute `want_wait` from the target status. `mode:human` only feeds `want_wait` and is never removed.
- [ ] **Step 4: Add `AGENTKIT_INTERFACE` to the job env** of dispatch, refine, implement, review and plan.
- [ ] **Step 5: Run** `tests/test_set_status.sh && ./actionlint -color && tests/run.sh`. Expected: clean.
- [ ] **Step 6: Commit** with message `feat: action:required label and needs-approval status for Slack mode`.

### Task C2: Reply parser

**Files:**
- Create: `scripts/reply.py`
- Test: `tests/test_reply.py`

**Interfaces:**
- Produces: `reply.py` reads `{"body", "labels": [..], "has_pr": bool}` on stdin and prints `{"action", "arg"}`. Valid actions per status:

  | Status | Keyword → action | Free text → action |
  |---|---|---|
  | `needs-info` | `research` → `research`, `block` → `block` | `answer` |
  | `needs-human` | `retry` → `retry`, `research`, `block` | `guide` |
  | `needs-verification` | `verified` → `verified`, `block` | `failed-check` |
  | `needs-approval` + `type:research` | `approve` → `approve-research`, `block` | `override-research` |
  | `needs-approval` + `type:rfc` | `accept`/`reject` → `decide`, `block` | `hint` |
  | `needs-approval` (split proposal, any other type) | `approve` → `approve-split`, `block` | `split-feedback` |
  | `blocked` | `unblock` → `unblock`, `replace` → `replace` (arg: the number) | `hint` |
  | `ready` + `mode:human` | `done` → `done`, `block` | `hint` |

  Matching: case-insensitive, after `strip()`, on the first word with trailing `.,:!` removed. `arg` is the rest of the text after the keyword (the whole body for free text). A keyword not valid for the status gives `{"action":"hint","arg":"<keyword>"}`.

- [ ] **Step 1: Write `tests/test_reply.py`.** It has one table-driven test over every row above (keyword and free text each), plus:
  - `test_keyword_case_and_punctuation`: `"  Approve."` on research needs-approval gives `approve-research`.
  - `test_keyword_wrong_status`: `"verified"` on `needs-info` gives `hint`.
  - `test_research_arg`: `"research how CoreBluetooth reconnects"` gives arg `"how CoreBluetooth reconnects"`.
  - `test_replace_number`: `"replace #42"` gives arg `"42"`. `"replace soon"` gives `hint`.
- [ ] **Step 2: Run** `python3 tests/test_reply.py`. Expected: FAIL.
- [ ] **Step 3: Implement** with stdlib only, as one dict from `(status, kind)` to the allowed keywords.
- [ ] **Step 4: Run** `python3 tests/test_reply.py && tests/run.sh` (add the test and `py_compile` to `run.sh`). Expected: PASS.
- [ ] **Step 5: Commit** with message `feat: reply.py maps Slack replies to actions`.

### Task C3: Reply workflow

**Files:**
- Create: `.github/workflows/reply.yml`
- Create: `scripts/apply-reply.sh`
- Test: `tests/test_apply_reply.sh`
- Modify: `.github/workflows/review.yml`:
  - the round count starts after the last `<!-- agentkit:rounds-reset -->` comment;
  - in the mode, a passing `type:research`/`type:rfc` PR goes to `status:needs-approval` instead of `approved` and isn't merged (an RFC whose PR has a `/decide` comment passes normally);
  - the needs-approval comment holds the recommendation: the doc's answer section, or the RFC's Recommendation;
  - on a push, the gate's `ok` pattern also accepts `status:needs-approval`, so a pushed research/RFC PR is re-gated.
- Modify: `templates/.github/workflows/agentkit.yml`:
  - new `reply` job: `issue_comment` on an issue (not a PR), commenter not a Bot, `vars.AGENTKIT_INTERFACE == 'claude-slack'`, and the issue has `action:required` or `status:blocked`;
  - the `refine` job's comment trigger gets `&& vars.AGENTKIT_INTERFACE != 'claude-slack'`, because in the mode, reply's `answer` sets `status:refining`, which triggers refine by label.

**Interfaces:**
- Consumes: `reply.py` (C2), `set-status.sh` (C1), `blockers.sh` (A1).
- Produces: `apply-reply.sh <repo> <n> <action> <arg> <login>`. It applies one action:

  | Action | Effect |
  |---|---|
  | `answer` | `set-status refining` |
  | `research` | create a `type:research` issue (title = arg, body has `## Question` + `## Acceptance criteria` + `<!-- agentkit:research-for #n -->`, `status:refining`); link it as a blocker of n; comment `<!-- agentkit:block -->` "waiting on research #r"; `set-status blocked` |
  | `block` | comment `<!-- agentkit:block -->\n**Blocked by @login:** <arg>`; `set-status blocked` |
  | `unblock` | `set-status refining` |
  | `replace` | add arg as a blocker; `set-status ready` |
  | `retry` / `guide` | if there's an agent PR: comment `<!-- agentkit:rounds-reset -->` (plus the guidance for `guide`) on the PR and `set-status changes-requested`; else `set-status in-progress` |
  | `verified` | tick every `- [ ]` under `## Human verification` in the PR body (`gh pr edit --body`); the existing dispatch step approves it |
  | `failed-check` | comment the text on the PR and `set-status changes-requested` |
  | `approve-research` | merge the research PR (`--squash --delete-branch`); for the `research-for` parent: comment `**Research #n recommends:**` + the recommendation and `set-status refining` |
  | `override-research` | close the research PR and the issue as not planned without running the drop handler (comment marker `<!-- agentkit:superseded -->`, which the A3 step skips); post `**Answer from @login:** <text>` on the parent; `set-status refining` on the parent |
  | `decide` | comment `/decide <accept\|reject> <why> (from @login in Slack)` on the RFC PR |
  | `approve-split` | comment `/plan` on the issue |
  | `split-feedback` | `set-status refining` |
  | `done` | `gh issue close --reason completed` |
  | `hint` | comment the valid keywords for this status |

- [ ] **Step 1: Write `tests/test_apply_reply.sh`** with a fake `gh` logging calls (pattern from `test_drop_dependency.sh`). One check per action asserts the key call:
  - `block` → `issue comment` containing `agentkit:block` and `issue edit … status:blocked`;
  - `approve-research` → `pr merge`;
  - `retry` with a PR → comment containing `rounds-reset`;
  - `hint` → no `issue edit`.
- [ ] **Step 2: Run it.** Expected: FAIL.
- [ ] **Step 3: Implement `apply-reply.sh`** as a `case` on action. Find the PR by `gh pr list --search "head:agent/<n>-"`.
- [ ] **Step 4: Write `reply.yml`.** Steps:
  1. App token (issues: write, pull-requests: write, contents: write for the merge). The job `env` sets `AGENTKIT_INTERFACE: ${{ vars.AGENTKIT_INTERFACE }}` like the others (C1).
  2. Load agentkit.
  3. `trusted` on the commenter.
  4. Build the input JSON from the event.
  5. Run `reply.py` and then `apply-reply.sh`.
- [ ] **Step 5: Add the A3 skip.** The drop step skips when the closing issue's last comment has `<!-- agentkit:superseded -->`.
- [ ] **Step 6: Run** `tests/test_apply_reply.sh && ./actionlint -color && tests/run.sh && python3 tests/test_caller.py`. Expected: clean.
- [ ] **Step 7: Commit** with message `feat: Slack replies drive the task (reply workflow)`.

### Task C4: Agents ask through stuck messages and start research themselves

**Files:**
- Modify: `plugins/agentkit/skills/refine-issue/SKILL.md`
- Modify: `plugins/agentkit/skills/implement-issue/SKILL.md`
- Modify: `.github/workflows/refine.yml`
- Modify: `.github/workflows/implement.yml`

**Interfaces:**
- Produces:
  - Refine's `## Questions` items become: `1. **Stuck on:** … **Why:** … **Checked:** <docs/decisions/research searched, with links> — default if unanswered: …`.
  - The VERDICT gains an optional key `"research": ["<question>", …]`. The workflow files each one as in `apply-reply.sh research` (call that script with action `research`) and sets the issue to `status:blocked` instead of the verdict's status.
  - The implementer may end with a last line `STUCK: {"kind":"question"|"research","text":"…","why":"…","checked":"…"}` instead of committing. In "Push and open PR", a STUCK line means:
    - `question`: post the stuck message and `set-status needs-info`;
    - `research`: `apply-reply.sh … research <text> <bot>`.

    Either way it skips the "no commits → needs-human" path. The answer re-runs refine, then ready, and the dispatcher's implement reuses the `agent/<n>-…` branch (existing "Select branch" behavior).

- [ ] **Step 1: Skills.** Add the rule: run `find-knowledge` before any question. If docs settle it, proceed and cite them. Add the `STUCK:` exit to implement-issue step 10/11, used only when the acceptance criteria can't be met without a person's answer or new knowledge.
- [ ] **Step 2: Workflows.** Extend the verdict validation (`research`: array of strings, optional) and the STUCK parsing (`sed -n 's/^STUCK: //p' | tail -1`, then validate with `jq -e '.kind|IN("question","research")'`).
- [ ] **Step 3: Run** `./actionlint -color && tests/run.sh`. Expected: clean.
- [ ] **Step 4: Commit** with message `feat: agents ask with stuck messages and start research when knowledge is missing`.

### Task C5: Auto-refine, split approval, done message

**Files:**
- Modify: `.github/workflows/dispatch.yml`:
  - step "Refine new issues" on `issues opened`: trusted author, mode on, status none or `backlog` → `set-status refining`;
  - "Close issue of merged agent PR": in the mode, post `Task #n done: <title>` + the PR body's `## Summary` + the PR URL to the webhook.
- Modify: `.github/workflows/refine.yml`: in the mode, a verdict of size `m`/`l`:
  - with `AUTO_SPLIT=true`: comment `/plan`;
  - otherwise: `set-status needs-approval` with the proposed split in the comment.
- Modify: `.github/workflows/plan.yml` and `plugins/agentkit/skills/plan-feature/SKILL.md`: the prompt passes `Sub-issue status: status:refining` in the mode and `status:backlog` otherwise. The skill uses that status and drops "Never label anything `status:ready`" in favor of "use the given sub-issue status".
- Modify: `.github/workflows/retro.yml`: in the mode, after posting the Discussion, post one webhook line `Weekly retro: <title> <url>`. It gets a `SLACK_WEBHOOK_URL` optional secret and the caller passes it. The Discussions subscription is dropped in the mode.
- Modify: `templates/.github/workflows/agentkit.yml`: add `opened` to `issues.types`, the dispatch `if` gets `github.event.action == 'opened'`, and the webhook secret goes to dispatch (done in A3) and retro.

- [ ] **Step 1: Implement** the three workflow changes and the skill change.
- [ ] **Step 2: Run** `./actionlint -color && tests/run.sh && python3 tests/test_caller.py`. Expected: clean.
- [ ] **Step 3: Commit** with message `feat: auto-refine, split approval and done message in Slack mode`.

### Task C6: CLI switch, doctor, docs, canary

**Files:**
- Modify: `cli/gh-agentkit/gh-agentkit`:
  - `setup`, `init` and `upgrade` accept `--interface claude-slack`, which sets `AGENTKIT_INTERFACE`, sets `AUTO_MERGE=true`, and prints the Slack lines;
  - `doctor`, when the var is set: FAIL if `AUTO_MERGE != true`, warn if `SLACK_WEBHOOK_URL` is missing, and print a reminder that each person must `/github signin` in Slack.
- Modify: `tests/test_upgrade.sh` (flag parsing for upgrade sets both variables: fake `gh variable set` logging).
- Modify: `README.md`: a "Claude Code + Slack mode" section (the switch, the Slack subscription lines from C0, the reply keywords table, `/board`, `/task`), the lifecycle diagram's `needs-approval`, and the Slack section's subscribe lines for the mode.

- [ ] **Step 1: Write the `test_upgrade.sh` case** (`cmd_upgrade` with `--interface claude-slack` logs `variable set AGENTKIT_INTERFACE` and `variable set AUTO_MERGE`). Run it. Expected: FAIL.
- [ ] **Step 2: Implement** the flag in the three commands (shared helper `set_interface <repo> <value>`) and the doctor checks.
- [ ] **Step 3: Run** `tests/run.sh`. Expected: PASS.
- [ ] **Step 4: README.**
- [ ] **Step 5: Canary (with the user's OK to push).** Run `scripts/canary.sh` on scratch with the mode off (it must pass unchanged), then with the mode on and one walkthrough by hand:
  1. a vague issue gets a stuck ping;
  2. reply `research …` creates a research task, which gets an approve ping;
  3. `approve` resumes the parent;
  4. the parent merges and sends the done message.
- [ ] **Step 6: Commit** with message `feat: gh agentkit --interface claude-slack, doctor checks, docs`.
