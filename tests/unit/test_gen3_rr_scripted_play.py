"""gen3_rr_scripted_play.lua: LEGS shape + fake-RAM behaviour (card gen3-P3-C3-7).

Two kinds of check, both through lupa, neither needing an emulator or a ROM:

* SHAPE -- site kinds, citations, the savestate each leg declares, no frame-count terminal.
* BEHAVIOUR -- each leg's `run`/`check` closure driven against a FAKE RAM whose contents change
  as frames advance and buttons are pressed. This is where the oracles are actually falsified:
  a leg that "passes" on a fake where the engine did the WRONG thing (withdrew a different mon,
  never left the battle, reported a map change that was really an unreadable pointer) is a leg
  whose oracle is decorative. Each negative test below is one such wrong-engine fake.

BizHawk globals are stubbed as CALLABLE TABLES: `type(gui.x)` is "userdata" in EmuHawk, so a
plain function stub is the wrong shape and a plain table is not callable
(reference_bizhawk_api_userdata). `client.exit` raises, which is how G.finish's "RESULT: FAIL"
becomes an observable outcome here instead of falling through.
"""
from __future__ import annotations

import os
import re

import pytest
from lupa import LuaRuntime

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_LUA_REPO = _REPO.replace("\\", "/")
_SCRIPT = os.path.join(_REPO, "lua", "tests", "gen3_rr_scripted_play.lua")
with open(_SCRIPT, encoding="utf-8") as _f:
    _SCRIPT_SRC = _f.read()

# docs/gen3_engine_sites.md "PINNED / UNVERIFIED matrix" -- the 23 recognized site kinds.
_KNOWN_KINDS = {
    "frame_control", "battle_begin", "battle_end", "faint", "capture_wild", "mon_given",
    "pc_move", "whiteout", "map_load", "evolve_species_store", "trade_done", "save",
    "poison_faint", "borrowed_party", "nature_change", "pc_deposit", "pc_withdraw",
    "pc_box_place", "pc_release_begin", "pc_release", "trade_evolve_species_store",
    "trade_begin", "poison_hp_before",
}

# The card's required coverage for RR. A kind counts whether its leg is open or not: an open
# leg's citation stands in for the run not yet scripted.
_REQUIRED_COVERAGE = {
    "battle_end", "faint", "capture_wild", "pc_move", "pc_deposit", "pc_withdraw", "save",
    "map_load",
}

# There is NO pret source for RR's maps, so citations point at this repo's own receipts,
# pinned-address tables and profiles rather than at data/maps.
_CITATION_ROOTS = ("docs/", "data/games/", "lua/", "src/", "patch/", "include/")

# The savestates tools/mkstates.py produces (lua/tests/mkstate.lua kinds town|battle).
_KNOWN_STATES = {
    # tools/mkstates.py kinds town|battle, plus the ball-pocket fixture
    # lua/tests/mkstate_gen3_rr_fill.lua (SLINK_GIVE_BALLS) produces.
    "slink_prebattle_balls.State",
    "slink_prebattle.State", "slink_battle.State", "slink_actionmenu.State",
    "slink_movemenu.State", "slink_overworld.State", "slink_door.State",
    "slink_pokecenter.State", "slink_pokecenter_full.State",
}

_RUNNABLE = {
    "battle_to_field", "wild_faint", "wild_catch", "door_warp", "pc_ops", "pc_release", "save",
}

# RAM/coordinate/counter/predicate terminal helpers this driver actually uses.
_TERMINAL_HELPERS = (
    "G.pos", "G.map", "mapid(", "G.pred_ok", "G.pred(", "in_battle(", "on_field(",
    "party_count(", "player_bmon_hp(", "player_faints(", "party_snapshot(",
    "at_action_menu(", "battle_outcome(", "hold_until_map_change(", "walk_to(",
    "G.save_via_menu", "G.flash_domain",
)

_BIZHAWK_GLOBALS = ("gui", "movie", "bizstring", "input", "mainmemory")

