"""Gen 2 wire projection tests (lua/gen2/wire.lua).

lua/gen2/wire.lua is pure: decoded party/box/battle-mon record -> the
JSON-shaped snapshot entry docs/protocol.md S4.1/S4.3/S4.4 expects. No
transport, no admission, no emulator globals, no writes.

Differential controls run the SAME sample bytes through the independent
Python oracle (server/adapters/gen2_codec.py, server/adapters/gen2_gsc.py)
and assert the Lua projection key/blob agree with what that oracle produces
and accepts (validate_party_blob). Records are decoded through
lua/gen2/reads.lua (the stable record API), never re-decoded by hand here,
matching how a real caller would feed wire.lua.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaRuntime

from server.adapters import gen2_codec as codec
from server.adapters.gen2_gsc import Gen2GSCAdapter

ROOT = Path(__file__).resolve().parents[2]
WIRE = ROOT / "lua/gen2/wire.lua"
READS = ROOT / "lua/gen2/reads.lua"
TITLES = ("crystal", "gold", "silver")


def py(value):
    """Recursively turn a lupa table (or scalar) into a plain Python value."""
    if hasattr(value, "items"):
        items = list(value.items())
        if items and all(isinstance(key, int) for key, _ in items):
            assert sorted(key for key, _ in items) == list(range(1, len(items) + 1))
            return [py(value[i]) for i in range(1, len(items) + 1)]
        return {key: py(item) for key, item in items}
    return value


def refused(result, contains):
    assert isinstance(result, tuple) and len(result) == 2 and result[0] is None
    assert contains in result[1]


def profile_for(title):
    return json.loads((ROOT / f"data/games/gen2_{title}/profile.json").read_text(encoding="utf-8"))["titles"][title]


class World:
    """wire.lua plus reads.lua, so tests can build real decoded records
    instead of hand-rolling record tables that could drift from the
    decoder's actual shape."""

    def __init__(self, title="crystal", name_decoder=None):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.wire = self.lua.eval("dofile")(WIRE.as_posix())
        reads_mod = self.lua.eval("dofile")(READS.as_posix())
        io_stub = self.lua.eval('{read_range=function() error("no io stub") end}')
        profile = self.lua.table_from(profile_for(title), recursive=True)
        decoder = None
        if name_decoder is not None:
            decoder = self.lua.eval("function(f) return function(b) return f(b) end end")(name_decoder)
        self.reads = reads_mod.new(profile, io_stub, decoder)

    def bytes(self, value):
        return self.lua.table_from(list(value))

    def party_mon(self, raw70, species_marker=25, slot=0):
        mon = self.reads.decode_transfer_blob(self.bytes(raw70), species_marker)
        assert not isinstance(mon, tuple), mon
        mon["slot"] = slot
        return mon

    def box_mon(self, raw32, species_marker=25, slot=0):
        mon = self.reads.decode_record(self.bytes(raw32), "box", species_marker, None, None)
        assert not isinstance(mon, tuple), mon
        mon["slot"] = slot
        return mon


# ── sample fixture: one real, decodable 70-byte Gen 2 party transfer blob ──
# Layout matches server/adapters/gen2_codec.py OFFSETS / lua/gen2/reads.lua's
# verified field partition: species(0) item(1) moves(2..5) ot_id(6..7)
# exp(8..10) stat_exp(11..20) dvs(21..22) pp(23..26) happiness(27)
# pokerus(28..30) level(31) status(32..33) hp(34..35) maxhp(36..37)
# atk/def/spd/sat/sdf(38..47), then 11-byte OT name, then 11-byte nickname.

