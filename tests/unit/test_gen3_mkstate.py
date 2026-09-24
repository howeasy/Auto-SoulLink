"""lua/tests/mkstate.lua + mkstate_gen3_rr_fill.lua on the NEW Gen 3 layer (card C5-6-MKSTATE).

Both are production savestate tooling (tools/mkstates.py, the RR opcode gates' fixtures), so they
must run without archive/gen3-old-client:lua/mailbox.lua before C5-6 deletes it. No emulator: each script runs under the
BizHawk stubs + fake companion of test_gen3_gatelib.py, with every dofile/require recorded.
"""
import sys
from pathlib import Path

import lupa
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_gen3_gatelib import OLD_LOAD, RAM, ROOT, N, code_of, world  # noqa: E402

TESTS = ROOT / "lua" / "tests"
SCRIPTS = ["mkstate.lua", "mkstate_gen3_rr_fill.lua"]

# Every load recorded; gatelib's `t` stashed as LAST_T; patch/build redirected to tmp; env faked.
HARNESS = r"""
local out, env = ...
LOADS, SAVED, TN = {}, {}, {}
local real_dofile, real_require, real_open = dofile, require, io.open
dofile = function(p)
    LOADS[#LOADS + 1] = p
    local r = real_dofile(p)
    if p:match("gen3_gatelib%.lua$") then
        local open = r.open
        r.open = function(...) LAST_T = open(...); return LAST_T end
    end
    return r
end
require = function(m) LOADS[#LOADS + 1] = m; return real_require(m) end
io.open = function(p, m) return real_open((p:gsub("^.*/patch/build/", out .. "/")), m) end
os.getenv = function(k) return env[k] end
savestate.save = function(p) SAVED[#SAVED + 1] = p:match("[^/\\]+$"); return true end
joypad.set = function(b) FAKE.pad = b or {} end
"""


def run(tmp_path, script, env, patch=2, setup=None):
    lua = world(tmp_path, patch=patch)
    lua.execute(HARNESS, tmp_path.as_posix(), lua.table_from(env))
    if setup:
        lua.execute(setup, lua.table_from(N), lua.table_from(RAM))
    err = None
    try:
        lua.execute(f'dofile("{(TESTS / script).as_posix()}")')
    except lupa.LuaError as e:
        err = str(e)
    g = lua.globals()
    text = "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("*_result.txt"))
    return g, text, err


def verdict(text):
    return [ln for ln in text.splitlines() if ln.startswith("RESULT:")][-1]


def loads(g):
    return [g.LOADS[i] for i in range(1, len(g.LOADS) + 1)]


# ── neither file needs the old client ──────────────────────────────────────────────────────

@pytest.mark.parametrize("script", SCRIPTS)
def test_script_source_loads_no_old_client_module(script):
    src = code_of(TESTS / script)
    assert not OLD_LOAD.search(src), OLD_LOAD.search(src).group(0)
    assert "gen3_gatelib.lua" in src


# ── rr_fill: OP_CREATE_MON through the raw poster ─────────────────────────────────────────

FILL_ENV = {"SLINK_STATE": "src.State", "SLINK_STATE_OUT": "full.State", "SLINK_FILL_TO": "3",
            "SLINK_GEN3_CHECKPOINT": (ROOT / "data/games/gen3_rr/write_checkpoint.json").as_posix(),
            "SLINK_GEN3_TITLE": "radical_red"}

# One mon in the party; the fake patch really creates a mon for each acked OP_CREATE_MON.
FILL_SETUP = r"""
local P, ram = ...
FAKE.mem[ram.PARTY_COUNT_ADDR] = 1
CREATED = {}
local inner = FAKE.patch
FAKE.patch = function()
    local B = P.BASE
    if FAKE.r16(B + 6) == P.OP_CREATE_MON and FAKE.status == 2 then
        local a = {}
        for i = 0, 5 do a[#a + 1] = FAKE.mem[B + 16 + i] or 0 end
        CREATED[#CREATED + 1] = a
        FAKE.mem[ram.PARTY_COUNT_ADDR] = FAKE.mem[ram.PARTY_COUNT_ADDR] + 1
    end
    inner()
end
"""


