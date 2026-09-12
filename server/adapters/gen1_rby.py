"""
server/adapters/gen1_rby.py — Game adapter for Gen 1 (Red, Blue, Yellow).

Gen 1 has no gender, no abilities, no shinies, and uses a unique mon key format
based on DVs, OT ID, and internal species index.
"""

import json
import logging
import os
import re

from server.data.items.gen1 import ITEM_NAMES as _ITEM_NAMES
from server.pokemon_data import species_name as _species_name

from .base import GameAdapter, gb_status_token, load_area_names_from_obj_map

log = logging.getLogger(__name__)

# Areas where a Pokémon is HANDED to you by a script rather than caught.
#
# `route_4` used to be in here, and it was the single worst defect in the Gen 1
# sweep: Route 4 is a real wild-grass route, so listing it as a gift area made
# `_handle_area_enter` return early (it could never dead-zone), made
# `_check_link_violation` be skipped entirely (all three clauses off), and stopped
# the Pokéball gate ever arming. Route 4 was an unlimited free-catch zone.
#
# The Magikarp salesman is not on Route 4 at all — pret puts him on
# MT_MOON_POKECENTER, map 68 (`scripts/MtMoonPokecenter.asm:47`, `lb bc, MAGIKARP, 5`),
# which was simply missing from area_map.json. Every grant on an unmapped map fell
# through to the literal area "gift", so the Magikarp and the Celadon Eevee
# (CELADON_MANSION_ROOF_HOUSE, map 132) shared one bucket and PAIRED WITH EACH
# OTHER. Both maps are now in area_map.json with their own ids.
#
# Pallet Town, Celadon City and Cinnabar Island used to be listed too, and they are
# fishing areas (Old, Good and Super Rod in all three titles), so they were the same
# free-catch hole as Route 4 with a rod instead of grass. No grant is delivered on those
# maps at runtime: the starter lives in `oaks_lab`, and every other script grant reaches
# the engine namespaced through `gift_link_area` (the fossil room folds into
# cinnabar_island and pairs under gift_cinnabar_island). A gift area is only for maps
# where a gift is the ONLY way a Pokémon arrives.
_GIFT_AREAS = frozenset({
    "oaks_lab",
    "saffron_city",
    "silph_co",
    "mt_moon_pokecenter",     # Magikarp salesman
    "celadon_mansion_roof",   # Eevee
    "celadon_game_corner",
    "gift",
})

# Gift areas where the script hands over ONE predetermined species, so both
# players necessarily receive the same thing and the clauses have nothing to
# compare. Player-CHOICE gifts (the Oak's Lab starters, the Cinnabar fossils, the
# Fighting Dojo pair) are deliberately absent — there the two players can pick
# differently and the clauses must still apply.
#
# NOTE the coupling: `gift_link_area` only leaves an area id alone when it is
# already a gift area, otherwise it namespaces it to `gift_<area>` — and
# `is_fixed_species_gift` is checked AFTER that rewrite. So every member here
# must also be in _GIFT_AREAS or the exemption silently stops firing.
# `test_gen1_gift_areas.py` pins that.
_FIXED_SPECIES_GIFTS = frozenset({
    "mt_moon_pokecenter",     # Magikarp from the salesman, always level 5
    "silph_co",               # Lapras on 7F
    "celadon_mansion_roof",   # Eevee from the back-door flat; no player choice, so the clauses do not apply
})

# Gen 1 type IDs → names
_TYPE_IDS = {
    0x00: "Normal", 0x01: "Fighting", 0x02: "Flying", 0x03: "Poison",
    0x04: "Ground", 0x05: "Rock", 0x07: "Bug", 0x08: "Ghost",
    0x14: "Fire", 0x15: "Water", 0x16: "Grass", 0x17: "Electric",
    0x18: "Psychic", 0x19: "Ice", 0x1A: "Dragon",
}
_TYPE_NAME_TO_ID = {v: k for k, v in _TYPE_IDS.items()}

