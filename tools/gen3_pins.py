#!/usr/bin/env python3
"""Print a Markdown table of hashes for the Gen 3 plan's pinned artifacts.

Rows: installed BizHawk tools, RR base ROM, patched build, companion UPS patch,
clean FR/LG dumps (if found).

Usage: python tools/gen3_pins.py [--json]
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).parent.parent
BIZHAWK_HOME = Path("E:/Howard/Bizhawk")
RR_BASE_PATHS = [
    Path("E:/Google Drive/SLink/Pokemon - Radical Red.gba"),
]
PATCHED_RR = REPO / "patch" / "build" / "slink_RR.gba"
UPS_PATCH = REPO / "patch" / "dist" / "SLink-RR.ups"
# Likely FR/LG locations (not exhaustive; no recursive search to avoid timeouts)
FR_SEARCH_PATHS = [
    Path("E:/Google Drive/SLink/Pokemon - Fire Red.gba"),
    Path("E:/Howard/GBA/Pokemon - Fire Red.gba"),
]
LG_SEARCH_PATHS = [
    Path("E:/Google Drive/SLink/Pokemon - Leaf Green.gba"),
    Path("E:/Howard/GBA/Pokemon - Leaf Green.gba"),
]


def hash_file(path, algs=None):
    """Return dict of {algo: hexdigest} for the file, or None if missing."""
    if algs is None:
        algs = ["sha256"]
    if not Path(path).exists():
        return None
    result = {}
    for alg in algs:
        h = hashlib.new(alg)
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        result[alg] = h.hexdigest()
    return result


def bizhawk_version():
    """Try to extract version from EmuHawk.exe."""
    exe = BIZHAWK_HOME / "EmuHawk.exe"
    if not exe.exists():
        return "unknown"
    try:
        with open(exe, "rb") as f:
            hits = re.findall(rb"2\.\d+\.\d+", f.read())
        versions = {h.decode() for h in hits}
        if versions:
            return max(versions, key=lambda v: [int(x) for x in v.split(".")])
    except Exception:
        pass
    return "unknown"


def find_rom(search_paths):
    """Search for a ROM file in specific paths; return first found or None."""
    for path in search_paths:
        if path.exists() and path.is_file():
            return path
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Output JSON instead of Markdown")
    args = parser.parse_args()

    pins = {}

    # BizHawk installed
    exe = BIZHAWK_HOME / "EmuHawk.exe"
    if exe.exists():
        h = hash_file(exe, ["sha256"])
        pins["bizhawk_emuawk.exe"] = {
            "sha256": h["sha256"] if h else "MISSING",
            "version": bizhawk_version(),
        }
    else:
        pins["bizhawk_emuawk.exe"] = {"sha256": "MISSING", "version": "unknown"}

    # mgba.dll
    dll = BIZHAWK_HOME / "dll" / "mgba.dll"
    if dll.exists():
        h = hash_file(dll, ["sha256"])
        pins["bizhawk_mgba.dll"] = {"sha256": h["sha256"] if h else "MISSING"}
    else:
        pins["bizhawk_mgba.dll"] = {"sha256": "MISSING"}

    # BizHawk.Emulation.Cores.dll
    cores_dll = BIZHAWK_HOME / "dll" / "BizHawk.Emulation.Cores.dll"
    if cores_dll.exists():
        h = hash_file(cores_dll, ["sha256"])
        pins["bizhawk_cores.dll"] = {"sha256": h["sha256"] if h else "MISSING"}
    else:
        pins["bizhawk_cores.dll"] = {"sha256": "MISSING"}

    # RR base ROM
    rr_base = None
    for path in RR_BASE_PATHS:
        if path.exists():
            rr_base = path
            break
    if rr_base:
        h = hash_file(rr_base, ["md5", "sha1"])
        pins["rr_base.gba"] = h if h else {"md5": "MISSING", "sha1": "MISSING"}
    else:
        pins["rr_base.gba"] = {
            "md5": "MISSING",
            "sha1": "MISSING",
            "paths_checked": [str(p) for p in RR_BASE_PATHS],
        }

    # Patched RR build
    if PATCHED_RR.exists():
        h = hash_file(PATCHED_RR, ["md5", "sha1"])
        pins["slink_RR.gba"] = h if h else {"md5": "MISSING", "sha1": "MISSING"}
    else:
        pins["slink_RR.gba"] = {
            "md5": "MISSING",
            "sha1": "MISSING",
            "path": str(PATCHED_RR),
        }

    # FireRed and LeafGreen
    fr_rom = find_rom(FR_SEARCH_PATHS)
    if fr_rom:
        h = hash_file(fr_rom, ["md5", "sha1"])
        pins["firered.gba"] = h if h else {"md5": "MISSING", "sha1": "MISSING"}
    else:
        pins["firered.gba"] = {
            "md5": "MISSING",
            "sha1": "MISSING",
            "paths_checked": [str(p) for p in FR_SEARCH_PATHS],
        }

    lg_rom = find_rom(LG_SEARCH_PATHS)
    if lg_rom:
        h = hash_file(lg_rom, ["md5", "sha1"])
        pins["leafgreen.gba"] = h if h else {"md5": "MISSING", "sha1": "MISSING"}
    else:
        pins["leafgreen.gba"] = {
            "md5": "MISSING",
            "sha1": "MISSING",
            "paths_checked": [str(p) for p in LG_SEARCH_PATHS],
        }

    # UPS patch
    if UPS_PATCH.exists():
        h = hash_file(UPS_PATCH, ["sha256"])
        pins["slink_rr.ups"] = {"sha256": h["sha256"] if h else "MISSING"}
    else:
        pins["slink_rr.ups"] = {
            "sha256": "MISSING",
            "path": str(UPS_PATCH),
        }

    if args.json:
        print(json.dumps(pins, indent=2))
    else:
        print_markdown(pins)


def print_markdown(pins):
    """Print a Markdown table of the pins."""
    print("| Artifact | Hash Type | Hash | Notes |")
    print("|---|---|---|---|")
    for name, hashes in pins.items():
        if isinstance(hashes, dict):
            for alg in ["sha256", "md5", "sha1", "version"]:
                if alg in hashes:
                    value = hashes[alg]
                    notes = ""
                    if "paths_checked" in hashes:
                        notes = f"Checked: {', '.join(hashes['paths_checked'][:1])}"
                    elif "path" in hashes:
                        notes = f"Path: {hashes['path']}"
                    elif "note" in hashes:
                        notes = hashes["note"]
                    print(f"| {name} | {alg} | {value} | {notes} |")


if __name__ == "__main__":
    main()
