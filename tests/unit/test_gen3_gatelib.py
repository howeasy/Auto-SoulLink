"""lua/tests/gen3_gatelib.lua + the opcode gate manifest (PLAN §14 P5, card C5-4); no emulator.

Every gate file is in exactly one manifest list. Every bound gate loads under gen3_gatelib with
BizHawk stubs, never touches the old client modules, FAILs when the companion is absent and runs to a
verdict against a fake patch. Only some gates have their DECISIVE oracle proven here, i.e. PASS only
against a fake that really performs the op and FAIL against one that refuses or does nothing:
COLD_BOOT_OP_GATES and the two FORCE_MOVE_SLOT gates (FMS_GATES). For the rest the oracle is proven
live only. The raw poster's receipt rules, deadline, poison and span checks have their own tests,
and each is mutation-checked (a mutant of the guarded line must turn its test red).
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
savestate = { load = function() if FAKE.on_load then FAKE.on_load() end return true end }
gameinfo = { getromhash = function() return FAKE.hash end }
"""

# A minimal companion: beacon up, ROM anchors pinned, save pointers valid, and a frame hook that
# consumes each posted opcode (like handlers.c: reason, status, ack_seq, then opcode = 0) and
#   * performs the copy ops and the battle-logic ops (OP_FORCE_FAINT / OP_FORCE_MOVE);
#   * refuses opcode 99 as unknown, and acks everything else with FAKE.status (2 OK, 3 FAIL);
#   * FAKE.delay > 0: consumes the opcode now but acks `delay` frames later (FAKE.busy_first also
#     publishes ST_BUSY meanwhile, the async-op shape; FAKE.busy_ack also echoes ack = seq with
#     that ST_BUSY, which the contract says is still no receipt); FAKE.status = nil never acks;
#   * FAKE.fms = "faithful" | "nonfiring": FORCE_MOVE_SLOT arms (ST_BUSY), then after FAKE.delay
#     frames either refuses a 0-PP slot (reason 11, menu left parked) or fires: hands the controller
#     back to PlayerBufferRunCommand, acks OK and drops the slot's PP 5 frames later. "nonfiring" acks
#     OK and does nothing else; "wrongslot" hands back and acks but drops slot 0's PP (the default
#     cursor pick). A savestate load re-parks battler 0's action menu with PP 10 each.
FAKE_PATCH = r"""
local P, ram = ...
FAKE.status = 2
FAKE.delay, FAKE.timers = 0, {}
FAKE.w(P.BASE, P.SIG, 4); FAKE.w(P.BASE + 4, P.ABI, 2)
local BM, COMM, CTRL = 0x02023BE4, 0x02023E82, 0x03004FE0
local ACTION_CTRL_A, RUN_COMMAND = 0x0802E439, 0x0802E3B5
local function pp_addr(b, i) return BM + b * 0x58 + 0x24 + i end
FAKE.on_load = function()
    for i = 0, 3 do FAKE.mem[pp_addr(0, i)] = 10 end
    FAKE.mem[COMM] = 1; FAKE.w(CTRL, ACTION_CTRL_A, 4)
end
local function later(n, fn) FAKE.timers[#FAKE.timers + 1] = { left = n, fn = fn } end
local function finish(seq, status, reason)
    FAKE.w(P.BASE + 14, reason or 0, 2)
    FAKE.w(P.BASE + 10, status, 2)
    FAKE.w(P.BASE + 12, seq, 2)
    FAKE.acked_at = emu.framecount()
end
FAKE.patch = function()
    local due = {}
    for i = #FAKE.timers, 1, -1 do
        local tm = FAKE.timers[i]
        tm.left = tm.left - 1
        if tm.left <= 0 then table.remove(FAKE.timers, i); due[#due + 1] = tm.fn end
    end
    for _, fn in ipairs(due) do fn() end
    local op = FAKE.r16(P.BASE + 6)
    if op == 0 then return end
    local args, seq = P.BASE + 16, FAKE.r16(P.BASE + 8)
    FAKE.consumed_at = emu.framecount()
    FAKE.w(P.BASE + 6, 0, 2)                          -- opcode consumed
    if FAKE.fms and op == P.OP_FORCE_MOVE_SLOT then
        local b, pos = FAKE.mem[args] or 0, FAKE.mem[args + 2] or 0
        FAKE.w(P.BASE + 10, 1, 2)                     -- ST_BUSY: armed until the controller fires
        later(math.max(1, FAKE.delay), function()
            if FAKE.fms == "nonfiring" then finish(seq, 2); return end
            if (FAKE.mem[pp_addr(b, pos)] or 0) == 0 then finish(seq, 3, 11); return end
            FAKE.mem[COMM + b] = 3; FAKE.w(CTRL + b * 4, RUN_COMMAND, 4)
            finish(seq, 2)
            local slot = FAKE.fms == "wrongslot" and 0 or pos
            later(5, function() FAKE.mem[pp_addr(b, slot)] = FAKE.mem[pp_addr(b, slot)] - 1 end)
        end)
        return
    end
    if FAKE.status == 2 and (op == P.OP_SET_PARTY_MON or op == P.OP_SET_ENEMY_PARTY) then
        finish(seq, 3, 9)       -- RR-DURABLE: the working patch refuses the raw trade bypasses
        return
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
    local status = op == 99 and 3 or FAKE.status
    if status == nil then return end                  -- never acks
    if FAKE.delay > 0 then
        if FAKE.busy_first then FAKE.w(P.BASE + 10, 1, 2) end
        if FAKE.busy_ack then FAKE.w(P.BASE + 12, seq, 2) end
        later(FAKE.delay, function() finish(seq, status) end)
    else
        finish(seq, status)
    end
end
"""


