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


def byte_policy() -> list[dict]:
    """RF-5 policy, laid out by pret include/pokemon.h:208-236 (plus agbcc tail padding)."""
    names = (
        "baseHP", "baseAttack", "baseDefense", "baseSpeed", "baseSpAttack", "baseSpDefense",
        "types[0]", "types[1]", "catchRate", "expYield", "evYield_HP/Attack/Defense/Speed",
        "evYield_SpAttack/SpDefense/reserved", "itemCommon low", "itemCommon high",
        "itemRare low", "itemRare high", "genderRatio", "eggCycles", "friendship", "growthRate",
        "eggGroups[0]", "eggGroups[1]", "abilities[0]", "abilities[1]", "safariZoneFleeRate",
        "bodyColor/noFlip", "padding[0]", "padding[1]",
    )
    projected = {*range(8), 16, 19, 22, 23}
    reasons = {
        8: "Ruling 31: minimum catch-rate settings are open; the server does not infer a catch from this value.",
        16: "Ruling 31 shared-rule policy, RF-5: gender clauses and display use the pinned personality/gender ratio.",
        19: "Ruling 31 shared-rule policy, RF-3: growth-curve changes remain forbidden by the Manager envelope.",
    }
    rows = []
    for offset, name in enumerate(names):
        reason = reasons.get(offset)
        allowed = []
        if offset == 8:
            allowed = ["catch_rate"]
        elif 12 <= offset <= 15:
            allowed = ["wild_held_items"]
            reason = "Ruling 31: wild held items are open; these item bytes are not fixed species rules."
        elif offset < 8 or offset in (22, 23):
            reason = "Ruling 31: base stats, types and abilities are fixed server/calc rule data."
        elif offset in (25, 26, 27):
            reason = "Ruling 31/RF-5: appearance or padding has no Soul Link rule meaning; no allowed setting changes it."
        elif reason is None:
            reason = "Ruling 31/RF-5: no server rule consumes this field; no allowed randomizer setting may change it."
        rows.append({"offset": offset, "name": name, "projected": offset in projected,
                     "allowed_write_domains": allowed, "reason": reason})
    return rows


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
            "layout_source": "pret/pokefirered include/pokemon.h:208-236; agbcc sizeof(SpeciesInfo)=28",
            "bytes": byte_policy(),
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
