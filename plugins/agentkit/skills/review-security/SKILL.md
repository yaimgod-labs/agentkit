---
name: review-security
description: Security review of a pull request diff — injection, authn/authz, secrets, unsafe deserialization, SSRF, path traversal, crypto misuse, dependency risk — returning a pass/fail verdict. Use when asked for a security review, and in the agentkit review workflow.
---

# Security review

1. Get the diff: `.agentkit-review/diff.patch` in CI, otherwise `git diff origin/<base>...HEAD`. Read surrounding code where a finding depends on context (callers, validation upstream).
2. Look for vulnerabilities the diff introduces or exposes:
   - injection (SQL, shell, template, log), XSS, SSRF, path traversal;
   - missing or weakened authentication or authorization checks, IDOR;
   - secrets, real hostnames, keys or tokens committed; secrets written to logs;
   - unsafe deserialization, crypto misuse, weak randomness for security values;
   - new dependencies that are unmaintained, typosquats, or pulled from untrusted sources;
   - CI changes that widen permissions, run untrusted input, or expose secrets;
   - anything the repo's `CLAUDE.md` names as a security rule;
   - an RFC (`docs/rfcs/`) whose design touches auth, data, secrets or the network but has no threat model, or whose recommended option has a concrete exploit path it does not address.
3. Report only findings with a concrete exploit path. No theoretical hardening advice, no style.
4. Leave an inline comment per finding: severity (high, medium, low), exploit path, fix.
5. Fix round (CI gives `.agentkit-review/previous.md`, the findings that sent earlier rounds back, and usually `.agentkit-review/since-last-round.patch`, what changed since; without it, treat all code as changed): check each earlier high or medium finding first; one not fixed still fails. Code outside `since-last-round.patch` was judged last round: a new finding there fails the review only if it is high, otherwise comment it as `(not blocking: judged last round)`.
6. Verdict: `fail` for any high or medium finding (within step 5's limits), `pass` otherwise.