def world(tmp_path, kind="companion", patch=None, beacon=False, fake=None):
    """A lupa runtime with the BizHawk stubs, a ROM that admits as `kind`, valid save pointers,
    and optionally a beacon or the fake patch (`fake`: extra FAKE fields, e.g. {"delay": 10})."""
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
        for k, v in (fake or {}).items():
            g.FAKE[k] = v
    elif beacon:
        for i, b in enumerate(N["SIG"].to_bytes(4, "little") + N["ABI"].to_bytes(2, "little")):
            mem[N["BASE"] + i] = b
    return lua


def run_gate(gate, tmp_path, kind="companion", patch=None, beacon=False, fake=None, path=None):
    """Run one gate file (or `path`, a mutated copy) under the stubs; returns the result text."""
    lua = world(tmp_path, kind, patch, beacon, fake)
    with pytest.raises(lupa.LuaError, match="slink-gate-finished"):
        lua.execute(f'dofile("{Path(path or GATE_DIR / gate).as_posix()}")')
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


LAUNCHER_CHECK = "the launcher refuses the clean RR: the companion patch is required"


def test_absent_gate_passes_on_clean_and_fails_on_a_beacon(tmp_path):
    """The clean RR boots as an admitted CLEAN artifact (native absent, Lua fallback) AND the
    launcher (Entry.admit_routed) refuses it with the companion verdict (patch-first, 2026-10-02)."""
    text = run_gate("test_mailbox_absent.lua", tmp_path, kind="clean")
    assert verdict(text).startswith("RESULT: PASS"), text
    assert LAUNCHER_CHECK in text and "needs the SLink companion patch" in text, text
    other = tmp_path / "beacon"
    other.mkdir()
    text = run_gate("test_mailbox_absent.lua", other, kind="clean", beacon=True)
    assert verdict(text).startswith("RESULT: FAIL"), text


def test_absent_gate_fails_if_the_launcher_would_admit_the_clean_rr(tmp_path):
    """The launcher check can fail: a gate copy whose t.routed() reports the clean RR admitted."""
    src = (GATE_DIR / "test_mailbox_absent.lua").read_text(encoding="utf-8")
    assert "t.routed()" in src
    mutant = tmp_path / "mutant_absent.lua"
    mutant.write_text(src.replace("t.routed()", "{ pack = 'gen3_rr', kind = 'clean' }"), encoding="utf-8")
    text = run_gate("test_mailbox_absent.lua", tmp_path / "out", kind="clean", path=mutant)         if (tmp_path / "out").mkdir() is None else ""
    assert verdict(text).startswith("RESULT: FAIL") and LAUNCHER_CHECK in text, text


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
    assert not posted and r.why.startswith("raw timeout: never posted")
    assert len(t.writes_log) == 0, "a refused arm writes nothing"
    assert "raw arm refused" in t.last_service
    assert t.raw_job is None and t.raw_poisoned is None, "nothing was posted, so nothing to poison"


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


