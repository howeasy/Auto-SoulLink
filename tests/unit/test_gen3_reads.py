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
import sys
from pathlib import Path

import pytest

from server.adapters import gen3_codec as codec
from tests.unit.gen3_world import mon_record
from tests.unit.test_gen3_entry import FIXTURES, World, lua_to_py

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "tools"))
import gen3_reads_pydec as pydec  # noqa: E402

RR_SAV = FIXTURES / "rr_town.sav"
FR_SAV = FIXTURES / "firered_town.sav"

# nickname_raw / ot_name_raw are Python `bytes`; Lua returns the same bytes as an array
# under *_bytes. Everything else is compared by name.
RAW_PAIRS = {"nickname_raw": "nickname_bytes", "ot_name_raw": "ot_name_bytes"}


def test_instance_exports_shared_record_geometry_and_compressed_expander():
    world = World()
    module = world.Reads
    reads = module.new(world.lua.table_from(world.profile, recursive=True), world.io)
    assert reads.PARTY_MON_SIZE == module.PARTY_MON_SIZE
    assert reads.BOX_MON_SIZE == module.BOX_MON_SIZE
    assert world.lua.eval("function(a,b) return a == b end")(
        reads.expand_compressed_mon, module.expand_compressed_mon)


def test_rr_expansion_sets_the_binary_pinned_ribbon_bit_without_changing_identity():
    world = World()
    raw = bytes(range(codec.COMPRESSED_MON_SIZE))
    py = codec.expand_compressed_box_mon(raw)
    lua = bytes(lua_to_py(world.Reads.expand_compressed_mon(world.lua.table(*raw))))
    assert lua == py and py[0x4F] == 0x80
    assert py[:8] == raw[:8] and py[0x1C:0x20] == bytes(4)
    assert codec.decode_box_mon(py, rr=True)["ribbons"] == 0x80000000


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


# SetSaveBlocksPointers (pret/pokefirered src/load_save.c:68-78 at c75f3523) relocates
# gSaveBlock1Ptr / gSaveBlock2Ptr / gPokemonStoragePtr together by
# `Random() & ((SAVEBLOCK_MOVE_RANGE - 1) & ~3)` with SAVEBLOCK_MOVE_RANGE 128 (:15), so the
# live offset from the static base is 4-byte aligned and in [0, 124].
RELOC_OFFSETS = (0, 4, 64, 124)


def storage_pointer_address(world):
    """The pointer symbol as the pack ships it — from write_checkpoint, which is what
    Entry.build hands to reads."""
    pointers = lua_to_py(world.parts.write_checkpoint.pointers)
    return pointers["gPokemonStoragePtr"]["address"]


def place_box(world, offset, box_index=0, records=None):
    """Relocate gPokemonStorage by `offset` and put `records` in box `box_index`."""
    ram, derived = world.profile["ram"], world.profile["derived"]
    live = ram["POKEMON_STORAGE_BASE"] + offset
    world.poke(storage_pointer_address(world), live.to_bytes(4, "little"))
    if records is not None:
        start = (live + derived["BOX_DATA_OFFSET"]
                 + box_index * derived["MONS_PER_BOX"] * codec.BOX_MON_SIZE)
        world.poke(start, b"".join(records))
    return live


def test_the_storage_pointer_symbol_agrees_across_the_two_packs_that_ship_it():
    """write_checkpoint.pointers.gPokemonStoragePtr and profile.ram.PSP_PTR_ADDR are the same
    symbol; if they ever drift, reads would bind whichever it happened to prefer."""
    world = World(pack="gen3_frlg", title="firered")
    assert storage_pointer_address(world) == world.profile["ram"]["PSP_PTR_ADDR"]


def test_vanilla_read_box_follows_the_relocated_storage_pointer():
    """The static base is NEVER read: the records sit at base+offset and read_box finds them
    only because it dereferences gPokemonStoragePtr on the call."""
    world = World(pack="gen3_frlg", title="firered")
    rng = random.Random(7)
    mon = codec.decode_party_mon(rr_party_bytes()[1][:codec.PARTY_MON_SIZE], rr=True)
    records = []
    for _slot in range(codec.MONS_PER_BOX):
        mon["personality"] = rng.randrange(1 << 32)
        records.append(codec.encode_box_mon(mon, rr=False))

    for offset in RELOC_OFFSETS:
        place_box(world, offset, box_index=3, records=records)
        box = lua_to_py(world.parts.reads.read_box(3))
        assert len(box) == codec.MONS_PER_BOX
        for slot, raw in enumerate(records):
            expected = codec.decode_box_mon(raw)
            assert expected["checksum_ok"] is True
            assert box[slot]["box_index"] == 3 and box[slot]["slot"] == slot
            assert_same_mon(box[slot], expected)


