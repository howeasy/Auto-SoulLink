"""
server/adapters/gen3_rsefrlg.py — Game adapter for Gen 3 (RSE + FRLG + AP + Radical Red).

This is the reference adapter that wraps the existing pokemon_data.py module,
maintaining 100% backward compatibility with the current FRLG implementation.
"""

import logging
import os
import json

from .base import GameAdapter
from server.pokemon_data import (
    base_form,
    gender_from_key_species,
    species_name as _species_name,
    species_types as _species_types,
    type_name as _type_name,
    ability_name as _ability_name,
    ability_description as _ability_description,
    to_national as _to_national,
    SPECIES_NAMES,
    GENDER_SYMBOL,
    CFRU_FORM_SPRITE_ID,
    TYPE_NAMES,
)

log = logging.getLogger(__name__)

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "games", "gen3_frlge"
)

# Gift/static encounter area_ids — Pokémon obtained here before Pokéballs.
_GIFT_AREAS = frozenset({
    "oaks_lab", "intro", "gift", "cinnabar_lab",
    "celadon_condominiums", "silph_co_7f", "saffron_dojo",
    "route_4_pokecenter",
})

# Gift areas where both players are guaranteed the SAME predetermined species
# (no player choice). These bypass clause checks entirely.
# Excludes starters (player choice), fossils (player choice), Hitmonlee/Hitmonchan (choice).
_FIXED_SPECIES_GIFTS = frozenset({
    "route_4_pokecenter",   # Magikarp from salesman
    "celadon_condominiums", # Eevee from Bill
    "silph_co_7f",          # Lapras
})

# RR trainer table: trainer index → {name, class, party_size}
_RR_TRAINERS: dict[int, dict] = {}
_rr_trainers_path = os.path.join(_DATA_DIR, "rr_trainers.json")
if os.path.exists(_rr_trainers_path):
    with open(_rr_trainers_path, "r") as _f:
        _raw_tr = json.load(_f)
        _RR_TRAINERS = {int(k): v for k, v in _raw_tr.get("trainers", {}).items()}

# RR trainer class ID → display name
_RR_TRAINER_CLASS: dict[int, str] = {
    1: "Pokémon Trainer", 2: "Team Rocket", 3: "Team Rocket Boss",
    4: "Gym Leader", 5: "Pokémon Trainer", 7: "Champion",
    8: "Gym Leader", 9: "Pokémon Trainer", 10: "Champion",
    13: "Pokémon Trainer", 20: "Pokémon Trainer", 22: "Pokémon Trainer",
    25: "Elite Four", 27: "Elite Four", 32: "Professor",
    33: "Pokémon Trainer", 46: "Pokémon Trainer", 48: "Pokémon Trainer",
    49: "Pokémon Trainer", 57: "Youngster", 58: "Bug Catcher",
    59: "Lass", 60: "Sailor", 61: "Camper", 62: "Picnicker",
    63: "Poké Maniac", 64: "Super Nerd", 65: "Hiker",
    66: "Biker", 67: "Burglar", 68: "Fisherman",
    69: "Swimmer ♂", 70: "Cue Ball", 71: "Black Belt",
    72: "Gentleman", 73: "Beauty", 74: "Psychic",
    75: "Rocker", 76: "Juggler", 77: "Tamer",
    78: "Bird Keeper", 79: "Scientist", 80: "Ace Trainer",
    81: "Rival", 82: "Cooltrainer ♀", 83: "Team Rocket Boss",
    84: "Gym Leader", 85: "Team Rocket Grunt", 86: "Channeler",
    87: "Elite Four", 88: "Pokéfan", 89: "Rival",
    90: "Rival", 91: "Cooltrainer ♀",
    92: "Young Couple", 93: "Young Couple", 94: "Young Couple",
    95: "Young Couple", 96: "Young Couple",
    97: "Professor", 98: "Rival",
    99: "Aroma Lady", 100: "Battle Girl", 101: "Parasol Lady",
    102: "Pokémon Ranger", 103: "Twins", 104: "Ruin Maniac",
    105: "Lady", 106: "Painter",
}