# ── C5-4d (R2 review): receipts, deadline, poison, header span ──────────────────────────────

GATELIB = GATE_DIR / "gen3_gatelib.lua"

# One raw PING against a fake that consumes the opcode now and acks FAKE.delay frames later.
# Returns the job's receipt, the frame the fake acked on, and the frame it consumed on.
RECEIPT_SCENARIO = """
local path, stale = ...
local t = dofile(path).open("unit_raw")
t.boot({ native = false })
local B = t.P.BASE
if stale then          -- a previous op's receipt left behind: ack == the NEXT seq, status OK
    FAKE.w(B + 12, (FAKE.r16(B + 8) + 1) % 65536, 2)
    FAKE.w(B + 10, 2, 2)
end
local job = t.raw("OP_PING", {})
t.wait(job, 40)
return job.receipt, FAKE.acked_at, FAKE.consumed_at
"""


RECEIPT_CASES = [  # (stale ack from a previous seq, ST_BUSY first, ST_BUSY with ack = seq)
    (True, False, False), (False, True, False), (True, True, False), (False, True, True)]


def receipt_scenario(tmp_path, gatelib=GATELIB, *, stale, busy_first, busy_ack=False, status=2):
    lua = world(tmp_path, patch=status,
                fake={"delay": 10, "busy_first": busy_first, "busy_ack": busy_ack})
    return lua.execute(RECEIPT_SCENARIO, gatelib.as_posix(), stale)


def receipt_is_the_real_ack(r, acked_at, consumed_at):
    return r is not None and acked_at is not None and r.frame == acked_at and acked_at > consumed_at


@pytest.mark.parametrize("stale,busy_first,busy_ack", RECEIPT_CASES)
def test_raw_receipt_is_the_real_ack_not_a_stale_or_busy_status(tmp_path, stale, busy_first, busy_ack):
    r, acked_at, consumed_at = receipt_scenario(tmp_path, stale=stale, busy_first=busy_first,
                                                busy_ack=busy_ack)
    assert receipt_is_the_real_ack(r, acked_at, consumed_at), (r and r.frame, acked_at, consumed_at)
    assert r.why is None


def test_raw_receipt_after_busy_reports_the_real_refusal(tmp_path):
    r, acked_at, consumed_at = receipt_scenario(tmp_path, stale=True, busy_first=True, status=3)
    assert receipt_is_the_real_ack(r, acked_at, consumed_at) and r.why == "native refused"


# R2 M1's three mutations of the poster; each must turn the receipt scenario red.
RECEIPT_MUTANTS = {
    "pre-write ack = seq": ("t.writes:write_u16(B + O.ack, (job.seq + 65535) % 65536)",
                            "t.writes:write_u16(B + O.ack, job.seq)"),
    "drop the ack == seq match": ("if r16(B + O.ack) == job.seq and (status == ST_OK or status == ST_FAIL) then",
                                  "if (status == ST_OK or status == ST_FAIL) then"),
    "accept ST_BUSY as a receipt": ("if r16(B + O.ack) == job.seq and (status == ST_OK or status == ST_FAIL) then",
                                    "if r16(B + O.ack) == job.seq and (status >= 1 and status <= 3) then"),
}


def mutant(tmp_path, source, old, new, name):
    src = source.read_text(encoding="utf-8")
    assert src.count(old) == 1, f"mutation site moved: {old}"
    path = tmp_path / name
    path.write_text(src.replace(old, new), encoding="utf-8")
    return path


@pytest.mark.parametrize("name", sorted(RECEIPT_MUTANTS))
def test_receipt_scenarios_catch_r2_mutant(tmp_path, name):
    lib = mutant(tmp_path, GATELIB, *RECEIPT_MUTANTS[name], "gatelib_mutant.lua")
    caught = False
    for i, (stale, busy_first, busy_ack) in enumerate(RECEIPT_CASES):
        out = tmp_path / str(i)
        out.mkdir()
        r, acked_at, consumed_at = receipt_scenario(out, lib, stale=stale, busy_first=busy_first,
                                                    busy_ack=busy_ack)
        caught = caught or not receipt_is_the_real_ack(r, acked_at, consumed_at)
    assert caught, f"mutant '{name}' survived every receipt scenario"


