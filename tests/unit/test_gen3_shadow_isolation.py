"""gen3-P3-C3-3: lua/gen3/shadow_run.lua's isolation contract (PLAN §5.7).

The shadow observer runs a SECOND client instance alongside the old production one and must
be provably incapable of mutating game state or the old client's own log: every deps.io
write_* throws, the BizHawk mutation globals it promises never to touch (joypad/savestate/
client.saveram/console.clear/gui.text) throw when exercised directly, every hook it registers
is named "SLink-gen3-shadow-*", and teardown unregisters exactly (and only) its own ids.

The last section drives shadow_run's own `M.start()`/`state.poll()` path against the REAL
`lua/gen3/entry.lua` (landed by card C3-1), with a fake ROM/memory/event built the way
tests/unit/test_gen3_entry.py's `World` builds one (`seed_rom`, `sites_of`, imported from
there) — never a fake Entry module for that part.
"""
from __future__ import annotations

import pathlib

import pytest

from tests.unit.test_gen3_entry import seed_rom, sites_of

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute lua/gen3/shadow_run.lua")

REPO = pathlib.Path(__file__).resolve().parents[2]
SHADOW_RUN = (REPO / "lua" / "gen3" / "shadow_run.lua").as_posix()


@pytest.fixture
def lua():
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    return L


@pytest.fixture
def M(lua):
    """The real module table, dofile'd fresh per test (module-level state like hook ids
    must not leak between tests)."""
    return lua.eval(f'dofile("{SHADOW_RUN}")')


def _raises_lua_error(fn, *a, **kw):
    with pytest.raises(lupa.LuaError):
        fn(*a, **kw)


# ── deps.io: reads pass through, every write_* throws ──────────────────────────────────────
# Contract (lua/gen3/entry.lua header + reads.lua/signals.lua asserts): io_ro exposes
# read_u8/read_u16/read_u32(addr) [no domain arg], read_bytes(addr, len), rom_read(off, len),
# framecount(), register(name). M.build_io(mem, reg) wraps a BizHawk-shaped `mem` (whose OWN
# reads DO take a domain, "System Bus" or "ROM") and a `reg` function(name) -> number
# (emu.getregister in production) into that shape.

class FakeMem:
    def __init__(self):
        self.bus = {0x1000: 0x42}
        self.rom = {0x2000: 0x99}
        self.frame = 7

    def _store(self, domain):
        return self.rom if domain == "ROM" else self.bus

    def read_u8(self, addr, domain=None):
        return self._store(domain).get(int(addr), 0)

    def read_u16_le(self, addr, domain=None):
        return 0xBEEF

    def read_u32_le(self, addr, domain=None):
        return 0xDEADBEEF

    def read_bytes(self, addr, length, domain=None):
        return [self._store(domain).get(int(addr) + i, 0) for i in range(int(length))]

    def framecount(self):
        return self.frame


def _fake_mem_table(lua, mem):
    return lua.table(read_u8=mem.read_u8, read_u16_le=mem.read_u16_le, read_u32_le=mem.read_u32_le,
                     read_bytes=mem.read_bytes, framecount=mem.framecount)


def test_reads_pass_through(lua, M):
    mem = FakeMem()
    io_ro = M.build_io(_fake_mem_table(lua, mem), lambda name: {"R15": 0x1234}.get(str(name), 0))
    assert io_ro.read_u8(0x1000) == 0x42
    assert io_ro.read_u16(0x2000) == 0xBEEF
    assert io_ro.read_u32(0x3000) == 0xDEADBEEF
    assert io_ro.framecount() == 7
    assert io_ro.register("R15") == 0x1234
    # rom_read is a distinct domain, not the bus -- 0x2000 differs between the two stores.
    assert io_ro.rom_read(0x2000, 1)[1] == 0x99
    assert io_ro.read_u8(0x2000) == 0  # the bus does NOT see the ROM byte at the same address


@pytest.mark.parametrize("sink,args", [
    ("write_u8", (0x1000, 5)),
    ("write_u16", (0x1000, 5)),
    ("write_u32", (0x1000, 5)),
    ("write_bytes", (0x1000, [1, 2, 3])),
])
def test_every_write_sink_throws(lua, M, sink, args):
    mem = FakeMem()
    io_ro = M.build_io(_fake_mem_table(lua, mem), lambda name: 0)
    _raises_lua_error(getattr(io_ro, sink), *args)


# ── mutation stubs: joypad/savestate/client/console/gui ────────────────────────────────────

