"""2B-TUTORIAL-STATES: mkstates_gen3_tutorials.lua's addresses, route, fixtures and witnesses.

Addresses/spans are checked against both committed .sym/.map files; the route against pret's
ViridianCity map.json (and the ROM layouts when the dumps are here); the witnesses over fake
RAM whose memory table has NO write functions at all.
"""
import json
import os
import re
import sys
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gba_map  # noqa: E402
import gen_gen3_write_checkpoint as gw  # noqa: E402
import mkstates_gen3_tutorials as tool  # noqa: E402

from server.adapters import gen3_codec as codec  # noqa: E402

LUA_PATH = ROOT / "lua/tests/mkstates_gen3_tutorials.lua"
SOURCE = LUA_PATH.read_text(encoding="utf-8")
PRET = ROOT.parents[2] / ".cache/pret/pokefirered"   # worktree -> repo root/.cache
TITLES = {"firered": "pokefirered", "leafgreen": "pokeleafgreen"}
ROMS = {"firered": "E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba",
        "leafgreen": "E:/Google Drive/SLink/Pokemon - LeafGreen Version (USA).gba"}
DELTA = {"Up": (0, -1), "Down": (0, 1), "Left": (-1, 0), "Right": (1, 0)}
SB1 = 0x02025000
KEY_OFF, KEY_N = 0x3B8, 30


def sym(name, stem):
    text = (ROOT / f"data/gen3/pret/{stem}.sym").read_text(encoding="utf-8")
    return int(re.search(rf"^([0-9a-f]{{8}}) \S+ \S+ {name}$", text, re.M).group(1), 16)


class Ram:
    """Fake memory: reads only. Any write attempt raises (there is no write_* at all)."""

    def __init__(self):
        self.b = {}

    def put(self, addr, value, width):
        for i in range(width):
            self.b[addr + i] = (value >> (8 * i)) & 0xFF

    def read(self, addr, width):
        return sum(self.b.get(addr + i, 0) << (8 * i) for i in range(width))


@pytest.fixture()
def env():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    ram = Ram()
    lua.globals().py_read = ram.read
    lua.execute("""
        memory = setmetatable({
            read_u8 = function(a) return py_read(a, 1) end,
            read_u16_le = function(a) return py_read(a, 2) end,
            read_u32_le = function(a) return py_read(a, 4) end,
        }, { __index = function(_, k) error("memory." .. tostring(k) .. " is not allowed", 2) end })
        mainmemory = memory
    """)
    return lua, lua.execute(SOURCE), ram


def pocket(lua):
    return lua.table(KEY_OFF, KEY_N)


# ── addresses ────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title", sorted(TITLES))
def test_addresses_match_sym_and_map(env, title):
    _, m, _ = env
    stem = TITLES[title]
    assert sym("gBattleTypeFlags", stem) == m.BATTLE_TYPE_FLAGS_ADDR
    assert sym("gBattlerControllerFuncs", stem) == m.BATTLER_CTRL_ADDR
    assert sym("sStaticResources", stem) == m.TTV_STATIC_ADDR
    assert sym("sContextMenuItemsPtr", stem) == m.CONTEXT_ITEMS_PTR_ADDR
    assert sym("sStartMenuCursorPos", stem) == m.START_MENU_CURSOR_ADDR
    assert sym("sNumStartMenuItems", stem) == m.START_MENU_COUNT_ADDR
    assert sym("sStartMenuOrder", stem) == m.START_MENU_ORDER_ADDR
    assert sym("sStartMenuWindowId", stem) == m.START_MENU_WINDOW_ADDR
    assert sym("gMain", stem) + 4 == m.GMAIN_CALLBACK2_ADDR
    assert sym("gTasks", stem) == m.TASKS_ADDR
    assert sym("gPaletteFade", stem) + 7 == m.PALETTE_FADE_BYTE_ADDR
    t = m.TITLES[title]
    for key, name in (("TASK_FIELD_ITEM_CONTEXT", "Task_FieldItemContextMenuHandleInput"),
                      ("CB2_TEACHY_TV", "TeachyTvCallback"),
                      ("TASK_TTV_LIST", "TeachyTvOptionListController"),
                      ("TASK_TTV_MSG", "TeachyTvRenderMsgAndSwitchClusterFuncs")):
        assert t[key] == sym(name, stem) | 1, key
    mp = ROOT / f"data/gen3/pret/{stem}.map"
    for kind in ("oak_old_man", "pokedude"):
        lo, hi = gw.text_span(mp, f"src/battle_controller_{kind}.o")
        assert (t[kind][1], t[kind][2]) == (lo, hi)
    # the setters the engine installs really are inside those spans
    assert lo <= sym("SetControllerToPokedude", stem) < hi
    assert t.oak_old_man[1] <= sym("SetControllerToOakOrOldMan", stem) < t.oak_old_man[2]


