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
          rom_name: str = "Pokemon Red (U) [!]") -> bytes:
    """A complete .rnqs file. ``flags`` is applied on top of UPR's own defaults.

    Setting a mode means clearing its siblings yourself -- e.g. enabling ``wild_RANDOM``
    without clearing ``wild_UNCHANGED`` leaves two mode bits set, and UPR's ``fromString``
    reads them in a fixed order so the result would be whichever it happens to test first.
    ``build_categories`` does that bookkeeping; prefer it.
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

    blob = bytearray(data)
    name_bytes = rom_name.encode("ascii")
    blob.append(len(name_bytes))
    blob += name_bytes
    blob += struct.pack(">I", binascii.crc32(bytes(blob)) & 0xFFFFFFFF)
    blob += struct.pack(">I", 0)      # customnames CRC -- written, never validated

    settings_string = base64.b64encode(bytes(blob))
    return struct.pack(">i", VERSION) + struct.pack(">i", len(settings_string)) + settings_string


# The categories this project allows a run to enable, and the mode bits each one owns.
# "Same settings, different seeds" is only meaningful if both players enabled the same set.
_CATEGORY_MODES = {
    "wild": ("wild_UNCHANGED", "wild_RANDOM"),
    "starters": ("starters_UNCHANGED", "starters_COMPLETELY_RANDOM"),
    "statics": ("static_UNCHANGED", "static_COMPLETELY_RANDOM"),
    "trainers": ("trainers_UNCHANGED", "trainers_RANDOM"),
    "tms": ("tms_UNCHANGED", "tms_RANDOM"),
    "field_items": ("fieldItems_UNCHANGED", "fieldItems_RANDOM"),
}


def build_categories(enabled: set[str], fastest_text: bool = True,
                     rom_name: str = "Pokemon Red (U) [!]") -> bytes:
    """Build a file with exactly ``enabled`` randomized and everything else untouched."""
    unknown = enabled - set(_CATEGORY_MODES)
    if unknown:
        raise UprSettingsError(f"not an allowed category: {sorted(unknown)}")
    flags: dict[str, bool] = {}
    for cat, (unchanged, randomized) in _CATEGORY_MODES.items():
        on = cat in enabled
        flags[unchanged] = not on
        flags[randomized] = on
    return build(flags, MISC_TWEAKS["FASTEST_TEXT"] if fastest_text else 0, rom_name)


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
    """Which allowed categories this settings file actually randomizes."""
    return {cat for cat, (_unchanged, randomized) in _CATEGORY_MODES.items()
            if parsed["flags"].get(randomized)}


def forbidden_enabled(parsed: dict) -> list[str]:
    """Settings that change data the Soul Link rules read. Any of these must reject a run.

    Types and evolutions decide the type and species clauses; move and base-stat changes
    make every cached stat and damage figure wrong. These are the domains the project chose
    NOT to support, so finding one enabled is a refusal, not a warning.
    """
    f = parsed["flags"]
    bad = []
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
# build_categories over every combination of the allowed categories and both Fastest Text
# states, so it cannot drift from what the pipeline actually supports -- adding a category
# to _CATEGORY_MODES widens the envelope automatically, and nothing else does.
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
        cats = sorted(_CATEGORY_MODES)
        envelope: list[set[int]] = [set() for _ in range(LENGTH_OF_SETTINGS_DATA)]
        for mask in range(1 << len(cats)):
            chosen = {c for i, c in enumerate(cats) if mask >> i & 1}
            for fastest in (True, False):
                data = load(build_categories(chosen, fastest_text=fastest))["data"]
                for i, byte in enumerate(data):
                    envelope[i].add(byte)
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
