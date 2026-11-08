#!/usr/bin/env python3
"""The signed record of a Slack reply (slack-bot interface). Python 3.9+, stdlib only.

An agent can comment as the kit's bot, so a bot comment alone never counts as a person's say. The reply workflow
writes a record the gate and people.sh accept as that person's, signed with a key only kit steps that hold the App key
secret can make: HMAC-SHA256 under sha256(env AGENTKIT_APP_KEY), over the repo, issue, login, a nonce and the text.

  slackrec.py sign <owner/repo> <issue> <login> < text      prints the comment body to post
  slackrec.py verify <owner/repo> <issue> < comment-body    prints {"login", "text"}; exit 1 when it is not a valid record

Body: `<!-- agentkit:slack-reply login=<l> nonce=<hex> sig=<hex> -->`, a blank line, `**Slack reply by @<l>:**`, a
blank line, then the text (CR removed, as GitHub may store it). The signature covers all of that text.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import sys

HEAD = re.compile(r"\A<!-- agentkit:slack-reply login=([A-Za-z0-9][A-Za-z0-9-]*) nonce=([0-9a-f]{32}) sig=([0-9a-f]{64}) -->\n\n"
                  r"\*\*Slack reply by @\1:\*\*\n\n(.*)\Z", re.S)


def mac(repo, n, login, nonce, text):
    key = hashlib.sha256(os.environ["AGENTKIT_APP_KEY"].encode()).digest()
    msg = "\0".join(["slack-reply", repo, str(n), login, nonce, text]).encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def sign(repo, n, login, text):
    text = text.replace("\r", "")
    nonce = secrets.token_hex(16)
    return (f"<!-- agentkit:slack-reply login={login} nonce={nonce} sig={mac(repo, n, login, nonce, text)} -->\n\n"
            f"**Slack reply by @{login}:**\n\n{text}")


def verify(repo, n, body):
    m = HEAD.match(body.replace("\r", ""))
    if not m or not os.environ.get("AGENTKIT_APP_KEY"):
        return None
    login, nonce, sig, text = m.groups()
    return {"login": login, "text": text} if hmac.compare_digest(sig, mac(repo, n, login, nonce, text)) else None


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 4 and a[0] == "sign":
        print(sign(a[1], a[2], a[3], sys.stdin.read()), end="")
    elif len(a) == 3 and a[0] == "verify":
        r = verify(a[1], a[2], sys.stdin.read())
        if r is None:
            sys.exit(1)
        print(json.dumps(r))
    else:
        sys.exit(__doc__)