def test_a_storage_pointer_outside_the_relocation_window_is_refused():
    world = World(pack="gen3_frlg", title="firered")
    base = world.profile["ram"]["POKEMON_STORAGE_BASE"]
    for bad, reason in ((base + 128, "relocation window"),   # one step past the range
                        (base + 0x1000, "relocation window"),
                        (base - 4, "relocation window"),
                        (base + 2, "word aligned"),          # Random() & ~3 cannot do this
                        (0, "null")):
        world.poke(storage_pointer_address(world), bad.to_bytes(4, "little"))
        box, why = world.parts.reads.read_box(0)
        assert box is None, f"pointer {bad:#010x} should be refused"
        assert reason in str(why), why
    # and the last accepted offset still works, so the bound is not off by one
    place_box(world, 124)
    assert lua_to_py(world.parts.reads.read_box(0)) != []


def test_vanilla_read_box_refuses_an_index_outside_the_pack():
    world = World(pack="gen3_frlg", title="firered")
    place_box(world, 0)
    boxes = world.profile["derived"]["BOXES_PER_STORE"]
    box, why = world.parts.reads.read_box(boxes)
    assert box is None and "outside profile" in str(why)


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


def test_a_null_or_unaligned_saveblock_pointer_is_refused():
    world = World(pack="gen3_frlg", title="firered")
    ptr, why = world.parts.reads.read_sb1()
    assert ptr is None and "null" in str(why)
    world.poke(world.profile["ram"]["SB1_PTR_ADDR"], (0x02025736).to_bytes(4, "little"))
    ptr, why = world.parts.reads.read_sb1()
    assert ptr is None and "word aligned" in str(why)


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


# ── P4 card C4-2a: trainer / location / badges / bag / battle ───────────────────────────
def _pointer_slot(world, symbol, ram_key):
    """The address reads.lua will actually dereference for `symbol`: write_checkpoint.pointers
    when the pack ships one (it wins over profile.ram -- lua/gen3/reads.lua pointer_address()),
    else the profile.ram fallback. gen3_rr's write_checkpoint pointer differs from its legacy
    ram.SB1_PTR_ADDR (the documented IntrMain_Buffer trap), so this must not assume they match."""
    checkpoint = getattr(world.parts, "write_checkpoint", None)
    if checkpoint is not None:
        pointers = lua_to_py(checkpoint.pointers)
        entry = pointers.get(symbol)
        if entry:
            return entry["address"]
    return world.profile["ram"][ram_key]


def place_sb1(world, addr, size=0x1200):
    world.poke(_pointer_slot(world, "gSaveBlock1Ptr", "SB1_PTR_ADDR"), addr.to_bytes(4, "little"))
    world.poke(addr, bytes(size))
    return addr


def place_sb2(world, addr, size=0x40):
    world.poke(_pointer_slot(world, "gSaveBlock2Ptr", "SB2_PTR_ADDR"), addr.to_bytes(4, "little"))
    world.poke(addr, bytes(size))
    return addr


def test_read_trainer_matches_pydec():
    world = World(pack="gen3_frlg", title="firered")
    derived = world.profile["derived"]
    sb2_addr = place_sb2(world, 0x0202402C)
    sb2 = bytearray(0x20)
    sb2[0:7] = codec.encode_name("ASH", 7)
    sb2[0x0A:0x0E] = (0x12345678).to_bytes(4, "little")
    world.poke(sb2_addr, bytes(sb2))

    got = lua_to_py(world.parts.reads.read_trainer())
    want = pydec.decode_trainer(bytes(sb2), derived["SB2_OT_ID_OFFSET"], derived["SB2_NAME_OFFSET"])
    assert got["ot_id"] == want["ot_id"] and got["name"] == want["name"]


