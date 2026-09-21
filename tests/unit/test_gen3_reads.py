"""gen3-P3-C3-1 (MODEL): lua/gen3/reads.lua against the PYDEC oracle.

`server/adapters/gen3_codec.py` is the independent Python decoder (PLAN §5.7). Every case
below decodes the SAME raw bytes twice — once in Lua through the production `Entry.build`
graph, once in Python — and requires the two to agree field for field. Bytes come from the
committed battery-save fixtures wherever a fixture carries the record, and from the oracle's
own encoder where none does (`firered_town.sav` has an empty party and empty boxes, so the
vanilla ENCRYPTED path has no fixture record to read; that is stated, not papered over).
"""
from __future__ import annotations

import random

import pytest

from server.adapters import gen3_codec as codec
from tests.unit.test_gen3_entry import FIXTURES, World, lua_to_py

RR_SAV = FIXTURES / "rr_town.sav"
FR_SAV = FIXTURES / "firered_town.sav"

# nickname_raw / ot_name_raw are Python `bytes`; Lua returns the same bytes as an array
# under *_bytes. Everything else is compared by name.
RAW_PAIRS = {"nickname_raw": "nickname_bytes", "ot_name_raw": "ot_name_bytes"}


def assert_same_mon(lua_mon, py_mon):
    got = lua_to_py(lua_mon) if not isinstance(lua_mon, dict) else lua_mon
    for key, value in py_mon.items():
        if key in RAW_PAIRS:
            assert got[RAW_PAIRS[key]] == list(value), key
        elif value is None:
            assert key not in got, f"{key} should be absent, got {got.get(key)!r}"
        else:
            assert got[key] == value, key


def rr_party_bytes(path=RR_SAV):
    sb1 = codec.parse_flash(path.read_bytes(), cfru=True)["sb1"]
    count = sb1[codec.SB1_PARTY_COUNT_OFFSET]
    start = codec.SB1_PARTY_OFFSET
    return count, sb1[start:start + count * codec.PARTY_MON_SIZE]


def fr_storage_bytes():
    return codec.parse_flash(FR_SAV.read_bytes())["storage"]


def test_the_charmap_agrees_with_pydec_on_every_byte():
    """The one glyph table: all 256 bytes, each as a one-glyph name, plus a terminated one."""
    world = World()
    reads = world.parts.reads
    for byte in range(256):
        raw = bytes([byte, 0xFF, 0x00])
        got = str(reads.decode_name(world.lua.table(*raw)))
        assert got == codec.decode_name(raw), f"byte 0x{byte:02X}"
    whole = bytes(range(0, 255))       # no terminator: every glyph in one string
    assert str(reads.decode_name(world.lua.table(*whole))) == codec.decode_name(whole)


def test_rr_party_record_from_the_fixture_matches_pydec():
    """Radical Red: fixed substruct order, unencrypted, no BoxPokemon checksum."""
    world = World(pack="gen3_rr", title="radical_red", kind="companion")
    count, blob = rr_party_bytes()
    assert count == 1, "the fixture's party is the record under test"
    raw = blob[:codec.PARTY_MON_SIZE]
    assert_same_mon(world.parts.reads.decode_party_mon(world.lua.table(*raw)),
                    codec.decode_party_mon(raw, rr=True))


def test_rr_read_party_walks_the_profile_addresses():
    world = World(pack="gen3_rr", title="radical_red")
    ram = world.profile["ram"]
    count, blob = rr_party_bytes()
    world.bus[ram["PARTY_COUNT_ADDR"]] = count
    world.poke(ram["PARTY_BASE"], blob)

    party = lua_to_py(world.parts.reads.read_party())
    assert len(party) == count
    assert party[0]["slot"] == 0
    assert_same_mon(party[0], codec.rr_party_from_save(RR_SAV.read_bytes())[0])
    assert party[0]["nickname"] == "Treecko"
    key = str(world.parts.reads.key(world.parts.reads.decode_party_mon(
        world.lua.table(*blob[:codec.PARTY_MON_SIZE]))))
    assert key == f"{party[0]['personality']:08X}:{party[0]['ot_id']:08X}"


def test_vanilla_encrypted_party_record_matches_pydec():
    """FR/LG: the 48-byte secure block is XOR'd with personality^otId and the four substructs
    are permuted by personality % 24. The committed FireRed fixture has an EMPTY party, so
    the record here is the fixture's RR mon re-encoded by the oracle into vanilla form — the
    bytes are the oracle's, the decode is Lua's."""
    world = World(pack="gen3_frlg", title="firered")
    _, blob = rr_party_bytes()
    mon = codec.decode_party_mon(blob[:codec.PARTY_MON_SIZE], rr=True)
    hits = 0
    for personality in (mon["personality"], 0, 1, 23, 24, 0xFFFFFFFF):
        mon["personality"] = personality
        raw = codec.encode_party_mon(mon, rr=False)
        expected = codec.decode_party_mon(raw, rr=False)
        assert expected["checksum_ok"] is True
        assert_same_mon(world.parts.reads.decode_party_mon(world.lua.table(*raw)), expected)
        hits += 1
    assert hits == 6