# ── the fake machine ─────────────────────────────────────────────────────────────────────────
# A byte-addressed RAM table plus a frame clock. `FAKE.on_frame(frame)` is the ENGINE: every
# test installs one, and that function is the only thing that decides what the game "did".
_HARNESS = r"""
FAKE = { ram = {}, frame = 0, log = {}, on_frame = nil, a = 0, down = 0, buttons = {} }

local function r8(a) return FAKE.ram[a] or 0 end
local function w8(a, v) FAKE.ram[a] = v & 0xFF end

function FAKE.w8(a, v) w8(a, v) end
function FAKE.w16(a, v) w8(a, v); w8(a + 1, v >> 8) end
function FAKE.w32(a, v) FAKE.w16(a, v & 0xFFFF); FAKE.w16(a + 2, (v >> 16) & 0xFFFF) end

memory = {
    read_u8      = function(a) return r8(a) end,
    read_u16_le  = function(a) return r8(a) | (r8(a + 1) << 8) end,
    read_u32_le  = function(a) return r8(a) | (r8(a + 1) << 8) | (r8(a + 2) << 16)
                                  | (r8(a + 3) << 24) end,
    read_s16_le  = function(a)
        local v = r8(a) | (r8(a + 1) << 8)
        if v >= 0x8000 then v = v - 0x10000 end
        return v
    end,
    write_u8 = function(a, v) w8(a, v) end,
    getmemorydomainlist = function() return {} end,
    getmemorydomainsize = function() return 0 end,
}

emu = {
    frameadvance = function()
        FAKE.frame = FAKE.frame + 1
        if FAKE.on_frame then FAKE.on_frame(FAKE.frame) end
    end,
    framecount = function() return FAKE.frame end,
}

-- Rising-edge button counting: G.tap holds a button for 3 frames, so an edge count is a PRESS
-- count, which is what a menu reacts to.
local DXY = { Up = {0,-1}, Down = {0,1}, Left = {-1,0}, Right = {1,0} }

joypad = {
    set = function(t)
        t = t or {}
        if t.A and not FAKE.a_down then FAKE.a = FAKE.a + 1 end
        if t.Down and not FAKE.d_down then FAKE.down = FAKE.down + 1 end
        FAKE.a_down, FAKE.d_down = t.A and true or false, t.Down and true or false
        -- Movement, on the same 12-frame hold playlib step uses. FAKE.walls is a set of
        -- "x,y" tiles that refuse entry, so a fake map can be a real obstacle course.
        local dir
        for _, d in ipairs({ "Up", "Down", "Left", "Right" }) do if t[d] then dir = d end end
        if dir then
            if FAKE.dir == dir then FAKE.held = FAKE.held + 1 else FAKE.dir, FAKE.held = dir, 1 end
            if FAKE.held == 12 then
                local x, y = FAKE.get_pos()
                local nx, ny = x + DXY[dir][1], y + DXY[dir][2]
                if not (FAKE.walls or {})[nx .. "," .. ny] then FAKE.set_pos(nx, ny) end
            end
        else
            FAKE.dir, FAKE.held = nil, 0
        end
        FAKE.buttons = t
    end,
    get = function() return {} end,
}

console = { log = function(s) FAKE.log[#FAKE.log + 1] = tostring(s) end }
client = {
    exit = function() error("SLINK_EXIT", 0) end,   -- G.finish must ABORT, not fall through
    exitCode = function() end,
    screenshot = function() end,
    speedmode = function() end,
    saveram = function() end,
}
savestate = { load = function() return true end, save = function() return true end }
event = { onframeend = function() end, on_bus_exec = function() end }

-- Profile facts, re-declared here so the fake writes where the driver reads.
FAKE.PARTY_COUNT = 0x02024029
FAKE.PARTY_BASE  = 0x02024284
FAKE.BATTLE_MONS = 0x02023BE4
FAKE.CTRL        = 0x03004FE0
FAKE.ACTION_MENU = 0x0802E439
FAKE.RESULTS     = 0x03004F90
FAKE.BALLS       = 0x0203C354

function FAKE.init(cp)
    FAKE.cp        = cp
    FAKE.gmain     = cp.predicates.callback2.address
    FAKE.cb2_off   = cp.predicates.callback2.offset
    FAKE.cb2_ok    = cp.predicates.callback2.expect
    FAKE.ib_off    = cp.predicates.in_battle.offset
    FAKE.ib_mask   = cp.predicates.in_battle.mask
    FAKE.sb1ptr    = cp.pointers.gSaveBlock1Ptr.address
    FAKE.sb1       = 0x02025734
end

function FAKE.reset()
    FAKE.ram, FAKE.frame, FAKE.log = {}, 0, {}
    FAKE.a, FAKE.down, FAKE.on_frame = 0, 0, nil
    FAKE.dir, FAKE.held, FAKE.walls = nil, 0, {}
    FAKE.a_down, FAKE.d_down = false, false
    FAKE.set_sb1(true)
    FAKE.set_map(3, 1)
    FAKE.set_pos(15, 7)
end

function FAKE.set_battle(on)
    local a = FAKE.gmain + FAKE.ib_off
    local v = r8(a) & ~FAKE.ib_mask
    if on then v = v | FAKE.ib_mask end
    w8(a, v)
end
function FAKE.set_overworld(on)
    FAKE.w32(FAKE.gmain + FAKE.cb2_off, on and FAKE.cb2_ok or 0x08001234)
end
function FAKE.set_sb1(valid) FAKE.w32(FAKE.sb1ptr, valid and FAKE.sb1 or 0) end
function FAKE.set_map(g, n) w8(FAKE.sb1 + 4, g); w8(FAKE.sb1 + 5, n) end
function FAKE.set_pos(x, y) FAKE.w16(FAKE.sb1 + 0, x & 0xFFFF); FAKE.w16(FAKE.sb1 + 2, y & 0xFFFF) end
function FAKE.get_pos()
    return memory.read_s16_le(FAKE.sb1 + 0), memory.read_s16_le(FAKE.sb1 + 2)
end
function FAKE.set_menu(on) FAKE.w32(FAKE.CTRL, on and FAKE.ACTION_MENU or 0) end
function FAKE.set_bmon(hp, maxhp)
    FAKE.w16(FAKE.BATTLE_MONS + 0x28, hp)
    FAKE.w16(FAKE.BATTLE_MONS + 0x2C, maxhp)
end
function FAKE.set_faints(n) w8(FAKE.RESULTS, n) end
function FAKE.set_outcome(n) w8(0x02023E8A, n) end
--- CFRU ball pocket slot 0: a raw ItemSlot {u16 itemId, u16 quantity}.
function FAKE.set_balls(id, qty)
    FAKE.w16(FAKE.BALLS, id)
    FAKE.w16(FAKE.BALLS + 2, qty)
end

--- `list` is an array of {pid, otid, filler}; each becomes a 100-byte party record.
function FAKE.set_party(list)
    w8(FAKE.PARTY_COUNT, #list)
    for i, m in ipairs(list) do
        local base = FAKE.PARTY_BASE + (i - 1) * 100
        for w = 0, 24 do FAKE.w32(base + w * 4, 0) end
        FAKE.w32(base + 0, m[1])
        FAKE.w32(base + 4, m[2])
        FAKE.w32(base + 8, m[3] or 0)
    end
end

--- Run one leg closure, capturing its log. `ok` is false both for a real Lua error and for
--- G.finish's abort; the log says which, and every assertion below reads the log.
function FAKE.run_leg(fn)
    FAKE.log = {}
    local ok, err = pcall(fn, FAKE.cp)
    return ok, table.concat(FAKE.log, "\n"), tostring(err)
end
"""


