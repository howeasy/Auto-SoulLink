#!/usr/bin/env python3
"""run_gb_gate.py — launch ONE headless Game Boy gate and report PASS/FAIL.

    python tools/run_gb_gate.py lua/tests/test_gen1_inspect_gate.lua
    python tools/run_gb_gate.py lua/tests/test_gen1_inspect_gate.lua --rom yellow --target battle
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
import os
import re
import shutil
import subprocess
import sys
import time

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

# The fixture builders, per generation. Gen 1's is tools/gen1_fixtures.py (the new client's
# scripted pipeline); the old gen1_playthrough driver this message used to name is gone, and
# naming a deleted command in a recovery message is worse than naming none.
_FIXTURE_BUILDERS = {
    "gen1_playthrough": "python tools/gen1_fixtures.py {rom} {target}",
    "gen2_playthrough": "python tools/gen2_playthrough.py --rom {rom} --target {target}",
}


def _rebuild_command(play_name: str, rom_key: str, target: str) -> str:
    template = _FIXTURE_BUILDERS.get(
        play_name, "python tools/" + play_name + ".py --rom {rom} --target {target}")
    return template.format(rom=rom_key, target=target)


# BizHawk names SaveRAM from its OWN gamedb entry, not the ROM filename — a ROM staged as
# gen1_red.gb still reads and writes "Pokemon - Red Version (USA, Europe).SaveRAM", and our
# Crystal dump is "(USA)" while its gamedb entry is "(USA, Europe)". To make a fixture visible
# to the emulator it has to be copied under THAT name.
#
# The companion-patch builds do NOT inherit their base ROM's name: BizHawk
# looks the game up by ROM HASH, and a patched ROM is unknown, so it falls back to a name
# derived from the FILENAME — `slink_red.gb` becomes "slink red.SaveRAM". Seeding only the
# vanilla name meant the patched build found no save, started a NEW GAME, and the gate
# reported party=0.
#
# In `patched`, a base fixture of None means COLD BOOT: there is no battery save to seed, and
# any stale one is removed so the ROM reaches NEW GAME — that is what the `*_cold` keys are.
#   key -> (fixture to seed from, ROM path, SaveRAM filename BizHawk will use)
GENS = {
    "gen1": {
        "play": g1,
        "saveram_names": {
            "red": "Pokemon - Red Version (USA, Europe).SaveRAM",
            "blue": "Pokemon - Blue Version (USA, Europe).SaveRAM",
            "yellow": "Pokemon - Yellow Version (USA, Europe).SaveRAM",
            # pureRGB: a built cartridge BizHawk has never seen, so the name is derived from the
            # staged FILENAME (underscores -> spaces, .gbc dropped): patch/build/gen1_purered.gbc
            # -> "gen1 purered.SaveRAM". g1.save_name_for derives the same string from the path,
            # and the unit test pins these three literals against it.
            "purered": "gen1 purered.SaveRAM",
            "pureblue": "gen1 pureblue.SaveRAM",
            "puregreen": "gen1 puregreen.SaveRAM",
        },
        "patched": {
            "red_patched": ("red", "patch/gen1/build/slink_red.gb", "slink red.SaveRAM"),
            # The RANDOMIZED path's artifact. Built by
            # `tests/live/make_randomized_patched.py` when a UPR jar is available, and
            # deliberately a separate key: the whole question it answers is whether the
            # structural injector produces a cartridge that boots and runs the panel, which
            # a hash comparison against the clean build cannot tell you.
            "red_rand_patched": ("red", "patch/gen1/build/slink_red_randomized.gb",
                                 "slink red randomized.SaveRAM"),
            "blue_patched": ("blue", "patch/gen1/build/slink_blue.gb", "slink blue.SaveRAM"),
            # Cold-boot keys: the vanilla cartridge with no save at all, so it reaches the
            # intro rather than CONTINUE. A ROM path of None means "the vanilla dump for the
            # key before _cold" (tests/live/test_gen1_new_gates.py, tools/gen1_fixtures.py).
            "red_cold": (None, None, "Pokemon - Red Version (USA, Europe).SaveRAM"),
            "blue_cold": (None, None, "Pokemon - Blue Version (USA, Europe).SaveRAM"),
            # Yellow's cold key for the scripted host: `rom_key.rsplit("_", 1)[0]` resolves the
            # staged dump, and the saveram name above is the one BizHawk itself will write.
            "yellow_cold": (None, None, "Pokemon - Yellow Version (USA, Europe).SaveRAM"),
            # pureRGB (P3b-e): the built cartridges take the same treatment as the patched builds
            # — BizHawk has no gamedb entry for them, so the SaveRAM name is filename-derived and
            # the ROM is staged from the pinned lock (g1.PURERGB_KEYS), not from a repo-root dump.
            # The `_cold` rows are what the fixture builder drives: a previous build's save must
            # not be seeded into the next one. The bare keys boot FROM a built pure fixture.
            "purered": ("purered", None, "gen1 purered.SaveRAM"),
            "pureblue": ("pureblue", None, "gen1 pureblue.SaveRAM"),
            "puregreen": ("puregreen", None, "gen1 puregreen.SaveRAM"),
            "purered_cold": (None, None, "gen1 purered.SaveRAM"),
            "pureblue_cold": (None, None, "gen1 pureblue.SaveRAM"),
            "puregreen_cold": (None, None, "gen1 puregreen.SaveRAM"),
            # pureRGB companion overlay (M3/P4): the clean build + the SLink UPS
            # (g1.purergb_overlay_dump), admitted on its own sha1 (admission_overlay.json). A4
            # says a clean pure SaveRAM loads unchanged, so these rows reuse the clean pure
            # fixture via `base_key` below rather than shipping a fixture of their own; the
            # SaveRAM name is filename-derived same as the clean pure rows (g1.save_name_for).
            "purered_overlay": ("purered", None, "gen1 purered overlay.SaveRAM"),
            "pureblue_overlay": ("pureblue", None, "gen1 pureblue overlay.SaveRAM"),
            "puregreen_overlay": ("puregreen", None, "gen1 puregreen overlay.SaveRAM"),
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

# tests/live/test_gen1_gates.py reads this to find each patched build's ROM path. The pureRGB
# rows live here too: "patched" means "BizHawk's gamedb does not know this cartridge", which is
# exactly what a built pureRGB ROM is.
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


def named_title(rom_key: str) -> str | None:
    """The family to hand a gate whose sha1 cannot be admitted, or None to require admission.

    Only the vanilla companion-patch rows qualify: the patch adds code, it does not move WRAM, and
    vanilla's admission table does not exist yet (gen1_rby has no admission.json), so their sha1 is
    in no pack. A pureRGB row never qualifies — its pack ships admission.json, so a pure cartridge
    is admitted on its bytes or the gate refuses.
    """
    spec = GENS["gen1"]
    base = spec["patched"].get(rom_key, (None, None, None))[0]
    return base if base in spec["play"].ROMS else None


def gate_env(rom_key: str, title: str | None = None) -> dict:
    """The environment a gate runs with.

    SLINK_ROOT is how every gate finds the repo. `title` is set only for a cartridge whose sha1
    cannot be admitted: the vanilla companion-patch artifacts are vanilla-layout by construction
    (the patch adds code, it does not move WRAM), and vanilla's admission table does not exist yet,
    so the launcher names the family and the gate skips the sha1 lookup. A pureRGB build is never
    named from outside — it ships data/games/gen1_purergb/admission.json, so it has to be admitted
    on its bytes.
    """
    env = dict(os.environ, SLINK_ROOT=REPO.replace("\\", "/"))
    if title:
        env["SLINK_GATE_TITLE"] = title
    return env


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
    # play.fixture_path, not a second copy of the naming rule: an overlay key resolves to the
    # CLEAN pure fixture (A4), which this inlined f-string would miss.
    fixture = play.fixture_path(rom_key, target)
    if not os.path.exists(fixture):
        raise FileNotFoundError(
            f"missing fixture {os.path.relpath(fixture, REPO)} — build it with "
            f"`{_rebuild_command(play.__name__, rom_key, target)}`")
    target_dir = dest_dir or SAVERAM_DIR
    os.makedirs(target_dir, exist_ok=True)
    dst = os.path.join(target_dir, spec["saveram_names"][rom_key])
    shutil.copyfile(fixture, dst)
    return dst


def run_gate(script, rom_key="red", target="town", timeout=240, quiet=False):
    """Run one gate. Returns (passed, result_path, text)."""
    if not os.path.exists(EMUHAWK):
        raise FileNotFoundError(f"EmuHawk not found at {EMUHAWK} (set $SLINK_EMUHAWK)")
    spec = GENS[gen_for(rom_key)]
    play = spec["play"]

    if rom_key in spec["patched"]:
        base_key, rom_rel, saveram_name = spec["patched"][rom_key]
        if rom_rel is None:
            # An overlay key stages ITS OWN cartridge (g1.purergb_overlay_dump applies the UPS)
            # — rsplit("_", 1) would strip "_overlay" and stage the clean build instead. Every
            # other None-rom_rel row (the bare pure keys, the "*_cold" rows) IS the stripped
            # form: "purered" unchanged, "purered_cold" -> "purered".
            stage_key = rom_key if g1.is_purergb_overlay(rom_key) else rom_key.rsplit("_", 1)[0]
            rom_rel = play.staged_rom(stage_key)
        if not os.path.exists(os.path.join(REPO, rom_rel)):
            how = ("build the pinned pureRGB source (see data/purergb_sources.lock.json)"
                   if g1.is_purergb(rom_key) else "python patch/gen1/tools/build.py")
            raise FileNotFoundError(f"{rom_rel} missing — build it with `{how}`")
        os.makedirs(SAVERAM_DIR, exist_ok=True)
        if base_key is None:
            # Cold boot. A leftover save from an earlier run would put the title screen on
            # CONTINUE and quietly change what the gate is booting into.
            stale = os.path.join(SAVERAM_DIR, saveram_name)
            if os.path.exists(stale):
                os.remove(stale)
        else:
            fixture = os.path.join(play.FIXTURES, f"{base_key}_{target}.SaveRAM")
            if not os.path.exists(fixture):
                raise FileNotFoundError(f"missing fixture {os.path.relpath(fixture, REPO)}")
            shutil.copyfile(fixture, os.path.join(SAVERAM_DIR, saveram_name))
    else:
        rom_rel = play.staged_rom(rom_key)
        seed_saveram(rom_key, target)
    os.makedirs(BUILD, exist_ok=True)

    result = _result_path_for(script)
    if result and os.path.exists(result):
        os.remove(result)          # a leftover verdict must never be read as this run's

    tag = os.path.splitext(os.path.basename(script))[0]
    cfg_rel = f"patch/build/gate_cfg_{tag}_{rom_key}.ini"
    if os.path.exists(BIZHAWK_CONFIG):
        write_run_config(BIZHAWK_CONFIG, os.path.join(REPO, cfg_rel), purergb=g1.is_purergb(rom_key))

    env = gate_env(rom_key, named_title(rom_key))
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
    ap.add_argument("script", help="path to the gate, e.g. lua/tests/test_gen1_inspect_gate.lua")
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