def test_vanilla_box_records_from_the_fixture_match_pydec():
    """The FireRed fixture's boxes are empty, so these are all-zero 80-byte records: the
    decrypt/permute/checksum path still has to agree with the oracle on them."""
    world = World(pack="gen3_frlg", title="firered")
    storage = fr_storage_bytes()
    for slot in (0, 1, 29, 30):
        start = codec.BOX_DATA_OFFSET + slot * codec.BOX_MON_SIZE
        raw = storage[start:start + codec.BOX_MON_SIZE]
        assert_same_mon(world.parts.reads.decode_box_mon(world.lua.table(*raw)),
                        codec.decode_box_mon(raw))


def test_a_wrong_length_record_is_refused_not_guessed():
    world = World()
    reads = world.parts.reads
    mon, why = reads.decode_party_mon(world.lua.table(*bytes(80)))
    assert mon is None and "length disagrees" in str(why)
    mon, why = reads.decode_box_mon(world.lua.table(*bytes(100)))
    assert mon is None and "length disagrees" in str(why)


def test_compressed_box_records_expand_exactly_like_pydec():
    """RR stores 0x3A-byte CompressedPokemon in its boxes; no committed fixture carries a
    boxed RR mon (tests/fixtures/gen3/README.md), so the records are pseudo-random blobs
    put through both implementations of the same pure byte transform."""
    world = World(pack="gen3_rr", title="radical_red")
    rng = random.Random(20260921)
    for _ in range(16):
        raw = bytes(rng.randrange(256) for _ in range(codec.COMPRESSED_MON_SIZE))
        expanded = lua_to_py(world.Reads.expand_compressed_mon(world.lua.table(*raw)))
        assert bytes(expanded) == codec.expand_compressed_box_mon(raw)
    short, why = world.Reads.expand_compressed_mon(world.lua.table(*bytes(10)))
    assert short is None and "length disagrees" in str(why)


def test_rr_read_box_decodes_thirty_compressed_slots():
    world = World(pack="gen3_rr", title="radical_red")
    derived = world.profile["derived"]
    rng = random.Random(4)
    records = [bytes(rng.randrange(256) for _ in range(codec.COMPRESSED_MON_SIZE))
               for _ in range(codec.MONS_PER_BOX)]
    world.poke(derived["CFRU_BOX_BASES"][0], b"".join(records))

    box = lua_to_py(world.parts.reads.read_box(0))
    assert len(box) == codec.MONS_PER_BOX
    for slot, record in enumerate(records):
        expected = codec.decode_box_mon(codec.expand_compressed_box_mon(record), rr=True)
        assert box[slot]["slot"] == slot and box[slot]["box_index"] == 0
        assert_same_mon(box[slot], expected)


def test_rr_read_box_refuses_an_index_outside_the_pack():
    world = World(pack="gen3_rr", title="radical_red")
    boxes = len(world.profile["derived"]["CFRU_BOX_BASES"])
    box, why = world.parts.reads.read_box(boxes)
    assert box is None and "outside profile" in str(why)
    box, why = world.parts.reads.read_box(-1)
    assert box is None and "non-negative" in str(why)


def test_vanilla_read_box_refuses_because_the_pack_names_no_storage_base():
    """FRLG's gPokemonStorage base is NOT in data/games/gen3_frlg/profile.json today, so the
    read refuses by name instead of inventing an address."""
    world = World(pack="gen3_frlg", title="firered")
    box, why = world.parts.reads.read_box(0)
    assert box is None
    assert "POKEMON_STORAGE_BASE" in str(why)


def test_saveblock_pointers_are_dereferenced_every_call():
    world = World(pack="gen3_frlg", title="firered")
    ram = world.profile["ram"]
    world.poke(ram["SB1_PTR_ADDR"], (0x02025734).to_bytes(4, "little"))
    world.poke(ram["SB2_PTR_ADDR"], (0x0202402C).to_bytes(4, "little"))
    assert int(world.parts.reads.read_sb1()) == 0x02025734
    assert int(world.parts.reads.read_sb2()) == 0x0202402C
    # the engine relocates the block; the next call must see the new pointer
    world.poke(ram["SB1_PTR_ADDR"], (0x02026000).to_bytes(4, "little"))
    assert int(world.parts.reads.read_sb1()) == 0x02026000


def test_a_null_saveblock_pointer_is_refused():
    world = World(pack="gen3_frlg", title="firered")
    ptr, why = world.parts.reads.read_sb1()
    assert ptr is None and "null" in str(why)


def test_read_party_refuses_a_count_above_capacity():
    world = World(pack="gen3_rr", title="radical_red")
    world.bus[world.profile["ram"]["PARTY_COUNT_ADDR"]] = 7
    party, why = world.parts.reads.read_party()
    assert party is None and "exceeds capacity" in str(why)


@pytest.mark.parametrize("pack,title,rr", [
    ("gen3_frlg", "firered", False),
    ("gen3_frlg", "leafgreen", False),
    ("gen3_rr", "radical_red", True),
])
def test_the_encryption_mode_comes_from_the_pack(pack, title, rr):
    world = World(pack=pack, title=title)
    assert bool(world.parts.reads.rr) is rr
