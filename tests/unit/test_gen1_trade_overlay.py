"""ROM overlay bytes under lupa with the real writes.lua arm gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lupa.lua54 import LuaError, LuaRuntime

from server.adapters import gen1_codec

ROOT = Path(__file__).resolve().parents[2]
PROFILES = json.loads((ROOT / "data/games/gen1_rby/profile.json").read_text(encoding="utf-8"))["titles"]
MAGIC = bytes((0x53, 0x4C, 0x54, 0x31))  # trade_service.asm:173-185


@pytest.fixture(autouse=True)
def isolate_data_dir():
    """Override the repository's disk-writing state fixture."""
    yield


class Fake:
    def __init__(self, title="red"):
        self.ram = PROFILES[title]["ram"]
        self.derived = PROFILES[title]["derived"]
        self.memory = bytearray(65536)
        self.writes = []
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        profile = self.lua.table_from(PROFILES[title], recursive=True)
        write_io = self.lua.table_from({"write_u8": self._write_u8})
        self.write_module = self.lua.eval("dofile")((ROOT / "lua/gen1/writes.lua").as_posix())
        permit = self.lua.eval("dofile")((ROOT / "lua/write_permit.lua").as_posix())
        self.writer = self.write_module.new(profile, write_io, permit)
        make_reader = self.lua.eval("function(u,r) return {"
                                    "read_u8=function(a) return u(a) end,"
                                    "read_range=function(a,n) return r(a,n) end} end")
        reader = make_reader(lambda addr: self.memory[addr], self._read_range)
        module = self.lua.eval("dofile")((ROOT / "lua/gen1/trade_overlay.lua").as_posix())
        self.driver = module.new(profile, reader, self.writer)
        self.module = module

    def _read_range(self, addr, length):
        assert 0 <= addr <= len(self.memory) and 0 <= length <= len(self.memory) - addr
        return self.lua.table_from(list(self.memory[addr:addr + length]))

    def _write_u8(self, addr, value, domain):
        assert domain == "System Bus"
        assert 0 <= addr < len(self.memory)
        self.memory[addr] = value
        self.writes.append((addr, value))

    def call(self, name, *args):
        return getattr(self.driver, name)(self.driver, *args)

    def consume(self):
        expected = bytes(self.driver.expected[i] for i in range(1, 17))
        base = self.ram["wSerialPartyMonsPatchList"]
        backup = self.ram["wEnemyMons"] + self.derived["battle_struct_size"]
        sp = 0xDE80
        self.memory[base:base + 16] = self.memory[backup:backup + 16]
        self.memory[sp:sp + 16] = expected[::-1]
        return self.call("picked_up", sp)

    def arm(self):
        self.writer.arm(self.writer, "overworld")

    def bytes(self, values):
        return self.lua.table_from(list(values))

    def overlay(self):
        start = self.ram["wSerialPartyMonsPatchList"]
        return bytes(self.memory[start:start + 16])

    def seed_overlay(self, raw):
        assert len(raw) == 16
        start = self.ram["wSerialPartyMonsPatchList"]
        self.memory[start:start + 16] = raw


def _blob():
    b = bytearray(44)
    b[0], b[1:3], b[3], b[33] = 153, b"\x00\x1e", 12, 12
    b[12:14] = b"\xBE\xEF"
    b[27:29] = b"\xAB\xCD"
    mon = gen1_codec.decode_party_mon(b)
    assert gen1_codec.encode_party_mon(mon) == b
    return bytes(b) + gen1_codec.encode_name("TRAINER") + gen1_codec.encode_name("BULBA")


def _query(gen=23):
    # receptionist.asm:240-241 copies header then :167-173 publishes +6 last.
    return MAGIC + bytes((1, 1, gen, (gen - 1) % 256, 0, 0, 0, 0, 0, 0, 0, 0))


@pytest.mark.parametrize("title", ("red", "blue"))
def test_query_mask_token_and_ack_order(title):
    f = Fake(title)
    f.seed_overlay(_query())
    assert f.call("poll_query")["gen"] == 23
    before = f.overlay()
    with pytest.raises(LuaError, match="no armed write window"):
        f.call("answer_query", 23, 0b101001, f.bytes((1, 2, 3, 4)))
    assert f.overlay() == before and not f.writes
    f.arm()
    assert f.call("answer_query", 23, 0b101001, f.bytes((1, 2, 3, 4))) is True
    raw = f.overlay()
    assert raw == MAGIC + bytes((1, 1, 23, 23, 0, 0, 1, 0b101001, 1, 2, 3, 4))
    assert f.writes[-1] == (f.ram["wSerialPartyMonsPatchList"] + 7, 23)
    assert f.call("poll_query") is None
    f.seed_overlay(_query(24))
    assert f.call("answer_query", 24, 0, f.bytes((0, 0, 0, 0))) is True
    assert f.overlay()[10:12] == b"\x00\x00"
    assert f.call("answer_query", 24, 64, f.bytes((1, 0, 0, 0)))[0] is None