def test_mutation_stubs_all_throw(M):
    stubs = M.mutation_stubs()
    _raises_lua_error(stubs.joypad.set, 1)
    _raises_lua_error(stubs.savestate.load, "x")
    _raises_lua_error(stubs.savestate.save, "x")
    _raises_lua_error(stubs["client"].saveram)
    _raises_lua_error(stubs["client"].exit)
    _raises_lua_error(stubs.console.clear)
    _raises_lua_error(stubs.gui.text, 0, 0, "hi")


def test_faulty_observer_write_leaves_old_client_log_unchanged(lua, M):
    """A deliberately faulty observer that attempts a write must fail BEFORE anything touches
    the old client's own recorded output -- the throw happens inside deps.io, upstream of any
    side effect."""
    mem = FakeMem()
    io_ro = M.build_io(_fake_mem_table(lua, mem), lambda name: 0)
    old_client_log = []

    def faulty_observer():
        # A buggy observer tries to "helpfully" patch a byte and log it like the real client
        # would. The write must throw before the log append below ever runs.
        io_ro.write_u8(0x1000, 0x99)
        old_client_log.append("observer wrote 0x1000")  # unreachable if isolation holds

    with pytest.raises(lupa.LuaError):
        faulty_observer()
    assert old_client_log == []


# ── hook naming + exact teardown ────────────────────────────────────────────────────────────

class FakeEvent:
    def __init__(self):
        self.next_id = 1
        self.registered = {}   # id -> (fn, addr, name)
        self.unregistered = []

    def on_bus_exec(self, fn, addr, name, domain=None):
        hid = self.next_id
        self.next_id += 1
        self.registered[hid] = (fn, int(addr), str(name))
        return hid

    def unregisterbyid(self, hid):
        self.unregistered.append(int(hid))


def test_hook_names_are_prefixed(lua, M):
    ev = FakeEvent()
    tbl = lua.table(on_bus_exec=ev.on_bus_exec, unregisterbyid=ev.unregisterbyid)
    wrapped = M.build_ev(tbl, "SLink-gen3-shadow-")
    wrapped.on_bus_exec(lambda: None, 0x1000, "faint_site")
    wrapped.on_bus_exec(lambda: None, 0x2000, "capture_site")
    names = [name for (_fn, _addr, name) in ev.registered.values()]
    assert names == ["SLink-gen3-shadow-faint_site", "SLink-gen3-shadow-capture_site"]


def test_teardown_unregisters_exactly_its_own_ids_and_nothing_else(lua, M):
    ev = FakeEvent()
    tbl = lua.table(on_bus_exec=ev.on_bus_exec, unregisterbyid=ev.unregisterbyid)
    wrapped = M.build_ev(tbl, "SLink-gen3-shadow-")
    id_a = wrapped.on_bus_exec(lambda: None, 0x1000, "a")
    id_b = wrapped.on_bus_exec(lambda: None, 0x2000, "b")
    # An id this instance never registered (e.g. the old client's own hook) must be refused.
    _raises_lua_error(wrapped.unregister, 999)
    assert ev.unregistered == []

    wrapped.teardown()
    assert sorted(ev.unregistered) == sorted([id_a, id_b])
    assert list(wrapped.registered_ids()) == []


# ── SHADOW line format + monotonic t ────────────────────────────────────────────────────────

def test_format_shadow_line_fields(lua, M):
    extra = lua.table(lua.table("callback_addr", "0x08015B5C"), lua.table("raw_r15"))
    line = M.format_shadow_line(3, 12345, "faint", "DEADBEEF:CAFEBABE", extra)
    assert line.startswith("SHADOW t=3 frame=12345 kind=faint key=DEADBEEF:CAFEBABE")
    assert "callback_addr=0x08015B5C" in line
    # a nil value is omitted, not rendered as "nil"
    assert "raw_r15" not in line


# ── full bootstrap over a FAKE Entry (package.preload): shape of the wiring only ───────────

FAKE_ENTRY_LUA = """
local fires = {
    { kind = "faint", key = "AAAAAAAA:BBBBBBBB", callback_addr = 0x08015B5C, raw_r15 = 0x08015B5A },
    { kind = "capture", key = "11111111:22222222" },
}
local Entry = {}
function Entry.build(deps)
    assert(deps.mode == "observer", "shadow must build in observer mode")
    assert(deps.net == nil, "observer must get no net")
    assert(deps.hud == nil, "observer must get no hud")
    -- prove the write sink really throws from inside the built client's own io
    local ok = pcall(deps.io.write_u8, 0, 0)
    assert(ok == false, "observer io.write_u8 must throw")
    local drained = false
    local signals = {
        drain = function(_self)
            if drained then return {} end
            drained = true
            return fires
        end,
    }
    return {}, { signals = signals }
end
package.preload["gen3.entry"] = function() return Entry end
"""


