"""Read and write Universal Pokemon Randomizer ZX ``.rnqs`` settings files.

SLink needs this for two things, and only the first is obvious:

  1. ADMISSION. A run must be able to say "these two ROMs were made with the SAME settings
     and DIFFERENT seeds", and to refuse settings that change things the rules depend on.
     That means decoding a user-supplied .rnqs and checking it against an allowlist, not
     taking the player's word for it.
  2. TESTING. The scanner in ``server/adapters/gen1_rom_scan.py`` exists to read randomized
     ROMs, and a scanner that has only ever seen clean cartridges is untested where it
     matters. UPR has no CLI way to emit a settings file -- only its GUI writes one -- so
     producing a valid .rnqs headlessly is the only way to generate a randomized ROM in an
     automated test.

EVERY BIT POSITION HERE IS TRANSCRIBED FROM UPR v4.6.1's OWN ENCODER, ``Settings.toString()``
in ``src/com/dabomstew/pkrandom/Settings.java``, with the byte index its source comments use.
Nothing is inferred from observed files. ``makeByteSelected(b0, b1, ...)`` puts argument *i*
at bit *i*, least significant first, so a bit index here is an argument position there.

FILE LAYOUT (``Settings.write``/``read``, Settings.java:321-361)::

    [4] VERSION, big-endian int          322 for 4.6.1
    [4] length of the settings string, big-endian int
    [N] the settings string, US-ASCII    -- which is Base64 of the blob below

BLOB LAYOUT (``Settings.toString``)::

    [51] bit-packed options, byte indices 0..50
    [1]  length of romName
    [n]  romName, US-ASCII
    [4]  CRC32 of everything above, big-endian
    [4]  CRC32 of customnames.rncn, big-endian

Two quirks worth knowing before trusting a file:

  * the CRC covers only up to the FIRST checksum. The trailing customnames CRC is written
    and never validated -- ``getFileChecksum`` appears exactly once in Settings.java, in
    the writer -- so a mismatch there is not a reason to reject a file.
  * ``romName`` is stored but never compared against the ROM being randomized, so one
    settings file genuinely does apply to Red, Blue and Yellow alike.

AND THE ONE THAT MATTERS MOST: ``Settings.tweakForRom()`` MUTATES SETTINGS IN PLACE before
randomizing, and for Gen 1 it silently clears a number of them (held items, in-game trade
sub-options, abilities, move tutors, shop randomization) and masks the misc-tweak bitmask
down to what the ROM supports. The CLI computes ``isRemovedCodeTweaks`` and then discards
it, so nothing is printed. This means the settings a player HANDS us are not necessarily
the settings that were APPLIED -- which is why admission has to compare the effective
settings echoed in the log, not just the file.
"""
from __future__ import annotations

import base64
import binascii
import struct

VERSION = 322                     # Version.VERSION for 4.6.1 (Version.java:31)
VERSION_STRING = "4.6.1"
LENGTH_OF_SETTINGS_DATA = 51      # Settings.LENGTH_OF_SETTINGS_DATA (Settings.java:52)


class UprSettingsError(Exception):
    """The file is not a readable .rnqs. Never raised merely for settings we dislike."""


# ── the fields SLink cares about ─────────────────────────────────────────────────────────
# (byte index, bit index) -> name, straight from Settings.toString()'s argument order.
# Only the flags that bear on admission are named; the rest are carried as raw bytes so a
# round-trip is exact.
FLAGS: dict[str, tuple[int, int]] = {
    # 0: general
    "changeImpossibleEvolutions": (0, 0),
    "updateMoves": (0, 1),
    "randomizeTrainerNames": (0, 3),
    "randomizeTrainerClassNames": (0, 4),
    "makeEvolutionsEasier": (0, 5),
    "removeTimeBasedEvolutions": (0, 6),
    # 1: base stats
    "baseStats_RANDOM": (1, 1),
    "baseStats_SHUFFLE": (1, 2),
    "baseStats_UNCHANGED": (1, 3),
    "standardizeEXPCurves": (1, 4),
    "updateBaseStats": (1, 5),
    # 2: types
    "types_RANDOM_FOLLOW_EVOLUTIONS": (2, 0),
    "types_COMPLETELY_RANDOM": (2, 1),
    "types_UNCHANGED": (2, 2),
    "limitPokemon": (2, 5),
    # 3: abilities
    "abilities_UNCHANGED": (3, 0),
    "abilities_RANDOMIZE": (3, 1),
    "allowWonderGuard": (3, 2),
    # 4: starters
    "starters_CUSTOM": (4, 0),
    "starters_COMPLETELY_RANDOM": (4, 1),
    "starters_UNCHANGED": (4, 2),
    "starters_RANDOM_WITH_TWO_EVOLUTIONS": (4, 3),
    # 11: movesets
    "movesets_COMPLETELY_RANDOM": (11, 0),
    "movesets_RANDOM_PREFER_SAME_TYPE": (11, 1),
    "movesets_UNCHANGED": (11, 2),
    "movesets_METRONOME_ONLY": (11, 3),
    # 13: trainers
    "trainers_UNCHANGED": (13, 0),
    "trainers_RANDOM": (13, 1),
    "trainers_DISTRIBUTED": (13, 2),
    "trainers_MAINPLAYTHROUGH": (13, 3),
    "trainers_TYPE_THEMED": (13, 4),
    "trainers_TYPE_THEMED_ELITE4_GYMS": (13, 5),
    # 15/16: wild
    "wildRestriction_CATCH_EM_ALL": (15, 0),
    "wild_AREA_MAPPING": (15, 1),
    "wildRestriction_NONE": (15, 2),
    "wildRestriction_TYPE_THEME_AREAS": (15, 3),
    "wild_GLOBAL_MAPPING": (15, 4),
    "wild_RANDOM": (15, 5),
    "wild_UNCHANGED": (15, 6),
    "useTimeBasedEncounters": (15, 7),
    "useMinimumCatchRate": (16, 0),
    "blockWildLegendaries": (16, 1),
    "wildRestriction_SIMILAR_STRENGTH": (16, 2),
    "randomizeWildPokemonHeldItems": (16, 3),
    # 17: statics
    "static_UNCHANGED": (17, 0),
    "static_RANDOM_MATCHING": (17, 1),
    "static_COMPLETELY_RANDOM": (17, 2),
    "static_SIMILAR_STRENGTH": (17, 3),
    # 18: TMs
    "tmCompat_COMPLETELY_RANDOM": (18, 0),
    "tmCompat_RANDOM_PREFER_TYPE": (18, 1),
    "tmCompat_UNCHANGED": (18, 2),
    "tms_RANDOM": (18, 3),
    "tms_UNCHANGED": (18, 4),
    "tmLevelUpMoveSanity": (18, 5),
    "keepFieldMoveTMs": (18, 6),
    "tmCompat_FULL": (18, 7),
    # 21: move tutors
    "tutorCompat_UNCHANGED": (21, 2),
    "tutors_UNCHANGED": (21, 4),
    # 23: in-game trades
    "trades_RANDOMIZE_GIVEN_AND_REQUESTED": (23, 0),
    "trades_RANDOMIZE_GIVEN": (23, 1),
    "trades_UNCHANGED": (23, 6),
    # 24: field items
    "fieldItems_RANDOM": (24, 0),
    "fieldItems_SHUFFLE": (24, 1),
    "fieldItems_UNCHANGED": (24, 2),
    "banBadRandomFieldItems": (24, 3),
    "fieldItems_RANDOM_EVEN": (24, 4),
    # 25: move data randomizers -- every one of these rewrites move tables
    "randomizeMovePowers": (25, 0),
    "randomizeMoveAccuracies": (25, 1),
    "randomizeMovePPs": (25, 2),
    "randomizeMoveTypes": (25, 3),
    "randomizeMoveCategory": (25, 4),
    # 26: evolutions
    "evolutions_UNCHANGED": (26, 0),
    "evolutions_RANDOM": (26, 1),
    "evolutions_RANDOM_EVERY_LEVEL": (26, 7),
    # 27: trainer misc
    "trainersUsePokemonOfSimilarStrength": (27, 0),
    "rivalCarriesStarterThroughout": (27, 1),
    "trainersMatchTypingDistribution": (27, 2),
    "trainersBlockLegendaries": (27, 3),
    "trainersBlockEarlyWonderGuard": (27, 4),
    # 37: shop items
    "shopItems_UNCHANGED": (37, 2),
    # 39: exp curve / broken moves
    "expCurve_LEGENDARIES": (39, 0),
    "blockBrokenTMMoves": (39, 4),
    # 42: totem / ally
    "totem_UNCHANGED": (42, 0),
    "ally_UNCHANGED": (42, 3),
    # 49: pickup items
    "pickupItems_UNCHANGED": (49, 1),
}