# Area display names for the FRLG map
_AREA_DISPLAY_NAMES: dict[str, str] = {}
_area_map_path = os.path.join(_DATA_DIR, "area_map.json")
if os.path.exists(_area_map_path):
    with open(_area_map_path, "r") as _f:
        _raw_areas = json.load(_f)
        for _entry in _raw_areas.values() if isinstance(_raw_areas, dict) else _raw_areas:
            if isinstance(_entry, dict) and "area_id" in _entry:
                _AREA_DISPLAY_NAMES[_entry["area_id"]] = _entry.get("name", _entry["area_id"])

# ROM map names scraped from the live RR ROM via test_map_names.lua + parse_map_names.py.
# Keys are "group:num" strings; values have a "name" field (mapsec-level display name).
# Used to resolve dynamic gift_<group>_<num> area_ids to human-readable names.
_ROM_MAP_NAMES: dict[str, dict] = {}
_rom_map_names_path = os.path.join(_DATA_DIR, "rom_map_names.json")
if os.path.exists(_rom_map_names_path):
    with open(_rom_map_names_path, "r") as _f:
        _ROM_MAP_NAMES = json.load(_f)

# Manual overrides for special characters (apostrophes, accents, abbreviations)
_AREA_DISPLAY_OVERRIDES: dict[str, str] = {
    "mt_moon":           "Mt. Moon",
    "mt_ember":          "Mt. Ember",
    "digletts_cave":     "Diglett's Cave",
    "oaks_lab":          "Oak's Lab",
    "silph_co_7f":       "Silph Co. 7F",
    "silph_co":          "Silph Co.",
    "pokemon_mansion":   "Pokémon Mansion",
    "pokemon_tower":     "Pokémon Tower",
    "cerulean_cave":     "Cerulean Cave",
    "rock_tunnel":       "Rock Tunnel",
    "seafoam_islands":   "Seafoam Islands",
    "victory_road":      "Victory Road",
    "viridian_forest":   "Viridian Forest",
    "safari_zone_center":"Safari Zone",
    "safari_zone_east":  "Safari Zone East",
    "safari_zone_north": "Safari Zone North",
    "safari_zone_west":  "Safari Zone West",
    "power_plant":       "Power Plant",
    "berry_forest":      "Berry Forest",
    "icefall_cave":      "Icefall Cave",
    "dotted_hole":       "Dotted Hole",
    "pattern_bush":      "Pattern Bush",
    "lost_cave":         "Lost Cave",
    "birth_island":      "Birth Island",
    "navel_rock":        "Navel Rock",
    "water_labyrinth":   "Water Labyrinth",
    "altering_cave":     "Altering Cave",
    "ruin_valley":       "Ruin Valley",
    "sevault_canyon":    "Sevault Canyon",
    "saffron_dojo":      "Saffron Dojo",
    "route_4_pokecenter": "Route 4 Pokémon Center",
    "celadon_hotel":     "Celadon Hotel",
    "celadon_condominiums": "Celadon Condominiums",
    "cinnabar_lab":      "Cinnabar Lab",
    "rocket_hideout":    "Rocket Hideout",
    "rocket_warehouse":  "Rocket Warehouse",
    "dunsparce_tunnel":  "Three Isle Path",
    "monean_chamber":    "Monean Chamber",
    "liptoo_chamber":    "Liptoo Chamber",
    "weepth_chamber":    "Weepth Chamber",
    "dilford_chamber":   "Dilford Chamber",
    "scufib_chamber":    "Scufib Chamber",
    "rixy_chamber":      "Rixy Chamber",
    "viapois_chamber":   "Viapois Chamber",
    "tanoby_key":        "Tanoby Key",
    "pokemon_league":    "Pokémon League",
    "ss_anne":           "S.S. Anne",
}