def test_offer_receipt_accept_and_reject():
    f = Fake()
    token = bytes((9, 8, 7, 6))
    f.seed_overlay(_query(29))
    f.arm()
    assert f.call("answer_query", 29, 0b001001, f.bytes(token)) is True
    # receptionist.asm:439-466 publishes cmd2, slot+9, token+12..15, gen+6 last.
    offer = MAGIC + bytes((1, 2, 30, 29, 255, 3, 0, 0)) + token
    f.seed_overlay(offer)
    assert dict(f.call("poll_offer").items()) == {"slot": 3, "gen": 30}
    f.seed_overlay(MAGIC + bytes((1, 2, 30, 29, 255, 3, 0, 0)) + bytes((9, 8, 7, 5)))
    assert f.call("poll_offer") is None  # another visit's token is not ours
    f.seed_overlay(offer)
    assert f.call("answer_offer", 30, True) is True
    assert f.overlay()[8] == 0 and f.overlay()[7] == 30
    assert f.writes[-1] == (f.ram["wSerialPartyMonsPatchList"] + 7, 30)
    assert f.call("poll_offer") is None
    f.seed_overlay(MAGIC + bytes((1, 2, 31, 30, 255, 1, 0, 0)) + token)
    assert f.call("answer_offer", 31, False) is True
    assert f.overlay()[8] == 1 and f.overlay()[7] == 31
    f.seed_overlay(MAGIC + bytes((1, 2, 32, 31, 255, 7, 0, 0)) + token)
    assert f.call("poll_offer") is None


@pytest.mark.parametrize("command", (3, 5))
def test_arm_stages_enemy_preimage_and_publishes_generation_last(command):
    f = Fake()
    original = bytes(range(16))
    f.seed_overlay(original)
    blob, name, token = _blob(), gen1_codec.encode_name("PARTNER"), bytes((4, 3, 2, 1))
    before = f.memory[:]
    with pytest.raises(LuaError, match="no armed write window"):
        f.call("arm", command, 2, f.bytes(blob), f.bytes(name), f.bytes(token))
    assert f.memory == before and not f.writes
    f.arm()
    generation = f.call("arm", command, 2, f.bytes(blob), f.bytes(name), f.bytes(token))
    assert generation == 7  # old byte+6 was 6
    r = f.ram
    assert f.memory[r["wEnemyPartyCount"]] == 1
    assert f.memory[r["wEnemyPartySpecies"]:r["wEnemyPartySpecies"] + 2] == bytes((153, 255))
    assert bytes(f.memory[r["wEnemyMons"]:r["wEnemyMons"] + 44]) == blob[:44]
    assert gen1_codec.decode_party_mon(blob[:44])["ot_id"] == 0xBEEF
    assert bytes(f.memory[r["wEnemyMonOT"]:r["wEnemyMonOT"] + 11]) == blob[44:55]
    assert bytes(f.memory[r["wEnemyMonNicks"]:r["wEnemyMonNicks"] + 11]) == blob[55:66]
    assert bytes(f.memory[r["wLinkEnemyTrainerName"]:r["wLinkEnemyTrainerName"] + 11]) == name
    assert bytes(f.memory[r["wEnemyMons"] + 44:r["wEnemyMons"] + 60]) == original
    assert f.overlay() == MAGIC + bytes((1, command, 7, 6, 255, 2, 1, 0)) + token
    assert f.writes[-1] == (r["wSerialPartyMonsPatchList"] + 6, 7)
    assert f.call("clobbered") is False
    assert f.call("picked_up") is False  # a service poll is not consumption
    assert f.consume() is True
    f.memory[r["wSerialPartyMonsPatchList"] + 2] ^= 1  # native owns scratch now
    assert f.call("clobbered") is False
    assert dict(f.call("service_address").items()) == {"bank": 0x3F, "addr": 0x4500}


def test_done_release_token_and_uncertain_result():
    f = Fake()
    f.seed_overlay(bytes(16))
    f.arm()
    gen = f.call("arm", 5, 1, f.bytes(_blob()),
                 f.bytes(gen1_codec.encode_name("PARTNER")), f.bytes((1, 0, 0, 0)))
    assert f.call("poll_done") is None
    start = f.ram["wSerialPartyMonsPatchList"]
    f.memory[start + 5], f.memory[start + 8], f.memory[start + 7] = 7, 2, gen
    assert f.call("poll_done")["result"] == 2
    assert f.call("clobbered") is False  # native DONE is progress, not a scratch overwrite
    assert f.call("release", gen)[0] is None  # uncertain append must not release
    f.memory[start + 8] = 0
    assert f.call("release", (gen + 1) % 256)[0] is None
    f.writer.disarm(f.writer)
    with pytest.raises(LuaError, match="no armed write window"):
        f.call("release", gen)
    assert f.memory[start + 5] == 7
    f.arm()
    assert f.call("release", gen) is True
    assert f.memory[start + 5] == 8  # service.asm:142-143
    assert f.call("clobbered") is False


def test_clobber_detection_and_rearm_uses_new_local_preimage():
    f = Fake()
    f.seed_overlay(bytes((42,) * 16))
    f.arm()
    token = f.bytes((1, 2, 3, 4))
    name = f.bytes(gen1_codec.encode_name("PARTNER"))
    first = f.call("arm", 3, 0, f.bytes(_blob()), name, token)
    assert first == 43
    f.memory[f.ram["wSerialPartyMonsPatchList"] + 2] ^= 1  # player step borrowed tile scratch
    assert f.call("clobbered") is True
    new_preimage = f.overlay()
    second = f.call("arm", 3, 0, f.bytes(_blob()), name, token)
    assert second == 44
    assert f.call("clobbered") is False
    assert bytes(f.memory[f.ram["wEnemyMons"] + 44:f.ram["wEnemyMons"] + 60]) == new_preimage


def test_service_address_follows_the_profile_trade_block():
    f = Fake()
    assert dict(f.module.service_address().items()) == {"bank": 0x3F, "addr": 0x4500}
    overlay = f.lua.table_from({**PROFILES["red"], "trade": {"service": {"bank": 0x3E, "addr": 0x5000}}},
                               recursive=True)
    driver = f.module.new(overlay, f.lua.eval("function() return {read_u8=function() return 0 end,"
                                              "read_range=function() return {} end} end")(), f.writer)
    assert dict(driver.service_address().items()) == {"bank": 0x3E, "addr": 0x5000}
