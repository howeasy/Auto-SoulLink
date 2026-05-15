"""
server/adapters/gen5_bw.py — Game adapter for Gen 5 (Black/White/Black2/White2).

Gen 5 uses National Pokédex IDs natively (1-649). Mon keys use PID:OTID format,
identical to Gen 4. PKM struct is 220 bytes (vs Gen 4's 236), same LCRNG
block encryption. No CFRU/RR-style extensions.

Supports all 4 US variants: pokemon_black, pokemon_white, pokemon_black_2,
pokemon_white_2. All route via game_id = "gen5_bw".
"""

import json
import logging
import os

from .base import GameAdapter
from server.pokemon_data import (
    GENDER_RATIO,
    GENDER_SYMBOL,
    NATIONAL_SPECIES_NAMES,
    EVO_FAMILY,
    ability_name as _ability_name,
    ability_description as _ability_description,
    species_types as _species_types,
    type_name as _type_name,
    to_cfru as _to_cfru,
    natdex_base_form as _natdex_base_form,
    _parse_pid_otid_key,
    pid_otid_shiny,
)

log = logging.getLogger(__name__)

# Gift/static encounter area_ids — Pokémon obtained without requiring Pokéballs.
# Only include areas where the mon is received via scripted gift/egg (no wild battle).
# Legendary static encounters (Reshiram, Zekrom, Kyurem) are NOT gift areas —
# they are wild battles and consume a nuzlocke slot.
_GIFT_AREAS_BW1 = frozenset({
    "nuvema_town",    # Starter (Prof. Juniper's lab)
    "striaton_city",  # Elemental monkey gift (restaurant)
    "castelia_city",  # Eevee from Amanita (Bianca's sister)
    "nacrene_city",   # Fossil revives (Nacrene Museum)
    "gift",           # Fallback for unmapped gift areas
})

_GIFT_AREAS_BW2 = frozenset({
    "aspertia_city",  # Starter (Bianca's gift)
    "castelia_city",  # Eevee from Amanita
    "floccesy_ranch", # Riolu egg from Alder's grandson
    "nacrene_city",   # Fossil revives
    "gift",           # Fallback
})

# Area display names loaded from data/games/gen5_bw/area_map_bw.json
_AREA_DISPLAY_NAMES: dict[str, str] = {}
_data_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "games", "gen5_bw",
)
for _map_file in ("area_map_bw.json", "area_map_bw2.json"):
    _area_map_path = os.path.join(_data_dir, _map_file)
    if os.path.exists(_area_map_path):
        with open(_area_map_path, "r") as _f:
            for _entry in json.load(_f):
                _area_id = _entry.get("area_id", "")
                _name = _entry.get("name", "")
                if _area_id and _name and _area_id not in _AREA_DISPLAY_NAMES:
                    _AREA_DISPLAY_NAMES[_area_id] = _name