# Radical Red repurposes some vanilla map slots
_AREA_DISPLAY_RR_OVERRIDES: dict[str, str] = {
    "monean_chamber":    "Oak's Lab",
}

# RR item names (loaded if available)
_RR_ITEMS: dict[int, str] = {}
_rr_items_path = os.path.join(_DATA_DIR, "rr_items.json")
if os.path.exists(_rr_items_path):
    with open(_rr_items_path, "r") as _f:
        _raw_items = json.load(_f)
        # Support both nested {"items": {...}} and flat {id: name} formats
        _items_dict = _raw_items.get("items", _raw_items) if isinstance(_raw_items, dict) else {}
        _RR_ITEMS = {int(k): v for k, v in _items_dict.items() if k.isdigit()}

# RR wild encounter tables — area_id → {method → [entries]}
# Format: {"route_1": {"Day": [{"name":"Bidoof","species_id":452,"rate":20,"min_level":2,"max_level":4}]}}
_RR_ENCOUNTERS: dict[str, dict[str, list[dict]]] = {}
_rr_encounters_path = os.path.join(_DATA_DIR, "rr_encounters.json")
if os.path.exists(_rr_encounters_path):
    with open(_rr_encounters_path, "r", encoding="utf-8") as _f:
        _RR_ENCOUNTERS = json.load(_f)

# RR sprite filename mapping (RR internal ID -> funnotbun sprite filename).
_RR_SPRITE_FILE: dict[int, str] = {}
_rr_sprites_path = os.path.join(_DATA_DIR, "rr_sprites.json")
if os.path.exists(_rr_sprites_path):
    with open(_rr_sprites_path, "r") as _f:
        _raw_sprites = json.load(_f)
        _RR_SPRITE_FILE = {int(k): v for k, v in _raw_sprites.items()}

