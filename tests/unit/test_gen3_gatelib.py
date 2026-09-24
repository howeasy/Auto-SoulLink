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
# performs the copy ops and acks every posted opcode with FAKE.status (2 = ST_OK, 3 = ST_FAIL).
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
    end
    FAKE.w(P.BASE + 12, FAKE.r16(P.BASE + 8), 2)      -- ack = seq
    FAKE.w(P.BASE + 10, FAKE.status, 2)
    FAKE.w(P.BASE + 6, 0, 2)                          -- opcode consumed
end
"""


def run_gate(gate, tmp_path, kind="companion", patch=None, beacon=False):
    """Run one gate file under the stubs; returns the result text."""
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


@pytest.mark.parametrize("gate", gates.PORTED)
def test_ported_gate_is_bound_to_gen3_gatelib_only(gate):
    src = code_of(GATE_DIR / gate)
    assert "gen3_gatelib.lua" in src
    assert not OLD_CLIENT.search(src), OLD_CLIENT.search(src).group(0)
    assert _result_path_for(f"lua/tests/{gate}"), "run_gate.py cannot find this gate's result file"


def test_ported_gates_write_distinct_result_files():
    paths = [_result_path_for(f"lua/tests/{g}") for g in gates.PORTED]
    assert len(set(paths)) == len(paths)


def test_gatelib_itself_needs_no_old_client():
    assert not OLD_CLIENT.search(code_of(GATE_DIR / "gen3_gatelib.lua"))


# ── every ported gate loads and can FAIL ─────────────────────────────────────────────────

@pytest.mark.parametrize("gate", [g for g in gates.PORTED if g not in gates.CLEAN_ROM_GATES])
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

@pytest.mark.parametrize("gate", ["test_live_playse.lua", "test_live_setpartymon.lua",
                                  "test_live_enemyparty_route.lua"])
def test_cold_boot_gate_passes_against_a_working_patch(gate, tmp_path):
    text = run_gate(gate, tmp_path, patch=2)
    assert verdict(text).startswith("RESULT: PASS"), text


@pytest.mark.parametrize("gate", ["test_live_playse.lua", "test_live_setpartymon.lua",
                                  "test_live_enemyparty_route.lua"])
def test_cold_boot_gate_fails_when_the_patch_refuses(gate, tmp_path):
    text = run_gate(gate, tmp_path, patch=3)
    assert verdict(text).startswith("RESULT: FAIL") and "native refused" in text, text


@pytest.mark.parametrize("gate", [g for g in gates.PORTED if g not in gates.CLEAN_ROM_GATES])
def test_ported_gate_body_runs_to_a_verdict_against_a_fake_patch(gate, tmp_path):
    """Past the prologue: the whole gate body executes (no Lua error) and reports a verdict."""
    text = run_gate(gate, tmp_path, patch=2)
    assert verdict(text).startswith("RESULT:"), text
    assert "native:service raised" not in text, text
