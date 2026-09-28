"""Generate RR families from the admitted cartridge's evolution graph.

The older gen_pokemon_data.py name chains describe generic CFRU families and
omit regional branches. This separate RR artifact starts from the catalog and
every native wild slot, following all nonzero ROM evolution entries including
targets absent from those sources.

python tools/gen_rr_evolutions.py --rom "Pokemon - Radical Red.gba" [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/games/gen3_rr/evolution_families.json"
ROM_SHA1 = "964f951a0fdaf209e4ea1344883ef0d557bb3a80"
TABLE = 0x097CD9B0
SLOTS, STRIDE = 16, 8
POINTER_WITNESSES = (0x42F6C, 0x42FBC, 0x43138)


def graph_families(species, edges):
    """Connected evolution components, represented by their first base species.

    A base has no incoming evolution edge; cycles use their smallest ID.
    The representative is only an equality token, never a display-name ID.
    """
    adjacent = {s: set() for s in species}
    incoming = set()
    for source, target in edges:
        adjacent[source].add(target)
        adjacent[target].add(source)
        if source != target:
            incoming.add(target)
    remaining, families = set(species), {}
    while remaining:
        todo, component = [min(remaining)], set()
        while todo:
            s = todo.pop()
            if s in component:
                continue
            component.add(s)
            todo.extend(adjacent[s] - component)
        remaining -= component
        representative = min(component - incoming or component)
        families.update((s, representative) for s in component)
    return families


def generate(rom, catalog):
    if hashlib.sha1(rom).hexdigest() != ROM_SHA1:
        raise ValueError("RR evolution generator requires the pinned clean RR 4.1 ROM")
    if any(struct.unpack_from("<I", rom, at)[0] != TABLE for at in POINTER_WITNESSES):
        raise ValueError("RR evolution pointer witnesses changed")
    if __package__:
        from .rr_rom_encounters import decode_encounters
    else:
        from rr_rom_encounters import decode_encounters
    known = {int(s) for s in json.loads(catalog)}
    decoded = decode_encounters(rom)
    wild = {slot["species_id"] for headers in decoded["tables"].values() for header in headers
            for habitat in header["habitats"].values() for slot in habitat["slots"] if slot["species_id"]}
    todo, seen, edges = list(known | wild), set(), []
    while todo:
        source = todo.pop()
        if source in seen:
            continue
        seen.add(source)
        for slot in range(SLOTS):
            at = TABLE - 0x08000000 + (source * SLOTS + slot) * STRIDE
            method, _, target = struct.unpack_from("<HHH", rom, at)
            if not method:
                continue
            if not target or TABLE - 0x08000000 + (target + 1) * SLOTS * STRIDE > len(rom):
                raise ValueError(f"invalid RR evolution target {source}:{slot}->{target}")
            edges.append((source, target))
            if target not in seen:
                todo.append(target)
    families = graph_families(seen, edges)
    table_body = rom[TABLE - 0x08000000:TABLE - 0x08000000 + (max(seen) + 1) * SLOTS * STRIDE]
    return {
        "source_rom_sha1": ROM_SHA1,
        "species_catalog_sha256": hashlib.sha256(catalog).hexdigest(),
        "table_address": TABLE, "slots": SLOTS, "entry_size": STRIDE,
        "table_sha256": hashlib.sha256(table_body).hexdigest(),
        "species_count": len(seen), "edge_count": len(edges),
        "wild_ids_outside_catalog": sorted(wild - known),
        "reachable_ids_outside_catalog": sorted(seen - known),
        "families": {str(s): families[s] for s in sorted(seen)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    catalog = (ROOT / "data/games/gen3_frlge/rr_species.json").read_bytes()
    data = generate(args.rom.read_bytes(), catalog)
    if args.check:
        if json.loads(args.output.read_text(encoding="utf-8")) != data:
            raise SystemExit("RR evolution family artifact differs from its own ROM")
    else:
        args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"RR evolution families: {data['species_count']} species, {data['edge_count']} edges")


if __name__ == "__main__":
    main()
