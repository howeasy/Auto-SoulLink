#!/usr/bin/env python3
"""Generate Gen 1 wild encounter tables from pret/pokered raw asm.

Reads:
    .cache/pret/pokered/data/wild/grass_water.asm          (map_id → label)
    .cache/pret/pokered/data/wild/maps/*.asm               (per-map encounter slots)
    .cache/pret/pokered/constants/pokemon_constants.asm    (species name → internal idx)
    data/games/gen1_rby/area_map.json                      (map_id → area_id)
    data/games/gen1_rby/species_index.json                 (internal idx → NatDex)

Writes:
    data/games/gen1_rby/encounter_tables.json

Slot percentages per pret/data/wild/probabilities.asm:
    slot 0,1: 20%   slot 2: 15%   slots 3-5: 10%   slots 6-7: 5%   slot 8: 4%   slot 9: 1%

Per-species rates are summed across all slots the species occupies.
Min/max levels are min/max across those slots.
"""
from __future__ import annotations
import json
import os
import re
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_THIS_DIR, ".."))
_PRET = os.path.join(_REPO, ".cache", "pret", "pokered")
_PRET_YELLOW = os.path.join(_REPO, ".cache", "pret", "pokeyellow")
_OUT = os.path.join(_REPO, "data", "games", "gen1_rby", "encounter_tables.json")
_AREA_MAP = os.path.join(_REPO, "data", "games", "gen1_rby", "area_map.json")
_SPECIES_INDEX = os.path.join(_REPO, "data", "games", "gen1_rby", "species_index.json")

SLOT_RATES = [20, 20, 15, 10, 10, 10, 5, 5, 4, 1]  # must sum to 100

# Species constants with non-trivial display names (special characters etc.)
SPECIES_DISPLAY_OVERRIDES = {
    "NIDORAN_F": "Nidoran♀",
    "NIDORAN_M": "Nidoran♂",
    "FARFETCH_D": "Farfetch'd",
    "MR_MIME": "Mr. Mime",
    "MRMIME": "Mr. Mime",
}


def parse_pokemon_constants(path: str) -> dict[str, int]:
    """SPECIES_NAME → internal index (0..190).

    pret pokemon_constants.asm uses `const_def` (starts at $00 with NO_MON)
    followed by `const NAME` declarations that increment by 1. `const_skip`
    is a MissingNo placeholder that also increments the index without
    registering a name.
    """
    out: dict[str, int] = {}
    idx = -1
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split(";", 1)[0].strip()
            if line == "const_def":
                idx = 0
                continue
            if line == "const_skip":
                if idx >= 0:
                    idx += 1
                continue
            m = re.match(r"^const\s+([A-Z_0-9]+)\s*$", line)
            if m and idx >= 0:
                out[m.group(1)] = idx
                idx += 1
    return out


def parse_wild_pointers(path: str) -> list[tuple[int, str]]:
    """Return list of (map_id, label_symbol) for each `dw Foo` in WildDataPointers.

    Stops at the `assert_table_length NUM_MAPS` line.
    """
    out: list[tuple[int, str]] = []
    in_table = False
    idx = 0
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split(";", 1)[0].strip()
            if line.startswith("WildDataPointers"):
                in_table = True
                continue
            if not in_table:
                continue
            if line.startswith("assert_table_length"):
                break
            m = re.match(r"^dw\s+([A-Za-z_0-9]+)\s*$", line)
            if m:
                out.append((idx, m.group(1)))
                idx += 1
    return out


def find_map_asm(label: str, repo: str = _PRET) -> str | None:
    """Resolve a wild label (e.g. Route1WildMons) to its .asm path."""
    name = label[: -len("WildMons")] if label.endswith("WildMons") else label
    candidate = os.path.join(repo, "data", "wild", "maps", f"{name}.asm")
    if os.path.exists(candidate):
        return candidate
    return None


_IF_DEF_RE = re.compile(r"^IF\s+DEF\(\s*([A-Za-z_0-9]+)\s*\)\s*$")


