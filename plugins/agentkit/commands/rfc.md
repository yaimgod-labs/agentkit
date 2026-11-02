---
description: File a design proposal as a type:rfc issue; an agent writes the RFC, a person decides it with /decide
argument-hint: <problem to design for>
---

First use the `find-knowledge` skill for related docs, decisions and RFCs, and mention them. Then file a GitHub issue:
`gh issue create --label type:rfc --label status:refining --title "RFC: <short problem>" --body "<body>"`.
Body: `## Problem`, `## Constraints` (if any), `## Acceptance criteria` (`- [ ]` lines; at least: the RFC compares two or more options and recommends one). Ask the user only if the problem is unclear. Reply with the issue URL, and say that the RFC PR is decided with a `/decide accept <why>` or `/decide reject <why>` comment.

Problem: $ARGUMENTS
