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
import os
import re
import struct
from collections import Counter
from pathlib import Path

try:
    from tools import rr_companion
except ImportError:                    # run as a script: tools/ is sys.path[0]
    import rr_companion

ROOT = Path(__file__).resolve().parents[1]
BASE = 0x08000000
# the clean 4.1 dump, and the companion (exact, or an earlier build its pin row lists as canonical-equal: the tables read are vanilla's)
ROM_PINS = {"964f951a0fdaf209e4ea1344883ef0d557bb3a80", *rr_companion.accepted_sha1s()}
HEADER_SIZE = 20
HABITATS = (("land", 4, 12), ("water", 8, 5), ("rock_smash", 12, 5), ("fishing", 16, 10))
LOADS = {"Night": (0x090C356E, 0x4A24), "Day": (0x090C3590, 0x4A1D),
         "Fallback": (0x090C2668, 0x4C1C)}


def default_rom_path() -> Path:
    explicit = os.environ.get("SLINK_RR_ROM")
    return Path(explicit) if explicit else Path(os.environ.get("SLINK_GEN3_ROMS", ROOT)) / "Pokemon - Radical Red.gba"


def client_area_labels(root: Path = ROOT) -> tuple[dict[str, str], dict[str, str]]:
    """Existing client routing/display keys, not a source of encounter game facts."""
    directory = root / "data/games/gen3_frlge"
    coarse = json.loads((directory / "area_map.json").read_text(encoding="utf-8"))
    fine = dict(re.findall(r'\["(\d+:\d+)"\]\s*=\s*"([^"]+)"',
                           (directory / "gen3_frlge_locations.lua").read_text(encoding="utf-8")))
    fallback = {key: value for key, value in fine.items() if key not in coarse}
    return {**fine, **coarse}, fallback


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


def effective_variants(decoded: dict, period: str) -> list[dict]:
    """All statically selectable fallback variants, with primary habitats taking precedence."""
    primary = {(r["map_group"], r["map_num"]): r for r in decoded["tables"][period]}
    fallbacks = {}
    for row in decoded["tables"]["Fallback"]:
        fallbacks.setdefault((row["map_group"], row["map_num"]), []).append(row)
    out = []
    for key in sorted(primary.keys() | fallbacks.keys()):
        for variant, fallback in enumerate(fallbacks.get(key, [{}])):
            habitats = {}
            for kind, _, _ in HABITATS:
                info = primary.get(key, {}).get("habitats", {}).get(kind)
                source = period
                header = primary.get(key, {}).get("address")
                if info is None:
                    info = fallback.get("habitats", {}).get(kind)
                    source, header = "Fallback", fallback.get("address")
                if info is not None:
                    habitats[kind] = {**info, "selected_from": source, "header_address": header}
            out.append({"map_group": key[0], "map_num": key[1], "variant": variant, "habitats": habitats})
    return out


def slot_rates(rom: bytes) -> dict[str, list[int]]:
    """Read RR's own chooser CMP immediates; each tested interval is immediate+1."""
    def widths(addresses):
        out = []
        for address in addresses:
            word = int.from_bytes(_read(rom, address, 2, "RR slot probability"), "little")
            if word & 0xF800 != 0x2800:
                raise ValueError(f"RR chooser CMP changed at {address:#x}")
            out.append((word & 255)+1)
        return out

    land = widths([0x08082760, 0x08082770, 0x08082780, 0x08082790, 0x080827A0,
                   0x080827B0, 0x080827C0, 0x080827D0, 0x080827E0, 0x080827F0])
    # The final comparisons to98/99 split the two remaining land slots and final fish slot.
    if _read(rom, 0x080827F8, 2, "land tail") != b"\x62\x29" or _read(rom, 0x080828EA, 2, "fish tail") != b"\x63\x29":
        raise ValueError("RR chooser tail changed")
    land += [99-sum(land), 1]
    water = widths([0x0808281E, 0x0808282E, 0x0808283E, 0x0808284E])
    water += [100-sum(water)]
    old = widths([0x0808288E])
    old += [100-sum(old)]
    good = widths([0x08082896, 0x080828A4, 0x080828B2])
    super_ = widths([0x080828BA, 0x080828C8, 0x080828D6, 0x080828E4])
    super_ += [100-sum(super_)]
    rates = {"land": land, "water": water, "rock_smash": water, "Old Rod": old, "Good Rod": good, "Super Rod": super_}
    if any(sum(values) != 100 or min(values) <= 0 for values in rates.values()):
        raise ValueError("RR chooser intervals are not a probability distribution")
    return rates


