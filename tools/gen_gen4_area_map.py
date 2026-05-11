#!/usr/bin/env python3
"""
gen_gen4_area_map.py — Generate comprehensive HGSS zone-to-area_id mapping.

Outputs:
  data/games/gen4_hgsspt/gen4_hgsspt_areas.lua      — zone_id -> area_id lookup (Soul Link logic)
  data/games/gen4_hgsspt/gen4_hgsspt_locations.lua  — zone_id -> display name (HUD/status page)

Source: pret/pokeheartgold include/constants/maps.h (540 zones total)
All indoor zones are grouped under their parent town/route area_id.
"""

# Complete HGSS zone definitions from pret/pokeheartgold maps.h
# Format: zone_id: (area_id, display_name)
# Indoor zones map to their parent town's area_id for status display.
ZONE_MAP = {
    # System zones (not mapped — skipped)
    0: ("_system", "Everywhere"),
    1: ("_system", "Nothing"),
    2: ("_system", "Union Room"),
    3: ("_system", "Underground"),
    4: ("_system", "Wi-Fi Battle"),
    5: ("_system", "Wi-Fi Multi Battle"),

    # Bell Tower / Burned Tower / Ruins (multi-floor dungeon IDs)
    6: ("bell_tower", "Bell Tower"),
    7: ("burned_tower", "Burned Tower 1F"),
    8: ("ruins_of_alph", "Ruins of Alph"),

    # Kanto Routes 1-18
    9: ("route_1", "Route 1"),
    10: ("route_2", "Route 2"),
    11: ("route_3", "Route 3"),
    12: ("route_4", "Route 4"),
    13: ("route_5", "Route 5"),
    14: ("route_6", "Route 6"),
    15: ("route_7", "Route 7"),
    16: ("route_8", "Route 8"),
    17: ("route_9", "Route 9"),
    18: ("route_10", "Route 10"),
    19: ("route_11", "Route 11"),
    20: ("route_12", "Route 12"),
    21: ("route_13", "Route 13"),
    22: ("route_14", "Route 14"),
    23: ("route_15", "Route 15"),
    24: ("route_16", "Route 16"),
    25: ("route_17", "Route 17"),
    26: ("route_18", "Route 18"),
    27: ("route_22", "Route 22"),
    28: ("route_24", "Route 24"),
    29: ("route_25", "Route 25"),
    30: ("route_26", "Route 26"),
    31: ("route_27", "Route 27"),
    32: ("route_28", "Route 28"),

    # Johto Routes 29-48
    33: ("route_29", "Route 29"),
    34: ("route_30", "Route 30"),
    35: ("route_31", "Route 31"),
    36: ("route_32", "Route 32"),
    37: ("route_33", "Route 33"),
    38: ("route_34", "Route 34"),
    39: ("route_35", "Route 35"),
    40: ("route_36", "Route 36"),
    41: ("route_37", "Route 37"),
    42: ("route_38", "Route 38"),
    43: ("route_39", "Route 39"),
    44: ("route_42", "Route 42"),
    45: ("route_43", "Route 43"),
    46: ("route_44", "Route 44"),
    47: ("route_45", "Route 45"),
    48: ("route_46", "Route 46"),

    # Kanto Towns
    49: ("pallet_town", "Pallet Town"),
    50: ("viridian_city", "Viridian City"),
    51: ("pewter_city", "Pewter City"),
    52: ("cerulean_city", "Cerulean City"),
    53: ("lavender_town", "Lavender Town"),
    54: ("vermilion_city", "Vermilion City"),
    55: ("celadon_city", "Celadon City"),
    56: ("fuchsia_city", "Fuchsia City"),
    57: ("cinnabar_island", "Cinnabar Island"),
    58: ("indigo_plateau", "Indigo Plateau"),
    59: ("saffron_city", "Saffron City"),

    # New Bark Town + interiors
    60: ("new_bark_town", "New Bark Town"),
    61: ("new_bark_town", "Elm's Lab 1F"),
    62: ("new_bark_town", "Elm's Lab 2F"),
    63: ("new_bark_town", "Player's House 1F"),
    64: ("new_bark_town", "Player's House 2F"),
    65: ("new_bark_town", "New Bark SW House"),
    66: ("new_bark_town", "Rival's House"),

    # Cherrygrove City + interiors
    67: ("cherrygrove_city", "Cherrygrove City"),
    68: ("cherrygrove_city", "Cherrygrove Mart"),
    69: ("cherrygrove_city", "Cherrygrove PkCenter"),
    70: ("cherrygrove_city", "Cherrygrove SW House"),
    71: ("cherrygrove_city", "Guide Gent's House"),
    72: ("cherrygrove_city", "Cherrygrove SE House"),

    # Johto Towns (outdoor)
    73: ("violet_city", "Violet City"),
    74: ("azalea_town", "Azalea Town"),
    75: ("cianwood_city", "Cianwood City"),
    76: ("goldenrod_city", "Goldenrod City"),
    77: ("olivine_city", "Olivine City"),
    78: ("ecruteak_city", "Ecruteak City"),

    # Ecruteak interiors
    79: ("ecruteak_city", "Ecruteak Mart"),
    80: ("ecruteak_city", "Ecruteak Gym"),
    81: ("ecruteak_city", "Ecruteak PkCenter"),
    82: ("ecruteak_city", "Ecruteak House"),
    83: ("ecruteak_city", "Bell Tower Gate"),
    84: ("ecruteak_city", "Ecruteak Dowsing House"),
    85: ("ecruteak_city", "Ecruteak SW House"),
    86: ("ecruteak_city", "Dance Theater"),

    87: ("mahogany_town", "Mahogany Town"),
    88: ("lake_of_rage", "Lake of Rage"),
    89: ("blackthorn_city", "Blackthorn City"),
    90: ("mt_silver", "Mt. Silver"),

    # Water routes
    91: ("route_19", "Route 19"),
    92: ("route_20", "Route 20"),
    93: ("route_21", "Route 21"),
    94: ("route_40", "Route 40"),
    95: ("route_41", "Route 41"),

    # Dungeons and landmarks
    96: ("national_park", "National Park"),
    97: ("route_31", "Route 31 Gate"),
    98: ("route_32", "Route 32 Gate"),
    99: ("union_cave", "Union Cave 1F"),
    100: ("azalea_town", "Ilex Forest Gate"),
    101: ("route_35", "Route 35 Gate"),
    102: ("route_35", "Pokeathlon Gate"),
    103: ("route_36", "Ruins of Alph Gate"),
    104: ("route_36", "National Park Gate"),
    105: ("ecruteak_city", "Ecruteak Gate"),
    106: ("digletts_cave", "Diglett's Cave"),
    107: ("mt_moon", "Mt. Moon"),
    108: ("rock_tunnel", "Rock Tunnel 1F"),
    109: ("pal_park", "Pal Park"),
    110: ("sprout_tower", "Sprout Tower 1F"),
    111: ("bell_tower", "Bell Tower 1F"),
    112: ("goldenrod_city", "Radio Tower 1F"),
    113: ("ruins_of_alph", "Ruins of Alph"),
    114: ("slowpoke_well", "Slowpoke Well"),
    115: ("olivine_lighthouse", "Olivine Lighthouse 1F"),
    116: ("team_rocket_hq", "Team Rocket HQ"),
    117: ("ilex_forest", "Ilex Forest"),
    118: ("goldenrod_city", "Goldenrod Tunnel 1F"),
    119: ("mt_mortar", "Mt. Mortar 1F"),
    120: ("ice_path", "Ice Path 1F"),
    121: ("whirl_islands", "Whirl Islands 1F"),
    122: ("mt_silver_cave", "Mt. Silver Cave 1F"),
    123: ("dark_cave", "Dark Cave (Route 45)"),
    124: ("victory_road", "Victory Road 1F"),
    125: ("dragons_den", "Dragon's Den Entrance"),
    126: ("tohjo_falls", "Tohjo Falls"),

    # Route buildings and misc indoor
    127: ("route_30", "Apricorn House"),
    128: ("ecruteak_city", "Ecruteak PkCenter 2F"),
    129: ("ecruteak_city", "Ecruteak PkCenter 3F"),
    130: ("ecruteak_city", "Ecruteak PkCenter 4F"),
    131: ("ecruteak_city", "Ecruteak PkCenter B1F"),
    132: ("route_42", "Route 42 Gate"),
    133: ("mahogany_town", "Mahogany E House"),
    134: ("route_29", "Route 29 Gate"),
    135: ("violet_city", "Violet Gym"),
    136: ("azalea_town", "Azalea Gym Entrance"),
    137: ("goldenrod_city", "Goldenrod Gym"),
    138: ("olivine_city", "Olivine Gym"),
    139: ("cianwood_city", "Cianwood Gym"),
    140: ("mahogany_town", "Mahogany Gym"),
    141: ("blackthorn_city", "Blackthorn Gym"),
    142: ("route_43", "Route 43 Gate"),
    143: ("route_30", "Mr. Pokemon's House"),
    144: ("cherrygrove_city", "Cherrygrove PkCenter B1F"),
    145: ("cerulean_cave", "Cerulean Cave 1F"),
    146: ("seafoam_islands", "Seafoam Islands 1F"),
    147: ("viridian_forest", "Viridian Forest"),
    148: ("route_9", "Route 9 House"),
    149: ("violet_city", "Violet Gate"),
    150: ("national_park", "National Park Gate"),
    151: ("route_47", "Route 47"),
    152: ("route_48", "Route 48"),
    153: ("union_cave", "Union Cave B1F"),
    154: ("union_cave", "Union Cave B2F"),
    155: ("sprout_tower", "Sprout Tower 2F"),
    156: ("sprout_tower", "Sprout Tower 3F"),

    # Violet City interiors
    157: ("violet_city", "Violet Mart"),
    158: ("violet_city", "Violet PkCenter"),
    159: ("violet_city", "Pokemon School"),
    160: ("violet_city", "Violet NW House"),
    161: ("violet_city", "Violet House"),
    162: ("violet_city", "Violet Trade House"),

    # Azalea Town interiors
    163: ("azalea_town", "Charcoal Kiln"),
    164: ("azalea_town", "Kurt's House"),
    165: ("azalea_town", "Azalea Mart"),
    166: ("azalea_town", "Azalea PkCenter"),
    167: ("violet_city", "Violet PkCenter B1F"),
    168: ("azalea_town", "Azalea PkCenter B1F"),
    169: ("route_32", "Route 32 PkCenter"),
    170: ("route_32", "Route 32 PkCenter B1F"),
    171: ("route_34", "Ilex Forest Gate"),
    172: ("route_38", "Route 38 Gate"),
    173: ("safari_zone", "Safari Zone Gate"),
    174: ("safari_zone", "Safari Zone"),
    175: ("ecruteak_city", "Ecruteak House"),
    176: ("dark_cave", "Dark Cave (Route 31)"),
    177: ("slowpoke_well", "Slowpoke Well B1F"),
    178: ("victory_road", "Victory Road 2F"),
    179: ("victory_road", "Victory Road 3F"),
    180: ("azalea_town", "Azalea Gym"),
    181: ("slowpoke_well", "Slowpoke Well B2F"),

    # Goldenrod City interiors
    182: ("goldenrod_city", "Bike Shop"),
    183: ("goldenrod_city", "Game Corner"),
    184: ("goldenrod_city", "Flower Shop"),
    185: ("goldenrod_city", "Goldenrod PkCenter"),
    186: ("goldenrod_city", "Radio Tower 2F"),
    187: ("goldenrod_city", "Radio Tower 3F"),
    188: ("goldenrod_city", "Radio Tower 4F"),
    189: ("goldenrod_city", "Radio Tower 5F"),
    190: ("goldenrod_city", "Radio Tower Deck"),
    191: ("goldenrod_city", "Dept Store 1F"),
    192: ("goldenrod_city", "Dept Store 2F"),
    193: ("goldenrod_city", "Dept Store 3F"),
    194: ("goldenrod_city", "Dept Store 4F"),
    195: ("goldenrod_city", "Dept Store 5F"),
    196: ("goldenrod_city", "Dept Store 6F"),
    197: ("goldenrod_city", "Magnet Train 1F"),
    198: ("goldenrod_city", "Magnet Train 2F"),
    199: ("goldenrod_city", "Tunnel B1F"),
    200: ("goldenrod_city", "Dept Store B1F"),
    201: ("goldenrod_city", "Tunnel B2F"),
    202: ("goldenrod_city", "Tunnel Warehouse"),
    203: ("goldenrod_city", "Bill's House"),
    204: ("goldenrod_city", "Friendship House"),
    205: ("goldenrod_city", "Goldenrod NE House"),
    206: ("goldenrod_city", "Name Rater"),
    207: ("goldenrod_city", "Global Terminal 1F"),
    208: ("goldenrod_city", "Goldenrod House"),
    209: ("goldenrod_city", "Goldenrod House"),
    210: ("goldenrod_city", "Goldenrod House"),
    211: ("goldenrod_city", "Goldenrod House"),
    212: ("goldenrod_city", "Goldenrod House"),
    213: ("goldenrod_city", "Goldenrod House"),
    214: ("route_39", "Moomoo Farm"),
    215: ("route_39", "Moomoo Stable"),
    216: ("ecruteak_city", "Bell Tower Corridor"),
    217: ("burned_tower", "Burned Tower B1F"),
    218: ("ruins_of_alph", "Ruins of Alph"),
    219: ("goldenrod_city", "Goldenrod PkCenter B1F"),
    220: ("olivine_lighthouse", "Lighthouse 2F"),
    221: ("olivine_lighthouse", "Lighthouse Ext"),
    222: ("olivine_lighthouse", "Lighthouse 3F"),
    223: ("olivine_lighthouse", "Lighthouse 4F"),
    224: ("olivine_lighthouse", "Lighthouse 5F"),
    225: ("olivine_lighthouse", "Light Room"),

    # Olivine City interiors
    226: ("olivine_city", "Olivine PkCenter"),
    227: ("olivine_city", "Olivine Mart"),
    228: ("olivine_city", "Olivine N House"),
    229: ("olivine_city", "Olivine NE House"),
    230: ("olivine_city", "Olivine NW House"),
    231: ("olivine_city", "Olivine Cafe"),

    # Cianwood interiors
    232: ("cianwood_city", "Kirk's House"),
    233: ("cianwood_city", "Pharmacy"),
    234: ("cianwood_city", "Cameron's House"),
    235: ("cianwood_city", "Cianwood House"),
    236: ("cianwood_city", "Cianwood PkCenter"),

    # Ice Path floors
    237: ("ice_path", "Ice Path B1F"),
    238: ("ice_path", "Ice Path B2F"),
    239: ("ice_path", "Ice Path B3F"),

    240: ("olivine_city", "SS Aqua Port"),
    241: ("cianwood_city", "Cianwood PkCenter B1F"),

    # Whirl Islands floors
    242: ("whirl_islands", "Whirl Islands B1F"),
    243: ("whirl_islands", "Whirl Islands B2F"),
    244: ("whirl_islands", "Whirl Islands B3F"),

    245: ("route_43", "Route 43 Gate"),
    246: ("mahogany_town", "Mahogany PkCenter"),

    # Team Rocket HQ floors
    247: ("team_rocket_hq", "Rocket HQ B1F"),
    248: ("team_rocket_hq", "Rocket HQ B2F"),
    249: ("team_rocket_hq", "Rocket HQ B3F"),

    # Mt. Mortar floors
    250: ("mt_mortar", "Mt. Mortar Back"),
    251: ("mt_mortar", "Mt. Mortar 2F"),
    252: ("mt_mortar", "Mt. Mortar B1F"),

    253: ("dragons_den", "Dragon's Den"),

    # Battle Frontier complex
    254: ("battle_frontier", "Fight Area"),
    255: ("battle_frontier", "Fight Area PkCenter"),
    256: ("battle_frontier", "Fight Area"),
    257: ("battle_frontier", "Fight Area Mart"),
    258: ("battle_frontier", "Fight Area House"),
    259: ("battle_frontier", "Fight Area House"),
    260: ("battle_frontier", "Fight Area House"),
    261: ("battle_frontier", "Fight Area House"),
    262: ("battle_frontier", "Fight Area"),
    263: ("battle_frontier", "Battle Park"),
    264: ("battle_frontier", "Battle Park"),
    265: ("battle_frontier", "Battle Tower"),
    266: ("battle_frontier", "Battle Tower Elevator"),
    267: ("battle_frontier", "Battle Tower"),
    268: ("battle_frontier", "Battle Tower"),
    269: ("battle_frontier", "Battle Tower"),
    270: ("battle_frontier", "Battle Tower"),
    271: ("battle_frontier", "Battle Tower Partner"),
    272: ("battle_frontier", "Battle Frontier"),
    273: ("battle_frontier", "Frontier Access Gate"),
    274: ("battle_frontier", "Battle Tower"),
    275: ("battle_frontier", "Battle Factory"),
    276: ("battle_frontier", "Battle Hall"),
    277: ("battle_frontier", "Battle Castle"),
    278: ("battle_frontier", "Battle Arcade"),

    279: ("route_47", "Cliff Edge Gate"),

    # Pokeathlon Dome (near National Park)
    280: ("national_park", "Pokeathlon Dome"),
    281: ("national_park", "Pokeathlon 1F"),
    282: ("national_park", "Pokeathlon 2F"),
    283: ("national_park", "Pokeathlon Entrance"),
    284: ("national_park", "Pokeathlon B1F"),
    285: ("national_park", "Pokeathlon B1F"),
    286: ("national_park", "Pokeathlon B1F"),
    287: ("national_park", "Pokeathlon B1F"),

    288: ("dragons_den", "Dragon's Den Shrine"),

    # Blackthorn interiors
    289: ("blackthorn_city", "Blackthorn W House"),
    290: ("blackthorn_city", "Blackthorn E House"),
    291: ("blackthorn_city", "Move Tutor House"),
    292: ("blackthorn_city", "Blackthorn Mart"),
    293: ("blackthorn_city", "Blackthorn PkCenter"),

    # Lake of Rage interiors
    294: ("lake_of_rage", "Hidden Power House"),
    295: ("lake_of_rage", "Fishing Guru House"),

    # Route 26 interiors
    296: ("route_26", "Route 26 N House"),
    297: ("route_26", "Route 26 House"),

    298: ("tohjo_falls", "Tohjo Falls Hidden"),

    # Indigo Plateau / Pokemon League
    299: ("indigo_plateau", "League Reception"),
    300: ("indigo_plateau", "League Entrance"),
    301: ("indigo_plateau", "Will's Room"),
    302: ("indigo_plateau", "Koga's Room"),
    303: ("indigo_plateau", "Bruno's Room"),
    304: ("indigo_plateau", "Karen's Room"),
    305: ("indigo_plateau", "Lance's Room"),
    306: ("indigo_plateau", "Hall of Fame"),

    # SS Aqua
    307: ("ss_aqua", "SS Aqua 1F"),
    308: ("ss_aqua", "SS Aqua Captain"),
    309: ("ss_aqua", "SS Aqua SE Rooms"),
    310: ("ss_aqua", "SS Aqua SW Rooms"),
    311: ("ss_aqua", "SS Aqua NE Rooms"),

    # Ruins of Alph interiors
    312: ("ruins_of_alph", "Ruins NE Room"),
    313: ("ruins_of_alph", "Ruins NE Hidden"),
    314: ("ruins_of_alph", "Ruins SE Room"),
    315: ("ruins_of_alph", "Ruins Underground"),
    316: ("ruins_of_alph", "Ruins SW Room"),
    317: ("ruins_of_alph", "Ruins SW Hidden"),
    318: ("ruins_of_alph", "Ruins NW Room"),
    319: ("ruins_of_alph", "Ruins NW Hidden"),
    320: ("ruins_of_alph", "Ruins SE Hidden"),
    321: ("ruins_of_alph", "Research Center"),
    322: ("route_27", "Route 27 House"),
    323: ("ruins_of_alph", "Ruins Hall"),
    324: ("ruins_of_alph", "Ruins NE 2nd"),
    325: ("ruins_of_alph", "Ruins SE 2nd"),
    326: ("ruins_of_alph", "Ruins NW 2nd"),
    327: ("ruins_of_alph", "Ruins SW 2nd"),

    # SS Aqua continued
    328: ("ss_aqua", "SS Aqua NW Rooms"),
    329: ("ss_aqua", "SS Aqua B1F"),
    330: ("olivine_city", "SS Aqua Port Ext"),
    331: ("route_34", "Daycare"),

    # Bell Tower floors
    332: ("bell_tower", "Bell Tower 2F"),
    333: ("bell_tower", "Bell Tower 3F"),
    334: ("bell_tower", "Bell Tower 4F"),
    335: ("bell_tower", "Bell Tower 5F"),
    336: ("bell_tower", "Bell Tower 6F"),
    337: ("bell_tower", "Bell Tower 7F"),
    338: ("bell_tower", "Bell Tower 8F"),
    339: ("bell_tower", "Bell Tower 9F"),
    340: ("bell_tower", "Bell Tower Roof"),
    341: ("bell_tower", "Bell Tower 10F"),

    342: ("cliff_cave", "Cliff Cave"),

    # Safari Zone areas
    343: ("safari_zone", "Safari Zone 01"),
    344: ("safari_zone", "Safari Zone 02"),
    345: ("safari_zone", "Safari Zone 03"),
    346: ("safari_zone", "Safari Zone 04"),
    347: ("safari_zone", "Safari Zone 05"),
    348: ("safari_zone", "Safari Zone 06"),
    349: ("safari_zone", "Safari Zone 07"),
    350: ("safari_zone", "Safari Zone 08"),
    351: ("safari_zone", "Safari Zone 09"),
    352: ("safari_zone", "Safari Zone 10"),
    353: ("safari_zone", "Safari Zone 11"),
    354: ("safari_zone", "Safari Zone 12"),
    355: ("safari_zone", "Safari Zone 13"),
    356: ("safari_zone", "Safari Zone 14"),
    357: ("safari_zone", "Safari Zone Ext"),

    # Vermilion City interiors
    358: ("vermilion_city", "Vermilion PkCenter"),
    359: ("vermilion_city", "Vermilion PkCenter B1F"),
    360: ("vermilion_city", "Vermilion Mart"),
    361: ("vermilion_city", "Fishing Dude House"),
    362: ("vermilion_city", "Pokemon Fan Club"),
    363: ("vermilion_city", "Vermilion House"),
    364: ("vermilion_city", "Vermilion S House"),
    365: ("vermilion_city", "Vermilion Gym"),

    366: ("route_40", "Frontier Gate"),
    367: ("olivine_city", "Olivine PkCenter B1F"),
    368: ("mahogany_town", "Mahogany PkCenter B1F"),
    369: ("blackthorn_city", "Blackthorn PkCenter B1F"),

    # Celadon City interiors
    370: ("celadon_city", "Dept Store 1F"),
    371: ("celadon_city", "Dept Store 2F"),
    372: ("celadon_city", "Dept Store 3F"),
    373: ("celadon_city", "Dept Store 4F"),
    374: ("celadon_city", "Dept Store 5F"),
    375: ("celadon_city", "Dept Store Roof"),
    376: ("celadon_city", "Condominiums 1F"),
    377: ("celadon_city", "Condominiums 2F"),
    378: ("celadon_city", "Condominiums 3F"),
    379: ("celadon_city", "Condominiums Roof"),
    380: ("celadon_city", "Condominiums Room"),
    381: ("celadon_city", "Game Corner"),
    382: ("celadon_city", "Prize Corner"),
    383: ("celadon_city", "Restaurant"),

    384: ("new_bark_town", "Rival's House 2F"),
    385: ("cianwood_city", "Cianwood N House"),

    # Vermilion SS Aqua port
    386: ("vermilion_city", "SS Aqua Port Int"),
    387: ("vermilion_city", "SS Aqua Port Ext"),

    388: ("route_10", "Route 10 South"),

    # Route gatehouses
    389: ("route_6", "Saffron Gate"),
    390: ("route_8", "Saffron Gate"),
    391: ("route_5", "Saffron Gate"),
    392: ("route_15", "Fuchsia Gate"),

    # Celadon continued
    393: ("celadon_city", "Celadon PkCenter"),
    394: ("celadon_city", "Celadon PkCenter B1F"),
    395: ("celadon_city", "Celadon Gym"),

    # Mahogany Gym rooms
    396: ("mahogany_town", "Mahogany Gym 2"),
    397: ("mahogany_town", "Mahogany Gym 1"),

    # Saffron City interiors
    398: ("saffron_city", "Fighting Dojo"),
    399: ("saffron_city", "Mr. Psychic House"),
    400: ("saffron_city", "Magnet Train 1F"),
    401: ("saffron_city", "Magnet Train 2F"),
    402: ("saffron_city", "Silph Co"),
    403: ("saffron_city", "Silph Rotom Room"),
    404: ("saffron_city", "Copycat House 1F"),
    405: ("saffron_city", "Copycat House 2F"),
    406: ("saffron_city", "Saffron House"),
    407: ("saffron_city", "Saffron PkCenter"),
    408: ("saffron_city", "Saffron PkCenter 2F"),
    409: ("saffron_city", "Saffron Mart"),
    410: ("saffron_city", "Saffron Gym"),

    411: ("battle_frontier", "Frontier Access"),
    412: ("goldenrod_city", "Global Terminal 2F"),
    413: ("goldenrod_city", "Global Terminal 3F"),

    # Route interiors
    414: ("route_2", "Route 2 East"),
    415: ("route_16", "Route 16 House"),
    416: ("route_20", "Route 20 House"),
    417: ("route_2", "Route 2 House"),
    418: ("route_2", "Route 2 SE Gate"),
    419: ("route_2", "Forest S Gate"),
    420: ("route_2", "Forest N Gate"),
    421: ("route_16", "Route 16 Gate"),
    422: ("route_16", "Route 16 East"),
    423: ("route_18", "Route 18 Gate"),
    424: ("route_19", "Fuchsia Gate"),
    425: ("route_11", "Route 12 Gate"),

    # Cerulean City interiors
    426: ("cerulean_city", "Cerulean Mart"),
    427: ("cerulean_city", "Cerulean Gym"),
    428: ("cerulean_city", "Cerulean PkCenter"),
    429: ("cerulean_city", "Cerulean N House"),
    430: ("cerulean_city", "Cerulean E House"),
    431: ("cerulean_city", "Cerulean W House"),
    432: ("cerulean_city", "Bike Maniac House"),

    # Lavender Town interiors
    433: ("lavender_town", "Lavender Mart"),
    434: ("lavender_town", "Lavender PkCenter"),
    435: ("lavender_town", "Volunteer House"),
    436: ("lavender_town", "Lavender SW House"),
    437: ("lavender_town", "Name Rater"),
    438: ("lavender_town", "House of Memories"),
    439: ("lavender_town", "Radio Station"),

    440: ("route_25", "Sea Cottage"),

    # Elevators
    441: ("goldenrod_city", "Dept Store Elevator"),
    442: ("celadon_city", "Dept Store Elevator"),
    443: ("celadon_city", "Condo L Elevator"),
    444: ("celadon_city", "Condo R Elevator"),
    445: ("saffron_city", "Silph Elevator"),
    446: ("olivine_lighthouse", "Lighthouse Elevator"),
    447: ("goldenrod_city", "Radio Tower Elevator"),

    # Mt. Moon floors
    448: ("mt_moon", "Mt. Moon Square Ent"),
    449: ("mt_moon", "Mt. Moon Square"),

    # Cerulean Cave floors
    450: ("cerulean_cave", "Cerulean Cave 2F"),
    451: ("cerulean_cave", "Cerulean Cave B1F"),

    452: ("rock_tunnel", "Rock Tunnel B1F"),

    # Seafoam Islands floors
    453: ("seafoam_islands", "Seafoam B1F"),
    454: ("seafoam_islands", "Seafoam B2F"),
    455: ("seafoam_islands", "Seafoam B3F"),
    456: ("seafoam_islands", "Seafoam B4F"),
    457: ("seafoam_islands", "Cinnabar Gym"),
    458: ("seafoam_islands", "Seafoam Unused"),

    # Mt. Silver Cave floors
    459: ("mt_silver_cave", "Mt. Silver Upper"),
    460: ("mt_silver_cave", "Mt. Silver Lower"),
    461: ("mt_silver_cave", "Expert Belt"),
    462: ("mt_silver_cave", "Moltres Chamber"),
    463: ("mt_silver_cave", "Mt. Silver 2F"),
    464: ("mt_silver_cave", "Mt. Silver 3F"),
    465: ("mt_silver_cave", "Mt. Silver Summit"),

    # Route 10 interiors
    466: ("route_10", "Route 10 PkCenter"),
    467: ("route_10", "Power Plant"),
    468: ("route_5", "Route 5 House"),
    469: ("route_5", "Underground Gate"),
    470: ("route_6", "Underground Gate"),

    # Pewter City interiors
    471: ("pewter_city", "Museum of Science"),
    472: ("pewter_city", "Pewter NE House"),
    473: ("pewter_city", "Pewter Gym"),
    474: ("pewter_city", "Pewter Mart"),
    475: ("pewter_city", "Pewter PkCenter"),
    476: ("pewter_city", "Pewter PkCenter B1F"),
    477: ("pewter_city", "Pewter SW House"),

    # Fuchsia City interiors
    478: ("fuchsia_city", "Fuchsia Mart"),
    479: ("fuchsia_city", "Pal Park Entrance"),
    480: ("fuchsia_city", "Fuchsia Gym"),
    481: ("fuchsia_city", "Fuchsia SW House"),
    482: ("fuchsia_city", "Fuchsia PkCenter"),
    483: ("fuchsia_city", "Warden's House"),
    484: ("route_10", "Route 10 PkCenter B1F"),
    485: ("fuchsia_city", "Fuchsia PkCenter B1F"),

    486: ("whirl_islands", "Whirl Islands B3F"),

    # National Park variants
    487: ("national_park", "Bug Contest"),
    488: ("national_park", "National Park"),

    489: ("route_10", "Power Plant Broken"),

    # Ruins of Alph Sinjoh events
    490: ("ruins_of_alph", "Sinjoh Event"),
    491: ("ruins_of_alph", "Sinjoh Hall"),
    492: ("ruins_of_alph", "Sinjoh Event 2"),

    493: ("route_7", "Saffron Gate"),
    494: ("lavender_town", "Lavender PkCenter B1F"),
    495: ("cerulean_city", "Cerulean PkCenter B1F"),

    # Viridian City interiors
    496: ("viridian_city", "Viridian Gym"),
    497: ("viridian_city", "Viridian NE House"),
    498: ("viridian_city", "Trainer House 1F"),
    499: ("viridian_city", "Trainer House B1F"),
    500: ("viridian_city", "Viridian Mart"),
    501: ("viridian_city", "Viridian PkCenter"),
    502: ("viridian_city", "Viridian PkCenter B1F"),

    # Pallet Town interiors
    503: ("pallet_town", "Red's House 1F"),
    504: ("pallet_town", "Blue's House 1F"),
    505: ("pallet_town", "Oak's Lab"),
    506: ("pallet_town", "Red's House 2F"),
    507: ("pallet_town", "Blue's House 2F"),

    # Cinnabar Island
    508: ("cinnabar_island", "Cinnabar PkCenter"),
    509: ("cinnabar_island", "Cinnabar PkCenter B1F"),

    510: ("route_28", "Route 28 House"),
    511: ("route_3", "Route 3 PkCenter"),
    512: ("route_3", "Route 3 PkCenter B1F"),
    513: ("mt_moon", "Mt. Moon Clefairy"),

    # Mt. Silver PkCenter
    514: ("mt_silver", "Mt. Silver PkCenter"),
    515: ("mt_silver", "Mt. Silver PkCenter B1F"),

    516: ("_system", "Wi-Fi Plaza"),
    517: ("route_5", "Route 5 House"),
    518: ("mt_moon", "Mt. Moon Shop"),
    519: ("goldenrod_city", "Magnet Train Empty"),
    520: ("saffron_city", "Magnet Train Empty"),

    # Sinjoh Ruins
    521: ("sinjoh_ruins", "Sinjoh Exterior"),
    522: ("sinjoh_ruins", "Mystri Stage"),
    523: ("sinjoh_ruins", "Sinjoh Cabin"),

    # Embedded Tower (legendary)
    524: ("embedded_tower", "Groudon Room"),
    525: ("embedded_tower", "Kyogre Room"),
    526: ("embedded_tower", "Rayquaza Room"),

    527: ("viridian_city", "Route 1 Gate"),

    # Battle Frontier facilities
    528: ("battle_frontier", "Frontier PkCenter"),
    529: ("battle_frontier", "Frontier PkCenter B1F"),
    530: ("battle_frontier", "Frontier Mart"),
    531: ("battle_frontier", "Frontier Tutor"),
    532: ("route_5", "Underground Path"),
    533: ("route_12", "Fishing House"),
    534: ("safari_zone", "Safari PkCenter"),
    535: ("safari_zone", "Safari PkCenter B1F"),
    536: ("goldenrod_city", "Game Corner"),
    537: ("celadon_city", "Game Corner"),

    538: ("_system", "Unused"),
    539: ("indigo_plateau", "Wi-Fi Room"),
}




