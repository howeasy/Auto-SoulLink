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