DEADLINE_SCENARIO = """
local mode = ...
local t = dofile(SLINK_ROOT .. "/lua/tests/gen3_gatelib.lua").open("unit_raw")
t.boot({ native = false })
local job = t.raw("OP_PING", {})
if mode == "wait" then t.wait(job, 20) else t.idle(1805) end
local writes = #t.writes_log
t.idle(30)                                  -- nothing may be re-posted after the timeout
return job.receipt, t.raw_job, t.raw_poisoned, writes, #t.writes_log
"""


@pytest.mark.parametrize("mode", ["wait", "deadline"])
def test_raw_job_times_out_with_the_last_status_and_poisons(tmp_path, mode):
    lua = world(tmp_path, patch=2, fake={"status": None})    # consumes, never acks
    r, pending, poisoned, writes, writes_after = lua.execute(DEADLINE_SCENARIO, mode)
    assert r.why.startswith("raw timeout") and "last status=" in r.why, r.why
    assert pending is None and poisoned == r.why
    assert writes_after == writes, "the timed-out job was re-posted"


def test_poisoned_raw_poster_fails_the_gate_with_a_result_line(tmp_path):
    lua = world(tmp_path, patch=2, fake={"status": None})
    with pytest.raises(lupa.LuaError, match="slink-gate-finished"):
        lua.execute("""
            local t = dofile(SLINK_ROOT .. "/lua/tests/gen3_gatelib.lua").open("unit_poison")
            t.boot({ native = false })
            t.wait(t.raw("OP_PING", {}), 20)
            t.raw("OP_PING", {})
        """)
    text = (tmp_path / "unit_poison_result.txt").read_text(encoding="utf-8")
    assert "[FAIL] raw poster usable" in text and verdict(text).startswith("RESULT: FAIL")


def test_partial_post_poisons_the_raw_poster(tmp_path):
    lua = world(tmp_path, patch=2)
    r, poisoned = lua.execute("""
        local t = dofile(SLINK_ROOT .. "/lua/tests/gen3_gatelib.lua").open("unit_raw")
        t.boot({ native = false })
        local real = t.writes.write_u16
        t.writes.write_u16 = function() error("refused mid-post") end   -- a per-write refusal
        local job = t.raw("OP_PING", { 1 })
        t.writes.write_u16 = real
        return job.receipt, t.raw_poisoned
    """)
    assert r.why.startswith("raw post interrupted") and poisoned == r.why


def test_boot_is_the_poison_recovery_boundary(tmp_path):
    lua = world(tmp_path, patch=2, fake={"status": None})
    poisoned, after = lua.execute("""
        local t = dofile(SLINK_ROOT .. "/lua/tests/gen3_gatelib.lua").open("unit_raw")
        t.boot({ native = false })
        t.wait(t.raw("OP_PING", {}), 20)
        local p = t.raw_poisoned
        t.boot({ native = false })
        return p, t.raw_poisoned
    """)
    assert poisoned and after is None


@pytest.mark.parametrize("offset", [0, 4, 48, 60])
def test_raw_poster_refuses_a_stage_over_the_mailbox_header(tmp_path, offset):
    lua = world(tmp_path, patch=2)
    with pytest.raises(lupa.LuaError, match="touches the mailbox header"):
        lua.execute(f"""
            local t = dofile(SLINK_ROOT .. "/lua/tests/gen3_gatelib.lua").open("unit_raw")
            t.boot({{ native = false }})
            t.raw("OP_PING", {{}}, {{ {{ t.P.BASE + {offset}, {{ 0 }} }} }})
        """)


# ── M2: the ghost gates need the spawn receipt and a real object event ──────────────────────

GHOST_GATES = ["test_live_ghostavatar.lua", "test_live_ghostlayer.lua", "test_live_ghostshow.lua",
               "test_live_ghosttint.lua", "test_live_ghostwarp.lua", "test_live_peerinteract.lua"]


