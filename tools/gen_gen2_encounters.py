#!/usr/bin/env python3
"""Generate Gen 2 wild encounter tables from pret/pokecrystal raw asm.

Reads:
    .cache/pret/pokecrystal/data/wild/johto_grass.asm
    .cache/pret/pokecrystal/data/wild/kanto_grass.asm
    .cache/pret/pokecrystal/data/wild/johto_water.asm
    .cache/pret/pokecrystal/data/wild/kanto_water.asm
    data/games/gen2_crystal/area_map.json

Writes:
    data/games/gen2_crystal/encounter_tables.json

Gen 2 species constants ARE NatDex (1..251) — no internal-index translation needed.

Grass slot percentages: 30, 30, 20, 10, 5, 4, 1 (sum = 100).
Water slot percentages: 60, 30, 10.
Each map has 3 grass tables (morn/day/nite); we emit them as separate methods.

Multi-floor dungeons (UNION_CAVE_1F, UNION_CAVE_B1F, ...) collapse to the same
canonical area_id (e.g. "union_cave") via the area_map. First-wins: the first
floor encountered is the one we publish.
"""
from __future__ import annotations
import json
import os
import re
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_THIS_DIR, ".."))
_PRET = os.path.join(_REPO, ".cache", "pret", "pokecrystal")
_OUT = os.path.join(_REPO, "data", "games", "gen2_crystal", "encounter_tables.json")
_AREA_MAP = os.path.join(_REPO, "data", "games", "gen2_crystal", "area_map.json")

GRASS_RATES = [30, 30, 20, 10, 5, 4, 1]  # 7 slots
WATER_RATES = [60, 30, 10]               # 3 slots

# Special-character species display names
SPECIES_DISPLAY_OVERRIDES = {
    "NIDORAN_F":   "Nidoran♀",
    "NIDORAN_M":   "Nidoran♂",
    "FARFETCH_D":  "Farfetch'd",
    "MR__MIME":    "Mr. Mime",
    "MR_MIME":     "Mr. Mime",
    "HO_OH":       "Ho-Oh",
    "PORYGON2":    "Porygon2",
    "JYNX":        "Jynx",
    "MIME_JR":     "Mime Jr.",  # not in gen2 but harmless
}


