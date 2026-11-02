---
title: Record architecture decisions
status: accepted
description: Decisions live in docs/decisions as MADR records
---

# 0001 — Record architecture decisions

## Context

Agents start every run without memory. A decision that is not written down gets re-argued or silently broken.

## Decision

Record every significant decision in `docs/decisions/NNNN-slug.md` (MADR: context, options, decision, consequences).
An accepted record is never edited; a new record supersedes it (`status: superseded`, plus `supersedes: [NNNN]` on the new one).
Rejected options are recorded too (`status: rejected`).

## Consequences

- Reviewers fail a change that contradicts an accepted decision unless the change adds a superseding record.
- `find-knowledge` searches these records first for "why" questions.
