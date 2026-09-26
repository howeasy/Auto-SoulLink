#!/usr/bin/env python3
"""gen3_bw_hashes.py -- writes <lane>/patch/build/bw_hashes_<title>.json, the SLINK_BW_HASHES
input probe_gen3_checkpoint.lua's bw_* rows require (lua/tests/probe_gen3_checkpoint.lua:5-10,
P.bw_meta at :484-495). Closes G4 final-cut runbook §12 item 2: no producer existed in the tree.

Usage: python tools/gen3_bw_hashes.py <firered|leafgreen> [lane]

pack   = sha256 of <lane>/data/games/gen3_frlg/write_checkpoint.json (as checked out)
source = <lane> HEAD sha
states = per bw state file: {"state": sha256(.State), "fixture": sha256(fixture .sav),
         "prep": "<normal-input preparation receipt>"}
  - slink_preintro.State / slink_prebattle.State: patch/build/gen3_probe_states_c4p2/<title>
    against tests/fixtures/gen3/<title>_party_battle.sav (tools/mkstates_gen3.py --kind battle)
  - slink_oldman.State / slink_pokedude.State: patch/build/gen3_probe_states/<title>
    against tests/fixtures/gen3/<title>_party_town.sav (tools/mkstates_gen3_tutorials.py)

Refuses (nothing written) if any input file is missing -- every hash is computed before the
output file is opened, so a refusal never leaves a partial/truncated JSON behind.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

DEFAULT_LANE = "E:/Google Drive/SLink/.claude/worktrees/gen3-lane-clean"

# (state file, patch/build subdir, fixture scene, prep receipt)
_STATE_SPECS = [
    ("slink_preintro.State", "gen3_probe_states_c4p2", "battle",
     "tools/mkstates_gen3.py kind=battle (C4-PROBE2 states, gen3_probe_states_c4p2)"),
    ("slink_prebattle.State", "gen3_probe_states_c4p2", "battle",
     "tools/mkstates_gen3.py kind=battle (C4-PROBE2 states, gen3_probe_states_c4p2)"),
    ("slink_oldman.State", "gen3_probe_states", "town",
     "tools/mkstates_gen3_tutorials.py at lane {source} (gen3_probe_states)"),
    ("slink_pokedude.State", "gen3_probe_states", "town",
     "tools/mkstates_gen3_tutorials.py at lane {source} (gen3_probe_states)"),
]


def _sha256(path):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"missing input for SLINK_BW_HASHES: {path}")
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def build(title, lane=DEFAULT_LANE):
    """Return (out_path, doc). Every hash is computed (and every missing file raises
    FileNotFoundError) before anything is written."""
    sha = subprocess.check_output(["git", "-C", lane, "rev-parse", "HEAD"], text=True).strip()
    states = {}
    for name, subdir, scene, prep in _STATE_SPECS:
        state_path = f"{lane}/patch/build/{subdir}/{title}/{name}"
        fixture_path = f"{lane}/tests/fixtures/gen3/{title}_party_{scene}.sav"
        states[name] = {"state": _sha256(state_path), "fixture": _sha256(fixture_path), "prep": prep.format(source=sha[:8])}
    doc = {"pack": _sha256(f"{lane}/data/games/gen3_frlg/write_checkpoint.json"),
           "source": sha, "states": states}
    return f"{lane}/patch/build/bw_hashes_{title}.json", doc


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("title", choices=["firered", "leafgreen"])
    ap.add_argument("lane", nargs="?", default=DEFAULT_LANE)
    args = ap.parse_args()
    out, doc = build(args.title, args.lane)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
