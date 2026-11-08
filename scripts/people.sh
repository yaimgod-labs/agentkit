#!/usr/bin/env bash
# Usage: people.sh <owner/repo> <issue-or-pr> <bot-login>
# Prints, as one JSON array oldest first, [{id, body}] for the comments on the issue (or PR) by people with write
# access (write, maintain or admin): never a bot's (type Bot, or the kit's own <bot-login>). This is how the kit tells
# a person's say from text an agent posted with the kit's token. The one exception is a Slack reply record
# (slackrec.py): a kit comment with a valid signature counts as its login's, with the text as the body, when env
# AGENTKIT_APP_KEY is set (the steps that decide on a person's say pass it) and that login has write access.
# A failed comment read exits non-zero (fail closed); a failed permission read counts as no access.
set -euo pipefail
repo=$1 n=$2 me=$3
here=$(cd "$(dirname "$0")" && pwd)
# captured first, so a failed read stops the script
all=$(gh api --paginate "repos/$repo/issues/$n/comments" --jq '.[] | {id, login: .user.login, type: .user.type, body}')
comments=$(ME=$me jq -c 'select(.type != "Bot" and .login != env.ME) | {id, login, body}' <<<"$all")
if [ -n "${AGENTKIT_APP_KEY:-}" ]; then
  while read -r rec; do
    [ -n "$rec" ] || continue
    v=$(jq -j .body <<<"$rec" | python3 "$here/slackrec.py" verify "$repo" "$n") || continue
    comments+=$'\n'$(jq -c --argjson v "$v" '{id, login: $v.login, body: $v.text}' <<<"$rec")
  done < <(ME=$me jq -c 'select(.login == env.ME and (.body | startswith("<!-- agentkit:slack-reply ")))' <<<"$all")
fi
allowed=()
while read -r login; do
  [ -n "$login" ] || continue
  perm=$(gh api "repos/$repo/collaborators/$login/permission" --jq .permission 2>/dev/null </dev/null || echo none)
  case $perm in admin | maintain | write) allowed+=("$login") ;; esac
done < <(jq -r .login <<<"$comments" | sort -u)
# oldest first: comment ids only grow
jq -sc --args '[.[] | select(.login | IN($ARGS.positional[])) | {id, body}] | sort_by(.id)' ${allowed[@]+"${allowed[@]}"} <<<"$comments"