# Move split → integer ID expected by renderer (0=Physical, 1=Special, 2=Status)
_SPLIT_NAME_TO_ID = {"Physical": 0, "Special": 1, "Status": 2}

# ── Load Gen 1 moves data (Phase 3) ─────────────────────────────────────
_GEN1_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "games", "gen1_rby",
)
_GEN1_MOVES: dict[int, dict] = {}
_moves_path = os.path.join(_GEN1_DATA_DIR, "moves.json")
if os.path.exists(_moves_path):
    with open(_moves_path) as _f:
        for _entry in json.load(_f).get("moves", []):
            _GEN1_MOVES[int(_entry["id"])] = _entry
else:
    log.warning("Gen 1 moves.json not found: %s", _moves_path)

# ── Load the Gen 1 evolution families ──────────────────────────────────
# NatDex → family representative (the lowest NatDex in the line), generated from
# pret/pokered by tools/gen_gen1_evos.py.
#
# This exists because the shared `pokemon_data.base_form()` is the CFRU/Gen 3+
# table: it maps BOTH Hitmonlee (106) and Hitmonchan (107) to 236 (Tyrogue), a
# species Gen 1 has no concept of — `evos_moves.asm:683,694` give both an empty
# evolution list. The Fighting Dojo lets you take exactly one, so the canonical
# Soul Link split was rejected by the species clause and a live mon was
# force-fainted and buried.
#
# Clamping base_form() to 1..151 would NOT have been a fix: 236:[106,107] is the
# only merge of unrelated species, while 172:[25,26], 173:[35,36] and
# 174:[39,40] are real families remapped to a Gen 2 baby form — clamping splits
# Pikachu/Raichu, Clefairy/Clefable and Jigglypuff/Wigglytuff.
_GEN1_FAMILY: dict[int, int] = {}
_evos_path = os.path.join(_GEN1_DATA_DIR, "evolutions.json")
if os.path.exists(_evos_path):
    with open(_evos_path) as _f:
        for _k, _v in json.load(_f).get("family", {}).items():
            _GEN1_FAMILY[int(_k)] = int(_v)
else:
    log.warning("Gen 1 evolutions.json not found: %s — evo_family will be identity "
                "and the species clause will only reject exact duplicates", _evos_path)

# ── Load Gen 1 wild encounter tables (Phase 6) ─────────────────────────
_GEN1_ENCOUNTERS: dict[str, dict[str, list[dict]]] = {}
_enc_path = os.path.join(_GEN1_DATA_DIR, "encounter_tables.json")
if os.path.exists(_enc_path):
    with open(_enc_path) as _f:
        _GEN1_ENCOUNTERS = json.load(_f)
else:
    log.warning("Gen 1 encounter_tables.json not found: %s", _enc_path)

# Gen 1 item names (common items)

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

# map id -> area id. area_map.json is already read above for display names; this is the
# same file read for the other half of what it carries, so a client that reports its ROM's
# tables by MAP can have them collapsed into the AREAS the rest of SLink keys on.
_MAP_ID_TO_AREA: dict[int, str] = {}
_area_map_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "games", "gen1_rby", "area_map.json"
)
if os.path.exists(_area_map_path):
    with open(_area_map_path) as _f:
        for _k, _v in json.load(_f).items():
            if isinstance(_v, dict) and _v.get("area_id"):
                _MAP_ID_TO_AREA[int(_k)] = _v["area_id"]

