"""RR name/base-stat records; community data supplies display labels only."""
from __future__ import annotations

import ast
import hashlib

from server.adapters.gen3_codec import decode_name
from tools.rr_rom_encounters import BASE, _read, _u32, decode_encounters


def display_metadata(js: str) -> dict:
    """Parse the pinned data-only JS object without executing JavaScript."""
    class Literals(ast.NodeTransformer):
        def visit_Name(self, node):
            values = {"null": None, "true": True, "false": False}
            if node.id not in values:
                raise ValueError(f"non-data expression in RR display metadata: {node.id}")
            return ast.copy_location(ast.Constant(values[node.id]), node)

    value = ast.literal_eval(Literals().visit(ast.parse(js, mode="eval")))
    if not isinstance(value, dict) or not isinstance(value.get("species"), dict):
        raise ValueError("RR display metadata has no species dictionary")
    return value["species"]


def species_record(rom: bytes, sid: int) -> dict:
    if not 0 <= sid < 4096:
        raise ValueError(f"RR species id out of bounds: {sid}")
    names = _u32(rom, BASE+0x144, "RR species names")
    stats = _u32(rom, BASE+0x1BC, "RR base stats")
    raw_name = _read(rom, names+sid*11, 11, f"RR species {sid} name")
    raw_stats = _read(rom, stats+sid*28, 28, f"RR species {sid} stats")
    return {"species_id": sid, "name_address": names+sid*11, "base_stats_address": stats+sid*28,
            "rom_name": decode_name(raw_name), "name_hex": raw_name.hex(),
            "base_stats_hex": raw_stats.hex(), "stats": list(raw_stats[:6]),
            "types": list(raw_stats[6:8]), "terminated": 255 in raw_name}


def extend_names(rom: bytes, existing: dict[int, str], metadata: dict) -> tuple[dict, dict]:
    """Append the ROM's contiguous named/stat-bearing tail, stopping at its table boundary.

    This is a version-pinned RR4.1 extension, not an inferred universal species
    limit. Existing labels stay stable; new IDs exist because of ROM records,
    not because a community object happened to declare them.
    """
    names, records = dict(existing), []
    for sid in range(max(existing)+1, 4096):
        row = species_record(rom, sid)
        if not any(row["stats"]) and not row["terminated"]:
            stop = row
            break
        if not row["terminated"] or not row["rom_name"] or not all(row["stats"]):
            raise ValueError(f"RR species tail {sid} is not a named valid base-stat record")
        label = metadata.get(sid)
        if not isinstance(label, dict) or label.get("ID") != sid or label.get("stats") != row["stats"]:
            raise ValueError(f"RR species {sid}: display metadata does not bind to the ROM stats")
        display = label.get("key") or label.get("name")
        if not isinstance(display, str) or not display:
            raise ValueError(f"RR species {sid}: missing display name")
        names[sid] = display
        records.append({**row, "display_name": display, "display_source": "jwowsquared_data_js"})
    else:
        raise ValueError("RR species tail has no empty record within the reader bound")
    wild_ids = {s["species_id"] for rows in decode_encounters(rom)["tables"].values()
                for h in rows for info in h["habitats"].values() for s in info["slots"]} - {0}
    missing = sorted(wild_ids-names.keys())
    if missing:
        raise ValueError(f"RR wild species remain unnamed: {missing}")
    return names, {"schema": "rr-species-rom-extension-v1", "rom_sha1": hashlib.sha1(rom).hexdigest(),
                   "field_sources": {"species_id": "ROM name/base-stat record index",
                                     "rom_name": "ROM name table via08000144,11-byte stride",
                                     "stats": "ROM base-stat table via080001BC,28-byte stride",
                                     "display_name": "pinned community data.js key/name; stats identity checked"},
                   "added": records, "stop": stop, "wild_ids": sorted(wild_ids)}
