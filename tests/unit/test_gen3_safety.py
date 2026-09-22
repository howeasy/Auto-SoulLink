"""Pack-driven negative controls; no emulator or ROM required."""
import json
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]


class World:
    def __init__(self, title="radical_red", kind="companion"):
        folder = "gen3_rr" if title == "radical_red" else "gen3_frlg"
        self.pack = json.loads((ROOT / "data/games" / folder / "write_checkpoint.json").read_text())[title]
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute("""
            mem = {}; rom = {}; unreadable = nil
            function put(a, v, n)
                for i=0,n-1 do mem[a+i] = v % 256; v = math.floor(v/256) end
            end
            function read(a, n, domain)
                local source = domain == 'ROM' and rom or mem
                local v = 0
                for i=0,n-1 do
                    if a+i == unreadable or source[a+i] == nil then return nil end
                    v = v + source[a+i] * 256^i
                end
                return v
            end
            cpu = {R15=452, CPSR=31}; idle = true; frame = 7; writes = {}
            deps = {io={read_u8=function(a,d) return read(a,1,d) end,
                read_u16_le=function(a,d) return read(a,2,d) end,
                read_u32_le=function(a,d) return read(a,4,d) end,
                write_u8=function(a,v) writes[#writes+1]={a,v} end},
                regs=function() return cpu end, native_idle=function() return idle end,
                frame=function() return frame end}
        """)
        g = self.lua.globals()
        cpu = self.pack["cpu"]  # a parked frame end for this title
        g.cpu.R15 = cpu.get("observed_pc", cpu["pc_min"])
        g.cpu.CPSR = cpu["mode"] | cpu["thumb"] << 5
        for anchor in self.pack["anchors"].values():
            for i, byte in enumerate(bytes.fromhex(anchor["expected_hex"][kind])):
                g.rom[anchor["rom_offset"] + i] = byte
        for p in self.pack["predicates"].values():
            g.put(p["address"] + p["offset"], p["expect"], p["width"])
        for i, (name, p) in enumerate(self.pack["pointers"].items()):
            if name != "pokemon_storage_base":
                g.put(p["address"], 0x02010000 + i * 0x1000, 4)
        t = self.pack["tasks"]
        for i in range(t["count"] * t["struct_size"]):
            g.mem[t["address"] + i] = 0
        for i, fn in enumerate(t["allowed_overworld_tasks"].values()):
            base = t["address"] + i * t["struct_size"]
            g.put(base + t["func_offset"], fn | 1, 4)
            g.put(base + t["is_active_offset"], 1, 1)
        module = self.lua.execute((ROOT / "lua/gen3/safety.lua").read_text(encoding="utf-8"))
        self.safety = module.new(self.lua.table_from(self.pack, recursive=True), g.deps, kind)

    def check(self, snapshot=None):
        return self.safety.check(self.safety, snapshot)[0]


@pytest.mark.parametrize("title,kind", [("firered", "clean"), ("leafgreen", "clean"),
                                      ("radical_red", "clean"), ("radical_red", "companion")])
def test_committed_census_positive(title, kind):
    assert World(title, kind).check()


@pytest.mark.parametrize("name", ["callback1", "callback2", "field_controls_locked", "in_battle",
                                  "link_callback", "link_players_received", "link_transferring",
                                  "palette_fade_active", "save_dialog_cb", "script_context_status",
                                  "soft_reset_disabled"])
def test_each_forbidden_state(name):
    w = World()
    p = w.pack["predicates"][name]
    w.lua.globals().put(p["address"] + p["offset"], p.get("mask", p["expect"] ^ 1), p["width"])
    assert not w.check()


@pytest.mark.parametrize("r15,cpsr", [(452, 16), (452, 18), (452, 63), (16384, 31)])
def test_cpu_refuses_other_mode_thumb_or_unparked_pc(r15, cpsr):
    w = World()
    w.lua.globals().cpu.R15 = r15
    w.lua.globals().cpu.CPSR = cpsr
    assert not w.check()


@pytest.mark.parametrize("r15,cpsr,ok", [
    (0x080008AC, 0x6000003F, True),   # WaitForVBlank, System mode, Thumb (FR census row)
    (0x080008AC, 0x6000001F, False),  # same PC, T=0
    (0x0000001C, 0x00000012, False),  # BIOS IRQ vector in IRQ mode: refused on purpose
    (0x000001C4, 0x0000001F, False),  # the RR BIOS park is not an FR park
])
def test_firered_parked_cpu(r15, cpsr, ok):
    w = World("firered", "clean")
    w.lua.globals().cpu.R15 = r15
    w.lua.globals().cpu.CPSR = cpsr
    assert bool(w.check()) is ok


def test_unknown_active_task():
    w = World()
    t = w.pack["tasks"]
    w.lua.globals().put(t["address"] + t["func_offset"], 0x08000001, 4)
    assert not w.check()


@pytest.mark.parametrize("category", ["anchor", "predicate", "task", "pointer"])
def test_unreadable_input(category):
    w = World()
    p = w.pack
    address = {"anchor": p["anchors"]["cb1_overworld"]["rom_offset"],
               "predicate": p["predicates"]["callback1"]["address"],
               "task": p["tasks"]["address"] + p["tasks"]["is_active_offset"],
               "pointer": p["pointers"]["gSaveBlock1Ptr"]["address"]}[category]
    w.lua.globals().unreadable = address
    assert not w.check()


def test_rom_rechecked_and_native_idle_fail_closed():
    w = World()
    assert w.check()
    w.lua.globals().idle = False
    assert not w.check()
    w.lua.globals().idle = None
    assert not w.check()
    w.lua.globals().idle = True
    a = w.pack["anchors"]["frame_control"]["rom_offset"]
    w.lua.globals().rom[a] = w.lua.globals().rom[a] ^ 1
    assert not w.check()


@pytest.mark.parametrize("change", ["cpu=nil", "cpu.R15=nil", "cpu.CPSR=nil",
                                   "deps.native_idle=function() error('unreadable') end",
                                   "deps.io.read_u8=function() error('unreadable') end"])
def test_unavailable_dependencies_return_false(change):
    w = World()
    w.lua.execute(change)
    assert not w.check()


def test_missing_required_evidence_fails_closed():
    w = World()
    module = w.lua.execute((ROOT / "lua/gen3/safety.lua").read_text(encoding="utf-8"))
    del w.pack["predicates"]["save_dialog_cb"]
    w.safety = module.new(w.lua.table_from(w.pack, recursive=True), w.lua.globals().deps, "companion")
    assert not w.check()


def test_pointer_movement_refuses_before_write():
    w = World()
    g = w.lua.globals()
    g.deps.safety = w.safety
    module = w.lua.execute((ROOT / "lua/gen3/writes.lua").read_text(encoding="utf-8"))
    writer = module.new(g.deps)
    writer.arm(writer, "overworld", w.lua.eval("function() return true end"))
    g.put(w.pack["pointers"]["gSaveBlock1Ptr"]["address"], 0x02020000, 4)
    with pytest.raises(lupa.LuaError, match="pointer moved"):
        writer.write_u16(writer, 0x02010000, 0)
    assert len(g.writes) == 0
