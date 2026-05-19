"""
server/adapters/gen2_crystal.py — Game adapter for Gen 2 (Crystal).

Gen 2 uses sequential NatDex IDs 1-251. Mon keys use DV-based format
DDDD:TTTT:SS (same as Gen 1). Has gender (DV-based), shininess (DV-based),
but no abilities. Steel and Dark types are new vs Gen 1.
"""

import json
import logging
import os
import re

from .base import GameAdapter, load_area_names_from_obj_map
from server.pokemon_data import base_form

log = logging.getLogger(__name__)

# ── Data directory ──────────────────────────────────────────────────────
_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "games", "gen2_crystal",
)

# ── Gift/static encounter area_ids ──────────────────────────────────────
# Route 34 is intentionally NOT here — it's a daycare area (see _DAYCARE_AREAS).
# Wild captures on Route 34 grass go through the normal pokéball + quarantine
# flow; daycare-bred eggs picked up at Route 34 are classified by is_daycare_area.
_GIFT_AREAS = frozenset({
    "new_bark_town",     # Starter (Chikorita/Cyndaquil/Totodile)
    "goldenrod_city",    # Eevee from Bill / Game Corner prizes
    "olivine_city",      # Shuckle from Kirk (temporary trade)
    "dragons_den",       # Dratini from Elder
    "route_35",          # Kenya the Spearow (guard delivery)
    "mt_mortar",         # Tyrogue from Kiyo
    "cianwood_city",     # Shuckle from Kirk
    "celadon_city",      # Eevee (if Kanto gift)
    "gift",              # Fallback for unmapped gift areas
})

# Daycare areas — eggs picked up here are bred from deposited mons, not gifts.
# Crystal has exactly one daycare (Route 34, Day-Care Man). The Odd Egg is also
# given here, but it's mechanically indistinguishable from a daycare-bred egg,
# so it gets treated as a daycare pickup (not a gift) for tracker purposes.
# Mystery Egg from Mr. Pokemon is given on Route 30 — that's a non-daycare egg
# and correctly classified as a gift via the is_egg + !daycare path in state.py.
_DAYCARE_AREAS = frozenset({
    "route_34",
})

# Gift areas with a forced, identical species (no player choice).
# Excludes starters, Odd Egg (random species), and variable Game Corner prizes.
_FIXED_SPECIES_GIFTS = frozenset({
    "olivine_city",  # Shuckle from Kirk
    "dragons_den",   # Dratini from Elder
    "mt_mortar",     # Tyrogue from Kiyo
})

# ── Gen 2 type IDs → names (from pret/pokecrystal type_constants.asm) ──
# Physical: Normal=0..Steel=9 (Bird=6 unused), Special: Fire=20..Dark=27
_TYPE_IDS: dict[int, str] = {
    0: "Normal", 1: "Fighting", 2: "Flying", 3: "Poison",
    4: "Ground", 5: "Rock", 7: "Bug", 8: "Ghost", 9: "Steel",
    20: "Fire", 21: "Water", 22: "Grass", 23: "Electric",
    24: "Psychic", 25: "Ice", 26: "Dragon", 27: "Dark",
}

# Reverse: type name → type ID (for species_types.json lookup)
_TYPE_NAME_TO_ID: dict[str, int] = {v: k for k, v in _TYPE_IDS.items()}

# Mon key validation: XXXX:XXXX:XX (4 hex : 4 hex : 1-2 hex)
_KEY_PATTERN = re.compile(r'^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}:[0-9A-Fa-f]{1,2}$')

# ── Load species types from data file ───────────────────────────────────
_SPECIES_DATA: dict[int, dict] = {}
_species_types_path = os.path.join(_DATA_DIR, "species_types.json")
if os.path.exists(_species_types_path):
    with open(_species_types_path, "r") as _f:
        _raw = json.load(_f)
        for _k, _v in _raw.items():
            _SPECIES_DATA[int(_k)] = _v
else:
    log.warning("Gen 2 species_types.json not found: %s", _species_types_path)

# ── Load gender ratios from data file ───────────────────────────────────
_GENDER_RATIOS: dict[int, int] = {}
_gender_path = os.path.join(_DATA_DIR, "gender_ratios.json")
if os.path.exists(_gender_path):
    with open(_gender_path, "r") as _f:
        _raw = json.load(_f)
        for _k, _v in _raw.items():
            _GENDER_RATIOS[int(_k)] = int(_v)
else:
    log.warning("Gen 2 gender_ratios.json not found: %s", _gender_path)

# ── Load item names from data file ──────────────────────────────────────
_ITEM_NAMES: dict[int, str] = {}
_items_path = os.path.join(_DATA_DIR, "item_names.json")
if os.path.exists(_items_path):
    with open(_items_path, "r") as _f:
        _raw = json.load(_f)
        for _k, _v in _raw.items():
            _ITEM_NAMES[int(_k)] = _v
