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
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import MappingProxyType

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import gen1_playthrough as g1  # noqa: E402
from gen2_source_data import load_context as load_gen2_context  # noqa: E402
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
}

# Exact clean title identities. Crystal 1.1 remains build-only. SaveRAM names are
# verified against the configured emulator's SHA1 gamedb row before every launch.
_GEN2_IDENTITIES = {
    "crystal": ("pokecrystal", "f4cd194bdee0d04ca4eac29e09b8e4e9d818c133", "Pokemon - Crystal Version (USA, Europe).SaveRAM"),
    "gold": ("pokegold", "d8b8a3600a465308c9953dfa04f0081c05bdcb94", "Pokemon - Gold Version (USA, Europe).SaveRAM"),
    "silver": ("pokesilver", "49b163f7e57702bc939d642a18f591de55d92dae", "Pokemon - Silver Version (USA, Europe).SaveRAM"),
}


def describe_gen2(rom_key: str):
    """Immutable metadata only; run_gate separately verifies every actual input."""
    cold = isinstance(rom_key, str) and rom_key.endswith("_cold")
    title = rom_key[:-5] if cold else rom_key
    if title not in _GEN2_IDENTITIES:
        raise ValueError(f"unregistered Gen 2 gate key: {rom_key!r}")
    artifact, sha1, name = _GEN2_IDENTITIES[title]
    return MappingProxyType({"title": title, "artifact": artifact, "rom_sha1": sha1,
                             "core_mode": "CGB", "saveram_name": name, "cold": cold})


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
            # A RANDOMIZED PureRed (tests/live/test_gen1_rand_gates.py): the UPR fork's output,
            # copied under this path by the test itself, cold-booted (NEW GAME) and admitted by
            # the pack anchors (kind rand) -- its sha1 is in no table by construction.
            "purered_rand_cold": (None, "patch/build/gen1_purered_rand.gbc", "gen1 purered rand.SaveRAM"),
        },
    },
    "gen2": {
        "descriptors": {key: describe_gen2(key) for title in _GEN2_IDENTITIES for key in (title, title + "_cold")},
        "saveram_names": {title: describe_gen2(title)["saveram_name"] for title in _GEN2_IDENTITIES},
        "patched": {},
    },
}

# rom key -> generation. Built rather than written out, so adding a ROM to a GENS entry is
# enough. A duplicate key across generations would make `--rom` ambiguous, so it is an error
# rather than a last-one-wins.
ROM_TO_GEN = {}
for _gen, _spec in GENS.items():
    _keys = list(_spec["descriptors"]) if "descriptors" in _spec else list(_spec["play"].ROMS) + list(_spec["patched"])
    for _key in _keys:
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
    if gen_for(rom_key) == "gen2":
        raise ValueError("Gen 2 has no implicit fixture staging; run_gate requires an explicit isolated directory and candidate")
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