def sample_blob():
    raw = bytearray(70)
    raw[0:8] = bytes([25, 143, 33, 45, 0, 0, 0x12, 0x34])  # species 25, item 143 (King's Rock)
    raw[21:23] = bytes.fromhex("2aaa")  # DV word
    raw[23:27] = bytes([35, 40, 0, 0])  # pp packed: pp=[35,40,0,0], pp_ups=[0,0,0,0]
    raw[31] = 20  # level
    raw[34:38] = bytes.fromhex("00200030")  # hp=32, maxHP=48
    raw[38:48] = bytes.fromhex("00200020002000200020")
    raw[48:] = bytes([0x80, 0x50] + [0] * 9 + [0x81, 0x50] + [0] * 9)  # OT + nickname raw bytes
    return bytes(raw)


EXPECTED_KEY = "2AAA:1234:19"


def gsc_adapter(title):
    return Gen2GSCAdapter(title)


def layout_for(title):
    return codec.for_foundation(title, root=ROOT)


# ── mon_key: identity falsifier ─────────────────────────────────────────

@pytest.mark.parametrize("title", TITLES)
def test_mon_key_matches_independent_python_codec_and_adapter(title):
    world = World(title)
    mon = world.party_mon(sample_blob())
    key = world.wire.mon_key(mon)
    assert key == EXPECTED_KEY
    assert key == codec.key({"dv_word": 0x2AAA, "ot_id": 0x1234, "species_id": 25})
    assert gsc_adapter(title).is_valid_mon_key(key)


@pytest.mark.parametrize("dv_word,ot_id,species_id,expected", [
    (0, 0, 1, "0000:0000:01"),
    (0xFFFF, 0xFFFF, 251, "FFFF:FFFF:FB"),
    (0x1234, 0xABCD, 133, "1234:ABCD:85"),
])
def test_mon_key_field_for_field_against_codec(dv_word, ot_id, species_id, expected):
    world = World()
    mon = world.lua.table_from({"dv_word": dv_word, "ot_id": ot_id, "species_id": species_id})
    key = world.wire.mon_key(mon)
    assert key == expected == codec.key({"dv_word": dv_word, "ot_id": ot_id, "species_id": species_id})


@pytest.mark.parametrize("field,bad", [("dv_word", 65536), ("dv_word", -1), ("ot_id", 65536),
                                       ("species_id", 0), ("species_id", 252), ("species_id", "25")])
def test_mon_key_refuses_out_of_range_identity_fields(field, bad):
    world = World()
    base = {"dv_word": 1, "ot_id": 1, "species_id": 1}
    base[field] = bad
    refused(world.wire.mon_key(world.lua.table_from(base)), "")


def test_mon_key_refuses_non_table():
    world = World()
    refused(world.wire.mon_key(None), "mon record required")


# ── party_entry: shape, blob field order, PP-Up split, stat stages ─────

@pytest.mark.parametrize("title", TITLES)
def test_party_entry_shape_and_blob_round_trip_against_python_oracle(title):
    world = World(title)
    mon = world.party_mon(sample_blob())
    entry = py(world.wire.party_entry(mon, 0, None))
    assert entry["key"] == EXPECTED_KEY
    assert entry["slot"] == 0
    assert entry["species_id"] == 25
    assert entry["level"] == 20
    assert entry["hp"] == 32 and entry["maxHP"] == 48
    assert entry["status_cond"] == 0
    assert entry["moves"] == [33, 45, 0, 0]
    assert entry["held_item_id"] == 143
    assert entry["active"] is True
    # falsifier: wrong 70-byte field order in the emitted blob
    assert entry["blob_hex"] == sample_blob().hex()
    adapter = gsc_adapter(title)
    assert adapter.validate_party_blob(bytes.fromhex(entry["blob_hex"]), key=entry["key"], species_marker=25)
    oracle = adapter.decode_party_blob(sample_blob(), species_marker=25)
    assert entry["key"] == oracle["key"]
    assert entry["held_item_id"] == oracle["held_item"]


