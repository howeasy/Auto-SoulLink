#!/usr/bin/env python3
"""
gen_area_map.py — build artifact generator for SLink area tables.

Outputs three files from the same source data:
  data/area_map.json   — consumed by server/state.py for encounter linking
  data/games/gen3_frlge/gen3_frlge_areas.lua        — encounter-zone lookup (Soul Link logic, no JSON parser needed)
  data/games/gen3_frlge/gen3_frlge_locations.lua    — full physical map name table for ALL maps (display/debug only)

Run whenever area mappings change:
  cd SLink && python tools/gen_area_map.py

Source: pret/pokefirered data/maps/map_groups.json
  Group 0 = gMapGroup_Link          (no wild encounters)
  Group 1 = gMapGroup_Dungeons      (dungeons; multi-floor → one area_id)
  Group 2 = gMapGroup_SpecialArea   (special/post-game; multi-floor → one area_id)
  Group 3 = gMapGroup_TownsAndRoutes (towns 0–18 + routes 19–64)
  Groups 4+ = indoor buildings       (no wild encounters)

Notes on randomizer compatibility:
  mapGroup+mapNum are defined by the game's C source (not randomizable ROM data).
  All ids here are valid for any FireRed/LeafGreen US 1.0 ROM, vanilla or randomized.
"""

import json, os, re


def to_snake(name):
    """Convert FRLG PascalCase map names to snake_case display names.

    Examples:
      PalletTown            → pallet_town
      SSAnne_Exterior       → ss_anne_exterior
      MtMoon_B1F            → mt_moon_b1f
      SilphCo_11F           → silph_co_11f
      PokemonLeague_HallOfFame → pokemon_league_hall_of_fame
    """
    # Pass 1: split consecutive-uppercase acronyms before a CamelCase word
    #   SSAnne → SS_Anne,  SilphCo → SilphCo (no consecutive upper before lower)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    # Pass 2: split at lowercase→uppercase transitions
    #   PalletTown → Pallet_Town,  MtMoon → Mt_Moon
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
    s = s.lower()
    # Pass 3: normalize floor suffixes so digits don't get split from 'f'
    #   silph_co_1_f → silph_co_1f,  mt_moon_b1_f → mt_moon_b1f
    s = re.sub(r'_([b]?)(\d+)_f(\b|_|$)', lambda m: f'_{m.group(1)}{m.group(2)}f{m.group(3)}', s)
    return s

area_map = {}

dungeon_area = {
    0: "viridian_forest",
    1: "mt_moon", 2: "mt_moon", 3: "mt_moon",
    36: "digletts_cave", 37: "digletts_cave", 38: "digletts_cave",
    39: "victory_road", 40: "victory_road", 41: "victory_road",
    59: "pokemon_mansion", 60: "pokemon_mansion", 61: "pokemon_mansion", 62: "pokemon_mansion",
    63: "safari_zone_center", 64: "safari_zone_east", 65: "safari_zone_north", 66: "safari_zone_west",
    72: "cerulean_cave", 73: "cerulean_cave", 74: "cerulean_cave",
    81: "rock_tunnel", 82: "rock_tunnel",
    83: "seafoam_islands", 84: "seafoam_islands", 85: "seafoam_islands", 86: "seafoam_islands", 87: "seafoam_islands",
    89: "pokemon_tower", 90: "pokemon_tower", 91: "pokemon_tower",
    92: "pokemon_tower", 93: "pokemon_tower", 94: "pokemon_tower",
    95: "power_plant",
    96: "mt_ember", 97: "mt_ember", 98: "mt_ember", 99: "mt_ember",
    100: "mt_ember", 101: "mt_ember", 102: "mt_ember", 103: "mt_ember",
    104: "mt_ember", 105: "mt_ember", 106: "mt_ember", 107: "mt_ember", 108: "mt_ember",
    109: "berry_forest",
    110: "icefall_cave", 111: "icefall_cave", 112: "icefall_cave", 113: "icefall_cave",
    115: "dotted_hole", 116: "dotted_hole", 117: "dotted_hole", 118: "dotted_hole", 119: "dotted_hole",
    121: "pattern_bush",
    122: "altering_cave",
    # RR additions
    123: "rock_tunnel",        # RockTunnel_B2F
    124: "seafoam_islands",    # SeafoamIslands_B5F
    125: "pokemon_tower", 126: "pokemon_tower",  # PokemonTower 8F + Rooftop
    127: "viridian_forest",    # ViridianForest_Deep
    # Silph Co. extra floors — no wild encounters in vanilla but RR may add them
    128: "silph_co", 129: "silph_co",  # SilphCo 12F + 13F
}
for num, area_id in dungeon_area.items():
    area_map[f"1:{num}"] = area_id