def parse_map_asm(path: str, defines: frozenset[str] = frozenset()
                  ) -> tuple[int, list[tuple[int, str]], int, list[tuple[int, str]]]:
    """Parse one wild map .asm. Returns (grass_rate, grass_entries, water_rate, water_entries).

    Each entry is (level, species_const). A slot table is exactly 10 entries when present.

    34 of pokered's 59 wild maps split their table with `IF DEF(_RED)` / `IF DEF(_BLUE)`,
    so `defines` selects the branch to keep. Ignoring the directives concatenated BOTH
    branches — Route 2 yielded 15 slots instead of 10, and since aggregate() maps slot
    index to a fixed rate, every species past the split got the wrong rate (or none) and
    Red's table was contaminated with Blue's exclusives. pokeyellow has no conditionals.
    """
    grass_rate = 0
    water_rate = 0
    grass: list[tuple[int, str]] = []
    water: list[tuple[int, str]] = []
    section = None  # 'grass' | 'water' | None
    cond_stack: list[bool] = []   # one entry per open IF; False = branch not taken
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            m = _IF_DEF_RE.match(line)
            if m:
                cond_stack.append(m.group(1) in defines)
                continue
            if line == "ENDC":
                if cond_stack:
                    cond_stack.pop()
                continue
            if line == "ELSE":
                if cond_stack:
                    cond_stack[-1] = not cond_stack[-1]
                continue
            if not all(cond_stack):
                continue
            m = re.match(r"^def_grass_wildmons\s+(\d+)\s*$", line)
            if m:
                grass_rate = int(m.group(1))
                section = "grass"
                continue
            m = re.match(r"^def_water_wildmons\s+(\d+)\s*$", line)
            if m:
                water_rate = int(m.group(1))
                section = "water"
                continue
            if line == "end_grass_wildmons" or line == "end_water_wildmons":
                section = None
                continue
            m = re.match(r"^db\s+(\d+)\s*,\s*([A-Z_0-9]+)\s*$", line)
            if m and section is not None:
                level = int(m.group(1))
                species = m.group(2)
                (grass if section == "grass" else water).append((level, species))
    return grass_rate, grass, water_rate, water


def species_display_name(species_const: str) -> str:
    if species_const in SPECIES_DISPLAY_OVERRIDES:
        return SPECIES_DISPLAY_OVERRIDES[species_const]
    return species_const.title().replace("_", " ")


def aggregate(entries: list[tuple[int, str]]) -> list[dict]:
    """Collapse 10-slot list to per-species rate + min/max levels.

    Drops MISSINGNO entries (species_const == "MISSINGNO") and NO_MON.
    """
    by_species: dict[str, dict] = {}
    for slot, (level, sp) in enumerate(entries):
        if sp in ("NO_MON", "MISSINGNO"):
            continue
        rate = SLOT_RATES[slot] if slot < len(SLOT_RATES) else 0
        if sp not in by_species:
            by_species[sp] = {"_const": sp, "rate": 0, "min_level": level, "max_level": level}
        cur = by_species[sp]
        cur["rate"] += rate
        cur["min_level"] = min(cur["min_level"], level)
        cur["max_level"] = max(cur["max_level"], level)
    return list(by_species.values())


