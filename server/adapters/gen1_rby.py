"""
server/adapters/gen1_rby.py — Game adapter for Gen 1 (Red, Blue, Yellow).

Gen 1 has no gender, no abilities, no shinies, and uses a unique mon key format
based on DVs, OT ID, and internal species index.
"""

import json
import logging
import os
import re

from .base import GameAdapter, load_area_names_from_obj_map
from server.pokemon_data import base_form, species_name as _species_name

log = logging.getLogger(__name__)

# Gift/static encounter area_ids
_GIFT_AREAS = frozenset({
    "pallet_town",
    "oaks_lab",
    "celadon_city",
    "saffron_city",
    "silph_co",
    "cinnabar_island",
    "route_4",
    "celadon_game_corner",
    "gift",
})

# Gift areas with a forced, identical species (no player choice).
_FIXED_SPECIES_GIFTS = frozenset({
    "route_4",   # Magikarp from salesman
    "silph_co",  # Lapras on 7F
})

# Gen 1 type IDs → names
_TYPE_IDS = {
    0x00: "Normal", 0x01: "Fighting", 0x02: "Flying", 0x03: "Poison",
    0x04: "Ground", 0x05: "Rock", 0x07: "Bug", 0x08: "Ghost",
    0x14: "Fire", 0x15: "Water", 0x16: "Grass", 0x17: "Electric",
    0x18: "Psychic", 0x19: "Ice", 0x1A: "Dragon",
}

# Gen 1 item names (common items)
_ITEM_NAMES = {
    0x01: "Master Ball", 0x02: "Ultra Ball", 0x03: "Great Ball", 0x04: "Poké Ball",
    0x05: "Town Map", 0x06: "Bicycle", 0x0A: "Moon Stone",
    0x0B: "Antidote", 0x0C: "Burn Heal", 0x0D: "Ice Heal", 0x0E: "Awakening",
    0x0F: "Parlyz Heal", 0x10: "Full Restore", 0x11: "Max Potion",
    0x12: "Hyper Potion", 0x13: "Super Potion", 0x14: "Potion",
    0x1D: "Escape Rope", 0x1E: "Repel", 0x20: "Fire Stone",
    0x21: "Thunder Stone", 0x22: "Water Stone", 0x23: "HP Up",
    0x24: "Protein", 0x25: "Iron", 0x26: "Carbos", 0x27: "Calcium",
    0x28: "Rare Candy", 0x2D: "X Accuracy", 0x2E: "Leaf Stone",
    0x32: "Nugget", 0x34: "Poké Doll", 0x35: "Full Heal",
    0x36: "Revive", 0x37: "Max Revive", 0x38: "Guard Spec.",
    0x39: "Super Repel", 0x3A: "Max Repel", 0x3D: "Fresh Water",
    0x3E: "Soda Pop", 0x3F: "Lemonade", 0x43: "X Attack",
    0x44: "X Defend", 0x45: "X Speed", 0x46: "X Special",
}