def _gen2_plan(rom_key, saveram_dir, fixture_path, speed_percent):
    """Validate a Gen 2 launch plan without creating, copying or deleting files."""
    descriptor = dict(GENS["gen2"]["descriptors"].get(rom_key, {}))
    expected = dict(describe_gen2(rom_key))
    if descriptor != expected or descriptor.get("core_mode") != "CGB" or type(descriptor.get("cold")) is not bool:
        raise ValueError("missing or mismatched explicit Gen 2 descriptor")
    if saveram_dir is None:
        raise ValueError("Gen 2 requires an explicit isolated SaveRAM directory")
    directory = Path(saveram_dir).resolve()
    roots = (Path(REPO).resolve() / ".cache/gen2-fixtures", Path(BUILD).resolve())
    if directory == Path(SAVERAM_DIR).resolve() or not any(directory.is_relative_to(base) and directory != base for base in roots):
        raise ValueError("Gen 2 SaveRAM directory must be an isolated attempt directory under .cache/gen2-fixtures or BUILD")
    if type(speed_percent) is not int or speed_percent not in (100, 300):
        raise ValueError("Gen 2 speed must be explicitly 100 or 300 percent")
    if descriptor["cold"]:
        if fixture_path is not None:
            raise ValueError("cold Gen 2 gate cannot seed a fixture")
        fixture = None
    else:
        if fixture_path is None or not Path(fixture_path).is_file():
            raise ValueError("warm Gen 2 gate requires an explicit existing candidate fixture_path")
        fixture = Path(fixture_path).resolve()
        if fixture == directory / descriptor["saveram_name"]:
            raise ValueError("candidate fixture and mutable emulator save must be separate")
    ctx = load_gen2_context(descriptor["title"], root=Path(REPO))
    if ctx.artifact != descriptor["artifact"] or hashlib.sha1(ctx.rom).hexdigest() != descriptor["rom_sha1"]:
        raise ValueError("Gen 2 selected artifact/hash binding disagrees")
    rom = (ctx.source_dir / ctx.lock["outputs"][ctx.artifact]["filename"]).resolve()
    if not rom.is_relative_to(Path(REPO).resolve()) or hashlib.sha1(rom.read_bytes()).hexdigest() != descriptor["rom_sha1"]:
        raise ValueError("Gen 2 actual ROM differs from the selected descriptor")
    database = Path(EMUHAWK).resolve().parent / "gamedb/gamedb_gbc.txt"
    rows = [line.split("\t") for line in database.read_text(encoding="utf-8-sig").splitlines()
            if line.split("\t", 1)[0].lower() == descriptor["rom_sha1"]]
    if (len(rows) != 1 or len(rows[0]) < 4 or rows[0][1] != "G" or rows[0][3] != "GBC"
            or rows[0][2] + ".SaveRAM" != descriptor["saveram_name"]):
        raise ValueError("Gen 2 SHA1/name/CGB gamedb binding missing or contradictory")
    config = json.loads(Path(BIZHAWK_CONFIG).read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or not any(row.get("Type") == "Save RAM" and row.get("System") in g1._GB_PATH_SYSTEMS
        for row in (config.get("PathEntries") or {}).get("Paths", [])):
        raise ValueError("Gen 2 requires a parseable config with an explicit GB Save RAM path entry")
    return {**descriptor, "rom": rom, "directory": directory, "fixture": fixture, "speed_percent": speed_percent}


def _gen2_config(plan, path):
    # Existing GB config machinery; its legacy keyword selects only the CGB pins.
    write_run_config(BIZHAWK_CONFIG, str(path), saveram_dir=str(plan["directory"]), purergb=True)
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    config.update(SpeedPercent=plan["speed_percent"], SpeedPercentAlternate=plan["speed_percent"],
                  ClockThrottle=True, Unthrottled=False)
    sync = config["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"]
    if sync.get("ConsoleMode") != 2 or config.get("GbAsSgb") is not False or sync.get("RealTimeRTC") is not False:
        raise ValueError("Gen 2 generated config did not establish CGB/RTC settings")
    paths = (config.get("PathEntries") or {}).get("Paths", [])
    if not all(Path(row["Path"]).resolve() == plan["directory"] for row in paths
               if row.get("Type") == "Save RAM" and row.get("System") in g1._GB_PATH_SYSTEMS):
        raise ValueError("Gen 2 config SaveRAM redirection disagrees")
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def run_gate(script, rom_key="red", target="town", timeout=240, quiet=False, *,
             saveram_dir=None, fixture_path=None, speed_percent=None, env_overrides=None):
    """Run one gate. Returns (passed, result_path, text)."""
    if type(timeout) not in (int, float) or not 0 < timeout <= 86400:
        raise ValueError("gate timeout must be positive and bounded")
    protected = {"SLINK_ROOT", "SLINK_GATE_TITLE", "SLINK_GEN2_TITLE", "SLINK_GEN2_ROM_SHA1",
                 "SLINK_GEN2_CORE_MODE", "SLINK_GEN2_COLD", "SLINK_GEN2_SAVERAM_DIR", "SLINK_GEN2_SAVERAM_NAME"}
    overrides = dict(env_overrides or {})
    for key, value in overrides.items():
        if (not isinstance(key, str) or re.fullmatch(r"SLINK_[A-Z0-9_]+", key) is None or key in protected
                or not isinstance(value, str) or "\x00" in value):
            raise ValueError("gate environment overrides must be textual SLINK_* values outside protected bindings")
    if not os.path.exists(EMUHAWK):
        raise FileNotFoundError(f"EmuHawk not found at {EMUHAWK} (set $SLINK_EMUHAWK)")
    generation = gen_for(rom_key)
    spec = GENS[generation]
    plan = _gen2_plan(rom_key, saveram_dir, fixture_path, speed_percent) if generation == "gen2" else None
    play = spec.get("play")
    if plan and _result_path_for(script) is None:
        raise ValueError("Gen 2 gate must declare its exact terminal result path")

    if plan:
        rom_rel = plan["rom"].relative_to(Path(REPO).resolve()).as_posix()
        plan["directory"].mkdir(parents=True, exist_ok=True)
        destination = plan["directory"] / plan["saveram_name"]
        if plan["cold"]:
            destination.unlink(missing_ok=True)
        else:
            shutil.copyfile(plan["fixture"], destination)
    elif rom_key in spec["patched"]:
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
    if plan:
        _gen2_config(plan, Path(REPO) / cfg_rel)
    elif os.path.exists(BIZHAWK_CONFIG):
        write_run_config(BIZHAWK_CONFIG, os.path.join(REPO, cfg_rel), purergb=g1.is_purergb(rom_key))

    env = gate_env(rom_key, named_title(rom_key))
    env.update(overrides)
    if plan:
        env.pop("SLINK_GATE_TITLE", None)
        env.update(SLINK_GEN2_TITLE=plan["title"], SLINK_GEN2_ROM_SHA1=plan["rom_sha1"],
                   SLINK_GEN2_CORE_MODE=plan["core_mode"], SLINK_GEN2_COLD="1" if plan["cold"] else "0",
                   SLINK_GEN2_SAVERAM_DIR=str(plan["directory"]), SLINK_GEN2_SAVERAM_NAME=plan["saveram_name"])
        if hashlib.sha1(plan["rom"].read_bytes()).hexdigest() != plan["rom_sha1"]:
            raise ValueError("Gen 2 ROM changed before launch")
    cmd = [EMUHAWK, f"--lua={script}"]
    if os.path.exists(os.path.join(REPO, cfg_rel)):
        cmd.append(f"--config={cfg_rel}")
    cmd.append(rom_rel)

    if not quiet:
        print(f"[gate] {tag} on {rom_key}/{target} …", file=sys.stderr)
    proc = subprocess.Popen(cmd, cwd=REPO, env=env)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(1)
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=10)
        return False, result, f"timed out after {timeout}s"

    text = ""
    if result and os.path.exists(result):
        with open(result, encoding="utf-8", errors="replace") as f:
            text = f.read()
    verdict = next((ln for ln in reversed(text.splitlines())
                    if ln.startswith("RESULT:")), "")
    return proc.poll() == 0 and re.match(r"^RESULT: PASS(?:\s|$)", verdict) is not None, result, text


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", help="path to the gate, e.g. lua/tests/test_gen1_inspect_gate.lua")
    ap.add_argument("--rom", choices=sorted(ROM_TO_GEN), default="red")
    ap.add_argument("--target", choices=("town", "battle"), default="town")
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--saveram-dir", help="explicit isolated Gen 2 attempt SaveRAM directory")
    ap.add_argument("--fixture-path", help="explicit Gen 2 warm-boot candidate; forbidden for cold boot")
    ap.add_argument("--speed-percent", type=int, choices=(100, 300), help="explicit Gen 2 route/qualification speed")
    args = ap.parse_args()

    passed, path, text = run_gate(args.script, args.rom, args.target, args.timeout,
                                saveram_dir=args.saveram_dir, fixture_path=args.fixture_path,
                                speed_percent=args.speed_percent)
    print(text.rstrip())
    print(f"\n[gate] {'PASS' if passed else 'FAIL'}  ({path})", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
