"""
server/adapters/gen4_hgsspt.py — Game adapter for Gen 4 (HeartGold/SoulSilver/Platinum).

Gen 4 uses National Pokédex IDs natively (1-493). Mon keys use the same
PID:OTID format as Gen 3. No CFRU/RR support.
"""

import json
import logging
import os

from .base import GameAdapter
from server.pokemon_data import (
    GENDER_RATIO,
    GENDER_SYMBOL,
    NATIONAL_SPECIES_NAMES,
    NATIONAL_TO_CFRU,
    EVO_FAMILY,
    CFRU_TO_NATIONAL,
    ability_name as _ability_name,
    ability_description as _ability_description,
    species_types as _species_types,
    type_name as _type_name,
    to_cfru as _to_cfru,
    to_national as _to_national,
)

log = logging.getLogger(__name__)

# Gift/static encounter area_ids — Pokémon obtained without requiring Pokéballs.
_GIFT_AREAS = frozenset({
    # HGSS (Johto/Kanto)
    "new_bark_town",   # Starter (Chikorita/Cyndaquil/Totodile)
    "route_30",        # Pokémon Egg from Mr. Pokémon (Togepi)
    "ruins_of_alph",   # Unown (gift-like static encounters)
    "dragons_den",     # Dratini from Elder / Extreme Speed Dratini
    "goldenrod_city",  # Eevee from Bill / Game Corner prizes
    "mt_mortar",       # Tyrogue from Kiyo
    "cianwood_city",   # Shuckle from Kirk
    "ilex_forest",     # Spiky-eared Pichu (event)
    "route_35",        # Kenya the Spearow (guard delivery)
    # Platinum (Sinnoh)
    "twinleaf_town",   # Starter (Turtwig/Chimchar/Piplup from Prof. Rowan)
    "sandgem_town",    # Dawn/Lucas Egg + other town events
    "eterna_city",     # Togepi egg (Underground Man) / Cleffa
    "hearthome_city",  # Eevee from Bebe
    "iron_island",     # Riolu egg from Riley
    "veilstone_city",  # Porygon (condominiums)
    "route_212",       # Togepi egg from Cynthia
    "pal_park",        # Pokémon migrated via Pal Park
    # Universal fallback
    "gift",            # Fallback for unmapped gift areas
})

# Gift areas with a forced, identical species (no player choice).
# Excludes starters, Odd Egg / random eggs, and variable Game Corner prizes.
_FIXED_SPECIES_GIFTS = frozenset({
    "route_30",        # Togepi egg from Mr. Pokémon
    "dragons_den",     # Dratini from Elder
    "mt_mortar",       # Tyrogue from Kiyo
    "ilex_forest",     # Spiky-eared Pichu (event)
    "goldenrod_city",  # Eevee from Bill (HGSS)
    "hearthome_city",  # Eevee from Bebe (Platinum)
    "iron_island",     # Riolu egg from Riley
    "veilstone_city",  # Porygon (condominiums)
})

# Area display names: loaded from both HGSS and Platinum area maps.
_AREA_DISPLAY_NAMES: dict[str, str] = {}
_data_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "games", "gen4_hgsspt",
)
for _map_file in ("area_map_hgss.json", "area_map_platinum.json"):
    _area_map_path = os.path.join(_data_dir, _map_file)
    if os.path.exists(_area_map_path):
        with open(_area_map_path, "r") as _f:
            _raw_areas = json.load(_f)
            for _area_id, _entry in _raw_areas.items():
                if isinstance(_entry, dict) and "display" in _entry:
                    _AREA_DISPLAY_NAMES[_area_id] = _entry["display"]

