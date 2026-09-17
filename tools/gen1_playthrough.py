#!/usr/bin/env python3
"""gen1_playthrough.py — the shared launch machinery for the Gen 1 battery saves.

WHAT IS HERE: the paths and rules every Gen 1 harness shares — where the ROM dumps and the
fixtures live, how a ROM is staged to a space-free name, how BizHawk's config is copied with
the window/sound/RTC pins and a per-instance SaveRAM directory, and the shared constants
(run_gb_gate.py:37-44, gen2_playthrough.py:44-50 and the e2e/live wrappers import these).

WHAT IS NOT HERE: the fixture BUILDER. The old single-instance driver
(lua/tests/gen1_playthrough.lua) and its CLI went with the old client (deletion step 3); the
Gen 1 fixtures are built by tools/gen1_fixtures.py from the new client's scripted pipeline:

    python tools/gen1_fixtures.py red town
    python tools/gen1_fixtures.py red battle

WHY THOSE FIXTURES ARE COMMITTED: a .SaveRAM is plain SRAM content, NOT version-locked the
way a BizHawk savestate is, so the builder runs rarely rather than on every CI run.

Launch rules match run_gate.py / e2e_duo.py: cwd = repo root with RELATIVE EmuHawk arg
paths, because absolute paths containing the "Google Drive" space break BizHawk's CLI
parser. Absolute paths are fine inside Lua.
"""
import json
import os
import shutil

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
    # $type is what BizHawk deserialises these by, and it is only already present if this
    # config has loaded a GB core before. On a fresh one both setdefaults above create bare
    # dicts, BizHawk discards the untagged entry, and the pin silently does nothing — which
    # is the failure the paragraph above claims to have removed. setdefault so an existing
    # entry keeps whatever tag BizHawk itself wrote.
    sync.setdefault("$type", "BizHawk.Emulation.Cores.Nintendo.Gameboy.Gameboy"
                             "+GambatteSyncSettings, BizHawk.Emulation.Cores")
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
