#!/usr/bin/env python3
"""mkstates.py — rebuild the SLink savestates for the INSTALLED BizHawk.

BizHawk savestates are version-locked: the committed slink_*.State files were written by
2.9.1 and make 2.11.1 hang on load ("Read a zipstate of version 1.0.2", then never returns).
Rather than re-capturing by hand after every emulator upgrade, this regenerates them from
the patched ROM plus its battery save, driving the title/CONTINUE intro with scripted input
(lua/tests/mkstate.lua).

    python tools/mkstates.py --status            # report only, build nothing
    python tools/mkstates.py --only pokecenter   # rebuild ONE family
    python tools/mkstates.py --force             # rebuild everything (see the warning below)

TWO families are derived, and **each needs the battery save made somewhere different**:

    town     standing IN FRONT OF A POKéMON CENTER DOOR, in a town
             -> overworld, door, pokecenter
             The overworld capture is REJECTED if pacing there triggers a wild battle: a
             generic state captured in grass makes every walking gate and duo scenario
             randomly flaky.
    battle   standing IN TALL GRASS
             -> prebattle, battle, actionmenu, movemenu

So `--force` with one save will rebuild that save's family and fail the others. Use `--only`
after moving the save, or just run it bare, which rebuilds whatever is stale.

`slink_battle2` and `slink_partyfreeze` are still hand-captured; no gate references either.
Gates whose state is absent or stale skip with that reason rather than hanging the suite.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIZHAWK = os.environ.get("SLINK_BIZHAWK_HOME", "E:/Howard/Bizhawk")
EMUHAWK = os.environ.get("SLINK_EMUHAWK", os.path.join(BIZHAWK, "EmuHawk.exe"))
BIZHAWK_CONFIG = os.environ.get("SLINK_BIZHAWK_CONFIG", os.path.join(BIZHAWK, "config.ini"))
STATE_DIR = os.path.join(BIZHAWK, "GBA", "State")
SAVERAM_DIR = os.path.join(BIZHAWK, "GBA", "SaveRAM")
ROM_REL = "patch/build/slink_RR.gba"
# BizHawk keys SaveRAM by ROM basename, so the patched build needs its own copy of the save.
SAVERAM_DST = "slink_RR.SaveRAM"
SAVERAM_OVERRIDE = None   # set by --saveram

# name -> how it is produced.  None = hand-captured only (see module docstring).
STATES = {
    # ONE emulator run from a save made STANDING IN FRONT OF A POKéMON CENTER DOOR, in a town:
    # the generic walkable state, the doorway, and the interior. The overworld capture is
    # rejected if pacing there triggers a wild battle.
    "slink_overworld.State": "town",
    "slink_door.State": "town",
    "slink_pokecenter.State": "town",
    # ONE emulator run from a save made STANDING IN TALL GRASS: pace until an encounter fires,
    # advance to the action menu, then one A press further. Listed per-file so the staleness
    # report is per-file, but the "battle" kind writes all four.
    "slink_prebattle.State": "battle",
    "slink_battle.State": "battle",
    "slink_actionmenu.State": "battle",
    "slink_movemenu.State": "battle",
    # Still hand-captured: a second battle context and a borrowed-party (Battle Tower /
    # Poke Dude) moment. No gate references either.
    "slink_battle2.State": None,
    "slink_partyfreeze.State": None,
}


def emuhawk_version():
    """Installed EmuHawk version, read out of the binary (no --version flag exists)."""
    import re
    with open(EMUHAWK, "rb") as f:
        hits = set(re.findall(rb"2\.\d+\.\d+", f.read()))
    return max((h.decode() for h in hits), key=lambda v: [int(x) for x in v.split(".")]) \
        if hits else "?"


def state_version(path):
    """The BizHawk version stamped inside a .State, or None if unreadable."""
    try:
        with zipfile.ZipFile(path) as z:
            return z.read("BizVersion.txt").decode().split()[-1]
    except Exception:
        return None


def is_stale(path, emu_ver):
    """A state is usable only if it was written by the running emulator version."""
    if not os.path.exists(path):
        return True, "missing"
    v = state_version(path)
    if v is None:
        return True, "unreadable"
    if v != emu_ver:
        return True, f"written by BizHawk {v}, running {emu_ver}"
    return False, f"current ({v})"


def is_blank_save(path):
    """A BizHawk GBA .SaveRAM is <flash bytes> + a 16-byte footer; erased flash is all 0xFF.
    A ROM that was booted but never saved in-game leaves a fully erased file behind, so
    "the file exists" is not the same as "there is a save in it"."""
    try:
        with open(path, "rb") as f:
            body = f.read()[:-16]
    except OSError:
        return True
    return all(b == 0xFF for b in body)


def find_saveram():
    """Newest non-blank Radical Red battery save in BizHawk's GBA SaveRAM dir, or None.

    Discovered rather than hard-coded: BizHawk names SaveRAM after whatever the ROM file was
    called, so the same save shows up as "slink RR.SaveRAM", "Pokemon - Radical Red.SaveRAM",
    "rr unpatched.SaveRAM" ... depending on which copy was last played. Matching on rr/radical
    keeps the FireRed saves in the same directory out of it.
    """
    import glob
    import re
    cands = []
    for p in glob.glob(os.path.join(SAVERAM_DIR, "*.SaveRAM")):
        name = os.path.basename(p)
        if name == SAVERAM_DST or ".AutoSaveRAM." in name:
            continue                       # our own copy, and BizHawk's autosave shadow
        if not re.search(r"(?i)(?:^|[^a-z])(rr|radical)(?:[^a-z]|$)", name):
            continue
        if is_blank_save(p):
            continue
        cands.append(p)
    return max(cands, key=os.path.getmtime) if cands else None


NO_SAVE_HELP = """\
No usable Radical Red battery save exists — every GBA/SaveRAM/*.SaveRAM is erased flash
(all 0xFF).  The old test runs booted from savestates and never saved in-game, so the mid-game
party those states carry lives ONLY inside them, and BizHawk {emu} cannot read a 2.9.1 state
(it stops on a modal version dialog, which is the "hang").

One manual step unlocks automatic regeneration from here on, permanently — a battery save is
plain flash content and is NOT version-locked:

  1. Get BizHawk 2.9.1 (portable, alongside your 2.11.1 install).
  2. Load patch/build/slink_RR.gba, then load slink_overworld.State.
  3. SAVE IN-GAME (the in-game menu, not a savestate) and close the emulator.
  4. Copy "GBA/SaveRAM/slink_RR.SaveRAM" from that install to this one.
  5. python tools/mkstates.py

If you'd rather not install 2.9.1: play RR in 2.11.1 to any point with a party you're happy
to test against, save in-game, and step 5 works the same.

Until then the live gates skip instead of hanging — pytest and everything else is unaffected.\
"""


def _run_mkstate(kind, target, timeout, extra_env=None):
    """One EmuHawk run of lua/tests/mkstate.lua in the given mode."""
    result = os.path.join(REPO, "patch", "build", "mkstate_result.txt")
    if os.path.exists(result):
        os.remove(result)
    cfg_rel = "patch/build/mkstate_cfg.ini"
    shutil.copyfile(BIZHAWK_CONFIG, os.path.join(REPO, cfg_rel))

    env = dict(os.environ, SLINK_ROOT=REPO.replace("\\", "/"),
               SLINK_STATE_OUT=target.replace("\\", "/"), SLINK_STATE_KIND=kind,
               **(extra_env or {}))
    cmd = [EMUHAWK, f"--config={cfg_rel}", "--lua=lua/tests/mkstate.lua", ROM_REL]
    print(f"[mkstates] {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    done = False
    while proc.poll() is None and time.time() - t0 < timeout:
        time.sleep(1.0)
        # Stop waiting as soon as the script publishes its verdict — see run_gate.py.
        if os.path.exists(result):
            with open(result, encoding="utf-8", errors="replace") as f:
                if any(ln.strip().startswith("RESULT:") for ln in f):
                    done = True
                    break
    if proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        if not done:
            print(f"[mkstates] TIMEOUT after {timeout}s")
    text = open(result, encoding="utf-8", errors="replace").read() if os.path.exists(result) else ""
    print(text.strip() or "(no result file)")
    return "RESULT: PASS" in text


def build_town(timeout=600):
    """Capture slink_overworld + slink_door + slink_pokecenter from a town save made standing
    in front of a Pokemon Center door."""
    src = SAVERAM_OVERRIDE or find_saveram()
    if not src:
        print(NO_SAVE_HELP.format(emu=emuhawk_version()))
        return False
    shutil.copyfile(src, os.path.join(SAVERAM_DIR, SAVERAM_DST))
    print(f"[mkstates] seeded {SAVERAM_DST} from {os.path.basename(src)}")
    return _run_mkstate("town", os.path.join(STATE_DIR, "slink_pokecenter.State"), timeout,
                        {"SLINK_STATE_DIR": STATE_DIR.replace("\\", "/")})


def build_battle(timeout=600):
    """Capture prebattle/battle/actionmenu/movemenu from a save made IN TALL GRASS.

    Boots from the battery save rather than deriving from slink_overworld.State: the two want
    opposite terrain (this one needs encounters, that one must not have them), so tying them
    together forced both to share a location and made the walking scenarios flaky.
    """
    src = SAVERAM_OVERRIDE or find_saveram()
    if not src:
        print(NO_SAVE_HELP.format(emu=emuhawk_version()))
        return False
    shutil.copyfile(src, os.path.join(SAVERAM_DIR, SAVERAM_DST))
    print(f"[mkstates] seeded {SAVERAM_DST} from {os.path.basename(src)}")
    return _run_mkstate("battle", os.path.join(STATE_DIR, "slink_battle.State"), timeout,
                        {"SLINK_STATE_DIR": STATE_DIR.replace("\\", "/")})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="rebuild even if current")
    ap.add_argument("--status", action="store_true", help="report only, build nothing")
    ap.add_argument("--only", default=None, choices=("town", "battle"),
                    help="rebuild just this family. Each kind needs the battery save made "
                         "somewhere different (tall grass for battle, a Pokemon Center door "
                         "for pokecenter), so rebuilding everything at once is usually NOT "
                         "what you want.")
    ap.add_argument("--saveram", default=None,
                    help="battery save to boot from (default: newest non-blank rr/radical "
                         "*.SaveRAM in BizHawk's GBA/SaveRAM)")
    args = ap.parse_args()
    global SAVERAM_OVERRIDE
    SAVERAM_OVERRIDE = args.saveram

    emu_ver = emuhawk_version()
    print(f"[mkstates] EmuHawk {emu_ver}  states in {STATE_DIR}")
    found = SAVERAM_OVERRIDE or find_saveram()
    print(f"[mkstates] battery save: {os.path.basename(found) if found else 'NONE (see below)'}")
    kinds, manual = [], []
    for name, kind in sorted(STATES.items()):
        path = os.path.join(STATE_DIR, name)
        stale, why = is_stale(path, emu_ver)
        flag = "STALE" if stale else "ok   "
        print(f"  {flag} {name:26s} {why}")
        if not (stale or args.force):
            continue
        if kind is None:
            manual.append(name)
        elif args.only and kind != args.only:
            continue
        elif kind not in kinds:
            kinds.append(kind)          # one run per kind, not per file
    if args.status:
        return 0

    def _backup(name):
        path = os.path.join(STATE_DIR, name)
        if not os.path.exists(path):
            return
        backup = path + f".bizhawk{state_version(path) or 'unknown'}.bak"
        if not os.path.exists(backup):
            shutil.copyfile(path, backup)
            print(f"[mkstates] backed up the old state -> {os.path.basename(backup)}")

    rc = 0
    # Order matters: the battle states are DERIVED from the overworld one.
    for kind in ("town", "battle"):
        if kind not in kinds:
            continue
        for name, k in STATES.items():
            if k == kind:
                _backup(name)
        ok = {"town": build_town, "battle": build_battle}[kind]()
        if not ok:
            print(f"[mkstates] FAILED to build the {kind} state(s)")
            rc = 1
    if manual:
        print("\n[mkstates] These need a hand capture in EmuHawk "
              f"{emu_ver} (they sit at a specific map/battle context):")
        for n in manual:
            print(f"    {n}")
        print("  Gates that need one are skipped while it is stale — nothing hangs.")
    if rc:
        print("\nEach family needs the in-game save made somewhere specific:\n"
              "    town    in front of a Pokemon Center door, in a town (must be encounter-free)\n"
              "    battle  standing in tall grass\n"
              "Move the save, then re-run with --only <kind>. A failed run never overwrites a "
              "good state.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