@pytest.fixture(scope="module")
def lua():
    runtime = LuaRuntime(unpack_returned_tuples=True)
    runtime.execute(
        "\n".join(
            f"{name} = setmetatable({{}}, {{ __index = function(t, k)"
            f" local v = setmetatable({{}}, getmetatable(t)); rawset(t, k, v); return v end,"
            f" __call = function() return nil end }})"
            for name in _BIZHAWK_GLOBALS
        )
    )
    runtime.execute(_HARNESS)
    return runtime


@pytest.fixture(scope="module")
def module(lua):
    os.environ.setdefault("SLINK_ROOT", _LUA_REPO)
    os.environ["SLINK_GEN3_CHECKPOINT"] = f"{_LUA_REPO}/data/games/gen3_rr/write_checkpoint.json"
    os.environ["SLINK_GEN3_TITLE"] = "radical_red"
    mod = lua.execute(f'return dofile("{_LUA_REPO}/lua/tests/gen3_rr_scripted_play.lua")')
    # The REAL RR checkpoint drives the fake, so every predicate address/mask/expectation
    # exercised below is the one the lane uses.
    cp = mod.boot_check.checkpoint()[0]   # checkpoint() returns (cp, title_key)
    lua.globals().FAKE.init(cp)
    return mod


@pytest.fixture(scope="module")
def legs(module):
    return module.LEGS


@pytest.fixture
def fake(lua, module):
    """A reset machine, plus a zeroed frame budget on the driver's own boot_check instance."""
    f = lua.globals().FAKE
    f.reset()
    module.boot_check.spent = 0
    module.boot_check.budget = 400000
    return f


def _py_list(lua_table):
    return [lua_table[i] for i in range(1, len(lua_table) + 1)]


def _each(legs):
    for i in range(1, len(legs) + 1):
        yield legs[i]


def _leg(legs, name):
    for leg in _each(legs):
        if leg["name"] == name:
            return leg
    raise AssertionError(f"no leg named {name!r}")


# ── shape ────────────────────────────────────────────────────────────────────────────────────


def test_the_script_loads_without_running_any_leg(legs):
    assert len(legs) >= 7


def test_every_leg_names_at_least_one_known_site_kind(legs):
    for leg in _each(legs):
        kinds = _py_list(leg["exercises"])
        assert kinds, f"leg {leg['name']!r} names no site kinds"
        unknown = [k for k in kinds if k not in _KNOWN_KINDS]
        assert not unknown, f"leg {leg['name']!r} names unknown kind(s) {unknown}"


def test_every_leg_carries_a_citation(legs):
    for leg in _each(legs):
        sources = _py_list(leg["source"])
        assert sources, f"leg {leg['name']!r} has no source citations"
        for cite in sources:
            assert any(root in cite for root in _CITATION_ROOTS), (
                f"leg {leg['name']!r} citation {cite!r} points at none of {_CITATION_ROOTS}"
            )


def test_required_site_kinds_are_covered_somewhere_in_the_union(legs):
    covered = set()
    for leg in _each(legs):
        covered |= set(_py_list(leg["exercises"]))
    assert not _REQUIRED_COVERAGE - covered, f"no leg exercises {_REQUIRED_COVERAGE - covered}"


def test_every_leg_declares_the_savestate_it_starts_from(legs):
    for leg in _each(legs):
        state = leg["state"]
        assert state, f"leg {leg['name']!r} declares no savestate"
        assert state in _KNOWN_STATES, (
            f"leg {leg['name']!r} wants {state!r}, which tools/mkstates.py does not produce"
        )


def test_every_runnable_leg_has_a_precondition_check(legs):
    """A leg that does not validate the situation it was handed cannot enforce a precondition,
    however faithfully the loop loads its state."""
    for leg in _each(legs):
        if not leg["open"]:
            assert leg["check"] is not None, f"leg {leg['name']!r} has no check()"