def test_constants_match_pret(env):
    _, m, _ = env
    if not PRET.exists():
        pytest.skip("pret checkout not present")
    battle = (PRET / "include/constants/battle.h").read_text()
    assert f"BATTLE_TYPE_OLD_MAN_TUTORIAL   (1 << {m.OLD_MAN.bit_length() - 1})" in battle
    assert f"BATTLE_TYPE_POKEDUDE           (1 << {m.POKEDUDE.bit_length() - 1})" in battle
    assert re.search(rf"VAR_MAP_SCENE_VIRIDIAN_CITY_OLD_MAN\s+0x{m.VAR_OLD_MAN:04X}",
                     (PRET / "include/constants/vars.h").read_text())
    assert f"#define ITEM_TEACHY_TV {m.ITEM_TEACHY_TV}" in (PRET / "include/constants/items.h").read_text()
    assert f"ITEMMENUACTION_USE           {m.ITEMMENUACTION_USE}" in (
        PRET / "include/constants/item_menu.h").read_text()
    ttv = (PRET / "src/teachy_tv.c").read_text()
    for table in ("sListMenuItems[]", "sListMenuItems_NoTMCase[]"):   # TTVSCR_BATTLE is row 0
        body = ttv[ttv.index(table):]
        assert body.index("TTVSCR_BATTLE") < body.index(".index", body.index(".label") + 1) + 40
        assert body[:body.index("TTVSCR_BATTLE")].count(".index") == 1


# ── route ────────────────────────────────────────────────────────────────────────────────────

def tiles(m):
    x, y = m.START[1], m.START[2]
    out, ends = [], []
    for seg in m.SEGMENTS.values():
        dx, dy = DELTA[seg[1]]
        for _ in range(seg[2]):
            x, y = x + dx, y + dy
            out.append((x, y))
        ends.append(((x, y), (seg[3][1], seg[3][2])))
    return out, ends


def test_route_segments_end_where_they_say(env):
    _, m, _ = env
    walked, ends = tiles(m)
    assert all(a == b for a, b in ends)
    assert (walked[-1][0], walked[-1][1] - 1) == (m.TRIGGER[1], m.TRIGGER[2])


def test_route_meets_only_the_right_trigger(env):
    _, m, _ = env
    if not PRET.exists():
        pytest.skip("pret checkout not present")
    d = json.loads((PRET / "data/maps/ViridianCity/map.json").read_text())
    walked, _ = tiles(m)
    trig = {(c["x"], c["y"]): c for c in d["coord_events"]}
    right = trig[(m.TRIGGER[1], m.TRIGGER[2])]
    assert (right["script"], right["var"], right["var_value"]) == (
        "ViridianCity_EventScript_TutorialTriggerRight", "VAR_MAP_SCENE_VIRIDIAN_CITY_OLD_MAN", "1")
    for t in walked:   # (22,11) RoadBlocked fires only at var 0; nothing else is on the path
        assert t not in trig or trig[t]["var_value"] == "0", t
    statics = {(o["x"], o["y"]) for o in d["object_events"] if o["movement_range_x"] == 0}
    assert not statics & set(walked)