# -- Platinum zone map ---------------------------------------------------------------
# Source: pret/pokeplatinum generated/map_headers.txt (593 entries, 0-indexed).
# Building interiors map to their parent area_id. UNKNOWN_N zones are omitted.
# Zones not in this dict return "" from Lua lookup (no encounter tracking).
ZONE_MAP_PT = {
    # System zones
    0:   ("_system", "Everywhere"),
    1:   ("_system", "Wi-Fi Plaza"),
    2:   ("_system", "Underground"),
    3: ('jubilife_city', 'Jubilife City'),
    4: ('jubilife_city', 'Jubilife City Mart'),
    5: ('jubilife_city', 'Jubilife City Unknown House 1'),
    6: ('jubilife_city', 'Jubilife City Pokecenter 1F'),
    7: ('jubilife_city', 'Jubilife City Pokecenter 2F'),
    8: ('jubilife_city', 'Poketch Co 1F'),
    9: ('jubilife_city', 'Poketch Co 2F'),
    10: ('jubilife_city', 'Poketch Co 3F'),
    11: ('jubilife_city', 'Jubilife Tv 1F'),
    12: ('jubilife_city', 'Jubilife Tv 2F'),
    13: ('jubilife_city', 'Jubilife Tv 3F'),
    14: ('jubilife_city', 'Jubilife Tv 4F'),
    15: ('jubilife_city', 'Jubilife Tv 2F Gallery'),
    16: ('jubilife_city', 'Jubilife Tv 3F Global Ranking Room'),
    17: ('jubilife_city', 'Jubilife Tv 3F Group Ranking Room'),
    18: ('jubilife_city', 'Jubilife Tv Elevator'),
    19: ('jubilife_city', 'Jubilife City South House 1F'),
    20: ('jubilife_city', 'Jubilife City South House 2F'),
    21: ('jubilife_city', 'Jubilife City South House 3F'),
    22: ('jubilife_city', 'Jubilife City South House 4F'),
    23: ('jubilife_city', 'Jubilife City Unknown House 2'),
    24: ('jubilife_city', 'Jubilife City Condominiums 1F'),
    25: ('jubilife_city', 'Jubilife City Condominiums 2F'),
    26: ('jubilife_city', 'Jubilife City Condominiums 3F'),
    27: ('jubilife_city', 'Jubilife City Condominiums 4F'),
    28: ('jubilife_city', 'Global Terminal 1F'),
    29: ('jubilife_city', 'Trainers School'),
    30: ('jubilife_city', 'Jubilife City Southwest House 1F'),
    31: ('jubilife_city', 'Jubilife City Unknown House 3'),
    32: ('jubilife_city', 'Jubilife City Unknown House 4'),
    33: ('canalave_city', 'Canalave City'),
    34: ('canalave_city', 'Canalave City Mart'),
    35: ('canalave_city', 'Canalave City Gym'),
    36: ('canalave_city', 'Canalave City Pokecenter 1F'),
    37: ('canalave_city', 'Canalave City Pokecenter 2F'),
    38: ('canalave_city', 'Canalave Library 1F'),
    39: ('canalave_city', 'Canalave Library 2F'),
    40: ('canalave_city', 'Canalave Library 3F'),
    41: ('canalave_city', 'Canalave City Southeast House'),
    42: ('canalave_city', 'Canalave City East House'),
    43: ('canalave_city', 'Canalave City Harbor Inn'),
    44: ('canalave_city', 'Canalave City Sailor Eldritch House'),
    45: ('oreburgh_city', 'Oreburgh City'),
    46: ('oreburgh_city', 'Oreburgh City Mart'),
    47: ('oreburgh_city', 'Oreburgh City Gym'),
    48: ('oreburgh_city', 'Oreburgh City Pokecenter 1F'),
    49: ('oreburgh_city', 'Oreburgh City Pokecenter 2F'),
    50: ('oreburgh_city', 'Oreburgh City Northwest House 1F'),
    51: ('oreburgh_city', 'Oreburgh City Northwest House 2F'),
    52: ('oreburgh_city', 'Oreburgh City Northwest House 3F'),
    53: ('oreburgh_city', 'Oreburgh City Northwest House 4F'),
    54: ('oreburgh_city', 'Oreburgh City North House 1F'),
    55: ('oreburgh_city', 'Oreburgh City North House 2F'),
    56: ('oreburgh_city', 'Oreburgh City North House 3F'),
    57: ('oreburgh_city', 'Oreburgh City North House 4F'),
    58: ('oreburgh_city', 'Oreburgh City Middle House'),
    59: ('oreburgh_city', 'Mining Museum'),
    60: ('oreburgh_city', 'Oreburgh City West House'),
    61: ('oreburgh_city', 'Oreburgh City East House 1F'),
    62: ('oreburgh_city', 'Oreburgh City East House 2F'),
    63: ('oreburgh_city', 'Oreburgh City East House 3F'),
    64: ('oreburgh_city', 'Oreburgh City South House'),
    65: ('eterna_city', 'Eterna City'),
    66: ('eterna_city', 'Eterna City Mart'),
    67: ('eterna_city', 'Eterna City Gym'),
    68: ('eterna_city', 'Eterna City Dp Gym'),
    69: ('eterna_city', 'Eterna City Pokecenter 1F'),
    70: ('eterna_city', 'Eterna City Pokecenter 2F'),
    72: ('galactic_hq', 'Team Galactic Eterna Building 1F'),
    73: ('galactic_hq', 'Team Galactic Eterna Building 2F'),
    74: ('galactic_hq', 'Team Galactic Eterna Building 3F'),
    75: ('galactic_hq', 'Team Galactic Eterna Building 4F'),
    76: ('eterna_city', 'Eterna City Condominiums 1F'),
    77: ('eterna_city', 'Eterna City Condominiums 2F'),
    78: ('eterna_city', 'Eterna City Condominiums 3F'),
    79: ('eterna_city', 'Unused Eterna City Condominiums 4F'),
    80: ('route_206', 'Route 206 Cycling Road North Gate'),
    81: ('eterna_city', 'Eterna City Herb Shop'),
    82: ('eterna_city', 'Eterna City South House'),
    83: ('eterna_city', 'Eterna City East House'),
    85: ('eterna_city', 'Eterna City Unknown House'),
    86: ('hearthome_city', 'Hearthome City'),
    87: ('hearthome_city', 'Hearthome City Mart'),
    88: ('hearthome_city', 'Hearthome City Gym Entrance Room'),
    89: ('hearthome_city', 'Hearthome City Gym Trainer Room 1'),
    90: ('hearthome_city', 'Hearthome City Gym Trainer Room 2'),
    91: ('hearthome_city', 'Hearthome City Gym Leader Room'),
    92: ('hearthome_city', 'Hearthome City Dp Gym Trainer Room 1'),
    93: ('hearthome_city', 'Hearthome City Dp Gym Elevator Room 1'),
    94: ('hearthome_city', 'Hearthome City Dp Gym Trainer Room 2'),
    95: ('hearthome_city', 'Hearthome City Dp Gym Elevator Room 2'),
    96: ('hearthome_city', 'Hearthome City Dp Gym Trainer Room 3'),
    97: ('hearthome_city', 'Hearthome City Dp Gym Trainer Room 4'),
    98: ('hearthome_city', 'Hearthome City Dp Gym Trainer Room 5'),
    99: ('hearthome_city', 'Hearthome City Dp Gym Trainer Room 6'),
    100: ('hearthome_city', 'Hearthome City Dp Gym Leader Room'),
    101: ('hearthome_city', 'Hearthome City Pokecenter 1F'),
    102: ('hearthome_city', 'Hearthome City Pokecenter 2F'),
    103: ('hearthome_city', 'Hearthome City Southeast House 1F'),
    104: ('hearthome_city', 'Hearthome City Southeast House 2F'),
    105: ('hearthome_city', 'Hearthome City Southeast House Elevator'),
    106: ('hearthome_city', 'Hearthome City Pokemon Fan Club'),
    107: ('hearthome_city', 'Hearthome City West Gate To Amity Square'),
    108: ('hearthome_city', 'Hearthome City East Gate To Amity Square'),
    109: ('route_208', 'Route 208 Gate To Hearthome City'),
    110: ('route_209', 'Route 209 Gate To Hearthome City'),
    111: ('route_212', 'Route 212 Gate To Hearthome City'),
    112: ('hearthome_city', 'Hearthome City Northeast House 1F'),
    113: ('hearthome_city', 'Hearthome City Northeast House 2F'),
    114: ('hearthome_city', 'Hearthome City Northeast House Elevator'),
    115: ('hearthome_city', 'Hearthome City Northwest House'),
    116: ('hearthome_city', 'Poffin House'),
    117: ('hearthome_city', 'Contest Hall Lobby'),
    118: ('hearthome_city', 'Contest Hall Stage Ongoing Contest'),
    120: ('pastoria_city', 'Pastoria City'),
    121: ('pastoria_city', 'Pastoria City Mart'),
    122: ('pastoria_city', 'Pastoria City Gym'),
    123: ('pastoria_city', 'Pastoria City Pokecenter 1F'),
    124: ('pastoria_city', 'Pastoria City Pokecenter 2F'),
    125: ('pastoria_city', 'Pastoria City Observatory Gate 1F'),
    126: ('pastoria_city', 'Pastoria City Observatory Gate 2F'),
    127: ('pastoria_city', 'Pastoria City Southwest House'),
    128: ('pastoria_city', 'Pastoria City Middle House'),
    129: ('pastoria_city', 'Pastoria City East House'),
    130: ('pastoria_city', 'Pastoria City North House'),
    131: ('pastoria_city', 'Pastoria City Northeast House'),
    132: ('veilstone_city', 'Veilstone City'),
    133: ('veilstone_city', 'Veilstone City Gym'),
    134: ('veilstone_city', 'Veilstone City Pokecenter 1F'),
    135: ('veilstone_city', 'Veilstone City Pokecenter 2F'),
    136: ('veilstone_city', 'Game Corner'),
    137: ('veilstone_city', 'Veilstone Store 1F'),
    138: ('veilstone_city', 'Veilstone Store 2F'),
    139: ('veilstone_city', 'Veilstone Store 3F'),
    140: ('veilstone_city', 'Veilstone Store 4F'),
    141: ('veilstone_city', 'Veilstone Store 5F'),
    142: ('veilstone_city', 'Veilstone Store Elevator'),
    143: ('veilstone_city', 'Veilstone City Galactic Warehouse'),
    144: ('veilstone_city', 'Veilstone City Prize Exchange'),
    145: ('veilstone_city', 'Veilstone City Southeast House'),
    146: ('veilstone_city', 'Veilstone City Northwest House'),
    147: ('veilstone_city', 'Veilstone City Northeast House'),
    148: ('veilstone_city', 'Veilstone City Southwest House'),
    149: ('route_215', 'Route 215 Gate To Veilstone City'),
    150: ('sunyshore_city', 'Sunyshore City'),
    151: ('sunyshore_city', 'Sunyshore City Pokecenter 1F'),
    152: ('sunyshore_city', 'Sunyshore City Pokecenter 2F'),
    153: ('sunyshore_city', 'Sunyshore City Mart'),
    154: ('sunyshore_city', 'Sunyshore City Gym Room 1'),
    155: ('sunyshore_city', 'Sunyshore City Gym Room 2'),
    156: ('sunyshore_city', 'Sunyshore City Gym Room 3'),
    157: ('sunyshore_city', 'Sunyshore Market'),
    158: ('sunyshore_city', 'Sunyshore City Northeast House'),
    159: ('sunyshore_city', 'Sunyshore City West House'),
    160: ('sunyshore_city', 'Sunyshore City Northwest House'),
    161: ('sunyshore_city', 'Sunyshore City Unknown House 1'),
    162: ('sunyshore_city', 'Sunyshore City Unknown House 2'),
    163: ('sunyshore_city', 'Sunyshore City East House'),
    164: ('sunyshore_city', 'Vista Lighthouse'),
    165: ('snowpoint_city', 'Snowpoint City'),
    166: ('snowpoint_city', 'Snowpoint City Mart'),
    167: ('snowpoint_city', 'Snowpoint City Gym'),
    168: ('snowpoint_city', 'Snowpoint City Pokecenter 1F'),
    169: ('snowpoint_city', 'Snowpoint City Pokecenter 2F'),
    170: ('snowpoint_city', 'Snowpoint City West House'),
    171: ('snowpoint_city', 'Snowpoint City East House'),
    172: ('pokemon_league', 'Pokemon League'),
    173: ('pokemon_league', 'Pokemon League South Pokecenter 1F'),
    174: ('pokemon_league', 'Pokemon League South Pokecenter 2F'),
    175: ('pokemon_league', 'Pokemon League North Pokecenter 1F'),
    176: ('pokemon_league', 'Pokemon League Elevator To Aaron Room'),
    177: ('pokemon_league', 'Pokemon League Aaron Room'),
    178: ('pokemon_league', 'Pokemon League Elevator To Bertha Room'),
    179: ('pokemon_league', 'Pokemon League Bertha Room'),
    180: ('pokemon_league', 'Pokemon League Elevator To Flint Room'),
    181: ('pokemon_league', 'Pokemon League Flint Room'),
    182: ('pokemon_league', 'Pokemon League Elevator To Lucian Room'),
    183: ('pokemon_league', 'Pokemon League Lucian Room'),
    184: ('pokemon_league', 'Pokemon League Elevator To Champion Room'),
    185: ('pokemon_league', 'Pokemon League Champion Room'),
    186: ('pokemon_league', 'Pokemon League Hallway To Hall Of Fame'),
    187: ('pokemon_league', 'Pokemon League Hall Of Fame'),
    188: ('fight_area', 'Fight Area'),
    189: ('fight_area', 'Fight Area Pokecenter 1F'),
    190: ('fight_area', 'Fight Area Pokecenter 2F'),
    191: ('fight_area', 'Fight Area Mart'),
    192: ('fight_area', 'Battle Park Gate To Fight Area'),
    193: ('route_225', 'Route 225 Gate To Fight Area'),
    194: ('fight_area', 'Fight Area Middle House'),
    195: ('fight_area', 'Fight Area South House'),
    196: ('fight_area', 'Fight Area Unknown House'),
    198: ('oreburgh_mine', 'Oreburgh Mine B1F'),
    199: ('oreburgh_mine', 'Oreburgh Mine B2F'),
    200: ('valley_windworks', 'Valley Windworks Outside'),
    201: ('valley_windworks', 'Valley Windworks Building'),
    202: ('eterna_forest', 'Eterna Forest Outside'),
    203: ('eterna_forest', 'Eterna Forest'),
    204: ('fuego_ironworks', 'Fuego Ironworks Outside'),
    205: ('fuego_ironworks', 'Fuego Ironworks Building'),
    207: ('mt_coronet', 'Mt Coronet 1F South'),
    208: ('mt_coronet', 'Mt Coronet 2F'),
    209: ('mt_coronet', 'Mt Coronet 3F'),
    210: ('mt_coronet', 'Mt Coronet Outside North'),
    211: ('mt_coronet', 'Mt Coronet Outside South'),
    212: ('mt_coronet', 'Mt Coronet 4F Rooms 1 And 2'),
    213: ('mt_coronet', 'Mt Coronet 4F Room 3'),
    214: ('mt_coronet', 'Mt Coronet 5F'),
    215: ('mt_coronet', 'Mt Coronet 6F'),
    216: ('mt_coronet', 'Mt Coronet 1F Tunnel Room'),
    217: ('mt_coronet', 'Mt Coronet 1F North Room 2'),
    218: ('mt_coronet', 'Mt Coronet 1F North Room 1'),
    219: ('mt_coronet', 'Mt Coronet B1F'),
    220: ('spear_pillar', 'Spear Pillar'),
    221: ('spear_pillar', 'Spear Pillar Distorted'),
    223: ('pastoria_city', 'Pastoria City Dp Great Marsh'),
    225: ('solaceon_ruins', 'Solaceon Ruins Maniac Tunnel Room'),
    226: ('solaceon_ruins', 'Solaceon Ruins Room 1'),
    227: ('solaceon_ruins', 'Solaceon Ruins Room 2 Northeast Dead End'),
    228: ('solaceon_ruins', 'Solaceon Ruins Room 1 Northwest Dead End'),
    229: ('solaceon_ruins', 'Solaceon Ruins Room 2'),
    230: ('solaceon_ruins', 'Solaceon Ruins Room 1 Southeast Dead End'),
    231: ('solaceon_ruins', 'Solaceon Ruins Room 3'),
    232: ('solaceon_ruins', 'Solaceon Ruins Room 2 Southeast Dead End'),
    233: ('solaceon_ruins', 'Solaceon Ruins Room 6 Southeast Dead End'),
    234: ('solaceon_ruins', 'Solaceon Ruins Room 5 Southwest Dead End'),
    235: ('solaceon_ruins', 'Solaceon Ruins Room 3 Northwest Dead End'),
    236: ('solaceon_ruins', 'Solaceon Ruins Room 3 Southwest Dead End'),
    237: ('solaceon_ruins', 'Solaceon Ruins Room 4'),
    238: ('solaceon_ruins', 'Solaceon Ruins Room 6'),
    239: ('solaceon_ruins', 'Solaceon Ruins Room 5'),
    240: ('solaceon_ruins', 'Solaceon Ruins Room 7'),
    241: ('solaceon_ruins', 'Solaceon Ruins Room 4 Southeast Dead End'),
    242: ('solaceon_ruins', 'Solaceon Ruins Room 6 Northwest Dead End'),
    244: ('victory_road_pt', 'Victory Road 1F'),
    245: ('victory_road_pt', 'Victory Road 2F'),
    246: ('victory_road_pt', 'Victory Road B1F'),
    247: ('victory_road_pt', 'Victory Road 1F Room 2'),
    248: ('victory_road_pt', 'Victory Road 1F Room 1'),
    249: ('victory_road_pt', 'Victory Road 1F Room 3'),
    251: ('pal_park', 'Pal Park'),
    253: ('hearthome_city', 'Amity Square'),
    254: ('ravaged_path', 'Ravaged Path'),
    256: ('floaroma_meadow', 'Floaroma Meadow'),
    257: ('floaroma_meadow', 'Floaroma Meadow House'),
    258: ('oreburgh_gate', 'Oreburgh Gate 1F'),
    259: ('oreburgh_gate', 'Oreburgh Gate B1F'),
    260: ('fullmoon_island', 'Fullmoon Island'),
    261: ('fullmoon_island', 'Fullmoon Island Forest'),
    262: ('stark_mountain', 'Stark Mountain Outside'),
    263: ('stark_mountain', 'Stark Mountain Room 1'),
    264: ('stark_mountain', 'Stark Mountain Room 2'),
    265: ('stark_mountain', 'Stark Mountain Room 3'),
    267: ('sendoff_spring', 'Sendoff Spring'),
    268: ('turnback_cave', 'Turnback Cave Entrance'),
    269: ('turnback_cave', 'Turnback Cave Pillar Room'),
    270: ('turnback_cave', 'Turnback Cave Giratina Room'),
    271: ('turnback_cave', 'Turnback Cave Pillar 1 Room 1'),
    272: ('turnback_cave', 'Turnback Cave Pillar 1 Room 2'),
    273: ('turnback_cave', 'Turnback Cave Pillar 1 Room 3'),
    274: ('flower_paradise', 'Flower Paradise'),
    278: ('snowpoint_temple', 'Snowpoint Temple 1F'),
    279: ('snowpoint_temple', 'Snowpoint Temple B1F'),
    280: ('snowpoint_temple', 'Snowpoint Temple B2F'),
    281: ('snowpoint_temple', 'Snowpoint Temple B3F'),
    282: ('snowpoint_temple', 'Snowpoint Temple B4F'),
    283: ('snowpoint_temple', 'Snowpoint Temple B5F'),
    284: ('wayward_cave', 'Wayward Cave 1F'),
    285: ('wayward_cave', 'Wayward Cave B1F'),
    286: ('wayward_cave', 'Ruin Maniac Cave Short'),
    287: ('trophy_garden', 'Trophy Garden'),
    288: ('iron_island', 'Iron Island'),
    289: ('iron_island', 'Iron Island 1F'),
    290: ('iron_island', 'Iron Island B1F Left Room'),
    291: ('iron_island', 'Iron Island B1F Right Room'),
    292: ('iron_island', 'Iron Island B2F Right Room'),
    293: ('iron_island', 'Iron Island B2F Left Room'),
    294: ('iron_island', 'Iron Island B3F'),
    295: ('old_chateau', 'Old Chateau'),
    296: ('old_chateau', 'Old Chateau Dining Area'),
    297: ('old_chateau', 'Old Chateau Side Rooms'),
    298: ('old_chateau', 'Old Chateau Corridor'),
    299: ('old_chateau', 'Old Chateau Back West Room'),
    300: ('old_chateau', 'Old Chateau Back Middle West Room'),
    301: ('old_chateau', 'Old Chateau Back Middle Room'),
    302: ('old_chateau', 'Old Chateau Back Middle East Room'),
    303: ('old_chateau', 'Old Chateau Back East Room'),
    305: ('galactic_hq', 'Galactic Hq 1F'),
    306: ('galactic_hq', 'Galactic Hq 2F'),
    307: ('galactic_hq', 'Galactic Hq 3F'),
    308: ('galactic_hq', 'Galactic Hq 4F'),
    309: ('galactic_hq', 'Galactic Hq B1F'),
    310: ('galactic_hq', 'Galactic Hq B2F'),
    311: ('lake_verity', 'Lake Verity Low Water'),
    312: ('lake_verity', 'Lake Verity'),
    313: ('lake_verity', 'Verity Cavern'),
    314: ('lake_valor', 'Lake Valor Drained'),
    315: ('lake_valor', 'Lake Valor'),
    316: ('lake_valor', 'Valor Cavern'),
    317: ('lake_acuity', 'Lake Acuity Low Water'),
    318: ('lake_acuity', 'Lake Acuity'),
    319: ('lake_acuity', 'Acuity Cavern'),
    320: ('newmoon_island', 'Newmoon Island'),
    321: ('newmoon_island', 'Newmoon Island Forest'),
    322: ('fight_area', 'Battle Park'),
    323: ('fight_area', 'Battle Park Exchange Service Corner'),
    326: ('fight_area', 'Battle Tower'),
    327: ('fight_area', 'Battle Tower Elevator'),
    328: ('fight_area', 'Battle Tower Corridor'),
    329: ('fight_area', 'Battle Tower Corridor Multi'),
    330: ('fight_area', 'Battle Tower Battle Room'),
    331: ('fight_area', 'Battle Tower Multi Battle Room'),
    332: ('fight_area', 'Communication Club Colosseum 2P'),
    333: ('fight_area', 'Communication Club Colosseum 4P'),
    334: ('lake_verity', 'Verity Lakefront'),
    335: ('lake_verity', 'Verity Lakefront Unknown House'),
    336: ('lake_valor', 'Valor Lakefront'),
    337: ('lake_valor', 'Restaurant'),
    338: ('lake_valor', 'Grand Lake Valor Lakefront East House'),
    339: ('lake_valor', 'Grand Lake Valor Lakefront West House'),
    340: ('lake_acuity', 'Acuity Lakefront'),
    341: ('sendoff_spring', 'Spring Path'),
    342: ('route_201', 'Route 201'),
    343: ('route_202', 'Route 202'),
    344: ('route_203', 'Route 203'),
    345: ('route_204', 'Route 204 South'),
    346: ('route_204', 'Route 204 North'),
    347: ('route_205', 'Route 205 South'),
    348: ('route_205', 'Route 205 House'),
    349: ('route_205', 'Route 205 North'),
    350: ('route_206', 'Route 206'),
    351: ('route_206', 'Route 206 Cycling Road South Gate'),
    352: ('route_206', 'Gate Between Eterna City Route 206'),
    353: ('route_207', 'Route 207'),
    354: ('route_208', 'Route 208'),
    355: ('route_208', 'Route 208 House'),
    356: ('route_209', 'Route 209'),
    357: ('lost_tower', 'Route 209 Lost Tower 1F'),
    358: ('lost_tower', 'Route 209 Lost Tower 2F'),
    359: ('lost_tower', 'Route 209 Lost Tower 3F'),
    360: ('lost_tower', 'Route 209 Lost Tower 4F'),
    361: ('lost_tower', 'Route 209 Lost Tower 5F'),
    362: ('route_210', 'Route 210 South'),
    363: ('route_210', 'Route 210 North'),
    364: ('route_210', 'Route 210 Grandma Wilma House'),
    365: ('route_211', 'Route 211 West'),
    366: ('route_211', 'Route 211 East'),
    367: ('route_212', 'Route 212 North'),
    368: ('trophy_garden', 'Pokemon Mansion'),
    369: ('trophy_garden', 'Pokemon Mansion Maids Room'),
    370: ('trophy_garden', 'Pokemon Mansion Office'),
    371: ('route_212', 'Route 212 South'),
    372: ('route_212', 'Route 212 House'),
    373: ('route_213', 'Route 213'),
    374: ('route_213', 'Route 213 Gate To Pastoria City'),
    376: ('route_213', 'Grand Lake Route 213 Lobby'),
    377: ('route_213', 'Grand Lake Route 213 East House'),
    378: ('route_213', 'Grand Lake Route 213 Northwest House'),
    379: ('route_213', 'Grand Lake Route 213 Northeast House'),
    380: ('route_214', 'Route 214'),
    381: ('route_214', 'Route 214 Gate To Veilstone City'),
    382: ('route_215', 'Route 215'),
    383: ('route_216', 'Route 216'),
    384: ('route_216', 'Route 216 House'),
    385: ('route_217', 'Route 217'),
    386: ('route_217', 'Route 217 West House'),
    387: ('route_217', 'Route 217 Northeast House'),
    388: ('route_218', 'Route 218'),
    389: ('route_218', 'Route 218 Gate To Jubilife City'),
    390: ('route_218', 'Route 218 Gate To Canalave City'),
    391: ('route_219', 'Route 219'),
    392: ('route_221', 'Route 221'),
    393: ('pal_park', 'Pal Park Lobby'),
    394: ('route_221', 'Route 221 House'),
    395: ('route_222', 'Route 222'),
    396: ('route_222', 'Route 222 West House'),
    397: ('route_222', 'Route 222 East House'),
    398: ('route_222', 'Route 222 Gate To Sunyshore City'),
    399: ('route_224', 'Route 224'),
    400: ('route_225', 'Route 225'),
    403: ('route_227', 'Route 227'),
    406: ('route_228', 'Route 228'),
    407: ('route_229', 'Route 229'),
    411: ('twinleaf_town', 'Twinleaf Town'),
    412: ('twinleaf_town', 'Twinleaf Town Rival House 1F'),
    413: ('twinleaf_town', 'Twinleaf Town Rival House 2F'),
    414: ('twinleaf_town', 'Twinleaf Town Player House 1F'),
    415: ('twinleaf_town', 'Twinleaf Town Player House 2F'),
    416: ('twinleaf_town', 'Twinleaf Town Northeast House'),
    417: ('twinleaf_town', 'Twinleaf Town Southwest House'),
    418: ('sandgem_town', 'Sandgem Town'),
    419: ('sandgem_town', 'Sandgem Town Mart'),
    420: ('sandgem_town', 'Sandgem Town Pokecenter 1F'),
    421: ('sandgem_town', 'Sandgem Town Pokecenter 2F'),
    422: ('sandgem_town', 'Sandgem Town Pokemon Research Lab'),
    423: ('sandgem_town', 'Sandgem Town Counterpart House 1F'),
    424: ('sandgem_town', 'Sandgem Town Counterpart House 2F'),
    425: ('sandgem_town', 'Sandgem Town House'),
    426: ('floaroma_town', 'Floaroma Town'),
    427: ('floaroma_town', 'Floaroma Town Mart'),
    428: ('floaroma_town', 'Floaroma Town Pokecenter 1F'),
    429: ('floaroma_town', 'Floaroma Town Pokecenter 2F'),
    430: ('floaroma_town', 'Flower Shop'),
    431: ('floaroma_town', 'Floaroma Town Southeast House'),
    432: ('floaroma_town', 'Floaroma Town Middle House'),
    433: ('solaceon_town', 'Solaceon Town'),
    434: ('solaceon_town', 'Solaceon Town Mart'),
    435: ('solaceon_town', 'Solaceon Town Pokecenter 1F'),
    436: ('solaceon_town', 'Solaceon Town Pokecenter 2F'),
    437: ('solaceon_town', 'Pokemon Day Care'),
    438: ('solaceon_town', 'Solaceon Town Northeast House'),
    439: ('solaceon_town', 'Solaceon Town Pokemon News Press'),
    440: ('solaceon_town', 'Solaceon Town North House'),
    441: ('solaceon_town', 'Solaceon Town East House'),
    442: ('celestic_town', 'Celestic Town'),
    443: ('celestic_town', 'Celestic Town Pokecenter 1F'),
    444: ('celestic_town', 'Celestic Town Pokecenter 2F'),
    445: ('celestic_town', 'Celestic Town North House'),
    446: ('celestic_town', 'Celestic Town Northwest House'),
    447: ('celestic_town', 'Celestic Town Northeast House'),
    448: ('celestic_town', 'Celestic Town Southwest House'),
    449: ('celestic_town', 'Celestic Town Cave'),
    450: ('survival_area', 'Survival Area'),
    451: ('survival_area', 'Survival Area Mart'),
    452: ('survival_area', 'Survival Area Pokecenter 1F'),
    453: ('survival_area', 'Survival Area Pokecenter 2F'),
    454: ('survival_area', 'Battleground'),
    455: ('survival_area', 'Survival Area South House'),
    456: ('survival_area', 'Survival Area North House'),
    457: ('resort_area', 'Resort Area'),
    458: ('resort_area', 'Unused Resort Area Mart'),
    459: ('resort_area', 'Resort Area Pokecenter 1F'),
    460: ('resort_area', 'Resort Area Pokecenter 2F'),
    461: ('resort_area', 'Resort Area Ribbon Syndicate 1F'),
    462: ('resort_area', 'Resort Area Ribbon Syndicate 2F'),
    463: ('resort_area', 'Resort Area Ribbon Syndicate Elevator'),
    464: ('resort_area', 'Villa'),
    465: ('resort_area', 'Resort Area House'),
    467: ('route_220', 'Route 220'),
    468: ('route_223', 'Route 223'),
    469: ('route_226', 'Route 226'),
    471: ('route_230', 'Route 230'),
    472: ('flower_paradise', 'Seabreak Path'),
    474: ('jubilife_city', 'Jubilife City Pokecenter B1F'),
    475: ('canalave_city', 'Canalave City Pokecenter B1F'),
    476: ('oreburgh_city', 'Oreburgh City Pokecenter B1F'),
    477: ('eterna_city', 'Eterna City Pokecenter B1F'),
    478: ('hearthome_city', 'Hearthome City Pokecenter B1F'),
    479: ('pastoria_city', 'Pastoria City Pokecenter B1F'),
    480: ('veilstone_city', 'Veilstone City Pokecenter B1F'),
    481: ('sunyshore_city', 'Sunyshore City Pokecenter B1F'),
    482: ('snowpoint_city', 'Snowpoint City Pokecenter B1F'),
    483: ('pokemon_league', 'Pokemon League South Pokecenter B1F'),
    484: ('fight_area', 'Fight Area Pokecenter B1F'),
    485: ('sandgem_town', 'Sandgem Town Pokecenter B1F'),
    486: ('floaroma_town', 'Floaroma Town Pokecenter B1F'),
    487: ('solaceon_town', 'Solaceon Town Pokecenter B1F'),
    488: ('celestic_town', 'Celestic Town Pokecenter B1F'),
    489: ('survival_area', 'Survival Area Pokecenter B1F'),
    490: ('resort_area', 'Resort Area Pokecenter B1F'),
    491: ('canalave_city', 'Canalave City West House'),
    492: ('route_210', 'Cafe'),
    493: ('fight_area', 'Battle Tower Battle Salon'),
    494: ('galactic_hq', 'Galactic Hq Control Room'),
    495: ('pokemon_league', 'Pokemon League North Pokecenter 2F'),
    496: ('pokemon_league', 'Pokemon League North Pokecenter B1F'),
    497: ('galactic_hq', 'Galactic Hq Laboratory'),
    498: ('route_225', 'Route 225 House'),
    499: ('route_226', 'Route 226 House'),
    500: ('route_227', 'Route 227 House'),
    501: ('route_226', 'Route 228 Gate To Route 226'),
    502: ('route_228', 'Route 228 North House'),
    503: ('route_228', 'Route 228 South House'),
    504: ('great_marsh', 'Great Marsh 1'),
    505: ('great_marsh', 'Great Marsh 2'),
    506: ('great_marsh', 'Great Marsh 3'),
    507: ('great_marsh', 'Great Marsh 4'),
    508: ('great_marsh', 'Great Marsh 5'),
    509: ('great_marsh', 'Great Marsh 6'),
    510: ('spear_pillar', 'Hall Of Origin'),
    512: ('wayward_cave', 'Ruin Maniac Cave Long'),
    513: ('wayward_cave', 'Maniac Tunnel'),
    514: ('iron_island', 'Iron Island House'),
    515: ('solaceon_ruins', 'Solaceon Ruins Room 5 Southeast Deadend'),
    516: ('sunyshore_city', 'Vista Lighthouse Elevator'),
    517: ('jubilife_city', 'Jubilife City Southwest House 2F'),
    518: ('turnback_cave', 'Turnback Cave Pillar 1 Room 4'),
    519: ('turnback_cave', 'Turnback Cave Pillar 1 Room 5'),
    520: ('turnback_cave', 'Turnback Cave Pillar 1 Room 6'),
    521: ('turnback_cave', 'Turnback Cave Pillar 2 Room 1'),
    522: ('turnback_cave', 'Turnback Cave Pillar 2 Room 2'),
    523: ('turnback_cave', 'Turnback Cave Pillar 2 Room 3'),
    524: ('turnback_cave', 'Turnback Cave Pillar 2 Room 4'),
    525: ('turnback_cave', 'Turnback Cave Pillar 2 Room 5'),
    526: ('turnback_cave', 'Turnback Cave Pillar 2 Room 6'),
    527: ('turnback_cave', 'Turnback Cave Pillar 3 Room 1'),
    528: ('turnback_cave', 'Turnback Cave Pillar 3 Room 2'),
    529: ('turnback_cave', 'Turnback Cave Pillar 3 Room 3'),
    530: ('turnback_cave', 'Turnback Cave Pillar 3 Room 4'),
    531: ('turnback_cave', 'Turnback Cave Pillar 3 Room 5'),
    532: ('turnback_cave', 'Turnback Cave Pillar 3 Room 6'),
    558: ('hearthome_city', 'Contest Hall Stage No Contest'),
    559: ('fight_area', 'Battle Frontier'),
    560: ('fight_area', 'Battle Frontier Gate To Fight Area'),
    562: ('fight_area', 'Battle Factory'),
    563: ('fight_area', 'Battle Hall'),
    564: ('fight_area', 'Battle Castle'),
    565: ('fight_area', 'Battle Arcade'),
    566: ('veilstone_city', 'Veilstone Store B1F'),
    567: ('jubilife_city', 'Global Terminal 2F'),
    568: ('jubilife_city', 'Global Terminal 3F'),
    569: ('galactic_hq', 'Galactic Hq Hall'),
    571: ('old_chateau', 'Rotoms Room'),
    573: ('distortion_world', 'Distortion World 1F'),
    574: ('distortion_world', 'Distortion World B1F'),
    575: ('distortion_world', 'Distortion World B2F'),
    576: ('distortion_world', 'Distortion World B3F'),
    577: ('distortion_world', 'Distortion World B4F'),
    579: ('distortion_world', 'Distortion World B5F'),
    580: ('distortion_world', 'Distortion World B6F'),
    581: ('distortion_world', 'Distortion World B7F'),
    582: ('distortion_world', 'Distortion World Giratina Room'),
    583: ('turnback_cave', 'Distortion World Turnback Cave Room'),
    584: ('spear_pillar', 'Spear Pillar Dialga'),
    585: ('spear_pillar', 'Spear Pillar Palkia'),
    587: ('iron_island', 'Iron Island Iron Ruins'),
    588: ('iron_island', 'Iron Ruins'),
    589: ('mt_coronet', 'Mt Coronet Iceberg Ruins'),
    590: ('lake_acuity', 'Iceberg Ruins'),
    591: ('route_228', 'Route 228 Rock Peak Ruins'),
    592: ('sendoff_spring', 'Rock Peak Ruins'),
}

