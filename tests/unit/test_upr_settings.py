"""The .rnqs codec, checked against UPR v4.6.1's own encoder.

These tests need no jar and no ROM: the format is fully specified by
``Settings.toString()``/``fromString()`` and every bit position in server/upr_settings.py is
transcribed from there. What the codec is FOR is admission -- deciding whether two players'
settings are the same, and whether either enabled something the Soul Link rules cannot
survive -- so the tests are about those decisions, not about byte trivia.

The one thing they cannot prove is that UPR agrees. That is proved separately and for real
in tests/unit/test_gen1_rom_scan.py::TestRandomizedRoms, which feeds a file built here to
the actual jar; UPR validates the CRC on load, so a malformed file is rejected outright.
"""
from __future__ import annotations

import base64
import struct

import pytest

from server.upr_settings import (
    FLAGS, MISC_TWEAKS, VERSION, UprSettingsError, build, build_categories,
    categories_enabled, forbidden_enabled, load, parse_settings_string,
)

ALL_CATEGORIES = {"wild", "starters", "statics", "trainers", "tms", "field_items"}


def test_a_default_file_randomizes_nothing():
    parsed = load(build())
    assert parsed["version"] == VERSION
    assert parsed["version_matches"] is True
    assert categories_enabled(parsed) == set()
    assert forbidden_enabled(parsed) == []


def test_an_all_zero_blob_is_not_the_same_as_unchanged():
    """UNCHANGED is an explicit SET bit, so zeros mean "no mode chosen", not "do nothing".

    Building defaults by zeroing is the obvious shortcut and it is wrong -- this pins that
    the default really does carry the UNCHANGED bits.
    """
    parsed = load(build())
    for name in ("wild_UNCHANGED", "starters_UNCHANGED", "static_UNCHANGED",
                 "trainers_UNCHANGED", "tms_UNCHANGED", "fieldItems_UNCHANGED",
                 "types_UNCHANGED", "evolutions_UNCHANGED", "movesets_UNCHANGED",
                 "baseStats_UNCHANGED"):
        assert parsed["flags"][name] is True, f"{name} is not set in the default blob"


@pytest.mark.parametrize("categories", [
    set(), {"wild"}, {"wild", "starters"}, ALL_CATEGORIES,
])
def test_categories_round_trip(categories):
    parsed = load(build_categories(categories))
    assert categories_enabled(parsed) == categories
    # Enabling a category must CLEAR its UNCHANGED sibling; leaving both set would make the
    # result depend on which bit UPR happens to test first.
    for cat in categories:
        unchanged = {"wild": "wild_UNCHANGED", "starters": "starters_UNCHANGED",
                     "statics": "static_UNCHANGED", "trainers": "trainers_UNCHANGED",
                     "tms": "tms_UNCHANGED", "field_items": "fieldItems_UNCHANGED"}[cat]
        assert parsed["flags"][unchanged] is False, f"{cat}: both mode bits are set"


def test_fastest_text_is_a_misc_tweak_not_a_flag():
    on = load(build_categories({"wild"}, fastest_text=True))
    off = load(build_categories({"wild"}, fastest_text=False))
    assert on["misc_tweak_names"] == ["FASTEST_TEXT"]
    assert on["misc_tweaks"] == MISC_TWEAKS["FASTEST_TEXT"] == 1 << 3
    assert off["misc_tweak_names"] == []


def test_an_unknown_category_is_refused():
    with pytest.raises(UprSettingsError, match="not an allowed category"):
        build_categories({"wild", "abilities"})


def test_an_unknown_flag_is_refused():
    with pytest.raises(UprSettingsError, match="unknown settings flag"):
        build({"randomizeEverything": True})


# ── the refusals that protect the rules ──────────────────────────────────────────────────
@pytest.mark.parametrize("flag,expected", [
    ("types_UNCHANGED", "types"),
    ("evolutions_UNCHANGED", "evolutions"),
    ("movesets_UNCHANGED", "movesets"),
    ("baseStats_UNCHANGED", "base_stats"),
])
def test_clearing_an_unchanged_bit_is_reported_as_forbidden(flag, expected):
    """These four decide the type clause, the species clause and every cached stat."""
    assert forbidden_enabled(load(build({flag: False}))) == [expected]


@pytest.mark.parametrize("flag", [
    "randomizeMovePowers", "randomizeMoveAccuracies", "randomizeMovePPs",
    "randomizeMoveTypes", "randomizeMoveCategory",
    "changeImpossibleEvolutions", "makeEvolutionsEasier", "removeTimeBasedEvolutions",
    "updateMoves", "updateBaseStats",
])
def test_each_rule_bearing_mutation_is_reported(flag):
    assert flag in forbidden_enabled(load(build({flag: True})))


def test_the_allowed_set_is_not_reported_as_forbidden():
    """The whole allowlist enabled at once must still be admissible.

    Without this, a forbidden_enabled that simply returned everything would pass every
    test above.
    """
    assert forbidden_enabled(load(build_categories(ALL_CATEGORIES))) == []


# ── file integrity ───────────────────────────────────────────────────────────────────────
def test_a_tampered_blob_fails_its_checksum():
    raw = bytearray(build_categories({"wild"}))
    length = struct.unpack(">i", raw[4:8])[0]
    blob = bytearray(base64.b64decode(raw[8:8 + length]))
    blob[15] ^= 0xFF                     # flip the wild-mode byte, leave the CRC alone
    tampered = base64.b64encode(bytes(blob))
    rebuilt = raw[:4] + struct.pack(">i", len(tampered)) + tampered
    with pytest.raises(UprSettingsError, match="checksum mismatch"):
        load(bytes(rebuilt))