def pret_const_to_area_id(pret_const: str, known_area_ids: set[str]) -> str | None:
    """Map a pret map constant (ROUTE_29, SPROUT_TOWER_2F, UNION_CAVE_B1F, …)
    to a canonical area_id in known_area_ids by stripping floor / section suffixes.

    Returns None if no match could be derived.
    """
    name = pret_const.lower()
    # Try direct match first
    if name in known_area_ids:
        return name
    # Strip suffixes in priority order
    suffixes = [
        "_b3f", "_b2f", "_b1f",
        "_1f", "_2f", "_3f", "_4f", "_5f", "_6f", "_7f", "_8f", "_9f", "_10f",
        "_outside", "_inside",
        "_violet_entrance", "_blackthorn_entrance",
        "_mahogany_side", "_blackthorn_side",
        "_b2f_mahogany_side", "_b2f_blackthorn_side",
        "_nw", "_sw", "_ne", "_se",
        "_room_1", "_room_2", "_room_3",
        "_item_rooms", "_square",
        "_pokecenter_1f",
    ]
    # Try stripping any matching suffix
    for suf in suffixes:
        if name.endswith(suf):
            candidate = name[: -len(suf)]
            if candidate in known_area_ids:
                return candidate
    # Bespoke special cases
    special = {
        "whirl_island_nw": "whirl_islands",
        "whirl_island_sw": "whirl_islands",
        "whirl_island_ne": "whirl_islands",
        "whirl_island_se": "whirl_islands",
        "whirl_island_b1f": "whirl_islands",
        "whirl_island_b2f": "whirl_islands",
        "whirl_island_cave": "whirl_islands",
        "whirl_island_lugia_chamber": "whirl_islands",
        "mount_moon": "mt_moon",
        "mount_mortar_1f_inside": "mt_mortar",
        "mount_mortar_1f_outside": "mt_mortar",
        "mount_mortar_2f_inside": "mt_mortar",
        "mount_mortar_b1f": "mt_mortar",
        "olivine_port": "olivine_city",
        "vermilion_port": "vermilion_city",
        "route_10_north": "route_10",
        "silver_cave_room_1": "silver_cave",
        "silver_cave_room_2": "silver_cave",
        "silver_cave_room_3": "silver_cave",
        "silver_cave_item_rooms": "silver_cave",
        "mt_silver_outside": "silver_cave",
        "ruins_of_alph_outside": "ruins_of_alph",
        "ruins_of_alph_kabuto_chamber": "ruins_of_alph",
        "ruins_of_alph_omanyte_chamber": "ruins_of_alph",
        "ruins_of_alph_aerodactyl_chamber": "ruins_of_alph",
        "ruins_of_alph_ho_oh_chamber": "ruins_of_alph",
        "ruins_of_alph_inner_chamber": "ruins_of_alph",
        "ruins_of_alph_research_center": "ruins_of_alph",
        "dark_cave_violet_entrance": "dark_cave",
        "dark_cave_blackthorn_entrance": "dark_cave",
        "mt_mortar_1f_outside": "mt_mortar",
        "mt_mortar_1f_inside": "mt_mortar",
        "mt_mortar_2f_inside": "mt_mortar",
        "mt_mortar_b1f": "mt_mortar",
        "slowpoke_well_b1f": "slowpoke_well",
        "slowpoke_well_b2f": "slowpoke_well",
        "burned_tower_1f": "burned_tower",
        "burned_tower_b1f": "burned_tower",
        "ice_path_1f": "ice_path",
        "ice_path_b1f": "ice_path",
        "ice_path_b2f_mahogany_side": "ice_path",
        "ice_path_b2f_blackthorn_side": "ice_path",
        "ice_path_b3f": "ice_path",
        "ice_path_b3f_2": "ice_path",
        "tin_tower_1f": "tin_tower",
        "tin_tower_2f": "tin_tower",
        "tin_tower_3f": "tin_tower",
        "tin_tower_4f": "tin_tower",
        "tin_tower_5f": "tin_tower",
        "tin_tower_6f": "tin_tower",
        "tin_tower_7f": "tin_tower",
        "tin_tower_8f": "tin_tower",
        "tin_tower_9f": "tin_tower",
        "mt_moon_square": "mt_moon",
        "mt_moon": "mt_moon",
        "sprout_tower_1f": "sprout_tower",
        "sprout_tower_2f": "sprout_tower",
        "sprout_tower_3f": "sprout_tower",
        "dragons_den_b1f": "dragons_den",
        "dragons_den_1f": "dragons_den",
        "victory_road": "victory_road",
        "cerulean_cave_1f": "cerulean_cave",  # not in current area_map; fallback
        "cerulean_cave_2f": "cerulean_cave",
        "cerulean_cave_b1f": "cerulean_cave",
        "rock_tunnel_1f": "rock_tunnel",
        "rock_tunnel_b1f": "rock_tunnel",
        "tohjo_falls": "tohjo_falls",
    }
    if name in special:
        # Allow even if not in known_area_ids — generates a new area_id entry
        return special[name]
    return None


def species_display_name(species_const: str) -> str:
    if species_const in SPECIES_DISPLAY_OVERRIDES:
        return SPECIES_DISPLAY_OVERRIDES[species_const]
    return species_const.title().replace("_", " ")


