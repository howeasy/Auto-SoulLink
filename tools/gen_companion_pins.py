#!/usr/bin/env python3
"""Fill the vanilla Red/Blue entries of patch/dist/companion_pins.json from the committed UPS patches.

    python tools/gen_companion_pins.py            # rewrite rb-red / rb-blue
    python tools/gen_companion_pins.py --check    # exit 1 if the file has drifted from the UPS files

Each entry is derived the same way a player's browser derives it: apply patch/dist/SLink-RB-<Title>.ups to the clean dump,
then take the exact md5 (what server/patcher.py shows the player), the version printed on the main menu (decoded from the
fixed-width field), and the canonical sha1 -- the sha1 with that field and the Game Boy global checksum zeroed
(patch/tools/rom_identity.py), which is what qualification evidence is keyed on. The "rr" entry belongs to the Gen 3
builder and is never touched.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("patch/tools", "patch/gen1/tools"):
    sys.path.insert(0, str(ROOT / sub))

import companion_pins  # noqa: E402
import make_ups  # noqa: E402
import manifest  # noqa: E402
import rom_identity  # noqa: E402
import title_screen  # noqa: E402

SLUGS = {"rb-red": ("red", "SLink-RB-Red.ups"), "rb-blue": ("blue", "SLink-RB-Blue.ups")}
SLOT = {"offset": title_screen.MENU_TEXT_ADDR, "length": rom_identity.FIELD}


def clean_dump(key: str) -> bytes:
    name, sha1 = manifest.ROMS[key]
    for path in (ROOT / name, ROOT / "patch" / "build" / f"gen1_{key}.gb"):
        if path.is_file():
            data = path.read_bytes()
            if hashlib.sha1(data).hexdigest() == sha1:
                return data
    raise SystemExit(f"no clean {key} dump with sha1 {sha1} (looked for {name} and patch/build/gen1_{key}.gb)")


def derive(key: str, ups: str) -> dict:
    rom = make_ups.ups_apply(clean_dump(key), (ROOT / "patch" / "dist" / ups).read_bytes())
    version = title_screen.menu_version(rom[SLOT["offset"]:SLOT["offset"] + SLOT["length"]])
    return {"patched_md5": hashlib.md5(rom).hexdigest(),
            "canonical_sha1": rom_identity.canonical_sha1(rom, [SLOT], gb=True),
            "version": version,
            "version_slot": dict(SLOT)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if companion_pins.json has drifted")
    args = ap.parse_args()
    pins = companion_pins.load()["pins"]
    drift = 0
    for slug, (key, ups) in SLUGS.items():
        want = derive(key, ups)
        have = pins.get(slug, {})
        if args.check:
            for field, value in want.items():
                if have.get(field) != value:
                    drift += 1
                    print(f"DRIFT {slug}.{field}: file has {have.get(field)!r}, the UPS gives {value!r}")
        else:
            companion_pins.update(slug, want)
            print(f"{slug}: md5 {want['patched_md5']} canonical {want['canonical_sha1']} version {want['version']}")
    if args.check:
        print("companion_pins.json: rb-red/rb-blue " + ("DRIFTED" if drift else "match the UPS patches"))
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
