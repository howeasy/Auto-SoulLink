"""Generate SPECIES_TYPES dict for server/pokemon_data.py from RR Base_Stats.c.

Parses Base_Stats.c and species.h from funnotbun/funnotbun.github.io to build
a mapping of every RR species internal ID to its (type1, type2) tuple using
Gen III type byte values.

Usage:
    python tools/gen_rr_types.py

Outputs data/rr_types.json and prints a Python dict literal for pasting into
pokemon_data.py as SPECIES_TYPES.

Both sources used to be fetched live from funnotbun/funnotbun.github.io,
which no longer exists on GitHub (confirmed 404, 2026-09-26). This now reads
byte-for-byte pinned Wayback Machine captures declared in
data/gen3_rr_sources.lock.json (funnotbun_base_stats_c, funnotbun_species_h).
See docs/gen3_requirements.md row F-7 and tools/fetch_rr_sources.py.

Usage:
    python tools/gen_rr_types.py            # regenerate data/rr_types.json
    python tools/gen_rr_types.py --check     # regenerate in memory and diff
                                               # against the committed
                                               # data/games/gen3_frlge/rr_types.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_rr_sources import cached_source, diff_snippet  # noqa: E402

CANONICAL_OUTPUT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) \
    / "data" / "games" / "gen3_frlge" / "rr_types.json"
# The non-check write target -- kept identical to CANONICAL_OUTPUT so
# `python tools/gen_rr_types.py` (no --check) actually updates the file
# server/pokemon_data.py loads and --check compares against, instead of a
# stray CWD-relative data/rr_types.json nothing reads.
OUTPUT = str(CANONICAL_OUTPUT)

# Gen III type constants (from pret/pokefirered include/constants/pokemon.h)
# CFRU adds TYPE_FAIRY = 0x12 (18)
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
    parser.add_argument("--check", action="store_true",
                        help="Regenerate in memory and diff against the "
                             f"committed {CANONICAL_OUTPUT}; exit 1 on drift.")
    args = parser.parse_args()

    data_h = cached_source("funnotbun_species_h").decode("utf-8")
    data_bs = cached_source("funnotbun_base_stats_c").decode("utf-8")
    species_types = _parse_species_types(data_h, data_bs)
    print(f"  Parsed types for {len(species_types)} species")

    json_out = {str(k): list(v) for k, v in sorted(species_types.items())}
    regen = json.dumps(json_out, separators=(",", ":"))

    if args.check:
        committed = CANONICAL_OUTPUT.read_text(encoding="utf-8")
        if regen == committed:
            print(f"OK: regenerated output matches {CANONICAL_OUTPUT} byte-for-byte "
                  f"({len(json_out)} species).")
            return 0
        print(f"DRIFT: regenerated output ({len(regen)} bytes) != "
              f"{CANONICAL_OUTPUT} ({len(committed)} bytes)\n"
              f"{diff_snippet(committed, regen)}", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        f.write(regen)
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

    # Generate Python dict literal for SPECIES_TYPES
    py_out = os.path.join(os.path.dirname(OUTPUT), "rr_types_dict.txt")
    with open(py_out, "w") as f:
        f.write("# Auto-generated by tools/gen_rr_types.py — do not edit manually.\n")
        f.write("# Maps RR internal species ID -> (type1, type2) using Gen III type byte values.\n")
        f.write("SPECIES_TYPES: dict[int, tuple[int, int]] = {\n")
        items = sorted(species_types.items())
        for i, (sid, (t1, t2)) in enumerate(items):
            sep = "," if i < len(items) - 1 else ""
            f.write(f"    {sid}:({t1},{t2}){sep}\n")
        f.write("}\n")
    print(f"\nPython dict written to {py_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
