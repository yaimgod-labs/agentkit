"""slackrec.py: a signed Slack reply record verifies only for its own repo, issue and text, under its own key."""
import os, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
os.environ["AGENTKIT_APP_KEY"] = "k1"
import slackrec

fails = 0
def expect(name, cond):
    global fails
    print(("ok: " if cond else "FAIL: ") + name); fails += not cond

body = slackrec.sign("o/r", 7, "alice", "accept: <!-- x -->\r\nline 2")
expect("round trip, CR removed, text kept", slackrec.verify("o/r", 7, body) == {"login": "alice", "text": "accept: <!-- x -->\nline 2"})
expect("other issue refused", slackrec.verify("o/r", 8, body) is None)
expect("other repo refused", slackrec.verify("p/r", 7, body) is None)
expect("changed text refused", slackrec.verify("o/r", 7, body + "!") is None)
expect("changed login refused", slackrec.verify("o/r", 7, body.replace("login=alice", "login=bob").replace("@alice", "@bob")) is None)
expect("a record is not replayable as another record's nonce", slackrec.sign("o/r", 7, "alice", "a") != slackrec.sign("o/r", 7, "alice", "a"))
os.environ["AGENTKIT_APP_KEY"] = "k2"
expect("other key refused", slackrec.verify("o/r", 7, body) is None)
del os.environ["AGENTKIT_APP_KEY"]
expect("no key: nothing verifies", slackrec.verify("o/r", 7, body) is None)
sys.exit(1 if fails else 0)