# Complete Gen 1 species type table: NatDex → (type1, type2)
# Monotypes have both slots the same. Type IDs use Gen 1 encoding.
_SPECIES_TYPES: dict[int, tuple[int, int]] = {
    1: (0x16, 0x03),    # Bulbasaur: Grass/Poison
    2: (0x16, 0x03),    # Ivysaur: Grass/Poison
    3: (0x16, 0x03),    # Venusaur: Grass/Poison
    4: (0x14, 0x14),    # Charmander: Fire
    5: (0x14, 0x14),    # Charmeleon: Fire
    6: (0x14, 0x02),    # Charizard: Fire/Flying
    7: (0x15, 0x15),    # Squirtle: Water
    8: (0x15, 0x15),    # Wartortle: Water
    9: (0x15, 0x15),    # Blastoise: Water
    10: (0x07, 0x07),   # Caterpie: Bug
    11: (0x07, 0x07),   # Metapod: Bug
    12: (0x07, 0x02),   # Butterfree: Bug/Flying
    13: (0x07, 0x03),   # Weedle: Bug/Poison
    14: (0x07, 0x03),   # Kakuna: Bug/Poison
    15: (0x07, 0x03),   # Beedrill: Bug/Poison
    16: (0x00, 0x02),   # Pidgey: Normal/Flying
    17: (0x00, 0x02),   # Pidgeotto: Normal/Flying
    18: (0x00, 0x02),   # Pidgeot: Normal/Flying
    19: (0x00, 0x00),   # Rattata: Normal
    20: (0x00, 0x00),   # Raticate: Normal
    21: (0x00, 0x02),   # Spearow: Normal/Flying
    22: (0x00, 0x02),   # Fearow: Normal/Flying
    23: (0x03, 0x03),   # Ekans: Poison
    24: (0x03, 0x03),   # Arbok: Poison
    25: (0x17, 0x17),   # Pikachu: Electric
    26: (0x17, 0x17),   # Raichu: Electric
    27: (0x04, 0x04),   # Sandshrew: Ground
    28: (0x04, 0x04),   # Sandslash: Ground
    29: (0x03, 0x03),   # Nidoran♀: Poison
    30: (0x03, 0x03),   # Nidorina: Poison
    31: (0x03, 0x04),   # Nidoqueen: Poison/Ground
    32: (0x03, 0x03),   # Nidoran♂: Poison
    33: (0x03, 0x03),   # Nidorino: Poison
    34: (0x03, 0x04),   # Nidoking: Poison/Ground
    35: (0x00, 0x00),   # Clefairy: Normal
    36: (0x00, 0x00),   # Clefable: Normal
    37: (0x14, 0x14),   # Vulpix: Fire
    38: (0x14, 0x14),   # Ninetales: Fire
    39: (0x00, 0x00),   # Jigglypuff: Normal
    40: (0x00, 0x00),   # Wigglytuff: Normal
    41: (0x03, 0x02),   # Zubat: Poison/Flying
    42: (0x03, 0x02),   # Golbat: Poison/Flying
    43: (0x16, 0x03),   # Oddish: Grass/Poison
    44: (0x16, 0x03),   # Gloom: Grass/Poison
    45: (0x16, 0x03),   # Vileplume: Grass/Poison
    46: (0x07, 0x16),   # Paras: Bug/Grass
    47: (0x07, 0x16),   # Parasect: Bug/Grass
    48: (0x07, 0x03),   # Venonat: Bug/Poison
    49: (0x07, 0x03),   # Venomoth: Bug/Poison
    50: (0x04, 0x04),   # Diglett: Ground
    51: (0x04, 0x04),   # Dugtrio: Ground
    52: (0x00, 0x00),   # Meowth: Normal
    53: (0x00, 0x00),   # Persian: Normal
    54: (0x15, 0x15),   # Psyduck: Water
    55: (0x15, 0x15),   # Golduck: Water
    56: (0x01, 0x01),   # Mankey: Fighting
    57: (0x01, 0x01),   # Primeape: Fighting
    58: (0x14, 0x14),   # Growlithe: Fire
    59: (0x14, 0x14),   # Arcanine: Fire
    60: (0x15, 0x15),   # Poliwag: Water
    61: (0x15, 0x15),   # Poliwhirl: Water
    62: (0x15, 0x01),   # Poliwrath: Water/Fighting
    63: (0x18, 0x18),   # Abra: Psychic
    64: (0x18, 0x18),   # Kadabra: Psychic
    65: (0x18, 0x18),   # Alakazam: Psychic
    66: (0x01, 0x01),   # Machop: Fighting
    67: (0x01, 0x01),   # Machoke: Fighting
    68: (0x01, 0x01),   # Machamp: Fighting
    69: (0x16, 0x03),   # Bellsprout: Grass/Poison
    70: (0x16, 0x03),   # Weepinbell: Grass/Poison
    71: (0x16, 0x03),   # Victreebel: Grass/Poison
    72: (0x15, 0x03),   # Tentacool: Water/Poison
    73: (0x15, 0x03),   # Tentacruel: Water/Poison
    74: (0x05, 0x04),   # Geodude: Rock/Ground
    75: (0x05, 0x04),   # Graveler: Rock/Ground
    76: (0x05, 0x04),   # Golem: Rock/Ground
    77: (0x14, 0x14),   # Ponyta: Fire
    78: (0x14, 0x14),   # Rapidash: Fire
    79: (0x15, 0x18),   # Slowpoke: Water/Psychic
    80: (0x15, 0x18),   # Slowbro: Water/Psychic
    81: (0x17, 0x17),   # Magnemite: Electric
    82: (0x17, 0x17),   # Magneton: Electric
    83: (0x00, 0x02),   # Farfetch'd: Normal/Flying
    84: (0x00, 0x02),   # Doduo: Normal/Flying
    85: (0x00, 0x02),   # Dodrio: Normal/Flying
    86: (0x15, 0x15),   # Seel: Water
    87: (0x15, 0x19),   # Dewgong: Water/Ice
    88: (0x03, 0x03),   # Grimer: Poison
    89: (0x03, 0x03),   # Muk: Poison
    90: (0x15, 0x15),   # Shellder: Water
    91: (0x15, 0x19),   # Cloyster: Water/Ice
    92: (0x08, 0x03),   # Gastly: Ghost/Poison
    93: (0x08, 0x03),   # Haunter: Ghost/Poison
    94: (0x08, 0x03),   # Gengar: Ghost/Poison
    95: (0x05, 0x04),   # Onix: Rock/Ground
    96: (0x18, 0x18),   # Drowzee: Psychic
    97: (0x18, 0x18),   # Hypno: Psychic
    98: (0x15, 0x15),   # Krabby: Water
    99: (0x15, 0x15),   # Kingler: Water
    100: (0x17, 0x17),  # Voltorb: Electric
    101: (0x17, 0x17),  # Electrode: Electric
    102: (0x16, 0x18),  # Exeggcute: Grass/Psychic
    103: (0x16, 0x18),  # Exeggutor: Grass/Psychic
    104: (0x04, 0x04),  # Cubone: Ground
    105: (0x04, 0x04),  # Marowak: Ground
    106: (0x01, 0x01),  # Hitmonlee: Fighting
    107: (0x01, 0x01),  # Hitmonchan: Fighting
    108: (0x00, 0x00),  # Lickitung: Normal
    109: (0x03, 0x03),  # Koffing: Poison
    110: (0x03, 0x03),  # Weezing: Poison
    111: (0x04, 0x05),  # Rhyhorn: Ground/Rock
    112: (0x04, 0x05),  # Rhydon: Ground/Rock
    113: (0x00, 0x00),  # Chansey: Normal
    114: (0x16, 0x16),  # Tangela: Grass
    115: (0x00, 0x00),  # Kangaskhan: Normal
    116: (0x15, 0x15),  # Horsea: Water
    117: (0x15, 0x15),  # Seadra: Water
    118: (0x15, 0x15),  # Goldeen: Water
    119: (0x15, 0x15),  # Seaking: Water
    120: (0x15, 0x15),  # Staryu: Water
    121: (0x15, 0x18),  # Starmie: Water/Psychic
    122: (0x18, 0x18),  # Mr. Mime: Psychic
    123: (0x07, 0x02),  # Scyther: Bug/Flying
    124: (0x19, 0x18),  # Jynx: Ice/Psychic
    125: (0x17, 0x17),  # Electabuzz: Electric
    126: (0x14, 0x14),  # Magmar: Fire
    127: (0x07, 0x07),  # Pinsir: Bug
    128: (0x00, 0x00),  # Tauros: Normal
    129: (0x15, 0x15),  # Magikarp: Water
    130: (0x15, 0x02),  # Gyarados: Water/Flying
    131: (0x15, 0x19),  # Lapras: Water/Ice
    132: (0x00, 0x00),  # Ditto: Normal
    133: (0x00, 0x00),  # Eevee: Normal
    134: (0x15, 0x15),  # Vaporeon: Water
    135: (0x17, 0x17),  # Jolteon: Electric
    136: (0x14, 0x14),  # Flareon: Fire
    137: (0x00, 0x00),  # Porygon: Normal
    138: (0x05, 0x15),  # Omanyte: Rock/Water
    139: (0x05, 0x15),  # Omastar: Rock/Water
    140: (0x05, 0x15),  # Kabuto: Rock/Water
    141: (0x05, 0x15),  # Kabutops: Rock/Water
    142: (0x05, 0x02),  # Aerodactyl: Rock/Flying
    143: (0x00, 0x00),  # Snorlax: Normal
    144: (0x19, 0x02),  # Articuno: Ice/Flying
    145: (0x17, 0x02),  # Zapdos: Electric/Flying
    146: (0x14, 0x02),  # Moltres: Fire/Flying
    147: (0x1A, 0x1A),  # Dratini: Dragon
    148: (0x1A, 0x1A),  # Dragonair: Dragon
    149: (0x1A, 0x02),  # Dragonite: Dragon/Flying
    150: (0x18, 0x18),  # Mewtwo: Psychic
    151: (0x18, 0x18),  # Mew: Psychic
}

