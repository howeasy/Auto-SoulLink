"""Run unchanged RR client Lua against synthetic BizHawk memory, never an emulator.

Only host surfaces (RAM/ROM reads, frame count, socket, input and presentation) are
faked. Production memory_gba, mailbox, game detection, profile and area modules are
loaded unchanged. Native ARM effects are NOT emulated: cases explicitly supply an
engine state/ACK boundary and test what the actual client does with that evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lupa import LuaRuntime


class HarnessError(RuntimeError):
    pass


HOST = r"""
_RR_RAM = {}; _RR_FRAME = 0; _RR_LOGS = {}; _RR_SENT = {}; _RR_RESPONSES = {}
_RR_WRITES = {}; _RR_VIOLATIONS = {}; _RR_CALLBACK = nil
local function address(a, domain)
    assert(type(a) == "number" and a % 1 == 0 and a >= 0 and a <= 0xFFFFFFFF,
           "invalid synthetic memory address")
    if domain == "ROM" then return 0x08000000 + a end
    assert(domain == nil or domain == "System Bus", "unsupported synthetic memory domain")
    return a
end
local function r8(a, domain) return _RR_RAM[address(a, domain)] or 0 end
local function r16(a, domain) return r8(a,domain) | (r8(a+1,domain) << 8) end
local function r32(a, domain) return r16(a,domain) | (r16(a+2,domain) << 16) end
local function w8(a, value, domain)
    a = address(a,domain)
    if not ((a >= 0x02000000 and a < 0x02040000) or (a >= 0x03000000 and a < 0x03008000)) then
        _RR_VIOLATIONS[#_RR_VIOLATIONS+1] = a
        error(string.format("production write outside synthetic RAM: 0x%08X", a))
    end
    assert(type(value)=="number", "non-numeric write")
    _RR_WRITES[#_RR_WRITES+1] = {frame=_RR_FRAME, address=a, before=_RR_RAM[a] or 0, value=value & 255}
    _RR_RAM[a] = value & 255
end
memory = {
    read_u8=r8, read_u16_le=r16, read_u32_le=r32,
    read_s8=function(a,d) local v=r8(a,d);return v>=128 and v-256 or v end,
    read_s16_le=function(a,d) local v=r16(a,d);return v>=32768 and v-65536 or v end,
    write_u8=w8,
    write_u16_le=function(a,v,d) w8(a,v,d);w8(a+1,v>>8,d) end,
    write_u32_le=function(a,v,d) for i=0,3 do w8(a+i,v>>(i*8),d) end end,
    getmemorydomainlist=function() return {"System Bus","ROM"} end,
}
console={log=function(s) _RR_LOGS[#_RR_LOGS+1]=tostring(s) end, clear=function() end}
emu={framecount=function() return _RR_FRAME end, getsystemid=function() return "GBA" end}
event={onframeend=function(fn,name) assert(_RR_CALLBACK==nil,"duplicate callback");_RR_CALLBACK=fn end}
input={get=function() return {} end}
gui=setmetatable({}, {__index=function() return function() end end})
local presentation=setmetatable({}, {__index=function() return function() end end})
local connector={
    init=function() end, pump=function() end, connected=function() return true end,
    send=function(s) _RR_SENT[#_RR_SENT+1]=s;return true end,
    receive=function() return table.remove(_RR_RESPONSES,1) end,
}
-- These are host-facing dependencies only. No production function is replaced.
package.preload["connector"]=function() return connector end
package.preload["hud"]=function() return presentation end
package.preload["peer_ghost_npc"]=function()
    return {init=function() end,on_frame=function() end,consume_interact=function() return false end}
end
function _rr_step()
    _RR_FRAME=_RR_FRAME+1
    assert(_RR_CALLBACK,"client did not register its frame callback")
    _RR_CALLBACK()
end
"""


class RRHarness:
    SOURCES = (
        "lua/clients/gen3_frlge_client.lua",
        "lua/memory_gba.lua",
        "lua/mailbox.lua",
        "lua/json_codec.lua",
        "lua/game_detect.lua",
        "lua/games/gen3_frlge.lua",
        "data/games/gen3_frlge/gen3_frlge_areas.lua",
        "data/games/gen3_frlge/gen3_frlge_locations.lua",
    )
    SB1 = 0x02010000
    SB2 = 0x02014000

    def __init__(self, repo: Path, *, party=(111,), load=True):
        self.repo = Path(repo).resolve()
        self.sources = self.SOURCES + tuple(
            path.relative_to(self.repo).as_posix()
            for path in sorted((self.repo / "lua/rr").glob("*.lua"))
        )
        for relative in self.sources:
            if not (self.repo / relative).is_file():
                raise HarnessError(f"Missing production source: {self.repo / relative}")
        self._source_hashes = self._hash_sources()
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(HOST)
        roots = [
            self.repo / "lua",
            self.repo / "lua/games",
            self.repo / "data/games/gen3_frlge",
        ]
        self.lua.globals().package.path = ";".join(p.as_posix() + "/?.lua" for p in roots)
        self.seed(0x080000AC, b"BPRE")
        self.seed(0x08000108, b"pokemon red version\0")
        # Static ROM discriminator, not a supplied copyrighted ROM.
        self.seed_u32(0x080001BC, 0x08100000)
        self.M = self.lua.eval('require("memory_gba")')
        if isinstance(self.M, tuple):
            self.M = self.M[0]
        self.G = self.lua.eval('require("games.gen3_frlge")')
        if isinstance(self.G, tuple):
            self.G = self.G[0]
        self.M.applyProfile(self.G.profiles.radical_red, "radical_red")
        self.seed_u32(self.M.SB1_PTR_ADDR, self.SB1)
        self.seed_u32(self.M.SB2_PTR_ADDR, self.SB2)
        self.seed(self.SB2, bytes([0xBB, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]))
        self.set_area(19)
        self.seed_u16(self.M.BALL_POCKET_ADDR, 4)
        self.seed_u16(self.M.BALL_POCKET_ADDR + 2, 10)
        self.seed_u8(self.M.PARTY_COUNT_ADDR, len(party))
        for i, pid in enumerate(party):
            self.set_mon(i, pid)
        self.set_battler(0, party[0])
        self.set_battle(False)
        self.seed_u32(self.M.BATTLE_MAIN_FUNC_ADDR, self.M.RETURN_FROM_BATTLE_ADDR)
        self.seed_u8(self.M.POKEMON_STORAGE_BASE, 0)
        # A valid matching companion beacon. ARM handler effects remain explicit fixtures.
        self.seed_u32(0x0203F800, 0x4B4E4C53)
        self.MB = self.lua.eval('require("mailbox")')
        if isinstance(self.MB, tuple):
            self.MB = self.MB[0]
        self.seed_u16(0x0203F804, int(self.MB.ABI))
        self.seed_u32(0x030030F4, 0x080565B5)
        self.loaded = False
        if load:
            self.load_client()

    def load_client(self, *, expect_patch=True):
        if self.loaded:
            raise HarnessError(
                "Each harness loads production once; use a fresh instance for reload cases"
            )
        path = self.repo / self.SOURCES[0]
        self.lua.execute(path.read_text(encoding="utf-8"), name="@" + path.as_posix())
        self.M = self.lua.globals().package.loaded["memory_gba"]
        self.MB = self.lua.globals().package.loaded["mailbox"]
        if self.M.profile_name != "radical_red" or bool(self.MB.present()) != expect_patch:
            raise HarnessError("Production RR detection or expected patch availability differs")
        valid = self.M.validateROM()
        if isinstance(valid, tuple):
            valid = valid[0]
        if not valid:
            raise HarnessError("Synthetic RR save failed actual validateROM")
        self.loaded = True
        self.assert_healthy()

    @property
    def frame(self):
        return int(self.lua.globals()._RR_FRAME)

    @staticmethod
    def key(pid, ot=222):
        return f"{pid:08X}:{ot:08X}"

    def seed(self, addr, data):
        """Engine fixture write; bypasses the log of production-origin writes."""
        for i, value in enumerate(data):
            self.lua.globals()._RR_RAM[addr + i] = value

    def seed_u8(self, a, v):
        self.seed(a, bytes([v]))

    def seed_u16(self, a, v):
        self.seed(a, int(v).to_bytes(2, "little"))

    def seed_u32(self, a, v):
        self.seed(a, int(v).to_bytes(4, "little"))

    def bytes(self, a, n):
        return bytes(self.lua.globals().memory.read_u8(a + i) for i in range(n))

    def u8(self, a):
        return int(self.lua.globals().memory.read_u8(a))

    def u16(self, a):
        return int(self.lua.globals().memory.read_u16_le(a))

    def set_area(self, map_num):
        self.seed(self.SB1 + 4, bytes([3, map_num]))

    def set_mon(self, slot, pid, hp=50, *, ot=222, species=25):
        a = int(self.M.PARTY_BASE + slot * self.M.MON_SIZE)
        raw = bytearray(100)
        raw[0:4] = pid.to_bytes(4, "little")
        raw[4:8] = ot.to_bytes(4, "little")
        raw[8:18] = bytes([0xBB] + [0xFF] * 9)
        raw[0x12] = 2
        raw[0x13] = 2
        raw[0x14:0x1B] = bytes([0xBB] + [0xFF] * 6)
        raw[0x20:0x22] = species.to_bytes(2, "little")
        raw[0x24:0x28] = (8000).to_bytes(4, "little")
        raw[0x29] = 70
        raw[0x2C:0x2E] = (33).to_bytes(2, "little")
        raw[0x34] = 35
        raw[0x48:0x4C] = (0x3FFFFFFF).to_bytes(4, "little")
        raw[0x54] = 20
        raw[0x56:0x58] = hp.to_bytes(2, "little")
        for off in [0x58, 0x5A, 0x5C, 0x5E, 0x60, 0x62]:
            raw[off : off + 2] = (50).to_bytes(2, "little")
        self.seed(a, raw)

    def set_battler(self, slot, pid, hp=50, *, ot=222, battler=0):
        a = int(self.M.BATTLE_MONS_ADDR + battler * self.M.BATTLE_MON_SIZE)
        self.seed_u16(self.M.BATTLER_PARTY_INDEXES_ADDR + battler * 2, slot)
        self.seed_u8(self.M.BATTLERS_COUNT_ADDR, 2)
        self.seed_u16(a, 25)
        self.seed_u16(a + self.M.BATTLE_MON_HP_OFF, hp)
        self.seed_u8(a + 0x2A, 20)
        self.seed_u16(a + 0x2C, 50)
        self.seed_u32(a + self.M.BATTLE_MON_PERS_OFF, pid)
        self.seed_u32(a + self.M.BATTLE_MON_OTID_OFF, ot)
        for i in range(7):
            self.seed_u8(a + self.M.BATTLE_MON_STAT_STAGES_OFF + i, 6)

    def set_battle(self, active, *, outcome=4, flags=0):
        self.seed_u8(self.M.BATTLE_OUTCOME_ADDR, 0 if active else outcome)
        self.seed_u32(self.M.BATTLE_TYPE_ADDR, flags)

    def set_faint_counter(self, count):
        self.seed_u8(self.M.BATTLE_RESULTS_ADDR + self.M.BATTLE_RESULTS_PLAYER_FAINTS_OFF, count)

    def command(self, name, **fields):
        packet = json.dumps({"commands": [{"cmd": name, **fields}]}, separators=(",", ":"))
        queue = self.lua.globals()._RR_RESPONSES
        queue[len(queue) + 1] = packet

    def pending_native(self):
        return {
            "opcode": self.u16(0x0203F806),
            "seq": self.u16(0x0203F808),
            "args": list(self.bytes(0x0203F810, 3)),
        }

    def engine_ack(self, *, ok, reason=0):
        """Inject the engine's mailbox completion boundary; does not pretend to execute ARM."""
        command = self.pending_native()
        if not command["opcode"]:
            raise HarnessError("No native opcode to acknowledge")
        # ABI2 reservations are echoed before terminal publication by the native
        # handler. The host fixture must supply that same completion evidence.
        self.seed(0x0203F838, self.bytes(0x0203F828, 8))
        self.seed_u16(0x0203F80E, reason)
        self.seed_u16(0x0203F80C, command["seq"])
        self.seed_u16(0x0203F806, 0)
        self.seed_u16(0x0203F80A, int(self.MB.ST_OK if ok else self.MB.ST_FAIL))

    def native_event(self, kind, a=0, b=0):
        """Supply one native EvRing entry; production events_drain does the reading."""
        base = int(self.MB.EVR)
        wr, rd = self.u8(base), self.u8(base + 1)
        if (wr - rd) % 256 >= 8:
            raise HarnessError("Native event fixture exceeded the eight-slot ring")
        self.seed_u32(base + 8 + (wr % 8) * 4, int(kind) | (a << 8) | (b << 16))
        self.seed_u8(base, (wr + 1) % 256)

    @staticmethod
    def compressed_fixture(raw):
        """Independent representation fixture; does not execute or replace Lua code."""
        moves = [int.from_bytes(raw[0x2C + i * 2 : 0x2E + i * 2], "little") for i in range(4)]
        packed = sum((move & 1023) << (10 * i) for i, move in enumerate(moves))
        return (
            raw[:28]
            + raw[0x20:0x2B]
            + packed.to_bytes(5, "little")
            + raw[0x38:0x3E]
            + raw[0x44:0x4C]
        )

    def engine_storage_effect(self, *, withdrawn_party=None):
        """Supply a successful native storage boundary, without pretending to run ARM.

        Tests explicitly provide a recomputed party blob for withdrawal. This
        exercises client readback, not the native conversion/stat calculation.
        """
        opcode = self.pending_native()["opcode"]
        args = self.bytes(0x0203F810, 14)
        count = self.u8(self.M.PARTY_COUNT_ADDR)
        base = int(self.M.PARTY_BASE)
        party = [self.bytes(base + i * 100, 100) for i in range(6)]
        if opcode in (24, 26):
            slot, box, pos = args[:3]
            self.seed(int(self.M.boxMonAddr(box, pos)), self.compressed_fixture(party[slot]))
            if opcode == 24:
                party[slot : count - 1] = party[slot + 1 : count]
            else:
                party[slot] = party[count - 1]
            party[count - 1] = bytes(100)
            for i, raw in enumerate(party):
                self.seed(base + i * 100, raw)
            self.seed_u8(self.M.PARTY_COUNT_ADDR, count - 1)
        elif opcode == 25:
            if withdrawn_party is None or len(withdrawn_party) != 100:
                raise HarnessError("Withdrawal fixture must supply engine-recomputed party bytes")
            box, pos, slot = args[:3]
            self.seed(base + slot * 100, withdrawn_party)
            self.seed(int(self.M.boxMonAddr(box, pos)), bytes(58))
            self.seed_u8(self.M.PARTY_COUNT_ADDR, count + 1)
        elif opcode == 28:
            source = int(self.M.boxMonAddr(args[0], args[1]))
            destination = int(self.M.boxMonAddr(args[2], args[13]))
            self.seed(destination, self.bytes(source, 58))
            self.seed(source, bytes(58))
        else:
            raise HarnessError(f"Not a storage operation: {opcode}")
        self.engine_ack(ok=True)

    def step(self, n=1):
        for _ in range(n):
            self.lua.globals()._rr_step()
            self.assert_healthy()

    def events(self, kind=None):
        result = [json.loads(value) for value in self.lua.globals()._RR_SENT.values()]
        return [e for e in result if kind is None or e.get("event") == kind]

    def logs(self):
        return list(self.lua.globals()._RR_LOGS.values())

    def assert_healthy(self):
        errors = [v for v in self.logs() if "ERROR (handler kept alive)" in v]
        violations = list(self.lua.globals()._RR_VIOLATIONS.values())
        if errors or violations:
            raise HarnessError(f"Invalid harness execution: {errors}; writes={violations}")

    def canary(self, addr, size=8):
        expected = bytes((0xA5 + i * 17) & 255 for i in range(size))
        self.seed(addr, expected)
        return (addr, expected)

    def check_canaries(self, *guards):
        for addr, expected in guards:
            if self.bytes(addr, len(expected)) != expected:
                raise HarnessError(f"Write-boundary canary changed at 0x{addr:08X}")

    def _hash_sources(self):
        return {
            path: hashlib.sha256((self.repo / path).read_bytes()).hexdigest()
            for path in self.sources
        }

    def manifest(self):
        if self._hash_sources() != self._source_hashes:
            raise HarnessError(
                "Production sources changed during the scenario; discard this result"
            )
        return dict(self._source_hashes)