def parse_grass_asm(path: str) -> list[dict]:
    """Parse johto_grass.asm or kanto_grass.asm.

    Returns list of {map_const, rates: (morn, day, nite), entries: {morn:[],day:[],nite:[]}}
    """
    out: list[dict] = []
    current = None
    section = None  # 'morn' | 'day' | 'nite' | None
    section_order = ["morn", "day", "nite"]
    section_idx = 0

    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    rate_pattern = re.compile(
        r"^db\s+(\d+)\s*percent\s*,\s*(\d+)\s*percent\s*,\s*(\d+)\s*percent"
    )

    for raw in lines:
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^def_grass_wildmons\s+([A-Z_0-9]+)\s*$", line)
        if m:
            current = {"map_const": m.group(1), "rates": (0, 0, 0),
                       "morn": [], "day": [], "nite": []}
            section_idx = 0
            section = None
            continue
        if line == "end_grass_wildmons":
            if current:
                out.append(current)
            current = None
            section = None
            continue
        if current is None:
            continue
        m = rate_pattern.match(line)
        if m:
            current["rates"] = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            section = section_order[0]
            section_idx = 0
            continue
        m = re.match(r"^db\s+(\d+)\s*,\s*([A-Z_0-9]+)\s*$", line)
        if m and section is not None:
            current[section].append((int(m.group(1)), m.group(2)))
            if len(current[section]) == 7 and section_idx < 2:
                section_idx += 1
                section = section_order[section_idx]
    return out


def parse_water_asm(path: str) -> list[dict]:
    """Parse johto_water.asm or kanto_water.asm.

    Returns list of {map_const, rate, entries: [(level, species_const), ...]}.
    """
    out: list[dict] = []
    current = None
    rate_pattern = re.compile(r"^db\s+(\d+)\s*percent")

    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    for raw in lines:
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^def_water_wildmons\s+([A-Z_0-9]+)\s*$", line)
        if m:
            current = {"map_const": m.group(1), "rate": 0, "entries": []}
            continue
        if line == "end_water_wildmons":
            if current:
                out.append(current)
            current = None
            continue
        if current is None:
            continue
        m = rate_pattern.match(line)
        if m and current["rate"] == 0:
            current["rate"] = int(m.group(1))
            continue
        m = re.match(r"^db\s+(\d+)\s*,\s*([A-Z_0-9]+)\s*$", line)
        if m:
            current["entries"].append((int(m.group(1)), m.group(2)))
    return out


def aggregate_slots(entries: list[tuple[int, str]], slot_rates: list[int]) -> list[dict]:
    """Collapse N-slot list to per-species rate + min/max level."""
    by_species: dict[str, dict] = {}
    for slot, (level, sp) in enumerate(entries):
        if sp in ("NO_MON",):
            continue
        rate = slot_rates[slot] if slot < len(slot_rates) else 0
        if sp not in by_species:
            by_species[sp] = {"_const": sp, "rate": 0, "min_level": level, "max_level": level}
        cur = by_species[sp]
        cur["rate"] += rate
        cur["min_level"] = min(cur["min_level"], level)
        cur["max_level"] = max(cur["max_level"], level)
    return list(by_species.values())


def build_method_entries(aggregated: list[dict]) -> list[dict]:
    out = []
    for e in aggregated:
        # Gen 2 species constants are NatDex (1..251). Most uppercase names
        # map directly via .title() — overrides handle special chars.
        out.append({
            "species_id": _species_const_to_natdex(e["_const"]),
            "name": species_display_name(e["_const"]),
            "rate": e["rate"],
            "min_level": e["min_level"],
            "max_level": e["max_level"],
        })
    out = [x for x in out if x["species_id"]]
    out.sort(key=lambda x: (-x["rate"], x["species_id"]))
    return out


_SPECIES_NATDEX_CACHE: dict[str, int] = {}


