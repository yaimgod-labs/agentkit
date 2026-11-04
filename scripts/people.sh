#!/usr/bin/env bash
# Usage: people.sh <owner/repo> <issue-or-pr> <bot-login>
# Prints, as one JSON array oldest first, [{id, body}] for the comments on the issue (or PR) by people with write
# access (write, maintain or admin): never a bot's (type Bot, or the kit's own <bot-login>). This is how the kit tells
# a person's say from text an agent posted with the kit's token. A failed comment read exits non-zero (fail closed);
# a failed permission read counts as no access.
set -euo pipefail
repo=$1 n=$2 me=$3
# captured first, so a failed read stops the script
comments=$(ME=$me gh api --paginate "repos/$repo/issues/$n/comments" \
  --jq '.[] | select(.user.type != "Bot" and .user.login != env.ME) | {id, login: .user.login, body}')
allowed=()
while read -r login; do
  [ -n "$login" ] || continue
  perm=$(gh api "repos/$repo/collaborators/$login/permission" --jq .permission 2>/dev/null </dev/null || echo none)
  case $perm in admin | maintain | write) allowed+=("$login") ;; esac
done < <(jq -r .login <<<"$comments" | sort -u)
jq -sc --args '[.[] | select(.login | IN($ARGS.positional[])) | {id, body}]' ${allowed[@]+"${allowed[@]}"} <<<"$comments"
