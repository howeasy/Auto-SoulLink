#!/usr/bin/env python3
"""Generate data/games/gen1_purergb/{area_map,floor_labels}.json from pureRGB source.

pureRGB renumbers every map id and adds 18 new maps (§3.5 of docs/purergb/PLAN.md), so the
old JSON->Lua area-map converter (deleted in 21ff0d7) has no equivalent for a second
foundation: this tool derives the map entirely from pureRGB's own `constants/map_constants.asm`
plus its wild-encounter tables, the same way `tools/gen_gen1_encounters.py` already derives
per-map wild data for pret.

Rule (decision 4 + owner ruling U10, docs/purergb/PLAN.md §0/§13): "area granularity follows
vanilla's dungeon collapse" -- read literally against vanilla's OWN `area_map.json` +
`floor_labels.json` (not just the five buildings U10's prose names), vanilla collapses NINE
multi-floor buildings into one shared area id each: Mt. Moon, Rock Tunnel, Seafoam Islands,
Victory Road, Pokemon Tower (U10's named five) plus Pokemon Mansion, Cerulean Cave, Rocket
Hideout and Silph Co. (confirmed by reading the real vanilla file: e.g. its `"165"/"214"/"215"/
"216"` rows all share `"area_id": "pokemon_mansion"` and all four get a `floor_labels.json`
suffix, exactly like Mt. Moon's three floors do). This tool follows the same nine-building set:
  1. Every map with a non-empty grass/water wild table, or a fishing spot (an `OceanMaps` /
     `SuperRodData` entry), is its own area -- EXCEPT a floor belonging to one of the nine
     buildings above, which collapses onto that building's one shared area id. The floor
     identity is carried by `floor_labels.json` + the encounter generator's method-name suffix
     ("Grass B1F"), never by splitting the area id -- and, matching vanilla exactly, a floor
     only gets a suffix when it is the building's *own* wild-data pointer (not the shared
     `NothingWildMons` sentinel every trainer-only floor of Rocket Hideout/Silph Co points at,
     which is why those two buildings collapse to one area with NO floor_labels rows at all).
  2. Safari Zone's four quadrants (East/North/West/Center) do NOT collapse -- U10 says they
     "stay one area each", matching vanilla's actual `safari_zone_{east,north,west,center}`
     rows -- so no special-casing is needed: each quadrant already has its own wild table.
  3. Every other map (a house, gym, cave with no table, etc.) inherits its parent town/route's
     area id for display, by constant-name prefix/route-number/city-token matching, with a
     small hand table for names that carry no derivable prefix (mirrors vanilla's own set of
     un-derivable interiors: Oak's Lab, S.S. Anne, the Elite Four rooms, ...).

Unlike vanilla's hand-maintained file (which only lists ~88 "interesting" ids), this generator
emits a `display_name` for all 248 map ids, so a client can label any map it lands on.

Overrides that could not be derived from the constant name alone are recorded in the sibling
`area_map_notes.json` (kept OUT of area_map.json itself: that file's shape --
`{"<map_id>": {"area_id", "name"}}` -- is a load-bearing contract other code indexes by
`int(map_id)`, and a stray non-numeric key would break that walk).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tools.gen1_foundation as gf  # noqa: E402

FOUNDATION = "purergb"
NUM_MAPS = 248
EXPECTED_AREAS_BEFORE_COLLAPSE = 69  # W1 census: 66 grass/water tables + 3 fishing-only maps

_OUT_AREA = gf.data_dir(FOUNDATION) / "area_map.json"
_OUT_FLOORS = gf.data_dir(FOUNDATION) / "floor_labels.json"
_OUT_NOTES = gf.data_dir(FOUNDATION) / "area_map_notes.json"

# Multi-floor dungeons that collapse to one area id (U10). Order of `floors` is display order,
# not gameplay order; `pokecenter` is a rest-stop map given its OWN area id, matching vanilla's
# `mt_moon_pokecenter`/`rock_tunnel_pokecenter` treatment -- not folded into any single floor.
DUNGEON_GROUPS = {
    "mt_moon": {
        "name": "Mt. Moon",
        "floors": ["MT_MOON_1F", "MT_MOON_B1F", "MT_MOON_B2F"],
        "pokecenter": "MT_MOON_POKECENTER",
    },
    "rock_tunnel": {
        "name": "Rock Tunnel",
        "floors": ["ROCK_TUNNEL_1F", "ROCK_TUNNEL_B1F"],
        "pokecenter": "ROCK_TUNNEL_POKECENTER",
    },
    "seafoam_islands": {
        "name": "Seafoam Islands",
        "floors": ["SEAFOAM_ISLANDS_1F", "SEAFOAM_ISLANDS_B1F", "SEAFOAM_ISLANDS_B2F",
                   "SEAFOAM_ISLANDS_B3F", "SEAFOAM_ISLANDS_B4F"],
        "pokecenter": None,
    },
    "victory_road": {
        "name": "Victory Road",
        "floors": ["VICTORY_ROAD_1F", "VICTORY_ROAD_2F", "VICTORY_ROAD_3F"],
        "pokecenter": None,
    },
    "pokemon_tower": {
        "name": "Pokemon Tower",
        # B1F has no wild-data pointer of its own (a new pureRGB map, points at the shared
        # NothingWildMons sentinel) -- it still collapses into the group; it just never gets a
        # floor_labels.json suffix, same as any other Nothing-pointer floor.
        "floors": ["POKEMON_TOWER_1F", "POKEMON_TOWER_2F", "POKEMON_TOWER_3F",
                   "POKEMON_TOWER_4F", "POKEMON_TOWER_5F", "POKEMON_TOWER_6F",
                   "POKEMON_TOWER_7F", "POKEMON_TOWER_B1F"],
        "pokecenter": None,
    },
    # Not named in U10's prose, but present in vanilla's real area_map.json/floor_labels.json
    # (its "165"/"214"/"215"/"216" pokemon_mansion rows, each with a floor suffix) -- U10 says
    # "follows vanilla's dungeon collapse", and this is part of that collapse.
    "pokemon_mansion": {
        "name": "Pokemon Mansion",
        "floors": ["POKEMON_MANSION_1F", "POKEMON_MANSION_2F", "POKEMON_MANSION_3F",
                   "POKEMON_MANSION_B1F"],
        "pokecenter": None,
    },
    "cerulean_cave": {
        "name": "Cerulean Cave",
        "floors": ["CERULEAN_CAVE_1F", "CERULEAN_CAVE_2F", "CERULEAN_CAVE_B1F"],
        "pokecenter": None,
    },
    # Rocket Hideout and Silph Co have NO wild-data pointer on any floor (every floor points at
    # the shared NothingWildMons sentinel), so none of them would ever qualify for "own area"
    # under rule 1 and would otherwise fall through to their host city by the generic prefix/
    # city-token rules below -- but vanilla's real file keeps each building as its own area
    # (`"199".."202"` -> `rocket_hideout`, `"181"`+`"207".."213"`+`"233".."235"` -> `silph_co`),
    # distinct from Celadon/Saffron City, presumably so a Soul Link dead-zone doesn't conflate
    # "in the city" with "raiding the hideout". No floor gets a floor_labels.json suffix here
    # (matches vanilla: neither building has any floor_labels rows) since no floor carries its
    # own wild-data pointer to hang a suffix on.
    "rocket_hideout": {
        "name": "Rocket Hideout",
        "floors": ["ROCKET_HIDEOUT_B1F", "ROCKET_HIDEOUT_B2F", "ROCKET_HIDEOUT_B3F",
                   "ROCKET_HIDEOUT_B4F", "ROCKET_HIDEOUT_ELEVATOR"],
        "pokecenter": None,
    },
    "silph_co": {
        "name": "Silph Co.",
        "floors": ["SILPH_CO_1F", "SILPH_CO_2F", "SILPH_CO_3F", "SILPH_CO_4F", "SILPH_CO_5F",
                   "SILPH_CO_6F", "SILPH_CO_7F", "SILPH_CO_8F", "SILPH_CO_9F", "SILPH_CO_10F",
                   "SILPH_CO_11F", "SILPH_CO_ELEVATOR"],
        "pokecenter": None,
    },
}

CITY_TOWN_IDS = list(range(0, 11))
ROUTE_IDS = list(range(12, 37))

DISPLAY_OVERRIDES = {
    "REDS_HOUSE_1F": "Red's House 1F", "REDS_HOUSE_2F": "Red's House 2F",
    "BLUES_HOUSE": "Blue's House", "OAKS_LAB": "Oak's Lab",
    "DIGLETTS_CAVE": "Diglett's Cave", "DIGLETTS_CAVE_ROUTE_2": "Diglett's Cave (Route 2)",
    "DIGLETTS_CAVE_ROUTE_11": "Diglett's Cave (Route 11)",
    "MR_FUJIS_HOUSE": "Mr. Fuji's House", "MR_PSYCHICS_HOUSE": "Mr. Psychic's House",
    "WARDENS_HOUSE": "Warden's House", "COPYCATS_HOUSE_1F": "Copycat's House 1F",
    "COPYCATS_HOUSE_2F": "Copycat's House 2F", "NAME_RATERS_HOUSE": "Name Rater's House",
    "TYPE_GUYS_HOUSE": "Type Guy's House", "FOSSIL_GUYS_HOUSE": "Fossil Guy's House",
    "CHAMPIONS_ROOM": "Champion's Room", "SS_ANNE_1F": "S.S. Anne 1F",
    "SS_ANNE_2F": "S.S. Anne 2F", "SS_ANNE_3F": "S.S. Anne 3F", "SS_ANNE_B1F": "S.S. Anne B1F",
    "SS_ANNE_BOW": "S.S. Anne Bow", "SS_ANNE_KITCHEN": "S.S. Anne Kitchen",
    "SS_ANNE_CAPTAINS_ROOM": "S.S. Anne Captain's Room",
    "SS_ANNE_1F_ROOMS": "S.S. Anne 1F Rooms", "SS_ANNE_2F_ROOMS": "S.S. Anne 2F Rooms",
    "SS_ANNE_B1F_ROOMS": "S.S. Anne B1F Rooms", "LORELEIS_ROOM": "Lorelei's Room",
    "BRUNOS_ROOM": "Bruno's Room", "AGATHAS_ROOM": "Agatha's Room", "LANCES_ROOM": "Lance's Room",
    "CINNABAR_LAB_TRADE_ROOM": "Cinnabar Lab Trade Room",
    "MT_MOON_POKECENTER": "Mt. Moon Pokecenter", "ROCK_TUNNEL_POKECENTER": "Rock Tunnel Pokecenter",
    "BILLS_GARDEN": "Bill's Garden",
}

# Constant name -> parent map id, for interiors with no derivable prefix. Every entry here is
# reported in area_map_notes.json as a `game_knowledge_override`. `None` = no known parent,
# kept as its own id.
GAME_KNOWLEDGE_OVERRIDES: dict[str, int | None] = {
    "GAME_CORNER": 6, "GAME_CORNER_PRIZE_ROOM": 6,
    "FIGHTING_DOJO": 7, "COPYCATS_HOUSE_1F": 7, "COPYCATS_HOUSE_2F": 7,
    "LORELEIS_ROOM": 10, "BRUNOS_ROOM": 10, "AGATHAS_ROOM": 10, "LANCES_ROOM": 10,
    "CHAMPIONS_ROOM": 10, "HALL_OF_FAME": 10, "INDIGO_PLATEAU_LOBBY": 10, "CHAMP_ARENA": 10,
    "TYPE_GUYS_HOUSE": 10,
    "SS_ANNE_1F": 5, "SS_ANNE_2F": 5, "SS_ANNE_3F": 5, "SS_ANNE_B1F": 5,
    "SS_ANNE_BOW": 5, "SS_ANNE_KITCHEN": 5, "SS_ANNE_CAPTAINS_ROOM": 5,
    "SS_ANNE_1F_ROOMS": 5, "SS_ANNE_2F_ROOMS": 5, "SS_ANNE_B1F_ROOMS": 5,
    "POKEMON_FAN_CLUB": 5,
    "MUSEUM_1F": 2, "MUSEUM_2F": 2,
    "BIKE_SHOP": 3, "NAME_RATERS_HOUSE": 3,
    "WARDENS_HOUSE": 8,
    "BILLS_HOUSE": 36,
    "UNDERGROUND_PATH_NORTH_SOUTH": 16, "UNDERGROUND_PATH_WEST_EAST": 18,
    "DAYCARE": 16,
    "SAFARI_ZONE_GATE": 0xDC, "SAFARI_ZONE_SECRET_HOUSE": 0xDC,
    "FOSSIL_GUYS_HOUSE": 9,
    "DIAMOND_MINE": None, "SECRET_LAB": None, "TRADE_CENTER": None, "COLOSSEUM": None,
    "REDS_HOUSE_1F": 0, "REDS_HOUSE_2F": 0, "BLUES_HOUSE": 0, "OAKS_LAB": 0,
    "MR_FUJIS_HOUSE": 4, "MR_PSYCHICS_HOUSE": 19,
}


def parse_map_constants(text: str) -> tuple[dict[int, str], dict[str, int]]:
    id_to_name: dict[int, str] = {}
    name_to_id: dict[str, int] = {}
    idx = 0
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        m = re.match(r"^map_const\s+([A-Z0-9_]+)\s*,", line)
        if m:
            id_to_name[idx] = m.group(1)
            name_to_id[m.group(1)] = idx
            idx += 1
    return id_to_name, name_to_id


_IF_DEF_RE = re.compile(r"^IF\s+DEF\(\s*([A-Za-z_0-9]+)\s*\)\s*$")


def parse_wild_pointers(text: str) -> list[tuple[int, str]]:
    out = []
    in_table = False
    idx = 0
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        if line.startswith("WildDataPointers"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("assert_table_length") or line.startswith("dw -1"):
            break
        m = re.match(r"^dw\s+([A-Za-z_0-9]+)\s*$", line)
        if m:
            out.append((idx, m.group(1)))
            idx += 1
    return out


def parse_map_asm(text: str) -> tuple[int, int]:
    """Return (grass_rate, water_rate); skips the `_DEBUG` branch of a conditional table."""
    grass_rate = water_rate = 0
    cond_stack: list[list] = []
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        if not line:
            continue
        m = _IF_DEF_RE.match(line)
        if m:
            cond_stack.append([m.group(1), False])
            continue
        if line == "ELSE":
            if cond_stack:
                cond_stack[-1][1] = not cond_stack[-1][1]
            continue
        if line == "ENDC":
            if cond_stack:
                cond_stack.pop()
            continue
        if any(not taken for _, taken in cond_stack):
            continue
        m = re.match(r"^def_grass_wildmons\s+(\d+)\s*$", line)
        if m:
            grass_rate = int(m.group(1))
            continue
        m = re.match(r"^def_water_wildmons\s+(\d+)\s*$", line)
        if m:
            water_rate = int(m.group(1))
            continue
    return grass_rate, water_rate


def parse_name_list(text: str, header: str) -> list[str]:
    out = []
    in_table = False
    for line in text.splitlines():
        line = line.split(";", 1)[0].strip()
        if line.startswith(header + ":"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("db -1"):
            break
        m = re.match(r"^db\s+([A-Za-z_0-9]+)\s*$", line)
        if m:
            out.append(m.group(1))
    return out


def snake(name: str) -> str:
    return name.lower()


def display_name(const_name: str) -> str:
    if const_name in DISPLAY_OVERRIDES:
        return DISPLAY_OVERRIDES[const_name]
    if const_name.startswith("UNUSED_MAP_"):
        return "Unused Map " + const_name.split("_")[-1]
    return " ".join(w.capitalize() for w in const_name.split("_"))


def build(root) -> tuple[dict, dict, list]:
    map_text = (root / "constants" / "map_constants.asm").read_text(encoding="utf-8")
    id_to_name, name_to_id = parse_map_constants(map_text)
    if len(id_to_name) != NUM_MAPS:
        raise SystemExit(f"expected {NUM_MAPS} map ids, parsed {len(id_to_name)}")

    wild_text = (root / "data" / "wild" / "grass_water.asm").read_text(encoding="utf-8")
    pointers = parse_wild_pointers(wild_text)
    maps_dir = root / "data" / "wild" / "maps"
    label_to_path = {}
    for p in maps_dir.glob("*.asm"):
        label_to_path[p.stem + "WildMons"] = p
    label_to_path["NothingWildMons"] = maps_dir / "nothing.asm"

    ocean_names = parse_name_list(
        (root / "data" / "maps" / "ocean_maps.asm").read_text(encoding="utf-8"), "OceanMaps")
    ocean_ids = {name_to_id[n] for n in ocean_names if n in name_to_id}

    super_rod_text = (root / "data" / "wild" / "super_rod.asm").read_text(encoding="utf-8")
    super_rod_maps = set()
    for line in super_rod_text.splitlines():
        line = line.split(";", 1)[0].strip()
        m = re.match(r"^dbw\s+([A-Za-z_0-9]+)\s*,\s*\S+\s*$", line)
        if m and m.group(1) in name_to_id:
            super_rod_maps.add(name_to_id[m.group(1)])

    own_area: dict[int, str] = {}
    for map_id, label in pointers:
        if label == "NothingWildMons":
            if map_id in ocean_ids or map_id in super_rod_maps:
                own_area[map_id] = snake(id_to_name[map_id])
            continue
        path = label_to_path.get(label)
        if path is None:
            raise SystemExit(f"map {map_id} ({id_to_name.get(map_id)}): no asm for {label}")
        grass_rate, water_rate = parse_map_asm(path.read_text(encoding="utf-8"))
        if grass_rate > 0 or water_rate > 0 or map_id in ocean_ids or map_id in super_rod_maps:
            own_area[map_id] = snake(id_to_name[map_id])

    if len(own_area) != EXPECTED_AREAS_BEFORE_COLLAPSE:
        raise SystemExit(
            f"expected {EXPECTED_AREAS_BEFORE_COLLAPSE} areas before collapse, "
            f"got {len(own_area)}: {sorted(id_to_name[m] for m in own_area)}")

    # ---- U10 dungeon collapse: fold each group's floors onto one shared area id/name ----
    # A floor earns a floor_labels.json suffix only when it owns a REAL wild-data pointer (not
    # the shared NothingWildMons sentinel) -- matching vanilla exactly: Pokemon Tower's 7 floors
    # and Pokemon Mansion's 4 all get suffixes (each has its own pointer, even at rate 0),
    # Rocket Hideout's 5 and Silph Co.'s 12 get none (every one points at NothingWildMons).
    pointer_label = dict(pointers)
    group_of: dict[int, str] = {}       # map_id -> collapsed area_id
    group_name: dict[str, str] = {}     # area_id -> display name
    floor_suffix: dict[int, str] = {}   # map_id -> " 1F" / " B1F" / ...
    for area_id, spec in DUNGEON_GROUPS.items():
        group_name[area_id] = spec["name"]
        floor_ids = []
        for const in spec["floors"]:
            mid = name_to_id.get(const)
            if mid is None:
                raise SystemExit(f"dungeon group {area_id}: unknown map const {const}")
            group_of[mid] = area_id
            floor_ids.append(mid)
        wild_floor_ids = [mid for mid in floor_ids if pointer_label.get(mid) != "NothingWildMons"]
        multi = len(wild_floor_ids) > 1
        for const, mid in zip(spec["floors"], floor_ids, strict=True):
            if not multi or mid not in wild_floor_ids:
                continue
            floor = const.rsplit("_", 1)[-1]  # "MT_MOON_B1F" -> "B1F"
            floor_suffix[mid] = " " + floor
        pokecenter_const = spec.get("pokecenter")
        if pokecenter_const:
            pc_id = name_to_id[pokecenter_const]
            group_of[pc_id] = snake(pokecenter_const)  # own id, NOT folded into the group
            group_name[snake(pokecenter_const)] = display_name(pokecenter_const)

    own_area_tokens = {tuple(id_to_name[mid].split("_")): mid for mid in own_area}
    route_name_to_id = {id_to_name[mid]: mid for mid in ROUTE_IDS}
    city_first_token = {id_to_name[mid].split("_")[0]: mid for mid in CITY_TOWN_IDS}

    def prefix_match(const_name: str):
        toks = const_name.split("_")
        for plen in range(len(toks) - 1, 0, -1):
            cand = tuple(toks[:plen])
            if cand in own_area_tokens:
                return own_area_tokens[cand]
        return None

    def route_match(const_name: str):
        m = re.search(r"ROUTE_(\d+)", const_name)
        if m:
            return route_name_to_id.get(f"ROUTE_{m.group(1)}")
        return None

    def city_match(const_name: str):
        return city_first_token.get(const_name.split("_")[0])

    result: dict[int, dict] = {}
    notes: list[dict] = []
    for mid in range(NUM_MAPS):
        const_name = id_to_name[mid]
        name = display_name(const_name)
        if mid in group_of:
            area_id = group_of[mid]
            result[mid] = {"area_id": area_id, "name": group_name.get(area_id, name)}
            continue
        if mid in own_area:
            result[mid] = {"area_id": own_area[mid], "name": name}
            continue
        if const_name.startswith("UNUSED_MAP_"):
            result[mid] = {"area_id": snake(const_name), "name": name}
            continue
        if const_name in GAME_KNOWLEDGE_OVERRIDES:
            parent = GAME_KNOWLEDGE_OVERRIDES[const_name]
            if parent is None:
                result[mid] = {"area_id": snake(const_name), "name": name}
            else:
                parent_area = group_of.get(parent) or own_area.get(parent) or snake(id_to_name[parent])
                result[mid] = {"area_id": parent_area, "name": name}
            notes.append({"map_id": mid, "const": const_name,
                          "rule": "game_knowledge_override", "area_id": result[mid]["area_id"]})
            continue
        parent = prefix_match(const_name) or route_match(const_name) or city_match(const_name)
        if parent is not None:
            parent_area = group_of.get(parent) or own_area.get(parent) or snake(id_to_name[parent])
            result[mid] = {"area_id": parent_area, "name": name}
            continue
        # city/town/route with no table of its own, or a genuinely unresolved interior: own id.
        result[mid] = {"area_id": snake(const_name), "name": name}
        if mid not in CITY_TOWN_IDS and mid not in ROUTE_IDS:
            notes.append({"map_id": mid, "const": const_name, "rule": "unresolved_own_id_fallback",
                          "area_id": result[mid]["area_id"]})

    published = {str(k): v for k, v in sorted(result.items())}
    return published, {str(k): v for k, v in sorted(floor_suffix.items())}, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the files on disk are stale")
    args = ap.parse_args()

    root = gf.source_root(FOUNDATION)
    area_map, floor_labels, notes = build(root)
    post_collapse_areas = len({v["area_id"] for v in area_map.values()})

    docs = {
        _OUT_AREA: area_map,
        _OUT_FLOORS: floor_labels,
        _OUT_NOTES: {"schema": "gen1-purergb-area-notes-v1", "notes": notes},
    }
    if args.check:
        stale = []
        for path, doc in docs.items():
            if not path.exists() or json.loads(path.read_text(encoding="utf-8")) != doc:
                stale.append(path)
        if stale:
            for p in stale:
                print(f"stale: {p}", file=sys.stderr)
            return 1
        print(f"area_map.json/floor_labels.json/area_map_notes.json match source "
              f"({len(area_map)} maps, {post_collapse_areas} areas after collapse)")
        return 0

    for path, doc in docs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {_OUT_AREA.relative_to(gf.REPO)}: {len(area_map)} maps, "
          f"{EXPECTED_AREAS_BEFORE_COLLAPSE} areas before collapse, "
          f"{post_collapse_areas} areas after collapse")
    print(f"Wrote {_OUT_FLOORS.relative_to(gf.REPO)}: {len(floor_labels)} multi-floor maps")
    print(f"Wrote {_OUT_NOTES.relative_to(gf.REPO)}: {len(notes)} game_knowledge_override/"
          f"unresolved notes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
