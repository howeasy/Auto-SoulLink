#!/usr/bin/env python3
"""gen1_ap_rom.py — build the Archipelago Red/Blue ROMs the AP gate runs against.

    python tools/gen1_ap_rom.py            # build both, skip what already exists
    python tools/gen1_ap_rom.py --force
    python tools/gen1_ap_rom.py --status

NO ARCHIPELAGO SEED IS NEEDED. `pokemon_rb.apworld` ships `basepatch_{red,blue}.bsdiff4` —
the compiled Alchav fork as a delta against the vanilla cartridge. Applying it is the whole
job: that ROM already has the fork's relocated WRAM (wCurMap +216, wEnemyMons -18, the box
block +11), which is the only thing SLink's `red_ap` profile cares about. Generate.py, a
YAML, a MultiServer and a .apred patch would add item placements on top and change nothing
we read. The unrandomized seed slot decodes to "(NOT RANDOMIZED)", which is still text, so
gen1_rby.detect_archipelago() fires on it exactly as it would on a real seed.

Output: patch/build/gen1_{red,blue}_ap.gb   (gitignored, like every other build artifact)
"""
import argparse
import hashlib
import os
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(REPO, "patch", "build")

# Where a stock Archipelago install keeps its worlds. $SLINK_AP_APWORLD overrides.
APWORLD_CANDIDATES = (
    os.environ.get("SLINK_AP_APWORLD", ""),
    r"C:\ProgramData\Archipelago\lib\worlds\pokemon_rb.apworld",
    r"C:\ProgramData\Archipelago\custom_worlds\pokemon_rb.apworld",
    os.path.expanduser("~/Archipelago/lib/worlds/pokemon_rb.apworld"),
    os.path.expanduser("~/Archipelago/custom_worlds/pokemon_rb.apworld"),
)

# base ROM (repo root, gitignored) -> output name
BUILDS = {
    "red_ap": ("Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb",
               "basepatch_red.bsdiff4", "gen1_red_ap.gb"),
    "blue_ap": ("Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb",
                "basepatch_blue.bsdiff4", "gen1_blue_ap.gb"),
}


def find_apworld():
    for p in APWORLD_CANDIDATES:
        if p and os.path.exists(p):
            return p
    return None


def out_path(key):
    return os.path.join(BUILD, BUILDS[key][2])


def build(key, apworld, *, force=False):
    """Returns (ok, message)."""
    base_name, patch_name, _ = BUILDS[key]
    dst = out_path(key)
    if os.path.exists(dst) and not force:
        return True, "already built (use --force)"
    base_path = os.path.join(REPO, base_name)
    if not os.path.exists(base_path):
        return False, f"{base_name} not present (ROMs are gitignored)"
    try:
        import bsdiff4
    except ImportError:
        return False, "pip install bsdiff4"

    with open(base_path, "rb") as f:
        base = f.read()
    with zipfile.ZipFile(apworld) as z:
        patch = z.read(f"pokemon_rb/{patch_name}")
    try:
        rom = bsdiff4.patch(base, patch)
    except Exception as exc:                       # noqa: BLE001 - report, don't crash
        return False, f"bsdiff4 refused the base ROM ({exc}) — wrong dump?"

    # The fork keeps the vanilla ROM title, so a wrong output is not obvious downstream.
    # Check the one byte range that MUST have changed: the AP seed slot.
    if rom[0x5F22:0x5F32] == base[0x5F22:0x5F32]:
        return False, "seed slot unchanged — this patch did not produce an AP build"
    os.makedirs(BUILD, exist_ok=True)
    with open(dst, "wb") as f:
        f.write(rom)
    return True, f"{os.path.relpath(dst, REPO)}  md5={hashlib.md5(rom).hexdigest()}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", choices=sorted(BUILDS), help="only this build")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    if args.status:
        for key in BUILDS:
            p = out_path(key)
            print(f"{os.path.relpath(p, REPO):34s} "
                  f"{'ok' if os.path.exists(p) else 'MISSING'}")
        print(f"apworld: {find_apworld() or 'NOT FOUND'}")
        return 0

    apworld = find_apworld()
    if not apworld:
        print("pokemon_rb.apworld not found. Install Archipelago, or set "
              "$SLINK_AP_APWORLD to the .apworld path.", file=sys.stderr)
        return 2

    rc = 0
    for key in ([args.rom] if args.rom else list(BUILDS)):
        ok, msg = build(key, apworld, force=args.force)
        print(f"[ap-rom] {key}: {'OK  ' if ok else 'FAIL'} {msg}", file=sys.stderr)
        rc |= 0 if ok else 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
