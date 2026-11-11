# Words agentkit uses with people

One word per thing, in everything a person reads: Slack, Claude Code commands, CLI output, comments the kit posts, settings. Code, workflow comments and maintainer docs may use the internal names. `tests/test_terms.py` fails on the retired ones.

| Thing | Say | Not |
|---|---|---|
| a unit of work | **task** (an **issue** only when pointing at the GitHub page) | card, ticket |
| a Slack message with buttons | **card** | — |
| the reader | **you**; in the third person, **a person** | a human |
| the system | **agentkit** | the kit, the bot (that is the Slack bot only) |
| any Claude job | **the agent** (planning, building, reviewing) | refiner, dispatcher, implementer, planner, gate |
| `.github/workflows/agentkit.yml` in a project | **agentkit.yml** | the caller, the caller workflow |
| one pass of the fix loop | **attempt** (attempt 2 of 3) | round, fix round |
| a dependency | **waits on #12** | held by, blocked by |
| stopped until a person acts | **Blocked** | — |
| large work | **big task**, split into **sub-tasks** | epic, sub-issue |
| something you can change | **setting**: **just for you** or **whole project** | variable, input, pref, knob |
| answering agents from Slack | **Slack mode** (`--interface slack`); with the bot's cards, **Slack bot** | Claude Code + Slack mode, claude-slack |

## Status names

`SAYS` in `plugins/agentkit/scripts/board.py` is the one table; `/board`, the Slack board, the cards and the digest's headings use it. Label names and the board's Stage options are ids and stay as they are.

| Label | A person reads | Their move |
|---|---|---|
| `status:needs-info` | Needs your answer | answer |
| `status:needs-approval` | Needs your approval | `approve` |
| `status:needs-verification` | Needs your check | `verified` |
| `status:needs-human` | Needs you | `retry`, or say what to change |
| `status:blocked` | Blocked | `unblock` |
| `status:approved` | Approved | merge (unless it merges by itself) |
| `status:refining` | Being planned | — |
| `status:ready` | Up next | — |
| `status:in-progress` | Being built | — |
| `status:review`, `status:changes-requested` | In review | — |

## A message that waits on a person

Three parts, in this order: what happened, what it needs, how to answer. The words to answer with come from `scripts/reply.py`'s table. `approve` and `accept` mean the same wherever either is valid.