# MiscTweak bit values (MiscTweak.java). The whole set is a big-endian int at bytes 32-35.
MISC_TWEAKS = {
    "BAN_LUCKY_EGG": 1 << 0,
    "LOWER_CASE_POKEMON_NAMES": 1 << 1,
    "NATIONAL_DEX_AT_START": 1 << 2,
    "FASTEST_TEXT": 1 << 3,
    "RUNNING_SHOES_INDOORS": 1 << 4,
    "RANDOMIZE_PC_POTION": 1 << 5,
    "ALLOW_PIKACHU_EVOLUTION": 1 << 6,
    "FORCE_CHALLENGE_MODE": 1 << 7,
    "BW_EXP_PATCH": 1 << 8,
    "NERF_X_ACCURACY": 1 << 9,
    "FIX_CRIT_RATE": 1 << 10,
    "UPDATE_TYPE_EFFECTIVENESS": 1 << 11,
}

# A settings blob that changes nothing, byte by byte. Values are UPR's own field defaults
# (Settings.java field declarations), NOT zeros: an "UNCHANGED" enum is an explicit SET bit,
# so an all-zero blob does not mean "do nothing" -- it means "no mode selected at all".
_LEVEL_MOD_BIAS = 50            # written as (modifier + 50); 0 means unmodified


def _default_bytes() -> bytearray:
    b = bytearray(LENGTH_OF_SETTINGS_DATA)
    for name in (
        "baseStats_UNCHANGED", "types_UNCHANGED", "abilities_UNCHANGED", "allowWonderGuard",
        "starters_UNCHANGED", "movesets_UNCHANGED", "trainers_UNCHANGED", "wild_UNCHANGED",
        "wildRestriction_NONE", "blockWildLegendaries", "static_UNCHANGED",
        "tmCompat_UNCHANGED", "tms_UNCHANGED", "tutorCompat_UNCHANGED", "tutors_UNCHANGED",
        "trades_UNCHANGED", "fieldItems_UNCHANGED", "evolutions_UNCHANGED",
        "trainersBlockLegendaries", "trainersBlockEarlyWonderGuard", "shopItems_UNCHANGED",
        "expCurve_LEGENDARIES", "totem_UNCHANGED", "ally_UNCHANGED", "pickupItems_UNCHANGED",
    ):
        idx, bit = FLAGS[name]
        b[idx] |= 1 << bit
    b[5], b[6] = 0xFF, 0xFF        # customStarters[0] - 1 == -1, little-endian
    b[7], b[8] = 0xFF, 0xFF
    b[9], b[10] = 0xFF, 0xFF
    b[14] = 30                     # trainersForceFullyEvolvedLevel default, not forced
    b[36] = _LEVEL_MOD_BIAS        # trainersLevelModifier 0
    b[38] = _LEVEL_MOD_BIAS        # wildLevelModifier 0
    b[41] = 0x08                   # auraMod UNCHANGED
    b[43] = _LEVEL_MOD_BIAS        # totemLevelModifier 0
    b[46] = 0                      # selectedEXPCurve MEDIUM_FAST (ExpCurve.toByte)
    b[47] = _LEVEL_MOD_BIAS        # staticLevelModifier 0
    b[50] = 0                      # eliteFourUnique 0 | (minimumCatchRateLevel - 1) << 3
    return b


