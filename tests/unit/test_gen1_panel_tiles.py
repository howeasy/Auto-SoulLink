"""The panel's tile whitelist is a contract with the ROM, and with the row generator.

Lua paints wTileMap directly rather than calling PlaceString, so nothing in the game
validates what lands there: a wrong tile id is simply a wrong glyph on screen, and $00
would be read by any code that later walks the map as a terminator. The formatter is the
only check there is, and it had no test at all.

It also has to agree with whatever builds the rows. It did not: `-` is a perfectly legal
Gen 1 tile ($E3, pokered/constants/charmap.asm:163) and server.py emits dead-zone rows as
`"-" + area_name`, but the whitelist had no case for it, so every dead-zone line lost its
dash and rendered as an indented name.

Character ids are re-derived from the decomp here rather than copied from the Lua.
"""

from __future__ import annotations

import os
import re

import pytest

lupa = pytest.importorskip("lupa")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
TILEMAP, COLS, ROWS = 0xC3A0, 20, 18


@pytest.fixture
def mem():
    """The real memory_gb, on a fake bus, with the Gen 1 red profile."""
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
    lua.execute("package.path='" + p("lua", "?.lua") + ";'..package.path")
    lua.execute(
        "bus[0xDEE2]=0x53;bus[0xDEE3]=0x4C;bus[0xDEE4]=0x4E;bus[0xDEE5]=0x4B;bus[0xDEE6]=3;bus[0xDEE7]=2;bus[0xDEF1]=1;for a=0xDEF8,0xDEFF do bus[a]=0xA5 end"
    )
    return lua, M


def row_tiles(lua, row):
    return [lua.eval(f"bus[{TILEMAP + row * COLS + c}] or 0") for c in range(COLS)]


@pytest.fixture(scope="module")
def charmap():
    """`character -> tile id`, straight out of the decomp."""
    d = _REPO
    for _ in range(6):
        cand = os.path.join(d, ".cache", "pret", "pokered")
        if os.path.isdir(cand):
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    path = os.path.join(cand, "constants", "charmap.asm")
    if not os.path.exists(path):
        pytest.skip("pokered not cloned — run tools/build_pret_syms.py")
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\s*charmap\s+"(.*?)",\s*\$([0-9a-fA-F]+)', line)
            if m and len(m.group(1)) == 1:
                out[m.group(1)] = int(m.group(2), 16)
    return out


def test_the_charmap_fixture_is_real(charmap):
    """Control: every comparison below is vacuous if this parsed nothing."""
    assert charmap.get("A") == 0x80
    assert charmap.get(" ") == 0x7F
    assert charmap.get("0") == 0xF6


def test_every_supported_character_matches_the_decomp(mem, charmap):
    lua, M = mem
    supported = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/- "
    # In COLS-wide chunks: writing only supported[:COLS] would have checked the first
    # twenty letters and none of the digits, the slash, the dash or the space.
    for start in range(0, len(supported), COLS):
        chunk = supported[start : start + COLS]
        M.panelWriteRow(0, chunk)
        tiles = row_tiles(lua, 0)
        for col, ch in enumerate(chunk):
            assert tiles[col] == charmap[ch], (
                f"{ch!r} rendered as {tiles[col]:#04x}, cartridge says {charmap[ch]:#04x}"
            )


def test_the_dash_is_not_a_space(mem, charmap):
    """The specific disagreement with the row generator: server.py builds dead-zone
    rows as "-" + name, so a missing dash silently reindented every one of them."""
    lua, M = mem
    M.panelWriteRow(0, "-VIRIDIAN FOREST")
    assert row_tiles(lua, 0)[0] == charmap["-"] == 0xE3


def test_an_unknown_character_becomes_a_space_never_a_guess(mem):
    """A wrong tile is a glyph the player has to interpret. A space is honest."""
    lua, M = mem
    M.panelWriteRow(0, "A@B~C")
    tiles = row_tiles(lua, 0)
    assert tiles[1] == 0x7F and tiles[3] == 0x7F


def test_no_tile_is_ever_zero(mem):
    """$00 is NullChar. Nothing here calls PlaceString, but anything that later walks
    the map would read it as a terminator."""
    lua, M = mem
    M.panelWriteRow(0, "".join(chr(c) for c in range(32, 127))[:COLS])
    assert 0 not in row_tiles(lua, 0)


def test_a_row_is_padded_to_the_full_width(mem):
    """Otherwise a shorter row leaves the previous page's tiles behind it."""
    lua, M = mem
    M.panelWriteRow(0, "X" * COLS)
    M.panelWriteRow(0, "AB")
    assert row_tiles(lua, 0)[2:] == [0x7F] * (COLS - 2)


def test_an_over_long_row_is_truncated_not_wrapped(mem):
    """Wrapping would push every following row down and corrupt the page."""
    lua, M = mem
    M.panelWriteRow(1, "A" * (COLS + 10))
    assert row_tiles(lua, 1) == [0x80] * COLS
    assert row_tiles(lua, 2) == [0] * COLS, "the overflow was written into the next row"


def test_rows_past_the_bottom_are_dropped(mem):
    """panelStage writes whatever the patch is about to reveal; spilling past row 17
    would run into whatever follows wTileMap."""
    lua, M = mem
    rows = lua.table_from([f"R{i}" for i in range(ROWS + 5)])
    M.panelStage(rows)
    last = lua.eval(f"bus[{TILEMAP + ROWS * COLS}] or 0")
    assert last == 0, "panelStage wrote past the bottom row of the screen"
