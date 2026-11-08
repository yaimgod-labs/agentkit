---
description: Ask "can I change X?" and get the kit's options for it, from the settings registry
argument-hint: [question | setting key]
---

The only source is the kit's registry, `config/settings.json`. Never invent a setting, a variable, an input or an option that is not in it, and never change a value that `settings.py validate` refuses.

## Load the registry

One Bash call:

```
REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
CALLER="$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.github/workflows/agentkit.yml"
T=$(mktemp -d); mkdir -p "$T/config" "$T/scripts"
KIT="${CLAUDE_PLUGIN_ROOT}/../.."
if [ -f "$KIT/config/settings.json" ] && [ -f "$KIT/scripts/settings.py" ]; then
  cp "$KIT/config/settings.json" "$T/config/"; cp "$KIT/scripts/settings.py" "$T/scripts/"
else
  # the kit repo and ref the project's caller pins
  USES=$(grep -oE 'uses: *[^ ]+/\.github/workflows/dispatch\.yml@[^ ]+' "$CALLER" | head -1 | sed -E 's#uses: *##')
  KITREPO=${USES%%/.github/*}; REF=${USES##*@}
  for f in config/settings.json scripts/settings.py; do
    gh api "repos/$KITREPO/contents/$f?ref=$REF" -H "Accept: application/vnd.github.raw" >"$T/$f"
  done
fi
S="$T/scripts/settings.py"
```

If that fails (no caller file, no access to the kit repo), say the registry could not be loaded and why, and stop. Later Bash calls reuse the same `$T`.

## No argument

Print the output of `python3 "$S" show` as it is.

## A question or a key

1. `python3 "$S" show` (or `show <word>` to narrow it) and pick the entries that answer the question, by key, title and description. A question about a person's own nudges or hours matches `user` entries. Leave out `advanced` entries unless the question names one or asks for them.
2. No entry matches: say plainly that this is not configurable in the kit. Offer to file it as a feature request in the kit repo's backlog (`gh issue create --repo "$KITREPO"`, or the kit repo named in the caller's `uses:`); file it only if the user says yes.
3. Otherwise answer in a few lines per entry: the title, what it does (its description), the current value, and the choices: its `options`, plus "or another value" when `other` is true. Current value, by `apply.via`:
   - `variable`: `gh variable get <apply.name> --repo "$REPO"`; unset means the `default`.
   - `caller`: the job's `with:` input (`apply.input`) in `$CALLER`, or for a cron entry the matching line under `schedule:`; absent or commented out means the `default`.
   - `prefs`: each person's own value, kept by the Slack bot; you cannot read it from here.
   - `server`: set in the Slack bot's environment on its server; you cannot read it from here.
4. When the user picks a value, check it first: `python3 "$S" validate <key> '<value>'`. Exit 1 prints the reason: tell them and stop. Then apply by `apply.via`, and say how to undo it (the same step with the old value):
   - `variable`: do not run it. Print the exact command for the user, who needs admin permission on the repo: `gh variable set <apply.name> --repo <REPO> --body '<value>'` (`true`/`false` for a bool).
   - `caller`: propose the exact edit to `.github/workflows/agentkit.yml`: the `<apply.input>: <value>` line under the `with:` of each job in `apply.job` (add `with:` if the job has none; uncomment a commented example instead of adding a second line). For a cron entry: the line under `schedule:` and, for the digest and retro jobs, the same string in that job's `if: github.event.schedule == '…'`. Make the edit on a new branch and open a PR only when the user says yes; merging stays theirs.
   - `prefs`: a person's own setting is changed in the Slack bot (a DM or App Home → Settings), not from here. Say so.
   - `server`: tell them to set `<apply.name>` in the bot's container environment on its server and restart the bot (`docs/slack-bot.md` in the kit).