def _emit_pt_lua(zone_map: dict, areas_path: str, locs_path: str):
    """Write Platinum area and location Lua tables."""
    area_lines = [
        "-- data/games/gen4_hgsspt/gen4_hgsspt_areas_pt.lua -- AUTO-GENERATED -- DO NOT EDIT BY HAND",
        "-- Source: tools/gen_gen4_area_map.py (pret/pokeplatinum generated/map_headers.txt)",
        "-- Maps zoneId to area_id for Platinum (all confirmed game zones).",
        "--",
        '-- Gift areas: "twinleaf_town", "sandgem_town", "eterna_city", "hearthome_city",',
        '--              "iron_island", "veilstone_city", "route_212", "pal_park"',
        "",
        "local AREAS = {",
    ]
    loc_lines = [
        "-- data/games/gen4_hgsspt/gen4_hgsspt_locations_pt.lua -- AUTO-GENERATED -- DO NOT EDIT BY HAND",
        "-- Source: tools/gen_gen4_area_map.py (pret/pokeplatinum generated/map_headers.txt)",
        "-- Maps zoneId to human-readable location name for HUD display (Platinum).",
        "",
        "local LOCATIONS = {",
    ]

    count = 0
    for zid in sorted(zone_map.keys()):
        area_id, display = zone_map[zid]
        if area_id.startswith("_"):
            continue
        area_lines.append(f'  [{zid}] = "{area_id}",  -- {display}')
        loc_lines.append(f'  [{zid}] = "{display}",')
        count += 1

    for lines, tail in [(area_lines, "return AREAS"), (loc_lines, "return LOCATIONS")]:
        lines.append("}")
        lines.append("")
        lines.append(tail)
        lines.append("")

    with open(areas_path, "w", newline="\n") as f:
        f.write("\n".join(area_lines))
    with open(locs_path, "w", newline="\n") as f:
        f.write("\n".join(loc_lines))

    return count