def build(flags: dict[str, bool] | None = None,
          misc_tweaks: int = 0,
          rom_name: str = "Pokemon Red (U) [!]",
          *, bytes_override: dict[int, int] | None = None) -> bytes:
    """A complete .rnqs file. ``flags`` is applied on top of UPR's own defaults.

    Setting a mode means clearing its siblings yourself -- e.g. enabling ``wild_RANDOM``
    without clearing ``wild_UNCHANGED`` leaves two mode bits set, and UPR's ``fromString``
    reads them in a fixed order so the result would be whichever it happens to test first.
    ``build_spec`` does that bookkeeping; prefer it. ``bytes_override`` writes whole bytes
    last -- the level modifiers and the like, which are numbers rather than bits.
    """
    data = _default_bytes()
    for name, on in (flags or {}).items():
        if name not in FLAGS:
            raise UprSettingsError(f"unknown settings flag {name!r}")
        idx, bit = FLAGS[name]
        if on:
            data[idx] |= 1 << bit
        else:
            data[idx] &= ~(1 << bit) & 0xFF
    data[32:36] = struct.pack(">i", misc_tweaks)
    for idx, val in (bytes_override or {}).items():
        data[idx] = val & 0xFF
    return _encode(data, rom_name)


def _encode(data: bytearray, rom_name: str) -> bytes:
    blob = bytearray(data)
    name_bytes = rom_name.encode("ascii")
    blob.append(len(name_bytes))
    blob += name_bytes
    blob += struct.pack(">I", binascii.crc32(bytes(blob)) & 0xFFFFFFFF)
    blob += struct.pack(">I", 0)      # customnames CRC -- written, never validated

    settings_string = base64.b64encode(bytes(blob))
    return struct.pack(">i", VERSION) + struct.pack(">i", len(settings_string)) + settings_string


# ── the options this project exposes ─────────────────────────────────────────────────────
# Everything a run may set, and how each value lands in the blob. This table is the whole
# definition of "compatible with SLink": the form renders it, build_spec writes from it,
# spec_from_parsed reads back through it, and the allowlist envelope is enumerated from it,
# so nothing can be offered that the pipeline would then refuse, or refused that it offers.
#
# What is NOT here, and why: types, evolutions, level-up movesets, base stats and move data
# (the species and type clauses must mean the same on both cartridges; _check_content
# verifies base stats and the evolution graph survived); EXP curves (Gen 1 stores the growth
# rate inside the base-stats table, so the same check would refuse the ROM);
# ALLOW_PIKACHU_EVOLUTION (an evolution); in-game trades (the client reasons about the
# specific species an NPC trade gives, untested on randomized ones); and everything
# tweakForRom clears for Gen 1 anyway (held items, abilities, time-based encounters, tutors).
#
# kind "choice": ``choices`` maps value -> (label, flags to set); every flag any choice of
# that option owns is cleared first, so exactly one mode bit ends up set.
# kind "bool": ``flag`` (a FLAGS name) or ``misc`` (a MISC_TWEAKS name).
# kind "int": ``byte`` plus ``encode``/``decode`` between the value and that whole byte.
def _level_mod(byte: int) -> dict:
    # (modified ? 0x80 : 0) | (modifier + 50); 0 % is written as "not modified"
    return {"kind": "int", "min": -50, "max": 50, "unit": "%", "byte": byte,
            "encode": lambda v: (0x80 | (v + _LEVEL_MOD_BIAS)) if v else _LEVEL_MOD_BIAS,
            "decode": lambda b: (b & 0x7F) - _LEVEL_MOD_BIAS if b & 0x80 else 0}


