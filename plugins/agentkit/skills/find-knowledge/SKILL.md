---
name: find-knowledge
description: Answer "what did we decide / how does X work / where is Y / why is it like this" from the project's own written knowledge — docs/, decision records, issues, PRs and Discussions — with links. Use before designing or changing something non-trivial, and whenever asked about past decisions or project knowledge.
---

# Find knowledge

Search in this order and stop when the question is answered. Cite every claim with a link or `path:line`.

1. **Docs index:** read `docs/README.md` (generated list of every doc with status and summary). Open the matching docs.
2. **Decisions first for "why" questions:** `docs/decisions/` (accepted records win; check `superseded` ones only for history), then `docs/rfcs/` for designs proposed or rejected and `docs/research/` for questions already answered.
3. **Full text:** `rg -n -i "<terms>" docs/` then, if needed, the code: `rg -n "<identifier>"`.
4. **Code index (local only):** if repowise MCP tools are available, use `get_answer` / `search_codebase` / `get_why`.
5. **Work history:** `gh search issues "<terms>" --repo <owner/repo> --state all`, `gh search prs "<terms>" --repo <owner/repo>`,
   and Discussions: `gh api graphql -f query='query($q:String!){search(query:$q,type:DISCUSSION,first:10){nodes{...on Discussion{title url}}}}' -f q="repo:<owner/repo> <terms>"`.

Answer shape:
- the answer in 1–3 sentences;
- sources as links;
- conflicts or gaps you found (a doc that contradicts the code, a decision with no record). When a doc is wrong or missing, say so; do not guess.
