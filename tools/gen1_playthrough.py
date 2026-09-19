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
import hashlib
import json
import os
import shutil
import sys

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

# ── pureRGB (P3b-e) ────────────────────────────────────────────────────────────────────────────
# The three pureRGB titles are NOT files at the repo root: they are the BUILT cartridges, whose
# names and sha1s are pinned in data/purergb_sources.lock.json. They resolve from
# $SLINK_PURERGB_ROMS first, then .cache/purergb/. A key is refused unless the file's sha1 equals
# the lock's output — a stale build, or a randomizer-patched .gbc, would otherwise be staged as
# the canonical cartridge and every downstream fact would be read from a different game.
PURERGB_ROMS = os.environ.get("SLINK_PURERGB_ROMS") or os.path.join(REPO, ".cache", "purergb")
PURERGB_LOCK = os.path.join(REPO, "data", "purergb_sources.lock.json")
# rom key -> the lock's output name. The key is the title the client admits the build as
# (data/games/gen1_purergb/admission.json), so harness and client spell the foundation the same way.
PURERGB_KEYS = {"purered": "pokered", "pureblue": "pokeblue", "puregreen": "pokegreen"}

# ── pureRGB companion overlay (M3/P4) ──────────────────────────────────────────────────────────
# The overlay cartridge is the clean pure build + patch/dist/SLink-Pure{Red,Blue,Green}.ups
# (tools/build_purergb_overlay.py); the harness never needs the full RGBDS toolchain to run a
# gate against it, only the applier in patch/tools/make_ups.py and the admitted sha1 in
# data/games/gen1_purergb/admission_overlay.json (A4: overlay == clean + UPS, nothing else).
OVERLAY_SUFFIX = "_overlay"
PURERGB_ADMISSION_OVERLAY = os.path.join(REPO, "data", "games", "gen1_purergb", "admission_overlay.json")
# where the applied overlay bytes are cached, keyed by rom key (mirrors PURERGB_ROMS' role for
# the clean builds: a place staged_rom's copy step reads FROM, never the final launch path).
PURERGB_OVERLAY_STAGE = os.path.join(REPO, ".cache", "purergb-overlay-staged")


def is_purergb_overlay(rom_key: str) -> bool:
    return rom_key.endswith(OVERLAY_SUFFIX) and rom_key[: -len(OVERLAY_SUFFIX)] in PURERGB_KEYS


def is_purergb(rom_key: str) -> bool:
    return rom_key in PURERGB_KEYS or is_purergb_overlay(rom_key)


def _overlay_admission_row(base_key: str) -> tuple:
    """(sha1, entry) from admission_overlay.json whose `title` is the clean rom key."""
    with open(PURERGB_ADMISSION_OVERLAY, encoding="utf-8") as f:
        table = json.load(f)
    for sha1, entry in table.items():
        if entry["title"] == base_key:
            return sha1, entry
    raise KeyError(f"no overlay admission row for {base_key!r} in {PURERGB_ADMISSION_OVERLAY}")


def purergb_overlay_dump(rom_key: str) -> str:
    """Apply the SLink UPS to the sha1-verified clean pureRGB build and assert the result
    against admission_overlay.json (PLAN M3 A4: the overlay is the clean build + the UPS,
    nothing else — no RGBDS toolchain needed here). Cached under PURERGB_OVERLAY_STAGE;
    rebuilt when the clean ROM or the UPS is newer than the cache.
    """
    base_key = rom_key[: -len(OVERLAY_SUFFIX)]
    clean_path = purergb_dump(base_key)
    want_sha1, entry = _overlay_admission_row(base_key)
    ups_path = os.path.join(REPO, entry["ups"])
    ext = os.path.splitext(clean_path)[1]
    cache = os.path.join(PURERGB_OVERLAY_STAGE, f"{rom_key}{ext}")
    stale = (not os.path.exists(cache)
             or os.path.getmtime(cache) < os.path.getmtime(clean_path)
             or os.path.getmtime(cache) < os.path.getmtime(ups_path))
    if stale:
        sys.path.insert(0, os.path.join(REPO, "patch", "tools"))
        from make_ups import ups_apply  # local import: keeps this module dependency-free otherwise
        with open(clean_path, "rb") as f:
            source = f.read()
        with open(ups_path, "rb") as f:
            patch = f.read()
        overlay_bytes = ups_apply(source, patch)
        os.makedirs(PURERGB_OVERLAY_STAGE, exist_ok=True)
        with open(cache, "wb") as f:
            f.write(overlay_bytes)
    with open(cache, "rb") as f:
        got = hashlib.sha1(f.read()).hexdigest()
    if got != want_sha1:
        raise ValueError(
            f"{cache} is not the admitted overlay for {rom_key}: sha1 {got}, expected "
            f"{want_sha1} ({PURERGB_ADMISSION_OVERLAY})")
    return cache