OPTIONS: dict[str, dict] = {
    # wild
    "wild": {"kind": "choice", "group": "Wild encounters", "label": "Wild encounters", "default": "random",
             "choices": {"unchanged": ("Unchanged", ["wild_UNCHANGED"]),
                         "random": ("Random", ["wild_RANDOM"]),
                         "area": ("1-to-1 per area", ["wild_AREA_MAPPING"]),
                         "global": ("Global 1-to-1", ["wild_GLOBAL_MAPPING"])}},
    "wild_restriction": {"kind": "choice", "group": "Wild encounters", "label": "Restriction", "default": "none",
                         "choices": {"none": ("None", ["wildRestriction_NONE"]),
                                     "similar": ("Similar strength", ["wildRestriction_SIMILAR_STRENGTH"]),
                                     "catch_em_all": ("Catch 'em all", ["wildRestriction_CATCH_EM_ALL"]),
                                     "type_themed": ("Type-themed areas", ["wildRestriction_TYPE_THEME_AREAS"])}},
    "wild_block_legendaries": {"kind": "bool", "group": "Wild encounters", "label": "No wild legendaries",
                               "default": True, "flag": "blockWildLegendaries"},
    "wild_min_catch_rate": {"kind": "int", "group": "Wild encounters", "label": "Minimum catch rate",
                            "default": 0, "min": 0, "max": 5, "byte": 50,
                            "flag": "useMinimumCatchRate",                    # bit 0 of byte 16, on when > 0
                            "encode": lambda v: ((v - 1) << 3) if v else 0,
                            "decode": lambda b: (b >> 3 & 7) + 1},
    "wild_levels": dict(_level_mod(38), group="Wild encounters", label="Wild level curve", default=0),
    # starters
    "starters": {"kind": "choice", "group": "Starters", "label": "Starters", "default": "random",
                 "choices": {"unchanged": ("Unchanged", ["starters_UNCHANGED"]),
                             "random": ("Random", ["starters_COMPLETELY_RANDOM"]),
                             "two_evos": ("Random with two evolutions", ["starters_RANDOM_WITH_TWO_EVOLUTIONS"])}},
    # statics
    "statics": {"kind": "choice", "group": "Static encounters", "label": "Static encounters", "default": "unchanged",
                "choices": {"unchanged": ("Unchanged", ["static_UNCHANGED"]),
                            "random": ("Random", ["static_COMPLETELY_RANDOM"]),
                            "matching": ("Random, legendary for legendary", ["static_RANDOM_MATCHING"]),
                            "similar": ("Similar strength", ["static_SIMILAR_STRENGTH"])}},
    "static_levels": dict(_level_mod(47), group="Static encounters", label="Static level curve", default=0),
    # trainers
    "trainers": {"kind": "choice", "group": "Trainers", "label": "Trainer teams", "default": "random",
                 "choices": {"unchanged": ("Unchanged", ["trainers_UNCHANGED"]),
                             "random": ("Random", ["trainers_RANDOM"]),
                             "distributed": ("Random, evenly distributed", ["trainers_DISTRIBUTED"]),
                             "type_themed": ("Type-themed", ["trainers_TYPE_THEMED"]),
                             "type_themed_gyms": ("Type-themed gyms and Elite Four", ["trainers_TYPE_THEMED_ELITE4_GYMS"])}},
    "trainers_similar_strength": {"kind": "bool", "group": "Trainers", "label": "Similar strength",
                                  "default": False, "flag": "trainersUsePokemonOfSimilarStrength"},
    "trainers_rival_starter": {"kind": "bool", "group": "Trainers", "label": "Rival keeps their starter",
                               "default": False, "flag": "rivalCarriesStarterThroughout"},
    "trainers_block_legendaries": {"kind": "bool", "group": "Trainers", "label": "No trainer legendaries",
                                   "default": True, "flag": "trainersBlockLegendaries"},
    "trainers_match_typing": {"kind": "bool", "group": "Trainers", "label": "Match the original type spread",
                              "default": False, "flag": "trainersMatchTypingDistribution"},
    "trainers_levels": dict(_level_mod(36), group="Trainers", label="Trainer level curve", default=0),
    "trainers_force_evolved": {"kind": "int", "group": "Trainers", "label": "Fully evolved from level",
                               "default": 0, "min": 0, "max": 100, "byte": 14,
                               "encode": lambda v: (0x80 | v) if v else 30,   # 30: UPR's default, not forced
                               "decode": lambda b: b & 0x7F if b & 0x80 else 0},
    "trainer_names": {"kind": "bool", "group": "Trainers", "label": "Random trainer names",
                      "default": False, "flag": "randomizeTrainerNames"},
    "trainer_class_names": {"kind": "bool", "group": "Trainers", "label": "Random trainer classes",
                            "default": False, "flag": "randomizeTrainerClassNames"},
    # TMs
    "tms": {"kind": "choice", "group": "TMs", "label": "TM moves", "default": "unchanged",
            "choices": {"unchanged": ("Unchanged", ["tms_UNCHANGED"]),
                        "random": ("Random", ["tms_RANDOM"])}},
    "tm_compat": {"kind": "choice", "group": "TMs", "label": "TM compatibility", "default": "unchanged",
                  "choices": {"unchanged": ("Unchanged", ["tmCompat_UNCHANGED"]),
                              "random": ("Random", ["tmCompat_COMPLETELY_RANDOM"]),
                              "prefer_type": ("Random, prefer same type", ["tmCompat_RANDOM_PREFER_TYPE"]),
                              "full": ("Everything learns everything", ["tmCompat_FULL"])},
                  "help": "the 151 dex records; pureRGB's 13 non-dex forms/spirits keep their own "
                          "TM bytes on every mode (review cx-795d1423 #7)"},
    "tm_sanity": {"kind": "bool", "group": "TMs", "label": "Level-up moves stay TM-compatible",
                  "default": False, "flag": "tmLevelUpMoveSanity"},
    "tm_keep_field": {"kind": "bool", "group": "TMs", "label": "Keep field-move TMs",
                      "default": False, "flag": "keepFieldMoveTMs"},
    # field items
    "field_items": {"kind": "choice", "group": "Field items", "label": "Field items", "default": "unchanged",
                    "choices": {"unchanged": ("Unchanged", ["fieldItems_UNCHANGED"]),
                                "random": ("Random", ["fieldItems_RANDOM"]),
                                "shuffle": ("Shuffled", ["fieldItems_SHUFFLE"]),
                                "random_even": ("Random, evenly spread", ["fieldItems_RANDOM_EVEN"])}},
    "field_items_ban_bad": {"kind": "bool", "group": "Field items", "label": "No junk items",
                            "help": "no effect on Gen 1: stock UPR has no bad-item list there (review cx-795d1423 #6)",
                            "default": False, "flag": "banBadRandomFieldItems"},
    # misc tweaks -- none of these touch species, types or evolutions
    "fastest_text": {"kind": "bool", "group": "Tweaks", "label": "Fastest text", "default": True, "misc": "FASTEST_TEXT"},
    "pc_potion": {"kind": "bool", "group": "Tweaks", "label": "Random PC potion", "default": False, "misc": "RANDOMIZE_PC_POTION"},
    "lowercase_names": {"kind": "bool", "group": "Tweaks", "label": "Lower-case names", "default": False, "misc": "LOWER_CASE_POKEMON_NAMES"},
    "nerf_x_accuracy": {"kind": "bool", "group": "Tweaks", "label": "Nerf X Accuracy", "default": False, "misc": "NERF_X_ACCURACY"},
    "fix_crit_rate": {"kind": "bool", "group": "Tweaks", "label": "Fix the crit rate", "default": False, "misc": "FIX_CRIT_RATE"},
    "update_type_effectiveness": {"kind": "bool", "group": "Tweaks", "label": "Later-gen type chart", "default": False, "misc": "UPDATE_TYPE_EFFECTIVENESS"},
}

