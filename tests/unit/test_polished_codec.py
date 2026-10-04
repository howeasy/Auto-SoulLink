"""Polished Crystal codec (server/adapters/polished_codec.py): party/savemon round trips, the NEWBOX.md
§3.3 checksum vector, Bad-Egg detection, and the struct offsets re-read from the pinned build's .sym."""
import random
import re
from pathlib import Path

import pytest

from server.adapters import polished_codec as pc

SYM = Path(__file__).resolve().parents[2] / "data" / "polished" / "polishedcrystal.sym"


def _sym_offsets(prefix):
    rows = re.findall(rf"^[0-9a-f]{{2}}:([0-9a-f]{{4}}) {prefix}(\w+)$", SYM.read_text(encoding="utf-8"), re.M)
    if not rows:
        pytest.skip("pinned Polished .sym absent")
    addresses = {name: int(addr, 16) for addr, name in rows}
    return {name: addr - addresses["Species"] for name, addr in addresses.items()}


def test_party_offsets_match_the_built_rom():
    sym = _sym_offsets("wPartyMon1")
    assert {k: sym[k] for k in pc.PARTY} == pc.PARTY


def test_savemon_offsets_match_the_built_rom():
    sym = _sym_offsets("sBoxMons1AMon1")
    assert {k: sym[k] for k in pc.SAVEMON} == pc.SAVEMON


def _hand_entry():
    entry = bytearray(pc.SAVEMON_SIZE)
    entry[0], entry[28] = 0x01, 0x05
    entry[32:] = pc.encode_name_bytes(bytes([0x80] + [pc.TERMINATOR] * 9 + [0x81] + [pc.TERMINATOR] * 6))
    return bytes(entry)


def test_newbox_hand_vector():
    entry = _hand_entry()
    assert entry[32:].hex(" ").upper() == "00 7B 7B 7B 7B 7B 7B 7B 7B 7B 01 7B 7B 7B 7B 7B 7B"
    assert pc.checksum(entry) == 0x32D1
    sealed = pc.seal(entry)
    assert sealed[32:].hex(" ").upper() == "00 7B FB FB 7B 7B FB 7B FB FB 01 FB 7B 7B 7B FB 7B"
    assert pc.verify(sealed) and not pc.verify(entry)
    mon = pc.decode_savemon(sealed)
    assert (mon["species_id"], mon["level"], mon["nickname"], mon["ot_name"]) == (1, 5, "A", "B")


def _random_savemon(rng):
    entry = bytearray(rng.randrange(256) for _ in range(pc.SAVEMON_SIZE))
    entry[0], entry[28] = rng.randrange(1, 256), rng.randrange(1, 101)
    return pc.seal(bytes(entry))


def test_savemon_round_trip():
    rng = random.Random(3)
    for _ in range(200):
        sealed = _random_savemon(rng)
        assert pc.encode_savemon(pc.decode_savemon(sealed, name_decoder=None)) == sealed


@pytest.mark.parametrize("index", [0, 21, 31, 32, 48])
def test_a_flipped_bit_is_a_bad_egg(index):
    sealed = pc.seal(_hand_entry())
    bad = bytearray(sealed)
    bad[index] ^= 0x80 if index == 48 else 0x01
    assert not pc.verify(bytes(bad))
    with pytest.raises(ValueError, match="Bad Egg"):
        pc.decode_savemon(bytes(bad))


def _party_blob(rng):
    raw = bytearray(rng.randrange(256) for _ in range(pc.PARTY_SIZE))
    raw[0], raw[31] = rng.randrange(1, 256), rng.randrange(1, 101)
    ot = pc.encode_text("Kris", 8) + bytes(rng.randrange(256) for _ in range(3))
    return bytes(raw) + ot + pc.encode_text("Chicory", 11)


def test_party_round_trip():
    rng = random.Random(7)
    for _ in range(200):
        blob = _party_blob(rng)
        mon = pc.decode_party_blob(blob)
        assert (mon["ot_name"], mon["nickname"]) == ("Kris", "Chicory")
        assert pc.encode_party_blob(mon) == blob
        assert pc.encode_party_mon(pc.decode_party_mon(blob[:48])) == blob[:48]