# Vanilla FRLG item names (embedded — no circular import needed).
# Source: pret/pokefirered include/constants/items.h
_FRLG_ITEM_NAMES: dict[int, str] = {
    1:"Master Ball",   2:"Ultra Ball",    3:"Great Ball",    4:"Poké Ball",
    5:"Safari Ball",   6:"Net Ball",      7:"Dive Ball",     8:"Nest Ball",
    9:"Repeat Ball",   10:"Timer Ball",   11:"Luxury Ball",  12:"Premier Ball",
    52:"Park Ball",    53:"Cherish Ball",
    60:"Dusk Ball",    61:"Heal Ball",    62:"Quick Ball",
    622:"Fast Ball",   623:"Level Ball",  624:"Lure Ball",   625:"Heavy Ball",
    626:"Love Ball",   627:"Friend Ball", 628:"Moon Ball",   629:"Sport Ball",
    630:"Beast Ball",  631:"Dream Ball",
    13:"Potion",        14:"Antidote",     15:"Burn Heal",    16:"Ice Heal",
    17:"Awakening",     18:"Parlyz Heal",  19:"Full Restore", 20:"Max Potion",
    21:"Hyper Potion",  22:"Super Potion", 23:"Full Heal",    24:"Revive",
    25:"Max Revive",    26:"Fresh Water",  27:"Soda Pop",     28:"Lemonade",
    29:"MooMoo Milk",   30:"EnergyPowder", 31:"Energy Root",  32:"Heal Powder",
    33:"Revival Herb",  34:"Ether",        35:"Max Ether",    36:"Elixir",
    37:"Max Elixir",    38:"Lava Cookie",  39:"Blue Flute",   40:"Yellow Flute",
    41:"Red Flute",     42:"Black Flute",  43:"White Flute",  44:"Berry Juice",
    45:"Sacred Ash",
    46:"Shoal Salt",    47:"Shoal Shell",  48:"Red Shard",    49:"Blue Shard",
    50:"Yellow Shard",  51:"Green Shard",
    63:"HP Up",    64:"Protein",   65:"Iron",      66:"Carbos",   67:"Calcium",
    68:"Rare Candy", 69:"PP Up",   70:"Zinc",      71:"PP Max",
    73:"Guard Spec.", 74:"Dire Hit",  75:"X Attack",  76:"X Defend",
    77:"X Speed",   78:"X Accuracy", 79:"X Special", 80:"Poké Doll",
    81:"Fluffy Tail", 83:"Super Repel", 84:"Max Repel", 85:"Escape Rope",
    86:"Repel",
    93:"Sun Stone",     94:"Moon Stone",   95:"Fire Stone",
    96:"Thunder Stone", 97:"Water Stone",  98:"Leaf Stone",
    103:"Tiny Mushroom", 104:"Big Mushroom", 106:"Pearl",      107:"Big Pearl",
    108:"Stardust",      109:"Star Piece",   110:"Nugget",     111:"Heart Scale",
    121:"Orange Mail",  122:"Harbor Mail",  123:"Glitter Mail", 124:"Mech Mail",
    125:"Wood Mail",    126:"Wave Mail",    127:"Bead Mail",    128:"Shadow Mail",
    129:"Tropic Mail",  130:"Dream Mail",   131:"Fab Mail",     132:"Retro Mail",
    133:"Cheri Berry",  134:"Chesto Berry", 135:"Pecha Berry",  136:"Rawst Berry",
    137:"Aspear Berry", 138:"Leppa Berry",  139:"Oran Berry",   140:"Persim Berry",
    141:"Lum Berry",    142:"Sitrus Berry", 143:"Figy Berry",   144:"Wiki Berry",
    145:"Mago Berry",   146:"Aguav Berry",  147:"Iapapa Berry", 148:"Razz Berry",
    149:"Bluk Berry",   150:"Nanab Berry",  151:"Wepear Berry", 152:"Pinap Berry",
    153:"Pomeg Berry",  154:"Kelpsy Berry", 155:"Qualot Berry", 156:"Hondew Berry",
    157:"Grepa Berry",  158:"Tamato Berry", 159:"Cornn Berry",  160:"Magost Berry",
    161:"Rabuta Berry", 162:"Nomel Berry",  163:"Spelon Berry", 164:"Pamtre Berry",
    165:"Watmel Berry", 166:"Durin Berry",  167:"Belue Berry",  168:"Liechi Berry",
    169:"Ganlon Berry", 170:"Salac Berry",  171:"Petaya Berry", 172:"Apicot Berry",
    173:"Lansat Berry", 174:"Starf Berry",  175:"Enigma Berry",
    179:"BrightPowder",  180:"White Herb",      181:"Macho Brace",   182:"Exp. Share",
    183:"Quick Claw",    184:"Soothe Bell",     185:"Mental Herb",   186:"Choice Band",
    187:"King's Rock",   188:"Silver Powder",   189:"Amulet Coin",   190:"Cleanse Tag",
    191:"Soul Dew",      192:"Deep Sea Tooth",  193:"Deep Sea Scale",194:"Smoke Ball",
    195:"Everstone",     196:"Focus Band",      197:"Lucky Egg",     198:"Scope Lens",
    199:"Metal Coat",    200:"Leftovers",       201:"Dragon Scale",  202:"Light Ball",
    203:"Soft Sand",     204:"Hard Stone",      205:"Miracle Seed",  206:"BlackGlasses",
    207:"Black Belt",    208:"Magnet",          209:"Mystic Water",  210:"Sharp Beak",
    211:"Poison Barb",   212:"NeverMeltIce",    213:"Spell Tag",     214:"TwistedSpoon",
    215:"Charcoal",      216:"Dragon Fang",     217:"Silk Scarf",    218:"Up-Grade",
    219:"Shell Bell",    220:"Sea Incense",     221:"Lax Incense",   222:"Lucky Punch",
    223:"Metal Powder",  224:"Thick Club",      225:"Stick",
    254:"Red Scarf",   255:"Blue Scarf",   256:"Pink Scarf",
    257:"Green Scarf", 258:"Yellow Scarf",
    289:"TM01", 290:"TM02", 291:"TM03", 292:"TM04", 293:"TM05",
    294:"TM06", 295:"TM07", 296:"TM08", 297:"TM09", 298:"TM10",
    299:"TM11", 300:"TM12", 301:"TM13", 302:"TM14", 303:"TM15",
    304:"TM16", 305:"TM17", 306:"TM18", 307:"TM19", 308:"TM20",
    309:"TM21", 310:"TM22", 311:"TM23", 312:"TM24", 313:"TM25",
    314:"TM26", 315:"TM27", 316:"TM28", 317:"TM29", 318:"TM30",
    319:"TM31", 320:"TM32", 321:"TM33", 322:"TM34", 323:"TM35",
    324:"TM36", 325:"TM37", 326:"TM38", 327:"TM39", 328:"TM40",
    329:"TM41", 330:"TM42", 331:"TM43", 332:"TM44", 333:"TM45",
    334:"TM46", 335:"TM47", 336:"TM48", 337:"TM49", 338:"TM50",
    339:"HM01", 340:"HM02", 341:"HM03", 342:"HM04",
    343:"HM05", 344:"HM06", 345:"HM07", 346:"HM08",
}