# What each option and each choice means, in the form's words: UPR ZX's own GUI tooltips
# (the jar's com/dabomstew/pkrandom/newgui/Bundle.properties, keys in the comments),
# shortened, plus the Soul Link consequence where there is one. Kept beside OPTIONS rather
# than inside it so the option rows stay the codec they are; option_form() merges these in.
HELP: dict[str, str] = {
    "wild": "Which Pokémon appear in the grass, caves and water. The same setting on both cartridges, so the species clause means the same thing for both players.",
    "wild_restriction": "A rule on top of the wild mode. Under a global 1-to-1 map only None applies.",
    "wild_block_legendaries": "Legendaries never appear as wild replacements.",                      # wpDontUseLegendaries
    "wild_min_catch_rate": "0 is off. 1 to 5 raises every species with a lower catch rate to that tier: 1 ≈ 10 % with a Poké Ball at full health, 2 ≈ 17 %, 3 ≈ 27 %, 4 ≈ 34 %, 5 = guaranteed.",  # wpSetMinimumCatchRateSlider
    "wild_levels": "Raise or lower every wild Pokémon's level by this much.",                       # wpPercentageLevelModifier
    "starters": "The three starters on the lab table.",                                             # sp*
    "statics": "The one-off encounters, gifts and purchases: Snorlax, the birds, the Eevee, the fossils…",  # stp*
    "static_levels": "Raise or lower every static encounter's level by this much.",                # stpPercentageLevelModifier
    "trainers": "Which Pokémon trainers fight you with.",                                           # tp*
    "trainers_similar_strength": "Each replacement is of similar power to the original. Other rules, such as type theming, take precedence, so it is not exact.",  # tpSimilarStrength
    "trainers_rival_starter": "Your rival keeps their starter in every fight, evolved as they progress; the rest of their team is random like everyone else's.",  # tpRivalCarriesStarter
    "trainers_block_legendaries": "Legendaries never appear on a trainer's team.",                  # tpDontUseLegendaries
    "trainers_match_typing": "The number of trainers of each type roughly follows how many Pokémon have that type — less repetition, but runs of the same type in a row.",  # tpWeightTypes
    "trainers_levels": "Raise or lower every trainer Pokémon's level by this much.",               # tpPercentageLevelModifier
    "trainers_force_evolved": "0 is off. Above it, every trainer Pokémon at or over this level is fully evolved, whatever else is set.",  # tpForceFullyEvolvedAt
    "trainer_names": "Trainers get new names. In Red / Blue / Yellow only the Gym Leaders and the Elite Four have names to change.",  # tpRandomizeTrainerNames
    "trainer_class_names": "Trainer classes get new names — a Youngster could become a Misfit.",  # tpRandomizeTrainerClassNames
    "tms": "Which move each TM teaches. HM moves are never affected, and every TM stays unique.",  # tm*
    "tm_compat": "Which Pokémon can learn which TMs and HMs.",                                      # thc*
    "tm_sanity": "A Pokémon can always learn the TM of a move it also learns by levelling up.",     # tmLevelupMoveSanity
    "tm_keep_field": "TMs with field moves — Dig, Teleport — are left alone; healing moves are not counted.",  # tmKeepFieldMoveTMs
    "field_items": "The items on the ground and the hidden ones. Key items stay where they are.",  # fi*
    "field_items_ban_bad": "Berries, mail and other items that do little are left out of the random pool.",  # fiBanBadItems
    "fastest_text": "Every text box shows with the least delay, whatever the in-game text speed.",  # miscFastestText
    "pc_potion": "The Potion in your PC at the start becomes another useful item.",                 # miscRandomizePCPotion
    "lowercase_names": "Pokémon names in Camel Case: VENUSAUR becomes Venusaur.",                  # miscLowerCasePokemonNames
    "nerf_x_accuracy": "X Accuracy no longer makes sleep, trapping and one-hit-KO moves hit every time.",  # miscNerfXAccuracy
    "fix_crit_rate": "Critical hits at the later games' 1/16 instead of Gen 1's Speed-based rate; Focus Energy and Dire Hit raise it as intended.",  # miscFixCritRate
    "update_type_effectiveness": "The type chart as of Gen 6 (Ghost hits Psychic, Ice resists nothing extra…). No Fairy type. Both cartridges get it, so the type clause still means the same on both.",  # miscUpdateTypeEffectiveness
}
CHOICE_HELP: dict[tuple[str, str], str] = {
    ("wild", "unchanged"): "Wild Pokémon stay as the game made them.",
    ("wild", "random"): "Every encounter slot in every area is random: many different Pokémon per area.",   # wpRandom
    ("wild", "area"): "Within an area, each species is swapped for one other species in every slot it has: a handful of Pokémon per area.",  # wpArea1To1
    ("wild", "global"): "Everywhere a species appears in the game it is swapped for one other species. Too restrictive for any other rule but None.",  # wpGlobal1To1
    ("wild_restriction", "none"): "No extra rule.",
    ("wild_restriction", "similar"): "Each replacement is of similar power to the original, as far as the map allows.",  # wpARSimilarStrength
    ("wild_restriction", "catch_em_all"): "Every replacement is a species not used before, so every Pokémon is catchable somewhere.",  # wpARCatchEmAll
    ("wild_restriction", "type_themed"): "Each area gets one random type and only Pokémon of that type — realistic, or odd (Fire Pokémon while surfing).",  # wpARTypeThemeAreas
    ("starters", "unchanged"): "Bulbasaur, Charmander, Squirtle.",
    ("starters", "random"): "Three random Pokémon.",                                                    # spRandomCompletely
    ("starters", "two_evos"): "Three random Pokémon that each have two evolutions ahead of them, like the real starters.",  # spRandomTwoEvos
    ("statics", "unchanged"): "Static Pokémon stay as the game made them.",
    ("statics", "random"): "Any Pokémon can replace any static one — a Mew in the Game Corner is possible.",  # stpRandomCompletely
    ("statics", "matching"): "Random, but a legendary is always swapped for another legendary.",       # stpSwapLegendariesSwapStandards
    ("statics", "similar"): "Each static Pokémon is swapped for one of similar strength.",             # stpRandomSimilarStrength
    ("trainers", "unchanged"): "Trainer teams stay as the game made them.",
    ("trainers", "random"): "Every trainer Pokémon is random.",                                          # tpRandom
    ("trainers", "distributed"): "Random, spread so that no species keeps turning up. Similar strength cannot be verified under it.",  # tpRandomEvenDistribution
    ("trainers", "type_themed"): "Each trainer gets a type and random Pokémon of that type; a gym's trainers share one type.",  # tpTypeThemed
    ("trainers", "type_themed_gyms"): "Type-themed for the Gym trainers, Leaders and the Elite Four only; everyone else random.",  # tpMain5TypeThemedEliteFourGyms
    ("tms", "unchanged"): "TMs teach what they always did.",
    ("tms", "random"): "Each TM teaches a new move.",                                                    # tmRandom
    ("tm_compat", "unchanged"): "Each Pokémon learns the same TMs it could before — even if the TMs' moves changed, which can get odd.",  # thcUnchanged
    ("tm_compat", "random"): "Each TM or HM has a 50 % chance of being learnable, whatever the type.",   # thcRandomCompletely
    ("tm_compat", "prefer_type"): "90 % chance for a TM of the Pokémon's own type, 50 % for Normal moves, 25 % otherwise.",  # thcRandomPreferSameType
    ("tm_compat", "full"): "Every Pokémon learns every TM and HM. Fun, and possibly too easy.",          # thcFullCompatibility
    ("field_items", "unchanged"): "Items stay where the game put them.",
    ("field_items", "random"): "A new random item in every item ball and hidden spot — a Master Ball on Route 1 is possible.",  # fiRandom
    ("field_items", "shuffle"): "The same items, in a new order: each appears once, somewhere else.",    # fiShuffle
    ("field_items", "random_even"): "Random, but the randomizer controls how many times each item is placed.",  # fiRandomEvenDistribution
}