def test_party_fields_and_key():
    raw = bytearray(pc.PARTY_SIZE)
    raw[0], raw[21] = 288 & 0xFF, 0x80 | 0x20 | 0x02     # ext species bit -> 288, female, form 2
    raw[20] = 0x80 | 0x40 | 0x07                          # shiny, ability slot 2, nature 7
    raw[6:8], raw[17:20], raw[31] = b"\x12\x34", b"\xab\xcd\xef", 50
    raw[22] = 0xC0 | 35
    mon = pc.decode_party_mon(bytes(raw))
    assert (mon["species_id"], mon["form"], mon["gender"], mon["is_egg"]) == (288, 2, "female", False)
    assert (mon["shiny"], mon["ability_slot"], mon["nature"]) == (True, 2, 7)
    assert mon["dvs"] == {"hp": 10, "attack": 11, "defense": 12, "speed": 13,
                          "special_attack": 14, "special_defense": 15}
    assert (mon["pp"][0], mon["pp_ups"][0]) == (35, 3)
    assert pc.key(mon) == "ABCDEF:1234:120:C2"
    mon["is_egg"] = True                                   # hatching is not a new identity
    assert pc.key(mon) == "ABCDEF:1234:120:C2"


def test_contradictory_fields_are_refused():
    mon = pc.decode_party_mon(bytes(_party_blob(random.Random(1))[:48]))
    mon["dv_bytes"] ^= 1
    with pytest.raises(ValueError, match="contradictory DV"):
        pc.encode_party_mon(mon)


def test_name_substitutions_for_space_terminator_and_start():
    assert pc.encode_name_bytes(bytes([0x7F, 0x53, 0x00])) == bytes([0x7A, 0x7B, 0x7C])
    assert pc.decode_name_bytes(bytes([0xFA, 0xFB, 0xFC])) == bytes([0x7F, 0x53, 0x00])


def test_a_party_blob_converts_to_a_sealed_savemon():
    rng = random.Random(7)
    raw = bytearray(rng.randrange(256) for _ in range(pc.BLOB_SIZE))
    raw[0], raw[21] = 25, 0x00                       # Pikachu, plain form
    raw[31] = 12                                     # level
    raw[pc.PARTY_SIZE + 7] = pc.TERMINATOR           # OT name terminated inside its 8 bytes
    raw[pc.PARTY_SIZE + pc.NAME_SIZE + 5:] = bytes([pc.TERMINATOR] * (pc.NICKNAME_SIZE - 5))
    blob = bytes(raw)
    mon = pc.decode_party_blob(blob)
    entry = pc.party_to_savemon(mon)
    assert pc.verify(entry)
    assert entry[0:22] == blob[0:22]
    assert entry[22] == sum((blob[22 + i] >> 6) << 2 * i for i in range(4))
    assert entry[23:29] == blob[26:32]
    assert entry[29:32] == blob[pc.PARTY_SIZE + 8:pc.PARTY_SIZE + 11]
    assert pc.decode_savemon(entry)["level"] == 12


def test_a_renamed_text_field_must_agree_with_the_raw_bytes():
    mon = pc.decode_savemon(pc.seal(_hand_entry()))
    renamed = dict(mon, nickname="STAR")
    with pytest.raises(ValueError, match="disagree"):
        pc.encode_savemon(renamed)
    text_only = {k: v for k, v in renamed.items() if k != "nickname_raw_hex"}
    out = pc.encode_savemon(text_only)
    assert pc.decode_savemon(out)["nickname"] == "STAR"


def test_a_hand_built_party_mon_may_omit_dv_bytes():
    blob = bytearray(pc.BLOB_SIZE)
    blob[0], blob[31] = 1, 5
    mon = pc.decode_party_blob(bytes(blob))
    hand = {k: v for k, v in mon.items() if k != "dv_bytes"}
    assert pc.encode_party_mon(hand) == pc.encode_party_mon(mon)


def test_glyph_table_is_immutable_and_a_missing_charmap_is_a_value_error(monkeypatch, tmp_path):
    with pytest.raises(TypeError):
        pc.glyphs()[83] = "Z"
    pc.glyphs.cache_clear()
    pc._reverse.cache_clear()
    monkeypatch.setattr(pc, "CHARMAP", tmp_path / "nope.lua")
    try:
        with pytest.raises(ValueError, match="unreadable"):
            pc.glyphs()
    finally:
        pc.glyphs.cache_clear()
        pc._reverse.cache_clear()
