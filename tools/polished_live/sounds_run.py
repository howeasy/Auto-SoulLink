#!/usr/bin/env python3
"""Run the POL-SOUNDS live proof on the COMMITTED Polished overlay (card POL-SOUNDS round 2).

    python tools/polished_live/sounds_run.py

Nothing is rebuilt. The staged ROM is the pinned release ROM with the committed
patch/dist/SLink-Polished.ups applied, and it is refused unless its sha1 equals
data/polished/overlay_provenance.json's `output.sha1` (harness.stage_rom's own gate).

The driver is tools/polished_live/sounds.lua: a SCRIPTED MAILBOX WRITER. It presses only
wSlinkMailbox + SLINK_OFS_SFX_REQUEST and reads the audio engine; it is not the SLink client,
whose sound path belongs to the integration worker.

Everything runs under F:/slink-work/lanes/pol-sounds2 (short, non-Drive). Only the EmuHawk PID
this script starts is ever killed (harness.kill_own); never an image-name kill.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO))

os.environ.setdefault("POL_LANE", "F:/slink-work/lanes/pol-sounds2")
os.environ.setdefault("POL_FIXTURE", "F:/slink-work/lanes/pol-live/fixture/polished_overlay_warp.SaveRAM")

import harness  # noqa: E402  (tools/polished_live/harness.py)
from patch.tools.make_ups import ups_apply  # noqa: E402

LANE = harness.LANE
PROV = json.loads((REPO / "data/polished/overlay_provenance.json").read_text(encoding="utf-8"))
RELEASE = Path("F:/slink-work/cache/polished/release/polishedcrystal-3.2.3.gbc")
UPS = REPO / "patch/dist/SLink-Polished.ups"
STAGED = LANE / "rom" / "pol_sounds.gbc"
# the sound driver reads three audio WRAM words the client harness does not
EXTRA = ("wCurSFX", "wChannel5Flags", "wMusicFade")


def stage() -> str:
    """release + committed UPS -> lane/rom/pol_sounds.gbc, refused unless the sha1 is the pin."""
    clean = RELEASE.read_bytes()
    if hashlib.sha1(clean).hexdigest() != PROV["base_sha1"]:
        raise SystemExit("cached release ROM is not the pinned base")
    data = ups_apply(clean, UPS.read_bytes())
    sha1 = hashlib.sha1(data).hexdigest()
    if sha1 != PROV["output"]["sha1"]:
        raise SystemExit(f"staged overlay sha1 {sha1} != provenance {PROV['output']['sha1']}")
    STAGED.parent.mkdir(parents=True, exist_ok=True)
    STAGED.write_bytes(data)
    return sha1


def main() -> int:
    sha1 = stage()
    print(f"[pol-sounds] staged {STAGED} sha1 {sha1}", flush=True)
    harness.ROM_SRC = STAGED                 # the committed UPS, not a build tree
    harness.ROM = STAGED                    # harness.ROM is what EmuHawk is handed
    harness.SYMBOLS = tuple(harness.SYMBOLS) + EXTRA
    harness.SYM = REPO / "data" / "polished" / "polished_slink.sym"

    # own the fixture: the source lane belongs to another card and can be rewritten mid-run
    source = harness.FIXTURE
    if not source.is_file():
        raise SystemExit(f"no save fixture at {source}; the game never gets past the intro")
    fixture = LANE / "fixture" / "pol_sounds.SaveRAM"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, fixture)
    print(f"[pol-sounds] fixture sha256 {hashlib.sha256(fixture.read_bytes()).hexdigest()}", flush=True)
    sram = harness.SRAM
    sram.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture, sram / harness.SAVE_NAME)

    run = LANE / "sounds"
    text, pid = harness.launch("tools/polished_live/sounds.lua", run, {}, 180)
    print(text)
    data = [line for line in text.splitlines() if line.startswith("RESULT-DATA ")]
    if data:
        Path(str(run / "result.json")).write_text(data[0][len("RESULT-DATA "):], encoding="utf-8")
    print(f"[pol-sounds] result.txt sha256 "
          f"{hashlib.sha256((run / 'result.txt').read_bytes()).hexdigest() if (run / 'result.txt').exists() else 'n/a'}",
          flush=True)
    ok = "RESULT: PASS" in text
    print(f"[pol-sounds] {'PASS' if ok else 'FAIL'} (EmuHawk pid {pid})", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())