def purergb_dump(rom_key: str) -> str:
    """Absolute path of a pinned pureRGB build (sha1-checked)."""
    with open(PURERGB_LOCK, encoding="utf-8") as f:
        want = json.load(f)["outputs"][PURERGB_KEYS[rom_key]]
    path = os.path.join(PURERGB_ROMS, want["filename"])
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"pureRGB {rom_key} is not at {path} — build it (make {want['filename']} in the pinned "
            f"checkout) or point $SLINK_PURERGB_ROMS at a directory holding it")
    with open(path, "rb") as f:
        got = hashlib.sha1(f.read()).hexdigest()
    if got != want["sha1"]:
        raise ValueError(
            f"{path} is not the pinned {rom_key} build: sha1 {got}, expected {want['sha1']} "
            f"(data/purergb_sources.lock.json outputs.{PURERGB_KEYS[rom_key]}) — a rebuilt or "
            f"randomized cartridge must not be run as the canonical one")
    return path


def dump_path(rom_key: str) -> str:
    """Absolute path of a key's cartridge dump (vanilla keys are repo-root filenames)."""
    if is_purergb_overlay(rom_key):
        return purergb_overlay_dump(rom_key)
    if is_purergb(rom_key):
        return purergb_dump(rom_key)
    return os.path.join(REPO, ROMS[rom_key])


def save_name_for(rom_rel: str) -> str:
    """The SaveRAM filename BizHawk derives for a ROM whose hash is not in its gamedb.

    BizHawk looks the cartridge up by hash; an unknown hash falls back to the ROM's FILENAME with
    the extension dropped and underscores turned into spaces. Measured on this machine's
    Gameboy/SaveRAM directory: patch/build/gen1_red_ap.gb is "gen1 red ap.SaveRAM" and
    patch/gen1/build/slink_blue.gb is "slink blue.SaveRAM" — the two forms run_gb_gate.GENS
    already carries as literals, which the unit test pins against this function. Known hashes
    (every vanilla cartridge) use the gamedb name instead, so this applies only to the patched and
    pureRGB builds.
    """
    base = os.path.splitext(os.path.basename(rom_rel))[0]
    return base.replace("_", " ") + ".SaveRAM"


def dump_keys() -> tuple:
    """Every rom key that has a cartridge: vanilla three, pureRGB three, pureRGB-overlay three."""
    return tuple(ROMS) + tuple(PURERGB_KEYS) + tuple(k + OVERLAY_SUFFIX for k in PURERGB_KEYS)


def staged_rom(rom_key: str) -> str:
    """Copy the ROM to a space-free relative path and return it (relative to REPO)."""
    src = dump_path(rom_key)
    if not os.path.exists(src):
        raise FileNotFoundError(f"ROM not found: {src}")
    ext = os.path.splitext(src)[1]
    rel = f"patch/build/gen1_{rom_key}{ext}"
    dst = os.path.join(REPO, rel)
    os.makedirs(BUILD, exist_ok=True)
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        shutil.copyfile(src, dst)
    return rel


def fixture_path(rom_key: str, target: str) -> str:
    """The committed SaveRAM fixture for a rom key. An overlay key has none of its own — A4 says
    a clean pure SaveRAM loads on the overlay build unchanged, so it resolves to the clean pure
    fixture (PLAN M3 P4)."""
    if is_purergb_overlay(rom_key):
        rom_key = rom_key[: -len(OVERLAY_SUFFIX)]
    return os.path.join(FIXTURES, f"{rom_key}_{target}.SaveRAM")


# Where to park the emulator window, and whether to make noise. These runs are long and
# unattended, so by default they go to a SECOND MONITOR with sound off rather than stealing
# the primary display and blasting the Pokemon theme. Override with SLINK_EMU_WINDOW="x,y"
# (or "primary" to leave the position alone) and SLINK_EMU_SOUND=1.
EMU_WINDOW = os.environ.get("SLINK_EMU_WINDOW", "1200,-1300")
EMU_SOUND = os.environ.get("SLINK_EMU_SOUND", "0") == "1"


def write_run_config(src: str, dst: str, saveram_dir: str | None = None,
                     purergb: bool = False) -> None:
    """Copy BizHawk's config, muted and positioned, without touching the user's own.

    config.ini is JSON with a BOM. Unknown-key edits are harmless, but SaveWindowPosition
    must be turned off too — otherwise BizHawk writes the window back on exit and the next
    run reads the moved position from OUR copy rather than the requested one.

    `purergb` pins the run to GBC (PLAN A15): a pureRGB cartridge is a GBC cartridge, and the
    client reads hGBC — its 2x-speed and palette-fade paths are CGB-only. ConsoleMode is
    Gambatte's sync setting (GambatteSyncSettings.ConsoleModeType: Auto 0, GB 1, GBC 2, GBA 3,
    SGB2 4, BizHawk 2.11.1 Gambatte.ISettable.cs) and GbAsSgb is the client's own top-level
    switch: GBC + not-SGB.

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

    if purergb:
        # Values, not names: BizHawk deserialises both as numbers/bools (its own config on this
        # machine reads ConsoleMode 0, the Auto default this replaces for pure runs).
        sync["ConsoleMode"] = 2
        cfg["GbAsSgb"] = False

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
