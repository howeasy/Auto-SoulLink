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
    FLAGS,
    MISC_TWEAKS,
    VERSION,
    UprSettingsError,
    build,
    build_categories,
    categories_enabled,
    forbidden_enabled,
    load,
    parse_settings_string,
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
    # Every one of these passes forbidden_enabled, and none is in OPTIONS. That is the point.
    "useTimeBasedEncounters",
    "limitPokemon",
    "standardizeEXPCurves",
    "blockBrokenTMMoves",
    "randomizeWildPokemonHeldItems",
    "trades_RANDOMIZE_GIVEN",
    "trainersBlockEarlyWonderGuard",
])
def test_a_setting_outside_the_supported_set_is_named(flag):
    from server.upr_settings import unexpected_settings
    on = flag != "trainersBlockEarlyWonderGuard"      # a default-on flag: turning it OFF is foreign
    out = unexpected_settings(load(build({flag: on})))
    assert out, f"{flag} was accepted"
    assert any(flag in line for line in out), out


def test_two_mode_bits_in_one_group_are_refused():
    """A hand-made file with CATCH_EM_ALL set but NONE still set is not a file we produce,
    even though each bit alone is an option we offer."""
    from server.upr_settings import unexpected_settings
    out = unexpected_settings(load(build({"wildRestriction_CATCH_EM_ALL": True})))
    assert out and "byte 15" in out[0], out


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
    blob[43] = 0x80 | 60            # totemLevelsModified, +10 levels (Gen 7 only)
    body = bytes(blob[:-8])
    blob[-8:-4] = struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)
    fixed = base64.b64encode(bytes(blob))
    parsed = load(bytes(raw[:4]) + struct.pack(">i", len(fixed)) + fixed)
    out = unexpected_settings(parsed)
    assert any("byte 43" in line for line in out), out


def test_the_envelope_covers_all_fifty_one_bytes():
    """A short envelope would silently accept whatever it did not cover."""
    from server.upr_settings import permitted_byte_values
    env = permitted_byte_values()
    assert len(env) == 51
    assert all(v for v in env), "some byte has no permitted value at all"


# ── the option table ─────────────────────────────────────────────────────────────────────
# OPTIONS is the definition of "compatible with SLink": the form renders it, build_spec
# writes from it, spec_from_parsed reads back through it and the envelope is enumerated from
# it. These pin that the four agree with each other.