def build_catalog(rom: bytes, area_map: dict[str, str], names: dict[int, str], labels=None) -> tuple[dict, dict]:
    """ROM owns all encounter facts; names/optional labels are display metadata."""
    decoded, rates = decode_encounters(rom), slot_rates(rom)
    labels = labels or {}
    periods = {"Day": {}, "Night": {}}
    unmapped, empty = set(), set()
    for period in periods:
        seen = {}
        for row in effective_variants(decoded, period):
            map_key = f"{row['map_group']}:{row['map_num']}"
            area = area_map.get(map_key)
            if not area:
                unmapped.add(map_key)
                continue
            for kind, info in row["habitats"].items():
                for slot in info["slots"]:
                    sid, index = slot["species_id"], slot["slot"]
                    if sid == 0:
                        empty.add(slot["address"])
                        continue
                    if sid not in names:
                        raise ValueError(f"RR encounter {map_key}/{kind}/{index}: unnamed species {sid}")
                    method = {"land": "land", "water": "Surfing", "rock_smash": "Rock Smash"}.get(kind)
                    rate = rates[kind][index] if kind != "fishing" else None
                    if kind == "fishing":
                        method = "Old Rod" if index < 2 else "Good Rod" if index < 5 else "Super Rod"
                        rate = rates[method][index - (0 if index < 2 else 2 if index < 5 else 5)]
                    source = {"map": map_key, "period": period, "fallback_variant": row["variant"],
                              "habitat": kind,
                              "header_address": info["header_address"], "selected_from": info["selected_from"],
                              "info_address": info["info_address"], "slots_address": info["slots_address"],
                              "encounter_rate": info["encounter_rate"], "slot": index,
                              "address": slot["address"], "raw_hex": slot["raw_hex"]}
                    unique = (area, method, slot["address"])
                    if unique in seen:
                        seen[unique]["sources"].append(source)
                        continue
                    entry = {"name": labels.get(sid, names[sid]), "species_id": sid, "rate": rate,
                             "min_level": slot["min_level"], "max_level": slot["max_level"]}
                    item = {"entry": entry, "sources": [source]}
                    seen[unique] = item
                    periods[period].setdefault(area, {}).setdefault(method, []).append(item)
    out, proofs = {}, {}
    for area in sorted(periods["Day"].keys() | periods["Night"].keys()):
        methods, evidence = {}, {}
        day, night = periods["Day"].get(area, {}), periods["Night"].get(area, {})
        for method in ("land", "Surfing", "Old Rod", "Good Rod", "Super Rod", "Rock Smash"):
            a, b = day.get(method, []), night.get(method, [])
            if not a and not b:
                continue
            if method != "land" and [r["entry"] for r in a] == [r["entry"] for r in b]:
                methods[method] = [r["entry"] for r in a]
                evidence[method] = [x["sources"]+y["sources"] for x, y in zip(a, b, strict=True)]
            else:
                for period, rows in (("Day", a), ("Night", b)):
                    if rows:
                        label = period if method == "land" else period+" "+method
                        methods[label] = [r["entry"] for r in rows]
                        evidence[label] = [r["sources"] for r in rows]
        out[area], proofs[area] = methods, evidence
    return out, {"schema": "rr-rom-encounters-v1", "rom_sha1": decoded["rom_sha1"],
                 "heads": decoded["heads"], "rates": rates,
                 "field_sources": {"species_id": "RR ROM WildPokemon+2",
                                   "min_level": "RR ROM WildPokemon+0", "max_level": "RR ROM WildPokemon+1",
                                   "rate": "RR ROM chooser instruction intervals",
                                   "name": "display metadata only: pinned community label or species catalog"},
                 "unmapped_maps": sorted(unmapped), "excluded_none_slot_addresses": sorted(empty),
                 "runtime_limits": ["gWildDataSwitch overrides and swarms are not inferred",
                                    "fallback variants are possibilities, not an observation of the active variable"],
                 "entries": proofs}


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


