"""Legacy observation flags and AP behavior, independent of RBY write permission.

Live cartridge evidence shows these flags alone can be clear during title and
nickname screens. RBY deferred writes use isPartyWriteSafe; its source/CPU tests
are in test_gen1_write_checkpoint.py and the separate live checkpoint gates.
"""
import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MEMORY_GB = os.path.join(REPO, "lua", "memory_gb.lua")
GEN1 = os.path.join(REPO, "lua", "games", "gen1_rby.lua")

# pret/pokered
IN_BATTLE, JOY_IGNORE, FONT_LOADED, CUR_BOX = 0xD057, 0xCD6B, 0xCFC4, 0xD5A0


@pytest.fixture
def mem():
    lupa = pytest.importorskip("lupa")
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute("""
    _G.RAM = {}
    _G.memory = {
      getmemorydomainlist = function() return {"System Bus","CartRAM","ROM"} end,
      read_u8 = function(a) return RAM[a] or 0 end,
      write_u8 = function(a,v) RAM[a] = v end,
      read_u16_le = function(a) return (RAM[a] or 0) + 256*(RAM[a+1] or 0) end,
      write_u16_le = function(a,v) RAM[a]=v%256; RAM[a+1]=math.floor(v/256) end,
    }
    _G.console = { log = function() end }
    _G.print = function() end
    """)
    load = L.eval("function(s) return load(s)() end")
    with open(MEMORY_GB, encoding="utf-8") as f:
        M = load(f.read())
    with open(GEN1, encoding="utf-8") as f:
        G = load(f.read())
    M.initProfile(G, "red")
    return L, M


def _set(L, values):
    """values: {address: byte}. A plain dict, not kwargs — the keys are ints."""
    for addr, val in values.items():
        L.globals().RAM[addr] = val


def test_plain_overworld_is_safe(mem):
    L, M = mem
    _set(L, {IN_BATTLE: 0, JOY_IGNORE: 0, FONT_LOADED: 0})
    assert M.isInOverworld() is True


def test_battle_is_not_safe(mem):
    L, M = mem
    _set(L, {IN_BATTLE: 1, JOY_IGNORE: 0, FONT_LOADED: 0})
    assert M.isInOverworld() is False


def test_script_holding_the_joypad_is_not_safe(mem):
    """Cutscene / forced movement — writing here fights the script."""
    L, M = mem
    _set(L, {IN_BATTLE: 0, JOY_IGNORE: 0xFF, FONT_LOADED: 0})
    assert M.isInOverworld() is False


def test_open_text_box_or_menu_is_not_safe(mem):
    """The PC box UI and party menu both keep the font loaded; this is the window that
    actually corrupts box data, because the UI writes its own copy back."""
    L, M = mem
    _set(L, {IN_BATTLE: 0, JOY_IGNORE: 0, FONT_LOADED: 1})
    assert M.isInOverworld() is False


def test_font_loaded_checks_bit_zero_not_the_whole_byte(mem):
    """wFontLoaded's other bits are unrelated; only bit 0 means 'font is up'."""
    L, M = mem
    _set(L, {IN_BATTLE: 0, JOY_IGNORE: 0, FONT_LOADED: 0x02})
    assert M.isInOverworld() is True


def test_battle_lost_sentinel_is_not_treated_as_in_battle(mem):
    """wIsInBattle can be 0xFF (IN_BATTLE_LOST) during post-battle cleanup; only 1 and 2
    are real battles, and the overworld gate must agree with isInBattle about that."""
    L, M = mem
    _set(L, {IN_BATTLE: 0xFF, JOY_IGNORE: 0, FONT_LOADED: 0})
    assert M.isInBattle() is False
    assert M.isInOverworld() is True


def test_current_box_number_masks_the_changed_flag(mem):
    """The high bit of wCurrentBoxNum is a 'box changed' flag, not part of the index."""
    L, M = mem
    _set(L, {CUR_BOX: 0x8B})       # bit 7 set + box 11
    assert M.getCurrentBoxNum() == 11
    _set(L, {CUR_BOX: 0x00})
    assert M.getCurrentBoxNum() == 0