else:
    log.warning("Gen 2 item_names.json not found: %s", _items_path)

_AREA_DISPLAY_NAMES: dict[str, str] = load_area_names_from_obj_map(
    os.path.join(_DATA_DIR, "area_map.json")
)

# ── Load Gen 2 moves data (Phase 3) ─────────────────────────────────────
_GEN2_MOVES: dict[int, dict] = {}
_moves_path = os.path.join(_DATA_DIR, "moves.json")
if os.path.exists(_moves_path):
    with open(_moves_path, "r") as _f:
        for _entry in json.load(_f).get("moves", []):
            _GEN2_MOVES[int(_entry["id"])] = _entry
else:
    log.warning("Gen 2 moves.json not found: %s", _moves_path)

# ── Load Gen 2 wild encounter tables (Phase 6) ─────────────────────────
_GEN2_ENCOUNTERS: dict[str, dict[str, list[dict]]] = {}
_enc_path = os.path.join(_DATA_DIR, "encounter_tables.json")
if os.path.exists(_enc_path):
    with open(_enc_path, "r") as _f:
        _GEN2_ENCOUNTERS = json.load(_f)
else:
    log.warning("Gen 2 encounter_tables.json not found: %s", _enc_path)

# Move split → integer ID expected by renderer (0=Physical, 1=Special, 2=Status)
_SPLIT_NAME_TO_ID = {"Physical": 0, "Special": 1, "Status": 2}


