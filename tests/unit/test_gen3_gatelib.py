"""lua/tests/gen3_gatelib.lua + the opcode gate manifest (PLAN §14 P5, card C5-4); no emulator.

Every gate file is in exactly one manifest list; the ported ones load under gen3_gatelib with
BizHawk stubs, never touch the old client modules, FAIL when the companion is absent (so a first
live run can fail), and PASS only against a fake patch that really performs the op.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

import lupa
import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE_DIR = ROOT / "lua" / "tests"
sys.path.insert(0, str(ROOT / "tools"))
from run_gate import _result_path_for  # noqa: E402

_spec = importlib.util.spec_from_file_location("lua_gates_manifest", ROOT / "tests/live/test_lua_gates.py")
gates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gates)

OLD_CLIENT = re.compile(r"mailbox\.lua|require\(\s*[\"']mailbox[\"']|memory_gba|gen3_frlge_client"
                        r"|peer_ghost_npc|games\.gen3_frlge|games/gen3_frlge\.lua")


def code_of(path):
    """Lua source with comments stripped: a gate may NAME the old client in prose, never load it."""
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"--\[(=*)\[.*?\]\1\]", "", src, flags=re.S)
    return re.sub(r"--[^\n]*", "", src)


_SIGNALS = json.loads((ROOT / "data/games/gen3_rr/engine_signals.json").read_text())
HASH = {k: v["rom_sha1"] for k, v in _SIGNALS["titles"]["radical_red"]["artifacts"].items()}
PROFILE = json.loads((ROOT / "data/games/gen3_rr/profile.json").read_text())
N = PROFILE["native"]
RAM = PROFILE["titles"]["radical_red"]["ram"]
WC = json.loads((ROOT / "data/games/gen3_rr/write_checkpoint.json").read_text())["radical_red"]

STUBS = r"""
local mem, rom, frame = {}, {}, 0
FAKE = { mem = mem, rom = rom }
local function rd(a, d) if d == "ROM" then return rom[a] or 0 end return mem[a] or 0 end
local function r16(a, d) return rd(a, d) | (rd(a + 1, d) << 8) end
local function r32(a, d) return r16(a, d) | (r16(a + 2, d) << 16) end
local function w(a, v, n) for i = 0, n - 1 do mem[a + i] = (v >> (8 * i)) & 0xFF end end
FAKE.w, FAKE.r16, FAKE.r32 = w, r16, r32
memory = {
    usememorydomain = function() return true end,
    read_u8 = rd, read_u16_le = r16, read_u32_le = r32,
    read_s16_le = function(a) local v = r16(a) return v >= 0x8000 and v - 0x10000 or v end,
    write_u8 = function(a, v) w(a, v, 1) end,
    write_u16_le = function(a, v) w(a, v, 2) end,
    write_s16_le = function(a, v) w(a, v & 0xFFFF, 2) end,
    write_u32_le = function(a, v) w(a, v, 4) end,
    read_bytes_as_array = function(a, n) local t = {} for i = 1, n do t[i] = rd(a + i - 1) end return t end,
}
emu = { frameadvance = function() frame = frame + 1; if FAKE.patch then FAKE.patch() end end,
        framecount = function() return frame end, getregister = function() return 0 end }
