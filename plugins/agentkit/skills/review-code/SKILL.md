---
name: review-code
description: Review a pull request for correctness against its linked issue's acceptance criteria and the repo's CLAUDE.md rules, and return a pass/fail verdict. Use when asked to review a PR or diff, and in the agentkit review workflow.
---

# Code review

1. Get the inputs. In CI they are files: `.agentkit-review/pr.md`, `.agentkit-review/issue.md`, `.agentkit-review/diff.patch`. Locally: `git diff origin/<base>...HEAD`, and the linked issue (`Closes #n` in the PR body) via `gh issue view <n>`. If you cannot read the issue's acceptance criteria, the verdict is `fail` — never pass a change you could not check against its criteria.
2. Check, in this order:
   - each acceptance criterion is actually met by the diff, with a test where a test is possible;
   - correctness bugs: wrong logic, unhandled errors on real paths, races, broken edge cases;
   - violations of explicit rules in `CLAUDE.md`;
   - contradictions with an accepted record in `docs/decisions/` (unless the PR adds a superseding record);
   - docs the diff makes wrong: a doc whose behaviour changed but whose text did not, or a `docs reviewed` reason that is false;
   - scope: changes unrelated to the issue;
   - for a `type:rfc` issue (see the issue's labels): the RFC has at least two real options with for and against, a recommendation that follows from them, consequences, and rejected options with reasons; it stays `status: proposed` unless the PR has a `/decide` comment (in `pr.md` under `Decision comment`), and then its status, and the decision record linking it, match that comment, contains no implementation, and does not contradict an accepted decision without proposing to supersede it.
3. Leave an inline comment on the exact line for each finding (in CI use the inline comment tool). One finding per comment: problem, then fix.
4. Verdict:
   - `fail` if any acceptance criterion is unmet, or there is a correctness bug, a CLAUDE.md rule violation, a contradicted decision, a doc the change made wrong, or an RFC missing what step 2 asks of it.
   - `pass` otherwise. Style nits and suggestions never fail a review.
5. Return the verdict and a short summary listing the blocking findings.
