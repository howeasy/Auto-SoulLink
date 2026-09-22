"""Independent Lua decoder vectors; SOURCE/MODEL only, never played-save proof.

No import of the independently authored Python Gen 2 codec. Expected bytes are
laid out directly from pinned pret macros/constants and include unequal words
to expose endianness, split Special, slot, and name-block mistakes.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
READS = ROOT / "lua/gen2/reads.lua"
TITLES = ("crystal", "gold", "silver")


@pytest.fixture(autouse=True)
def isolate_data_dir():
    """These pure tests do not import server state or create disk data."""
    yield


def profile_for(title):
    return json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text(encoding="utf-8"))["titles"][title]


def vector():
    record = bytearray(48)
    record[0:6] = bytes((25, 146, 1, 33, 166, 237))
    record[6:8] = b"\x12\x34"
    record[8:11] = b"\x01\x02\x03"
    record[11:21] = bytes.fromhex("0102030405060708090a")
    record[21:23] = b"\xab\xcd"
    record[23:27] = bytes((0, 0x41, 0x82, 0xFF))
    record[27:32] = bytes((200, 0x32, 0x91, 0x27, 51))
    record[32:34] = b"\x88\x7f"
    record[34:48] = struct.pack(">7H", 0x123, 0x456, 0x1234, 0x2345, 0x3456, 0x4567, 0x5678)
    return bytes(record)


OT = bytes((0x80, 0x50, *([0xAA] * 9)))
NICKNAME = bytes((0x81, 0x82, 0x50, *([0xBB] * 8)))


def expected_record(*, party=True, egg=False):
    result = {
        "species_id": 25, "species_marker": 253 if egg else 25, "is_egg": egg,
        "held_item": 146, "moves": [1, 33, 166, 237], "ot_id": 0x1234, "exp": 0x010203,
        "stat_exp": {"hp": 0x0102, "attack": 0x0304, "defense": 0x0506, "speed": 0x0708, "special": 0x090A},
        "dv_word": 0xABCD, "dvs": {"attack": 10, "defense": 11, "speed": 12, "special": 13, "hp": 5},
        "pp": [0, 1, 2, 63], "pp_ups": [0, 1, 2, 3], "happiness": 200, "pokerus": 0x32,
        "aux_bytes_hex": "9127", "level": 51, "raw_hex": vector()[:48 if party else 32].hex(),
    }
    if party:
        result.update(status=0x88, hp=0x123, max_hp=0x456,
                      stats={"attack": 0x1234, "defense": 0x2345, "speed": 0x3456,
                             "special_attack": 0x4567, "special_defense": 0x5678})
    return result


def block(*, party, count=1, species=25, egg=False):
    capacity, stride = (6, 48) if party else (20, 32)
    records = capacity + 2
    ots = records + capacity * stride
    nicks = ots + capacity * 11
    size = nicks + capacity * 11 + (0 if party else 2)
    data = bytearray([0xEE] * size)
    data[0] = count
    data[count + 1] = 255
    for slot in range(count):
        data[1 + slot] = 253 if egg else species
        record = bytearray(vector()[:stride])
        record[0] = species
        data[records + slot * stride:records + (slot + 1) * stride] = record
        data[ots + slot * 11:ots + (slot + 1) * 11] = OT
        data[nicks + slot * 11:nicks + (slot + 1) * 11] = NICKNAME
    return bytes(data)


def py(value):
    if hasattr(value, "items"):
        items = list(value.items())
        if all(isinstance(key, int) for key, _ in items):
            assert sorted(key for key, _ in items) == list(range(1, len(items) + 1))
            return [py(value[i]) for i in range(1, len(items) + 1)]
        return {key: py(item) for key, item in items}
    return value


class World:
    def __init__(self, title="crystal", name_decoder=None, profile=None):
        self.profile = profile if profile is not None else profile_for(title)
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.module = self.lua.eval("dofile")(READS.as_posix())
        self.bus = bytearray(65536)
        self.cart = bytearray(65536 if title == "crystal" else 32768)
        self.calls = []
        self.bank_calls = []
        self.bank_answers = []
        self.bank_ok = True
        self.read_override = None
        self.size_override = None
        make_io = self.lua.eval("""function(read, bank, size)
            return {read_range=function(a,n,d) return read(a,n,d) end,
                    bank_valid=function(b,a,n) return bank(b,a,n) end,
                    domain_size=function(d) return size(d) end, cart_ram_linear=true}
            end""")
        self.io = make_io(self.read_range, self.bank_valid, self.domain_size)
        decoder = None
        if name_decoder:
            decoder = self.lua.eval("function(f) return function(b) return f(b) end end")(name_decoder)
        self.lua_profile = self.lua.table_from(self.profile, recursive=True)
        self.reader = self.module.new(self.lua_profile, self.io, decoder)

    def bytes(self, value):
        return self.lua.table_from(list(value))

    def read_range(self, address, length, domain):
        self.calls.append((domain, address, length))
        if self.read_override:
            return self.read_override(address, length, domain)
        source = self.bus if domain == "System Bus" else self.cart if domain == "CartRAM" else None
        assert source is not None
        assert 0 <= address <= address + length <= len(source)
        return self.bytes(source[address:address + length])

    def bank_valid(self, bank, address, length):
        self.bank_calls.append((bank, address, length))
        if self.bank_answers:
            return self.bank_answers.pop(0)
        return self.bank_ok

    def domain_size(self, domain):
        assert domain == "CartRAM"
        return self.size_override if self.size_override is not None else len(self.cart)

    def put_party(self, raw):
        base = self.profile["ram"]["wPartyCount"]
        self.bus[base:base + len(raw)] = raw

    def put_box(self, raw, index=None):
        if index is None:
            bank, address = self.profile["sram_bank"]["sBox"], self.profile["ram"]["sBox"]
        else:
            row = self.profile["storage_boxes"][index]
            bank, address = row["bank"], row["addr"]
        flat = bank * 8192 + address - 40960
        self.cart[flat:flat + len(raw)] = raw
        return flat


def error(result, contains):
    assert isinstance(result, tuple) and len(result) == 2 and result[0] is None
    assert contains in result[1]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("party", [True, False])
@pytest.mark.parametrize("egg", [True, False])
def test_independent_record_vector(title, party, egg):
    world = World(title)
    result = world.reader.decode_record(world.bytes(vector()[:48 if party else 32]),
                                        "party" if party else "box", 253 if egg else 25)
    assert py(result) == expected_record(party=party, egg=egg)
    assert world.calls == []


def test_hp_dv_uses_all_four_low_bits_and_pp_covers_every_packed_value():
    world = World()
    for low_bits in range(16):
        raw = bytearray(vector())
        raw[21] = (8 + ((low_bits >> 3) & 1)) * 16 + 10 + ((low_bits >> 2) & 1)
        raw[22] = (12 + ((low_bits >> 1) & 1)) * 16 + 14 + (low_bits & 1)
        assert world.reader.decode_record(world.bytes(raw), "party", 25)["dvs"]["hp"] == low_bits
    for packed in range(256):
        raw = bytearray(vector())
        raw[23:27] = bytes([packed] * 4)
        result = world.reader.decode_record(world.bytes(raw), "party", 25)
        assert py(result["pp"]) == [packed & 0x3F] * 4
        assert py(result["pp_ups"]) == [packed >> 6] * 4


@pytest.mark.parametrize("title", TITLES)
def test_transfer_names_remain_exact_without_assuming_a_charmap(title):
    world = World(title)
    blob = vector() + OT + NICKNAME
    result = py(world.reader.decode_transfer_blob(world.bytes(blob), 253))
    assert result == {**expected_record(egg=True), "ot_raw_hex": OT.hex(), "nickname_raw_hex": NICKNAME.hex()}
    assert world.reader.transfer_blob_size == 70
    for bad in (blob[:-1], blob + b"\x00"):
        error(world.reader.decode_transfer_blob(world.bytes(bad), 253), "48+11+11")


def test_injected_name_decoder_is_optional_and_receives_a_copy():
    def decoder(raw):
        raw[1] = 0
        return "decoded"
    world = World(name_decoder=decoder)
    result = py(world.reader.decode_transfer_blob(world.bytes(vector() + OT + NICKNAME), 25))
    assert result["ot_name"] == result["nickname"] == "decoded"
    assert result["ot_raw_hex"] == OT.hex()
    assert result["nickname_raw_hex"] == NICKNAME.hex()
    failed = World(name_decoder=lambda _: None)
    error(failed.reader.decode_transfer_blob(failed.bytes(vector() + OT + NICKNAME), 25), "decoder unavailable")


@pytest.mark.parametrize("raw,kind,marker,message", [
    (vector()[:-1], "party", 25, "record bytes"),
    (vector(), "unknown", 25, "record kind"),
    (vector(), "party", None, "marker required"),
    (vector(), "party", 252, "marker required"),
    (vector(), "party", 26, "mismatch"),
    (bytes([253]) + vector()[1:], "party", 253, "record species"),
    (bytes([0]) + vector()[1:], "party", 25, "record species"),
])
def test_malformed_record_refusal(raw, kind, marker, message):
    world = World()
    error(world.reader.decode_record(world.bytes(raw), kind, marker), message)


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("level,valid", [(0, False), (101, False), (255, False), (1, True), (100, True)])
@pytest.mark.parametrize("shape", ["party_record", "box_record", "party", "box", "active_box", "transfer"])
def test_source_level_bounds_across_records_and_occupied_containers(title, level, valid, shape):
    world = World(title)
    if shape in ("party_record", "box_record", "transfer"):
        raw = bytearray(vector()[:32 if shape == "box_record" else 48])
        raw[31] = level
        if shape == "transfer":
            result = world.reader.decode_transfer_blob(world.bytes(raw + OT + NICKNAME), 253)
        else:
            result = world.reader.decode_record(world.bytes(raw), "box" if shape == "box_record" else "party", 253)
    else:
        party = shape == "party"
        raw = bytearray(block(party=party, egg=True))
        raw[(8 if party else 22) + 31] = level
        if shape == "party":
            world.put_party(raw)
            result = world.reader.read_party()
        elif shape == "box":
            world.put_box(raw, 13)
            result = world.reader.read_storage_box(13)
        else:
            world.put_box(raw[:-2])
            result = world.reader.read_active_box()
    if not valid:
        error(result, "level")
    else:
        decoded = py(result)
        mon = decoded if "species_id" in decoded else decoded["mons"][0]
        assert mon["level"] == level and mon["is_egg"] is True


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("count", [0, 1, 6])
def test_party_reads_use_one_bounded_system_bus_range_with_explicit_bank_proof(title, count):
    world = World(title)
    raw = block(party=True, count=count, egg=True)
    world.put_party(raw)
    result = py(world.reader.read_party())
    assert result["count"] == count and len(result["mons"]) == count
    for slot, mon in enumerate(result["mons"]):
        assert mon == {**expected_record(egg=True), "ot_raw_hex": OT.hex(), "nickname_raw_hex": NICKNAME.hex(), "slot": slot}
    address = world.profile["ram"]["wPartyCount"]
    assert world.calls == [("System Bus", address, 428)]
    assert world.bank_calls == [(1, address, 428)] * 2
    assert result["snapshot_qualified"] is False


@pytest.mark.parametrize("title", TITLES)
def test_all_14_backing_boxes_and_active_shadow_have_distinct_locations_and_ownership(title):
    world = World(title)
    world.bus[world.profile["ram"]["wCurBox"]] = 13
    world.put_box(block(party=False, species=133))
    for index in range(14):
        flat = world.put_box(block(party=False, species=index + 1), index)
        result = py(world.reader.read_storage_box(index))
        assert result["mons"][0]["species_id"] == index + 1
        assert result["box_index"] == index
        assert result["bank"] == (2 if index < 7 else 3)
        assert result["ownership"] == "backing_sram_box"
        assert result["active_shadow_authoritative"] is (index == 13)
        assert result["copy_length"] == 1102 and result["padding_hex"] == "eeee"
        assert result["durable_save_verified"] is False
        assert ("CartRAM", flat, 1104) in world.calls
    result = py(world.reader.read_active_box())
    assert result["mons"][0]["species_id"] == 133
    assert result["box_index"] == 13 and result["bank"] == 1
    assert result["ownership"] == "active_sram_shadow"
    assert result["is_current"] is True
    assert "padding_hex" not in result and len(result["raw_hex"]) == 1102 * 2
    active_flat = 8192 + world.profile["ram"]["sBox"] - 40960
    assert ("CartRAM", active_flat, 1102) in world.calls
    assert ("CartRAM", active_flat, 1104) not in world.calls
    assert ("CartRAM", 0x79E0, 1104) in world.calls  # Independent Box 14 source location.


@pytest.mark.parametrize("count", [0, 20])
def test_box_capacity_edges_and_padding_are_preserved(count):
    world = World()
    result = py(world.reader.decode_box_block(world.bytes(block(party=False, count=count, egg=True))))
    assert result["count"] == count and len(result["mons"]) == count
    assert result["padding_hex"] == "eeee"
    assert all(mon["is_egg"] for mon in result["mons"])


def test_active_box_decoder_does_not_consume_backing_box_padding():
    world = World("gold")
    active = block(party=False)[:-2]
    decoded = py(world.reader.decode_active_box_block(world.bytes(active)))
    assert decoded["copy_length"] == 1102 and "padding_hex" not in decoded
    error(world.reader.decode_active_box_block(world.bytes(active + b"\x11\x22")), "collection bytes")
    error(world.reader.decode_box_block(world.bytes(active)), "collection bytes")


@pytest.mark.parametrize("party", [True, False])
def test_bad_count_terminator_marker_and_short_collection_refuse(party):
    world = World()
    method = world.reader.decode_party_block if party else world.reader.decode_box_block
    original = block(party=party)
    error(method(world.bytes(original[:-1])), "collection bytes")
    bad = bytearray(original)
    bad[0] = 7 if party else 21
    error(method(world.bytes(bad)), "exceeds capacity")
    bad = bytearray(original)
    bad[2] = 0
    error(method(world.bytes(bad)), "terminator")
    bad = bytearray(original)
    bad[1] = 99
    error(method(world.bytes(bad)), "mismatch")


def test_unreadable_malformed_and_bank_change_refuse_without_zero_fallback():
    world = World()
    world.put_party(block(party=True))
    world.bank_ok = False
    error(world.reader.read_party(), "bank unavailable")
    assert world.calls == []
    world.bank_ok = True
    world.bank_answers = [True, False]
    error(world.reader.read_party(), "bank changed")
    world.io.bank_valid = None
    error(world.reader.read_party(), "explicit WRAM bank")
    world = World()
    world.read_override = lambda *_: None
    error(world.reader.read_party(), "unavailable or malformed")
    world.read_override = lambda _, n, __: world.bytes([False] * n)
    error(world.reader.read_party(), "unavailable or malformed")
    world.read_override = lambda _, n, __: world.bytes([0.5] * n)
    error(world.reader.read_party(), "unavailable or malformed")


def test_linear_cartram_binding_bounds_and_box_switch_are_required():
    world = World()
    world.put_box(block(party=False), 13)
    world.io.cart_ram_linear = False
    error(world.reader.read_storage_box(13), "linear CartRAM")
    world.io.cart_ram_linear = True
    world.size_override = 0x79E0 + 1103
    error(world.reader.read_storage_box(13), "range unavailable")
    world.size_override = None
    original = world.read_range

    def switched(address, length, domain):
        saved = world.read_override
        world.read_override = None
        value = original(address, length, domain)
        world.read_override = saved
        if domain == "CartRAM":
            world.bus[world.profile["ram"]["wCurBox"]] = 1
        return value

    world.read_override = switched
    error(world.reader.read_storage_box(13), "box changed")


def test_current_box_is_not_a_gen1_high_bit_mask_and_bad_bindings_refuse():
    world = World()
    world.bus[world.profile["ram"]["wCurBox"]] = 0x80
    error(world.reader.read_current_box_num(), "outside 0..13")
    for index in (-1, 14, 0.5, None):
        error(world.reader.read_storage_box(index), "outside 0..13")
    world.lua_profile.sram_bank.sBox = 2
    error(world.reader.read_active_box(), "active sBox")
    world.lua_profile.storage_boxes[1].bank = 3
    error(world.reader.read_storage_box(0), "binding disagrees")


def test_absent_saved_state_is_unavailable_and_raw_flags_never_establish_admission():
    world = World()
    # Missing input still refuses; the positive uses the generated profile itself.
    world.lua_profile.ram.wSavedAtLeastOnce = None
    error(world.reader.read_admission_facts(), "wSavedAtLeastOnce")
    world = World()
    assert world.profile["ram_bank"]["wSavedAtLeastOnce"] == 1
    world.bus[world.profile["ram"]["wSavedAtLeastOnce"]] = 1
    world.bus[world.profile["ram"]["wBattleMode"]] = 2
    result = py(world.reader.read_admission_facts())
    assert result["saved_at_least_once"] == 1 and result["battle_mode"] == 2
    assert result["admission_established"] is False and result["evidence"] == "RAW_RAM_ONLY"
    assert "qualified checkpoint or qualified running battle" in result["requires"]


@pytest.mark.parametrize("field,value", [("MON_DVS", 27), ("PARTYMON_STRUCT_LENGTH", 44), ("EGG", 252)])
def test_incompatible_generated_layout_refuses(field, value):
    profile = profile_for("gold")
    profile["constants"][field] = value
    error(World("gold", profile=profile).reader, "profile constant" if field != "MON_DVS" else "record offset")


def test_source_receipt_for_layout_egg_pp_and_storage_is_independent_of_codec():
    for repo in ("pokecrystal", "pokegold"):
        source = ROOT / ".cache/gen2-build" / repo
        macros = (source / "macros/ram.asm").read_text(encoding="utf-8")
        assert "\\1SpclAtk::" in macros and "\\1SpclDef::" in macros
        assert "\\1MonOTs::" in macros and "\\1MonNicknames::" in macros
        constants = (source / "constants/pokemon_data_constants.asm").read_text(encoding="utf-8")
        assert "DEF PP_UP_MASK EQU %11000000" in constants
        assert "DEF PP_MASK    EQU %00111111" in constants
        assert "DEF NUM_BOXES EQU 14" in constants
        battle_constants = (source / "constants/battle_constants.asm").read_text(encoding="utf-8")
        assert "DEF MAX_LEVEL EQU 100" in battle_constants
        experience = (source / "engine/pokemon/experience.asm").read_text(encoding="utf-8")
        assert "\tld d, 1\n.next_level\n\tinc d" in experience
        assert "\tcp LOW(MAX_LEVEL + 1)\n\tjr z, .got_level" in experience
        assert ".got_level\n\tdec d\n\tret" in experience
        moving = (source / "engine/pokemon/move_mon.asm").read_text(encoding="utf-8")
        assert "\tld a, EGG\n\tld [hl], a" in moving
        assert "DV_HP = (DV_ATK & 1) << 3" in moving
        layout = (source / "layout.link").read_text(encoding="utf-8")
        assert 'SRAM $02\n\t"Boxes 1-7"\nSRAM $03\n\t"Boxes 8-14"' in layout
    lua = READS.read_text(encoding="utf-8")
    assert "write_u8" not in lua and "memory." not in lua and "require(" not in lua


@pytest.mark.parametrize("title", TITLES)
def test_player_and_map_fields_are_raw_readback_not_session_admission(title):
    world = World(title, name_decoder=lambda _raw: "PLAYER")
    a = world.profile["ram"]
    world.bus[a["wPlayerID"]:a["wPlayerID"] + 13] = b"\x12\x34" + OT
    player = py(world.reader.read_player())
    assert player["ot_id"] == 0x1234 and player["name_raw_hex"] == OT.hex()
    assert player["player_name"] == "PLAYER" and player["identity_qualified"] is False
    assert player["snapshot_qualified"] is False
    world.bus[a["wMapGroup"]:a["wMapGroup"] + 4] = bytes([24, 3, 17, 29])
    location = py(world.reader.read_map())
    assert (location["group"], location["number"], location["x"], location["y"]) == (24, 3, 29, 17)
    assert location["snapshot_qualified"] is False


def _put_pockets(world):
    a = world.profile["ram"]
    # Duplicate ordinary stacks remain separate; the Ball pocket is independently read.
    world.bus[a["wNumItems"]:a["wNumItems"] + 6] = bytes([2, 20, 99, 20, 1, 255])
    world.bus[a["wNumBalls"]:a["wNumBalls"] + 6] = bytes([2, 4, 5, 1, 2, 255])
    world.bus[a["wNumKeyItems"]:a["wNumKeyItems"] + 4] = bytes([2, 7, 54, 255])
    world.bus[a["wTMsHMs"]] = 99
    world.bus[a["wTMsHMs"] + 56] = 1


@pytest.mark.parametrize("title", TITLES)
def test_pockets_preserve_stack_records_key_ids_and_tmhm_ordinals(title):
    world = World(title)
    _put_pockets(world)
    bag = py(world.reader.read_bag())
    assert bag["items"]["entries"] == [{"slot": 0, "id": 20, "quantity": 99},
                                        {"slot": 1, "id": 20, "quantity": 1}]
    assert bag["balls"]["entries"] == [{"slot": 0, "id": 4, "quantity": 5},
                                        {"slot": 1, "id": 1, "quantity": 2}]
    assert bag["key_items"]["entries"] == [{"slot": 0, "id": 7}, {"slot": 1, "id": 54}]
    assert len(bag["tmhm"]["quantities"]) == 57
    assert bag["tmhm"]["quantities"][0] == 99 and bag["tmhm"]["quantities"][-1] == 1
    assert bag["snapshot_qualified"] is False


@pytest.mark.parametrize("pocket,symbol,offset,value,message", [
    ("items", "wNumItems", 0, 21, "capacity"),
    ("balls", "wNumBalls", 5, 0, "terminator"),
    ("items", "wNumItems", 1, 0, "item id"),
    ("balls", "wNumBalls", 2, 0, "quantity"),
    ("balls", "wNumBalls", 2, 100, "quantity"),
    ("key_items", "wNumKeyItems", 1, 255, "item id"),
    ("tmhm", "wTMsHMs", 1, 100, "quantity"),
])
def test_corrupt_pocket_never_becomes_an_empty_success(pocket, symbol, offset, value, message):
    world = World()
    _put_pockets(world)
    world.bus[world.profile["ram"][symbol] + offset] = value
    error(world.reader.read_pocket(pocket), message)


def test_ancillary_methods_refuse_missing_symbols_decoder_failures_and_wrong_banks():
    world = World(name_decoder=lambda _raw: None)
    error(world.reader.read_player(), "decoder unavailable")
    world = World()
    world.lua_profile.ram.wMapNumber = None
    error(world.reader.read_map(), "geometry")
    world.lua_profile.ram.wPlayerID = None
    error(world.reader.read_player(), "wPlayerID")
    world = World()
    world.bank_answers = [True, False]
    error(world.reader.read_map(), "bank changed")
    world.bank_ok = False
    error(world.reader.read_pocket("items"), "bank unavailable")


def battle_vector():
    data = bytearray(32)
    data[:8] = bytes([25, 146, 1, 33, 166, 237, 0xAB, 0xCD])
    data[8:16] = bytes([0, 65, 130, 255, 200, 51, 0x88, 0x7F])
    data[16:30] = struct.pack(">7H", 0x0123, 0x0456, 0x1234, 0x2345, 0x3456, 0x4567, 0x5678)
    data[30:32] = bytes([13, 16])
    return bytes(data)


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("side,prefix", [("player", "wBattleMon"), ("enemy", "wEnemyMon")])
def test_battle_view_uses_its_own_layout_and_preserves_packed_pp_and_dvs(title, side, prefix):
    world = World(title, name_decoder=lambda _raw: "BATTLE")
    a = world.profile["ram"]
    raw = battle_vector()
    world.bus[a[prefix]:a[prefix] + len(raw)] = raw
    world.bus[a[prefix + "Nickname"]:a[prefix + "Nickname"] + 11] = NICKNAME
    mon = py(world.reader.read_battle_mon(side))
    assert mon["species_id"] == 25 and mon["held_item"] == 146
    assert mon["moves"] == [1, 33, 166, 237]
    assert mon["dv_word"] == 0xABCD and mon["dvs"] == expected_record()["dvs"]
    assert mon["pp_raw"] == [0, 65, 130, 255]
    assert mon["pp"] == [0, 1, 2, 63] and mon["pp_ups"] == [0, 1, 2, 3]
    assert (mon["status"], mon["status_aux_raw"], mon["hp"], mon["max_hp"]) == (0x88, 0x7F, 0x123, 0x456)
    assert mon["stats"] == expected_record()["stats"]
    assert mon["types_raw"] == [13, 16] and mon["raw_hex"] == raw.hex()
    assert mon["nickname"] == "BATTLE" and mon["nickname_raw_hex"] == NICKNAME.hex()
    assert mon["identity_qualified"] is False and mon["battle_qualified"] is False
    assert "ot_id" not in mon and "key" not in mon


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("mode", [0, 1, 2])
def test_raw_battle_context_masks_flags_without_inventing_whiteout_or_reading_stale_trainer(title, mode):
    world = World(title)
    a = world.profile["ram"]
    world.bus[a["wBattleMode"]] = mode
    world.bus[a["wBattleType"]] = 5
    world.bus[a["wBattleResult"]] = (0xC0 if title == "crystal" else 0x80) | 1
    world.bus[a["wCurBattleMon"]] = 4
    world.bus[a["wOtherTrainerClass"]] = 42
    world.bus[a["wOtherTrainerID"]] = 9
    result = py(world.reader.read_battle())
    assert result["mode"] == mode and result["battle_type"] == 5 and result["result_code"] == 1
    assert result["result_raw"] == world.bus[a["wBattleResult"]]
    assert result["battle_qualified"] is False and "whiteout" not in result
    if mode:
        assert result["active_slot"] == 4
    else:
        assert "active_slot" not in result
    if mode == 2:
        assert result["trainer"] == {"class_raw": 42, "id_raw": 9}
    else:
        assert "trainer" not in result
        assert not any(address in (a["wOtherTrainerClass"], a["wOtherTrainerID"])
                       for _domain, address, _length in world.calls)


def test_invalid_or_changing_battle_context_refuses():
    world = World()
    a = world.profile["ram"]
    world.bus[a["wBattleMode"]] = 3
    error(world.reader.read_battle(), "enumeration")
    world.bus[a["wBattleMode"]] = 1
    world.bus[a["wCurBattleMon"]] = 6
    error(world.reader.read_battle(), "capacity")
    world.bus[a["wCurBattleMon"]] = 0
    calls = [0]

    def changing(address, length, _domain):
        raw = bytes(world.bus[address:address + length])
        if address == a["wBattleMode"]:
            calls[0] += 1
            if calls[0] == 2:
                raw = bytes([0])
        return world.bytes(raw)

    world.read_override = changing
    error(world.reader.read_battle(), "changed during read")


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("side,prefix", [("player", "wPlayer"), ("enemy", "wEnemy")])
def test_seven_named_stages_normalize_while_the_eighth_byte_stays_uninterpreted(title, side, prefix):
    world = World(title)
    base = world.profile["ram"][prefix + "StatLevels"]
    raw = [1, 7, 13, 2, 6, 8, 12, 255]
    world.bus[base:base + 8] = bytes(raw)
    result = py(world.reader.read_stat_stages(side))
    assert result["raw"] == raw and result["unused_raw"] == 255
    assert result["wire"] == [0, 6, 12, 1, 5, 7, 11]
    assert result["battle_qualified"] is False and result["snapshot_qualified"] is False


@pytest.mark.parametrize("bad", [0, 14, 255])
def test_invalid_named_stage_is_not_clamped_or_replaced_with_neutral(bad):
    world = World()
    base = world.profile["ram"]["wPlayerStatLevels"]
    world.bus[base:base + 8] = bytes([7, 7, 7, bad, 7, 7, 7, 0])
    error(world.reader.read_stat_stages("player"), "source bounds")


@pytest.mark.parametrize("title", TITLES)
def test_badge_regions_remain_separate_eight_bit_fields(title):
    world = World(title)
    base = world.profile["ram"]["wJohtoBadges"]
    world.bus[base:base + 2] = bytes([0x81, 0x42])
    result = py(world.reader.read_badges())
    assert result["johto"] == 0x81 and result["kanto"] == 0x42
    assert result["raw_hex"] == "8142" and result["snapshot_qualified"] is False


def test_new_reads_require_all_generated_facts_and_do_not_infer_missing_offsets():
    world = World()
    world.lua_profile.constants.BASE_STAT_LEVEL = None
    error(world.reader.read_stat_stages("player"), "stat-stage facts")
    world.lua_profile.constants.NUM_JOHTO_BADGES = None
    error(world.reader.read_badges(), "badge-count facts")
    world.lua_profile.constants.BATTLERESULT_BITMASK = None
    error(world.reader.read_battle(), "battle-context facts")
    world.lua_profile.ram.wEnemyMonDVs = None
    error(world.reader.read_battle_mon("enemy"), "geometry")
    error(world.reader.read_battle_mon("other"), "side")
    error(world.reader.read_stat_stages("other"), "side")


def test_source_receipts_cover_ancillary_layouts_and_stat_normalization_bounds():
    for repo, player_line in (("pokecrystal", "wPlayerStatLevels::"), ("pokegold", "wPlayerStatLevels::")):
        source = ROOT / ".cache/gen2-build" / repo
        wram = (source / "ram/wram.asm").read_text()
        assert "wPlayerID:: dw" in wram and "wPlayerName:: ds NAME_LENGTH" in wram
        assert "wItems:: ds MAX_ITEMS * 2 + 1" in wram
        assert "wKeyItems:: ds MAX_KEY_ITEMS + 1" in wram
        assert "wBalls:: ds MAX_BALLS * 2 + 1" in wram
        assert "wTMsHMs:: ds NUM_TMS + NUM_HMS" in wram and player_line in wram
        assert "wPlayerEvaLevel::  db\n\tds 1" in wram
        constants = (source / "constants/battle_constants.asm").read_text()
        assert "DEF BASE_STAT_LEVEL EQU 7" in constants and "DEF MAX_STAT_LEVEL EQU 13" in constants
        assert "const ABILITY ; used for BattleCommand_Curse\nDEF NUM_LEVEL_STATS EQU const_value" in constants
        effects = (source / "engine/battle/effect_commands.asm").read_text()
        assert "\tld b, [hl]\n\tdec b\n\tjp z, .CantLower" in effects
        assert "\tdec b\n\tjr nz, .ComputerMiss\n\tinc b" in effects