# Gen 4 item names (HGSS/Platinum item IDs — differ from Gen 3)
_GEN4_ITEM_NAMES: dict[int, str] = {
    1:"Master Ball",   2:"Ultra Ball",    3:"Great Ball",    4:"Poké Ball",
    5:"Safari Ball",   6:"Net Ball",      7:"Dive Ball",     8:"Nest Ball",
    9:"Repeat Ball",   10:"Timer Ball",   11:"Luxury Ball",  12:"Premier Ball",
    13:"Dusk Ball",    14:"Heal Ball",    15:"Quick Ball",   16:"Cherish Ball",
    17:"Potion",       18:"Antidote",     19:"Burn Heal",    20:"Ice Heal",
    21:"Awakening",    22:"Parlyz Heal",  23:"Full Restore", 24:"Max Potion",
    25:"Hyper Potion", 26:"Super Potion", 27:"Full Heal",    28:"Revive",
    29:"Max Revive",   30:"Fresh Water",  31:"Soda Pop",     32:"Lemonade",
    33:"MooMoo Milk",  34:"EnergyPowder", 35:"Energy Root",  36:"Heal Powder",
    37:"Revival Herb", 38:"Ether",        39:"Max Ether",    40:"Elixir",
    41:"Max Elixir",   42:"Lava Cookie",  43:"Old Gateau",   44:"Guard Spec.",
    45:"Dire Hit",     46:"X Attack",     47:"X Defend",     48:"X Speed",
    49:"X Accuracy",   50:"X Special",    51:"X Sp. Def",    52:"Poké Doll",
    53:"Fluffy Tail",  54:"Blue Flute",   55:"Yellow Flute", 56:"Red Flute",
    57:"Black Flute",  58:"White Flute",  59:"Shoal Salt",   60:"Shoal Shell",
    61:"Red Shard",    62:"Blue Shard",   63:"Yellow Shard", 64:"Green Shard",
    65:"Super Repel",  66:"Max Repel",    67:"Escape Rope",  68:"Repel",
    69:"Sun Stone",    70:"Moon Stone",   71:"Fire Stone",   72:"Thunderstone",
    73:"Water Stone",  74:"Leaf Stone",   75:"TinyMushroom", 76:"Big Mushroom",
    77:"Pearl",        78:"Big Pearl",    79:"Stardust",     80:"Star Piece",
    81:"Nugget",       82:"Heart Scale",  83:"Honey",
    84:"Growth Mulch", 85:"Damp Mulch",   86:"Stable Mulch", 87:"Gooey Mulch",
    88:"Root Fossil",  89:"Claw Fossil",  90:"Helix Fossil", 91:"Dome Fossil",
    92:"Old Amber",    93:"Armor Fossil", 94:"Skull Fossil", 95:"Rare Bone",
    96:"Shiny Stone",  97:"Dusk Stone",   98:"Dawn Stone",   99:"Oval Stone",
    100:"Odd Keystone",
    103:"HP Up",    104:"Protein",   105:"Iron",      106:"Calcium",
    107:"Zinc",     108:"Carbos",    109:"Rare Candy", 110:"PP Up",    111:"PP Max",
    112:"Old Gateau",
    133:"Lucky Egg",   134:"Exp. Share",
    135:"Amulet Coin", 136:"Cleanse Tag", 137:"Soul Dew",
    138:"DeepSeaTooth",139:"DeepSeaScale",140:"Smoke Ball",
    141:"Everstone",   142:"Focus Band",  143:"Lucky Punch", 144:"Metal Powder",
    145:"Thick Club",  146:"Stick",
    149:"Macho Brace", 150:"Exp. Share",
    203:"Leftovers",   204:"Shell Bell",
    233:"Soothe Bell", 234:"Choice Band",
    236:"Scope Lens",  237:"Metal Coat",
    256:"Bright Powder",257:"White Herb", 258:"Power Herb",
    259:"Absorb Bulb", 260:"Mental Herb", 261:"Choice Scarf",
    262:"Choice Specs", 263:"Focus Sash", 264:"Life Orb",
    265:"Toxic Orb",   266:"Flame Orb",
    268:"Black Sludge", 269:"King's Rock",
    270:"Razor Claw",  271:"Razor Fang",
    275:"Wide Lens",   276:"Muscle Band", 277:"Wise Glasses",
    278:"Expert Belt",
    281:"Light Clay",  282:"Rocky Helmet",
    289:"Silk Scarf",
}


def _natdex_base_form(natdex_id: int) -> int:
    """Return the base-form NatDex ID for an evolution family.

    Converts NatDex→CFRU, looks up EVO_FAMILY, converts back.
    """
    cfru_id = _to_cfru(natdex_id)
    base_cfru = EVO_FAMILY.get(cfru_id, cfru_id)
    return _to_national(base_cfru)


