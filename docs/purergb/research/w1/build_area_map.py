#!/usr/bin/env python3
"""Build area_map_purergb.json (map_id -> {area_id, name}) for pureRGB v2.7.6."""
import json
import os
import re

P = r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-recursing-hopper-86c382\27f97123-cfa0-473c-aed8-f288963eedeb\scratchpad\purergb"
OUT = r"C:\Users\howar\AppData\Local\Temp\claude\E--Google-Drive-SLink--claude-worktrees-recursing-hopper-86c382\2eefad46-f87d-42d5-a71b-d9e3807a4bb1\scratchpad\workers\w1"

def parse_map_constants(path):
    id_to_name, name_to_id = {}, {}
    idx = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split(";", 1)[0].strip()
            m = re.match(r"^map_const\s+([A-Z0-9_]+)\s*,", line)
            if m:
                id_to_name[idx] = m.group(1)
                name_to_id[m.group(1)] = idx
                idx += 1
    return id_to_name, name_to_id

def snake(name):
    return name.lower()

# hand overrides for readable display names (apostrophes, abbreviations, punctuation)
DISPLAY_OVERRIDES = {
    "REDS_HOUSE_1F": "Red's House 1F", "REDS_HOUSE_2F": "Red's House 2F",
    "BLUES_HOUSE": "Blue's House", "OAKS_LAB": "Oak's Lab",
    "DIGLETTS_CAVE": "Diglett's Cave", "DIGLETTS_CAVE_ROUTE_2": "Diglett's Cave (Route 2)",
    "DIGLETTS_CAVE_ROUTE_11": "Diglett's Cave (Route 11)",
    "MR_FUJIS_HOUSE": "Mr. Fuji's House", "MR_PSYCHICS_HOUSE": "Mr. Psychic's House",
    "WARDENS_HOUSE": "Warden's House", "COPYCATS_HOUSE_1F": "Copycat's House 1F",
    "COPYCATS_HOUSE_2F": "Copycat's House 2F", "NAME_RATERS_HOUSE": "Name Rater's House",
    "TYPE_GUYS_HOUSE": "Type Guy's House", "FOSSIL_GUYS_HOUSE": "Fossil Guy's House",
    "FUCHSIA_BILLS_GRANDPAS_HOUSE": "Fuchsia Bill's Grandpa's House",
    "CHAMPIONS_ROOM": "Champion's Room", "SS_ANNE_1F": "S.S. Anne 1F", "SS_ANNE_2F": "S.S. Anne 2F",
    "SS_ANNE_3F": "S.S. Anne 3F", "SS_ANNE_B1F": "S.S. Anne B1F", "SS_ANNE_BOW": "S.S. Anne Bow",
    "SS_ANNE_KITCHEN": "S.S. Anne Kitchen", "SS_ANNE_CAPTAINS_ROOM": "S.S. Anne Captain's Room",
    "SS_ANNE_1F_ROOMS": "S.S. Anne 1F Rooms", "SS_ANNE_2F_ROOMS": "S.S. Anne 2F Rooms",
    "SS_ANNE_B1F_ROOMS": "S.S. Anne B1F Rooms", "LORELEIS_ROOM": "Lorelei's Room",
    "BRUNOS_ROOM": "Bruno's Room", "AGATHAS_ROOM": "Agatha's Room", "LANCES_ROOM": "Lance's Room",
    "CINNABAR_LAB_TRADE_ROOM": "Cinnabar Lab Trade Room",
}

def display_name(const_name):
    if const_name in DISPLAY_OVERRIDES:
        return DISPLAY_OVERRIDES[const_name]
    if const_name.startswith("UNUSED_MAP_"):
        return "Unused Map " + const_name.split("_")[-1]
    words = const_name.split("_")
    return " ".join(w.upper() if w in ("ss",) else w.capitalize() for w in words)

