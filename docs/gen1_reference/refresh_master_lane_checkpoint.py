"""Refresh the master-release-lane entry in the sole checkpoint + the worktree register.

Usage: python refresh_checkpoint.py <state> <files-json> <next_action> <live_lane> <head> <register-note>
The JSON block between the AGENT_CHECKPOINT markers is parsed, the entry replaced, and the
block re-serialised with 2-space indent (the file's own style). Nothing else in the guide moves.
"""
import datetime
import json
import re
import sys

GUIDE = r"E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2/docs/gen1_reference/RC_MASTER_GUIDE.md"
REGISTER = r"E:/Google Drive/SLink/.claude/worktrees/gen1-rby-code-sweep-8d06e2/docs/gen1_reference/WORKTREE_REGISTER.md"
START, END = "<!-- AGENT_CHECKPOINT_START -->", "<!-- AGENT_CHECKPOINT_END -->"

state, files, next_action, live_lane, head, register_note = sys.argv[1:7]
files = json.loads(files)

text = open(GUIDE, encoding="utf-8").read()
a, b = text.index(START) + len(START), text.index(END)
block = text[a:b]
m = re.search(r"```json\n(.*?)\n```", block, re.S)
cp = json.loads(m.group(1))
now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
cp["updated_at_utc"] = now
cp["live_lane"] = live_lane or None
entry = next(w for w in cp["workers"] if w["id"] == "master-release-lane")
entry["owner"] = ("Claude Fable 5.1 coordinator (session e136b7e5) in worktree gen1-master-release-plan-6b4279 "
                  "(branch claude/gen1-master-release-plan-6b4279); owner-approved plan v3.9 2026-09-17")
entry["state"] = state
entry["files"] = files
entry["next_action"] = next_action
entry["reuse_decision"] = ("shared infra (state.py/server.py/connector/hud/adapters/base.py) reused unchanged; "
                           "Gen 1 facts regenerated from pret; RC runtime not adopted; harness mechanisms "
                           "(post-result oracle registry, fail-closed runner) recorded for docs/shared_runtime.md")
entry["source_head"] = head
entry["independent_review"] = ("OMP Gen1 Peer 2 reviews every coordinator Lua/client diff before a lane run; "
                               "subagent cuts are coordinator-reviewed and OMP adversarial-reviewed before the tag; "
                               "no worker reviews its own cut")
new_block = block[:m.start(1)] + json.dumps(cp, indent=2, ensure_ascii=False) + block[m.end(1):]
open(GUIDE, "w", encoding="utf-8", newline="\n").write(text[:a] + new_block + text[b:])

reg = open(REGISTER, encoding="utf-8").read()
pat = re.compile(r"(\*\*Master release lane \(2026-09-14 UTC\)\.\*\*.*?)(\n\n## Preserved)", re.S)
mm = pat.search(reg)
assert mm, "register paragraph not found"
para = mm.group(1)
para = re.sub(r"\(HEAD [^)]*\)", f"(HEAD {head}; {register_note})", para, count=1)
para = para.replace("rebased onto master `e2fefa9`", "rebased onto master `d2c30fb` (2026-09-17)")
reg = reg[:mm.start(1)] + para + reg[mm.end(1):]
open(REGISTER, "w", encoding="utf-8", newline="\n").write(reg)
print("checkpoint", now, "head", head, "state", state)