def build_variant(repo: str, defines: frozenset[str], index_to_natdex: dict[int, int],
                  map_id_to_area: dict[int, str]) -> tuple[dict, list, set]:
    """Encounter tables for ONE game version. Returns (areas, skipped_areas, skipped_species)."""
    species_consts = parse_pokemon_constants(
        os.path.join(repo, "constants", "pokemon_constants.asm")
    )
    pointers = parse_wild_pointers(os.path.join(repo, "data", "wild", "grass_water.asm"))

    # First-wins: collapse multi-floor dungeons to canonical area_id
    areas: dict[str, dict] = {}
    skipped_unknown_area: list[tuple[int, str]] = []
    skipped_unknown_species: set[str] = set()

    for map_id, label in pointers:
        if label == "NothingWildMons":
            continue
        area_id = map_id_to_area.get(map_id)
        if not area_id:
            skipped_unknown_area.append((map_id, label))
            continue
        if area_id in areas:
            # First-wins; later floors of the same area are skipped.
            continue
        asm_path = find_map_asm(label, repo)
        if not asm_path:
            sys.stderr.write(f"WARN: no asm for label {label} (map_id {map_id})\n")
            continue
        grass_rate, grass, water_rate, water = parse_map_asm(asm_path, defines)

        block: dict[str, list[dict]] = {}
        for method, rate, entries in (("Grass", grass_rate, grass),
                                       ("Water", water_rate, water)):
            if rate == 0 or not entries:
                continue
            agg = aggregate(entries)
            method_entries = []
            for e in agg:
                idx = species_consts.get(e["_const"])
                if idx is None:
                    skipped_unknown_species.add(e["_const"])
                    continue
                natdex = index_to_natdex.get(idx)
                if not natdex:
                    skipped_unknown_species.add(e["_const"])
                    continue
                method_entries.append({
                    "species_id": natdex,
                    "name": species_display_name(e["_const"]),
                    "rate": e["rate"],
                    "min_level": e["min_level"],
                    "max_level": e["max_level"],
                })
            if method_entries:
                method_entries.sort(key=lambda x: (-x["rate"], x["species_id"]))
                block[method] = method_entries
        if block:
            areas[area_id] = block

    return areas, skipped_unknown_area, skipped_unknown_species


# variant -> (repo path, rgbasm defines). Yellow is its own decomp and has no conditionals.
VARIANTS = {
    "red":    (_PRET, frozenset({"_RED"})),
    "blue":   (_PRET, frozenset({"_BLUE"})),
    "yellow": (_PRET_YELLOW, frozenset()),
}


def _check_rates(variant: str, areas: dict) -> list[str]:
    """Each method block must sum to 100% and carry no zero-rate species.

    A blended table shows up here immediately: extra slots push the sum past 100, and a
    species that only occupied slots in the branch we dropped lands at rate 0.
    """
    problems = []
    for area_id, block in areas.items():
        for method, entries in block.items():
            total = sum(e["rate"] for e in entries)
            if total != 100:
                problems.append(f"{variant}/{area_id}/{method}: rates sum to {total}, expected 100")
            for e in entries:
                if e["rate"] <= 0:
                    problems.append(f"{variant}/{area_id}/{method}: {e['name']} has rate {e['rate']}")
    return problems


def main() -> int:
    for path in {repo for repo, _ in VARIANTS.values()}:
        if not os.path.exists(path):
            sys.stderr.write(f"Missing pret repo at {path}\n"
                             "Run tools/build_pret_syms.py first to clone it.\n")
            return 1

    with open(_AREA_MAP, encoding="utf-8") as f:
        area_map = json.load(f)
    with open(_SPECIES_INDEX, encoding="utf-8") as f:
        sidx = json.load(f)
    index_to_natdex = {int(k): v for k, v in sidx["index_to_national"].items()}
    map_id_to_area = {int(k): v["area_id"] for k, v in area_map.items() if isinstance(v, dict)}

    out: dict[str, dict] = {}
    problems: list[str] = []
    for variant, (repo, defines) in VARIANTS.items():
        areas, skipped_area, skipped_species = build_variant(
            repo, defines, index_to_natdex, map_id_to_area)
        out[variant] = areas
        problems += _check_rates(variant, areas)
        print(f"{variant}: {len(areas)} areas")
        if skipped_area:
            print(f"  {len(skipped_area)} maps skipped (no area_id mapping): "
                  + ", ".join(f"{lbl}({mid})" for mid, lbl in skipped_area))
        if skipped_species:
            print(f"  {len(skipped_species)} species skipped: {', '.join(sorted(skipped_species))}")

    if problems:
        sys.stderr.write("REFUSING TO WRITE — rate validation failed:\n")
        for p in problems[:40]:
            sys.stderr.write(f"  {p}\n")
        if len(problems) > 40:
            sys.stderr.write(f"  ... and {len(problems) - 40} more\n")
        return 1

    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {_OUT} (per-variant: {', '.join(out)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
