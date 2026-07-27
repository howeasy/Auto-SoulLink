#!/usr/bin/env python3
"""run_gen1_gate.py — launch ONE headless Gen 1 gate and report PASS/FAIL.

    python tools/run_gen1_gate.py lua/tests/test_gen1_memory_gate.lua
    python tools/run_gen1_gate.py lua/tests/test_gen1_memory_gate.lua --rom yellow --target battle

The Gen 1 counterpart to tools/run_gate.py, which is bound to the GBA/Radical Red setup.
The important difference is that these gates need NO SAVESTATE.

Gen 3 gates each load a `slink_*.State`, which is version-locked — BizHawk stops on a modal
dialog when handed a state from another release, which is the entire reason mkstates.py
exists. Gen 1 boots from tests/fixtures/gen1/<rom>_<target>.SaveRAM instead: a battery save
is plain SRAM, so it never goes stale, and booting to CONTINUE costs a second at speedmode.
Nothing here has to be rebuilt after a BizHawk upgrade.

Launch rules match run_gate.py: cwd = repo root with RELATIVE EmuHawk arg paths, because
absolute paths containing the "Google Drive" space break BizHawk's CLI parser.
"""
import argparse
import os
import re
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
    FIXTURES,
    ROMS,
    SAVERAM_DIR,
    staged_rom,
    write_run_config,
)

# BizHawk names SaveRAM from its OWN gamedb entry, not the ROM filename — a ROM staged as
# gen1_red.gb still reads and writes "Pokemon - Red Version (USA, Europe).SaveRAM". To make
# a fixture visible to the emulator it has to be copied under THAT name.
SAVERAM_NAMES = {
    "red": "Pokemon - Red Version (USA, Europe).SaveRAM",
    "blue": "Pokemon - Blue Version (USA, Europe).SaveRAM",
    "yellow": "Pokemon - Yellow Version (USA, Europe).SaveRAM",
}

# The companion-patch builds.
#
# They do NOT inherit their base ROM's SaveRAM name: BizHawk looks the game up in its gamedb
# by ROM HASH, and a patched ROM is unknown, so it falls back to a name derived from the
# FILENAME — `slink_red.gb` becomes "slink red.SaveRAM". Seeding only the vanilla name meant
# the patched build found no save, started a NEW GAME, and the gate reported party=0.
#   key -> (fixture to seed from, ROM path, SaveRAM filename BizHawk will use)
PATCHED = {
    "red_patched": ("red", "patch/gen1/build/slink_red.gb", "slink red.SaveRAM"),
    "blue_patched": ("blue", "patch/gen1/build/slink_blue.gb", "slink blue.SaveRAM"),
}

# Gates name their own verdict file; read it out of the source so we watch exactly one file
# rather than "whichever file in patch/build changed" (run_gate.py learned that the hard
# way — a stale neighbour's verdict could be attributed to this run).
_OUT_RE = re.compile(r"patch/build/([A-Za-z0-9_]+_result\.txt)")


def _result_path_for(script):
    try:
        with open(os.path.join(REPO, script), encoding="utf-8", errors="replace") as f:
            src = f.read()
    except OSError:
        return None
    m = _OUT_RE.search(src)
    if m:
        return os.path.join(BUILD, m.group(1))
    # gen1_gatelib builds the path from the gate's own name.
    m = re.search(r'G\.start\("([A-Za-z0-9_]+)"\)', src)
    return os.path.join(BUILD, m.group(1) + "_result.txt") if m else None


def seed_saveram(rom_key: str, target: str) -> str:
    """Copy the committed fixture into BizHawk's SaveRAM dir so the ROM boots into it."""
    fixture = os.path.join(FIXTURES, f"{rom_key}_{target}.SaveRAM")
    if not os.path.exists(fixture):
        raise FileNotFoundError(
            f"missing fixture {os.path.relpath(fixture, REPO)} — build it with "
            f"`python tools/gen1_playthrough.py --rom {rom_key} --target {target}`")
    os.makedirs(SAVERAM_DIR, exist_ok=True)
    dst = os.path.join(SAVERAM_DIR, SAVERAM_NAMES[rom_key])
    shutil.copyfile(fixture, dst)
    return dst


def run_gate(script, rom_key="red", target="town", timeout=240, quiet=False):
    """Run one gate. Returns (passed, result_path, text)."""
    if not os.path.exists(EMUHAWK):
        raise FileNotFoundError(f"EmuHawk not found at {EMUHAWK} (set $SLINK_EMUHAWK)")
    if rom_key in PATCHED:
        base_key, rom_rel, saveram_name = PATCHED[rom_key]
        if not os.path.exists(os.path.join(REPO, rom_rel)):
            raise FileNotFoundError(
                f"{rom_rel} missing — build it with `python patch/gen1/tools/build.py`")
        fixture = os.path.join(FIXTURES, f"{base_key}_{target}.SaveRAM")
        if not os.path.exists(fixture):
            raise FileNotFoundError(f"missing fixture {os.path.relpath(fixture, REPO)}")
        os.makedirs(SAVERAM_DIR, exist_ok=True)
        shutil.copyfile(fixture, os.path.join(SAVERAM_DIR, saveram_name))
    else:
        rom_rel = staged_rom(rom_key)
        seed_saveram(rom_key, target)
    os.makedirs(BUILD, exist_ok=True)

    result = _result_path_for(script)
    if result and os.path.exists(result):
        os.remove(result)          # a leftover verdict must never be read as this run's

    tag = os.path.splitext(os.path.basename(script))[0]
    cfg_rel = f"patch/build/gate_cfg_{tag}_{rom_key}.ini"
    if os.path.exists(BIZHAWK_CONFIG):
        write_run_config(BIZHAWK_CONFIG, os.path.join(REPO, cfg_rel))

    env = dict(os.environ, SLINK_ROOT=REPO.replace("\\", "/"))
    cmd = [EMUHAWK, f"--lua={script}"]
    if os.path.exists(os.path.join(REPO, cfg_rel)):
        cmd.append(f"--config={cfg_rel}")
    cmd.append(rom_rel)

    if not quiet:
        print(f"[gate] {tag} on {rom_key}/{target} …", file=sys.stderr)
    proc = subprocess.Popen(cmd, cwd=REPO, env=env)
    deadline = time.time() + timeout
    while time.time() < deadline and proc.poll() is None:
        time.sleep(1)
    if proc.poll() is None:
        proc.kill()
        return False, result, f"timed out after {timeout}s"

    text = ""
    if result and os.path.exists(result):
        with open(result, encoding="utf-8", errors="replace") as f:
            text = f.read()
    verdict = next((ln for ln in reversed(text.splitlines())
                    if ln.startswith("RESULT:")), "")
    return verdict.startswith("RESULT: PASS"), result, text


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", help="path to the gate, e.g. lua/tests/test_gen1_memory_gate.lua")
    ap.add_argument("--rom", choices=sorted(ROMS) + sorted(PATCHED), default="red")
    ap.add_argument("--target", choices=("town", "battle"), default="town")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    passed, path, text = run_gate(args.script, args.rom, args.target, args.timeout)
    print(text.rstrip())
    print(f"\n[gate] {'PASS' if passed else 'FAIL'}  ({path})", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
