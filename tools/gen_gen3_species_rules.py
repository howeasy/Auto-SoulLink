#!/usr/bin/env python3
"""Extract FR/LG normalization facts from both SHA-1-pinned clean dumps.

    python tools/gen_gen3_species_rules.py [--firered path] [--leafgreen path] [--check]

The output records original empty second-ability slots, never current cartridge values.
No ROM bytes are emitted. The source lock, symbol hashes and table hashes identify the input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/games/gen3_frlg/species_rules.json"
STAGED = {"firered": "patch/build/gen3_Pokemon_-_FireRed_Version_(USA).gba",
          "leafgreen": "patch/build/gen3_Pokemon_-_LeafGreen_Version_(USA).gba"}


def build(roms: dict[str, bytes]) -> dict:
    lock = json.loads((ROOT / "data/gen3_sources.lock.json").read_text(encoding="utf-8"))
    if set(roms) != set(STAGED):
        raise ValueError("both pinned FireRed and LeafGreen dumps are required")
    originals = {}
    titles = {}
    for title, rom in roms.items():
        digest = hashlib.sha1(rom).hexdigest()
        if digest != lock["outputs"][f"poke{title}"]["sha1"]:
            raise ValueError(f"{title}: ROM is not the SHA-1-pinned clean dump")
        symbols = ROOT / "data/gen3/pret" / f"poke{title}.sym"
        matches = [line.split() for line in symbols.read_text(encoding="utf-8").splitlines()
                   if line.split() and line.split()[-1] == "gSpeciesInfo"]
        if len(matches) != 1 or len(matches[0]) != 4:
            raise ValueError(f"{symbols}: expected one gSpeciesInfo symbol")
        addr, size = int(matches[0][0], 16), int(matches[0][2], 16)
        base = addr - 0x08000000
        if base < 0 or size <= 0 or size % 28 or base + size > len(rom):
            raise ValueError(f"{symbols}: invalid gSpeciesInfo span")
        table = rom[base:base + size]
        originals[title] = [i // 28 for i in range(0, size, 28) if table[i + 23] == 0]
        titles[title] = {"rom_sha1": digest, "symbols_sha256": hashlib.sha256(symbols.read_bytes()).hexdigest(),
                         "species_info_address": addr, "species_count": size // 28,
                         "species_info_sha256": hashlib.sha256(table).hexdigest()}
    if originals["firered"] != originals["leafgreen"]:
        raise ValueError("the pinned titles disagree on original empty second-ability slots")
    return {"schema": 1, "generated_by": "python tools/gen_gen3_species_rules.py",
            "source": lock["source"], "record_size": 28, "second_ability_offset": 23,
            "titles": titles, "zero_second_ability_species": originals["firered"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for title, path in STAGED.items():
        parser.add_argument(f"--{title}", type=Path, default=ROOT / path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        text = json.dumps(build({t: getattr(args, t).read_bytes() for t in STAGED}), indent=2) + "\n"
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"stale: {OUT.relative_to(ROOT)}")
            return 1
        print(f"current: {OUT.relative_to(ROOT)}")
    else:
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