# The six categories older callers speak in. Each is the choice option of the same name;
# "enabled" means anything but unchanged.
_CATEGORY_MODES = ("wild", "starters", "statics", "trainers", "tms", "field_items")

# Foundations the pipeline randomizes. The pure family (docs/purergb/PLAN.md §6 M5) runs on
# the SLink fork's lossless entries, which offer NO misc tweak: every tweak is a code write
# (fastest text is a C9 at TextDelayFunctionOffset; pureRGB has instant text natively), and
# the fork's tweakForRom would silently drop one that was asked for, so a settings file for
# the pure family must not ask.
FAMILY_VANILLA = "gen1_rby"
FAMILY_PURE = "gen1_purergb"
FAMILIES = (FAMILY_VANILLA, FAMILY_PURE)
# Options the fork cannot honour on a pure entry (review cx-795d1423 #4/#5): the pure INI rows
# carry TrainerTaggingDisabled=1 (no gym/Elite/rival tags -- pureRGB renumbered every class
# and the rival is name-substituted at runtime) and omit CanChangeTrainerText (the 56-entry
# class-name table and the unique OT names are not the vanilla text model). Stock UPR skips
# these silently; the pure family refuses them so nobody believes a setting that did nothing.
PURE_INERT_BOOLS = ("trainers_rival_starter", "trainer_names", "trainer_class_names")
PURE_INERT_TRAINER_MODES = ("type_themed_gyms",)


def misc_options() -> list[str]:
    return [key for key, opt in OPTIONS.items() if "misc" in opt]


def family_spec(spec: dict, family: str = FAMILY_VANILLA) -> dict:
    """``spec`` with the family's allowlist applied: the pure family has every tweak off."""
    if family not in FAMILIES:
        raise UprSettingsError(f"unknown randomizer family {family!r}")
    out = dict(spec)
    if family == FAMILY_PURE:
        for key in misc_options():
            out[key] = False              # a DEFAULT flip (fastest text defaults on); the
    return out                            # inert options are refused, never coerced


def default_spec(family: str = FAMILY_VANILLA) -> dict:
    return family_spec({key: opt["default"] for key, opt in OPTIONS.items()}, family)


def option_form() -> list[dict]:
    """The table as the form renders it: JSON-safe, in display order, no encoders. `pure` on
    a row / a choice says whether the pure family can honour it (the form disables what it
    cannot; a selection that slips through is refused by name, never coerced -- review
    cx-758c671d #2)."""
    out = []
    for key, opt in OPTIONS.items():
        row = {"key": key, "kind": opt["kind"], "group": opt["group"], "label": opt["label"],
               "default": opt["default"], "help": HELP.get(key, opt.get("help", "")),
               "note": opt.get("help", "") if key in HELP else "",
               "pure": key not in PURE_INERT_BOOLS and "misc" not in opt}
        if opt["kind"] == "choice":
            row["choices"] = [{"value": v, "label": lbl, "help": CHOICE_HELP.get((key, v), ""),
                               "pure": not (key == "trainers" and v in PURE_INERT_TRAINER_MODES)}
                              for v, (lbl, _f) in opt["choices"].items()]
        elif opt["kind"] == "int":
            row.update(min=opt["min"], max=opt["max"], unit=opt.get("unit", ""))
        out.append(row)
    return out


def _spec_data(spec: dict) -> bytearray:
    """Validate ``spec`` against OPTIONS and lay it over UPR's defaults. Every key must be
    known; missing keys take their default. This is the trust boundary for the HTTP body."""
    unknown = set(spec) - set(OPTIONS)
    if unknown:
        raise UprSettingsError(f"unknown randomizer option: {sorted(unknown)}")
    flags: dict[str, bool] = {}
    misc = 0
    override: dict[int, int] = {}
    for key, opt in OPTIONS.items():
        val = spec.get(key, opt["default"])
        kind = opt["kind"]
        if kind == "choice":
            if val not in opt["choices"]:
                raise UprSettingsError(f"{key}: {val!r} is not one of {sorted(opt['choices'])}")
            for _v, (_lbl, names) in opt["choices"].items():
                for n in names:
                    flags[n] = False
            for n in opt["choices"][val][1]:
                flags[n] = True
        elif kind == "bool":
            if not isinstance(val, bool):
                raise UprSettingsError(f"{key}: expected true/false, got {val!r}")
            if "flag" in opt:
                flags[opt["flag"]] = val
            else:
                misc |= MISC_TWEAKS[opt["misc"]] if val else 0
        else:
            if isinstance(val, bool) or not isinstance(val, int) or not opt["min"] <= val <= opt["max"]:
                raise UprSettingsError(f"{key}: expected {opt['min']}..{opt['max']}, got {val!r}")
            override[opt["byte"]] = opt["encode"](val)
            if "flag" in opt:
                flags[opt["flag"]] = val > 0
    data = _default_bytes()
    for name, on in flags.items():
        idx, bit = FLAGS[name]
        data[idx] = (data[idx] | 1 << bit) if on else (data[idx] & ~(1 << bit) & 0xFF)
    data[32:36] = struct.pack(">i", misc)
    for idx, val in override.items():
        data[idx] = val
    return data


def build_spec(spec: dict, rom_name: str = "Pokemon Red (U) [!]") -> bytes:
    """A file for exactly ``spec`` (see OPTIONS); anything not mentioned is at its default."""
    return _encode(_spec_data(spec), rom_name)


def spec_from_parsed(parsed: dict) -> dict:
    """The inverse of build_spec, read off a parsed file or log string. A choice with no
    recognised mode bit set reads as its default, so a foreign file still yields a spec --
    unexpected_settings is what refuses it, not this."""
    data, flags, tweaks = parsed["data"], parsed["flags"], parsed["misc_tweaks"]
    spec = {}
    for key, opt in OPTIONS.items():
        kind = opt["kind"]
        if kind == "choice":
            spec[key] = next((v for v, (_lbl, names) in opt["choices"].items()
                              if all(flags.get(n) for n in names)), opt["default"])
        elif kind == "bool":
            spec[key] = bool(flags.get(opt["flag"])) if "flag" in opt else bool(tweaks & MISC_TWEAKS[opt["misc"]])
        else:
            spec[key] = opt["decode"](data[opt["byte"]]) if ("flag" not in opt or flags.get(opt["flag"])) else 0
    return spec