def test_read_location_matches_pydec_and_is_signed():
    world = World(pack="gen3_frlg", title="firered")
    derived = world.profile["derived"]
    sb1_addr = place_sb1(world, 0x02025734)
    sb1 = bytearray(0x20)
    sb1[4], sb1[5] = 250, 3
    world.poke(sb1_addr, bytes(sb1))

    got = lua_to_py(world.parts.reads.read_location())
    want = pydec.decode_location(bytes(sb1), derived["SB1_LOCATION_MAP_GROUP_OFFSET"],
                                  derived["SB1_LOCATION_MAP_NUM_OFFSET"])
    assert got == want and got["map_group"] == -6


def test_read_badges_matches_pydec_badge_eight_only():
    world = World(pack="gen3_frlg", title="firered")
    derived = world.profile["derived"]
    sb1_addr = place_sb1(world, 0x02025734)
    sb1 = bytearray(0x1200)
    byte_addr = derived["SB1_FLAGS_OFFSET"] + derived["SB1_BADGE_BYTE_OFFSET"]
    sb1[byte_addr] = 0b10000000  # badge 8 only
    world.poke(sb1_addr, bytes(sb1))

    got = world.parts.reads.read_badges()
    assert got == pydec.decode_badges(0b10000000) == 0x80


def test_read_balls_matches_pydec_vanilla_encrypted():
    world = World(pack="gen3_frlg", title="firered")
    derived = world.profile["derived"]
    sb1_addr = place_sb1(world, 0x02025734)
    sb2_addr = place_sb2(world, 0x0202402C)
    key = 0xABCD1234
    world.poke(sb2_addr + derived["SB2_ENC_KEY_OFFSET"], (key & 0xFFFFFFFF).to_bytes(4, "little"))

    count = derived["SB1_BALL_POCKET_COUNT"]
    pocket = bytearray(count * 4)
    pocket[0:2] = (4).to_bytes(2, "little")
    pocket[2:4] = (37 ^ (key & 0xFFFF)).to_bytes(2, "little")
    for i in range(1, count):
        pocket[i * 4:i * 4 + 2] = (0).to_bytes(2, "little")   # ITEM_NONE
        pocket[i * 4 + 2:i * 4 + 4] = (999).to_bytes(2, "little")
    world.poke(sb1_addr + derived["SB1_BALL_POCKET_OFFSET"], bytes(pocket))

    got = lua_to_py(world.parts.reads.read_balls())
    want = pydec.decode_ball_pocket(bytes(pocket), count, key)
    assert got == want == {"ball_count": 37, "has_pokeballs": True}


def test_read_balls_matches_pydec_rr_unencrypted_and_ewram():
    world = World(pack="gen3_rr", title="radical_red")
    ram, derived = world.profile["ram"], world.profile["derived"]
    assert derived["BAG_IN_EWRAM"] is True and derived["BALL_POCKET_ENC"] is False
    count = derived["SB1_BALL_POCKET_COUNT"]
    pocket = bytearray(count * 4)
    pocket[0:2] = (1).to_bytes(2, "little")
    pocket[2:4] = (12).to_bytes(2, "little")
    world.poke(ram["BALL_POCKET_ADDR"], bytes(pocket))

    got = lua_to_py(world.parts.reads.read_balls())
    want = pydec.decode_ball_pocket(bytes(pocket), count, key=None)
    assert got == want == {"ball_count": 12, "has_pokeballs": True}


def test_rr_pack_gracefully_lacks_trainer_ot_id_today():
    """gen3_rr has no pret source and the old client never read SaveBlock2.playerTrainerId
    either (P4 card C4-2a addendum 4/5): read_trainer must refuse with a reason, not guess."""
    world = World(pack="gen3_rr", title="radical_red")
    value, why = world.parts.reads.read_trainer()
    assert value is None and "profile has no derived." in str(why)


