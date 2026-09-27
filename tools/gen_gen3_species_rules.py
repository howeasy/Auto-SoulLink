#!/usr/bin/env python3
"""Extract normalization facts from SHA-1-pinned clean FR/LG or Emerald dumps.

    python tools/gen_gen3_species_rules.py [--firered path] [--leafgreen path] [--check]
    python tools/gen_gen3_species_rules.py --title emerald [--emerald path] [--check]

The output records original empty second-ability slots, never current cartridge values.
No ROM bytes are emitted. The source lock, symbol hashes and table hashes identify the input.
Emerald defaults to SLINK_GEN3_ROMS and has a separate output; FR/LG output is unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/games/gen3_frlg/species_rules.json"
EMERALD_OUT = ROOT / "data/games/gen3_emerald/species_rules.json"
EMERALD_NAME = "Pokemon - Emerald Version (USA, Europe).gba"
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


def build_emerald(rom: bytes) -> dict:
    """Independent Emerald facts; the FR/LG output and normalization set stay unchanged."""
    sys.path.insert(0, str(ROOT))
    from server.adapters import gen3_rom_tables as R

    pin = json.loads((ROOT / "data/gen3/pret/pokeemerald_provenance.json").read_text(encoding="utf-8"))
    digest = hashlib.sha1(rom).hexdigest()
    if digest != pin["rom"]["sha1"]:
        raise ValueError("emerald: ROM is not the SHA-1-pinned clean dump")
    symbols = ROOT / "data/gen3/pret/pokeemerald.sym"
    head = R.table_symbols("emerald", symbol_dir=symbols.parent)["gSpeciesInfo"]
    if head["count"] != 412 or head["size"] != 412 * 28:
        raise ValueError("Emerald gSpeciesInfo is not 412 * 28 bytes")
    table = R._Rom(rom).read(head["address"], head["size"], "gSpeciesInfo")
    zero_slots = [i for i in range(412) if table[i * 28 + 23] == 0]
    policy = byte_policy()
    projected = R._normalised_species_rule_rows(
        table, frozenset(zero_slots), tuple(row["offset"] for row in policy if row["projected"]),
        R.DEOXYS_FORME["emerald"])
    decoded = R.decode_rom_tables(rom, "emerald")
    return {
        "schema": 1, "generated_by": "python tools/gen_gen3_species_rules.py --title emerald",
        "source": {"url": "https://github.com/pret/pokeemerald", "commit": pin["origin"]["source_commit"]},
        "record_size": 28, "second_ability_offset": 23,
        "layout_source": "pret/pokeemerald include/pokemon.h:297-325; declarations and byte offsets match FR/LG",
        "layout_declarations_sha256": "3e19a8672a0d926961f74ab416896bac1e48d18ab59e4078be0e971d6639667f",
        "bytes": policy,
        "titles": {"emerald": {"rom_sha1": digest,
            "symbols_sha256": hashlib.sha256(symbols.read_bytes()).hexdigest(),
            "species_info_address": head["address"], "species_count": head["count"],
            "species_info_sha256": hashlib.sha256(table).hexdigest()}},
        "zero_second_ability_species": zero_slots,
        "normalised_species_rules_sha256": hashlib.sha256(projected).hexdigest(),
        "evolutions_sha256": hashlib.sha256(json.dumps(sorted(decoded["evolutions"].items())).encode()).hexdigest(),
        "clean_content_sha256": R.gen3_content_fingerprint(decoded),
    }


def emerald_path() -> Path:
    folders = [Path(os.environ["SLINK_GEN3_ROMS"])] if os.environ.get("SLINK_GEN3_ROMS") else [ROOT, *ROOT.parents]
    return next((folder / EMERALD_NAME for folder in folders if (folder / EMERALD_NAME).is_file()),
                ROOT / "patch/build/gen3_Pokemon_-_Emerald_Version_(USA,_Europe).gba")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for title, path in STAGED.items():
        parser.add_argument(f"--{title}", type=Path, default=ROOT / path)
    parser.add_argument("--title", choices=("frlg", "emerald"), default="frlg")
    parser.add_argument("--emerald", type=Path, default=None,
                        help="pinned Emerald dump; default SLINK_GEN3_ROMS or the staged dump")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        facts = (build_emerald((args.emerald or emerald_path()).read_bytes()) if args.title == "emerald"
                 else build({t: getattr(args, t).read_bytes() for t in STAGED}))
        text = json.dumps(facts, indent=2) + "\n"
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    output = EMERALD_OUT if args.title == "emerald" else OUT
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != text:
            print(f"stale: {output.relative_to(ROOT)}")
            return 1
        print(f"current: {output.relative_to(ROOT)}")
    else:
        output.write_text(text, encoding="utf-8")
        print(f"wrote {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