class Gen4Adapter(GameAdapter):
    """Adapter for Gen 4: HeartGold/SoulSilver/Platinum.

    Uses National Pokédex IDs (1-493). Mon keys are PID:OTID format,
    identical to Gen 3.
    """

    def __init__(self, **kwargs):
        pass

    @property
    def game_id(self) -> str:
        return "gen4_hgsspt"

    # ── GameRulesAdapter ─────────────────────────────────────────────────

    def is_gift_area(self, area_id: str) -> bool:
        return area_id in _GIFT_AREAS or area_id.startswith("gift_")

    def is_fixed_species_gift(self, area_id: str) -> bool:
        return area_id in _FIXED_SPECIES_GIFTS

    def evo_family(self, species_id: int) -> int:
        return _natdex_base_form(species_id)

    def gender_from_key(self, key: str, species_id: int) -> str:
        """Derive gender from PID:OTID key and NatDex species ID.

        Gen 4 uses the same formula as Gen 3: personality & 0xFF vs threshold.
        GENDER_RATIO is keyed by CFRU ID, so we convert first.
        """
        if not key or not species_id:
            return ""
        try:
            personality = int(key.split(":")[0], 16)
        except (ValueError, IndexError):
            return ""
        cfru_id = _to_cfru(species_id)
        threshold = GENDER_RATIO.get(cfru_id, 127)
        if threshold == 255:
            return "genderless"
        if threshold == 254:
            return "female"
        if threshold == 0:
            return "male"
        return "female" if (personality & 0xFF) < threshold else "male"

    def species_types(self, species_id: int) -> tuple[int, int] | None:
        cfru_id = _to_cfru(species_id)
        return _species_types(cfru_id, is_rr=False)

    def is_shiny(self, key: str) -> bool:
        """Gen IV shiny: (tid ^ sid ^ p_upper ^ p_lower) < 8."""
        try:
            parts = key.split(":")
            if len(parts) != 2:
                return False
            personality = int(parts[0], 16)
            ot_id = int(parts[1], 16)
        except (ValueError, IndexError):
            return False
        tid = ot_id & 0xFFFF
        sid = (ot_id >> 16) & 0xFFFF
        p_upper = (personality >> 16) & 0xFFFF
        p_lower = personality & 0xFFFF
        return (tid ^ sid ^ p_upper ^ p_lower) < 8

    def parse_ot_id(self, key: str) -> str:
        """Extract OT ID from PID:OTID key format."""
        try:
            parts = key.split(":")
            if len(parts) == 2:
                return parts[1]
        except (ValueError, IndexError):
            pass
        return ""

    def is_valid_mon_key(self, key: str) -> bool:
        """Validate PID:OTID format: 8-hex-digit:8-hex-digit."""
        try:
            parts = key.split(":")
            if len(parts) != 2:
                return False
            int(parts[0], 16)
            int(parts[1], 16)
            return len(parts[0]) <= 8 and len(parts[1]) <= 8
        except (ValueError, IndexError):
            return False

    def species_name(self, species_id: int) -> str:
        return NATIONAL_SPECIES_NAMES.get(species_id, f"#{species_id}")

    def type_name(self, type_id: int) -> str:
        return _type_name(type_id)

    # ── GamePresentationAdapter ──────────────────────────────────────────

    def sprite_html(self, species_id: int) -> str:
        if not species_id or species_id < 1:
            return ""
        url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{species_id}.png"
        return f'<img src="{url}" width="40" height="40" loading="lazy">'

    def ability_name(self, ability_id: int) -> str:
        return _ability_name(ability_id, is_rr=False)

    def ability_description(self, ability_id: int) -> str:
        return _ability_description(ability_id, is_rr=False)

    def trainer_info(self, trainer_id: int) -> tuple[str, str]:
        # Gen 4 doesn't have a trainer table
        return ("", "")

    def item_name(self, item_id: int) -> str:
        return _GEN4_ITEM_NAMES.get(item_id, f"Item #{item_id}") if item_id else ""

    def area_display_name(self, area_id: str) -> str:
        if area_id in _AREA_DISPLAY_NAMES:
            return _AREA_DISPLAY_NAMES[area_id]
        return area_id.replace("_", " ").title()

    def to_national_dex(self, species_id: int) -> int:
        return species_id

    def gender_symbol(self, gender: str) -> str:
        return GENDER_SYMBOL.get(gender, "")

    def form_sprite_id(self, species_id: int) -> int | None:
        return None

    @property
    def memorial_box_index(self) -> int:
        # Gen 4: box 17 (last of 18 boxes)
        return 17

    def gym_badge_slugs(self, rom_type: str) -> list[tuple[int, str]]:
        if (rom_type or "").lower() == "platinum":
            return [
                (25, "Coal Badge"),
                (26, "Forest Badge"),
                (27, "Cobble Badge"),
                (28, "Fen Badge"),
                (29, "Relic Badge"),
                (30, "Mine Badge"),
                (31, "Icicle Badge"),
                (32, "Beacon Badge"),
            ]
        # HeartGold / SoulSilver → Johto + Kanto (16 badges)
        return [
            ( 9, "Zephyr Badge"),
            (10, "Hive Badge"),
            (11, "Plain Badge"),
            (12, "Fog Badge"),
            (13, "Storm Badge"),
            (14, "Mineral Badge"),
            (15, "Glacier Badge"),
            (16, "Rising Badge"),
            # Kanto (bits 8-15 via kanto_badges)
            (1, "Boulder Badge"),
            (2, "Cascade Badge"),
            (3, "Thunder Badge"),
            (4, "Rainbow Badge"),
            (5, "Soul Badge"),
            (6, "Marsh Badge"),
            (7, "Volcano Badge"),
            (8, "Earth Badge"),
        ]