def _species_const_to_natdex(const: str) -> int:
    """Resolve pret species constant to NatDex by parsing pokemon_constants.asm.

    Gen 2 const_def starts at 1 with BULBASAUR; const_skip increments without
    naming. Result is cached.
    """
    if not _SPECIES_NATDEX_CACHE:
        path = os.path.join(_PRET, "constants", "pokemon_constants.asm")
        with open(path, encoding="utf-8") as f:
            idx = -1
            for line in f:
                line = line.split(";", 1)[0].strip()
                m = re.match(r"^const_def\s+(\d+)\s*$", line)
                if m:
                    idx = int(m.group(1))
                    continue
                if line == "const_def":
                    idx = 0
                    continue
                if line == "const_skip":
                    if idx >= 0:
                        idx += 1
                    continue
                m = re.match(r"^const\s+([A-Z_0-9]+)\s*$", line)
                if m and idx >= 0:
                    _SPECIES_NATDEX_CACHE[m.group(1)] = idx
                    idx += 1
    return _SPECIES_NATDEX_CACHE.get(const, 0)


def main() -> int:
    if not os.path.exists(_PRET):
        sys.stderr.write(f"Missing pret repo at {_PRET}\n"
                         "Run tools/build_pret_syms.py first to clone it.\n")
        return 1

    with open(_AREA_MAP, encoding="utf-8") as f:
        area_map = json.load(f)
    known_area_ids = set()
    for v in area_map.values():
        if isinstance(v, dict) and "area_id" in v:
            known_area_ids.add(v["area_id"])

    # Parse all 4 source files
    grass = (parse_grass_asm(os.path.join(_PRET, "data", "wild", "johto_grass.asm"))
             + parse_grass_asm(os.path.join(_PRET, "data", "wild", "kanto_grass.asm")))
    water = (parse_water_asm(os.path.join(_PRET, "data", "wild", "johto_water.asm"))
             + parse_water_asm(os.path.join(_PRET, "data", "wild", "kanto_water.asm")))

    areas: dict[str, dict[str, list[dict]]] = {}
    unmapped: list[str] = []
    skipped_species: set[str] = set()

    for g in grass:
        area_id = pret_const_to_area_id(g["map_const"], known_area_ids)
        if not area_id:
            unmapped.append(g["map_const"])
            continue
        if area_id in areas and any(m in areas[area_id] for m in ("Morn", "Day", "Nite")):
            continue  # first-wins per area
        block = areas.setdefault(area_id, {})
        for tod_key, tod_label in (("morn", "Morn"), ("day", "Day"), ("nite", "Nite")):
            entries = g[tod_key]
            if not entries:
                continue
            agg = aggregate_slots(entries, GRASS_RATES)
            method_entries = build_method_entries(agg)
            for sp in [e["_const"] for e in agg if not _species_const_to_natdex(e["_const"])]:
                skipped_species.add(sp)
            if method_entries:
                block[tod_label] = method_entries

    for w in water:
        area_id = pret_const_to_area_id(w["map_const"], known_area_ids)
        if not area_id:
            unmapped.append(w["map_const"])
            continue
        block = areas.setdefault(area_id, {})
        if "Surf" in block:
            continue
        if not w["entries"]:
            continue
        agg = aggregate_slots(w["entries"], WATER_RATES)
        method_entries = build_method_entries(agg)
        if method_entries:
            block["Surf"] = method_entries

    out = {
        "_comment": ("Gen 2 Crystal wild encounter tables generated from "
                     "pret/pokecrystal data/wild/{johto,kanto}_{grass,water}.asm. "
                     "Methods: Morn/Day/Nite (grass time-of-day) and Surf (water). "
                     "Each entry has species_id (NatDex), name, rate (per-species %, "
                     "sum ≤ 100), min_level, max_level. Generated by "
                     "tools/gen_gen2_encounters.py. Fishing tables (Old/Good/Super Rod) "
                     "use a separate fishgroup table and are not currently included."),
        "areas": areas,
    }
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {_OUT}")
    print(f"  {len(areas)} areas covered")
    if unmapped:
        unique = sorted(set(unmapped))
        print(f"  {len(unique)} unmapped pret consts (need area_map entry):")
        for x in unique:
            print(f"    {x}")
    if skipped_species:
        print(f"  {len(skipped_species)} species skipped (no const match):")
        for sp in sorted(skipped_species):
            print(f"    {sp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