@pytest.mark.parametrize("title", TITLES)
def test_party_entry_pp_up_bits_separated_from_current_pp(title):
    world = World(title)
    raw = bytearray(sample_blob())
    raw[23] = 0xC5  # packed: pp = 0xC5 & 63 = 5, pp_ups = 0xC5 >> 6 = 3
    mon = world.party_mon(bytes(raw))
    entry = py(world.wire.party_entry(mon, None, None))
    assert entry["pp"][0] == 5
    assert entry["pp_ups"][0] == 3
    oracle = codec.decode_party_blob(bytes(raw), layout_for(title), species_marker=25)
    assert entry["pp"] == oracle["pp"]
    assert entry["pp_ups"] == oracle["pp_ups"]


def test_party_entry_active_slot_gates_stat_stages():
    world = World()
    mon = world.party_mon(sample_blob(), slot=2)
    # docs/protocol.md S4.1: ATK,DEF,SPD,SATK,SDEF,ACC,EVA, 6 == neutral.
    # Distinct SATK/SDEF values: the falsifier is Special collapsing the two.
    stages = world.lua.table_from([5, 6, 7, 3, 9, 6, 6])
    inactive = world.wire.party_entry(mon, 0, stages)  # active_slot(0) != mon.slot(2)
    inactive_entry = py(inactive)
    assert "stat_stages" not in inactive_entry
    assert inactive_entry["active"] is False

    active = py(world.wire.party_entry(mon, 2, stages))
    assert active["active"] is True
    assert active["stat_stages"] == [5, 6, 7, 3, 9, 6, 6]
    # SpAtk (index 4, 1-based) and SpDef (index 5) stay independent slots --
    # unlike Gen 1, which tracks one combined "Special" stage and blanks SDEF.
    assert active["stat_stages"][3] != active["stat_stages"][4]


@pytest.mark.parametrize("stages,reason", [
    ([6, 6, 6, 6, 6, 6], "invalid stat_stages"),        # falsifier: stat-stage order/shape wrong (short)
    ([6, 6, 6, 6, 6, 6, 6, 6], "invalid stat_stages"),  # too long
    ([13, 6, 6, 6, 6, 6, 6], "invalid stat_stages"),    # out of 0..12
    ([-1, 6, 6, 6, 6, 6, 6], "invalid stat_stages"),
])
def test_party_entry_refuses_malformed_stat_stages(stages, reason):
    world = World()
    mon = world.party_mon(sample_blob(), slot=0)
    refused(world.wire.party_entry(mon, 0, world.lua.table_from(stages)), reason)


@pytest.mark.parametrize("title", TITLES)
def test_party_entry_refuses_egg_record(title):
    world = World(title)
    mon = world.party_mon(sample_blob(), species_marker=253)  # EGG marker
    assert py(mon["is_egg"]) is True
    refused(world.wire.party_entry(mon, None, None), "egg")


@pytest.mark.parametrize("missing", ["raw_hex", "ot_raw_hex", "nickname_raw_hex"])
def test_party_entry_refuses_missing_blob_component(missing):
    world = World()
    mon = world.party_mon(sample_blob())
    del mon[missing]
    refused(world.wire.party_entry(mon, None, None), missing)


@pytest.mark.parametrize("field,value,reason", [
    ("slot", None, "slot"),
    ("slot", 6, "slot"),
    ("level", 0, "level"),
    ("level", 101, "level"),
    ("status", None, "status"),
    ("held_item", None, "held_item"),
])
def test_party_entry_refuses_malformed_required_fields(field, value, reason):
    world = World()
    mon = world.party_mon(sample_blob())
    mon[field] = value
    refused(world.wire.party_entry(mon, None, None), reason)


@pytest.mark.parametrize("bad_list", [[1, 2, 3], [1, 2, 3, 4, 5], [1, 2, 3, 256]])
def test_party_entry_refuses_malformed_move_pp_arrays(bad_list):
    world = World()
    mon = world.party_mon(sample_blob())
    mon["moves"] = world.lua.table_from(bad_list)
    refused(world.wire.party_entry(mon, None, None), "moves")


