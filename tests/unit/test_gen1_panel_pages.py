"""The native panel pages, and the two halves have to agree on how many pages there are.

The patch owns a page number at mailbox+10 and the client publishes a page COUNT at +11 --
only the client can know it, because only the client has seen how much text the server
sent. The patch reads the count to decide whether A turns a page or closes; without it, A
on a one-page panel would white out and repaint the same rows, which looks like a fault.

Before this the panel showed one screen and `panelStage` silently DROPPED anything past
row 18, while the server capped dead zones at eight to stay under that limit. Both the cap
and the silent drop existed only because there was nowhere to put the rest.
"""
from __future__ import annotations

import os

import pytest

lupa = pytest.importorskip("lupa")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
TILEMAP, COLS, ROWS = 0xC3A0, 20, 18
PANEL_PAGE, PANEL_PAGES, PANEL_STATE = 0xDEEC, 0xDEED, 0xDEEB


@pytest.fixture
def mem():
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("bus = {}; cart = {}; print = function() end")
    lua.execute("""
        local function pick(d) if d == "CartRAM" then return cart else return bus end end
        memory = {
            getmemorydomainlist = function() return {"System Bus", "CartRAM"} end,
            read_u8  = function(a, d) return pick(d)[a] or 0 end,
            write_u8 = function(a, v, d) pick(d)[a] = v % 256 end,
            read_u16_le = function(a, d) local t = pick(d)
                                         return (t[a] or 0) + (t[a+1] or 0) * 256 end,
            write_u16_le = function(a, v, d) local t = pick(d)
                                             t[a] = v % 256; t[a+1] = math.floor(v/256) % 256 end,
        }
    """)
    def p(*x):
        return os.path.join(_REPO, *x).replace("\\", "/")
    M = lua.eval(f'dofile("{p("lua", "memory_gb.lua")}")')
    G = lua.eval(f'dofile("{p("lua", "games", "gen1_rby.lua")}")')
    M.initProfile(G, "red")
    return lua, M


def _rows(lua, n, prefix="R"):
    return lua.table_from([f"{prefix}{i}" for i in range(n)])


def row_text(lua, row):
    out = []
    for c in range(COLS):
        b = lua.eval(f"bus[{TILEMAP + row * COLS + c}] or 0")
        out.append(chr(b - 0x80 + 65) if 0x80 <= b <= 0x99 else
                   (chr(b - 0xF6 + 48) if 0xF6 <= b <= 0xFF else " "))
    return "".join(out).rstrip()


# ── the page count ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n,expected", [(0, 1), (1, 1), (18, 1), (19, 2), (36, 2), (37, 3)])
def test_page_count(mem, n, expected):
    """Always at least one, so an empty panel still opens rather than paging to nothing."""
    lua, M = mem
    assert M.panelPageCount(_rows(lua, n)) == expected


def test_the_count_is_published_for_the_patch(mem):
    """The patch cannot compute this — it never sees the text."""
    lua, M = mem
    M.panelStage(_rows(lua, 40))
    assert lua.eval(f"bus[{PANEL_PAGES}]") == 3


# ── which rows land on screen ────────────────────────────────────────────────────────

def test_page_zero_paints_the_first_screen(mem):
    lua, M = mem
    M.panelStage(_rows(lua, 40))
    assert row_text(lua, 0) == "R0"
    assert row_text(lua, 17) == "R17"


def test_page_one_paints_the_second_screen(mem):
    """The rows that used to be silently dropped."""
    lua, M = mem
    lua.execute(f"bus[{PANEL_PAGE}] = 1")
    M.panelStage(_rows(lua, 40))
    assert row_text(lua, 0) == "R18"
    assert row_text(lua, 17) == "R35"


def test_a_short_last_page_is_padded_not_left_stale(mem):
    """Otherwise the tail of the previous page shows through under the last one."""
    lua, M = mem
    M.panelStage(_rows(lua, 40, prefix="OLD"))
    lua.execute(f"bus[{PANEL_PAGE}] = 2")
    M.panelStage(_rows(lua, 40))
    assert row_text(lua, 0) == "R36"
    assert row_text(lua, 5) == "", "a stale row from the previous page survived"


def test_a_page_past_the_end_clamps_instead_of_reading_off_the_list(mem):
    """Defensive: the patch should never ask, but a stale byte must not paint garbage."""
    lua, M = mem
    lua.execute(f"bus[{PANEL_PAGE}] = 40")
    M.panelStage(_rows(lua, 5))
    assert row_text(lua, 0) == "R0"


def test_staging_still_hands_the_screen_back(mem):
    """The control: pagination must not break the handshake the patch waits on."""
    lua, M = mem
    M.panelStage(_rows(lua, 5))
    assert lua.eval(f"bus[{PANEL_STATE}]") == 2      # STAGED
