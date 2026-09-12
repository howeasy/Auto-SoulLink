"""Complete settings format and locked policy, without a JAR or ROM."""
import base64
import binascii
import re
import struct

import pytest

from server import gen1_upr_policy as policy
from server.upr_catalog import FIELDS, decode, encode, read_file, settings_file
from server.upr_runner import UprRunError, canonical_seed, strict_log
from server.upr_settings import UprSettingsError, load


def test_catalog_owns_every_bit_once_including_reserved_positions():
    positions = [tuple(position) for field in FIELDS.values() for position in field["positions"]]
    assert len(positions) == len(set(positions)) == 408
    assert set(positions) == {(byte, bit) for byte in range(51) for bit in range(8)}


def test_locked_default_has_no_enabled_side_flags_and_roundtrips():
    values = policy.defaults()
    assert all(value is False for name, value in values.items() if FIELDS[name]["kind"] == "boolean")
    assert decode(encode(values)) == read_file(policy.build_preset()) == values


def test_every_forbidden_boolean_is_rejected_by_its_own_name():
    for name, field in FIELDS.items():
        if field["kind"] == "boolean" and name not in policy.ALLOWED_BOOLEANS:
            with pytest.raises(UprSettingsError, match=name):
                policy.build_preset({name: True})


def test_every_forbidden_enum_is_rejected_including_irrelevant_generations():
    for name, field in FIELDS.items():
        if field["kind"] != "enum":
            continue
        allowed = policy.ALLOWED_ENUMS.get(name, {policy.defaults()[name]})
        for value in field["choices"]:
            if value not in allowed:
                with pytest.raises(UprSettingsError, match=name):
                    policy.build_preset({name: value})


def test_every_reserved_bit_and_ambiguous_enum_is_rejected():
    original = encode(policy.defaults())
    for name, field in FIELDS.items():
        if field["kind"] == "reserved":
            data = bytearray(original)
            byte, bit = field["positions"][0]
            data[byte] |= 1 << bit
            with pytest.raises(UprSettingsError, match=name):
                decode(bytes(data))
        elif field["kind"] == "enum":
            data = bytearray(original)
            for byte, bit in field["positions"]:
                data[byte] &= ~(1 << bit)
            with pytest.raises(UprSettingsError, match=name):
                decode(bytes(data))
            for byte, bit in field["positions"]:
                data[byte] |= 1 << bit
            with pytest.raises(UprSettingsError, match=name):
                decode(bytes(data))


@pytest.mark.parametrize("changes", [
    {"wildPokemonMod": "AREA_MAPPING"}, {"startersMod": "COMPLETELY_RANDOM"},
    {"staticPokemonMod": "RANDOM_MATCHING"}, {"trainersMod": "DISTRIBUTED"},
    {"tmsMod": "RANDOM"}, {"fieldItemsMod": "SHUFFLE"},
    {"changeImpossibleEvolutions": True}, {"makeEvolutionsEasier": True},
    {"removeTimeBasedEvolutions": True}, {"currentMiscTweaks": 8},
    {"trainersLevelModified": True, "trainersLevelModifier": 50},
    {"startersMod": "CUSTOM", "customStarters[0]": 1, "customStarters[1]": 150, "customStarters[2]": 151},
])
def test_approved_settings_preserve_the_selected_values(changes):
    assert policy.validate_file(policy.build_preset(changes)) == policy.defaults() | changes


def test_effective_changes_are_only_the_exact_canonical_starter_sentinels():
    original = policy.build_preset({"wildPokemonMod": "RANDOM"})
    effective = policy.validate_file(original)
    effective.update({"customStarters[0]": 25, "customStarters[1]": 133, "customStarters[2]": 1})
    stringify = lambda values: "322"+settings_file(values)[8:].decode("ascii")
    assert policy.verify_effective(original, stringify(effective), [25, 133]) == effective
    for name, value in (("customStarters[1]", 1), ("wildPokemonMod", "UNCHANGED"), ("blockWildLegendaries", True)):
        with pytest.raises(UprSettingsError, match=re.escape(name)):
            policy.verify_effective(original, stringify(effective | {name: value}), [25, 133])


@pytest.mark.parametrize("seed", ["", "00", "01", "-1", "+1", " 1", "1\n", "1.0", "1e2", "281474976710656", True, 1, None])
def test_seed_refuses_noncanonical_or_out_of_range_input(seed):
    with pytest.raises(UprRunError):
        canonical_seed(seed)


def test_seed_boundaries_are_losslessly_supported():
    assert canonical_seed("0") == 0
    assert canonical_seed("281474976710655") == (1 << 48)-1


def test_log_refuses_duplicates_missing_version_wrong_seed_and_bad_utf8():
    setting = "322"+policy.build_preset()[8:].decode("ascii")
    good = f"Randomizer Version: 4.6.1\nRandom Seed: 15\nSettings String: {setting}\n".encode()
    assert strict_log(b"\xef\xbb\xbf"+good)["seed"] == 15
    for label in (b"Randomizer Version", b"Random Seed", b"Settings String"):
        line = next(line for line in good.splitlines() if line.startswith(label))
        with pytest.raises(UprRunError):
            strict_log(good+line+b"\n")
        with pytest.raises(UprRunError):
            strict_log(good.replace(line+b"\n", b""))
    for bad in (good+b"\xff", good.replace(b": 15", b": 015"), good.replace(b": 4.6.1", b": 4.6.0"),
                good.replace(b"String: 322", b"String: 321")):
        with pytest.raises(UprRunError):
            strict_log(bad)


def test_settings_refuse_trailing_file_bytes_and_malformed_name_even_with_valid_crc():
    valid = policy.build_preset()
    with pytest.raises(UprSettingsError):
        load(valid+b"trailing")
    blob = bytearray(base64.b64decode(valid[8:]))
    blob[51] += 1
    blob[-8:-4] = struct.pack(">I", binascii.crc32(blob[:-8]) & 0xffffffff)
    encoded = base64.b64encode(blob)
    with pytest.raises(UprSettingsError, match="name length"):
        load(struct.pack(">II", 322, len(encoded))+encoded)