# Load species index conversion table
_INDEX_TO_NATIONAL: dict[int, int] = {}
_species_index_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "games", "gen1_rby", "species_index.json"
)
if os.path.exists(_species_index_path):
    with open(_species_index_path) as _f:
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

    # rom_type (as the Lua client sends it) → encounter-table variant. Red and Blue share
    # a decomp but differ in 25 of 39 wild areas; Yellow is a separate decomp and differs
    # from Red in 36 of 39. AP ROMs inherit their base game's tables.
    _ROM_TYPE_TO_ENC_VARIANT = {
        "Red": "red", "red": "red", "red_ap": "red", "Red (AP)": "red",
        "Blue": "blue", "blue": "blue", "blue_ap": "blue", "Blue (AP)": "blue",
        "Yellow": "yellow", "yellow": "yellow",
    }
    _DEFAULT_ENC_VARIANT = "red"

    def __init__(self, **kwargs):
        # Gen 1's only variant axis is the game version, which selects the wild encounter
        # tables. rom_type is passed by the hello path and restored from links.json on
        # reload; when it is absent we fall back to Red rather than serving no tables.
        rom_type = kwargs.get("rom_type") or ""
        self._enc_variant = self._ROM_TYPE_TO_ENC_VARIANT.get(
            rom_type, self._DEFAULT_ENC_VARIANT)
        # The partner cartridge, when the run declares it (the durable runtime always does:
        # both variants are in the paired contract). It decides only whether the starter
        # gift is fixed-species for this pair; None means "unknown", which applies the clauses.
        self._peer_enc_variant = self._ROM_TYPE_TO_ENC_VARIANT.get(kwargs.get("peer_rom_type") or "")
        # None means "nobody has told us what this cartridge holds", which is different
        # from an empty table and must keep the shipped data in use.
        self._rom_encounters: dict[str, dict[str, list[dict]]] | None = None

    @property
    def game_id(self) -> str:
        return "gen1_rby"

    # ── GameRulesAdapter ─────────────────────────────────────────────────

    def supports_abilities(self) -> bool:
        """This generation predates abilities — the party table must not render the column."""
        return False

    # RIVAL1 / RIVAL2 / RIVAL3 in OPP space: pret trainer_constants.asm gives $19/$2A/$2B
    # and OPP_ID_OFFSET = 200, which is what wCurOpponent holds and what the client sends
    # on trainer_battle_start. Mirrored in lua/games/gen1_rby_trainers.lua RIVAL_CLASS_IDS
    # and pinned to pret by tests/unit/test_gen1_trainer_tables.py.
    _RIVAL_IDS = frozenset({225, 242, 243})

    def rival_trainer_ids(self) -> set[int]:
        """Gen 1's rival is identified by CLASS, not by individual trainer number — all
        three rival classes are rival-only, so the class alone is unambiguous."""
        return set(self._RIVAL_IDS)

    def supports_explode_mode(self) -> bool:
        """Gen 1 needs no ROM patch for this. Explosion is move 153, and the engine takes
        the player's choice from wPlayerSelectedMove, so coercing it is a plain RAM write —
        unlike Gen 3, where the same feature required the companion patch."""
        return True

    def party_blob_size(self) -> int:
        """44-byte party struct + 11-byte OT name + 11-byte nickname.

        Gen 1 stores names in arrays parallel to the struct rather than inside it, so a
        faithful copy — the kind a rival-team swap writes back into wEnemyMons and its two
        name arrays — is this composite, not just the struct.
        """
        return 44 + 11 + 11

    def is_gift_area(self, area_id: str) -> bool:
        return area_id in _GIFT_AREAS or area_id.startswith("gift_")

    # Gift areas until 2026-09-12 that are fishing areas in every title. Everything a run
    # persisted under these ids was classified as a gift (that was the defect), so on reload
    # they move to the gift namespace and keep exactly the meaning they had; new records use
    # the bare id for rod captures and gift_<id> for grants, as every other wild area does.
    _RECLASSIFIED_GIFT_AREAS = frozenset({"pallet_town", "celadon_city", "cinnabar_island"})
    # Bump when an area is reclassified again; a document without this exact token is legacy.
    _AREA_POLICY = "gen1-areas-v2-fishing-towns"

    def area_policy(self) -> str | None:
        return self._AREA_POLICY

    def persisted_area(self, area_id: str) -> str:
        if area_id in self._RECLASSIFIED_GIFT_AREAS:
            return f"gift_{area_id}"
        return area_id

    def bind_peer(self, rom_type: str) -> None:
        """Declare the partner cartridge after construction (the restore path learns the
        pair from the runtime contract, after the rule state has been rebuilt)."""
        self._peer_enc_variant = self._ROM_TYPE_TO_ENC_VARIANT.get(rom_type or "")

    def is_fixed_species_gift(self, area_id: str) -> bool:
        # Owner decision 2026-09-11: starters are under the clauses like every other capture,
        # which is what Gen 3 does today ("intro" is not in its fixed-species set). The one
        # exemption is Yellow/Yellow: both scripts hand out Pikachu with no choice, so the
        # starter is a fixed-species gift there by the engine's own definition. Every other
        # pairing has a choice on at least one side, and Pikachu shares no family or type
        # with the three Kanto starters, so the clauses are always satisfiable.
        if area_id == "oaks_lab":
            return self._enc_variant == "yellow" and self._peer_enc_variant == "yellow"
        return area_id in _FIXED_SPECIES_GIFTS

    def evo_family(self, species_id: int) -> int:
        """Gen 1's own evolution families — see _GEN1_FAMILY above.

        Falls back to the species itself, never to `base_form()`: an unknown
        species should be its own family (rejecting only exact duplicates)
        rather than inheriting a modern-generation grouping Gen 1 does not have.
        """
        return _GEN1_FAMILY.get(species_id, species_id)

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
        # `class="mon-sprite"` and `data-species` are NOT decoration -- shared code keys off
        # both, and Gen 1 rendered without them:
        #   * server.py:1659 rewrites the class to `enc-sprite` to shrink encounter icons to
        #     20px; with no class to rewrite that is a silent no-op and the icons render at
        #     40px in a list sized for 20;
        #   * every responsive rule is written against `.mon-sprite` (slink.css:381,
        #     dashboard.css:1159/1161), so party, foe and overlay sprites ignored theme
        #     sizing entirely and stayed locked at 40px;
        #   * the greyscale rules for a fainted mon (`slink.css:450`) and a dead link row
        #     (`:487`) never matched, so KO'd Pokemon never greyed out;
        #   * dashboard.js:70 / overlay-helpers.js:65 select `img.mon-sprite, img.enc-sprite`
        #     for the chroma-key pass and skipped Gen 1 entirely.
        # `onerror` collapses a 404 instead of showing the browser's broken-image glyph.
        return (
            f'<span style="display:inline-block;width:40px;height:40px;overflow:hidden;vertical-align:middle">'
            f'<img class="mon-sprite" data-species="{species_id}" src="{url}" '
            f'width="52" height="52" loading="lazy" '
            f'onerror="this.style.visibility=&#39;hidden&#39;" '
            f'style="image-rendering:pixelated;margin:-6px">'
            f'</span>'
        )

    def sprite_src(self, species_id: int) -> str:
        """Bare sprite URL, used by _enc_table_for_status() for the JSON payload.

        Without this the base default serves modern PokeAPI artwork, so the encounter
        table showed Gen 8-era renders next to the 8-bit Red/Blue sprites `sprite_html`
        returns everywhere else -- on the same stream layout. Gen 2 already overrides this
        for the same reason (gen2_crystal.py).
        """
        if not species_id or species_id < 1:
            return ""
        return ("https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/"
                f"versions/generation-i/red-blue/transparent/{species_id}.png")

    def status_token(self, status_cond: int) -> str:
        """SLP/PSN/BRN/FRZ/PAR for Gen 1's status byte, or "".

        Inherited the base "" until now, which cost the partner column on the dashboard its
        status pill (server.py:3901) -- "is my linked partner asleep?" was unanswerable. The
        player's OWN party was unaffected: html_render.status_icon_html decodes the bitfield
        directly and its layout happens to be right for Gen 1.

        The bit layout is shared with Gen 2 byte for byte, so the decode lives in
        base.gb_status_token with the citations for both.
        """
        return gb_status_token(status_cond)

    def ability_name(self, ability_id: int, species_id: int = 0) -> str:
        # Gen 1 has no abilities
        return ""

    def ability_description(self, ability_id: int) -> str:
        # Gen 1 has no abilities
        return ""

    def trainer_info(self, trainer_id: int) -> tuple[str, str]:
        # Gen 1 doesn't have a trainer table
        return ("", "")

    # ── Move data (Phase 3) ───────────────────────────────────────────────

    def move_name(self, move_id: int) -> str:
        m = _GEN1_MOVES.get(move_id)
        return m["name"] if m else ""

    def move_data(self, move_id: int) -> dict | None:
        m = _GEN1_MOVES.get(move_id)
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
        }

    # ── Encounter tables (Phase 6) ───────────────────────────────────────

    def encounter_table(self, area_id: str) -> dict[str, list[dict]] | None:
        """Return wild encounter data for the given area, or None if unknown.

        The table file is keyed by game version first — Red, Blue and Yellow have
        genuinely different wild tables, and the generator used to blend Red's and Blue's
        into one set that matched neither.
        """
        # A ROM-derived table wins when the client supplied one: it describes the
        # cartridge actually being played, whereas the shipped file describes retail.
        if self._rom_encounters is not None:
            return self._rom_encounters.get(area_id)
        return _GEN1_ENCOUNTERS.get(self._enc_variant, {}).get(area_id)

    def ingest_rom_content(self, payload: dict) -> dict[str, dict[str, list[dict]]] | None:
        """Decode a client's report of its own cartridge into encounter tables.

        Raises RomScanError on anything malformed -- see the base class for why refusing
        beats returning partial data here.
        """
        from server.adapters.gen1_rom_scan import build_encounter_tables, parse_client_content
        content = parse_client_content(payload)
        return build_encounter_tables(
            content, _MAP_ID_TO_AREA, _INDEX_TO_NATIONAL, self.species_name)

    def supports_info_panel(self) -> bool:
        """Red and Blue only, and only with the companion patch — but the ADAPTER cannot
        know which ROM a given player is running. This says the generation is capable; the
        server gates the actual send on what each client reports at hello, because a
        patched and an unpatched cartridge can sit in the same run.
        """
        return True

    def info_panel_width(self) -> int:
        return 20      # the Game Boy tile map is 20 columns

    def rom_content_fingerprint(self, payload: dict) -> str | None:
        from server.adapters.gen1_rom_scan import content_fingerprint, parse_client_content
        content = parse_client_content(payload)
        return content_fingerprint(content["variant"], content["wild"], content["fishing"])

    def use_rom_encounters(self, tables: dict[str, dict[str, list[dict]]] | None) -> None:
        """Adopt ROM-derived tables for this adapter instance, or clear them.

        Per INSTANCE rather than per class: two players in one run may hold ROMs randomized
        with different seeds, so the run cannot have a single answer. get_adapter() builds a
        fresh object every call, which is what makes one adapter per player affordable.
        """
        self._rom_encounters = tables

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

    def stat_stage_labels(self) -> list[str]:
        # ONE Special, not two. RBY has no Sp.Atk/Sp.Def split (that arrives in Gen 2),
        # so the fifth slot is blanked and the fourth is named for what it actually is.
        # Mirroring Special into both Gen 3 slots made a single Psychic drop render as
        # "-1 SATK -1 SDEF": two chips for one stat the cartridge does not have twice.
        return ["ATK", "DEF", "SPD", "SPC", "", "ACC", "EVA"]

    @property
    def mons_per_box(self) -> int:
        # pokered/constants/pokemon_data_constants.asm:60 — DEF MONS_PER_BOX EQU 20.
        return 20

    @property
    def memorial_box_index(self) -> int:
        # Gen 1 R/B/Y: 12 boxes (0-indexed 0–11), memorial = Box 12 (index 11).
        # Lua-side depositMemorialMon writes to SRAM CartRAM offset 0x75EA;
        # the Gen 1 client reads it back into pc_boxes with box=11 so the
        # server's memorial-contents filter picks it up.
        return 11