@pytest.mark.parametrize("title", sorted(TITLES))
def test_route_walkable_on_rom(env, title):
    _, m, _ = env
    if not os.path.exists(ROMS[title]):
        pytest.skip("ROM not on this machine")
    viridian = gba_map.load(ROMS[title], sym_path=ROOT / f"data/gen3/pret/{TITLES[title]}.sym").map(3, 1)
    walked, _ = tiles(m)
    for x, y in walked + [(m.TRIGGER[1], m.TRIGGER[2])]:
        assert viridian.collision[y][x] == 0, (x, y)
        assert viridian.behaviour[y][x] not in gba_map.DEFAULT_AVOID_BEHAVIOURS, (x, y)


# ── fixtures (read-only) ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title", sorted(TITLES))
def test_town_fixture_is_at_the_start_before_the_tutorial(title):
    sb1 = codec.parse_flash((ROOT / f"tests/fixtures/gen3/{title}_party_town.sav").read_bytes())["sb1"]
    pos = (int.from_bytes(sb1[0:2], "little"), int.from_bytes(sb1[2:4], "little"))
    assert (sb1[4], sb1[5], pos) == (3, 1, (24, 39))
    assert tool.precondition(sb1) == []


def test_precondition_falsifiers():
    sb1 = bytearray(codec.parse_flash(
        (ROOT / "tests/fixtures/gen3/firered_party_town.sav").read_bytes())["sb1"])
    scene2 = bytearray(sb1)
    scene2[0x1000 + 0x51 * 2] = 2
    assert "var 0x4051 is 2" in tool.precondition(bytes(scene2))[0]
    has_tv = bytearray(sb1)
    has_tv[KEY_OFF:KEY_OFF + 2] = (366).to_bytes(2, "little")
    assert tool.precondition(bytes(has_tv)) == ["TEACHY TV is already in the key pocket"]


# ── witnesses over fake RAM ──────────────────────────────────────────────────────────────────

def set_scene(ram, var, tv_slot=None):
    ram.put(SB1 + 0x1000 + 0x51 * 2, var, 2)
    if tv_slot is not None:
        ram.put(SB1 + KEY_OFF + 4 * tv_slot, 366, 2)


def test_scene_two_without_the_tv_fails(env):
    lua, m, ram = env
    set_scene(ram, 2)
    ok, why = m.after_scene(SB1, pocket(lua))
    assert not ok and "no TEACHY TV" in why
    set_scene(ram, 1, 0)
    assert not m.after_scene(SB1, pocket(lua))[0]
    ok, _ = m.before_scene(SB1, pocket(lua))
    assert not ok                                   # TV already there: not a fresh tutorial


def test_scene_two_with_the_tv_passes(env):
    lua, m, ram = env
    set_scene(ram, 1)
    assert m.before_scene(SB1, pocket(lua)) is True
    set_scene(ram, 2, 3)
    assert tuple(m.after_scene(SB1, pocket(lua))) == (True, 3)


def witness(env, title, kind, flags, ctrl, in_battle=True):
    _, m, ram = env
    ram.put(m.BATTLE_TYPE_FLAGS_ADDR, flags, 4)
    ram.put(m.BATTLER_CTRL_ADDR, ctrl, 4)
    return m.battle_witness(kind, m.TITLES[title], in_battle)


@pytest.mark.parametrize("title", sorted(TITLES))
def test_witnesses_accept_the_real_tutorials(env, title):
    stem = TITLES[title]
    assert witness(env, title, "oak_old_man", 0x200, sym("OakOldManBufferRunCommand", stem) | 1)[0]
    assert witness(env, title, "pokedude", 0x10000, sym("SetControllerToPokedude", stem) | 1)[0]


