#!/usr/bin/env python3
"""gen1_playthrough.py — bootstrap the Gen 1 battery saves the live tests run from.

    python tools/gen1_playthrough.py                     # all 3 ROMs x both targets
    python tools/gen1_playthrough.py --rom red           # one ROM, both targets
    python tools/gen1_playthrough.py --rom red --target town
    python tools/gen1_playthrough.py --status            # report what exists, build nothing

Drives lua/tests/gen1_playthrough.lua from a cold boot to a save containing a party, Poke
Balls, and a position — then promotes the resulting SaveRAM to:

    tests/fixtures/gen1/{red,blue,yellow}_{town,battle}.SaveRAM

WHY THESE ARE COMMITTED: a .SaveRAM is plain SRAM content, NOT version-locked the way a
BizHawk savestate is. mkstates.py rebuilds savestates from them after any emulator upgrade,
so this script runs six times ever rather than on every CI run. Its flakiness therefore
costs minutes once instead of breaking builds.

TWO TARGETS PER ROM, because mkstates.py's hard-won rule applies here too:
    town    encounter-free ground — overworld, box and memorialize scenarios. A state
            captured in grass makes every walking scenario randomly flaky.
    battle  tall grass — anything that needs a wild encounter.
BizHawk only flushes SaveRAM when the ROM closes, so each target is its own run.

Launch rules match run_gate.py / e2e_duo.py: cwd = repo root with RELATIVE EmuHawk arg
paths, because absolute paths containing the "Google Drive" space break BizHawk's CLI
parser. Absolute paths are fine inside Lua.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIZHAWK = os.environ.get("SLINK_BIZHAWK_HOME", "E:/Howard/Bizhawk")
EMUHAWK = os.environ.get("SLINK_EMUHAWK", os.path.join(BIZHAWK, "EmuHawk.exe"))
BIZHAWK_CONFIG = os.environ.get("SLINK_BIZHAWK_CONFIG", os.path.join(BIZHAWK, "config.ini"))
# Game Boy, not GBA — the Gen 3 harness's dirs do not apply.
SAVERAM_DIR = os.path.join(BIZHAWK, "Gameboy", "SaveRAM")
# The (System, Type) pair BizHawk files Game Boy saves under. GBC cartridges are covered by
# the same entry as DMG — there is no separate GBC system in the path table.
_GB_PATH_SYSTEMS = {"GB_GBC_SGB", "GBL"}
BUILD = os.path.join(REPO, "patch", "build")
FIXTURES = os.path.join(REPO, "tests", "fixtures", "gen1")
RESULT = os.path.join(BUILD, "gen1_playthrough_result.txt")

# rom key -> the cartridge dump at the repo root. Staged to a space-free name under
# patch/build/ before launch (see the module docstring).
ROMS = {
    "red": "Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb",
    "blue": "Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb",
    "yellow": "Pokemon - Yellow Version (USA, Europe).gbc",
}
TARGETS = ("town", "battle")


def staged_rom(rom_key: str) -> str:
    """Copy the ROM to a space-free relative path and return it (relative to REPO)."""
    src = os.path.join(REPO, ROMS[rom_key])
    if not os.path.exists(src):
        raise FileNotFoundError(f"ROM not found: {ROMS[rom_key]}")
    ext = os.path.splitext(src)[1]
    rel = f"patch/build/gen1_{rom_key}{ext}"
    dst = os.path.join(REPO, rel)
    os.makedirs(BUILD, exist_ok=True)
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        shutil.copyfile(src, dst)
    return rel


def fixture_path(rom_key: str, target: str) -> str:
    return os.path.join(FIXTURES, f"{rom_key}_{target}.SaveRAM")


# Where to park the emulator window, and whether to make noise. These runs are long and
# unattended, so by default they go to a SECOND MONITOR with sound off rather than stealing
# the primary display and blasting the Pokemon theme. Override with SLINK_EMU_WINDOW="x,y"
# (or "primary" to leave the position alone) and SLINK_EMU_SOUND=1.
EMU_WINDOW = os.environ.get("SLINK_EMU_WINDOW", "1200,-1300")
EMU_SOUND = os.environ.get("SLINK_EMU_SOUND", "0") == "1"


def write_run_config(src: str, dst: str, saveram_dir: str | None = None) -> None:
    """Copy BizHawk's config, muted and positioned, without touching the user's own.

    config.ini is JSON with a BOM. Unknown-key edits are harmless, but SaveWindowPosition
    must be turned off too — otherwise BizHawk writes the window back on exit and the next
    run reads the moved position from OUR copy rather than the requested one.

    `saveram_dir` redirects the Game Boy Save RAM path for THIS run only.

    Why that is needed: BizHawk names a SaveRAM file from its gamedb entry, which is keyed on
    the ROM hash — not on the path we launched. Two instances of the SAME cartridge therefore
    resolve to one file and stamp on each other. Gen 1 sidestepped it by pairing Red with
    Blue, but that is a constraint on which cartridges can be tested together, not a fix, and
    Gen 2 has only one dump available. Redirecting the directory per instance makes a
    same-cartridge duo work and retires the Gen 1 pairing constraint too.
    """
    try:
        with open(src, encoding="utf-8-sig") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        shutil.copyfile(src, dst)          # unparseable: fall back to a plain copy
        return

    if not EMU_SOUND:
        for key in ("SoundEnabled", "SoundEnabledNormal", "SoundEnabledRWFF"):
            cfg[key] = False
        cfg["SoundVolume"] = 0
    if EMU_WINDOW.lower() != "primary":
        cfg["MainWindowPosition"] = EMU_WINDOW.replace(",", ", ")
        cfg["MainWindowMaximized"] = False
        cfg["SaveWindowPosition"] = False

    # Pin the Game Boy RTC. Gen 2 branches on time of day — encounter tables, scripts, and
    # which Pokemon are even present — so a fixture built at 10am and replayed at 2am is a
    # different game. Left to the real clock this presents as unreproducible flake rather
    # than as a clock problem. Gen 1 has no RTC and is unaffected either way.
    #
    # Forced rather than asserted: this makes determinism a property of the harness instead
    # of a property of whichever config.ini the developer happens to have.
    sync = cfg.setdefault("CoreSyncSettings", {}).setdefault(
        "BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy", {})
    sync["RealTimeRTC"] = False
    sync["InitialTime"] = 0

    if saveram_dir:
        os.makedirs(saveram_dir, exist_ok=True)
        # BizHawk stores paths per (System, Type). The Game Boy family shares one entry,
        # so a GBC cartridge is covered by GB_GBC_SGB. Rewrite only that pair and leave
        # every other system's paths alone.
        entries = (cfg.get("PathEntries") or {}).get("Paths") or []
        patched = 0
        for entry in entries:
            if entry.get("Type") == "Save RAM" and entry.get("System") in _GB_PATH_SYSTEMS:
                entry["Path"] = saveram_dir.replace("\\", "/")
                patched += 1
        if not patched:
            raise RuntimeError(
                f"no Save RAM PathEntries for {sorted(_GB_PATH_SYSTEMS)} in {src} — BizHawk's "
                f"config schema changed, and silently not redirecting would let two "
                f"instances of one cartridge share a SaveRAM file")

    with open(dst, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# SRAM bank 1 holds the main save block; sPartyData is System-Bus 0xAF2C there, and its
# first byte is the party count. Flat CartRAM offset = bank*0x2000 + (addr - 0xA000).
_SPARTY_COUNT = 0x2000 + (0xAF2C - 0xA000)


def _is_blank(path: str) -> bool:
    """True unless this SaveRAM actually contains a saved game.

    "Not all 0x00/0xFF" is too weak: a run whose menu drive silently failed still produced
    a 32KB file with 138 nonzero bytes and sPartyCount = 0xFF. Check the party count the
    game itself writes, which is the thing every downstream test depends on.
    """
    if not os.path.exists(path) or os.path.getsize(path) <= _SPARTY_COUNT:
        return True
    with open(path, "rb") as f:
        data = f.read()
    if all(b == 0 for b in data) or all(b == 0xFF for b in data):
        return True
    return not 1 <= data[_SPARTY_COUNT] <= 6


def run_one(rom_key: str, target: str, timeout: int = 600) -> tuple[bool, str]:
    """One cold-boot run. Returns (ok, message)."""
    if not os.path.exists(EMUHAWK):
        return False, f"EmuHawk not found at {EMUHAWK} (set $SLINK_EMUHAWK)"
    rom_rel = staged_rom(rom_key)
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(FIXTURES, exist_ok=True)

    # BizHawk names SaveRAM after the game's entry in its OWN gamedb, not after the ROM
    # file — a ROM staged as gen1_red.gb still writes
    # "Pokemon - Red Version (USA, Europe).SaveRAM". So snapshot the directory and find
    # whatever appears or changes during the run instead of predicting the name.
    before = {}
    if os.path.isdir(SAVERAM_DIR):
        for name in os.listdir(SAVERAM_DIR):
            path = os.path.join(SAVERAM_DIR, name)
            if name.endswith(".SaveRAM"):
                before[path] = os.path.getmtime(path)
    if os.path.exists(RESULT):
        os.remove(RESULT)

    cfg_rel = f"patch/build/play_cfg_{rom_key}_{target}.ini"
    if os.path.exists(BIZHAWK_CONFIG):
        write_run_config(BIZHAWK_CONFIG, os.path.join(REPO, cfg_rel))

    env = dict(os.environ, SLINK_ROOT=REPO.replace("\\", "/"), SLINK_PLAY_TARGET=target)
    cmd = [EMUHAWK, "--lua=lua/tests/gen1_playthrough.lua"]
    if os.path.exists(os.path.join(REPO, cfg_rel)):
        cmd.append(f"--config={cfg_rel}")
    cmd.append(rom_rel)

    print(f"[play] {rom_key}/{target}: launching …", file=sys.stderr)
    proc = subprocess.Popen(cmd, cwd=REPO, env=env)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(2)
    else:
        proc.kill()
        # N8: a killed EmuHawk may leave a torn SaveRAM, so never promote after a timeout.
        return False, f"timed out after {timeout}s (SaveRAM not promoted)"

    verdict = ""
    if os.path.exists(RESULT):
        with open(RESULT, encoding="utf-8", errors="replace") as f:
            text = f.read()
        # LAST verdict wins: an aborted run can emit more than one line.
        verdict = next((ln for ln in reversed(text.splitlines())
                        if ln.startswith("RESULT:")), "")
    if not verdict.startswith("RESULT: PASS"):
        return False, verdict or "script wrote no RESULT line"

    touched = []
    if os.path.isdir(SAVERAM_DIR):
        for name in os.listdir(SAVERAM_DIR):
            path = os.path.join(SAVERAM_DIR, name)
            if not name.endswith(".SaveRAM") or ".AutoSaveRAM" in name:
                continue
            if path not in before or os.path.getmtime(path) > before[path]:
                touched.append(path)
    if not touched:
        return False, f"no SaveRAM written in {SAVERAM_DIR}"
    saveram = max(touched, key=os.path.getmtime)
    if _is_blank(saveram):
        return False, "SaveRAM is blank — the in-game SAVE did not commit"

    dst = fixture_path(rom_key, target)
    shutil.copyfile(saveram, dst)
    return True, f"{verdict}  →  {os.path.relpath(dst, REPO)}"


def status() -> int:
    print(f"{'fixture':34s} {'size':>8s}  state")
    missing = 0
    for rom_key in ROMS:
        for target in TARGETS:
            p = fixture_path(rom_key, target)
            name = os.path.relpath(p, REPO)
            if not os.path.exists(p):
                print(f"{name:34s} {'-':>8s}  MISSING")
                missing += 1
            elif _is_blank(p):
                print(f"{name:34s} {os.path.getsize(p):8d}  BLANK (rebuild)")
                missing += 1
            else:
                print(f"{name:34s} {os.path.getsize(p):8d}  ok")
    return 1 if missing else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", choices=sorted(ROMS), help="only this ROM (default: all three)")
    ap.add_argument("--target", choices=TARGETS, help="only this target (default: both)")
    ap.add_argument("--timeout", type=int, default=600, help="per-run seconds (default 600)")
    ap.add_argument("--status", action="store_true", help="report fixtures, build nothing")
    ap.add_argument("--force", action="store_true", help="rebuild fixtures that already exist")
    args = ap.parse_args()

    if args.status:
        return status()

    roms = [args.rom] if args.rom else list(ROMS)
    targets = [args.target] if args.target else list(TARGETS)
    failures = []
    for rom_key in roms:
        for target in targets:
            dst = fixture_path(rom_key, target)
            if os.path.exists(dst) and not _is_blank(dst) and not args.force:
                print(f"[play] {rom_key}/{target}: already present (use --force)", file=sys.stderr)
                continue
            ok, msg = run_one(rom_key, target, timeout=args.timeout)
            print(f"[play] {rom_key}/{target}: {'OK ' if ok else 'FAIL'} {msg}", file=sys.stderr)
            if not ok:
                failures.append(f"{rom_key}/{target}: {msg}")

    if failures:
        print("\nFAILED:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