class Gen2CrystalAdapter(GameAdapter):
    """Adapter for Gen 2: Pokémon Crystal.

    Gen 2 has DV-based gender and shininess, no abilities, and uses
    sequential NatDex IDs 1-251. Steel and Dark are new types.
    """

    def __init__(self, **kwargs):
        pass

    @property
    def game_id(self) -> str:
        return "gen2_crystal"

    # ── GameRulesAdapter ─────────────────────────────────────────────────

    def is_gift_area(self, area_id: str) -> bool:
        return area_id in _GIFT_AREAS or area_id.startswith("gift_")

    def is_fixed_species_gift(self, area_id: str) -> bool:
        return area_id in _FIXED_SPECIES_GIFTS

    def is_daycare_area(self, area_id: str) -> bool:
        return area_id in _DAYCARE_AREAS

    # ── Move data (Phase 3) ───────────────────────────────────────────────

    def move_name(self, move_id: int) -> str:
        m = _GEN2_MOVES.get(move_id)
        return m["name"] if m else ""

    def move_data(self, move_id: int) -> dict | None:
        m = _GEN2_MOVES.get(move_id)
        if not m:
            return None
        type_name = m["type"]
        return {
            "name": m["name"],
            "type_id": _TYPE_NAME_TO_ID.get(type_name, 0),
            "type_name": type_name,
            "power": m["power"],
            "accuracy": m["accuracy"],
            "pp": m["pp"],
            "split": _SPLIT_NAME_TO_ID.get(m["split"], 2),
            "effect_chance": m.get("effect_chance", 0),
        }

    # ── Encounter tables (Phase 6) ───────────────────────────────────────

    def encounter_table(self, area_id: str) -> dict[str, list[dict]] | None:
        """Return wild encounter data keyed by method (Morn/Day/Nite/Surf/...).
        Partial coverage — see data/games/gen2_crystal/encounter_tables.json."""
        return _GEN2_ENCOUNTERS.get(area_id)

    def evo_family(self, species_id: int) -> int:
        return base_form(species_id, False)


    def gender_from_key(self, key: str, species_id: int) -> str:
        """Derive gender from DV-based key and species gender ratio.

        Gen 2 gender: compare Attack DV against species threshold.
        Key format: DDDD:TTTT:SS where DDDD = 2 DV bytes as hex.
        First hex digit of DDDD = Attack DV (0-15).

        From pret/pokecrystal engine/pokemon/search.asm CheckPokemon_Pokemon:
          A mon is female if: atk_dv <= floor(ratio / 16)
          (actually the comparison is: cp (ratio + 1) — so female if atk < ceil(ratio/16))
        Simplified: female if atk_dv * 17 <= ratio (equivalent for all ratio values)
        """
        if not key or not species_id:
            return ""
        ratio = _GENDER_RATIOS.get(species_id, 127)
        if ratio == 255:
            return "genderless"
        if ratio == 254:
            return "female"
        if ratio == 0:
            return "male"
        try:
            dv_hex = key.split(":")[0]  # DDDD
            atk_dv = int(dv_hex[0], 16)  # upper nibble of first DV byte
        except (ValueError, IndexError):
            return ""
        # Gen 2 threshold: female if atk_dv <= floor(ratio / 16)
        # This matches pokecrystal: ratio=127 → threshold=7 (atk 0-7 female)
        # ratio=31 → threshold=1 (atk 0-1 female)
        # ratio=191 → threshold=11 (atk 0-11 female)
        # ratio=63 → threshold=3 (atk 0-3 female)
        threshold = ratio // 16
        if atk_dv <= threshold:
            return "female"
        return "male"

    def species_types(self, species_id: int) -> tuple[int, int] | None:
        """Return (type1_id, type2_id) using Gen 2 type encoding."""
        entry = _SPECIES_DATA.get(species_id)
        if not entry:
            return None
        t1 = _TYPE_NAME_TO_ID.get(entry.get("type1", ""), -1)
        t2 = _TYPE_NAME_TO_ID.get(entry.get("type2", ""), -1)
        if t1 < 0:
            return None
        return (t1, t2 if t2 >= 0 else t1)

    def is_shiny(self, key: str) -> bool:
        """Gen 2 shiny check: based on DVs.

        A Pokémon is shiny if:
        - Defense DV = 10
        - Speed DV = 10
        - Special DV = 10
        - Attack DV is 2, 3, 6, 7, 10, 11, 14, or 15

        Key format: DDDD:TTTT:SS where DDDD = 2 DV bytes.
        Byte 1: upper nibble = Atk DV, lower nibble = Def DV
        Byte 2: upper nibble = Spd DV, lower nibble = Spc DV
        """
        try:
            dv_hex = key.split(":")[0]  # DDDD
            if len(dv_hex) != 4:
                return False
            atk = int(dv_hex[0], 16)
            def_ = int(dv_hex[1], 16)
            spd = int(dv_hex[2], 16)
            spc = int(dv_hex[3], 16)
        except (ValueError, IndexError):
            return False
        return (
            def_ == 10 and spd == 10 and spc == 10
            and atk in (2, 3, 6, 7, 10, 11, 14, 15)
        )

    def parse_ot_id(self, key: str) -> str:
        """Extract OT ID from Gen 2 key format (DDDD:TTTT:SS) — middle segment."""
        try:
            parts = key.split(":")
            if len(parts) == 3:
                return parts[1]
        except (ValueError, IndexError):
            pass
        return ""

    def is_valid_mon_key(self, key: str) -> bool:
        """Validate Gen 2 key format: XXXX:XXXX:XX."""
        return bool(_KEY_PATTERN.match(key))

    def species_name(self, species_id: int) -> str:
        entry = _SPECIES_DATA.get(species_id)
        if entry:
            return entry.get("name", f"#{species_id}")
        return f"#{species_id}"

    def type_name(self, type_id: int) -> str:
        return _TYPE_IDS.get(type_id, f"Type #{type_id}")

    # ── GamePresentationAdapter ──────────────────────────────────────────

    def sprite_html(self, species_id: int) -> str:
        if not species_id or species_id < 1 or species_id > 251:
            return ""
        # Crystal sprites from PokeAPI, with overflow crop for consistent sizing
        url = (
            f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/"
            f"pokemon/versions/generation-ii/crystal/transparent/{species_id}.png"
        )
        return (
            f'<span style="display:inline-block;width:40px;height:40px;'
            f'overflow:hidden;vertical-align:middle">'
            f'<img src="{url}" width="52" height="52" loading="lazy" '
            f'style="image-rendering:pixelated;margin:-6px">'
            f'</span>'
        )

    def ability_name(self, ability_id: int, species_id: int = 0) -> str:
        # Gen 2 has no abilities
        return ""

    def ability_description(self, ability_id: int) -> str:
        # Gen 2 has no abilities
        return ""

    def trainer_info(self, trainer_id: int) -> tuple[str, str]:
        # Not implemented for prototype
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
        # Crystal uses sequential NatDex IDs 1-251
        return species_id

    def gender_symbol(self, gender: str) -> str:
        return {"male": "♂", "female": "♀", "genderless": ""}.get(gender, "")

    def form_sprite_id(self, species_id: int) -> int | None:
        # No alternate forms in Gen 2 (Unown forms are cosmetic, same NatDex)
        return None

    @property
    def memorial_box_index(self) -> int:
        # Gen 2 C/G/S: 14 boxes (0-indexed 0–13), memorial = Box 14 (index 13).
        # Lua-side depositMemorialMon writes to SRAM CartRAM offset 0x79E0;
        # the Gen 2 client reads it back into pc_boxes with box=13 so the
        # server's memorial-contents filter picks it up.
        return 13

    def gym_badge_slugs(self, rom_type: str) -> list[tuple[int, str]]:
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
