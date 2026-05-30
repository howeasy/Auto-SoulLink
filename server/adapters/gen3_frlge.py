"""
server/adapters/gen3_rsefrlg.py — Game adapter for Gen 3 (RSE + FRLG + AP + Radical Red).

This is the reference adapter that wraps the existing pokemon_data.py module,
maintaining 100% backward compatibility with the current FRLG implementation.
"""

import logging
import os
import json
import re

from .base import GameAdapter
from server.data.items.gen3_vanilla import ITEM_NAMES as _FRLG_ITEM_NAMES
from server.pokemon_data import (
    base_form,
    gender_from_key_species,
    species_name as _species_name,
    species_types as _species_types,
    type_name as _type_name,
    ability_name as _ability_name,
    ability_description as _ability_description,
    to_national as _to_national,
    _parse_pid_otid_key,
    pid_otid_shiny,
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

# Daycare areas — eggs picked up here are bred from deposited mons, not gifts.
_DAYCARE_AREAS = frozenset({
    "route5_pokemon_day_care",
    "four_island_pokemon_day_care",
})

# RR trainer table: trainer index → {name, class, party_size}
_RR_TRAINERS: dict[int, dict] = {}
_rr_trainers_path = os.path.join(_DATA_DIR, "rr_trainers.json")
if os.path.exists(_rr_trainers_path):
    with open(_rr_trainers_path, "r") as _f:
        _raw_tr = json.load(_f)
        _RR_TRAINERS = {int(k): v for k, v in _raw_tr.get("trainers", {}).items()}

# RR priority trainer roster: 1-based runtime trainer ID → {name, class, party, area?}.
# Source: tools/gen_rr_priority_trainers.py merges the RR damage-calc
# normal.js sets (canonical party data) with the community boss spreadsheet
# (area mapping). Keys are stringified ints; values keep the same shape used
# by the dashboard's Upcoming Trainers widget.
_RR_PRIORITY_PARTIES: dict[int, dict] = {}
_RR_PRIORITY_BY_AREA: dict[str, list[int]] = {}
# Main-tab level-cap milestone progression. Used by the dashboard to flag
# Past / Current / Future fight variants relative to the player's highest
# party level — see Gen3Adapter.milestone_cap_for_label() below.
_RR_PRIORITY_MILESTONES_ORDER: list[dict] = []   # [{name, cap}, ...] in story order
_RR_PRIORITY_PRE_CAPS:  dict[str, int] = {}      # "Lt. Surge" → 34
_RR_PRIORITY_POST_CAPS: dict[str, int] = {}      # "Lt. Surge" → 44 (next pre cap)
_rr_priority_path = os.path.join(_DATA_DIR, "rr_priority_trainers.json")
if os.path.exists(_rr_priority_path):
    with open(_rr_priority_path, "r", encoding="utf-8") as _f:
        _raw_pt = json.load(_f)
        _RR_PRIORITY_PARTIES = {
            int(k): v for k, v in (_raw_pt.get("parties") or {}).items()
        }
        _RR_PRIORITY_BY_AREA = {
            k: list(v) for k, v in (_raw_pt.get("trainers_by_area") or {}).items()
        }
        _ms = _raw_pt.get("milestones") or {}
        _RR_PRIORITY_MILESTONES_ORDER = list(_ms.get("order") or [])
        _RR_PRIORITY_PRE_CAPS  = {k: int(v) for k, v in (_ms.get("pre")  or {}).items()}
        _RR_PRIORITY_POST_CAPS = {k: int(v) for k, v in (_ms.get("post") or {}).items()}

# Rival trainer ID set for Radical Red (used by Rival Team Swap feature).
# Built at import time by scanning _RR_TRAINERS for entries whose name is
# "Terry" (RR's default rival name) and whose class is one of the rival
# classes (81/89/90 — Rival Early/Mid/Late).  Spot-check: 27 entries in
# RR4.1 spanning IDs 325-440 and 738-740 (post-game).  Class 98 (also
# labeled "Rival" in _RR_TRAINER_CLASS) is NOT used by Terry in the
# canonical table; filtering on Terry-by-name avoids false positives.
_RR_RIVAL_CLASSES = frozenset({81, 89, 90})
_RR_RIVAL_TRAINER_IDS: frozenset[int] = frozenset(
    tid for tid, tr in _RR_TRAINERS.items()
    if (tr.get("name") or "").strip() == "Terry"
    and tr.get("class") in _RR_RIVAL_CLASSES
)

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
        profile = "Radical Red / CFRU" if is_rr else "vanilla / AP / Emerald"
        log.debug(f"[ADAPTER] Gen3Adapter initialized: profile={profile!r}")

    @property
    def game_id(self) -> str:
        return "gen3_frlge"

    # ── GameRulesAdapter ─────────────────────────────────────────────────

    def is_gift_area(self, area_id: str) -> bool:
        return area_id in _GIFT_AREAS or area_id.startswith("gift_")

    def is_fixed_species_gift(self, area_id: str) -> bool:
        return area_id in _FIXED_SPECIES_GIFTS

    def is_daycare_area(self, area_id: str) -> bool:
        return area_id in _DAYCARE_AREAS

    def evo_family(self, species_id: int) -> int:
        return base_form(species_id, self._is_rr)

    def gender_from_key(self, key: str, species_id: int) -> str:
        return gender_from_key_species(key, species_id, self._is_rr)

    def species_types(self, species_id: int) -> tuple[int, int] | None:
        return _species_types(species_id, self._is_rr)

    def is_shiny(self, key: str) -> bool:
        """Gen III shiny: (tid ^ sid ^ p_upper ^ p_lower) < 8."""
        parsed = _parse_pid_otid_key(key)
        if parsed is None:
            return False
        return pid_otid_shiny(*parsed)

    def species_name(self, species_id: int) -> str:
        return _species_name(species_id, self._is_rr)

    def type_name(self, type_id: int) -> str:
        return _type_name(type_id)

    def rival_trainer_ids(self) -> set[int]:
        """Return the rival trainer IDs for the Rival Team Swap feature.

        Radical Red (CFRU): returns the precomputed Terry-by-name set
        (27 entries spanning Oak's Lab → Champion → post-game).
        Vanilla / AP / Emerald: returns empty — feature is RR-only for MVP.
        """
        if self._is_rr:
            return set(_RR_RIVAL_TRAINER_IDS)
        return set()

    # ── GamePresentationAdapter ──────────────────────────────────────────

    def sprite_html(self, species_id: int, form: int = 0) -> str:
        """Generate sprite <img> tag with funnotbun RR sprites + PokeAPI fallback.

        `form` is accepted for adapter-signature consistency but unused — Gen 3
        only has Unown letters, which share the same sprite.
        """
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

    def sprite_src(self, species_id: int) -> str:
        """Return the best sprite URL for this species.

        For RR runs: funnotbun URL when available (correct CFRU/custom forms).
        Fallback: PokeAPI with CFRU→NatDex conversion.
        """
        if not species_id or species_id < 1:
            return ""
        if self._is_rr:
            rr_file = _RR_SPRITE_FILE.get(species_id)
            if rr_file and species_id not in _TILED_SPRITE_BLOCKLIST:
                return (f"https://raw.githubusercontent.com/funnotbun/funnotbun.github.io"
                        f"/main/data/species/frontspr/{rr_file}.png")
        form_pid = CFRU_FORM_SPRITE_ID.get(species_id)
        if form_pid:
            return (f"https://raw.githubusercontent.com/PokeAPI/sprites/master"
                    f"/sprites/pokemon/{form_pid}.png")
        nat = _to_national(species_id)
        if nat and 1 <= nat <= 1025:
            return (f"https://raw.githubusercontent.com/PokeAPI/sprites/master"
                    f"/sprites/pokemon/{nat}.png")
        return ""

    def ability_name(self, ability_id: int, species_id: int = 0) -> str:
        return _ability_name(ability_id, self._is_rr, species_id)

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

    def trainers_for_area(self, area_id: str) -> list[int]:
        """Return runtime trainer IDs that appear in the given area.

        Source: data/games/gen3_frlge/rr_priority_trainers.json. Only populated
        for RR runs — vanilla FRLG/Emerald variants return []. The returned
        IDs are 1-based runtime IDs (the same shape used by `trainer_info`
        and reported by the Lua client's TRAINER_OPPONENT_ADDR read).
        """
        if not self._is_rr or not area_id:
            return []
        return list(_RR_PRIORITY_BY_AREA.get(area_id, []))

    def trainer_party(self, trainer_id: int) -> list[dict]:
        """Return the curated party for a trainer ID, or [] if unknown.

        Each entry has: species (str), level (int), and optionally nature,
        ability, item, moves (list[str]), evs (dict), ivs (dict). The
        species string is the calc-format name (e.g. "Geodude-Alola",
        "Charizard-Mega-Y") — callers needing a species_id should resolve
        it via the species table.
        """
        if not self._is_rr:
            return []
        entry = _RR_PRIORITY_PARTIES.get(trainer_id)
        if not entry:
            return []
        return list(entry.get("party") or [])

    def milestone_cap_for_fight_label(self, fight_label: str) -> int | None:
        """Resolve a "Pre X" / "Post X" fight_label into a story-progression
        level cap, using the Main-tab milestone list.

        "Pre Lt. Surge"  → 34 (the cap when approaching that fight)
        "Post Lt. Surge" → 44 (the cap AFTER clearing it — next pre milestone)

        Returns None when the label doesn't match a known milestone (or the
        adapter is not in RR mode). Used by the dashboard's Upcoming Trainers
        widget to mark each fight variant as Past / Current / Future against
        the player's highest party mon level.
        """
        if not self._is_rr or not fight_label:
            return None
        s = fight_label.strip()
        # Match "Pre X" / "Post X" — milestone names may have spaces, dots,
        # or punctuation, so anchor on the leading "Pre"/"Post" keyword.
        m = re.match(r"(Pre|Post)[\s-]+(.+)", s, re.I)
        if not m:
            return None
        kind = m.group(1).lower()
        name = m.group(2).strip()
        table = _RR_PRIORITY_PRE_CAPS if kind == "pre" else _RR_PRIORITY_POST_CAPS
        # Lenient lookup: exact match first, then case-insensitive contains.
        if name in table:
            return table[name]
        n_lower = name.lower()
        for k, v in table.items():
            if k.lower() == n_lower or n_lower in k.lower():
                return v
        return None

    def trainer_brief(self, trainer_id: int) -> dict | None:
        """Return {name, class, party, area?, level_cap?} for a priority trainer.

        Convenience helper used by the dashboard's Upcoming Trainers widget:
        combines name/class lookup with party data in one call. Returns None
        when the trainer is not in the priority roster.
        """
        if not self._is_rr:
            return None
        entry = _RR_PRIORITY_PARTIES.get(trainer_id)
        if not entry:
            return None
        out = {
            "name":  entry.get("name", "") or "",
            "class": entry.get("class", "") or "",
            "party": list(entry.get("party") or []),
            "area":  entry.get("area", "") or "",
        }
        lc = entry.get("level_cap")
        if isinstance(lc, int):
            out["level_cap"] = lc
        for k in ("calc_label", "fight_label", "sprite_url"):
            v = entry.get(k)
            if v:
                out[k] = v
        return out

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
        # Dynamic gift area: "gift_<group>_<num>" → "Gift – <ROM map name>"
        if area_id.startswith("gift_"):
            parts = area_id[5:].split("_", 1)  # "10_11" → ["10", "11"]
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                entry = _ROM_MAP_NAMES.get(f"{parts[0]}:{parts[1]}")
                if entry and entry.get("name"):
                    return f"Gift \u2013 {entry['name']}"
                return "Gift"
            # Synthetic "gift_<area_id>" (e.g. gift_vermilion_city) -> name the host area.
            bare = area_id[5:]
            if bare and not bare.startswith("gift_") and not bare.isdigit():
                return f"Gift \u2013 {self.area_display_name(bare)}"
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
        from server.data.moves import move_name as _move_name
        return _move_name(move_id, generation=3, variant=("rr" if self._is_rr else "vanilla"))

    def move_data(self, move_id: int) -> dict | None:
        from server.data.moves import move_data as _move_data, move_name as _move_name
        variant = "rr" if self._is_rr else "vanilla"
        raw = _move_data(move_id, generation=3, variant=variant)
        if raw is None:
            return None
        name = _move_name(move_id, generation=3, variant=variant)
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