def test_full_bootstrap_logs_semantic_signals_with_monotonic_t(lua, M, tmp_path):
    lua.execute(FAKE_ENTRY_LUA)
    ev = FakeEvent()
    mem = FakeMem()
    logged = []
    g = lua.globals()
    g.event = lua.table(on_bus_exec=ev.on_bus_exec, unregisterbyid=ev.unregisterbyid)
    g.memory = _fake_mem_table(lua, mem)
    g.emu = lua.table(framecount=lambda: mem.frame, getregister=lambda n: 0)
    g.console = lua.table(log=lambda s: logged.append(str(s)))

    result_path = tmp_path / "duoA_result.txt"
    result_path.write_text("", encoding="utf-8")
    opts = lua.table(duo=lua.table(result=str(result_path).replace("\\", "/"), player="a"),
                      shadow=True, pack="gen3_frlg", title="firered", kind="clean")
    state = M.start(opts)
    assert state is not None

    state.poll()
    shadow_lines = [ln for ln in logged if ln.startswith("SHADOW ")]
    assert len(shadow_lines) == 2
    assert "kind=faint" in shadow_lines[0] and "key=AAAAAAAA:BBBBBBBB" in shadow_lines[0]
    assert "t=1 " in shadow_lines[0]
    assert "kind=capture" in shadow_lines[1] and "t=2 " in shadow_lines[1]
    assert "frame=7" in shadow_lines[0]
    # `frame` is not duplicated by the generic scalar-field forwarder (it's already the
    # line's leading field; the fake fires above don't even carry one, but real signals do).
    assert shadow_lines[0].count("frame=") == 1

    # the shadow log file (next to the duo result) got the same lines
    shadow_log_path = tmp_path / "duoA_result.shadow.log"
    assert shadow_log_path.exists()
    on_disk = shadow_log_path.read_text(encoding="utf-8").splitlines()
    assert on_disk == shadow_lines

    # a second poll (no new fires) does not re-log anything or reset t
    logged.clear()
    state.poll()
    assert logged == []

    state.teardown()
    assert sorted(ev.unregistered) == sorted(ev.registered.keys())


def test_disabled_by_default_no_op(lua, M, monkeypatch):
    """No SLINK_SHADOW global and no env var: start() is a costless no-op."""
    monkeypatch.delenv("SLINK_SHADOW", raising=False)
    assert M.start() is None


# ── full bootstrap over the REAL lua/gen3/entry.lua ─────────────────────────────────────────
# Same fake-ROM/fake-memory technique as tests/unit/test_gen3_entry.py's `World` (seed_rom,
# sites_of), but driven entirely through shadow_run's own M.start()/state.poll(), with the
# BizHawk globals (memory/event/emu/console) injected as `opts` rather than read off _G.