@pytest.mark.parametrize("title", sorted(TITLES))
def test_wrong_controller_or_type_fails(env, title):
    stem = TITLES[title]
    player = sym("HandleInputChooseAction", stem) | 1      # first in the .sym: the player's
    oak = sym("OakOldManBufferRunCommand", stem) | 1
    dude = sym("SetControllerToPokedude", stem) | 1
    cases = [
        ("oak_old_man", 0x200, player, "controller outside"),   # normal player controller
        ("oak_old_man", 0x004, oak, "wrong type flags"),         # wild flags, stale oak ctrl
        ("oak_old_man", 0x10000, oak, "wrong type flags"),
        ("pokedude", 0x10000, oak, "controller outside"),        # stale old-man controller
        ("pokedude", 0x200, dude, "wrong type flags"),
        ("pokedude", 0x10200, dude, "wrong type flags"),
        ("pokedude", 0x008, player, "wrong type flags"),         # a trainer battle
    ]
    for kind, flags, ctrl, reason in cases:
        ok, why = witness(env, title, kind, flags, ctrl)
        assert not ok and reason in why, (kind, flags, hex(ctrl), why)
    ok, why = witness(env, title, "pokedude", 0x10000, dude, in_battle=False)
    assert not ok and "not in battle" in why


def list_snapshot(env, title, cb2_name, fade_active, task=True):
    _, m, ram = env
    stem = TITLES[title]
    ram.put(m.GMAIN_CALLBACK2_ADDR, sym(cb2_name, stem) | 1, 4)
    ram.put(m.PALETTE_FADE_BYTE_ADDR, 0x80 if fade_active else 0, 1)
    ram.put(m.TASKS_ADDR + 3 * 40, sym("TeachyTvOptionListController", stem) | 1, 4)
    ram.put(m.TASKS_ADDR + 3 * 40 + 4, 1 if task else 0, 1)
    return m.ttv_list_ready(m.TITLES[title])


@pytest.mark.parametrize("title", sorted(TITLES))
def test_ttv_list_not_ready_mid_setup(env, title):
    # LIVE FR+LG on c08328b4: "TTVSCR_BATTLE was not chosen". A snapshot inside
    # TeachyTvMainCallback case 1 has the list task but no fade yet; the A fell into the fade-in.
    assert not list_snapshot(env, title, "TeachyTvMainCallback", fade_active=False)
    assert not list_snapshot(env, title, "TeachyTvCallback", fade_active=True)
    assert not list_snapshot(env, title, "TeachyTvCallback", fade_active=False, task=False)
    assert list_snapshot(env, title, "TeachyTvCallback", fade_active=False)


def test_ttv_setup_installs_the_steady_callback_after_the_fade():
    if not PRET.exists():
        pytest.skip("pret checkout not present")
    ttv = (PRET / "src/teachy_tv.c").read_text()
    body = ttv[ttv.index("static void TeachyTvMainCallback(void)\n{"):]
    body = body[:body.index("\n}\n")]
    task = body.index("CreateTask(TeachyTvOptionListController, 0)")
    fade = body.index("BeginNormalPaletteFade(")
    steady = body.index("SetMainCallback2(TeachyTvCallback)")
    assert task < fade < steady       # list task exists before the fade even starts
    listc = ttv[ttv.index("static void TeachyTvOptionListController(u8 taskId)\n{"):]
    assert listc.index("if (!gPaletteFade.active)") < listc.index("ListMenu_ProcessInput")


def test_fake_memory_refuses_writes(env):
    lua, _, _ = env
    with pytest.raises(lupa.LuaError, match="not allowed"):
        lua.execute("memory.write_u8(0x02000000, 1)")


# ── static input/write policy ────────────────────────────────────────────────────────────────

def test_builder_never_writes_ram_or_loads_state():
    code = "\n".join(ln.split("--")[0] for ln in SOURCE.splitlines())   # comments stripped
    for bad in ("memory.write", "mainmemory", "writebyte", "savestate.load", "client.saveram"):
        assert bad not in code, bad
    assert code.count("pcall(savestate.save") == 1


def test_builder_never_presses_b():
    code = "\n".join(ln.split("--")[0] for ln in SOURCE.splitlines())
    assert not re.search(r"""["']B["']|\bB\s*=\s*true""", code)
    # the only helper it borrows that CAN press B is playlib's menu_back; it is never reached
    assert "leave_menu" not in code and "menu_back" not in code and "G.mash" not in code


def test_result_file_is_the_builders_own():
    import run_gate
    assert run_gate._result_path_for("lua/tests/mkstates_gen3_tutorials.lua").endswith(
        "mkstates_gen3_tutorials_result.txt")