def test_open_legs_are_marked_carry_a_reason_and_have_no_run_body(legs):
    saw_open = False
    for leg in _each(legs):
        if leg["open"]:
            saw_open = True
            assert leg["open_reason"], f"leg {leg['name']!r} is open with no reason"
            assert leg["run"] is None, f"open leg {leg['name']!r} carries an uncallable run body"
    assert saw_open, "expected pc_move_full_party to be open (no full-party savestate)"


def test_the_runnable_legs_are_the_ones_the_card_asked_for(legs):
    assert {leg["name"] for leg in _each(legs) if not leg["open"]} == _RUNNABLE
    for leg in _each(legs):
        if not leg["open"]:
            assert leg["run"] is not None, f"leg {leg['name']!r} has no run body"


def test_leg_names_are_unique(legs):
    names = [leg["name"] for leg in _each(legs)]
    assert len(names) == len(set(names))


def test_pc_release_runs_after_pc_ops_and_before_save(legs):
    """pc_release reuses pc_ops's own route to the PC and its shared menu helpers -- it must
    run after pc_ops in the file, and before the save leg that ends the sequence."""
    names = [leg["name"] for leg in _each(legs)]
    assert names.index("pc_ops") < names.index("pc_release") < names.index("save")


def test_pc_release_declares_the_pokecenter_state_and_the_pinned_site_pair(legs):
    leg = _leg(legs, "pc_release")
    assert leg["state"] == "slink_pokecenter_full.State"
    assert set(_py_list(leg["exercises"])) == {"pc_release_begin", "pc_release"}


def test_pc_release_confirmation_moves_off_the_no_default_before_confirming():
    """Task_ReleaseMon's Yes/No box starts on NO (ShowYesNoWindow(1),
    pokefirered src/pokemon_storage_system_tasks.c:1261) and does not wrap
    (Menu_MoveCursorNoWrapAround), so an Up press before the confirming A is not optional --
    the FR driver's own pc_release leg skips it and says outright that the press is unpinned
    (lua/tests/gen3_scripted_play.lua:1263-1267). This greps the RAW source rather than the
    parsed leg table because the press sequence is code, not a leg field."""
    start = _SCRIPT_SRC.index('name = "pc_release"')
    release_src = _SCRIPT_SRC[start:_SCRIPT_SRC.index("\n}\n", start)]
    up_idx = release_src.find('pc_press("Up"')
    release_idx = release_src.find('-- RELEASE ->')
    confirm_idx = release_src.find('pc_press("A", 240)')
    assert up_idx != -1, "pc_release never presses Up before confirming"
    assert release_idx < up_idx < confirm_idx, (
        "pc_release must press Up (off the NO default) after selecting RELEASE and before the "
        "confirming A"
    )
    assert "ShowYesNoWindow(1)" in release_src
    assert "does not wrap" in release_src or "no wrap" in release_src.lower()


def test_state_path_resolves_bare_names_and_passes_absolute_ones_through(module):
    fn = module.state_path
    assert fn("slink_door.State").endswith("/slink_door.State")
    assert fn("slink_door.State") != "slink_door.State"          # a directory was prepended
    assert fn("E:/x/slink_door.State") == "E:/x/slink_door.State"
    assert fn("") is None
    assert fn(None) is None


_RUN_BODY_RE = re.compile(r"run = function\(cp\)(.*?)\n    end,", re.DOTALL)


def test_no_run_body_terminates_on_a_bare_frame_count():
    bodies = _RUN_BODY_RE.findall(_SCRIPT_SRC)
    assert len(bodies) == len(_RUNNABLE), f"expected one run body per runnable leg, got {len(bodies)}"
    for body in bodies:
        assert any(h in body for h in _TERMINAL_HELPERS), (
            "a leg's run body has no RAM/coordinate/counter/predicate terminal helper:\n" + body
        )


def test_the_driver_owns_no_runner_of_its_own():
    """The leg runner, the per-leg savestate load, the precondition check, the open-leg
    reporting and the shadow block all live in lua/tests/playlib.lua now, and their BEHAVIOUR is
    tested there (tests/unit/test_playlib.py) against a fake game rather than by scanning this
    source. What this file still owns is the wiring: that the driver hands playlib the right
    result path and lets it run the legs."""
    assert 'dofile(WT .. "/lua/tests/playlib.lua")' in _SCRIPT_SRC
    assert "play.main(LEGS, {" in _SCRIPT_SRC
    for gone in ("local reached, skipped", "local function mash_a", "local function state_path",
                 "local function in_battle", "local function on_field", "for i = from_idx"):
        assert gone not in _SCRIPT_SRC, f"{gone} is playlib's job now, not the driver's"


def test_the_driver_never_mashes_start_in_the_overworld():
    """G.mash pulses Start every 16 frames, which opens the START menu the moment a leg lands
    back on the field -- the reason this driver carries its own A-only mash."""
    assert "G.mash(" not in _SCRIPT_SRC


def test_the_shared_runtime_is_bound_with_the_rr_host_and_game_facts():
    """playlib holds no host call and no game fact (Codex cx-67a6e199): every one of these has
    to be supplied here, or the library could not run at all."""
    binding = _SCRIPT_SRC.split("local H = {")[1].split(chr(10) + "local play")[0]
    for name in ("press", "map", "in_battle", "on_field", "scene_quiet", "party_count",
                 "load_state", "register_frame_end", "unregister_frame_end", "observer"):
        assert name + " " in binding or name + "=" in binding or name + " =" in binding, name
    opts = _SCRIPT_SRC.split("play = PL.bind(H, {")[1].split(chr(10) + "})")[0]
    assert "state_dir" in opts
    assert "battle" in opts, "how RR fights is the binding's, not the library's"