def main():
    # Build Lua area lookup table
    lines = []
    lines.append("-- data/games/gen4_hgsspt/gen4_hgsspt_areas.lua -- AUTO-GENERATED -- DO NOT EDIT BY HAND")
    lines.append("-- Source: tools/gen_gen4_area_map.py (pret/pokeheartgold maps.h)")
    lines.append("-- Maps zoneId to area_id for HGSS (all 534 game zones).")
    lines.append("--")
    lines.append('-- Gift areas: "dragons_den", "new_bark_town", "route_30", "ruins_of_alph"')
    lines.append("")
    lines.append("local AREAS = {")

    count = 0
    for zid in sorted(ZONE_MAP.keys()):
        area_id, display = ZONE_MAP[zid]
        if area_id.startswith("_"):
            continue
        lines.append(f'  [{zid}] = "{area_id}",  -- {display}')
        count += 1

    lines.append("}")
    lines.append("")
    lines.append("return AREAS")
    lines.append("")

    with open("data/games/gen4_hgsspt/gen4_hgsspt_areas.lua", "w", newline="\n") as f:
        f.write("\n".join(lines))

    print(f"Generated data/games/gen4_hgsspt/gen4_hgsspt_areas.lua ({count} entries)")

    # Build Lua location display name table
    loc_lines = []
    loc_lines.append("-- data/games/gen4_hgsspt/gen4_hgsspt_locations.lua -- AUTO-GENERATED -- DO NOT EDIT BY HAND")
    loc_lines.append("-- Source: tools/gen_gen4_area_map.py (pret/pokeheartgold maps.h)")
    loc_lines.append("-- Maps zoneId to human-readable location name for HUD display.")
    loc_lines.append("")
    loc_lines.append("local LOCATIONS = {")

    for zid in sorted(ZONE_MAP.keys()):
        area_id, display = ZONE_MAP[zid]
        if area_id.startswith("_"):
            continue
        loc_lines.append(f'  [{zid}] = "{display}",')

    loc_lines.append("}")
    loc_lines.append("")
    loc_lines.append("return LOCATIONS")
    loc_lines.append("")

    with open("data/games/gen4_hgsspt/gen4_hgsspt_locations.lua", "w", newline="\n") as f:
        f.write("\n".join(loc_lines))

    print(f"Generated data/games/gen4_hgsspt/gen4_hgsspt_locations.lua ({count} entries)")

    # Summary
    areas = set()
    for zid, (area_id, _) in ZONE_MAP.items():
        if not area_id.startswith("_"):
            areas.add(area_id)
    print(f"Unique area_ids (HGSS): {len(areas)}")

    # ── Platinum output ───────────────────────────────────────────────────────
    pt_count = _emit_pt_lua(
        ZONE_MAP_PT,
        "data/games/gen4_hgsspt/gen4_hgsspt_areas_pt.lua",
        "data/games/gen4_hgsspt/gen4_hgsspt_locations_pt.lua",
    )
    print(f"Generated data/games/gen4_hgsspt/gen4_hgsspt_areas_pt.lua ({pt_count} entries)")
    print(f"Generated data/games/gen4_hgsspt/gen4_hgsspt_locations_pt.lua ({pt_count} entries)")
    pt_areas = set()
    for zid, (area_id, _) in ZONE_MAP_PT.items():
        if not area_id.startswith("_"):
            pt_areas.add(area_id)
    print(f"Unique area_ids (Platinum): {len(pt_areas)}")

    # ── area_map_platinum.json ────────────────────────────────────────────────
    import json, collections
    area_map: dict[str, dict] = {}
    for zid, (area_id, display) in ZONE_MAP_PT.items():
        if area_id.startswith("_"):
            continue
        if area_id not in area_map:
            area_map[area_id] = {"display": display, "maps": []}
        area_map[area_id]["maps"].append([zid, 0])
    with open("data/games/gen4_hgsspt/area_map_platinum.json", "w", newline="\n") as f:
        json.dump(area_map, f, indent=2, ensure_ascii=False)
    print(f"Generated data/games/gen4_hgsspt/area_map_platinum.json ({len(area_map)} areas)")


if __name__ == "__main__":
    main()
