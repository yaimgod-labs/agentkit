---
description: Claim the top ready issue and implement it locally in its own worktree
---

1. List candidates: `gh issue list --label status:ready --json number,title,labels --limit 50`. Order by priority label (high, medium, low), then lowest number. Skip `mode:human`, `size:m` and `size:l` (those are split or done by a person first), and any issue with an open blocker (`gh api repos/{owner}/{repo}/issues/<n>/dependencies/blocked_by --jq '[.[]|select(.state=="open")]|length'` > 0).
2. Show the pick and ask the user to confirm.
3. Claim it: `gh issue edit <n> --remove-label status:ready --add-label status:in-progress`.
4. Create a worktree on branch `agent/<n>-<slug>` from the default branch and work there.
5. Use the `implementer` agent. When it finishes, show its summary and ask whether to push and open a PR (`Closes #<n>` in the body).