@pytest.mark.parametrize("gate", GHOST_GATES)
@pytest.mark.parametrize("status", [2, 3])
def test_ghost_gate_fails_without_an_acked_real_spawn(gate, status, tmp_path):
    # zeroed EWRAM reads GH->oeId 0: with no active localId-0xF0 object event that is not a ghost,
    # whether the fake acks the spawn (2) or refuses it (3)
    text = run_gate(gate, tmp_path, patch=status)
    assert verdict(text).startswith("RESULT: FAIL"), text
    if status == 3:
        assert "[FAIL] OP_GHOST_SPAWN acked OK" in text, text


# ── L9/L11: the FORCE_MOVE_SLOT gates' decisive oracles ────────────────────────────────────

FMS_GATES = ["test_live_forcemove.lua", "test_live_explode_route.lua"]


@pytest.mark.parametrize("gate", FMS_GATES)
def test_fms_gate_passes_against_a_faithful_driver(gate, tmp_path):
    text = run_gate(gate, tmp_path, patch=2, fake={"fms": "faithful", "delay": 12})
    assert verdict(text).startswith("RESULT: PASS"), text


@pytest.mark.parametrize("gate", FMS_GATES)
def test_fms_gate_fails_against_a_driver_that_acks_but_never_fires(gate, tmp_path):
    text = run_gate(gate, tmp_path, patch=2, fake={"fms": "nonfiring", "delay": 12})
    assert verdict(text).startswith("RESULT: FAIL"), text
    assert "[FAIL] controller handed back" in text


@pytest.mark.parametrize("gate", FMS_GATES)
def test_fms_gate_fails_when_the_default_slot_fires_instead(gate, tmp_path):
    text = run_gate(gate, tmp_path, patch=2, fake={"fms": "wrongslot", "delay": 12})
    assert verdict(text).startswith("RESULT: FAIL"), text
    assert "fired_slot=0" in text, text


FORCEMOVE_DECISIVE = [
    ('t.acked_ok(r), t.receipt_str(r))', 'true, t.receipt_str(r))'),
    ('RUN_COMMAND[ctrl_at_ack] == true, string.format', 'true, string.format'),
    ('fired == POS,\n', 'true,\n'),
    ('r2 ~= nil and r2.why == "native refused" and r2.reason == 11,', 'true,'),
    ('t.check("the menu stays with the player (still parked, not swapped)", parked(B),',
     't.check("the menu stays with the player (still parked, not swapped)", true,'),
]


def test_forcemove_decisive_checks_are_load_bearing(tmp_path):
    """R2 L11: forcing every decisive forcemove check to true must turn the non-firing test red."""
    src = (GATE_DIR / "test_live_forcemove.lua").read_text(encoding="utf-8")
    for old, new in FORCEMOVE_DECISIVE:
        assert src.count(old) == 1, f"decisive check moved: {old}"
        src = src.replace(old, new)
    path = tmp_path / "forcemove_mutant.lua"
    path.write_text(src, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    text = run_gate("test_live_forcemove.lua", out, patch=2, fake={"fms": "nonfiring", "delay": 12},
                    path=path)
    assert verdict(text).startswith("RESULT: PASS"), (
        "with its decisive checks forced true the gate must pass a non-firing driver, so "
        "test_fms_gate_fails_against_a_driver_that_acks_but_never_fires is what catches it\n" + text)


# ── M3: under SLINK_LIVE=1 a ported gate never skips green ──────────────────────────────────

def test_missing_prerequisite_fails_a_ported_gate_and_skips_a_deferred_one(monkeypatch, tmp_path):
    monkeypatch.setattr(gates.mkstates, "EMUHAWK", str(tmp_path / "no_EmuHawk.exe"))
    assert "EmuHawk not found" in gates.prerequisite_problem("test_live_playse.lua")
    with pytest.raises(pytest.fail.Exception, match="prerequisite missing"):
        gates._run("test_live_playse.lua", strict=True)
    with pytest.raises(pytest.skip.Exception, match="prerequisite missing"):
        gates._run("test_live_ghostwarp.lua", strict=False)


def test_zero_executed_ported_gates_fail_the_module():
    with pytest.raises(pytest.fail.Exception, match="zero of 26"):
        gates.check_executed(26, 0)
    gates.check_executed(26, 1)
    gates.check_executed(0, 0)          # nothing selected (e.g. -k on a deferred gate): no verdict
