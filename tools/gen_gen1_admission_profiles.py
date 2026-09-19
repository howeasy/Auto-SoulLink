#!/usr/bin/env python3
"""Generate data/games/gen1_purergb/admission.json, the A3 admission table (PLAN §6 M1).

    {sha1 -> {title, kind, profile_id, header_title, header_crc, crc32, md5, size}}

computed from the built pureRGB ROMs (SLINK_PURERGB_ROMS / SLINK_PURERGB_SRC) and cross-checked
against data/purergb_sources.lock.json (sha1, header CRC, CRC32, header title). `kind` is
"clean" for the built ROMs. `--kind overlay` writes admission_overlay.json the same way for the
SLink companion build (PLAN M3): rows of kind "overlay" from the overlay ROMs, cross-checked
against data/purergb/overlay_provenance.json, each naming the clean `base_sha1` its UPS applies to.
lua/gen1/entry.lua reads both files into one sha1 table.

    python tools/gen_gen1_admission_profiles.py            # rewrite
    python tools/gen_gen1_admission_profiles.py --check    # exit 1 if the committed file is stale
    python tools/gen_gen1_admission_profiles.py --kind overlay
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import zlib

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import gen1_foundation as F  # noqa: E402

FOUNDATION = "purergb"


def describe(rom: bytes) -> dict:
    return {
        "header_title": rom[0x134:0x143].rstrip(b"\0").decode("ascii"),  # $143 is the CGB flag
        "header_crc": rom[0x14E:0x150].hex().upper(),  # global checksum, big-endian as the header stores it
        "crc32": f"{zlib.crc32(rom) & 0xFFFFFFFF:08X}",
        "md5": hashlib.md5(rom).hexdigest(),
        "size": len(rom),
    }


def build(foundation: str = FOUNDATION) -> dict:
    lock = F.lock(foundation)
    fnd = F.foundation(foundation)
    kind = "overlay" if foundation.endswith("_overlay") else "clean"
    out: dict = {}
    for title, (_sym, rom_file, _repo) in fnd["titles"].items():
        rom = F.rom_path(foundation, title).read_bytes()
        want = lock["outputs"][pathlib.Path(rom_file).stem]
        sha1 = hashlib.sha1(rom).hexdigest()
        row = {"title": title, "kind": kind, "profile_id": f"gen1_purergb/{title}", **describe(rom)}
        if kind == "overlay":
            row["base_sha1"] = want["base_sha1"]  # the clean ROM the UPS in patch/dist applies to
            row["ups"] = want["ups"]["file"]
        for key in ("sha1", "header_crc", "crc32"):
            got = sha1 if key == "sha1" else row[key]
            if got != want[key]:
                raise SystemExit(f"{title}: {key} {got} differs from the lock ({want[key]})")
        if row["header_title"] != want["title"]:
            raise SystemExit(f"{title}: header title {row['header_title']!r} differs from the lock ({want['title']!r})")
        out[sha1] = row
    return out


def render(value: dict) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    ap.add_argument("--kind", default="clean", choices=("clean", "overlay"),
                    help="overlay: the SLink companion build (admission_overlay.json)")
    args = ap.parse_args()
    foundation = F.with_kind(FOUNDATION, args.kind)
    out = F.out_path(foundation, "admission.json")
    text = render(build(foundation))
    if args.check:
        if not out.exists() or out.read_text(encoding="utf-8") != text:
            print(f"{out.relative_to(REPO)} is stale; run tools/gen_gen1_admission_profiles.py", file=sys.stderr)
            return 1
        print(f"{out.relative_to(REPO)} is current")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out.relative_to(REPO)}: " + ", ".join(f"{v['title']}={k[:12]}" for k, v in json.loads(text).items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