def summarize(spec: dict) -> str:
    """One line for the run record: what differs from a run that randomizes nothing."""
    parts = []
    for key, opt in OPTIONS.items():
        val = spec.get(key, opt["default"])
        if opt["kind"] == "choice":
            if val != next(iter(opt["choices"])):        # the first choice is the quiet one
                parts.append(f"{opt['label'].lower()} {opt['choices'][val][0].lower()}")
        elif opt["kind"] == "bool":
            if val != opt["default"]:
                parts.append(opt["label"].lower() + ("" if val else " off"))
        elif val:
            parts.append(f"{opt['label'].lower()} {val:+d}{opt.get('unit', '')}"
                         if opt.get("unit") else f"{opt['label'].lower()} {val}")
    return ", ".join(parts) or "nothing"


def build_categories(enabled: set[str], fastest_text: bool = True,
                     rom_name: str = "Pokemon Red (U) [!]") -> bytes:
    """Build a file with exactly ``enabled`` randomized and everything else untouched."""
    unknown = set(enabled) - set(_CATEGORY_MODES)
    if unknown:
        raise UprSettingsError(f"not an allowed category: {sorted(unknown)}")
    spec = {cat: "random" if cat in enabled else "unchanged" for cat in _CATEGORY_MODES}
    spec["fastest_text"] = fastest_text
    return build_spec(spec, rom_name)


# ── reading ──────────────────────────────────────────────────────────────────────────────
def parse_settings_string(settings_string: str) -> dict:
    """Decode the Base64 blob. Accepts the raw string or the log's ``322<base64>`` form.

    The log line is ``Settings String: `` + VERSION + toString() with NO separator
    (Randomizer.java:76), so the leading version digits have to be stripped by length, not
    by looking for a delimiter that is not there.
    """
    s = settings_string.strip()
    if s.startswith(str(VERSION)):
        s = s[len(str(VERSION)):]
    try:
        blob = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UprSettingsError(f"settings string is not valid Base64: {exc}") from exc
    if len(blob) < LENGTH_OF_SETTINGS_DATA + 1 + 8:
        raise UprSettingsError(f"settings blob is only {len(blob)} bytes")

    body, stored = blob[:-8], struct.unpack(">I", blob[-8:-4])[0]
    actual = binascii.crc32(body) & 0xFFFFFFFF
    if actual != stored:
        raise UprSettingsError(
            f"settings checksum mismatch: stored 0x{stored:08X}, computed 0x{actual:08X}")

    data = blob[:LENGTH_OF_SETTINGS_DATA]
    name_len = blob[LENGTH_OF_SETTINGS_DATA]
    rom_name = blob[LENGTH_OF_SETTINGS_DATA + 1:
                    LENGTH_OF_SETTINGS_DATA + 1 + name_len].decode("ascii", "replace")
    tweaks = struct.unpack(">i", data[32:36])[0]
    return {
        "rom_name": rom_name,
        "data": bytes(data),
        "flags": {name: bool(data[i] >> bit & 1) for name, (i, bit) in FLAGS.items()},
        "misc_tweaks": tweaks,
        "misc_tweak_names": sorted(n for n, v in MISC_TWEAKS.items() if tweaks & v),
    }


