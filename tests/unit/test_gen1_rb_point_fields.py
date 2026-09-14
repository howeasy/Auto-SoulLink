"""Pure decoders for the R/B scripted route point; no emulator."""

from pathlib import Path

from lupa.lua54 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def load():
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.execute((ROOT / "lua/tests/gen1_rb_point_fields.lua").read_text())


def reader(lua, memory):
    return lua.eval("function(t) return function(a) return t[a] or 0 end end")(lua.table_from(memory))


def test_event_bits_follow_pokered_numbering():
    lua, fields = load()
    read = reader(lua, {0xD747 + 7: 0b11, 0xD747 + 4: 0b1000})
    assert fields.event_bit(read, 0xD747, fields.EVENT_OAK_GOT_PARCEL) is True
    assert fields.event_bit(read, 0xD747, fields.EVENT_GOT_OAKS_PARCEL) is True
    assert fields.event_bit(read, 0xD747, 35) is True
    assert fields.event_bit(read, 0xD747, 36) is False


def test_money_is_three_byte_bcd():
    lua, fields = load()
    read = reader(lua, {0xD347: 0x00, 0xD348: 0x30, 0xD349: 0x00})
    assert fields.bcd_money(read, 0xD347) == 3000
    read = reader(lua, {0xD347: 0x09, 0xD348: 0x99, 0xD349: 0x99})
    assert fields.bcd_money(read, 0xD347) == 99999


def test_bag_quantity_scans_pairs_until_count_or_terminator():
    lua, fields = load()
    memory = {0xD31D: 2, 0xD31E: 0x46, 0xD31F: 1, 0xD320: 0x04, 0xD321: 5, 0xD322: 0xFF}
    read = reader(lua, memory)
    assert fields.bag_quantity(read, 0xD31D, 0xD31E, fields.OAKS_PARCEL) == 1
    assert fields.bag_quantity(read, 0xD31D, 0xD31E, fields.POKE_BALL) == 5
    assert fields.bag_quantity(read, 0xD31D, 0xD31E, 0x05) == 0
    memory[0xD31D] = 0
    assert fields.bag_quantity(reader(lua, memory), 0xD31D, 0xD31E, fields.POKE_BALL) == 0
    memory[0xD31D] = 0xFF
    assert fields.bag_quantity(reader(lua, memory), 0xD31D, 0xD31E, fields.POKE_BALL) == 0


def test_facing_names():
    lua, fields = load()
    assert fields.facing_name(0x08) == "left" and fields.facing_name(0x0C) == "right"
    assert fields.facing_name(0x00) == "down" and fields.facing_name(0x04) == "up"
    assert fields.facing_name(0x77) == "unknown"