special_area = {
    # NavelRock_Exterior (Lugia / Ho-Oh event island)
    0: "navel_rock",
    12: "lost_cave", 13: "lost_cave", 14: "lost_cave", 15: "lost_cave",
    16: "lost_cave", 17: "lost_cave", 18: "lost_cave", 19: "lost_cave",
    20: "lost_cave", 21: "lost_cave", 22: "lost_cave", 23: "lost_cave",
    24: "lost_cave", 25: "lost_cave", 26: "lost_cave",
    27: "monean_chamber", 28: "liptoo_chamber", 29: "weepth_chamber",
    30: "dilford_chamber", 31: "scufib_chamber", 32: "rixy_chamber", 33: "viapois_chamber",
    34: "dunsparce_tunnel",
    # SevenIsland_SevaultCanyon_TanobyKey — interior room (distinct from Sevault Canyon route)
    35: "tanoby_key",
    # NavelRock interior floors (1F, Summit, Base, SummitPath 2F–5F, BasePath B1F–B11F, B1F, Fork)
    36: "navel_rock", 37: "navel_rock", 38: "navel_rock", 39: "navel_rock",
    40: "navel_rock", 41: "navel_rock", 42: "navel_rock", 43: "navel_rock",
    44: "navel_rock", 45: "navel_rock", 46: "navel_rock", 47: "navel_rock",
    48: "navel_rock", 49: "navel_rock", 50: "navel_rock", 51: "navel_rock",
    52: "navel_rock", 53: "navel_rock", 54: "navel_rock", 55: "navel_rock",
    # BirthIsland_Exterior (Deoxys event island)
    56: "birth_island",
    # RR additions
    60: "silph_co", 61: "silph_co",    # SilphCo 14F + 15F
    62: "pokemon_mansion", 63: "pokemon_mansion",  # PokemonMansion B2F + B3F
    64: "safari_zone_center",  # SafariZone_Expansion
}
for num, area_id in special_area.items():
    area_map[f"2:{num}"] = area_id

route_area = {
    # Towns/cities — RR adds wild encounters to all towns
    0: "pallet_town", 1: "viridian_city", 2: "pewter_city",
    3: "cerulean_city", 4: "lavender_town",
    5: "vermilion_city", 6: "celadon_city", 7: "fuchsia_city",
    8: "cinnabar_island", 9: "indigo_plateau", 10: "saffron_city",
    # Routes (grass + optional fishing/surf)
    19: "route_1", 20: "route_2", 21: "route_3", 22: "route_4",
    23: "route_5", 24: "route_6", 25: "route_7", 26: "route_8",
    27: "route_9", 28: "route_10", 29: "route_11", 30: "route_12",
    31: "route_13", 32: "route_14", 33: "route_15", 34: "route_16",
    35: "route_17", 36: "route_18", 37: "route_19", 38: "route_20",
    39: "route_21", 40: "route_21", 41: "route_22", 42: "route_23",
    43: "route_24", 44: "route_25",
    # Sevii Islands routes
    45: "kindle_road", 46: "treasure_beach", 47: "cape_brink",
    48: "bond_bridge", 49: "three_isle_port",
    55: "water_labyrinth", 56: "five_isle_meadow", 58: "outcast_island",
    59: "green_path", 60: "water_path", 61: "ruin_valley",
    64: "sevault_canyon",
    # Sevii Islands towns/locations with fishing/surf (no grass)
    12: "one_island", 13: "two_island", 14: "three_island",
    15: "four_island", 16: "five_island", 17: "seven_island", 18: "six_island",
    54: "resort_gorgeous", 62: "trainer_tower", 65: "tanoby_ruins",
}
for num, area_id in route_area.items():
    area_map[f"3:{num}"] = area_id