# Species whose funnotbun sprites are tiled spritesheets — skip RR sprite.
_TILED_SPRITE_BLOCKLIST = frozenset({385})  # Castform (4-form sheet)


class Gen3Adapter(GameAdapter):
    """Adapter for Gen 3: FireRed/LeafGreen, Emerald, Archipelago, and Radical Red.

    Wraps existing pokemon_data.py functions to implement the GameAdapter
    interface. This ensures full backward compatibility with the existing
    167-test suite.
    """

    def __init__(self, is_rr: bool = False, **kwargs):
        """Initialize with ROM variant flag.

        Args:
            is_rr: True for Radical Red / CFRU ROMs, False for vanilla/AP/Emerald.
        """
        self._is_rr = is_rr

    @property
    def game_id(self) -> str:
        return "gen3_frlge"

    # ── GameRulesAdapter ─────────────────────────────────────────────────

    def is_gift_area(self, area_id: str) -> bool:
        return area_id in _GIFT_AREAS or area_id.startswith("gift_")

    def is_fixed_species_gift(self, area_id: str) -> bool:
        return area_id in _FIXED_SPECIES_GIFTS

    def evo_family(self, species_id: int) -> int:
        return base_form(species_id, self._is_rr)

    def gender_from_key(self, key: str, species_id: int) -> str:
        return gender_from_key_species(key, species_id, self._is_rr)

    def species_types(self, species_id: int) -> tuple[int, int] | None:
        return _species_types(species_id, self._is_rr)

    def is_shiny(self, key: str) -> bool:
        """Gen III shiny: (tid ^ sid ^ p_upper ^ p_lower) < 8."""
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
        """Extract OT ID from Gen 3 key format (personality:otId)."""
        try:
            parts = key.split(":")
            if len(parts) == 2:
                return parts[1]
        except (ValueError, IndexError):
            pass
        return ""

    def is_valid_mon_key(self, key: str) -> bool:
        """Validate Gen 3 key format: 8-hex-digit:8-hex-digit."""
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
        return _species_name(species_id, self._is_rr)

    def type_name(self, type_id: int) -> str:
        return _type_name(type_id)

    # ── GamePresentationAdapter ──────────────────────────────────────────

    def sprite_html(self, species_id: int) -> str:
        """Generate sprite <img> tag with funnotbun RR sprites + PokeAPI fallback."""
        if not species_id or species_id < 1:
            return ""

        # Egg (CFRU SPECIES_EGG = 412) — use Showdown egg sprite
        if species_id == 412:
            return ('<img class="mon-sprite" data-species="412" '
                    'src="https://play.pokemonshowdown.com/sprites/gen5/egg.png" '
                    'onerror="this.style.display=\'none\';" alt="Egg">')

        # Primary: funnotbun RR sprite (covers all 1322 RR species + forms)
        if self._is_rr:
            rr_file = _RR_SPRITE_FILE.get(species_id)
            if rr_file and species_id not in _TILED_SPRITE_BLOCKLIST:
                rr_url = (f"https://raw.githubusercontent.com/funnotbun/funnotbun.github.io"
                          f"/main/data/species/frontspr/{rr_file}.png")
                fallback_url = None
                form_pid = CFRU_FORM_SPRITE_ID.get(species_id)
                if form_pid:
                    fallback_url = (f"https://raw.githubusercontent.com/PokeAPI/sprites/master"
                                    f"/sprites/pokemon/{form_pid}.png")
                else:
                    nat = _to_national(species_id)
                    if nat and 1 <= nat <= 1025:
                        fallback_url = (f"https://raw.githubusercontent.com/PokeAPI/sprites/master"
                                        f"/sprites/pokemon/{nat}.png")
                if fallback_url:
                    return (f'<img class="mon-sprite" crossorigin="anonymous" data-species="{species_id}" src="{rr_url}" '
                            f'onerror="if(this.src!==\'{fallback_url}\'){{this.src=\'{fallback_url}\';}}else{{this.style.display=\'none\';}}" '
                            f'alt="">')
                return (f'<img class="mon-sprite" crossorigin="anonymous" data-species="{species_id}" src="{rr_url}" '
                        f'onerror="this.style.display=\'none\';" alt="">')

        # PokeAPI fallback: convert CFRU → NatDex for the URL
        form_pid = CFRU_FORM_SPRITE_ID.get(species_id)
        if form_pid:
            gen_url = (f"https://raw.githubusercontent.com/PokeAPI/sprites/master"
                       f"/sprites/pokemon/{form_pid}.png")
            return (f'<img class="mon-sprite" data-species="{species_id}" src="{gen_url}" '
                    f'onerror="this.style.display=\'none\';" alt="">')
        nat = _to_national(species_id)
        if not nat or nat < 1 or nat > 1025:
            return ""
        gen_url = (f"https://raw.githubusercontent.com/PokeAPI/sprites/master"
                   f"/sprites/pokemon/{nat}.png")
        if nat <= 386:
            frlg_url = (f"https://raw.githubusercontent.com/PokeAPI/sprites/master"
                        f"/sprites/pokemon/versions/generation-iii/firered-leafgreen/{nat}.png")
            return (f'<img class="mon-sprite" data-species="{nat}" src="{frlg_url}" '
                    f'onerror="if(this.src!==\'{gen_url}\'){{this.src=\'{gen_url}\';}}else{{this.style.display=\'none\';}}" '
                    f'alt="">')
        return (f'<img class="mon-sprite" data-species="{nat}" src="{gen_url}" '
                f'onerror="this.style.display=\'none\';" alt="">')

    def encounter_table(self, area_id: str) -> dict[str, list[dict]] | None:
        """Return wild encounter data for this area (RR only).

        Returns method → entries dict, or None for non-RR runs or areas
        with no encounter data.
        """
        if not self._is_rr:
            return None
        return _RR_ENCOUNTERS.get(area_id) or None

    def ability_name(self, ability_id: int) -> str:
        return _ability_name(ability_id, self._is_rr)

    def ability_description(self, ability_id: int) -> str:
        return _ability_description(ability_id, self._is_rr)

    def trainer_info(self, trainer_id: int) -> tuple[str, str]:
        """Resolve RR trainer name and class from 1-based trainer_id."""
        if not self._is_rr or not _RR_TRAINERS:
            return ("", "")
        tr = _RR_TRAINERS.get(trainer_id - 1)
        if not tr:
            return ("", "")
        cls_id = tr.get("class", 0)
        cls_name = _RR_TRAINER_CLASS.get(cls_id, "")
        # Rival classes (81/89/90) — show class only, no personal name
        if cls_name == "Rival":
            return ("", cls_name)
        return (tr.get("name", "").strip(), cls_name)

    def item_name(self, item_id: int) -> str:
        if not item_id:
            return ""
        if self._is_rr and item_id in _RR_ITEMS:
            return _RR_ITEMS[item_id]
        return _FRLG_ITEM_NAMES.get(item_id, f"Item #{item_id}")

    def area_display_name(self, area_id: str) -> str:
        if not area_id:
            return area_id
        # RR overrides take highest priority
        if self._is_rr and area_id in _AREA_DISPLAY_RR_OVERRIDES:
            return _AREA_DISPLAY_RR_OVERRIDES[area_id]
        # Manual overrides (apostrophes, accents, abbreviations)
        if area_id in _AREA_DISPLAY_OVERRIDES:
            return _AREA_DISPLAY_OVERRIDES[area_id]
        # area_map.json names
        if area_id in _AREA_DISPLAY_NAMES:
            return _AREA_DISPLAY_NAMES[area_id]
        # Dynamic gift area: "gift_<group>_<num>" → "Gift – <ROM map name>"
        if area_id.startswith("gift_"):
            parts = area_id[5:].split("_", 1)  # "10_11" → ["10", "11"]
            if len(parts) == 2:
                entry = _ROM_MAP_NAMES.get(f"{parts[0]}:{parts[1]}")
                if entry and entry.get("name"):
                    return f"Gift \u2013 {entry['name']}"
            return "Gift"
        # Fallback: humanize the area_id
        return area_id.replace("_", " ").title()

    def to_national_dex(self, species_id: int) -> int:
        return _to_national(species_id)

    def gender_symbol(self, gender: str) -> str:
        return GENDER_SYMBOL.get(gender, "")

    def form_sprite_id(self, species_id: int) -> int | None:
        return CFRU_FORM_SPRITE_ID.get(species_id)

    @property
    def memorial_box_index(self) -> int:
        # RR/CFRU: 25 boxes (0-indexed 0–24), memorial = index 24 (UI "Box 25"), fills downward
        # Vanilla/AP FRLG: 14 boxes (0-indexed 0–13), memorial = index 13 (UI "Box 14")
        return 24 if self._is_rr else 13

    # ── Move data ────────────────────────────────────────────────────────

    def move_name(self, move_id: int) -> str:
        from server.move_data import move_name as _move_name
        return _move_name(move_id, self._is_rr)

    def move_data(self, move_id: int) -> dict | None:
        from server.move_data import move_data as _move_data, move_name as _move_name
        raw = _move_data(move_id, self._is_rr)
        if raw is None:
            return None
        name = _move_name(move_id, self._is_rr)
        type_id = raw.get("type", 0)
        return {
            "name": name,
            "type_id": type_id,
            "type_name": self.type_name(type_id),
            "power": raw.get("power", 0),
            "accuracy": raw.get("accuracy", 0),
            "pp": raw.get("pp", 0),
            "split": raw.get("split", 0),
        }

    def gym_badge_slugs(self, rom_type: str) -> list[tuple[int, str]]:
        if (rom_type or "").lower() == "emerald":
            return [
                (17, "Stone Badge"),
                (18, "Knuckle Badge"),
                (19, "Dynamo Badge"),
                (20, "Heat Badge"),
                (21, "Balance Badge"),
                (22, "Feather Badge"),
                (23, "Mind Badge"),
                (24, "Rain Badge"),
            ]
        # FireRed / LeafGreen / Radical Red → Kanto
        return super().gym_badge_slugs(rom_type)
