#!/usr/bin/env python3
"""Stands in for `claude -p` in the tests: answers from file names instead of looking at pictures,
and logs every call (arguments + working folder) so the tests can check how Claude is run.
Never contacts anything. Env: SNAPSIFT_HOME (to read the inventory), FAKE_CLAUDE_LOG, FAKE_CLAUDE_FAIL_ONCE."""
import json, os, re, sys

argv = sys.argv[1:]
prompt = argv[argv.index("-p") + 1] if "-p" in argv else ""
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"argv": argv, "cwd": os.getcwd()}) + "\n")

flag = os.environ.get("FAKE_CLAUDE_FAIL_ONCE")
if flag and not os.path.exists(flag):  # first call answers early, like a busy Claude
    open(flag, "w").close()
    print(json.dumps({"result": "I'm busy right now, try again later."}))
    sys.exit(0)

home = os.environ["SNAPSIFT_HOME"]
inv = {r["id"]: r for r in json.load(open(os.path.join(home, "dashboard", "data", "inventory.json")))}


def reply(obj):
    print(json.dumps({"result": "Here you go:\n```json\n" + json.dumps(obj) + "\n```", "total_cost_usd": 0.001}))
    sys.exit(0)


if "album name" in prompt:  # events.py --name: try to escape the Albums folder
    ids = re.findall(r"^(e\d+):", prompt, re.M)
    reply({i: ("../../Escaped/Trip" if n == 0 else f"Nice day {n}") for n, i in enumerate(ids)})

if "highlights slideshow" in prompt:
    reply({"pick": [i for i, r in inv.items() if r["kind"] == "photo"][::-1]})

keys = dict(re.findall(r"^- ([a-z0-9-]+) \((photo|video)\):", prompt, re.M))
second = "hard to place" in prompt
out = {}
for i in re.findall(r"^(\d+): ", prompt, re.M):
    r = inv[int(i)]
    n = r["name"].lower()
    kind = r["kind"]
    pick = next(k for k, v in keys.items() if v == kind)
    flags = ""
    for word, key in (("food", "food"), ("selfie", "selfies"), ("beach", "travel"), ("party", "people"),
                      ("screenshot", "screenshots"), ("passport", "docs"), ("burst", "pets")):
        if word in n and key in keys:
            pick = key
    if "passport" in n:
        flags = "s"
    if "mystery" in n and not second:
        flags = "u"
    if kind == "video":
        pick = next(k for k, v in keys.items() if v == "video")
    out[i] = [pick, f"test caption for {n[:20]}", flags]
reply(out)