def test_duo_precedent_constants_are_labelled_as_such():
    """CTRL_ADDR/ACTION_MENU live in no profile and no checkpoint; a reader must not mistake
    them for pinned facts."""
    head = _SCRIPT_SRC.split("local function party_count")[0]
    assert "DUO-PRECEDENT CONSTANTS, NOT PROFILE FACTS" in head
    assert "scenario_explode.lua:27-28" in head


def test_the_shadow_observer_writes_the_rr_result_file():
    assert "gen3_rr_scripted_play_result.txt" in _SCRIPT_SRC
    assert "lua/gen3/shadow_run.lua" in _SCRIPT_SRC


# ── behaviour: battle_to_field ───────────────────────────────────────────────────────────────


def test_battle_to_field_passes_on_a_real_battle_to_field_transition(lua, fake, legs):
    fake.set_battle(True)
    fake.set_overworld(False)
    lua.execute("""
        FAKE.on_frame = function(f)
            if f >= 200 then FAKE.set_battle(false); FAKE.set_overworld(true) end
        end
    """)
    leg = _leg(legs, "battle_to_field")
    assert leg["check"](lua.globals().FAKE.cp) is None
    ok, log, err = lua.globals().FAKE.run_leg(leg["run"])
    assert ok, f"{err}\n{log}"
    assert "phase field" in log


def test_battle_to_field_refuses_to_start_when_already_on_the_field(lua, fake, legs):
    """Starting outside a battle would sail through every terminal without the engine ever
    executing ReturnFromBattleToOverworld -- a PASS for nothing."""
    fake.set_battle(False)
    fake.set_overworld(True)
    why = _leg(legs, "battle_to_field")["check"](lua.globals().FAKE.cp)
    assert why is not None
    assert "already on the field" in why


def test_battle_to_field_fails_when_the_battle_never_ends(lua, fake, legs):
    fake.set_battle(True)
    fake.set_overworld(False)          # no on_frame: the engine never leaves the battle
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "battle_to_field")["run"])
    assert not ok
    assert "RESULT: FAIL" in log
    assert "the battle never ended" in log


# ── behaviour: hold_until_map_change ─────────────────────────────────────────────────────────


def test_a_warp_that_really_happens_is_accepted(lua, fake, module):
    fake.set_overworld(True)
    lua.execute("""
        FAKE.on_frame = function(f) if f >= 100 then FAKE.set_map(5, 4) end end
    """)
    ok, detail = module.play.enter_warp(lua.globals().FAKE.cp, "Up", 30)
    assert ok, detail
    assert "769 -> 1284" in detail      # (3,1) -> (5,4)


def test_an_unreadable_map_pointer_is_not_a_map_change(lua, fake, module):
    """G.map returns -1,-1 whenever the SaveBlock1 pointer is not sane. Comparing that against
    a readable id looks exactly like a warp; accepting it would pass this leg while the engine
    was in the middle of nothing at all."""
    fake.set_sb1(False)
    fake.set_overworld(True)
    ok, detail = module.play.enter_warp(lua.globals().FAKE.cp, "Up", 30)
    assert not ok
    assert "unreadable" in detail


def test_a_map_change_that_never_settles_back_to_the_field_fails(lua, fake, module):
    fake.set_overworld(False)          # the fade never finishes
    lua.execute("""
        FAKE.on_frame = function(f) if f >= 100 then FAKE.set_map(5, 4) end end
    """)
    ok, detail = module.play.enter_warp(lua.globals().FAKE.cp, "Up", 30)
    assert not ok
    assert "never settled" in detail


# ── behaviour: pc_ops keyed oracle ───────────────────────────────────────────────────────────

_PARTY_ABC = "{ {0xAAAA0001, 0x1111, 0xA0}, {0xBBBB0002, 0x2222, 0xB0}, {0xCCCC0003, 0x3333, 0xC0} }"
# _PARTY_ABC with slot 2 (CCCC0003, the third mon) gone and the other two untouched -- the clean
# release pc_release's oracle must accept.
_PARTY_ABC_MINUS_C = "{ {0xAAAA0001, 0x1111, 0xA0}, {0xBBBB0002, 0x2222, 0xB0} }"


def _pc_scenario(lua, fake, after_withdraw: str):
    """Deposit at 5 A-presses, withdraw at 12. `after_withdraw` is the Lua party literal the
    fake engine hands back -- which is where each negative below differs."""
    fake.set_battle(False)
    fake.set_overworld(True)
    fake.set_pos(7, 8)                 # slink_pokecenter_full.State stands here
    lua.execute(f"""
        FAKE.set_party({_PARTY_ABC})
        FAKE.on_frame = function()
            -- the PHYSICAL flow (census_rr_pc_deposit_2026-09-21.txt): five A presses to
            -- reach the storage menu, then Down+A, Down+A, A to deposit -- and the same five
            -- again before the withdraw's three
            if FAKE.a >= 16 then FAKE.set_party({after_withdraw})
            elseif FAKE.a >= 8 then
                FAKE.set_party({{ {{0xBBBB0002, 0x2222, 0xB0}}, {{0xCCCC0003, 0x3333, 0xC0}} }})
            end
        end
    """)


