"""MODEL/SOURCE unit and lupa coverage for the P3b.3a live inspect gate -- no emulator, no
cartridge. Two things are exercised:

  1. lua/tests/gen2_inspect_gate.lua's pure functions and G.main(), driven under lupa with a fake
     `api` over synthetic WRAM/CartRAM bytearrays -- proving the driver actually emits a
     frame/domain/range-carrying DUMP record and the CHECKPOINT/PASS lines, and that it refuses
     cleanly on missing/malformed inputs.
  2. tests/live/test_gen2_new_gates.py's importable comparator functions (compare_collection,
     identity_matches, gender_and_shiny, tag_json, fixture_missing_reason, rom_missing_reason) --
     the first falsifier: the comparator must actually fail on a single mutated byte and on a
     wrong-fixture identity, and the skip-reason helpers must actually report a reason rather than
     silently passing when an input is absent.

Passing here is authoring/MODEL evidence only, never PHYSICAL evidence -- see
tests/live/test_gen2_new_gates.py for the cartridge lane this gate is meant to run under.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from run_gb_gate import describe_gen2  # noqa: E402

from server.adapters import gen2_codec as codec  # noqa: E402
from tests.live import test_gen2_new_gates as live  # noqa: E402

GATE = REPO / "lua/tests/gen2_inspect_gate.lua"
TITLE = "crystal"
ROM_SHA1 = describe_gen2(TITLE)["rom_sha1"]


def profile_wrapper(title=TITLE):
    return json.loads((REPO / f"data/games/gen2_{title}/profile.json").read_text(encoding="utf-8"))


def profile_row(title=TITLE):
    return profile_wrapper(title)["titles"][title]


def species_row(species_id, title=TITLE):
    species = json.loads((REPO / f"data/games/gen2_{title}/species_index.json").read_text(encoding="utf-8"))
    return species["species"][str(species_id)]


# =================================================================================================
# Part 1: the Lua gate under lupa, with a fake BizHawk `api`
# =================================================================================================


def wram_offset(addr, bank):
    return addr - 0xC000 if addr < 0xD000 else bank * 0x1000 + addr - 0xD000


class FakeApi:
    """A fake BizHawk: a flat WRAM bytearray (8 banks x 4KiB, matching the real domain size), a
    flat CartRAM bytearray, a frame counter, a captured button log and an exit flag."""

    def __init__(self, lua, *, rom_sha1=ROM_SHA1, cart_size=0x8000):
        self.lua = lua
        self.bus = bytearray(0x8000)
        self.cart = bytearray(cart_size)
        self.frame = 0
        self.buttons_log = []
        self.speeds = []
        self.exited = False
        self.rom_sha1 = rom_sha1
        self.systemid_value = "GBC"
        self.advance_hook = None  # optional callable(frame) -> mutate self.bus/cart mid-settle

    def table(self):
        return self.lua.table(read_range=self.read_range, domain_size=self.domain_size,
                              advance=self.advance, framecount=self.framecount,
                              set_buttons=self.set_buttons, romhash=self.romhash,
                              systemid=self.systemid, speed=self.speed, exit=self.exit)

    def read_range(self, addr, n, domain):
        addr, n = int(addr), int(n)
        source = self.bus if str(domain) == "WRAM" else self.cart if str(domain) == "CartRAM" else None
        assert source is not None, f"unexpected domain {domain!r}"
        return self.lua.table_from(list(source[addr:addr + n]))

    def domain_size(self, domain):
        return {"WRAM": len(self.bus), "CartRAM": len(self.cart)}[str(domain)]

    def advance(self):
        self.frame += 1
        if self.advance_hook:
            self.advance_hook(self.frame, self)

    def framecount(self):
        return self.frame

    def set_buttons(self, buttons):
        self.buttons_log.append(dict(buttons) if buttons else {})

    def romhash(self):
        return self.rom_sha1

    def systemid(self):
        return self.systemid_value

    def speed(self, _p):
        self.speeds.append(_p)

    def exit(self):
        self.exited = True


def put(bus_or_cart, profile, symbol, data, *, cart=False):
    addr = profile["ram"][symbol] if not cart else profile["ram"][symbol]
    if cart:
        bank = profile["sram_bank"][symbol]
        flat = bank * 0x2000 + addr - 0xA000
        bus_or_cart[flat:flat + len(data)] = data
        return flat
    bank = profile["ram_bank"][symbol]
    offset = wram_offset(addr, bank)
    bus_or_cart[offset:offset + len(data)] = data
    return offset


def _fresh_party_record(species_id=158, ot_id=0x1234, level=5):
    """A minimal but structurally valid 48-byte party record: enough non-zero DV/level/HP fields
    that decoding produces a real record rather than an all-zero degenerate one."""
    record = bytearray(48)
    record[0] = species_id            # MON_SPECIES
    record[1] = 0                     # MON_ITEM
    record[2:6] = bytes((1, 2, 3, 4))  # MON_MOVES
    record[6:8] = ot_id.to_bytes(2, "big")  # MON_OT_ID
    record[8:11] = (135).to_bytes(3, "big")  # MON_EXP
    # MON_HP_EXP..MON_SPC_EXP (offsets 11..21): stat exp, left zero
    record[21:23] = (0x2AAA).to_bytes(2, "big")  # MON_DVS: shiny-and-female-leaning vector
    # MON_PP (23..27), MON_HAPPINESS (27), MON_POKERUS (28..31): left zero
    record[31] = level                 # MON_LEVEL
    record[32:34] = bytes((0, 0))      # MON_STATUS (2 bytes: status + an unused byte)
    record[34:36] = (20).to_bytes(2, "big")   # MON_HP
    record[36:38] = (20).to_bytes(2, "big")   # MON_MAXHP
    record[38:40] = (10).to_bytes(2, "big")   # MON_ATK
    record[40:42] = (10).to_bytes(2, "big")   # MON_DEF
    record[42:44] = (10).to_bytes(2, "big")   # MON_SPD
    record[44:46] = (10).to_bytes(2, "big")   # MON_SAT
    record[46:48] = (10).to_bytes(2, "big")   # MON_SDF
    return bytes(record)


def place_one_mon_party(bus, profile, *, species_id=158, ot_id=0x1234):
    put(bus, profile, "wPartyCount", bytes([1]))
    put(bus, profile, "wPartySpecies", bytes([species_id, 255]))
    put(bus, profile, "wPartyMons", _fresh_party_record(species_id=species_id, ot_id=ot_id))
    put(bus, profile, "wPartyMonOTs", bytes([0x80] + [0xAA] * 10))
    put(bus, profile, "wPartyMonNicknames", bytes([0x81] + [0xBB] * 10))


def place_empty_box(cart, profile, symbol):
    """count=0, terminator immediately after; the rest of the (already zeroed) box is unused."""
    put(cart, profile, symbol, bytes([0, 255]), cart=True)


def place_all_boxes_empty(cart, profile):
    place_empty_box(cart, profile, "sBox")
    for entry in profile["storage_boxes"]:
        flat = entry["bank"] * 0x2000 + entry["addr"] - 0xA000
        cart[flat] = 0
        cart[flat + 1] = 255


@pytest.fixture
def gate():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.globals().SLINK_GEN2_GATE_LIBRARY = True
    module = lua.eval("dofile")(GATE.as_posix())
    return lua, module


def env_getenv(lua, overrides=None):
    env = {"SLINK_ROOT": str(REPO).replace("\\", "/"), "SLINK_GEN2_TITLE": TITLE,
           "SLINK_GEN2_ROM_SHA1": ROM_SHA1, "SLINK_GEN2_CORE_MODE": "CGB", "SLINK_GEN2_COLD": "0"}
    env.update(overrides or {})
    return lua.eval("function(t) return function(k) return t[k] end end")(lua.table_from(env))


def test_wram_offset_matches_pan_docs_bank_windows(gate):
    _lua, G = gate
    assert G.wram_offset(0, 0xC000, 1) == 0
    assert G.wram_offset(0, 0xCFFF, 1) == 0xFFF
    assert G.wram_offset(1, 0xD000, 1) == 0x1000
    assert G.wram_offset(7, 0xDFFF, 1) == 0x7FFF
    with pytest.raises(LuaError):
        G.wram_offset(0, 0xD000, 1)  # bank 0 does not cover the switchable window


def test_inputs_requires_every_binding_and_refuses_a_cold_boot(gate):
    lua, G = gate
    env = G.inputs(env_getenv(lua))
    assert env.title == TITLE and env.rom_sha1 == ROM_SHA1
    for missing in ("SLINK_GEN2_TITLE", "SLINK_GEN2_ROM_SHA1", "SLINK_GEN2_CORE_MODE", "SLINK_GEN2_COLD"):
        with pytest.raises(LuaError):
            G.inputs(env_getenv(lua, {missing: None}))
    with pytest.raises(LuaError, match="WARM"):
        G.inputs(env_getenv(lua, {"SLINK_GEN2_COLD": "1"}))
    with pytest.raises(LuaError):
        G.inputs(env_getenv(lua, {"SLINK_GEN2_CORE_MODE": "DMG"}))
    with pytest.raises(LuaError):
        G.inputs(env_getenv(lua, {"SLINK_GEN2_TITLE": "emerald"}))


def test_io_binding_reads_the_right_wram_bank_and_cartram_passthrough(gate):
    lua, G = gate
    profile = lua.table_from(profile_row(), recursive=True)
    api = FakeApi(lua)
    place_one_mon_party(api.bus, profile_row())
    api.cart[100] = 0x42
    io_ = G.io(api.table(), profile)
    party_addr = profile_row()["ram"]["wPartyCount"]
    got = io_.read_range(party_addr, 1, "System Bus")
    assert got[1] == 1  # party count we placed
    assert io_.read_range(100, 1, "CartRAM")[1] == 0x42
    assert io_.bank_valid(profile_row()["ram_bank"]["wPartyCount"], party_addr, 1) is True
    assert io_.bank_valid(99, party_addr, 1) is False
    with pytest.raises(LuaError):
        io_.read_range(0xC001, 1, "System Bus")  # not a profile symbol address


def test_dump_records_frame_domain_and_ranges(gate):
    lua, G = gate
    profile = lua.table_from(profile_row(), recursive=True)
    api = FakeApi(lua)
    place_one_mon_party(api.bus, profile_row())
    api.frame = 77
    io_ = G.io(api.table(), profile)
    dump = G.dump(api.table(), profile, io_)
    assert dump.frame == 77
    assert dump.party.domain == "System Bus"
    assert dump.party.address == profile_row()["ram"]["wPartyCount"]
    assert dump.party.length == (profile_row()["ram"]["wPartyMonNicknamesEnd"]
                                 - profile_row()["ram"]["wPartyCount"])
    assert dump.cartram.domain == "CartRAM" and dump.cartram.address == 0 and dump.cartram.length == 0x8000
    # the first byte of the party hex is the count we placed (1)
    assert dump.party.hex[:2] == "01"


def test_raw_fields_reads_badges_boxnum_and_battle_independently(gate):
    lua, G = gate
    profile = lua.table_from(profile_row(), recursive=True)
    api = FakeApi(lua)
    row = profile_row()
    put(api.bus, row, "wJohtoBadges", bytes([0x03]))
    put(api.bus, row, "wKantoBadges", bytes([0x00]))
    put(api.bus, row, "wCurBox", bytes([5]))
    put(api.bus, row, "wBattleMode", bytes([2]))
    put(api.bus, row, "wOtherTrainerClass", bytes([9]))
    put(api.bus, row, "wOtherTrainerID", bytes([1]))
    io_ = G.io(api.table(), profile)
    raw = G.raw_fields(profile, io_)
    assert raw.badges.johto == 3 and raw.badges.kanto == 0
    assert raw.boxnum == 5
    assert raw.battle.mode == 2 and raw.battle.trainer_class == 9 and raw.battle.trainer_id == 1


def test_raw_fields_omits_trainer_fields_outside_battle(gate):
    lua, G = gate
    profile = lua.table_from(profile_row(), recursive=True)
    api = FakeApi(lua)
    row = profile_row()
    put(api.bus, row, "wJohtoBadges", bytes([0, 0]))
    put(api.bus, row, "wCurBox", bytes([0]))
    put(api.bus, row, "wBattleMode", bytes([0]))
    io_ = G.io(api.table(), profile)
    raw = G.raw_fields(profile, io_)
    assert raw.battle.mode == 0
    assert raw.battle.trainer_class is None


@pytest.mark.parametrize("dv_word,ratio,gender,shiny", [
    (0x2AAA, 31, "male", True),       # attack=2 (bit1 set), def/spd/spc=10 -> shiny; combined=42>31 -> male
    (0x0000, 31, "female", False),    # all-zero DVs: not shiny; combined=0<=31 -> female
    (0x0000, 255, "genderless", False),
    (0x0000, 254, "female", False),
    (0x0000, 0, "male", False),
])
def test_gender_and_shiny_matches_source_formula(gate, dv_word, ratio, gender, shiny):
    _lua, G = gate
    got_gender, got_shiny = G.gender_and_shiny(dv_word, ratio)
    assert (got_gender, got_shiny) == (gender, shiny)


def test_settle_succeeds_immediately_when_the_party_is_already_present(gate):
    lua, G = gate
    profile = lua.table_from(profile_row(), recursive=True)
    api = FakeApi(lua)
    place_one_mon_party(api.bus, profile_row())
    io_ = G.io(api.table(), profile)
    Reads = lua.eval("dofile")((REPO / "lua/gen2/reads.lua").as_posix())
    reads = Reads.new(profile, io_)
    ok, frame = G.settle(api.table(), reads)
    assert ok is True and frame == 1


def test_settle_presses_a_until_the_party_appears_then_stops(gate):
    lua, G = gate
    profile = lua.table_from(profile_row(), recursive=True)
    api = FakeApi(lua)

    def reveal_after_ten(frame, api_ref):
        if frame == 10:
            place_one_mon_party(api_ref.bus, profile_row())
    api.advance_hook = reveal_after_ten
    io_ = G.io(api.table(), profile)
    Reads = lua.eval("dofile")((REPO / "lua/gen2/reads.lua").as_posix())
    reads = Reads.new(profile, io_)
    ok, frame = G.settle(api.table(), reads)
    assert ok is True and frame == 11  # read_party() is checked again right after frame 10's advance
    assert any(b.get("A") for b in api.buttons_log)


def test_settle_fails_closed_when_the_party_never_appears(gate):
    lua, G = gate
    profile = lua.table_from(profile_row(), recursive=True)
    api = FakeApi(lua)
    io_ = G.io(api.table(), profile)
    Reads = lua.eval("dofile")((REPO / "lua/gen2/reads.lua").as_posix())
    reads = Reads.new(profile, io_)
    G.BOOT_SETTLE_FRAMES = 20  # bound the test; production value is 1800
    ok, frame = G.settle(api.table(), reads)
    assert ok is False and frame == 20


def test_main_emits_pass_checkpoint_and_a_full_dump(gate, tmp_path):
    lua, G = gate
    G.BOOT_SETTLE_FRAMES = 50
    api = FakeApi(lua)
    place_one_mon_party(api.bus, profile_row())
    place_all_boxes_empty(api.cart, profile_row())
    getenv = env_getenv(lua)
    result_path = REPO / G.RESULT
    result_path.parent.mkdir(parents=True, exist_ok=True)
    G.main(api.table(), getenv)
    text = result_path.read_text(encoding="utf-8")
    assert text.splitlines()[-1].startswith("RESULT: PASS")
    assert "CHECKPOINT reached" in text
    dump = json.loads(next(line[5:] for line in text.splitlines() if line.startswith("DUMP ")))
    assert dump["party"]["domain"] == "System Bus" and dump["cartram"]["domain"] == "CartRAM"
    assert isinstance(dump["frame"], int)
    party = json.loads(next(line[10:] for line in text.splitlines() if line.startswith("PARTY_LUA ")))
    assert party["count"] == 1 and party["mons"][0]["species_id"] == 158
    for index in range(14):
        assert f"BOX_LUA_{index} " in text


def test_main_fails_closed_on_a_wrong_rom_hash(gate):
    lua, G = gate
    api = FakeApi(lua, rom_sha1="0" * 40)
    getenv = env_getenv(lua)
    result_path = REPO / G.RESULT
    result_path.parent.mkdir(parents=True, exist_ok=True)
    G.main(api.table(), getenv)
    text = result_path.read_text(encoding="utf-8")
    assert text.splitlines()[-1].startswith("RESULT: FAIL")
    assert "wrong ROM" in text.splitlines()[-1]


def test_main_fails_closed_on_missing_environment(gate):
    lua, G = gate
    api = FakeApi(lua)
    result_path = REPO / G.RESULT
    result_path.parent.mkdir(parents=True, exist_ok=True)
    G.main(api.table(), lua.eval("function(k) return nil end"))
    text = result_path.read_text(encoding="utf-8")
    assert text.splitlines()[-1].startswith("RESULT: FAIL")
    assert "bad environment" in text.splitlines()[-1]


# =================================================================================================
# Part 2: tests/live/test_gen2_new_gates.py's importable comparators -- the first falsifier
# =================================================================================================


def _real_layout():
    return codec.Gen2Layout.from_profile(profile_wrapper(), TITLE)


def _one_mon_collection(layout, *, species_id=158, ot_id=0x1234, mutate_byte=None):
    record = bytearray(_fresh_party_record(species_id=species_id, ot_id=ot_id))
    if mutate_byte is not None:
        offset, xor = mutate_byte
        record[offset] ^= xor
    body = bytearray(layout.addresses["wPartyMonNicknamesEnd"] - layout.addresses["wPartyCount"])
    body[0] = 1
    body[1] = species_id
    body[2] = 255
    records = layout.addresses["wPartyMon1"] - layout.addresses["wPartyCount"]
    ots = layout.addresses["wPartyMonOTs"] - layout.addresses["wPartyCount"]
    nicks = layout.addresses["wPartyMonNicknames"] - layout.addresses["wPartyCount"]
    body[records:records + 48] = record
    body[ots:ots + 11] = bytes([0x80] + [0xAA] * 10)
    body[nicks:nicks + 11] = bytes([0x81] + [0xBB] * 10)
    return codec.decode_party(bytes(body), layout)


def _as_lua_shaped(py_collection):
    """A PYDEC decode is already shaped like the Lua one (same field names); round-trip through
    JSON to strip the dataclass-free but still-Python-only bits (none here) and prove the
    comparator works on a plain dict, exactly what json.loads(the gate's own line) would hand it."""
    return json.loads(json.dumps(py_collection))


def test_compare_collection_agrees_on_an_identical_decode():
    layout = _real_layout()
    collection = _one_mon_collection(layout)
    live.compare_collection(_as_lua_shaped(collection), collection, where="identity control")


def test_compare_collection_fails_on_a_single_mutated_byte():
    layout = _real_layout()
    baseline = _one_mon_collection(layout)
    mutated = _one_mon_collection(layout, mutate_byte=(7, 0xFF))  # inside MON_OT_ID
    with pytest.raises(AssertionError):
        live.compare_collection(_as_lua_shaped(baseline), mutated, where="mutated-byte control")


def test_compare_collection_fails_on_a_mismatched_count():
    layout = _real_layout()
    collection = _one_mon_collection(layout)
    lua_shaped = _as_lua_shaped(collection)
    lua_shaped["count"] = 0
    lua_shaped["mons"] = []
    with pytest.raises(AssertionError, match="count disagrees"):
        live.compare_collection(lua_shaped, collection, where="count control")


def test_identity_matches_refuses_the_wrong_fixtures_own_ot():
    layout = _real_layout()
    town = _one_mon_collection(layout, ot_id=0x1234)
    ot2 = _one_mon_collection(layout, ot_id=0x5678)
    assert live.identity_matches(town, 0x1234)
    assert not live.identity_matches(town, 0x5678)   # town dump checked against the ot2 identity
    assert not live.identity_matches(ot2, 0x1234)    # ot2 dump checked against the town identity


def test_gender_and_shiny_matches_the_lua_reimplementation(gate):
    _lua, G = gate
    for dv_word, ratio in ((0x2AAA, 31), (0x0000, 31), (0x0000, 255), (0x0000, 254), (0x0000, 0), (0xF000, 200)):
        lua_gender, lua_shiny = G.gender_and_shiny(dv_word, ratio)
        py_gender, py_shiny = live.gender_and_shiny(dv_word, ratio)
        assert (lua_gender, lua_shiny) == (py_gender, py_shiny), (dv_word, ratio)


def test_tag_json_parses_the_gates_own_line_shape():
    text = "  [ok] something\nDUMP {\"frame\": 5, \"party\": {\"domain\": \"System Bus\"}}\nRESULT: PASS x (0 checks failed)\n"
    dump = live.tag_json(text, "DUMP")
    assert dump == {"frame": 5, "party": {"domain": "System Bus"}}
    with pytest.raises(AssertionError, match="no 'MISSING' line"):
        live.tag_json(text, "MISSING")


def test_fixture_and_rom_missing_reasons_are_never_silent(tmp_path):
    reason = live.fixture_missing_reason("crystal_town", repo=tmp_path)
    assert reason and "crystal_town.SaveRAM" in reason

    reason = live.rom_missing_reason("crystal", repo=tmp_path)
    assert reason and "crystal" in reason
