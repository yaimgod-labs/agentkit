"""scripts/reply.py: maps a person's Slack reply (an issue comment) to the action a workflow applies."""
import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts/reply.py"
fails = 0


def run_raw(raw):
    return subprocess.run([sys.executable, str(SCRIPT)], input=raw.encode(), capture_output=True)


def reply(body, *labels, has_pr=False):
    r = run_raw(json.dumps({"body": body, "labels": list(labels), "has_pr": has_pr}))
    assert r.returncode == 0, r.stderr.decode()
    return json.loads(r.stdout.decode("utf-8"))


def expect(name, cond, detail=""):
    global fails
    print(("ok: " if cond else "FAIL: ") + name + ("" if cond else f"\n{detail}"))
    fails += not cond


def act(body, *labels):
    out = reply(body, *labels)
    return out["action"], out["arg"]


# test_table: every row of the status table, keyword and free text
NI, NH, NV = ["status:needs-info"], ["status:needs-human"], ["status:needs-verification"]
NA_R, NA_F = ["status:needs-approval", "type:research"], ["status:needs-approval", "type:rfc"]
NA_S, BL, RH = ["status:needs-approval", "type:feature"], ["status:blocked"], ["status:ready", "mode:human"]
table = [
    (NI, "research why it drops", ("research", "why it drops")),
    (NI, "block waiting on legal", ("block", "waiting on legal")),
    (NI, "it is the second one", ("answer", "it is the second one")),
    (NI, "close not needed any more", ("close", "not needed any more")),
    (NH, "retry", ("retry", "")),
    (NH, "research how X works", ("research", "how X works")),
    (NH, "block no access", ("block", "no access")),
    (NH, "try the other branch", ("guide", "try the other branch")),
    (NH, "Close: already done in #12", ("close", "already done in #12")),
    (NV, "verified", ("verified", "")),
    (NV, "block broke on ios 17", ("block", "broke on ios 17")),
    (NV, "the button is still grey", ("failed-check", "the button is still grey")),
    (NA_R, "approve", ("approve-research", "")),
    (NA_R, "block too risky", ("block", "too risky")),
    (NA_R, "do option b instead", ("override-research", "do option b instead")),
    (NA_F, "accept fits our budget", ("decide", "accept fits our budget")),
    (NA_F, "reject too slow", ("decide", "reject too slow")),
    (NA_F, "block needs review", ("block", "needs review")),
    (NA_F, "what about option c", ("hint", "what about option c")),
    (NA_S, "approve", ("approve-split", "")),
    (NA_S, "block unclear scope", ("block", "unclear scope")),
    (NA_S, "merge the last two", ("split-feedback", "merge the last two")),
    (BL, "unblock", ("unblock", "")),
    (BL, "replace #42", ("replace", "42")),
    (BL, "ask again tomorrow", ("hint", "ask again tomorrow")),
    (RH, "done", ("done", "")),
    (RH, "block lost the device", ("block", "lost the device")),
    (RH, "starting tonight", ("hint", "starting tonight")),
]
for labels, body, want in table:
    got = act(body, *labels)
    expect(f"table: {labels[0][7:]} {labels[1:]} {body!r}", got == want, got)

# test_keyword_case_and_punctuation
expect("keyword case and punctuation", act("  Approve.", *NA_R) == ("approve-research", ""), act("  Approve.", *NA_R))
for punct in ".,:!":
    expect(f"trailing {punct!r} is stripped", act(f"VERIFIED{punct}", *NV) == ("verified", ""))

# test_keyword_wrong_status
expect("keyword wrong status", act("verified", *NI) == ("hint", "verified"), act("verified", *NI))
for labels in (NV, NA_R, NA_F, NA_S, BL, RH):
    expect(f"close is only for needs-info and needs-human: {labels}", act("close why", *labels) == ("hint", "close"), act("close why", *labels))
expect("block is not valid on blocked", act("block why", *BL) == ("hint", "block"))
expect("approve on rfc is a hint", act("approve", *NA_F) == ("hint", "approve"))

# test_research_arg
expect("research arg", act("research how CoreBluetooth reconnects", *NI) == ("research", "how CoreBluetooth reconnects"))

# test_replace_number
expect("replace #N", act("replace #42", *BL) == ("replace", "42"))
expect("replace N", act("replace 42", *BL) == ("replace", "42"))
expect("replace soon is a hint", act("replace soon", *BL) == ("hint", "replace"), act("replace soon", *BL))
expect("replace #42 and more is a hint", act("replace #42 and #43", *BL) == ("hint", "replace"))

