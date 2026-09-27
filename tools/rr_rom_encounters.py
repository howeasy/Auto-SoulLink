"""Read RR 4.1 wild tables from the cartridge, including its override selector.

RR ROM bytes are authoritative. CFRU b637a278 include/wild_encounter.h supplies
the struct layout only. The RR selector at 090C3550 reads its Night/Day literal
pools at 090C3600/090C3608 and falls back through 090C262C. That fallback reads
the relocated pointer at 08082990; it is NOT the current Day override table.
See docs/gen3/research/rr_encounter_forms.md for byte/call-chain evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 0x08000000
ROM_PINS = {"964f951a0fdaf209e4ea1344883ef0d557bb3a80", "7a3867499d66eb3621e0e7dde43bd033fc679f01"}
HEADER_SIZE = 20
HABITATS = (("land", 4, 12), ("water", 8, 5), ("rock_smash", 12, 5), ("fishing", 16, 10))
LOADS = {"Night": (0x090C356E, 0x4A24), "Day": (0x090C3590, 0x4A1D),
         "Fallback": (0x090C2668, 0x4C1C)}


def load_rom(path: Path) -> bytes:
    rom = path.read_bytes()
    digest = hashlib.sha1(rom).hexdigest()
    if digest not in ROM_PINS:
        raise ValueError(f"RR ROM SHA1 is not pinned: {digest} ({path})")
    return rom


def _read(rom: bytes, address: int, size: int, label: str) -> bytes:
    offset = address - BASE
    if not BASE <= address < 0x0A000000 or offset + size > len(rom) or size < 0:
        raise ValueError(f"{label}: ROM pointer {address:#010x}+{size} is out of range")
    return rom[offset:offset+size]


def _u32(rom: bytes, address: int, label: str) -> int:
    return struct.unpack("<I", _read(rom, address, 4, label))[0]


def table_heads(rom: bytes) -> dict[str, int]:
    """Follow actual RR PC-relative loads; reject changed selector instructions."""
    heads = {}
    for name, (site, expected) in LOADS.items():
        raw = _read(rom, site, 2, name + " selector")
        instruction = int.from_bytes(raw, "little")
        if instruction != expected:
            raise ValueError(f"{name}: RR selector instruction changed at {site:#x}: {raw.hex()}")
        pool = ((site+4) & ~3) + (instruction & 255)*4
        value = _u32(rom, pool, name + " literal")
        # Fallback has a pointer-to-pointer; Day/Night literals are direct heads.
        heads[name] = _u32(rom, value, "Fallback header pointer") if name == "Fallback" else value
    return heads


def read_table(rom: bytes, address: int, *, max_headers: int = 1024) -> list[dict]:
    """Preserve every map/header variant and every slot, following both pointer levels."""
    headers = []
    for index in range(max_headers):
        at = address + index*HEADER_SIZE
        raw = _read(rom, at, HEADER_SIZE, "wild header")
        group, number = raw[:2]
        if group == 255:
            return headers
        row = {"map_group": group, "map_num": number, "address": at, "habitats": {}}
        for kind, offset, count in HABITATS:
            info_address = int.from_bytes(raw[offset:offset+4], "little")
            if not info_address:
                continue
            info = _read(rom, info_address, 8, f"{group}.{number} {kind} info")
            slots_address = int.from_bytes(info[4:8], "little")
            slots_raw = _read(rom, slots_address, count*4, f"{group}.{number} {kind} slots")
            slots = []
            for slot in range(count):
                data = slots_raw[slot*4:slot*4+4]
                minimum, maximum, species = struct.unpack("<BBH", data)
                slots.append({"slot": slot, "species_id": species, "min_level": minimum,
                              "max_level": maximum, "address": slots_address+slot*4,
                              "raw_hex": data.hex()})
            row["habitats"][kind] = {"encounter_rate": info[0], "info_address": info_address,
                                     "slots_address": slots_address, "slots": slots}
        headers.append(row)
    raise ValueError(f"wild table {address:#x}: no sentinel within {max_headers} headers")


def decode_encounters(rom: bytes) -> dict:
    heads = table_heads(rom)
    return {"rom_sha1": hashlib.sha1(rom).hexdigest(), "heads": heads,
            "tables": {name: read_table(rom, head) for name, head in heads.items()}}


def effective_maps(decoded: dict, period: str) -> dict[tuple[int, int], dict]:
    """Default selection with gWildDataSwitch NULL and Altering Cave variant zero.

    Every raw fallback variant remains in decoded['tables']['Fallback']; this
    projection does not invent the runtime script/variable state selecting one.
    Missing maps and NULL habitat pointers fall back, as RR 090C3550 does.
    """
    if period not in ("Day", "Night"):
        raise ValueError("RR period must be Day or Night")
    fallback = {}
    for row in decoded["tables"]["Fallback"]:
        fallback.setdefault((row["map_group"], row["map_num"]), row)
    primary = {(row["map_group"], row["map_num"]): row for row in decoded["tables"][period]}
    out = {}
    for key in sorted(fallback.keys() | primary.keys()):
        habitats = {}
        for kind, _, _ in HABITATS:
            source = primary.get(key, {})
            table = source.get("habitats", {}).get(kind)
            selected_from = period
            if table is None:
                source = fallback.get(key, {})
                table = source.get("habitats", {}).get(kind)
                selected_from = "Fallback"
            if table is not None:
                habitats[kind] = {**table, "selected_from": selected_from,
                                   "header_address": source["address"]}
        out[key] = {"map_group": key[0], "map_num": key[1], "habitats": habitats}
    return out


def primary_area_slots(decoded: dict, area_map: dict[str, str]) -> dict:
    """Project primary override slots by the server's coarse area/method keys.

    Shared slot arrays used by several maps/method times are counted once per
    area/method, matching one community array definition. Raw maps stay intact
    in decode_encounters; absent area IDs are never guessed from a vanilla map.
    """
    out, seen = {}, set()
    for period in ("Day", "Night"):
        for row in decoded["tables"][period]:
            key = f"{row['map_group']}:{row['map_num']}"
            area = area_map.get(key)
            if not area:
                continue
            for kind, info in row["habitats"].items():
                for slot in info["slots"]:
                    method = period if kind == "land" else {"water": "Surfing", "rock_smash": "Rock Smash"}.get(kind)
                    if kind == "fishing":
                        method = "Old Rod" if slot["slot"] < 2 else "Good Rod" if slot["slot"] < 5 else "Super Rod"
                    unique = (area, method, slot["address"])
                    if unique not in seen:
                        seen.add(unique)
                        out.setdefault(area, {}).setdefault(method, []).append(slot)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="write the complete raw table census")
    args = parser.parse_args()
    decoded = decode_encounters(load_rom(args.rom))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(decoded, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"rom_sha1": decoded["rom_sha1"], "heads": decoded["heads"],
                      "header_counts": {name: len(rows) for name, rows in decoded["tables"].items()},
                      "slot_counts": {name: sum(len(h["slots"]) for r in rows for h in r["habitats"].values())
                                      for name, rows in decoded["tables"].items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