def load(path_or_bytes) -> dict:
    """Read a .rnqs file. Returns the parse plus the declared version."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        raw = bytes(path_or_bytes)
    else:
        with open(path_or_bytes, "rb") as f:
            raw = f.read()
    if len(raw) < 8:
        raise UprSettingsError(f"file is only {len(raw)} bytes, too short for a header")
    version, length = struct.unpack(">i", raw[:4])[0], struct.unpack(">i", raw[4:8])[0]
    if length < 0 or 8 + length > len(raw):
        raise UprSettingsError(
            f"declared settings-string length {length} does not fit in {len(raw)} bytes")
    out = parse_settings_string(raw[8:8 + length].decode("ascii", "replace"))
    out["version"] = version
    # A file from an older UPR loads only after SettingsUpdater rewrites it, and the CLI
    # merely warns. We refuse instead: an updated file is not the file the other player
    # used, so "same settings" would stop being true without anyone being told.
    out["version_matches"] = version == VERSION
    return out


def categories_enabled(parsed: dict) -> set[str]:
    """Which of the six categories this settings file actually randomizes (any mode)."""
    spec = spec_from_parsed(parsed)
    return {cat for cat in _CATEGORY_MODES if spec[cat] != "unchanged"}


# wild=global (one species map for the whole game) honours only the similar-strength
# restriction: UPR's game1to1Encounters never reads type_themed / catch_em_all, so a file that
# combines them would run as plain global while claiming more (review cx-73e80e05 #7).
GLOBAL_IGNORED_RESTRICTIONS = ("type_themed", "catch_em_all")
# wild=global + similar IS honoured by UPR, but its picker draws from a pool that shrinks across
# the whole map, so no per-ROM oracle can bound a draw exactly (the verifier declines to model
# it, cx-37fe2641 #3); the project claims every admitted option is verified or refused -> refused.
GLOBAL_UNVERIFIABLE_RESTRICTIONS = ("similar",)
# trainers=distributed + similar_strength: the placement-history filter runs BEFORE the strength
# band (AbstractRomHandler ~6882-6890), so the band a slot reaches depends on the whole draw
# prefix -- no per-ROM oracle can bound a draw exactly (cx-636b45dd #3) -> refused by name
# (see forbidden_enabled).


def forbidden_enabled(parsed: dict, family: str = FAMILY_VANILLA) -> list[str]:
    """Settings that change data the Soul Link rules read. Any of these must reject a run.

    Types and evolutions decide the type and species clauses; move and base-stat changes
    make every cached stat and damage figure wrong. These are the domains the project chose
    NOT to support, so finding one enabled is a refusal, not a warning. For the pure family
    every misc tweak is forbidden too (see FAMILY_PURE).
    """
    f = parsed["flags"]
    bad = []
    spec = spec_from_parsed(parsed)
    if spec.get("wild") == "global" and spec.get("wild_restriction") in GLOBAL_IGNORED_RESTRICTIONS:
        bad.append(f"wild=global with wild_restriction={spec['wild_restriction']} "
                   f"(UPR ignores that restriction under a global map)")
    if spec.get("wild") == "global" and spec.get("wild_restriction") in GLOBAL_UNVERIFIABLE_RESTRICTIONS:
        bad.append(f"wild=global with wild_restriction={spec['wild_restriction']} "
                   f"(not verifiable: the global picker's pool shrinks across the whole map)")
    if spec.get("trainers") == "distributed" and spec.get("trainers_similar_strength"):
        bad.append("trainers=distributed with trainers_similar_strength "
                   "(not verifiable: the placement-history filter precedes the strength band)")
    if family == FAMILY_PURE and parsed.get("misc_tweaks"):
        bad.append("tweaks (" + ", ".join(parsed.get("misc_tweak_names") or ["unknown"]) + ")")
    if family == FAMILY_PURE:
        bad += [f"{key} (not implemented for pureRGB entries)" for key in PURE_INERT_BOOLS if spec.get(key)]
        if spec.get("trainers") in PURE_INERT_TRAINER_MODES:
            bad.append(f"trainers={spec['trainers']} (pure entries carry no gym/Elite tags)")
    if not f.get("types_UNCHANGED"):
        bad.append("types")
    if not f.get("evolutions_UNCHANGED"):
        bad.append("evolutions")
    if not f.get("movesets_UNCHANGED"):
        bad.append("movesets")
    if not f.get("baseStats_UNCHANGED"):
        bad.append("base_stats")
    for name in ("randomizeMovePowers", "randomizeMoveAccuracies", "randomizeMovePPs",
                 "randomizeMoveTypes", "randomizeMoveCategory"):
        if f.get(name):
            bad.append(name)
    for name in ("changeImpossibleEvolutions", "makeEvolutionsEasier",
                 "removeTimeBasedEvolutions", "updateMoves", "updateBaseStats"):
        if f.get(name):
            bad.append(name)
    return bad


# ── the allowlist ────────────────────────────────────────────────────────────────────────
# forbidden_enabled names the domains that are DANGEROUS, which is the wrong way round for a
# settings file: it can only reject what someone thought to list, and UPR has well over a
# hundred options. Measured -- randomizeTrainerNames, trainersUsePokemonOfSimilarStrength,
# useMinimumCatchRate, CATCH_EM_ALL and limitPokemon all sailed through it.
#
# So the file is checked the other way round: a settings file is admissible only if it is
# byte-for-byte one of the files THIS PROJECT would produce. The envelope is computed from
# OPTIONS itself: for each byte, the options that write to it (found by building each
# single-option variant and diffing against the default) and the product of their value
# sets -- so adding an option to the table widens the envelope automatically, and nothing
# else does. Options write independent bits or whole bytes, so a per-byte product is exact
# and no byte has more than a few hundred values.
#
# This applies to the FILE a player hands us, where their intent lives. It deliberately does
# NOT apply to the effective settings echoed in UPR's log: tweakForRom legitimately rewrites
# bytes there (the custom-starter slots become the ROM's own), so those are checked with
# forbidden_enabled instead.
_ENVELOPE_CACHE: list[set[int]] | None = None


def permitted_byte_values() -> list[set[int]]:
    """For each of the 51 settings bytes, every value an allowed configuration can hold."""
    global _ENVELOPE_CACHE
    if _ENVELOPE_CACHE is None:
        import itertools

        base = _spec_data({})
        values = {key: (list(opt["choices"]) if opt["kind"] == "choice"
                        else [False, True] if opt["kind"] == "bool"
                        else list(range(opt["min"], opt["max"] + 1)))
                  for key, opt in OPTIONS.items()}
        touches: dict[int, list[str]] = {}
        for key, vals in values.items():
            for v in vals:
                data = _spec_data({key: v})
                for i in range(LENGTH_OF_SETTINGS_DATA):
                    if data[i] != base[i] and key not in touches.setdefault(i, []):
                        touches[i].append(key)
        envelope: list[set[int]] = [{base[i]} for i in range(LENGTH_OF_SETTINGS_DATA)]
        for i, keys in touches.items():
            for combo in itertools.product(*(values[k] for k in keys)):
                envelope[i].add(_spec_data(dict(zip(keys, combo, strict=True)))[i])
        _ENVELOPE_CACHE = envelope
    return _ENVELOPE_CACHE


def _flags_in_byte(index: int) -> list[str]:
    return sorted(name for name, (i, _bit) in FLAGS.items() if i == index)


def unexpected_settings(parsed: dict) -> list[str]:
    """Everything in this file that no allowed configuration would produce.

    Empty means the file is one SLink could have generated itself. A non-empty result is a
    refusal, not a warning: "same settings, different seeds" is only meaningful if both
    players' files are drawn from the same known set, and a file carrying an option we have
    never reasoned about is outside it whether or not that option turns out to matter.
    """
    envelope = permitted_byte_values()
    data = parsed.get("data") or b""
    if len(data) < LENGTH_OF_SETTINGS_DATA:
        return [f"settings block is only {len(data)} bytes"]

    out = []
    for index in range(LENGTH_OF_SETTINGS_DATA):
        if data[index] in envelope[index]:
            continue
        # Name the individual flags where the byte is one we model, so the message points
        # at a setting the player can actually find in the GUI.
        differing = []
        for name in _flags_in_byte(index):
            bit = FLAGS[name][1]
            mine = bool(data[index] >> bit & 1)
            if all(bool(v >> bit & 1) != mine for v in envelope[index]):
                differing.append(f"{name}={'on' if mine else 'off'}")
        if differing:
            out.append(f"byte {index}: " + ", ".join(differing))
        else:
            # An unmodelled byte -- a level modifier, a percentage, a misc-tweak bit.
            # Reported by index and value rather than guessed at.
            out.append(
                f"byte {index} is 0x{data[index]:02X}, not one of "
                + "/".join(f"0x{v:02X}" for v in sorted(envelope[index])))
    return out