# keywords that need an argument and have none
for labels, kw in [(NI, "research"), (NH, "block"), (NA_F, "reject"), (BL, "replace"), (NI, "close"), (NH, "close")]:
    expect(f"{kw} without an argument", act(kw, *labels) == ("hint", kw), act(kw, *labels))

# decide: lowercase keyword plus its why
expect("accept alone", act("accept", *NA_F) == ("decide", "accept"), act("accept", *NA_F))
expect("decide arg", act("Accept. fits our budget", *NA_F) == ("decide", "accept fits our budget"), act("Accept. fits our budget", *NA_F))

# keywords without an argument keep the rest as arg
expect("no-arg keyword keeps rest", act("approve thanks", *NA_R) == ("approve-research", "thanks"))

# empty body
expect("empty body", act("", *NI) == ("hint", ""))
expect("blank body", act("  \n ", *NA_S) == ("hint", ""))

# statuses outside the table
for labels in (["status:in-progress"], ["status:review"], ["status:ready"], ["type:bug"], []):
    expect(f"no action for {labels}", act("approve", *labels) == ("none", ""), act("approve", *labels))

# has_pr is accepted and changes nothing
expect("has_pr ignored", reply("verified", *NV, has_pr=True) == reply("verified", *NV, has_pr=False))
expect("has_pr may be absent", json.loads(run_raw(json.dumps({"body": "done", "labels": RH})).stdout) == {"action": "done", "arg": "", "keywords": ["done", "block"], "free_text": False})

# parsing details
expect("newline after the keyword", act("block\nwaiting on legal", *NI) == ("block", "waiting on legal"), act("block\nwaiting on legal", *NI))
expect("approve!!", act("approve!!", *NA_R) == ("approve-research", ""))
expect("keyword mid-sentence is free text", act("I think we should block this", *NI) == ("answer", "I think we should block this"))
for body in ("replace #0", "replace 007", "replace #\u0664\u0662"):
    expect(f"replace {body!r} is a hint", act(body, *BL) == ("hint", "replace"), act(body, *BL))

# no state change is safe when the labels are ambiguous
expect("two status labels", act("verified", "status:needs-verification", "status:needs-info") == ("none", ""))
expect("research and rfc together", act("approve", "status:needs-approval", "type:research", "type:rfc") == ("none", ""))
expect("research and rfc, free text", act("do b", "status:needs-approval", "type:rfc", "type:research") == ("none", ""))

# invalid input exits 2 with a message and no stdout
for raw in ('[]', '"x"', '{"body": 123, "labels": []}', '{"body": "a", "labels": [1]}', '{"body": "a", "labels": [null]}',
            '{"body": "a", "labels": "status:ready"}', '{"body": "a", "labels": [], "has_pr": "yes"}'):
    r = run_raw(raw)
    expect(f"bad input {raw} exits 2", r.returncode == 2 and r.stderr and not r.stdout, (r.returncode, r.stderr, r.stdout))
expect("null body is empty", json.loads(run_raw('{"body": null, "labels": ["status:needs-info"]}').stdout) == {"action": "hint", "arg": "", "keywords": ["research", "block", "close"], "free_text": True})

# keywords: the keywords valid for the status, in table order, whatever the reply was; none has none
for labels, want in [(NI, ["research", "block", "close"]), (NH, ["retry", "research", "block", "close"]), (NV, ["verified", "block"]),
                     (NA_R, ["approve", "block"]), (NA_F, ["accept", "reject", "block"]), (NA_S, ["approve", "block"]),
                     (BL, ["unblock", "replace"]), (RH, ["done", "block"])]:
    for body in ("free text here", "verified", ""):
        got = reply(body, *labels)["keywords"]
        expect(f"keywords for {labels} on {body!r}", got == want, got)
for labels in (["status:in-progress"], ["status:ready"], []):
    expect(f"no keywords for {labels}", reply("approve", *labels)["keywords"] == [])

# free_text: whether free text is a real action for the status (not a hint), whatever the reply was
for labels, want in [(NI, True), (NH, True), (NV, True), (NA_R, True), (NA_F, False), (NA_S, True), (BL, False), (RH, False)]:
    for body in ("free text here", "verified", ""):
        got = reply(body, *labels)["free_text"]
        expect(f"free_text for {labels} on {body!r}", got is want, got)
for labels in (["status:in-progress"], ["status:ready"], []):
    expect(f"no free text for {labels}", reply("approve", *labels)["free_text"] is False)

# invalid JSON
r = run_raw("not json")
expect("invalid JSON exits 2 with a message", r.returncode == 2 and r.stderr and not r.stdout, (r.returncode, r.stderr))

sys.exit(1 if fails else 0)