def test_truncated_and_short_files_are_refused():
    with pytest.raises(UprSettingsError, match="too short"):
        load(b"\x00\x00")
    raw = build_categories({"wild"})
    with pytest.raises(UprSettingsError, match="does not fit"):
        load(raw[:4] + struct.pack(">i", 99999))


def test_not_base64_is_refused():
    with pytest.raises(UprSettingsError, match="not valid Base64"):
        parse_settings_string("this is not base64!!!")


def test_an_older_settings_version_is_flagged_rather_than_silently_updated():
    """UPR would run SettingsUpdater and merely warn; an updated file is not the file the
    other player used, so "same settings" would quietly stop being true."""
    raw = bytearray(build_categories({"wild"}))
    raw[:4] = struct.pack(">i", VERSION - 1)
    assert load(bytes(raw))["version_matches"] is False


# ── the log form ─────────────────────────────────────────────────────────────────────────
def test_the_log_settings_string_has_no_separator_before_the_base64():
    """Randomizer.java writes VERSION + toString() with nothing between them, so the
    version digits have to be stripped by length rather than split on a delimiter."""
    raw = build_categories({"wild", "tms"})
    length = struct.unpack(">i", raw[4:8])[0]
    body = raw[8:8 + length].decode("ascii")
    from_log = parse_settings_string(f"{VERSION}{body}")
    assert categories_enabled(from_log) == {"wild", "tms"}
    assert parse_settings_string(body)["data"] == from_log["data"]


def test_rom_name_is_carried_but_does_not_restrict_the_rom():
    """UPR stores romName and never compares it, so one file really does apply to all
    three titles. Recording that here stops a future reader assuming it is a guard."""
    parsed = load(build_categories({"wild"}, rom_name="Pokemon Yellow (U) [!]"))
    assert parsed["rom_name"] == "Pokemon Yellow (U) [!]"


def test_every_named_flag_fits_in_the_settings_block():
    for name, (idx, bit) in FLAGS.items():
        assert 0 <= idx < 51, f"{name} indexes byte {idx}"
        assert 0 <= bit < 8, f"{name} indexes bit {bit}"


# ── the allowlist ────────────────────────────────────────────────────────────────────────
# forbidden_enabled names the DANGEROUS domains, which can only ever reject what someone
# thought to list. unexpected_settings inverts it: a file is admissible only if it is one
# this project would itself produce. These tests exist because the blacklist demonstrably
# waved through five real settings.

@pytest.mark.parametrize("categories", [
    set(), {"wild"}, {"wild", "tms"}, ALL_CATEGORIES,
])
@pytest.mark.parametrize("fastest", [True, False])
def test_every_configuration_we_can_produce_is_accepted(categories, fastest):
    """The envelope is computed from build_categories, so this is the check that it has not
    become narrower than the pipeline it is meant to describe."""
    from server.upr_settings import unexpected_settings
    parsed = load(build_categories(categories, fastest_text=fastest))
    assert unexpected_settings(parsed) == []


def test_the_default_file_is_accepted():
    from server.upr_settings import unexpected_settings
    assert unexpected_settings(load(build())) == []


@pytest.mark.parametrize("flag", [
    # Every one of these passed forbidden_enabled. That is the point.
    "randomizeTrainerNames",
    "randomizeTrainerClassNames",
    "trainersUsePokemonOfSimilarStrength",
    "rivalCarriesStarterThroughout",
    "useMinimumCatchRate",
    "wildRestriction_CATCH_EM_ALL",
    "wildRestriction_TYPE_THEME_AREAS",
    "useTimeBasedEncounters",
    "limitPokemon",
    "standardizeEXPCurves",
    "tmLevelUpMoveSanity",
    "keepFieldMoveTMs",
    "banBadRandomFieldItems",
    "blockBrokenTMMoves",
])
def test_a_setting_outside_the_supported_set_is_named(flag):
    from server.upr_settings import unexpected_settings
    out = unexpected_settings(load(build({flag: True})))
    assert out, f"{flag} was accepted"
    assert any(flag in line for line in out), out


def test_the_allowlist_also_catches_the_dangerous_domains():
    """It is a superset of forbidden_enabled, so nothing got weaker by adding it."""
    from server.upr_settings import unexpected_settings
    for flag in ("types_UNCHANGED", "evolutions_UNCHANGED", "movesets_UNCHANGED",
                 "baseStats_UNCHANGED"):
        assert unexpected_settings(load(build({flag: False}))), f"{flag}=off was accepted"


def test_an_unmodelled_byte_is_reported_by_index_rather_than_guessed_at():
    """Level modifiers and percentages have no entry in FLAGS. They must still be refused,
    and the message has to say which byte rather than inventing a name for it."""
    import binascii
    from server.upr_settings import unexpected_settings
    raw = bytearray(build_categories({"wild"}))
    length = struct.unpack(">i", raw[4:8])[0]
    blob = bytearray(base64.b64decode(raw[8:8 + length]))
    blob[38] = 0x80 | 60            # wildLevelsModified, +10 levels
    body = bytes(blob[:-8])
    blob[-8:-4] = struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)
    fixed = base64.b64encode(bytes(blob))
    parsed = load(bytes(raw[:4]) + struct.pack(">i", len(fixed)) + fixed)
    out = unexpected_settings(parsed)
    assert any("byte 38" in line for line in out), out


def test_the_envelope_covers_all_fifty_one_bytes():
    """A short envelope would silently accept whatever it did not cover."""
    from server.upr_settings import permitted_byte_values
    env = permitted_byte_values()
    assert len(env) == 51
    assert all(v for v in env), "some byte has no permitted value at all"