def test_rr_fill_creates_the_fillers_through_the_native_window(tmp_path):
    g, text, err = run(tmp_path, "mkstate_gen3_rr_fill.lua", FILL_ENV, setup=FILL_SETUP)
    assert err is None, err
    assert verdict(text).startswith("RESULT: PASS"), text
    assert not [p for p in loads(g) if OLD_LOAD.search(f"dofile({p})")], loads(g)
    created = [list(g.CREATED[i].values()) for i in range(1, len(g.CREATED) + 1)]
    # {slot, party, species lo, hi, level, bump}: Charmander into slot 1, Squirtle into slot 2
    assert created == [[1, 0, 4, 0, 5, 1], [2, 0, 7, 0, 5, 1]]
    assert g.FAKE.mem[RAM["PARTY_COUNT_ADDR"]] == 3
    assert list(g.SAVED.values()) == ["full.State"]
    log = [(e.reason, e.address, e.len) for e in g.LAST_T.writes_log.values()]
    base = N["BASE"]
    assert log and all(r == "native" and base + 6 <= a and a + n <= base + 48 for r, a, n in log), log
    opcodes = [i for i, (_, a, _) in enumerate(log) if a == base + 6]
    assert len(opcodes) == 2 and opcodes[-1] == len(log) - 1, "each post publishes its opcode last"


def test_rr_fill_fails_when_the_patch_refuses(tmp_path):
    g, text, _ = run(tmp_path, "mkstate_gen3_rr_fill.lua", FILL_ENV, patch=3, setup=FILL_SETUP)
    assert "RESULT: FAIL" in text and "OP_CREATE_MON acked OK" in text, text
    assert list(g.SAVED.values()) == []


def test_rr_fill_fails_without_the_companion(tmp_path):
    g, text, _ = run(tmp_path, "mkstate_gen3_rr_fill.lua", FILL_ENV, patch=None)
    assert verdict(text).startswith("RESULT: FAIL") and "SLNK beacon" in text, text
    assert list(g.SAVED.values()) == []


# ── mkstate town: the Pokémon Center trade-NPC check through native:config ──────────────

# A walkable field on map (3,1). Holding Up after slink_overworld.State is saved "enters" map (3,2);
# the fake patch spawns its trade NPC (localId 0xF1) in OE slot 3 while TN_ENABLE is set.
TOWN_SETUP = r"""
local P, ram = ...
local m = FAKE.mem
FAKE.w(0x030030F4, 0x080565B5, 4)             -- CB2_Overworld
m[0x02024029] = 1; FAKE.w(0x02024284, 0x12345678, 4)
FAKE.w(ram.SB1_PTR_ADDR, 0x02026000, 4); m[0x02026004], m[0x02026005] = 3, 1
local inner, OE = FAKE.patch, P.OBJECT_EVENTS_BASE
FAKE.patch = function()
    if inner then inner() end
    local saved_ow = false
    for _, n in ipairs(SAVED) do if n == "slink_overworld.State" then saved_ow = true end end
    if saved_ow and FAKE.pad and FAKE.pad.Up then m[0x02026005] = 2 end
    local on = (m[P.TN_ENABLE] or 0)
    if TN[#TN] ~= on then TN[#TN + 1] = on end
    if FAKE.spawns and on == 1 then m[OE + 3 * 0x24], m[OE + 3 * 0x24 + 8] = 1, 0xF1
    else m[OE + 3 * 0x24] = 0 end
end
"""


def town(tmp_path, spawns=True, patch=2):
    env = {"SLINK_STATE_OUT": (tmp_path / "slink_overworld.State").as_posix(),
           "SLINK_STATE_DIR": tmp_path.as_posix(), "SLINK_STATE_KIND": "town"}
    setup = TOWN_SETUP.replace("FAKE.spawns", "true" if spawns else "false")
    return run(tmp_path, "mkstate.lua", env, patch=patch, setup=setup)


def test_town_sets_the_trade_npc_flag_through_native_config(tmp_path):
    g, text, err = town(tmp_path)
    assert err and err.startswith("mkstate-finished"), err
    assert verdict(text).startswith("RESULT: PASS"), text
    assert "patch spawned the trade NPC at oe=3" in text
    assert not [p for p in loads(g) if OLD_LOAD.search(f"dofile({p})")], loads(g)
    assert list(g.TN.values()) == [0, 1, 0], "enabled for the check, then cleared"
    tn = [(e.reason, e.address, e.len) for e in g.LAST_T.writes_log.values()
          if e.address == N["TN_ENABLE"]]
    assert tn == [("native", N["TN_ENABLE"], 1)] * 2, tn
    assert list(g.SAVED.values())[-3:] == ["slink_door.State", "slink_overworld.State",
                                            "slink_pokecenter.State"]


def test_town_fails_when_the_patch_spawns_no_npc(tmp_path):
    g, text, _ = town(tmp_path, spawns=False)
    assert "RESULT: FAIL" in text and "did not spawn its trade NPC" in text, text
    assert "slink_pokecenter.State" not in list(g.SAVED.values())


def test_town_without_the_companion_skips_the_npc_check(tmp_path):
    g, text, err = town(tmp_path, patch=None)
    assert err and err.startswith("mkstate-finished"), err
    assert verdict(text).startswith("RESULT: PASS"), text
    assert g.LAST_T.native is None and not any("gen3/native.lua" in p for p in loads(g))