joypad = { set = function() end }
console = { log = function() end }
client = { speedmode = function() end, exit = function() end, screenshot = function() end }
savestate = { load = function() return true end }
gameinfo = { getromhash = function() return FAKE.hash end }
"""

# A minimal companion: beacon up, ROM anchors pinned, save pointers valid, and a frame hook that
# performs the copy ops and the battle-logic ops (handlers.c OP_FORCE_FAINT / OP_FORCE_MOVE), refuses
# opcode 99 as unknown, and acks every other posted opcode with FAKE.status (2 = ST_OK, 3 = ST_FAIL).
FAKE_PATCH = r"""
local P, ram = ...
FAKE.status = 2
FAKE.w(P.BASE, P.SIG, 4); FAKE.w(P.BASE + 4, P.ABI, 2)
FAKE.patch = function()
    local op = FAKE.r16(P.BASE + 6)
    if op == 0 then return end
    local args = P.BASE + 16
    local function copy(dst, n) for i = 0, n - 1 do FAKE.mem[dst + i] = FAKE.mem[P.BLOB_BUF + i] end end
    if FAKE.status == 2 and op == P.OP_SET_PARTY_MON then
        local slot = FAKE.mem[args] or 0
        copy(ram.PARTY_BASE + slot * 100, 100)
        if (FAKE.mem[args + 1] or 0) == 1 and (FAKE.mem[ram.PARTY_COUNT_ADDR] or 0) < slot + 1 then
            FAKE.mem[ram.PARTY_COUNT_ADDR] = slot + 1
        end
    elseif FAKE.status == 2 and op == P.OP_SET_ENEMY_PARTY then
        local n = FAKE.mem[args] or 0
        copy(ram.ENEMY_BASE, n * 100)
        FAKE.mem[ram.ENEMY_COUNT_ADDR] = n
        FAKE.w(ram.ENEMY_BASE + n * 100 + 0x58, 0, 2)
    elseif FAKE.status == 2 and op == P.OP_FORCE_FAINT then
        FAKE.w(0x02023BE4 + (FAKE.mem[args] or 0) * 0x58 + 0x28, 0, 2)
    elseif FAKE.status == 2 and op == P.OP_FORCE_MOVE then
        local b, target, pos = FAKE.mem[args] or 0, FAKE.mem[args + 1] or 0, FAKE.mem[args + 2] or 0
        FAKE.mem[0x02023D7C + b] = 0
        FAKE.w(0x02023DC4 + b * 2, (FAKE.mem[args + 4] or 0) | ((FAKE.mem[args + 5] or 0) << 8), 2)
        FAKE.mem[0x02023E82 + b] = 3
        local bs = FAKE.r32(0x02023FE8)
        if bs ~= 0 then FAKE.mem[bs + 0x80 + b] = pos; FAKE.mem[bs + 0x0C + b] = target end
    end
    FAKE.w(P.BASE + 12, FAKE.r16(P.BASE + 8), 2)      -- ack = seq
    FAKE.w(P.BASE + 10, op == 99 and 3 or FAKE.status, 2)
    FAKE.w(P.BASE + 6, 0, 2)                          -- opcode consumed
end
"""


def world(tmp_path, kind="companion", patch=None, beacon=False):
    """A lupa runtime with the BizHawk stubs, a ROM that admits as `kind`, valid save pointers,
    and optionally a beacon or the fake patch."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(STUBS)
    g = lua.globals()
    g.SLINK_ROOT = ROOT.as_posix()
    g.SLINK_GATE_OUT = tmp_path.as_posix()
    g.FAKE.hash = HASH[kind]
    rom, mem = g.FAKE.rom, g.FAKE.mem
    for a in WC["anchors"].values():
        raw = bytes.fromhex(a["expected_hex"][kind])
        for i, b in enumerate(raw):
            rom[a["rom_offset"] + i] = b
    for name, spec in WC["pointers"].items():
        if name != "pokemon_storage_base":
            for i, b in enumerate((0x02025000).to_bytes(4, "little")):
                mem[spec["address"] + i] = b
    if patch is not None:
        lua.execute(FAKE_PATCH, lua.table_from(N), lua.table_from(RAM))
        g.FAKE.status = patch
    elif beacon:
        for i, b in enumerate(N["SIG"].to_bytes(4, "little") + N["ABI"].to_bytes(2, "little")):
            mem[N["BASE"] + i] = b
    return lua


def run_gate(gate, tmp_path, kind="companion", patch=None, beacon=False):
    """Run one gate file under the stubs; returns the result text."""
    lua = world(tmp_path, kind, patch, beacon)
    with pytest.raises(lupa.LuaError, match="slink-gate-finished"):
        lua.execute(f'dofile("{(GATE_DIR / gate).as_posix()}")')
    results = list(tmp_path.glob("*_result.txt"))
    assert len(results) == 1, results
    return results[0].read_text(encoding="utf-8")


def verdict(text):
    return [ln for ln in text.splitlines() if ln.startswith("RESULT:")][-1]


# ── the manifest ──────────────────────────────────────────────────────────────────────────

def test_manifest_covers_every_gate_file_exactly_once():
    ported, deferred, gap = set(gates.PORTED), set(gates.DEFERRED), set(gates.GAP)
    assert not (ported & deferred) and not (ported & gap) and not (deferred & gap)
    assert ported | deferred | gap == set(gates.gate_files())
    assert len(gates.PORTED) == len(ported)


def test_deferred_list_is_explicit_with_reasons():
    ghosts = {f for f in gates.gate_files() if f.startswith("test_live_ghost")}
    assert ghosts and ghosts <= set(gates.DEFERRED), "every ghost gate is deferred, not dropped"
    for gate, why in gates.DEFERRED.items():
        assert "docs/gen3/TODO.md" in why and ("ghost" in why or "native text" in why), gate
    for gate, ops in gates.GAP.items():
        assert ops.strip(), gate
    # unported gates are reported as skips, never silently absent from the live run
    assert set(gates.UNPORTED) == set(gates.DEFERRED) | set(gates.GAP)