# Gen 5 (BW/BW2) item names — standard item IDs shared across all 4 variants.
# Ball IDs are identical to Gen 4 (0x0001-0x0010).
_GEN5_ITEM_NAMES: dict[int, str] = {
    # Pokéballs
    1:"Master Ball",   2:"Ultra Ball",    3:"Great Ball",    4:"Poké Ball",
    5:"Safari Ball",   6:"Net Ball",      7:"Dive Ball",     8:"Nest Ball",
    9:"Repeat Ball",   10:"Timer Ball",   11:"Luxury Ball",  12:"Premier Ball",
    13:"Dusk Ball",    14:"Heal Ball",    15:"Quick Ball",   16:"Cherish Ball",
    # Recovery items
    17:"Potion",       18:"Antidote",     19:"Burn Heal",    20:"Ice Heal",
    21:"Awakening",    22:"Parlyz Heal",  23:"Full Restore", 24:"Max Potion",
    25:"Hyper Potion", 26:"Super Potion", 27:"Full Heal",    28:"Revive",
    29:"Max Revive",   30:"Fresh Water",  31:"Soda Pop",     32:"Lemonade",
    33:"MooMoo Milk",  34:"EnergyPowder", 35:"Energy Root",  36:"Heal Powder",
    37:"Revival Herb", 38:"Ether",        39:"Max Ether",    40:"Elixir",
    41:"Max Elixir",   42:"Lava Cookie",  43:"Berry Juice",  44:"Guard Spec.",
    45:"Dire Hit",     46:"X Attack",     47:"X Defend",     48:"X Speed",
    49:"X Accuracy",   50:"X Special",    51:"X Sp. Def",
    # Battle items
    55:"Red Flute",    56:"Blue Flute",   57:"Yellow Flute",
    58:"Black Flute",  59:"White Flute",
    65:"Super Repel",  66:"Max Repel",    67:"Escape Rope",  68:"Repel",
    # Evolution stones
    69:"Sun Stone",    70:"Moon Stone",   71:"Fire Stone",   72:"Thunderstone",
    73:"Water Stone",  74:"Leaf Stone",
    # Valuables
    75:"TinyMushroom", 76:"Big Mushroom", 77:"Pearl",        78:"Big Pearl",
    79:"Stardust",     80:"Star Piece",   81:"Nugget",       82:"Heart Scale",
    # Fossils
    88:"Root Fossil",  89:"Claw Fossil",  90:"Helix Fossil", 91:"Dome Fossil",
    92:"Old Amber",    93:"Armor Fossil", 94:"Skull Fossil",
    95:"Rare Bone",    96:"Shiny Stone",  97:"Dusk Stone",   98:"Dawn Stone",
    99:"Oval Stone",   100:"Odd Keystone",
    # Vitamins
    103:"HP Up",    104:"Protein",   105:"Iron",      106:"Calcium",
    107:"Zinc",     108:"Carbos",    109:"Rare Candy", 110:"PP Up",   111:"PP Max",
    # Held items
    133:"Lucky Egg",   134:"Exp. Share",  135:"Amulet Coin",
    141:"Everstone",   142:"Focus Band",
    149:"Macho Brace", 150:"Power Bracer",151:"Power Belt",  152:"Power Lens",
    153:"Power Band",  154:"Power Anklet",155:"Power Weight",
    203:"Leftovers",   204:"Shell Bell",
    233:"Soothe Bell", 234:"Choice Band",
    236:"Scope Lens",  237:"Metal Coat",
    256:"Bright Powder",257:"White Herb", 258:"Power Herb",
    261:"Choice Scarf",262:"Choice Specs",263:"Focus Sash",  264:"Life Orb",
    265:"Toxic Orb",   266:"Flame Orb",
    268:"Black Sludge", 269:"King's Rock",
    270:"Razor Claw",  271:"Razor Fang",
    275:"Wide Lens",   276:"Muscle Band", 277:"Wise Glasses",
    278:"Expert Belt",
    281:"Light Clay",  282:"Rocky Helmet",
    289:"Silk Scarf",
}


class Gen5Adapter(GameAdapter):
    """Adapter for Gen 5: Black/White/Black2/White2.

    Uses National Pokédex IDs (1-649). Mon keys are PID:OTID format,
    same as Gen 3/4. PKM struct is 220 bytes with same LCRNG encryption.
    Same shiny and gender formulas as Gen 3/4.
    """

    def __init__(self, rom_type=None, **kwargs):
        # rom_type is passed on hello so is_gift_area() can select the correct set.
        self._rom_type = rom_type or ""

    @property
    def game_id(self) -> str:
        return "gen5_bw"

    # ── GameRulesAdapter ─────────────────────────────────────────────────

    def is_gift_area(self, area_id: str) -> bool:
        gift_set = self.gift_areas_for_rom(self._rom_type)
        return area_id in gift_set or area_id.startswith("gift_")

    def is_fixed_species_gift(self, area_id: str) -> bool:
        # Fixed-species gifts in BW1/BW2
        _FIXED = frozenset({
            "dreamyard",        # Munna (fixed)
            "floccesy_ranch",   # Riolu egg (fixed)
        })
        return area_id in _FIXED

    def gift_areas_for_rom(self, rom_type: str) -> frozenset[str]:
        """Return gift areas specific to a BW1 or BW2 ROM."""
        if rom_type in ("pokemon_black_2", "pokemon_white_2"):
            return _GIFT_AREAS_BW2
        return _GIFT_AREAS_BW1

    def evo_family(self, species_id: int) -> int:
        return _natdex_base_form(species_id)

    def gender_from_key(self, key: str, species_id: int) -> str:
        """Derive gender from PID:OTID key and NatDex species ID.

        Gen 5 uses the same formula as Gen 3/4: personality & 0xFF vs threshold.
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
        """Gen V shiny formula: (tid ^ sid ^ p_upper ^ p_lower) < 8.

        Same formula as Gen 3/4.
        """
        parsed = _parse_pid_otid_key(key)
        if parsed is None:
            return False
        return pid_otid_shiny(*parsed)

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
        return ("", "")

    def item_name(self, item_id: int) -> str:
        return _GEN5_ITEM_NAMES.get(item_id, f"Item #{item_id}") if item_id else ""

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
        # Gen 5: 24 boxes; Box 24 = index 23.
        return 23

    def gym_badge_slugs(self, rom_type: str) -> list[tuple[int, str]]:
        # All BW/BW2 variants have exactly 8 Unova badges (single badge byte).
        return [
            (1, "Trio Badge"),
            (2, "Basic Badge"),
            (3, "Insect Badge"),
            (4, "Bolt Badge"),
            (5, "Quake Badge"),
            (6, "Jet Badge"),
            (7, "Freeze Badge"),
            (8, "Legend Badge"),
        ]
