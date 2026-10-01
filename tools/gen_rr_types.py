"""Generate canonical RR species types from the pinned ROM's base-stat bytes.

The pinned community Base_Stats.c is a historical drift control only. It does
not supply the output types. Explicit RR->canonical conversion keeps raw Fairy23
separate from server Fairy18. Output includes raw/canonical provenance for each ID.

python tools/gen_rr_types.py --rom RR.gba [--check]
SLINK_RR_ROM or SLINK_GEN3_ROMS supplies the default ROM path.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_rr_sources import cached_source, diff_snippet  # noqa: E402
from rr_rom_encounters import default_rom_path, load_rom  # noqa: E402
from rr_rom_species import species_record  # noqa: E402

CANONICAL_OUTPUT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) \
    / "data" / "games" / "gen3_frlge" / "rr_types.json"
# The non-check write target -- kept identical to CANONICAL_OUTPUT so
# `python tools/gen_rr_types.py` (no --check) actually updates the file
# server/pokemon_data.py loads and --check compares against, instead of a
# stray CWD-relative data/rr_types.json nothing reads.
OUTPUT = str(CANONICAL_OUTPUT)
PROVENANCE_OUTPUT = CANONICAL_OUTPUT.parents[2] / "gen3_rr_types_rom.json"

# The server's canonical type namespace, deliberately distinct from RR's raw byte.
# The ROM uses 23 for Fairy; 18..22 are absent from its named base-stat records.
RR_TO_CANONICAL_TYPE = {
    0:0, 1:1, 2:2, 3:3, 4:4, 5:5, 6:6, 7:7, 8:8, 9:9,
    10:10, 11:11, 12:12, 13:13, 14:14, 15:15, 16:16, 17:17, 23:18,
}


def types_from_rom(rom: bytes, species_ids) -> tuple[dict, dict]:
    types, records = {}, {}
    for sid in sorted(map(int, species_ids)):
        row = species_record(rom, sid)
        if not any(row["stats"]):
            continue  # a reserved/catalog alias without a Pokemon base-stat record
        try:
            pair = tuple(RR_TO_CANONICAL_TYPE[t] for t in row["types"])
        except KeyError as exc:
            raise ValueError(f"RR species {sid}: unmapped raw type {exc.args[0]}") from None
        types[sid] = pair
        records[str(sid)] = {"address": row["base_stats_address"]+6,
                             "rom_type_bytes": row["types"], "canonical_types": list(pair)}
    return types, {"schema": "rr-rom-types-v1", "rom_sha1": hashlib.sha1(rom).hexdigest(),
                   "rr_to_canonical": {str(k):v for k,v in RR_TO_CANONICAL_TYPE.items()},
                   "field_sources": {"rom_type_bytes": "RR ROM base-stat record +6/+7",
                                     "canonical_types": "explicit RR raw-byte to server canonical-id map"},
                   "species": records}

# Canonical server type labels for the historical community-source comparison.
# Actual RR raw-byte conversion is explicit above; raw Fairy is 23.
TYPE_MAP = {
    "TYPE_NORMAL":   0,  "TYPE_FIGHTING": 1,  "TYPE_FLYING":   2,
    "TYPE_POISON":   3,  "TYPE_GROUND":   4,  "TYPE_ROCK":     5,
    "TYPE_BUG":      6,  "TYPE_GHOST":    7,  "TYPE_STEEL":    8,
    "TYPE_MYSTERY":  9,  "TYPE_FIRE":    10,  "TYPE_WATER":   11,
    "TYPE_GRASS":   12,  "TYPE_ELECTRIC":13,  "TYPE_PSYCHIC": 14,
    "TYPE_ICE":     15,  "TYPE_DRAGON":  16,  "TYPE_DARK":    17,
    "TYPE_FAIRY":   18,  "TYPE_ROOSTLESS": 19,  "TYPE_STELLAR": 20,
}


def _parse_species_types(data_h: str, data_bs: str) -> dict[int, tuple[int, int]]:
    name_to_id: dict[str, int] = {}
    for m in re.finditer(r"#define\s+(SPECIES_\w+)\s+0x([0-9A-Fa-f]+)", data_h):
        name, num = m.group(1), int(m.group(2), 16)
        if name not in ("SPECIES_NONE", "SPECIES_EGG") and num > 0:
            name_to_id[name] = num

    species_types: dict[int, tuple[int, int]] = {}
    blocks = re.split(r'\[SPECIES_', data_bs)
    for block in blocks[1:]:  # skip header before first species
        name_m = re.match(r'(\w+)\]', block)
        if not name_m:
            continue
        sname = "SPECIES_" + name_m.group(1)
        sid = name_to_id.get(sname)
        if sid is None:
            continue

        t1_m = re.search(r'\.type1\s*=\s*(TYPE_\w+)', block)
        t2_m = re.search(r'\.type2\s*=\s*(TYPE_\w+)', block)
        if not t1_m:
            continue
        t1_str = t1_m.group(1).strip()
        t2_str = t2_m.group(1).strip() if t2_m else t1_str

        t1 = TYPE_MAP.get(t1_str)
        t2 = TYPE_MAP.get(t2_str)
        if t1 is None or t2 is None:
            print(f"  WARNING: Unknown type for {sname}: {t1_str}={t1}, {t2_str}={t2}")
            continue
        species_types[sid] = (t1, t2)
    return species_types


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=default_rom_path(), help="pinned RR ROM (or SLINK_RR_ROM)")
    parser.add_argument("--check", action="store_true",
                        help="Regenerate in memory and diff against the "
                             f"committed {CANONICAL_OUTPUT}; exit 1 on drift.")
    args = parser.parse_args()

    data_h = cached_source("funnotbun_species_h").decode("utf-8")
    data_bs = cached_source("funnotbun_base_stats_c").decode("utf-8")
    legacy = _parse_species_types(data_h, data_bs)  # historical drift control, never the output authority
    catalog = json.loads((CANONICAL_OUTPUT.parent / "rr_species.json").read_text(encoding="utf-8"))
    species_types, provenance = types_from_rom(load_rom(args.rom), catalog)
    provenance["legacy_differences"] = {str(sid): {"community": list(legacy[sid]) if sid in legacy else None,
                                                  "rom_canonical": list(pair)}
                                        for sid,pair in species_types.items() if legacy.get(sid) != pair}
    print(f"  Parsed types for {len(species_types)} species")

    json_out = {str(k): list(v) for k, v in sorted(species_types.items())}
    regen = json.dumps(json_out, separators=(",", ":"))
    proof = json.dumps(provenance, indent=2)+"\n"

    if args.check:
        committed = CANONICAL_OUTPUT.read_text(encoding="utf-8")
        if regen == committed and PROVENANCE_OUTPUT.exists() and PROVENANCE_OUTPUT.read_text(encoding="utf-8") == proof:
            print(f"OK: regenerated output matches {CANONICAL_OUTPUT} byte-for-byte "
                  f"({len(json_out)} species).")
            return 0
        print(f"DRIFT: regenerated output ({len(regen)} bytes) != "
              f"{CANONICAL_OUTPUT} ({len(committed)} bytes)\n"
              f"{diff_snippet(committed, regen)}", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(regen)
    PROVENANCE_OUTPUT.write_text(proof, encoding="utf-8", newline="\n")
    print(f"Wrote {len(json_out)} entries to {OUTPUT} "
          f"({os.path.getsize(OUTPUT)} bytes)")

    # Print a few samples for verification
    print("\nSample entries:")
    samples = [
        ("Teddiursa-Sevii", 1278),
        ("Ursaring-Sevii", 1279),
        ("Vulpix-Alola", 1025),
        ("Zorua-Hisui", 1280),
        ("Kingambit", 936),
        ("Bulbasaur", 1),
    ]
    type_names = {v: k.replace("TYPE_", "") for k, v in TYPE_MAP.items()}
    for label, sid in samples:
        pair = species_types.get(sid)
        if pair:
            print(f"  {sid:>5} {label:25s} → {type_names.get(pair[0],'?')}/{type_names.get(pair[1],'?')} {pair}")
        else:
            print(f"  {sid:>5} {label:25s} → NOT FOUND")

    return 0


if __name__ == "__main__":
    sys.exit(main())