def test_rr_location_and_badges_work_from_old_client_evidence():
    """SaveBlock1 location/badge offsets ARE evidenced for RR: the old client reads them
    generically off M.SB1_PTR_ADDR/M.SB1_FLAGS_OFFSET with no RR-specific branch
    (archive/gen3-old-client:lua/memory_gba.lua:271-273,1112-1114,1174-1181), so they now carry over to gen3_rr too."""
    world = World(pack="gen3_rr", title="radical_red")
    derived = world.profile["derived"]
    sb1_addr = place_sb1(world, 0x02026000)
    sb1 = bytearray(0x1200)
    sb1[4], sb1[5] = 12, 34
    byte_off = derived["SB1_FLAGS_OFFSET"] + derived["SB1_BADGE_BYTE_OFFSET"]
    sb1[byte_off] = 0b00000011
    world.poke(sb1_addr, bytes(sb1))

    location = lua_to_py(world.parts.reads.read_location())
    assert location == {"map_group": 12, "map_num": 34}
    assert world.parts.reads.read_badges() == 0b00000011


def test_read_battle_vanilla_in_battle_via_gmain_bit():
    world = World(pack="gen3_frlg", title="firered")
    ram, derived = world.profile["ram"], world.profile["derived"]
    world.bus[ram["GMAIN_ADDR"] + derived["GMAIN_INBATTLE_OFFSET"]] = derived["GMAIN_INBATTLE_MASK"]
    world.bus[ram["BATTLE_TYPE_ADDR"]] = derived["BATTLE_TYPE_TRAINER_MASK"] | derived["BATTLE_TYPE_DOUBLE_MASK"]
    world.bus[ram["TRAINER_OPPONENT_ADDR"]] = 0x2A

    battle = lua_to_py(world.parts.reads.read_battle())
    assert battle["in_battle"] is True
    assert battle["is_trainer"] is True and battle["is_doubles"] is True
    assert battle["trainer_id"] == 0x2A
    assert battle["enemy_party"] == []


def test_read_battle_vanilla_not_in_battle():
    world = World(pack="gen3_frlg", title="firered")
    ram = world.profile["ram"]
    world.bus[ram["GMAIN_ADDR"] + world.profile["derived"]["GMAIN_INBATTLE_OFFSET"]] = 0
    battle = lua_to_py(world.parts.reads.read_battle())
    assert battle["in_battle"] is False


def test_read_battle_rr_in_battle_via_battle_mons_hp():
    """RR/CFRU has no reliable gMain (ram.GMAIN_ADDR is null in the pack), so read_battle must
    take the OVERWORLD_MODE == 'battle_outcome' branch: gBattleMons[0].maxHP > 0 and
    gBattleOutcome == 0 (archive/gen3-old-client:lua/memory_gba.lua M.isInBattle, the production-proven RR detector)."""
    world = World(pack="gen3_rr", title="radical_red")
    ram, derived = world.profile["ram"], world.profile["derived"]
    assert ram["GMAIN_ADDR"] is None and derived["OVERWORLD_MODE"] == "battle_outcome"
    Reads = world.Reads
    max_hp_off = ram["BATTLE_MONS_ADDR"] + Reads.BATTLE_MON_HP_OFF + 4
    world.bus[max_hp_off] = 100      # maxHP low byte
    world.bus[max_hp_off + 1] = 0
    world.bus[ram["BATTLE_OUTCOME_ADDR"]] = 0

    battle = lua_to_py(world.parts.reads.read_battle())
    assert battle["in_battle"] is True

    world.bus[ram["BATTLE_OUTCOME_ADDR"]] = derived["OUTCOME_CAUGHT"]
    battle = lua_to_py(world.parts.reads.read_battle())
    assert battle["in_battle"] is False
    assert battle["outcome"] == derived["OUTCOME_CAUGHT"]
    # RR's battle-type masks are old-client-evidenced (addendum 4/5), so these are present too.
    assert battle["is_trainer"] is False and battle["is_doubles"] is False