BOUND = sorted(gates.PORTED) + sorted(gates.DEFERRED)      # every gate file in lua/tests/


@pytest.mark.parametrize("gate", BOUND)
def test_ported_gate_is_bound_to_gen3_gatelib_only(gate):
    src = code_of(GATE_DIR / gate)
    assert "gen3_gatelib.lua" in src
    assert not OLD_CLIENT.search(src), OLD_CLIENT.search(src).group(0)
    assert _result_path_for(f"lua/tests/{gate}"), "run_gate.py cannot find this gate's result file"


def test_ported_gates_write_distinct_result_files():
    paths = [_result_path_for(f"lua/tests/{g}") for g in BOUND]
    assert len(set(paths)) == len(paths)


def test_gatelib_itself_needs_no_old_client():
    assert not OLD_CLIENT.search(code_of(GATE_DIR / "gen3_gatelib.lua"))


# ── every ported gate loads and can FAIL ─────────────────────────────────────────────────

@pytest.mark.parametrize("gate", [g for g in BOUND if g not in gates.CLEAN_ROM_GATES])
def test_ported_gate_fails_without_the_companion(gate, tmp_path):
    text = run_gate(gate, tmp_path)
    assert verdict(text).startswith("RESULT: FAIL"), text


def test_absent_gate_passes_on_clean_and_fails_on_a_beacon(tmp_path):
    assert verdict(run_gate("test_mailbox_absent.lua", tmp_path, kind="clean")).startswith("RESULT: PASS")
    other = tmp_path / "beacon"
    other.mkdir()
    text = run_gate("test_mailbox_absent.lua", other, kind="clean", beacon=True)
    assert verdict(text).startswith("RESULT: FAIL"), text


def test_absent_gate_fails_on_the_companion_artifact(tmp_path):
    text = run_gate("test_mailbox_absent.lua", tmp_path, kind="companion")
    assert verdict(text).startswith("RESULT: FAIL") and "gen3_rr/clean" in text, text


# ── the native path really reaches the (fake) patch ──────────────────────────────────────

COLD_BOOT_OP_GATES = ["test_live_playse.lua", "test_live_setpartymon.lua",
                      "test_live_enemyparty_route.lua", "test_mailbox_ping.lua",
                      "test_mailbox_battle.lua"]


@pytest.mark.parametrize("gate", COLD_BOOT_OP_GATES)
def test_cold_boot_gate_passes_against_a_working_patch(gate, tmp_path):
    text = run_gate(gate, tmp_path, patch=2)
    assert verdict(text).startswith("RESULT: PASS"), text


@pytest.mark.parametrize("gate", COLD_BOOT_OP_GATES)
def test_cold_boot_gate_fails_when_the_patch_refuses(gate, tmp_path):
    text = run_gate(gate, tmp_path, patch=3)
    assert verdict(text).startswith("RESULT: FAIL") and "native refused" in text, text


@pytest.mark.parametrize("gate", [g for g in BOUND if g not in gates.CLEAN_ROM_GATES])
def test_ported_gate_body_runs_to_a_verdict_against_a_fake_patch(gate, tmp_path):
    """Past the prologue: the whole gate body executes (no Lua error) and reports a verdict."""
    text = run_gate(gate, tmp_path, patch=2)
    assert verdict(text).startswith("RESULT:"), text
    assert "native:service raised" not in text, text


# ── the test-only raw poster (C5-4b) ─────────────────────────────────────────────────────

RAW_PING = """
local G = dofile(SLINK_ROOT .. "/lua/tests/gen3_gatelib.lua")
local t = G.open("unit_raw")
t.boot({ native = false })
local job = t.raw("OP_PING", {})
local posted = t.wait_posted(job, 5)
local r = t.wait(job, 30)
return t, posted, r
"""


def test_raw_poster_posts_through_the_native_write_window(tmp_path):
    lua = world(tmp_path, patch=2)
    t, posted, r = lua.execute(RAW_PING)
    assert posted and r is not None and r.why is None
    log = [(e.reason, e.address, e.len) for e in t.writes_log.values()]
    base = N["BASE"]
    assert log and all(reason == "native" for reason, _, _ in log)
    assert all(base + 6 <= a and a + n <= base + 48 for _, a, n in log), log
    assert log[-1][1] == base + 6, "the opcode is published last"


def test_raw_poster_is_refused_while_the_mailbox_is_busy(tmp_path):
    lua = world(tmp_path, beacon=True)
    lua.globals().FAKE.w(N["BASE"] + 10, 1, 2)          # status = ST_BUSY (e.g. an armed FMS)
    t, posted, r = lua.execute(RAW_PING)
    assert not posted and r is None
    assert len(t.writes_log) == 0, "a refused arm writes nothing"
    assert "raw arm refused" in t.last_service