def test_pc_ops_accepts_a_real_round_trip_even_though_the_record_is_lossy(lua, fake, legs):
    """RR stores a 58-byte CompressedPokemon, so the travelling record legitimately comes back
    with different bytes; its KEY must survive, and the records that stayed must not move."""
    _pc_scenario(lua, fake,
                 "{ {0xBBBB0002, 0x2222, 0xB0}, {0xCCCC0003, 0x3333, 0xC0}, "
                 "{0xAAAA0001, 0x1111, 0xDEAD} }")
    ok, log, err = lua.globals().FAKE.run_leg(_leg(legs, "pc_ops")["run"])
    assert ok, f"{err}\n{log}"
    assert "AAAA0001:00001111 left the party" in log
    assert "is back" in log


def test_pc_ops_fails_when_a_different_mon_comes_back(lua, fake, legs):
    """Deposit A, withdraw B: the count returns to 3, which a count-only oracle would accept."""
    _pc_scenario(lua, fake,
                 "{ {0xBBBB0002, 0x2222, 0xB0}, {0xCCCC0003, 0x3333, 0xC0}, "
                 "{0xBBBB0002, 0x2222, 0xB0} }")
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "pc_ops")["run"])
    assert not ok
    assert "RESULT: FAIL" in log
    assert "withdrawn mon is NOT the deposited one" in log


def test_pc_ops_fails_when_the_deposited_mon_was_released_and_another_withdrawn(lua, fake, legs):
    """A released-and-replaced mon also restores the count. It is not a round trip."""
    _pc_scenario(lua, fake,
                 "{ {0xBBBB0002, 0x2222, 0xB0}, {0xCCCC0003, 0x3333, 0xC0}, "
                 "{0xEEEE0009, 0x9999, 0xE0} }")
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "pc_ops")["run"])
    assert not ok
    assert "RESULT: FAIL" in log
    assert "withdrawn mon is NOT the deposited one" in log


def test_pc_ops_fails_when_a_bystander_record_changed(lua, fake, legs):
    _pc_scenario(lua, fake,
                 "{ {0xBBBB0002, 0x2222, 0xBEEF}, {0xCCCC0003, 0x3333, 0xC0}, "
                 "{0xAAAA0001, 0x1111, 0xA0} }")
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "pc_ops")["run"])
    assert not ok
    assert "is not byte-identical after the round trip" in log


def test_pc_ops_fails_when_the_storage_ui_never_closes(lua, fake, legs):
    """The final return to the field is an assertion, not a courtesy: leaving the UI up hands
    the next leg a broken starting point."""
    _pc_scenario(lua, fake,
                 "{ {0xBBBB0002, 0x2222, 0xB0}, {0xCCCC0003, 0x3333, 0xC0}, "
                 "{0xAAAA0001, 0x1111, 0xDEAD} }")
    lua.execute("""
        local inner = FAKE.on_frame
        FAKE.on_frame = function(f)
            inner(f)
            if FAKE.a >= 16 then FAKE.set_overworld(false) end   -- the UI never closes
        end
    """)
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "pc_ops")["run"])
    assert not ok
    assert "never got back to the field from the menu" in log


# ── behaviour: pc_release keyed oracle ───────────────────────────────────────────────────────
# Press-count map for pc_release's FIXED script (no branching, so the count is exact): 5 A's to
# open the storage menu, Down+A into the party view, Down+Down+A onto slot 2's popup, three
# Downs to RELEASE, A to pick it (a=8), Up (no A) off the ShowYesNoWindow(1) NO default, then A
# confirms (a=9) -- the mutation threshold below -- and two more A's dismiss the follow-up
# messages (a=10, a=11).


def _release_scenario(lua, fake, after_release: str):
    """Deposit-mode party view on slot 2 (the third mon, key CCCC0003:00003333). The fake
    mutates the party once FAKE.a reaches 9, the confirming A -- exactly where ReleaseMon()
    fires in Task_ReleaseMon's own state machine (pokefirered src/pokemon_storage_system_tasks.c
    :1301-1306)."""
    fake.set_battle(False)
    fake.set_overworld(True)
    fake.set_pos(7, 8)                 # slink_pokecenter_full.State stands here
    lua.execute(f"""
        FAKE.set_party({_PARTY_ABC})
        FAKE.on_frame = function()
            if FAKE.a >= 9 then FAKE.set_party({after_release}) end
        end
    """)


def test_pc_release_accepts_a_clean_release_of_the_targeted_slot(lua, fake, legs):
    """Down,Down from the lead selects slot 2 -- the third mon, CCCC0003 -- so a release that
    removes exactly that key and leaves the other two byte-identical must pass."""
    _release_scenario(lua, fake, _PARTY_ABC_MINUS_C)
    ok, log, err = lua.globals().FAKE.run_leg(_leg(legs, "pc_release")["run"])
    assert ok, f"{err}\n{log}"
    assert "phase released" in log
    assert "party 3 -> 2" in log
    assert "CCCC0003:00003333 gone" in log