# Gift/static encounter locations — NOT wild-encounter zones, but both players visit the
# same building and receive the same gift, so they must be linked by area_id.
# These are in indoor map groups (4+) normally excluded from the area map.
# group:mapNum → canonical area_id
#   4:3  = PalletTown_ProfessorOaksLab  (starter — vanilla)
#   0:0  = BattleColosseum_2P           (starter — AP intro sequence repurposes this map)
#   12:3 = CinnabarIsland_PokemonLab_ResearchRoom  (fossil revival)
#   10:11 = CeladonCity_Condominiums_RoofRoom  (Eevee — NOT 10:19 CeladonCity_Hotel)
#   1:53  = SilphCo_7F                  (Lapras)
#   14:2  = SaffronCity_Dojo            (Hitmonlee or Hitmonchan)
gift_areas = {
    "4:3":   "oaks_lab",
    "0:0":   "intro",
    "12:3":  "cinnabar_lab",
    "10:11": "celadon_condominiums",
    "1:53":  "silph_co_7f",
    "14:2":  "saffron_dojo",
    "16:0":  "route_4_pokecenter",   # Route4_PokemonCenter_1F (Magikarp salesman)
}
area_map.update(gift_areas)

# Canonical set of gift area_ids (used by server/state.py to gate Pokéball check)
GIFT_AREA_IDS = sorted(gift_areas.values())

with open(os.path.join("data", "games", "gen3_frlge", "area_map.json"), "w") as f:
    json.dump(area_map, f, indent=2, sort_keys=True)

# Generate data/games/gen3_frlge/gen3_frlge_areas.lua — static Lua table avoids JSON parsing in BizHawk scripts.
sorted_keys = sorted(area_map.keys(), key=lambda x: tuple(int(n) for n in x.split(":")))
lua_lines = [
    "-- data/games/gen3_frlge/gen3_frlge_areas.lua — AUTO-GENERATED by gen_area_map.py — DO NOT EDIT BY HAND",
    "-- Re-run: cd SLink && python tools/gen_area_map.py",
    "--",
    "-- Maps (mapGroup .. ':' .. mapNum) -> canonical area_id.",
    "-- Covers wild-encounter zones AND gift/static encounter buildings.",
    "-- Source: pret/pokefirered data/maps/map_groups.json",
    "-- Randomizer note: mapGroup+mapNum are defined by game code, not ROM data.",
    "--   This table is valid for any FireRed/LeafGreen US 1.0 base ROM (vanilla or randomized).",
    "--",
    "-- Gift areas (no wild encounters; used for starter/fossil/Eevee/Lapras/dojo linking):",
    "-- " + ", ".join(f'"{v}"' for v in sorted(gift_areas.values())),
    "",
    "return {",
]
for key in sorted_keys:
    lua_lines.append(f'  ["{key}"] = "{area_map[key]}",')
lua_lines.append("}")

with open("data/games/gen3_frlge/gen3_frlge_areas.lua", "w", newline="\n", encoding="utf-8") as f:
    f.write("\n".join(lua_lines) + "\n")