def test_party_entry_omits_nickname_without_injected_decoder():
    # "missing injected inputs": reads.lua was built with no name_decoder, so
    # the record has no decoded mon.nickname string -- wire.lua must not
    # invent one via its own charmap; the SHOULD-optional field is just absent.
    world = World()
    mon = world.party_mon(sample_blob())
    assert mon["nickname"] is None
    entry = py(world.wire.party_entry(mon, None, None))
    assert "nickname" not in entry


def test_party_entry_forwards_injected_decoder_nickname():
    world = World(name_decoder=lambda raw: "TAUROS")
    mon = world.party_mon(sample_blob())
    assert py(mon["nickname"]) == "TAUROS"
    entry = py(world.wire.party_entry(mon, None, None))
    assert entry["nickname"] == "TAUROS"


def test_party_entry_refuses_raw_nickname_bytes_never_hardcodes_a_charmap():
    world = World()
    mon = world.party_mon(sample_blob())
    mon["nickname"] = world.lua.table_from([1, 2, 3])  # raw bytes, not an injected decoder's string
    refused(world.wire.party_entry(mon, None, None), "nickname")


# ── foe_entry: no key, no ability/form, distinct SATK/SDEF ─────────────

def foe_mon(world):
    raw = bytearray(sample_blob()[:48])
    mon = world.reads.decode_record(world.bytes(raw), "party", 25, None, None)
    assert not isinstance(mon, tuple), mon
    return mon


def test_foe_entry_shape_has_no_key_ability_or_form():
    world = World()
    entry = py(world.wire.foe_entry(foe_mon(world), None))
    assert "key" not in entry
    assert "ability_id" not in entry
    assert "form" not in entry
    assert entry["active"] is True
    assert entry["species_id"] == 25
    assert entry["held_item_id"] == 143


def test_foe_entry_refuses_malformed_input():
    world = World()
    refused(world.wire.foe_entry(None, None), "mon record required")
    mon = foe_mon(world)
    mon["hp"] = None
    refused(world.wire.foe_entry(mon, None), "hp")


def test_foe_entry_stat_stages_keep_satk_sdef_independent():
    world = World()
    stages = world.lua.table_from([6, 6, 6, 4, 10, 6, 6])
    entry = py(world.wire.foe_entry(foe_mon(world), stages))
    assert entry["stat_stages"][3] != entry["stat_stages"][4]


# ── box_entry: held_item_id present (unlike Gen 1), egg refusal ────────

def sample_box_record():
    raw = bytearray(32)
    raw[0:8] = bytes([133, 99, 84, 85, 0, 0, 0x22, 0x33])  # Eevee, item 99, moves, ot_id
    raw[21:23] = bytes.fromhex("1555")
    raw[23:27] = bytes([10, 20, 0, 0])
    raw[31] = 15
    return bytes(raw)


def test_box_entry_shape_includes_held_item_unlike_gen1():
    world = World()
    mon = world.box_mon(sample_box_record(), species_marker=133, slot=4)
    entry = py(world.wire.box_entry(mon, 7))
    assert entry["box"] == 7
    assert entry["slot"] == 4
    assert entry["species_id"] == 133
    assert entry["level"] == 15
    assert entry["held_item_id"] == 99
    assert entry["key"] == codec.key({"dv_word": 0x1555, "ot_id": 0x2233, "species_id": 133})
    assert "nickname" not in entry


def test_box_entry_refuses_egg_and_out_of_range_box_index():
    world = World()
    mon = world.box_mon(sample_box_record(), species_marker=253, slot=0)
    refused(world.wire.box_entry(mon, 0), "egg")
    real = world.box_mon(sample_box_record(), species_marker=133, slot=0)
    refused(world.wire.box_entry(real, 14), "box_index")
    refused(world.wire.box_entry(real, None), "box_index")


def test_box_entry_refuses_raw_nickname_bytes():
    world = World()
    mon = world.box_mon(sample_box_record(), species_marker=133, slot=0)
    mon["nickname"] = world.lua.table_from([1, 2])
    refused(world.wire.box_entry(mon, 0), "nickname")