def test_pc_release_fails_when_the_party_count_never_drops(lua, fake, legs):
    """The scenario the pret-pinned Up press exists to prevent: ShowYesNoWindow(1) starts the
    confirmation on NO, and a press sequence that confirms without moving off it declines the
    release, so the party never shrinks. If a future edit ever drops that Up, this is what
    should fail -- not a silent no-op PASS."""
    fake.set_battle(False)
    fake.set_overworld(True)
    fake.set_pos(7, 8)
    lua.execute(f"FAKE.set_party({_PARTY_ABC})")   # on_frame left unset: nothing ever mutates
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "pc_release")["run"])
    assert not ok
    assert "RESULT: FAIL" in log
    assert "the party count is 3, not 2" in log


def test_pc_release_fails_when_the_wrong_slot_is_released(lua, fake, legs):
    """The count drops by exactly one, but it is the LEAD (slot 0) that vanished, not the
    targeted slot 2 -- a count-only oracle would accept this."""
    _release_scenario(lua, fake,
                       "{ {0xBBBB0002, 0x2222, 0xB0}, {0xCCCC0003, 0x3333, 0xC0} }")
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "pc_release")["run"])
    assert not ok
    assert "RESULT: FAIL" in log
    assert "left instead" in log


def test_pc_release_fails_when_a_survivor_record_changed(lua, fake, legs):
    _release_scenario(lua, fake,
                       "{ {0xAAAA0001, 0x1111, 0xDEAD}, {0xBBBB0002, 0x2222, 0xB0} }")
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "pc_release")["run"])
    assert not ok
    assert "RESULT: FAIL" in log
    assert "not byte-identical" in log


def test_pc_release_fails_when_the_storage_ui_never_closes(lua, fake, legs):
    _release_scenario(lua, fake, _PARTY_ABC_MINUS_C)
    lua.execute("""
        local inner = FAKE.on_frame
        FAKE.on_frame = function(f)
            inner(f)
            if FAKE.a >= 9 then FAKE.set_overworld(false) end   -- the UI never closes
        end
    """)
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "pc_release")["run"])
    assert not ok
    assert "never got back to the field from the menu" in log


# ── behaviour: wild_faint ────────────────────────────────────────────────────────────────────


def test_wild_faint_will_not_call_it_a_faint_without_the_engines_own_counter(lua, fake, legs):
    """The player battler goes positive -> 0 HP every encounter, but gBattleResults's
    playerFaintCounter never moves -- exactly what a host-side HP poke looks like. The leg must
    refuse it rather than report a faint the engine never processed."""
    fake.set_battle(False)
    fake.set_overworld(True)
    fake.set_faints(0)
    lua.execute("""
        FAKE.on_frame = function(f)
            local t = f % 800
            if t < 300 then
                FAKE.set_battle(false); FAKE.set_overworld(true)
                FAKE.set_menu(false); FAKE.set_bmon(0, 0)
            else
                FAKE.set_battle(true); FAKE.set_overworld(false); FAKE.set_menu(true)
                if t < 600 then FAKE.set_bmon(20, 20) else FAKE.set_bmon(0, 20) end
            end
        end
    """)
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "wild_faint")["run"])
    assert not ok
    assert "RESULT: FAIL" in log
    assert "no witnessed player faint" in log
    assert "hp_zero=true" in log        # the HP transition WAS seen; the counter is what failed


# -- behaviour: wild_catch (the pinned CFRU bag sequence) --------------------------------------


def _catch_world(lua, fake, *, balls=5, throws_to_catch=1):
    """A battle at the action menu with `balls` Poke Balls in CFRU's EWRAM pocket. The pinned
    sequence sends exactly three A presses per throw (open BAG, select, use), so the fake
    resolves a throw on every third one."""
    fake.set_battle(True)
    fake.set_overworld(False)
    fake.set_menu(True)
    fake.set_balls(4, balls)
    fake.set_outcome(0)
    lua.execute(f"""
        FAKE.set_party({{ {{0xAAAA0001, 0x1111, 0xA0}} }})
        FAKE.on_frame = function()
            -- The pinned sequence spends exactly three A presses per throw, and a THROWN ball
            -- leaves the pocket -- which is the witness the leg waits on.
            local throws = FAKE.a // 3
            FAKE.set_balls(4, math.max({balls} - throws, 0))
            if throws >= {throws_to_catch} then
                FAKE.set_menu(false)
                FAKE.set_outcome(7)                       -- B_OUTCOME_CAUGHT
                if FAKE.a >= {throws_to_catch} * 3 + 4 then
                    FAKE.set_battle(false); FAKE.set_overworld(true)
                    FAKE.set_party({{ {{0xAAAA0001, 0x1111, 0xA0}},
                                     {{0xCAFE0002, 0x2222, 0xB0}} }})
                end
            end
        end
    """)


def test_wild_catch_refuses_a_state_with_no_balls_in_the_pocket(lua, fake, legs):
    """The fixture IS the precondition: opening the BAG with an empty ball pocket wanders
    through a menu it cannot use and fails much later with something misleading."""
    fake.set_battle(True)
    fake.set_balls(0, 0)
    why = _leg(legs, "wild_catch")["check"](lua.globals().FAKE.cp)
    assert why is not None
    assert "make the balls state first" in why
    assert "slink_prebattle_balls.State" in why


