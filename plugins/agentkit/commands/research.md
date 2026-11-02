---
description: File a research question as a type:research issue for the refiner
argument-hint: <question>
---

File this as a GitHub issue: `gh issue create --label type:research --label status:refining --title "<short question>" --body "<body>"`.
Body: `## Question` (the question and the decision it feeds) and `## Acceptance criteria` (what the answer must cover, as `- [ ]` lines). Ask the user only if the question is unclear. Reply with the issue URL.

Question: $ARGUMENTS