# ── Location map — ALL FRLG maps → physical snake_case name ──────────────────
# Complete map group data (pret/pokefirered data/maps/map_groups.json).
# group_index → [map names in order]  (order defines mapNum 0, 1, 2, …)
ALL_MAP_GROUPS = {
    0: [  # gMapGroup_Link
        "BattleColosseum_2P", "TradeCenter", "RecordCorner",
        "BattleColosseum_4P", "UnionRoom",
    ],
    1: [  # gMapGroup_Dungeons
        "ViridianForest",
        "MtMoon_1F", "MtMoon_B1F", "MtMoon_B2F",
        "SSAnne_Exterior",
        "SSAnne_1F_Corridor", "SSAnne_2F_Corridor", "SSAnne_3F_Corridor", "SSAnne_B1F_Corridor",
        "SSAnne_Deck", "SSAnne_Kitchen", "SSAnne_CaptainsOffice",
        "SSAnne_1F_Room1", "SSAnne_1F_Room2", "SSAnne_1F_Room3", "SSAnne_1F_Room4",
        "SSAnne_1F_Room5", "SSAnne_1F_Room7",
        "SSAnne_2F_Room1", "SSAnne_2F_Room2", "SSAnne_2F_Room3",
        "SSAnne_2F_Room4", "SSAnne_2F_Room5", "SSAnne_2F_Room6",
        "SSAnne_B1F_Room1", "SSAnne_B1F_Room2", "SSAnne_B1F_Room3",
        "SSAnne_B1F_Room4", "SSAnne_B1F_Room5",
        "SSAnne_1F_Room6",
        "UndergroundPath_NorthEntrance", "UndergroundPath_NorthSouthTunnel",
        "UndergroundPath_SouthEntrance", "UndergroundPath_WestEntrance",
        "UndergroundPath_EastWestTunnel", "UndergroundPath_EastEntrance",
        "DiglettsCave_NorthEntrance", "DiglettsCave_B1F", "DiglettsCave_SouthEntrance",
        "VictoryRoad_1F", "VictoryRoad_2F", "VictoryRoad_3F",
        "RocketHideout_B1F", "RocketHideout_B2F", "RocketHideout_B3F",
        "RocketHideout_B4F", "RocketHideout_Elevator",
        "SilphCo_1F", "SilphCo_2F", "SilphCo_3F", "SilphCo_4F", "SilphCo_5F",
        "SilphCo_6F", "SilphCo_7F", "SilphCo_8F", "SilphCo_9F",
        "SilphCo_10F", "SilphCo_11F", "SilphCo_Elevator",
        "PokemonMansion_1F", "PokemonMansion_2F", "PokemonMansion_3F", "PokemonMansion_B1F",
        "SafariZone_Center", "SafariZone_East", "SafariZone_North", "SafariZone_West",
        "SafariZone_Center_RestHouse", "SafariZone_East_RestHouse",
        "SafariZone_North_RestHouse", "SafariZone_West_RestHouse", "SafariZone_SecretHouse",
        "CeruleanCave_1F", "CeruleanCave_2F", "CeruleanCave_B1F",
        "PokemonLeague_LoreleisRoom", "PokemonLeague_BrunosRoom", "PokemonLeague_AgathasRoom",
        "PokemonLeague_LancesRoom", "PokemonLeague_ChampionsRoom", "PokemonLeague_HallOfFame",
        "RockTunnel_1F", "RockTunnel_B1F",
        "SeafoamIslands_1F", "SeafoamIslands_B1F", "SeafoamIslands_B2F",
        "SeafoamIslands_B3F", "SeafoamIslands_B4F",
        "PokemonTower_1F", "PokemonTower_2F", "PokemonTower_3F", "PokemonTower_4F",
        "PokemonTower_5F", "PokemonTower_6F", "PokemonTower_7F",
        "PowerPlant",
        "MtEmber_RubyPath_B4F", "MtEmber_Exterior",
        "MtEmber_SummitPath_1F", "MtEmber_SummitPath_2F", "MtEmber_SummitPath_3F",
        "MtEmber_Summit", "MtEmber_RubyPath_B5F", "MtEmber_RubyPath_1F",
        "MtEmber_RubyPath_B1F", "MtEmber_RubyPath_B2F", "MtEmber_RubyPath_B3F",
        "MtEmber_RubyPath_B1F_Stairs", "MtEmber_RubyPath_B2F_Stairs",
        "ThreeIsland_BerryForest",
        "FourIsland_IcefallCave_Entrance", "FourIsland_IcefallCave_1F",
        "FourIsland_IcefallCave_B1F", "FourIsland_IcefallCave_Back",
        "FiveIsland_RocketWarehouse",
        "SixIsland_DottedHole_1F", "SixIsland_DottedHole_B1F", "SixIsland_DottedHole_B2F",
        "SixIsland_DottedHole_B3F", "SixIsland_DottedHole_B4F",
        "SixIsland_DottedHole_SapphireRoom",
        "SixIsland_PatternBush", "SixIsland_AlteringCave",
        # ── RR additions (1:123–1:129) ──
        "RockTunnel_B2F",       # 1:123 — extra floor (RR)
        "SeafoamIslands_B5F",   # 1:124 — extra floor (RR)
        "PokemonTower_8F",      # 1:125 — extra floor (RR)
        "PokemonTower_Rooftop", # 1:126 — extra floor (RR)
        "ViridianForest_Deep",  # 1:127 — forest expansion (RR)
        "SilphCo_12F",          # 1:128 — extra floor (RR)
        "SilphCo_13F",          # 1:129 — extra floor (RR)
    ],
    2: [  # gMapGroup_SpecialArea
        "NavelRock_Exterior",
        "TrainerTower_1F", "TrainerTower_2F", "TrainerTower_3F", "TrainerTower_4F",
        "TrainerTower_5F", "TrainerTower_6F", "TrainerTower_7F", "TrainerTower_8F",
        "TrainerTower_Roof", "TrainerTower_Lobby", "TrainerTower_Elevator",
        "FiveIsland_LostCave_Entrance",
        "FiveIsland_LostCave_Room1", "FiveIsland_LostCave_Room2", "FiveIsland_LostCave_Room3",
        "FiveIsland_LostCave_Room4", "FiveIsland_LostCave_Room5", "FiveIsland_LostCave_Room6",
        "FiveIsland_LostCave_Room7", "FiveIsland_LostCave_Room8", "FiveIsland_LostCave_Room9",
        "FiveIsland_LostCave_Room10", "FiveIsland_LostCave_Room11",
        "FiveIsland_LostCave_Room12", "FiveIsland_LostCave_Room13", "FiveIsland_LostCave_Room14",
        "SevenIsland_TanobyRuins_MoneanChamber", "SevenIsland_TanobyRuins_LiptooChamber",
        "SevenIsland_TanobyRuins_WeepthChamber", "SevenIsland_TanobyRuins_DilfordChamber",
        "SevenIsland_TanobyRuins_ScufibChamber", "SevenIsland_TanobyRuins_RixyChamber",
        "SevenIsland_TanobyRuins_ViapoisChamber",
        "ThreeIsland_DunsparceTunnel",
        "SevenIsland_SevaultCanyon_TanobyKey",
        "NavelRock_1F", "NavelRock_Summit", "NavelRock_Base",
        "NavelRock_SummitPath_2F", "NavelRock_SummitPath_3F",
        "NavelRock_SummitPath_4F", "NavelRock_SummitPath_5F",
        "NavelRock_BasePath_B1F", "NavelRock_BasePath_B2F", "NavelRock_BasePath_B3F",
        "NavelRock_BasePath_B4F", "NavelRock_BasePath_B5F", "NavelRock_BasePath_B6F",
        "NavelRock_BasePath_B7F", "NavelRock_BasePath_B8F", "NavelRock_BasePath_B9F",
        "NavelRock_BasePath_B10F", "NavelRock_BasePath_B11F",
        "NavelRock_B1F", "NavelRock_Fork",
        "BirthIsland_Exterior",
        "OneIsland_KindleRoad_EmberSpa",
        "BirthIsland_Harbor", "NavelRock_Harbor",
        # ── RR additions (2:60–2:64) ──
        "SilphCo_14F",                # 2:60 — extra floor (RR)
        "SilphCo_15F",                # 2:61 — extra floor (RR)
        "PokemonMansion_B2F",         # 2:62 — extra floor (RR)
        "PokemonMansion_B3F",         # 2:63 — extra floor (RR)
        "SafariZone_Expansion",       # 2:64 — new safari area (RR)
    ],
    3: [  # gMapGroup_TownsAndRoutes
        "PalletTown", "ViridianCity", "PewterCity", "CeruleanCity",
        "LavenderTown", "VermilionCity", "CeladonCity", "FuchsiaCity",
        "CinnabarIsland", "IndigoPlateau_Exterior", "SaffronCity", "SaffronCity_Connection",
        "OneIsland", "TwoIsland", "ThreeIsland", "FourIsland",
        "FiveIsland", "SevenIsland", "SixIsland",
        "Route1", "Route2", "Route3", "Route4", "Route5",
        "Route6", "Route7", "Route8", "Route9", "Route10",
        "Route11", "Route12", "Route13", "Route14", "Route15",
        "Route16", "Route17", "Route18", "Route19", "Route20",
        "Route21_North", "Route21_South", "Route22", "Route23", "Route24", "Route25",
        "OneIsland_KindleRoad", "OneIsland_TreasureBeach",
        "TwoIsland_CapeBrink", "ThreeIsland_BondBridge", "ThreeIsland_Port",
        "Prototype_SeviiIsle_6", "Prototype_SeviiIsle_7",
        "Prototype_SeviiIsle_8", "Prototype_SeviiIsle_9",
        "FiveIsland_ResortGorgeous", "FiveIsland_WaterLabyrinth", "FiveIsland_Meadow",
        "FiveIsland_MemorialPillar",
        "SixIsland_OutcastIsland", "SixIsland_GreenPath", "SixIsland_WaterPath",
        "SixIsland_RuinValley",
        "SevenIsland_TrainerTower", "SevenIsland_SevaultCanyon_Entrance",
        "SevenIsland_SevaultCanyon", "SevenIsland_TanobyRuins",
    ],
    4: [  # gMapGroup_IndoorPallet
        "PalletTown_PlayersHouse_1F", "PalletTown_PlayersHouse_2F",
        "PalletTown_RivalsHouse", "PalletTown_ProfessorOaksLab",
    ],
    5: [  # gMapGroup_IndoorViridian
        "ViridianCity_House", "ViridianCity_Gym", "ViridianCity_School",
        "ViridianCity_Mart", "ViridianCity_PokemonCenter_1F", "ViridianCity_PokemonCenter_2F",
    ],
    6: [  # gMapGroup_IndoorPewter
        "PewterCity_Museum_1F", "PewterCity_Museum_2F", "PewterCity_Gym", "PewterCity_Mart",
        "PewterCity_House1", "PewterCity_PokemonCenter_1F", "PewterCity_PokemonCenter_2F",
        "PewterCity_House2",
    ],
    7: [  # gMapGroup_IndoorCerulean
        "CeruleanCity_House1", "CeruleanCity_House2", "CeruleanCity_House3",
        "CeruleanCity_PokemonCenter_1F", "CeruleanCity_PokemonCenter_2F",
        "CeruleanCity_Gym", "CeruleanCity_BikeShop", "CeruleanCity_Mart",
        "CeruleanCity_House4", "CeruleanCity_House5",
    ],
    8: [  # gMapGroup_IndoorLavender
        "LavenderTown_PokemonCenter_1F", "LavenderTown_PokemonCenter_2F",
        "LavenderTown_VolunteerPokemonHouse", "LavenderTown_House1",
        "LavenderTown_House2", "LavenderTown_Mart",
    ],
    9: [  # gMapGroup_IndoorVermilion
        "VermilionCity_House1", "VermilionCity_PokemonCenter_1F", "VermilionCity_PokemonCenter_2F",
        "VermilionCity_PokemonFanClub", "VermilionCity_House2", "VermilionCity_Mart",
        "VermilionCity_Gym", "VermilionCity_House3",
    ],
    10: [  # gMapGroup_IndoorCeladon
        "CeladonCity_DepartmentStore_1F", "CeladonCity_DepartmentStore_2F",
        "CeladonCity_DepartmentStore_3F", "CeladonCity_DepartmentStore_4F",
        "CeladonCity_DepartmentStore_5F", "CeladonCity_DepartmentStore_Roof",
        "CeladonCity_DepartmentStore_Elevator",
        "CeladonCity_Condominiums_1F", "CeladonCity_Condominiums_2F",
        "CeladonCity_Condominiums_3F", "CeladonCity_Condominiums_Roof",
        "CeladonCity_Condominiums_RoofRoom",
        "CeladonCity_PokemonCenter_1F", "CeladonCity_PokemonCenter_2F",
        "CeladonCity_GameCorner", "CeladonCity_GameCorner_PrizeRoom",
        "CeladonCity_Gym", "CeladonCity_Restaurant", "CeladonCity_House1", "CeladonCity_Hotel",
    ],
    11: [  # gMapGroup_IndoorFuchsia
        "FuchsiaCity_SafariZone_Entrance", "FuchsiaCity_Mart", "FuchsiaCity_SafariZone_Office",
        "FuchsiaCity_Gym", "FuchsiaCity_House1",
        "FuchsiaCity_PokemonCenter_1F", "FuchsiaCity_PokemonCenter_2F",
        "FuchsiaCity_WardensHouse", "FuchsiaCity_House2", "FuchsiaCity_House3",
    ],
    12: [  # gMapGroup_IndoorCinnabar
        "CinnabarIsland_Gym",
        "CinnabarIsland_PokemonLab_Entrance", "CinnabarIsland_PokemonLab_Lounge",
        "CinnabarIsland_PokemonLab_ResearchRoom", "CinnabarIsland_PokemonLab_ExperimentRoom",
        "CinnabarIsland_PokemonCenter_1F", "CinnabarIsland_PokemonCenter_2F",
        "CinnabarIsland_Mart",
    ],
    13: [  # gMapGroup_IndoorIndigoPlateau
        "IndigoPlateau_PokemonCenter_1F", "IndigoPlateau_PokemonCenter_2F",
    ],
    14: [  # gMapGroup_IndoorSaffron
        "SaffronCity_CopycatsHouse_1F", "SaffronCity_CopycatsHouse_2F",
        "SaffronCity_Dojo", "SaffronCity_Gym", "SaffronCity_House", "SaffronCity_Mart",
        "SaffronCity_PokemonCenter_1F", "SaffronCity_PokemonCenter_2F",
        "SaffronCity_MrPsychicsHouse", "SaffronCity_PokemonTrainerFanClub",
    ],
    15: [  # gMapGroup_IndoorRoute2
        "Route2_ViridianForest_SouthEntrance", "Route2_House",
        "Route2_EastBuilding", "Route2_ViridianForest_NorthEntrance",
    ],
    16: [  # gMapGroup_IndoorRoute4
        "Route4_PokemonCenter_1F", "Route4_PokemonCenter_2F",
    ],
    17: [  # gMapGroup_IndoorRoute5
        "Route5_PokemonDayCare", "Route5_SouthEntrance",
    ],
    18: [  # gMapGroup_IndoorRoute6
        "Route6_NorthEntrance", "Route6_UnusedHouse",
    ],
    19: [  # gMapGroup_IndoorRoute7
        "Route7_EastEntrance",
    ],
    20: [  # gMapGroup_IndoorRoute8
        "Route8_WestEntrance",
    ],
    21: [  # gMapGroup_IndoorRoute10
        "Route10_PokemonCenter_1F", "Route10_PokemonCenter_2F",
    ],
    22: [  # gMapGroup_IndoorRoute11
        "Route11_EastEntrance_1F", "Route11_EastEntrance_2F",
    ],
    23: [  # gMapGroup_IndoorRoute12
        "Route12_NorthEntrance_1F", "Route12_NorthEntrance_2F", "Route12_FishingHouse",
    ],
    24: [  # gMapGroup_IndoorRoute15
        "Route15_WestEntrance_1F", "Route15_WestEntrance_2F",
    ],
    25: [  # gMapGroup_IndoorRoute16
        "Route16_House", "Route16_NorthEntrance_1F", "Route16_NorthEntrance_2F",
    ],
    26: [  # gMapGroup_IndoorRoute18
        "Route18_EastEntrance_1F", "Route18_EastEntrance_2F",
    ],
    27: [  # gMapGroup_IndoorRoute19
        "Route19_UnusedHouse",
    ],
    28: [  # gMapGroup_IndoorRoute22
        "Route22_NorthEntrance",
    ],
    29: [  # gMapGroup_IndoorRoute23
        "Route23_UnusedHouse",
    ],
    30: [  # gMapGroup_IndoorRoute25
        "Route25_SeaCottage",
    ],
    31: [  # gMapGroup_IndoorSevenIsland
        "SevenIsland_House_Room1", "SevenIsland_House_Room2", "SevenIsland_Mart",
        "SevenIsland_PokemonCenter_1F", "SevenIsland_PokemonCenter_2F",
        "SevenIsland_UnusedHouse", "SevenIsland_Harbor",
    ],
    32: [  # gMapGroup_IndoorOneIsland
        "OneIsland_PokemonCenter_1F", "OneIsland_PokemonCenter_2F",
        "OneIsland_House1", "OneIsland_House2", "OneIsland_Harbor",
    ],
    33: [  # gMapGroup_IndoorTwoIsland
        "TwoIsland_JoyfulGameCorner", "TwoIsland_House",
        "TwoIsland_PokemonCenter_1F", "TwoIsland_PokemonCenter_2F", "TwoIsland_Harbor",
    ],
    34: [  # gMapGroup_IndoorThreeIsland
        "ThreeIsland_House1",
        "ThreeIsland_PokemonCenter_1F", "ThreeIsland_PokemonCenter_2F",
        "ThreeIsland_Mart", "ThreeIsland_House2", "ThreeIsland_House3",
        "ThreeIsland_House4", "ThreeIsland_House5",
    ],
    35: [  # gMapGroup_IndoorFourIsland
        "FourIsland_PokemonDayCare",
        "FourIsland_PokemonCenter_1F", "FourIsland_PokemonCenter_2F",
        "FourIsland_House1", "FourIsland_LoreleisHouse", "FourIsland_Harbor",
        "FourIsland_House2", "FourIsland_Mart",
    ],
    36: [  # gMapGroup_IndoorFiveIsland
        "FiveIsland_PokemonCenter_1F", "FiveIsland_PokemonCenter_2F",
        "FiveIsland_Harbor", "FiveIsland_House1", "FiveIsland_House2",
    ],
    37: [  # gMapGroup_IndoorSixIsland
        "SixIsland_PokemonCenter_1F", "SixIsland_PokemonCenter_2F",
        "SixIsland_Harbor", "SixIsland_House", "SixIsland_Mart",
    ],
    38: [  # gMapGroup_IndoorThreeIslandRoute
        "ThreeIsland_Harbor",
    ],
    39: [  # gMapGroup_IndoorFiveIslandRoute
        "FiveIsland_ResortGorgeous_House",
    ],
    40: [  # gMapGroup_IndoorTwoIslandRoute
        "TwoIsland_CapeBrink_House",
    ],
    41: [  # gMapGroup_IndoorSixIslandRoute
        "SixIsland_WaterPath_House1", "SixIsland_WaterPath_House2",
    ],
    42: [  # gMapGroup_IndoorSevenIslandRoute
        "SevenIsland_SevaultCanyon_House",
    ],
}