def main():
    id_to_name, name_to_id = parse_map_constants(os.path.join(P, "constants", "map_constants.asm"))

    census = json.load(open(os.path.join(OUT, "encounter_census.json"), encoding="utf-8"))

    # step 1: which map ids get their OWN area_id (rule 1: has grass/water rate>0 OR super_rod OR good/old rod
    # attached because it's in the "fishable" set built by build_census.py -- but the task's rule is specifically
    # "wild/fishing table", so: nonzero grass rate, nonzero water rate, has super_rod entries, or is a
    # good-rod/old-rod fishing spot (i.e. was in the fishable_map_ids union in build_census.py, which itself is
    # WildDataPointers-listed maps unioned with OceanMaps/SuperRodData maps).
    own_area = {}
    for mid_s, entry in census.items():
        mid = int(mid_s)
        has_wild = False
        if "grass" in entry and entry["grass"]["rate"] > 0:
            has_wild = True
        if "water" in entry and entry["water"]["rate"] > 0:
            has_wild = True
        if entry.get("super_rod"):
            has_wild = True
        if entry.get("old_rod") or entry.get("good_rod"):
            has_wild = True  # every map in the fishable union counts as having a fishing table
        if has_wild:
            own_area[mid] = snake(id_to_name[mid])

    # step 2: parent inference for interiors, three passes from most to least specific.
    CITY_TOWN_IDS = list(range(0, 11))       # PALLET_TOWN..INDIGO_PLATEAU
    ROUTE_IDS = list(range(12, 37))          # ROUTE_1..ROUTE_25 ($0C..$24)
    outdoor_ids = CITY_TOWN_IDS + ROUTE_IDS

    # pass A: exact token-tuple prefix match against EVERY own_area map's own constant name
    # (not just cities/routes) -- catches e.g. SAFARI_ZONE_CENTER_REST_HOUSE -> SAFARI_ZONE_CENTER,
    # VIRIDIAN_FOREST_NORTH_GATE -> VIRIDIAN_FOREST, POWER_PLANT_ROOF -> POWER_PLANT,
    # DIGLETTS_CAVE_ROUTE_2 -> DIGLETTS_CAVE.
    own_area_tokens = {tuple(id_to_name[mid].split("_")): mid for mid in own_area}

    def prefix_match_own_area(const_name):
        toks = const_name.split("_")
        for plen in range(len(toks) - 1, 0, -1):  # exclude the full name itself (that's own_area already)
            cand = tuple(toks[:plen])
            if cand in own_area_tokens:
                return own_area_tokens[cand]
        return None

    # pass B: a ROUTE_<N> token pair appearing ANYWHERE in the name (not just as a prefix) --
    # catches ROUTE_2_GATE, ROUTE_2_TRADE_HOUSE, UNDERGROUND_PATH_ROUTE_5/6/7/8,
    # ROUTE_11_GATE_1F/2F, ROUTE_12_GATE_1F/2F, ROUTE_12_SUPER_ROD_HOUSE, ROUTE_15/16/18_GATE_*,
    # ROUTE_16_FLY_HOUSE, ROUTE_22_GATE.
    route_name_to_id = {id_to_name[mid]: mid for mid in ROUTE_IDS}

    def route_substring_match(const_name):
        m = re.search(r"ROUTE_(\d+)", const_name)
        if m:
            route_name = f"ROUTE_{m.group(1)}"
            if route_name in route_name_to_id:
                return route_name_to_id[route_name]
        return None

    # pass C: first-token match against the 11 city/town names (VIRIDIAN_POKECENTER -> VIRIDIAN_CITY,
    # PEWTER_GYM -> PEWTER_CITY, CINNABAR_GYM -> CINNABAR_ISLAND, LAVENDER_MART -> LAVENDER_TOWN, ...).
    CITY_FIRST_TOKEN = {id_to_name[mid].split("_")[0]: mid for mid in CITY_TOWN_IDS}

    def city_first_token_match(const_name):
        first = const_name.split("_")[0]
        return CITY_FIRST_TOKEN.get(first)

    def find_prefix_parent(const_name):
        return (prefix_match_own_area(const_name)
                or route_substring_match(const_name)
                or city_first_token_match(const_name))

    # step 3: hand overrides for parents that are NOT derivable from the constant name
    # (verified against vanilla RBY geography / pureRGB map objects read this session).
    GAME_KNOWLEDGE_OVERRIDES = {
        # Celadon City basement/rooms with no CELADON_ prefix
        "ROCKET_HIDEOUT_B1F": 6, "ROCKET_HIDEOUT_B2F": 6, "ROCKET_HIDEOUT_B3F": 6,
        "ROCKET_HIDEOUT_B4F": 6, "ROCKET_HIDEOUT_ELEVATOR": 6,
        "GAME_CORNER": 6, "GAME_CORNER_PRIZE_ROOM": 6,
        # Saffron City basement/tower/NPCs with no SAFFRON_ prefix
        "SILPH_CO_1F": 7, "SILPH_CO_2F": 7, "SILPH_CO_3F": 7, "SILPH_CO_4F": 7,
        "SILPH_CO_5F": 7, "SILPH_CO_6F": 7, "SILPH_CO_7F": 7, "SILPH_CO_8F": 7,
        "SILPH_CO_9F": 7, "SILPH_CO_10F": 7, "SILPH_CO_11F": 7, "SILPH_CO_ELEVATOR": 7,
        "FIGHTING_DOJO": 7, "COPYCATS_HOUSE_1F": 7, "COPYCATS_HOUSE_2F": 7,
        # Elite Four / league, reached from Indigo Plateau / Victory Road 3F
        "LORELEIS_ROOM": 10, "BRUNOS_ROOM": 10, "AGATHAS_ROOM": 10, "LANCES_ROOM": 10,
        "CHAMPIONS_ROOM": 10, "HALL_OF_FAME": 10, "INDIGO_PLATEAU_LOBBY": 10,
        "CHAMP_ARENA": 10,
        # SS Anne is docked at Vermilion; Pokemon Fan Club is also vanilla-Vermilion
        "SS_ANNE_1F": 5, "SS_ANNE_2F": 5, "SS_ANNE_3F": 5, "SS_ANNE_B1F": 5,
        "SS_ANNE_BOW": 5, "SS_ANNE_KITCHEN": 5, "SS_ANNE_CAPTAINS_ROOM": 5,
        "SS_ANNE_1F_ROOMS": 5, "SS_ANNE_2F_ROOMS": 5, "SS_ANNE_B1F_ROOMS": 5,
        "POKEMON_FAN_CLUB": 5,
        # Pewter City museum has no PEWTER_ prefix
        "MUSEUM_1F": 2, "MUSEUM_2F": 2,
        # Cerulean City extras with no CERULEAN_ prefix
        "BIKE_SHOP": 3, "NAME_RATERS_HOUSE": 3,
        # Fuchsia City warden's house has no FUCHSIA_ prefix
        "WARDENS_HOUSE": 8,
        # Bill's House is on Route 25 in vanilla geography
        "BILLS_HOUSE": 36,
        # Underground paths pair Route 5<->6 (north-south) and Route 7<->8 (west-east);
        # both endpoints are equally "correct" -- flagged ambiguous, Route 5/7 picked arbitrarily.
        "UNDERGROUND_PATH_NORTH_SOUTH": 16, "UNDERGROUND_PATH_WEST_EAST": 18,
        # Daycare sits on Route 5 in vanilla
        "DAYCARE": 16,
        # Pokemon Tower basement (new map) sits below 1F, closest to Lavender Town itself
        "POKEMON_TOWER_B1F": 4,
        # Mt Moon / Rock Tunnel each have 2-3 sibling wild-table floors and no single "own_area" --
        # arbitrarily anchored to the first floor.
        "MT_MOON_POKECENTER": 0x3B, "ROCK_TUNNEL_POKECENTER": 0x52,
        # Ticket booth outside the 4-quadrant Safari Zone -- anchored to the Center quadrant.
        "SAFARI_ZONE_GATE": 0xDC,
        # Fossil restoration NPC; vanilla-equivalent (Cinnabar Lab) has no wild table of its own
        # and CINNABAR_LAB* already resolves via the CINNABAR first-token pass, but FOSSIL_GUYS_HOUSE
        # doesn't carry that prefix.
        "FOSSIL_GUYS_HOUSE": 9,
        # New pureRGB maps with no wild/fishing table and no map-object evidence read this session
        # tying them to a specific route/town -- left UNKNOWN, own id, not a parent guess.
        "DIAMOND_MINE": None, "SECRET_LAB": None,
        # Trade Center / Colosseum are link-menu constructs, not tied to a map
        "TRADE_CENTER": None, "COLOSSEUM": None,
        # Pallet Town houses/lab with no PALLET_ prefix
        "REDS_HOUSE_1F": 0, "REDS_HOUSE_2F": 0, "BLUES_HOUSE": 0, "OAKS_LAB": 0,
        # Pokemon Tower 1F/2F are empty (grass=0, water=0) so they're not own_area even though
        # 3F-7F are; anchored to Lavender Town like the new B1F map.
        "POKEMON_TOWER_1F": 4, "POKEMON_TOWER_2F": 4,
        # Mr. Fuji's House is in Lavender Town
        "MR_FUJIS_HOUSE": 4,
        # Mr. Psychic's House is on Route 8 in vanilla
        "MR_PSYCHICS_HOUSE": 19,
        # Fourth Safari Zone building with no CENTER/EAST/NORTH/WEST quadrant word in its name
        "SAFARI_ZONE_SECRET_HOUSE": 0xDC,
    }
    AMBIGUOUS_NOTES = {
        "MT_MOON_POKECENTER": "Mt. Moon has 3 separate wild-table areas (1F/B1F/B2F); "
                               "the Pokecenter's own-map floor isn't derivable from the constant name.",
        "ROCK_TUNNEL_POKECENTER": "Rock Tunnel has 2 separate wild-table areas (1F/B1F); "
                                   "the Pokecenter's own-map floor isn't derivable from the constant name.",
        "SAFARI_ZONE_GATE": "Ticket booth outside the 4-quadrant Safari Zone; no single quadrant is 'the' parent.",
        "UNDERGROUND_PATH_NORTH_SOUTH": "Connects Route 5 and Route 6; parent chosen (route_5) is arbitrary.",
        "UNDERGROUND_PATH_WEST_EAST": "Connects Route 7 and Route 8; parent chosen (route_7) is arbitrary.",
        "POKEMON_TOWER_B1F": "New pureRGB map with no wild table and no obvious sibling-floor rule; "
                              "assigned to Pokemon Tower 1F/Lavender Town by proximity, not derived.",
        "DIAMOND_MINE": "New pureRGB map ($73). No wild/fishing table, no map-object read this session "
                         "ties it to a specific route/town. UNKNOWN parent -- left as its own id.",
        "SECRET_LAB": "New pureRGB map ($6F). No wild/fishing table, no map-object read this session "
                       "ties it to a specific route/town. UNKNOWN parent -- left as its own id.",
        "CINNABAR_VOLCANO_WEST": "New pureRGB map; has its own wild table (rule 1 applies -- given its own "
                                  "area_id), but note it shares CinnabarVolcanoWildMons' *label* with "
                                  "CINNABAR_VOLCANO despite being a different map id.",
        "TRADE_CENTER": "Link-cable menu construct, not reached via any overworld warp -- no parent town.",
        "COLOSSEUM": "Link-cable menu construct, not reached via any overworld warp -- no parent town.",
        "TYPE_GUYS_HOUSE": "New/renamed pureRGB NPC house near Indigo Plateau; not read from a map-object "
                            "file this session, parent assigned by position in map_constants ordering only.",
        "BILLS_HOUSE": "Vanilla geography places this on Route 25, but the constant name carries no route "
                        "number -- inferred from game knowledge, not derived.",
        "FOSSIL_GUYS_HOUSE": "New pureRGB map; vanilla's fossil-restoration NPC is in Cinnabar Lab but this "
                              "name carries no CINNABAR_ prefix -- inferred from game knowledge, not derived.",
        "DAYCARE": "Vanilla Day Care is on Route 5, but the constant name carries no route number -- "
                   "inferred from game knowledge, not derived.",
        "WARDENS_HOUSE": "Vanilla Warden's House is in Fuchsia City, but the constant name carries no "
                          "FUCHSIA_ prefix -- inferred from game knowledge, not derived.",
        "POKEMON_FAN_CLUB": "Vanilla Pokemon Fan Club is in Vermilion City, but the constant name carries "
                             "no VERMILION_ prefix -- inferred from game knowledge, not derived.",
        "BIKE_SHOP": "Vanilla Bike Shop is in Cerulean City, but the constant name carries no CERULEAN_ "
                     "prefix -- inferred from game knowledge, not derived.",
        "NAME_RATERS_HOUSE": "Vanilla Name Rater's House is in Cerulean City, but the constant name carries "
                              "no CERULEAN_ prefix -- inferred from game knowledge, not derived.",
        "MUSEUM_1F": "Vanilla Pewter Museum is in Pewter City, but the constant name carries no PEWTER_ "
                     "prefix -- inferred from game knowledge, not derived.",
        "MUSEUM_2F": "Vanilla Pewter Museum is in Pewter City, but the constant name carries no PEWTER_ "
                     "prefix -- inferred from game knowledge, not derived.",
        "FIGHTING_DOJO": "Vanilla Fighting Dojo is in Saffron City, but the constant name carries no "
                          "SAFFRON_ prefix -- inferred from game knowledge, not derived.",
        "COPYCATS_HOUSE_1F": "Vanilla Copycat's House is in Saffron City, but the constant name carries no "
                              "SAFFRON_ prefix -- inferred from game knowledge, not derived.",
        "COPYCATS_HOUSE_2F": "Vanilla Copycat's House is in Saffron City, but the constant name carries no "
                              "SAFFRON_ prefix -- inferred from game knowledge, not derived.",
        "REDS_HOUSE_1F": "Vanilla geography places this in Pallet Town, but the constant name carries no "
                          "PALLET_ prefix -- inferred from game knowledge, not derived.",
        "BLUES_HOUSE": "Vanilla geography places this in Pallet Town, but the constant name carries no "
                        "PALLET_ prefix -- inferred from game knowledge, not derived.",
        "OAKS_LAB": "Vanilla geography places this in Pallet Town, but the constant name carries no "
                    "PALLET_ prefix -- inferred from game knowledge, not derived.",
        "POKEMON_TOWER_1F": "Grass/water rate are both 0 in this map's own wild table (unlike 3F-7F), so "
                             "it doesn't qualify as its own area; anchored to Lavender Town by proximity.",
        "POKEMON_TOWER_2F": "Grass/water rate are both 0 in this map's own wild table (unlike 3F-7F), so "
                             "it doesn't qualify as its own area; anchored to Lavender Town by proximity.",
        "MR_FUJIS_HOUSE": "Vanilla geography places this in Lavender Town, but the constant name carries no "
                           "LAVENDER_ prefix -- inferred from game knowledge, not derived.",
        "MR_PSYCHICS_HOUSE": "Vanilla geography places this on Route 8, but the constant name carries no "
                              "route number -- inferred from game knowledge, not derived.",
        "SAFARI_ZONE_SECRET_HOUSE": "Fourth Safari Zone building; name has no CENTER/EAST/NORTH/WEST "
                                     "quadrant word, anchored to the Center quadrant like SAFARI_ZONE_GATE.",
    }
    # TYPE_GUYS_HOUSE sits right after INDIGO_PLATEAU_LOBBY in map id order ($AE..$B1 block); best-effort:
    GAME_KNOWLEDGE_OVERRIDES.setdefault("TYPE_GUYS_HOUSE", 10)

    result = {}
    unresolved = []
    ambiguous_used = []
    for mid in range(len(id_to_name)):
        const_name = id_to_name[mid]
        name = display_name(const_name)
        if mid in own_area:
            result[mid] = {"area_id": own_area[mid], "name": name, "_rule": "own_wild_or_fishing_table"}
            continue
        # unused placeholder maps
        if const_name.startswith("UNUSED_MAP_"):
            result[mid] = {"area_id": snake(const_name), "name": name, "_rule": "unused_map"}
            continue
        if const_name in GAME_KNOWLEDGE_OVERRIDES:
            parent = GAME_KNOWLEDGE_OVERRIDES[const_name]
            if parent is None:
                result[mid] = {"area_id": snake(const_name), "name": name, "_rule": "no_parent_own_id"}
            else:
                result[mid] = {"area_id": own_area.get(parent, snake(id_to_name[parent])),
                                "name": name, "_rule": "game_knowledge_override"}
            if const_name in AMBIGUOUS_NOTES:
                ambiguous_used.append((mid, const_name, AMBIGUOUS_NOTES[const_name]))
            continue
        parent = find_prefix_parent(const_name)
        if parent is not None:
            result[mid] = {"area_id": own_area.get(parent, snake(id_to_name[parent])),
                            "name": name, "_rule": "prefix_match"}
            continue
        # city/town/route itself with no wild table (own id, rule 2 "else their own id")
        if mid in outdoor_ids:
            result[mid] = {"area_id": snake(const_name), "name": name, "_rule": "own_id_no_table"}
            continue
        # truly unresolved interior
        result[mid] = {"area_id": snake(const_name), "name": name, "_rule": "UNRESOLVED_own_id_fallback"}
        unresolved.append((mid, const_name))

    print(f"Total maps: {len(result)}")
    print(f"Own-area (rule 1, has wild/fishing table): {len(own_area)}")
    print(f"Ambiguous (flagged, best-effort assigned): {len(ambiguous_used)}")
    for mid, cn, note in ambiguous_used:
        print(f"  [{mid:#04x}] {cn}: {note}")
    print(f"Fully unresolved (no rule matched): {len(unresolved)}")
    for mid, cn in unresolved:
        print(f"  [{mid:#04x}] {cn}")

    # strip internal _rule/debug fields for the final published file, but keep a debug copy
    published = {str(k): {"area_id": v["area_id"], "name": v["name"]} for k, v in sorted(result.items())}
    with open(os.path.join(OUT, "area_map_purergb.json"), "w", encoding="utf-8") as f:
        json.dump(published, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "area_map_purergb_debug.json"), "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in sorted(result.items())}, f, indent=2, ensure_ascii=False)
    print("Wrote area_map_purergb.json and area_map_purergb_debug.json")
    return result, ambiguous_used, unresolved

if __name__ == "__main__":
    main()