def test_raw_poster_never_shares_a_gate_with_native_lua(tmp_path):
    lua = world(tmp_path, patch=2)
    with pytest.raises(lupa.LuaError, match="native = false"):
        lua.execute("""
            local t = dofile(SLINK_ROOT .. "/lua/tests/gen3_gatelib.lua").open("unit_raw")
            t.boot()
            t.raw("OP_PING", {})
        """)


def test_raw_poster_refuses_a_stage_outside_the_native_spans(tmp_path):
    lua = world(tmp_path, patch=2)
    with pytest.raises(lupa.LuaError, match="outside every profile.native span"):
        lua.execute("""
            local t = dofile(SLINK_ROOT .. "/lua/tests/gen3_gatelib.lua").open("unit_raw")
            t.boot({ native = false })
            t.raw("OP_PING", {}, { { 0x02024284, { 0 } } })   -- gPlayerParty: not a native arena
        """)


def test_evring_drain_reads_the_ring_and_advances_the_read_index(tmp_path):
    lua = world(tmp_path, patch=2)
    evr = N["EVR"]
    fake = lua.globals().FAKE
    fake.mem[evr] = 2                                   # wr = 2, rd = 0
    fake.w(evr + 8, N["EV_PLAYER_FAINT"] | (3 << 8), 4)
    fake.w(evr + 12, N["EV_EVOLVE"] | (1 << 8) | (26 << 16), 4)
    fake.mem[evr + 2] = 1                               # overflow flagged
    evs, ovf = lua.execute("""
        local t = dofile(SLINK_ROOT .. "/lua/tests/gen3_gatelib.lua").open("unit_raw")
        t.boot({ native = false })
        return t.events_drain()
    """)
    got = [(e.type, e.a, e.b) for e in evs.values()]
    assert got == [(N["EV_PLAYER_FAINT"], 3, 0), (N["EV_EVOLVE"], 1, 26)]
    assert ovf is True and fake.mem[evr + 1] == 2 and fake.mem[evr + 2] == 0


# ── C5-4c: no gate loads the old client; the archive is never run ────────────────────────

OLD_LOAD = re.compile(r"\b(?:require|dofile)\s*\(?[^\n]*?"
                      r"(?:mailbox|memory_gba|game_detect|clients/gen3_frlge_client|peer_ghost_npc)")
ARCHIVE = GATE_DIR / "archive" / "gen3_old_client"


def test_old_load_pattern_catches_every_old_module():
    for line in ['local MB = dofile(WT .. "/lua/mailbox.lua")', 'local M = require("memory_gba")',
                 'require("game_detect")', 'dofile(ROOT .. "/lua/clients/gen3_frlge_client.lua")',
                 'local R = require("peer_ghost_npc")', 'local MB = require "mailbox"']:
        assert OLD_LOAD.search(line), line
    assert not OLD_LOAD.search('local G = dofile(ROOT .. "/lua/tests/gen3_gatelib.lua")')


def test_no_gate_requires_or_dofiles_an_old_client_module():
    files = sorted(GATE_DIR.glob("test_live_*.lua")) + sorted(GATE_DIR.glob("test_mailbox_*.lua"))
    assert len(files) == len(gates.gate_files()) > 0
    hits = [f"{f.name}: {m.group(0)}" for f in files for m in [OLD_LOAD.search(code_of(f))] if m]
    assert not hits, hits


def test_archive_is_documented_and_never_loaded_by_the_live_runner():
    archived = sorted(f.name for f in ARCHIVE.glob("*.lua"))
    assert archived, "the archive holds the old-driver gates"
    readme = (ARCHIVE / "README.md").read_text(encoding="utf-8")
    for name in archived:
        assert sum(1 for ln in readme.splitlines() if ln.startswith(f"- `{name}`")) == 1, name
    listed = set(gates.gate_files()) | set(gates.PORTED) | set(gates.DEFERRED) | set(gates.GAP)
    assert not listed & set(archived)
    assert Path(gates.GATE_DIR).resolve() == GATE_DIR.resolve()
    runner = (ROOT / "tests/live/test_lua_gates.py").read_text(encoding="utf-8")
    assert "archive" not in re.sub(r'""".*?"""|#[^\n]*', "", runner, flags=re.S)


def test_deferred_gates_are_opt_in_only():
    assert gates.DEFERRED_OPT_IN == "SLINK_GATES_DEFERRED"
    assert set(gates.DEFERRED).isdisjoint(gates._gates())