# Build location_map: every FRLG map → physical snake_case name (display/debug only).
# Does NOT merge with area_map — encounter zones keep their floor-specific names here
# (e.g. "mt_moon_1f", "mt_moon_b1f" rather than the merged "mt_moon" in areas.lua).
# test_1 shows area_id (from areas.lua) when available; loc_name otherwise.
location_map = {}
for group_idx, names in ALL_MAP_GROUPS.items():
    for map_num, raw_name in enumerate(names):
        location_map[f"{group_idx}:{map_num}"] = to_snake(raw_name)

loc_sorted_keys = sorted(location_map.keys(), key=lambda x: tuple(int(n) for n in x.split(":")))
loc_lua_lines = [
    "-- data/games/gen3_frlge/gen3_frlge_locations.lua — AUTO-GENERATED by gen_area_map.py — DO NOT EDIT BY HAND",
    "-- Re-run: cd SLink && python tools/gen_area_map.py",
    "--",
    "-- Maps (mapGroup .. ':' .. mapNum) -> physical snake_case location name.",
    "-- Covers ALL 43 FRLG map groups including towns, buildings, and dungeons.",
    "-- For DISPLAY / DEBUG only — Soul Link encounter logic uses areas.lua instead.",
    "-- Source: pret/pokefirered data/maps/map_groups.json",
    "",
    "return {",
]
for key in loc_sorted_keys:
    loc_lua_lines.append(f'  ["{key}"] = "{location_map[key]}",')
loc_lua_lines.append("}")

with open("data/games/gen3_frlge/gen3_frlge_locations.lua", "w", newline="\n", encoding="utf-8") as f:
    f.write("\n".join(loc_lua_lines) + "\n")

print(f"Generated {len(area_map)} area entries")
print(f"  → data/games/gen3_frlge/area_map.json")
print(f"  → data/games/gen3_frlge/gen3_frlge_areas.lua")
print(f"Generated {len(location_map)} location entries")
print(f"  → data/games/gen3_frlge/gen3_frlge_locations.lua")
print("Spot-checks (areas):")
for key in ["3:19", "1:1", "1:3", "1:81", "1:82", "1:72", "1:39", "1:63"]:
    print(f"  {key}: area={area_map.get(key)}  loc={location_map.get(key)}")
print("Spot-checks (towns/buildings):")
for key in ["3:0", "3:1", "3:4", "3:9", "5:1", "5:4", "7:5", "10:16"]:
    print(f"  {key}: loc={location_map.get(key)}")
