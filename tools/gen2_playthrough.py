#!/usr/bin/env python3
"""gen2_playthrough.py — bootstrap the Gen 2 battery save the live tests run from.

    python tools/gen2_playthrough.py                 # build it if missing
    python tools/gen2_playthrough.py --force         # rebuild
    python tools/gen2_playthrough.py --status        # report, build nothing

Drives lua/tests/gen2_playthrough.lua from a cold boot to a save containing a party, Poke
Balls and a position, then promotes the resulting SaveRAM to:

    tests/fixtures/gen2/crystal_town.SaveRAM

The Gen 1 counterpart, tools/gen1_playthrough.py, owns the shared launch machinery
(write_run_config, the staged-ROM rule, the emulator window/sound policy, the RTC pin), and
this imports it rather than forking it. What differs is genuinely Gen 2's:

  ONE ROM. Crystal only. Gold and Silver are supported for correctness — routing, profile
  keys, per-variant addresses, all verified statically against pret — but there are no dumps
  to run them against, and generating a fixture for an untested profile would produce a file
  that looks exactly like a verified one.

  ONE TARGET. `town` only. See the Lua header for why there is no grass fixture: New Bark
  Town's west exit is script-locked until Elm hands over a starter, and the duo scenarios
  that consume Gen 1's `battle` fixture are declared Gen 1-only because the rules they cover
  are enforced server-side and are generation-independent.

  A DIFFERENT COMMIT DETECTOR. Gen 1 reads sPartyCount through the System Bus at 0xAF2C;
  Gen 2's save block is at sPokemonData, whose first byte is sPartyCount — flat CartRAM
  0x2865 in Crystal (0x288A in Gold), reached without a bank switch.

Launch rules match the rest of the harness: cwd = repo root with RELATIVE EmuHawk arg paths,
because absolute paths containing the "Google Drive" space break BizHawk's CLI parser.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

from gen1_playthrough import (  # noqa: E402
    BIZHAWK_CONFIG,
    BUILD,
    EMUHAWK,
    SAVERAM_DIR,
    write_run_config,
)

FIXTURES = os.path.join(REPO, "tests", "fixtures", "gen2")
RESULT = os.path.join(BUILD, "gen2_playthrough_result.txt")

# rom key -> the cartridge dump at the repo root, and the name BizHawk files its SaveRAM
# under. That name comes from BizHawk's OWN gamedb entry (keyed on ROM hash), not from the
# path we launch — a ROM staged as gen2_crystal.gbc still writes
# "Pokemon - Crystal Version (USA).SaveRAM".
#
# MEASURED, not derived from the dump's filename: our dump is "…(USA).gbc" but BizHawk's
# gamedb entry is "(USA, Europe)", so it writes a file that does not resemble what was
# launched. The first run promoted nothing for exactly that reason.
ROMS = {"crystal": "Pokemon - Crystal Version (USA).gbc"}
SAVERAM_NAMES = {"crystal": "Pokemon - Crystal Version (USA, Europe).SaveRAM"}
TARGETS = ("town",)

# A Crystal .SaveRAM is 32790 bytes, not 32768: BizHawk appends the cartridge's 22-byte RTC
# block after the four 8KB SRAM banks. Bank-flat offsets below are unaffected, and freezing
# the clock inside the fixture is a bonus — the saved time of day travels with the save.
_RTC_TAIL = 22

# sPokemonData's first byte is sPartyCount (ram/sram.asm). The save block lives in SRAM
# bank 1, so flat CartRAM = 0x2000 + (sym - 0xA000).
_SPARTY_COUNT = {"crystal": 0x2000 + (0xA865 - 0xA000)}


def staged_rom(rom_key: str) -> str:
    """Copy the ROM to a space-free relative path and return it (relative to REPO)."""
    src = os.path.join(REPO, ROMS[rom_key])
    if not os.path.exists(src):
        raise FileNotFoundError(f"ROM not found: {ROMS[rom_key]}")
    ext = os.path.splitext(src)[1]
    rel = f"patch/build/gen2_{rom_key}{ext}"
    dst = os.path.join(REPO, rel)
    os.makedirs(BUILD, exist_ok=True)
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        shutil.copyfile(src, dst)
    return rel


def fixture_path(rom_key: str, target: str = "town") -> str:
    return os.path.join(FIXTURES, f"{rom_key}_{target}.SaveRAM")


def is_blank(path: str, rom_key: str = "crystal") -> bool:
    """True unless this SaveRAM actually contains a saved game.

    "Not all 0x00/0xFF" is too weak — Gen 1 measured a run whose menu drive silently failed
    still producing a 32KB file with 138 nonzero bytes. Check the party count the game itself
    wrote, which is what every downstream test depends on.
    """
    off = _SPARTY_COUNT[rom_key]
    if not os.path.exists(path) or os.path.getsize(path) <= off:
        return True
    with open(path, "rb") as f:
        data = f.read()
    if all(b == 0 for b in data) or all(b == 0xFF for b in data):
        return True
    return not 1 <= data[off] <= 6


def run_one(rom_key: str = "crystal", target: str = "town",
            timeout: int = 900) -> tuple[bool, str]:
    """One cold-boot run. Returns (ok, message)."""
    if not os.path.exists(EMUHAWK):
        return False, f"EmuHawk not found at {EMUHAWK} (set $SLINK_EMUHAWK)"
    rom_rel = staged_rom(rom_key)
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(FIXTURES, exist_ok=True)

    # A leftover save would put the title screen on CONTINUE, so the script would never see
    # the NEW GAME menu it asserts on. Move it aside rather than delete it — it may be the
    # only copy of whatever the last run produced.
    saveram = os.path.join(SAVERAM_DIR, SAVERAM_NAMES[rom_key])
    if os.path.exists(saveram):
        os.replace(saveram, saveram + ".prev")
    if os.path.exists(RESULT):
        os.remove(RESULT)

    cfg_rel = f"patch/build/play_cfg_gen2_{rom_key}_{target}.ini"
    if os.path.exists(BIZHAWK_CONFIG):
        write_run_config(BIZHAWK_CONFIG, os.path.join(REPO, cfg_rel))

    env = dict(os.environ, SLINK_ROOT=REPO.replace("\\", "/"), SLINK_PLAY_TARGET=target)
    cmd = [EMUHAWK, "--lua=lua/tests/gen2_playthrough.lua"]
    if os.path.exists(os.path.join(REPO, cfg_rel)):
        cmd.append(f"--config={cfg_rel}")
    cmd.append(rom_rel)

    print(f"[play] gen2 {rom_key}/{target}: launching …", file=sys.stderr)
    proc = subprocess.Popen(cmd, cwd=REPO, env=env)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(2)
    else:
        proc.kill()
        # A killed EmuHawk can leave a torn SaveRAM, so never promote after a timeout.
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

    if not os.path.exists(saveram):
        return False, f"no SaveRAM at {saveram} — BizHawk did not flush on close"
    dst = fixture_path(rom_key, target)
    shutil.copyfile(saveram, dst)
    if is_blank(dst, rom_key):
        os.remove(dst)
        return False, "SaveRAM is blank — the in-game SAVE did not commit"
    return True, f"{verdict}  →  {os.path.relpath(dst, REPO)}"


def status() -> int:
    print(f"{'fixture':40s} {'size':>8s}  state")
    missing = 0
    for rom_key in ROMS:
        for target in TARGETS:
            p = fixture_path(rom_key, target)
            name = os.path.relpath(p, REPO)
            if not os.path.exists(p):
                print(f"{name:40s} {'-':>8s}  MISSING")
                missing += 1
            elif is_blank(p, rom_key):
                print(f"{name:40s} {os.path.getsize(p):8d}  BLANK (rebuild)")
                missing += 1
            else:
                print(f"{name:40s} {os.path.getsize(p):8d}  ok")
    return 1 if missing else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", choices=sorted(ROMS), default="crystal")
    ap.add_argument("--target", choices=TARGETS, default="town")
    ap.add_argument("--timeout", type=int, default=900, help="per-run seconds (default 900)")
    ap.add_argument("--status", action="store_true", help="report fixtures, build nothing")
    ap.add_argument("--force", action="store_true", help="rebuild a fixture that exists")
    args = ap.parse_args()

    if args.status:
        return status()

    dst = fixture_path(args.rom, args.target)
    if os.path.exists(dst) and not is_blank(dst, args.rom) and not args.force:
        print(f"[play] gen2 {args.rom}/{args.target}: already present (use --force)",
              file=sys.stderr)
        return 0
    ok, msg = run_one(args.rom, args.target, timeout=args.timeout)
    print(f"[play] gen2 {args.rom}/{args.target}: {'OK ' if ok else 'FAIL'} {msg}",
          file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