def test_wild_catch_accepts_a_pocket_holding_poke_balls(lua, fake, legs):
    fake.set_balls(4, 5)
    assert _leg(legs, "wild_catch")["check"](lua.globals().FAKE.cp) is None


def test_wild_catch_passes_when_the_ball_lands_and_the_party_grows(lua, fake, legs):
    _catch_world(lua, fake)
    ok, log, err = lua.globals().FAKE.run_leg(_leg(legs, "wild_catch")["run"])
    assert ok, f"{err}\n{log}"
    assert "outcome=7, party 1 -> 2" in log


def test_wild_catch_retries_with_the_next_ball_after_a_miss(lua, fake, legs):
    """A miss returns to the action menu; the bound is the fixture ball count, not a frame
    count, so the sequence simply runs again."""
    _catch_world(lua, fake, balls=5, throws_to_catch=3)
    ok, log, err = lua.globals().FAKE.run_leg(_leg(legs, "wild_catch")["run"])
    assert ok, f"{err}\n{log}"
    assert "throw 1: outcome=0 balls 5 -> 4, back at the menu" in log
    assert "throw 3: outcome=7 balls 3 -> 2" in log   # the pocket is the witness
    assert "after 3 throw(s)" in log


def test_wild_catch_fails_when_no_ball_ever_lands(lua, fake, legs):
    _catch_world(lua, fake, balls=2, throws_to_catch=99)
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "wild_catch")["run"])
    assert not ok
    assert "RESULT: FAIL" in log
    assert "gBattleOutcome is 0, not 7" in log


def test_wild_catch_fails_when_the_outcome_says_caught_but_the_party_did_not_grow(lua, fake, legs):
    """B_OUTCOME_CAUGHT with room in the party and no new record means the mon did not actually
    reach the party -- the acquisition site never ran, whatever the text said."""
    _catch_world(lua, fake)
    lua.execute("""
        local inner = FAKE.on_frame
        FAKE.on_frame = function(f)
            inner(f)
            FAKE.set_party({ {0xAAAA0001, 0x1111, 0xA0} })     -- the party never grows
        end
    """)
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "wild_catch")["run"])
    assert not ok
    assert "the party went 1 -> 1" in log


def test_the_pokecenter_path_is_bfs_pinned_against_the_parsed_collision_grid(module):
    """RR has no pret source, but its map headers parse, so this path is held to the same
    standard as FireRed's: a BFS over the collision grid read out of the ROM, with the NPC
    spawn tiles blocked. The grid is re-stated here so the path cannot drift away from it."""
    rows = ["#.#############", "###########P###", "....###..##....", "....#######....",
            "...............", "...............", "#..........##..", "...........##..",
            "...............", "###############"]
    npcs = {(2, 3), (4, 7), (7, 2), (8, 2), (10, 6), (12, 5)}
    delta = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}
    path = module.PATHS["pokecenter_start_to_pc"]
    x, y = path["from"][1], path["from"][2]
    dirs = [path["dirs"][i] for i in range(1, len(path["dirs"]) + 1)]
    for step in dirs:
        x, y = x + delta[step][0], y + delta[step][1]
        assert rows[y][x] == ".", f"step {step} walks into collision at ({x},{y})"
        assert (x, y) not in npcs, f"step {step} walks into an NPC at ({x},{y})"
    assert (x, y) == (path["to"][1], path["to"][2]) == (11, 2)
    assert rows[y - 1][x] == "P", "the path does not end below the PC metatile"


def test_wild_catch_fails_when_the_bag_sequence_never_spends_a_ball(lua, fake, legs):
    """The lane called all five throws misses at 170-frame spacing -- it was judging the result
    before the ball animation had started. The pocket quantity is the witness: if no ball left
    the bag, the sequence never reached USE, and saying THAT is worth more than five fake
    misses."""
    _catch_world(lua, fake)
    lua.execute("FAKE.on_frame = function() FAKE.set_balls(4, 5) end")   # the pocket never moves
    ok, log, _err = lua.globals().FAKE.run_leg(_leg(legs, "wild_catch")["run"])
    assert not ok
    assert "ball not thrown on throw 1" in log
    assert "never reached USE" in log


def test_the_frame_end_binding_reports_a_refused_registration(lua, module):
    """`id or name` fabricated a handle whenever event.onframeend returned nil, which sailed
    past playlib's "was it registered?" check and then handed a NAME to unregisterbyid
    (Codex cx-bc675fa4). This drives the driver's OWN binding against both host shapes."""
    reg = module.play.H.register_frame_end
    lua.execute("event = { onframeend = function() return nil end }")
    assert reg(lua.eval("function() end"), "poll") is None
    lua.execute("event = { onframeend = function() error('no hooks left', 0) end }")
    assert reg(lua.eval("function() end"), "poll") is None
    lua.execute("event = { onframeend = function() return 77 end }")
    assert reg(lua.eval("function() end"), "poll") == 77


def test_the_binding_supplies_the_input_policies_and_a_savestate_writer(module):
    """Which button clears a textbox, which advances a scene, and how a state is written are
    per-game/per-host facts; playlib holds none of them."""
    assert module.play.opts.clear_dialogue is not None
    assert module.play.opts.advance_scene is not None
    assert module.play.H.save_state is not None