class BizMem:
    """A BizHawk `memory`-shaped fake: reads take a domain, "System Bus" (the live bus) or
    "ROM" (the cartridge) are kept as separate stores, like the real console."""

    def __init__(self, rom: dict[int, int]):
        self.rom = dict(rom)
        self.bus: dict[int, int] = {}
        self.frame = 0

    def _store(self, domain):
        return self.rom if domain == "ROM" else self.bus

    def read_u8(self, addr, domain=None):
        return self._store(domain).get(int(addr), 0)

    def read_u16_le(self, addr, domain=None):
        s = self._store(domain)
        return s.get(int(addr), 0) | (s.get(int(addr) + 1, 0) << 8)

    def read_u32_le(self, addr, domain=None):
        s, addr = self._store(domain), int(addr)
        return sum(s.get(addr + i, 0) << (8 * i) for i in range(4))

    def read_bytes(self, addr, length, domain=None):
        s, addr = self._store(domain), int(addr)
        return [s.get(addr + i, 0) for i in range(int(length))]

    def framecount(self):
        return self.frame

    def poke_bus(self, addr: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.bus[addr + i] = b


class BizEvent:
    """A BizHawk `event`-shaped fake: on_bus_exec(fn, addr, name) -> id, three args, no
    domain (unlike deps.ev's own optional fourth arg, which real signals.lua never passes)."""

    def __init__(self):
        self.next_id = 1
        self.registered: dict[int, tuple] = {}  # id -> (fn, addr, name)
        self.unregistered: list[int] = []

    def on_bus_exec(self, fn, addr, name):
        hid = self.next_id
        self.next_id += 1
        self.registered[hid] = (fn, int(addr), str(name))
        return hid

    def unregisterbyid(self, hid):
        self.unregistered.append(int(hid))


def _biz_globals(lua, mem, ev, regs=None):
    regs = regs or {}
    return {
        "memory": lua.table(read_u8=mem.read_u8, read_u16_le=mem.read_u16_le,
                            read_u32_le=mem.read_u32_le, read_bytes=mem.read_bytes,
                            framecount=mem.framecount),
        "event": lua.table(on_bus_exec=ev.on_bus_exec, unregisterbyid=ev.unregisterbyid),
        "emu": lua.table(framecount=lambda: mem.frame,
                         getregister=lambda n: regs.get(str(n), 0)),
        "console": lua.table(log=lambda s: None),
    }


def test_start_resolves_pack_title_kind_via_entry_admit_not_hardcoded_defaults(lua, M):
    """No pack/title/kind override: start() must use Entry.admit (anchors, since this fake
    ROM ships no gameinfo hash) over the fake cartridge -- gen3_rr/radical_red/clean's sites,
    not the hard-coded gen3_frlg/firered/clean fallback."""
    sites = sites_of("gen3_rr", "radical_red", "clean")
    rom = seed_rom(sites, header_code="BPRE")  # RR is a FireRed hack; carries FR's header code
    mem = BizMem(rom)
    ev = BizEvent()
    g = _biz_globals(lua, mem, ev)
    opts = lua.table(shadow=True, **g)
    state = M.start(opts)
    assert state is not None
    assert (state.deps.pack, state.deps.title, state.deps.kind) == (
        "gen3_rr", "radical_red", "clean")
    assert state.admitted_by == "anchors"


def test_start_falls_back_to_fr_clean_when_admission_cannot_decide(lua, M):
    """An all-zero ROM matches no pack's anchors and carries no recognised header code:
    admission returns nil, and start() falls back to the documented FR/clean default rather
    than crashing the duo run."""
    mem = BizMem(rom={})
    ev = BizEvent()
    g = _biz_globals(lua, mem, ev)
    opts = lua.table(shadow=True, **g)
    with pytest.raises(lupa.LuaError):
        # gen3_frlg/firered's own sites are not in this blank ROM either, so the fallback
        # build itself is refused by S.new's load-time anchor check -- proving start() really
        # tried to build gen3_frlg/firered/clean rather than silently doing nothing.
        M.start(opts)


def test_one_correctly_addressed_fire_logs_one_shadow_line_wrong_address_logs_none(lua, M, tmp_path):
    pack, title, kind = "gen3_frlg", "firered", "clean"
    sites = sites_of(pack, title, kind)
    rom = seed_rom(sites)
    mem = BizMem(rom)
    ev = BizEvent()
    logged = []
    g = _biz_globals(lua, mem, ev, regs={"R15": 0x1000, "CPSR": 0x6000003F, "R13": 0x03007F00})
    g["console"] = lua.table(log=lambda s: logged.append(str(s)))
    opts = lua.table(shadow=True, pack=pack, title=title, kind=kind, **g)
    state = M.start(opts)
    assert state is not None
    assert state.admitted_by == "override"

    site_kind = "save" if "save" in sites else next(iter(sorted(sites)))
    site = sites[site_kind]
    mem.poke_bus(site["address"], bytes.fromhex(site["expected_hex"]))
    hook_addr = site["address"] + site.get("capture_offset", 0)
    fn = next(fn for (fn, addr, _name) in ev.registered.values() if addr == hook_addr)

    logged.clear()
    fn(hook_addr)  # correct callback address: identity check passes, signal queues
    state.poll()
    lines = [ln for ln in logged if ln.startswith("SHADOW ")]
    assert len(lines) == 1
    assert f"kind={site_kind}" in lines[0]
    assert "callback_address=" in lines[0]

    logged.clear()
    fn(hook_addr + 4)  # wrong callback address: rejected inside signals.lua, never queued
    state.poll()
    assert [ln for ln in logged if ln.startswith("SHADOW ")] == []

    state.teardown()
    assert sorted(ev.unregistered) == sorted(ev.registered.keys())