def catalog_diff(decoded: dict, area_map: dict[str, str], catalog: dict) -> dict:
    """Complete comparison with the primary table projection; preserve every discrepancy."""
    actual = primary_area_slots(decoded, area_map)
    mismatches = []

    def values(rows):
        return [(r["species_id"], r["min_level"], r["max_level"]) for r in rows]

    for area in sorted(actual.keys() | catalog.keys()):
        rom_methods, json_methods = actual.get(area, {}), catalog.get(area, {})
        for method in sorted(rom_methods.keys() | json_methods.keys()):
            rom_rows, json_rows = values(rom_methods.get(method, [])), values(json_methods.get(method, []))
            if rom_rows != json_rows:
                rom_counts, json_counts = Counter(rom_rows), Counter(json_rows)
                mismatches.append({"area": area, "method": method,
                    "rom_count": len(rom_rows), "catalog_count": len(json_rows),
                    "rom_only": [{"species_id": row[0], "min_level": row[1], "max_level": row[2], "count": n}
                                 for row, n in sorted((rom_counts-json_counts).items())],
                    "catalog_only": [{"species_id": row[0], "min_level": row[1], "max_level": row[2], "count": n}
                                     for row, n in sorted((json_counts-rom_counts).items())],
                    "order_differs": rom_counts == json_counts})
    unmapped = sorted({(r["map_group"], r["map_num"]) for period in ("Day", "Night")
                       for r in decoded["tables"][period]
                       if f"{r['map_group']}:{r['map_num']}" not in area_map})
    return {"rom_sha1": decoded["rom_sha1"], "rom_areas": len(actual),
            "catalog_areas": len(catalog), "mismatched_methods": len(mismatches),
            "unmapped_primary_maps": [list(key) for key in unmapped], "mismatches": mismatches}


def full_catalog_diff(rom: bytes, area_map: dict[str, str], catalog: dict) -> dict:
    """Compare all shipped game-fact fields against the complete ROM selection model."""
    decoded = decode_encounters(rom)
    ids = {s["species_id"] for rows in decoded["tables"].values() for h in rows
           for info in h["habitats"].values() for s in info["slots"] if s["species_id"]}
    expected, _ = build_catalog(rom, area_map, {sid: str(sid) for sid in ids})
    by_area = {}

    def values(rows):
        return [(r["species_id"], r["min_level"], r["max_level"], r["rate"]) for r in rows]

    for area in sorted(expected.keys() | catalog.keys()):
        methods = {}
        a, b = expected.get(area, {}), catalog.get(area, {})
        for method in sorted(a.keys() | b.keys()):
            want, got = values(a.get(method, [])), values(b.get(method, []))
            if want != got:
                methods[method] = {"rom_count": len(want), "catalog_count": len(got),
                                   "rom_slots": want, "catalog_slots": got}
        by_area[area] = {"rom_count": sum(map(len, a.values())), "catalog_count": sum(map(len, b.values())),
                         "matched": not methods, "differences": methods}
    return {"rom_sha1": decoded["rom_sha1"], "fields": ["species_id", "min_level", "max_level", "rate"],
            "mismatched_areas": sum(not row["matched"] for row in by_area.values()),
            "mismatched_methods": sum(len(row["differences"]) for row in by_area.values()), "areas": by_area}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="write the complete raw table census")
    parser.add_argument("--catalog", type=Path, help="compare a generated encounter catalog")
    parser.add_argument("--diff-output", type=Path, help="write the complete catalog comparison")
    args = parser.parse_args()
    rom = load_rom(args.rom)
    decoded = decode_encounters(rom)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(decoded, indent=2)+"\n", encoding="utf-8")
    if args.catalog:
        area_map, _ = client_area_labels()
        diff = full_catalog_diff(rom, area_map, json.loads(args.catalog.read_text(encoding="utf-8")))
        if args.diff_output:
            args.diff_output.parent.mkdir(parents=True, exist_ok=True)
            args.diff_output.write_text(json.dumps(diff, indent=2)+"\n", encoding="utf-8")
        print(f"Catalog comparison: {diff['mismatched_methods']} method differences "
              f"in {diff['mismatched_areas']} areas")
    print(json.dumps({"rom_sha1": decoded["rom_sha1"], "heads": decoded["heads"],
                      "header_counts": {name: len(rows) for name, rows in decoded["tables"].items()},
                      "slot_counts": {name: sum(len(h["slots"]) for r in rows for h in r["habitats"].values())
                                      for name, rows in decoded["tables"].items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
