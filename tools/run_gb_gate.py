#!/usr/bin/env python3
"""run_gb_gate.py — launch ONE headless Game Boy gate and report PASS/FAIL.

    python tools/run_gb_gate.py lua/tests/test_gen1_memory_gate.lua
    python tools/run_gb_gate.py lua/tests/test_gen1_memory_gate.lua --rom yellow --target battle
    python tools/run_gb_gate.py lua/tests/test_gen2_memory_gate.lua --rom crystal

The GB counterpart to tools/run_gate.py, which is bound to the GBA/Radical Red setup. The
important difference is that these gates need NO SAVESTATE.

Gen 3 gates each load a `slink_*.State`, which is version-locked — BizHawk stops on a modal
dialog when handed a state from another release, which is the entire reason mkstates.py
exists. Gen 1 and Gen 2 boot from tests/fixtures/<gen>/<rom>_<target>.SaveRAM instead: a
battery save is plain SRAM, so it never goes stale, and booting to CONTINUE costs a second at
speedmode. Nothing here has to be rebuilt after a BizHawk upgrade.

ONE RUNNER, NOT ONE PER GENERATION. Everything that differs between Gen 1 and Gen 2 is a
table entry below, and `--rom` selects the generation implicitly because no ROM key is shared
between them. Copying this file for Gen 2 would have created a third divergent copy of a
launch sequence that is already subtle — see the SaveRAM naming rules, every clause of which
was a bug first.

Launch rules match run_gate.py: cwd = repo root with RELATIVE EmuHawk arg paths, because
absolute paths containing the "Google Drive" space break BizHawk's CLI parser.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen1_playthrough as g1  # noqa: E402
import gen2_playthrough as g2  # noqa: E402
from gen1_playthrough import (  # noqa: E402
    BIZHAWK_CONFIG,
    BUILD,
    EMUHAWK,
    SAVERAM_DIR,
    write_run_config,
)

# BizHawk names SaveRAM from its OWN gamedb entry, not the ROM filename — a ROM staged as
# gen1_red.gb still reads and writes "Pokemon - Red Version (USA, Europe).SaveRAM", and our
# Crystal dump is "(USA)" while its gamedb entry is "(USA, Europe)". To make a fixture visible
# to the emulator it has to be copied under THAT name.
#
# The companion-patch and Archipelago builds do NOT inherit their base ROM's name: BizHawk
# looks the game up by ROM HASH, and a patched ROM is unknown, so it falls back to a name
# derived from the FILENAME — `slink_red.gb` becomes "slink red.SaveRAM". Seeding only the
# vanilla name meant the patched build found no save, started a NEW GAME, and the gate
# reported party=0.
#
# In `patched`, a base fixture of None means COLD BOOT: there is no battery save to seed, and
# any stale one is removed so the ROM reaches NEW GAME. The Archipelago builds are in that
# category — the fork's save block is 4 bytes longer (sMainDataCheckSum 0xB523 -> 0xB527), so
# a vanilla .SaveRAM fails the AP checksum and CONTINUE is not offered at all.
#   key -> (fixture to seed from, ROM path, SaveRAM filename BizHawk will use)
GENS = {
    "gen1": {
        "play": g1,
        "saveram_names": {
            "red": "Pokemon - Red Version (USA, Europe).SaveRAM",
            "blue": "Pokemon - Blue Version (USA, Europe).SaveRAM",
            "yellow": "Pokemon - Yellow Version (USA, Europe).SaveRAM",
        },
        "patched": {
            # Isolated foreground trade-engine artifacts; no public companion
            # capability or receptionist dispatch is advertised by these builds.
            "red_native_trade": ("red", "patch/gen1/build/native_trade_red.gb", "native trade red.SaveRAM"),
            "blue_native_trade": ("blue", "patch/gen1/build/native_trade_blue.gb", "native trade blue.SaveRAM"),
            "yellow_native_trade": ("yellow", "patch/gen1/build/native_trade_yellow.gb", "native trade yellow.SaveRAM"),
            "red_foreground_trade": ("red", "patch/gen1/build/foreground_trade_red.gb", "foreground trade red.SaveRAM"),
            "blue_foreground_trade": ("blue", "patch/gen1/build/foreground_trade_blue.gb", "foreground trade blue.SaveRAM"),
            "yellow_foreground_trade": ("yellow", "patch/gen1/build/foreground_trade_yellow.gb", "foreground trade yellow.SaveRAM"),
            "red_receptionist_trade": ("red", "patch/gen1/build/receptionist_trade_red.gb", "receptionist trade red.SaveRAM"),
            "blue_receptionist_trade": ("blue", "patch/gen1/build/receptionist_trade_blue.gb", "receptionist trade blue.SaveRAM"),
            "yellow_receptionist_trade": ("yellow", "patch/gen1/build/receptionist_trade_yellow.gb", "receptionist trade yellow.SaveRAM"),
            "red_companion": ("red", "patch/gen1/build/companion_red/slink_red.gb", "slink red.SaveRAM"),
            "blue_companion": ("blue", "patch/gen1/build/companion_blue/slink_blue.gb", "slink blue.SaveRAM"),
            "yellow_companion": ("yellow", "patch/gen1/build/companion_yellow/slink_yellow.gb", "slink yellow.SaveRAM"),
            "red_patched": ("red", "patch/gen1/build/slink_red.gb", "slink red.SaveRAM"),
            # The RANDOMIZED path's artifact. Built by
            # `tests/live/make_randomized_patched.py` when a UPR jar is available, and
            # deliberately a separate key: the whole question it answers is whether the
            # structural injector produces a cartridge that boots and runs the panel, which
            # a hash comparison against the clean build cannot tell you.
            "red_rand_patched": ("red", "patch/gen1/build/slink_red_randomized.gb",
                                 "slink red randomized.SaveRAM"),
            "blue_patched": ("blue", "patch/gen1/build/slink_blue.gb", "slink blue.SaveRAM"),
            "red_ap": (None, "patch/build/gen1_red_ap.gb", "gen1 red ap.SaveRAM"),
            "blue_ap": (None, "patch/build/gen1_blue_ap.gb", "gen1 blue ap.SaveRAM"),
            # The AP gate's negative control: the SAME gate on the VANILLA cartridge, cold,
            # so it reaches the same intro and every AP assertion has to come out the other
            # way. Without that pair a detector stuck at "yes" would pass on its own. A ROM
            # path of None means "the vanilla dump for the key before _cold".
            "red_cold": (None, None, "Pokemon - Red Version (USA, Europe).SaveRAM"),
            "blue_cold": (None, None, "Pokemon - Blue Version (USA, Europe).SaveRAM"),
        },
    },
    "gen2": {
        "play": g2,
        "saveram_names": g2.SAVERAM_NAMES,
        # No patched or Archipelago Crystal builds are gated yet: the AP fork has no public
        # repo to build a symbol set from, so only five of its addresses are provable and the
        # profile is still flagged unverified (tests/unit/test_gen2_ap_addresses.py).
        "patched": {},
    },
}

# rom key -> generation. Built rather than written out, so adding a ROM to a GENS entry is
# enough. A duplicate key across generations would make `--rom` ambiguous, so it is an error
# rather than a last-one-wins.
ROM_TO_GEN = {}
for _gen, _spec in GENS.items():
    for _key in list(_spec["play"].ROMS) + list(_spec["patched"]):
        if _key in ROM_TO_GEN:
            raise RuntimeError(f"ROM key {_key!r} is claimed by both {ROM_TO_GEN[_key]} "
                               f"and {_gen} — --rom could not resolve it")
        ROM_TO_GEN[_key] = _gen

# tests/live/test_gen1_gates.py reads this to find each patched build's ROM path.
PATCHED = GENS["gen1"]["patched"]

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
    # gatelib builds the path from the gate's own name.
    m = re.search(r'G\.start\("([A-Za-z0-9_]+)"', src)
    return os.path.join(BUILD, m.group(1) + "_result.txt") if m else None


def gen_for(rom_key: str) -> str:
    try:
        return ROM_TO_GEN[rom_key]
    except KeyError:
        raise SystemExit(
            f"unknown --rom {rom_key!r}; known: {', '.join(sorted(ROM_TO_GEN))}") from None


def seed_saveram(rom_key: str, target: str, dest_dir: str | None = None) -> str:
    """Copy the committed fixture into BizHawk's SaveRAM dir so the ROM boots into it.

    `dest_dir` overrides where it lands, and MUST match whatever `write_run_config` was told,
    or the emulator boots an empty save from a directory nobody seeded. That pairing is the
    whole point of the per-instance redirect: two instances of one cartridge share a gamedb
    filename, so they need separate directories rather than separate names.
    """
    spec = GENS[gen_for(rom_key)]
    play = spec["play"]
    fixture = os.path.join(play.FIXTURES, f"{rom_key}_{target}.SaveRAM")
    if not os.path.exists(fixture):
        raise FileNotFoundError(
            f"missing fixture {os.path.relpath(fixture, REPO)} — build it with "
            f"`python tools/{play.__name__}.py --rom {rom_key} --target {target}`")
    target_dir = dest_dir or SAVERAM_DIR
    os.makedirs(target_dir, exist_ok=True)
    dst = os.path.join(target_dir, spec["saveram_names"][rom_key])
    shutil.copyfile(fixture, dst)
    return dst


def run_gate(script, rom_key="red", target="town", timeout=240, quiet=False, *, config_base=None,
             fixture_override=None, extra_env=None, cartridge_override=None):
    """Run one gate with isolated saves and optional per-run Lua input paths.

    Fixture overrides are copied into the same private SaveRAM directory as
    normal fixtures. Neither an override nor extra environment changes the
    caller's environment, base config, or source fixture.
    Returns (passed, result_path, text).
    """
    if extra_env and "SLINK_ROOT" in extra_env:
        raise ValueError("extra environment cannot override the gate worktree")
    if not os.path.exists(EMUHAWK):
        raise FileNotFoundError(f"EmuHawk not found at {EMUHAWK} (set $SLINK_EMUHAWK)")
    spec = GENS[gen_for(rom_key)]
    play = spec["play"]
    os.makedirs(BUILD, exist_ok=True)
    # Never seed or delete the user's emulator SaveRAM. A fresh directory also prevents
    # a same-hash cartridge or a previous failed gate from supplying this gate's save.
    run_dir = tempfile.mkdtemp(prefix=f"gb-gate-{rom_key}-", dir=BUILD)
    run_saveram = os.path.join(run_dir, "SaveRAM")
    os.makedirs(run_saveram)
    base_config = BIZHAWK_CONFIG if config_base is None else config_base
    if not os.path.isfile(base_config):
        raise FileNotFoundError(f"BizHawk config required for isolated SaveRAM: {base_config}")

    override_save_name=None
    if cartridge_override is not None:
        if not isinstance(cartridge_override,dict) or set(cartridge_override)!={"path","sha256","saveram_name"}:
            raise ValueError("explicit cartridge path, SHA256 and SaveRAM name required")
        source=Path(cartridge_override["path"]).resolve()
        if not source.is_relative_to(Path(REPO).resolve()) or source.suffix.lower() not in (".gb",".gbc"):
            raise ValueError("gate cartridge must be a Game Boy artifact inside this worktree")
        if not 0<source.stat().st_size<=8*1024*1024:raise ValueError("bounded Game Boy artifact required")
        data=source.read_bytes()
        if hashlib.sha256(data).hexdigest()!=cartridge_override["sha256"]:
            raise ValueError("gate cartridge hash differs")
        override_save_name=cartridge_override["saveram_name"]
        if not isinstance(override_save_name,str) or len(override_save_name)>180 or not re.fullmatch(r"[A-Za-z0-9 _().-]+\.SaveRAM",override_save_name):
            raise ValueError("single bounded SaveRAM filename required")
        base_key=spec["patched"][rom_key][0] if rom_key in spec["patched"] else rom_key
        if base_key is None:raise ValueError("explicit cartridge override requires a battery-save gate")
        staged=Path(run_dir)/("candidate"+source.suffix.lower());staged.write_bytes(data)
        if staged.read_bytes()!=data:raise ValueError("staged gate cartridge differs")
        rom_rel=staged.relative_to(REPO).as_posix()
        fixture=fixture_override or os.path.join(play.FIXTURES,f"{base_key}_{target}.SaveRAM")
        shutil.copyfile(fixture,os.path.join(run_saveram,override_save_name))
    elif rom_key in spec["patched"]:
        base_key, rom_rel, saveram_name = spec["patched"][rom_key]
        if rom_rel is None:
            rom_rel = play.staged_rom(rom_key.rsplit("_", 1)[0])
        if not os.path.exists(os.path.join(REPO, rom_rel)):
            builder = ("python tools/gen1_ap_rom.py" if base_key is None
                       else "python patch/gen1/tools/build.py")
            raise FileNotFoundError(f"{rom_rel} missing — build it with `{builder}`")
        if base_key is None:
            if fixture_override is not None:
                raise ValueError("cold-boot gates cannot accept a fixture override")
        else:
            fixture = fixture_override or os.path.join(play.FIXTURES, f"{base_key}_{target}.SaveRAM")
            if not os.path.exists(fixture):
                raise FileNotFoundError(f"missing fixture {os.path.relpath(fixture, REPO)}")
            shutil.copyfile(fixture, os.path.join(run_saveram, saveram_name))
    else:
        rom_rel = play.staged_rom(rom_key)
        if fixture_override is not None:
            shutil.copyfile(fixture_override, os.path.join(run_saveram, spec["saveram_names"][rom_key]))
        else:
            seed_saveram(rom_key, target, dest_dir=run_saveram)
    os.makedirs(BUILD, exist_ok=True)

    result = _result_path_for(script)
    if result and os.path.exists(result):
        os.remove(result)          # a leftover verdict must never be read as this run's

    tag = os.path.splitext(os.path.basename(script))[0]
    cfg_rel = os.path.relpath(os.path.join(run_dir, "config.ini"), REPO)
    write_run_config(base_config, os.path.join(REPO, cfg_rel), saveram_dir=run_saveram)

    env = dict(os.environ, SLINK_ROOT=REPO.replace("\\", "/"))
    if extra_env:
        env.update(extra_env)
    # This is the runner-owned destination, never an override from a test payload.
    save_name = override_save_name or (spec["patched"][rom_key][2] if rom_key in spec["patched"] else spec["saveram_names"][rom_key])
    env["SLINK_GATE_SAVERAM"] = os.path.join(run_saveram, save_name)
    env["SLINK_SAVERAM_DIRECTORY"] = run_saveram
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
    ap.add_argument("--rom", choices=sorted(ROM_TO_GEN), default="red")
    ap.add_argument("--target", choices=("town", "battle"), default="town")
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    passed, path, text = run_gate(args.script, args.rom, args.target, args.timeout)
    print(text.rstrip())
    print(f"\n[gate] {'PASS' if passed else 'FAIL'}  ({path})", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