# Mon key validation pattern: XXXX:XXXX:XX (4 hex : 4 hex : 1-2 hex)
_KEY_PATTERN = re.compile(r'^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{1,2}$')

_AREA_DISPLAY_NAMES: dict[str, str] = load_area_names_from_obj_map(os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "games", "gen1_rby", "area_map.json"
))

# Load species index conversion table
_INDEX_TO_NATIONAL: dict[int, int] = {}
_species_index_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "games", "gen1_rby", "species_index.json"
)
if os.path.exists(_species_index_path):
    with open(_species_index_path, "r") as _f:
        _raw_index = json.load(_f)
        for k, v in _raw_index.get("index_to_national", {}).items():
            _INDEX_TO_NATIONAL[int(k)] = int(v)
else:
    log.warning("Gen 1 species index not found: %s — to_national_dex() will passthrough", _species_index_path)


class Gen1Adapter(GameAdapter):
    """Adapter for Gen 1: Red, Blue, Yellow.

    Gen 1 has no gender, no abilities, no shinies, and uses internal species
    indices that must be converted to National Dex numbers.
    """

    def __init__(self, **kwargs):
        # Gen 1 has no variants (no is_rr equivalent); kwargs accepted but ignored
        pass

    @property
    def game_id(self) -> str:
        return "gen1_rby"

    # ── GameRulesAdapter ─────────────────────────────────────────────────

    def is_gift_area(self, area_id: str) -> bool:
        return area_id in _GIFT_AREAS or area_id.startswith("gift_")

    def is_fixed_species_gift(self, area_id: str) -> bool:
        return area_id in _FIXED_SPECIES_GIFTS

    def evo_family(self, species_id: int) -> int:
        return base_form(species_id, False)

    def gender_from_key(self, key: str, species_id: int) -> str:
        # Gen 1 has no gender mechanic
        return "genderless"

    def species_types(self, species_id: int) -> tuple[int, int] | None:
        return _SPECIES_TYPES.get(species_id)

    def is_shiny(self, key: str) -> bool:
        # Gen 1 has no shiny mechanic
        return False

    def parse_ot_id(self, key: str) -> str:
        """Extract OT ID from Gen 1 key format (DDDD:TTTT:II) — middle segment."""
        try:
            parts = key.split(":")
            if len(parts) == 3:
                return parts[1]
        except (ValueError, IndexError):
            pass
        return ""

    def is_valid_mon_key(self, key: str) -> bool:
        """Validate Gen 1 key format: XXXX:XXXX:XX."""
        return bool(_KEY_PATTERN.match(key))

    def species_name(self, species_id: int) -> str:
        return _species_name(species_id, False)

    def type_name(self, type_id: int) -> str:
        return _TYPE_IDS.get(type_id, f"Type #{type_id}")

    # ── GamePresentationAdapter ──────────────────────────────────────────

    def sprite_html(self, species_id: int, form: int = 0) -> str:
        # form unused (no alternate forms in Gen 1)
        if not species_id or species_id < 1:
            return ""
        # Use Gen 1 Red/Blue sprites from PokeAPI, cropped 5px on each edge via overflow
        url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/versions/generation-i/red-blue/transparent/{species_id}.png"
        return (
            f'<span style="display:inline-block;width:40px;height:40px;overflow:hidden;vertical-align:middle">'
            f'<img src="{url}" width="52" height="52" loading="lazy" '
            f'style="image-rendering:pixelated;margin:-6px">'
            f'</span>'
        )

    def ability_name(self, ability_id: int, species_id: int = 0) -> str:
        # Gen 1 has no abilities
        return ""

    def ability_description(self, ability_id: int) -> str:
        # Gen 1 has no abilities
        return ""

    def trainer_info(self, trainer_id: int) -> tuple[str, str]:
        # Gen 1 doesn't have a trainer table
        return ("", "")

    def item_name(self, item_id: int) -> str:
        if not item_id:
            return ""
        return _ITEM_NAMES.get(item_id, f"Item #{item_id}")

    def area_display_name(self, area_id: str) -> str:
        if area_id in _AREA_DISPLAY_NAMES:
            return _AREA_DISPLAY_NAMES[area_id]
        return area_id.replace("_", " ").title()

    def to_national_dex(self, species_id: int) -> int:
        """Convert species ID to National Dex number.

        If species_id is already in 1-151 range, returns as-is.
        Otherwise looks up the internal index conversion table.
        """
        if 1 <= species_id <= 151:
            return species_id
        return _INDEX_TO_NATIONAL.get(species_id, species_id)

    def gender_symbol(self, gender: str) -> str:
        # No gender in Gen 1
        return ""

    def form_sprite_id(self, species_id: int) -> int | None:
        # No forms in Gen 1
        return None