def test_read_battle_doubles_battler_mapping_and_enemy_party():
    world = World(pack="gen3_frlg", title="firered")
    ram = world.profile["ram"]
    world.bus[ram["BATTLERS_COUNT_ADDR"]] = 4
    # battler0 (party slot 0) and battler2 (party slot 1) are the player's active mons.
    world.bus[ram["BATTLER_PARTY_INDEXES_ADDR"] + 0] = 0
    world.bus[ram["BATTLER_PARTY_INDEXES_ADDR"] + 4] = 1

    _, blob = rr_party_bytes()
    mon = codec.decode_party_mon(blob[:codec.PARTY_MON_SIZE], rr=True)
    raw = codec.encode_party_mon(mon, rr=False)
    # ENEMY_COUNT_ADDR is deliberately left at its boot 0: the engine never maintains it in
    # battle (pret calls CalculateEnemyPartyCount only from trade.c), so a read gated on it
    # returns {} on hardware. See test_read_enemy_party_scans_occupancy_* below.
    world.poke(ram["ENEMY_BASE"], raw)

    battle = lua_to_py(world.parts.reads.read_battle())
    assert battle["battlers_count"] == 4
    assert battle["active_player_battler_slots"] == [0, 1]
    assert len(battle["enemy_party"]) == 1
    assert_same_mon(battle["enemy_party"][0], codec.decode_party_mon(raw))


# ── read_enemy_party: occupancy, not gEnemyPartyCount ────────────────────────────────────────
# Item 15 (docs/protocol.md:548) failed live on the new client: every in-battle tick carried
# `enemy_party: []`. The cause was the port dropping the old client's scan
# (archive/gen3-old-client:lua/memory_gba.lua:1545-1553) for a loop bounded by ram.ENEMY_COUNT_ADDR -- a byte the engine
# never maintains in battle (pret writes gEnemyPartyCount only from CalculateEnemyPartyCount,
# src/pokemon.c:3756-3767, called only from trade.c:942,1139). These cases pin the occupancy
# rule and the tail terminator that replaced it.

def enemy_records(*specs):
    """Encoded vanilla party records for the enemy array, in slot order."""
    return [codec.encode_party_mon(mon_record(personality=pid, ot_id=0x0BADF00D, species=sp,
                                              max_hp=mhp), rr=False)
            for pid, sp, mhp in specs]


def test_read_enemy_party_scans_occupancy_when_the_engine_count_is_zero():
    """The live FRLG condition: gEnemyPartyCount reads 0 through the whole battle, so the read
    must find the foe by occupancy or return nothing (this is the item-15 regression)."""
    world = World(pack="gen3_frlg", title="firered")
    ram = world.profile["ram"]
    assert world.bus.get(ram["ENEMY_COUNT_ADDR"], 0) == 0      # boot value, never written
    (foe,) = enemy_records((0x11223344, 19, 20))
    world.poke(ram["ENEMY_BASE"], foe)

    battle = lua_to_py(world.parts.reads.read_battle())
    assert len(battle["enemy_party"]) == 1
    assert battle["enemy_party"][0]["species"] == 19
    assert battle["enemy_party"][0]["max_hp"] == 20


def test_read_enemy_party_ignores_a_stale_count_below_the_real_party():
    """A stale non-zero count (the RR patch's staging writes one, handlers.c:1813-1820) must not
    truncate the team it no longer describes."""
    world = World(pack="gen3_frlg", title="firered")
    ram = world.profile["ram"]
    world.bus[ram["ENEMY_COUNT_ADDR"]] = 1                     # stale: the party below is two
    world.poke(ram["ENEMY_BASE"], b"".join(enemy_records((0x11223344, 19, 20),
                                                        (0x55667788, 25, 24))))

    party = lua_to_py(world.parts.reads.read_enemy_party())
    assert [m["species"] for m in party] == [19, 25]
    assert [m["slot"] for m in party] == [0, 1]


def test_read_enemy_party_stops_at_the_terminator_for_a_two_mon_trainer_party():
    """ZeroEnemyPartyMons clears all six slots before a trainer party is written, so a two-mon
    party has a zeroed tail: exactly two, no garbage decode past it. A slot with a species but
    maxHP 0 terminates too (the companion patch zeroes maxHP on trailing slots, not species)."""
    world = World(pack="gen3_frlg", title="firered")
    ram = world.profile["ram"]
    two = enemy_records((0x11223344, 19, 20), (0x55667788, 25, 24))
    tail = codec.encode_party_mon(mon_record(personality=0x99AABBCC, ot_id=0x0BADF00D,
                                             species=31, max_hp=0), rr=False)
    world.poke(ram["ENEMY_BASE"], b"".join(two + [tail]))

    party = lua_to_py(world.parts.reads.read_enemy_party())
    assert [m["species"] for m in party] == [19, 25]