def _every_value():
    from server.upr_settings import OPTIONS
    for key, opt in OPTIONS.items():
        if opt["kind"] == "choice":
            vals = list(opt["choices"])
        elif opt["kind"] == "bool":
            vals = [False, True]
        else:
            vals = [opt["min"], opt["default"], opt["max"], (opt["min"] + opt["max"]) // 2 + 1]
        for v in vals:
            yield key, v


@pytest.mark.parametrize("key,value", list(_every_value()))
def test_every_option_value_round_trips_and_is_admitted(key, value):
    from server.upr_settings import build_spec, spec_from_parsed, unexpected_settings
    parsed = load(build_spec({key: value}))
    assert spec_from_parsed(parsed)[key] == value
    assert unexpected_settings(parsed) == []
    assert forbidden_enabled(parsed) == []


def test_a_full_spec_round_trips():
    from server.upr_settings import OPTIONS, build_spec, spec_from_parsed, unexpected_settings
    spec = {}
    for key, opt in OPTIONS.items():           # the LAST value of every option, all at once
        if opt["kind"] == "choice":
            spec[key] = list(opt["choices"])[-1]
        elif opt["kind"] == "bool":
            spec[key] = not opt["default"]
        else:
            spec[key] = opt["max"]
    parsed = load(build_spec(spec))
    assert spec_from_parsed(parsed) == spec
    assert unexpected_settings(parsed) == []


def test_the_level_curve_bytes_carry_their_own_enable_bit():
    """+50 % trainers is byte 36 = 0x80 | 100; 0 % is the unmodified 50, not 0x80 | 50.
    (Settings.toString: (trainersLevelModified ? 0x80 : 0) | (trainersLevelModifier + 50).)"""
    from server.upr_settings import build_spec
    assert load(build_spec({"trainers_levels": 50}))["data"][36] == 0x80 | 100
    assert load(build_spec({"trainers_levels": -50}))["data"][36] == 0x80 | 0
    assert load(build_spec({"trainers_levels": 0}))["data"][36] == 50
    assert load(build_spec({"wild_levels": 10}))["data"][38] == 0x80 | 60
    assert load(build_spec({"static_levels": -10}))["data"][47] == 0x80 | 40
    d = load(build_spec({"trainers_force_evolved": 36}))["data"]
    assert d[14] == 0x80 | 36
    assert load(build_spec({"trainers_force_evolved": 0}))["data"][14] == 30
    d = load(build_spec({"wild_min_catch_rate": 3}))["data"]
    assert d[16] & 1 and d[50] == 2 << 3
    d = load(build_spec({"wild_min_catch_rate": 0}))["data"]
    assert not d[16] & 1 and d[50] == 0


def test_build_categories_is_the_random_choice_of_each_category():
    from server.upr_settings import build_spec
    assert build_categories({"wild", "tms"}) == build_spec(
        {"wild": "random", "tms": "random", "starters": "unchanged", "statics": "unchanged",
         "trainers": "unchanged", "field_items": "unchanged"})
    assert build_categories(set(), fastest_text=False) == build_spec(
        dict.fromkeys(("wild", "starters", "statics", "trainers", "tms", "field_items"), "unchanged")
        | {"fastest_text": False})


def test_categories_enabled_counts_any_mode_not_just_random():
    from server.upr_settings import build_spec, categories_enabled
    parsed = load(build_spec({"wild": "area", "trainers": "type_themed", "starters": "unchanged"}))
    assert categories_enabled(parsed) == {"wild", "trainers"}


@pytest.mark.parametrize("spec,needle", [
    ({"nope": 1}, "unknown"),
    ({"wild": "chaos"}, "wild"),
    ({"trainers_levels": 51}, "-50..50"),
    ({"trainers_levels": "10"}, "-50..50"),
    ({"trainers_levels": True}, "-50..50"),
    ({"wild_min_catch_rate": 6}, "0..5"),
    ({"fastest_text": 1}, "true/false"),
])
def test_a_bad_spec_is_refused_by_name(spec, needle):
    from server.upr_settings import build_spec
    with pytest.raises(UprSettingsError, match=needle):
        build_spec(spec)


def test_summarize_names_what_differs_from_nothing():
    from server.upr_settings import summarize
    assert summarize(dict.fromkeys(("wild", "starters", "trainers"), "unchanged")) == "nothing"
    line = summarize({"trainers_levels": 30, "trainers_force_evolved": 36, "wild": "area",
                      "wild_block_legendaries": False, "starters": "unchanged", "trainers": "unchanged"})
    assert line == ("wild encounters 1-to-1 per area, no wild legendaries off, "
                    "trainer level curve +30%, fully evolved from level 36")


def test_option_form_is_json_safe_and_ordered_like_the_table():
    import json

    from server.upr_settings import OPTIONS, option_form
    rows = option_form()
    assert [r["key"] for r in rows] == list(OPTIONS)
    json.dumps(rows)
    by_key = {r["key"]: r for r in rows}
    assert by_key["trainers_levels"]["min"] == -50 and by_key["trainers_levels"]["unit"] == "%"
    assert [c["value"] for c in by_key["wild"]["choices"]] == ["unchanged", "random", "area", "global"]


# ── the Polished Crystal family (docs/polished/UPR_HANDLER.md; fork patches 0017 wild, 0018 the rest) ───
def test_polished_family_is_the_handlers_wild_allowlist():
    from server.upr_settings import (
        FAMILIES,
        FAMILY_POLISHED,
        POLISHED_OPTION_KEYS,
        ROM_NAME,
        options_for,
    )
    assert FAMILY_POLISHED == "gen2_polished" and FAMILY_POLISHED in FAMILIES
    assert tuple(options_for(FAMILY_POLISHED)) == POLISHED_OPTION_KEYS
    assert {o["group"] for o in options_for(FAMILY_POLISHED).values()} == {
        "Wild encounters", "Starters", "Static encounters", "Trainers", "In-game trades"}      # 0018
    assert not any("misc" in o for o in options_for(FAMILY_POLISHED).values())
    assert ROM_NAME[FAMILY_POLISHED] == "Polished Crystal (U) 3.2.3"


def test_polished_widest_allowed_file_round_trips_and_is_admitted():
    from server.upr_settings import (
        FAMILY_POLISHED,
        build_spec,
        default_spec,
        spec_from_parsed,
        summarize,
        unexpected_settings,
    )
    spec = dict(default_spec(FAMILY_POLISHED), wild="area", wild_restriction="type_themed",
                wild_block_legendaries=False, wild_min_catch_rate=4, wild_levels=-20)
    parsed = load(build_spec(spec, family=FAMILY_POLISHED))
    assert parsed["misc_tweaks"] == 0 and parsed["rom_name"] == "Polished Crystal (U) 3.2.3"
    assert forbidden_enabled(parsed, FAMILY_POLISHED) == []
    assert unexpected_settings(parsed, FAMILY_POLISHED) == []
    assert spec_from_parsed(parsed, FAMILY_POLISHED) == spec
    assert categories_enabled(parsed, FAMILY_POLISHED) == {"wild", "starters", "trainers"}   # 0018 defaults
    assert "tm moves" not in summarize(spec_from_parsed(parsed, FAMILY_POLISHED))    # absent, not "unchanged"


@pytest.mark.parametrize("flags, expected", [
    ({"baseStats_UNCHANGED": False, "baseStats_RANDOM": True}, "base_stats"),
    ({"types_UNCHANGED": False}, "types"), ({"evolutions_UNCHANGED": False}, "evolutions"),
    ({"movesets_UNCHANGED": False}, "movesets"),
    ({"tms_UNCHANGED": False, "tms_RANDOM": True}, "tms"),
    ({"fieldItems_UNCHANGED": False, "fieldItems_RANDOM": True}, "field_items")])
def test_polished_refuses_rule_tables_and_every_category_without_a_writer(flags, expected):
    from server.upr_settings import FAMILY_POLISHED, unexpected_settings
    parsed = load(build(flags, rom_name="Polished Crystal (U) 3.2.3"))
    assert any(why.startswith(expected) for why in forbidden_enabled(parsed, FAMILY_POLISHED))
    assert unexpected_settings(parsed, FAMILY_POLISHED)


@pytest.mark.parametrize("tweak", ["FASTEST_TEXT", "BW_EXP_PATCH", "UPDATE_TYPE_EFFECTIVENESS", "LOWER_CASE_POKEMON_NAMES"])
def test_polished_refuses_every_misc_tweak(tweak):
    from server.upr_settings import FAMILY_POLISHED, unexpected_settings
    parsed = load(build({}, MISC_TWEAKS[tweak], rom_name="Polished Crystal (U) 3.2.3"))
    assert any(tweak in why for why in forbidden_enabled(parsed, FAMILY_POLISHED))
    assert unexpected_settings(parsed, FAMILY_POLISHED)


def test_polished_refuses_a_non_wild_option_by_name():
    from server.upr_settings import FAMILY_POLISHED, build_spec
    with pytest.raises(UprSettingsError, match="tms"):
        build_spec({"tms": "random"}, family=FAMILY_POLISHED)
    with pytest.raises(UprSettingsError, match="fastest_text"):
        build_spec({"fastest_text": True}, family=FAMILY_POLISHED)


# P8 / fork patch 0018: starters, statics (+ levels), trainer species and NPC-trade species; measured with the 0018
# jar on the release ROM (every allowed option honoured; the excluded ones throw in the handler or are dropped).
def test_polished_0018_widest_file_round_trips_and_is_admitted():
    from server.upr_settings import (
        FAMILY_POLISHED,
        build_spec,
        default_spec,
        spec_from_parsed,
        unexpected_settings,
    )
    spec = dict(default_spec(FAMILY_POLISHED), starters="two_evos", statics="matching", static_levels=20,
                trainers="type_themed_gyms", trainers_similar_strength=True, trainers_rival_starter=True,
                trainers_block_legendaries=False, trainers_match_typing=True, trades="given_and_requested")
    parsed = load(build_spec(spec, family=FAMILY_POLISHED))
    assert forbidden_enabled(parsed, FAMILY_POLISHED) == []
    assert unexpected_settings(parsed, FAMILY_POLISHED) == []
    assert spec_from_parsed(parsed, FAMILY_POLISHED) == spec
    assert categories_enabled(parsed, FAMILY_POLISHED) == {"wild", "starters", "statics", "trainers"}


@pytest.mark.parametrize("key, value", [
    ("trainers_levels", 20),            # the handler throws on any trainer level change
    ("trainers_force_evolved", 30),     # LEVEL_FROM_BADGES-relative trainer levels (> 100) read as plain levels
    ("trainer_names", True), ("trainer_class_names", True),            # canChangeTrainerText off: silently dropped
    ("trades_nicknames", True), ("trades_items", True), ("trades_ivs", True), ("trades_ots", True),   # handler throws
    ("wild_held_items", True), ("trainer_items_boss", True), ("tutors", "random"), ("shops", "random"),
    ("field_items", "random"), ("fastest_text", True), ("running_shoes_indoors", True)])
def test_polished_refuses_what_the_0018_handler_does_not_honour(key, value):
    from server.upr_settings import (
        FAMILY_FRLG,
        FAMILY_POLISHED,
        build_spec,
        default_spec,
        unexpected_settings,
    )
    with pytest.raises(UprSettingsError, match=key):
        build_spec({key: value}, family=FAMILY_POLISHED)
    # the same option in a file built elsewhere (FR/LG's table carries every key) is outside the envelope
    raw = {**default_spec(FAMILY_FRLG), "wild": "unchanged", "starters": "unchanged", "trainers": "unchanged",
           "fastest_text": False, key: value}
    assert unexpected_settings(load(build_spec(raw, rom_name="Polished Crystal (U) 3.2.3", family=FAMILY_FRLG)),
                               FAMILY_POLISHED)


def test_polished_minimum_catch_rate_stops_below_guaranteed_catching():
    """Level 5 is UPR's guaranteed catching, a code write the 0018 handler throws on (measured)."""
    from server.upr_settings import (
        FAMILY_POLISHED,
        OPTIONS,
        build_spec,
        options_for,
        unexpected_settings,
    )
    assert options_for(FAMILY_POLISHED)["wild_min_catch_rate"]["max"] == 4 and OPTIONS["wild_min_catch_rate"]["max"] == 5
    with pytest.raises(UprSettingsError, match="wild_min_catch_rate"):
        build_spec({"wild_min_catch_rate": 5}, family=FAMILY_POLISHED)
    assert unexpected_settings(load(build_spec({"wild_min_catch_rate": 5}, rom_name="Polished Crystal (U) 3.2.3")),
                               FAMILY_POLISHED)
