"""The panel's tile whitelist is a contract with the ROM, and with the row generator.

Lua paints wTileMap directly rather than calling PlaceString, so nothing in the game
validates what lands there: a wrong tile id is simply a wrong glyph on screen, and $00
would be read by any code that later walks the map as a terminator. The formatter is the
only check there is.

It also has to agree with whatever builds the rows. It did not: `-` is a perfectly legal
Gen 1 tile ($E3, pokered/constants/charmap.asm:163) and server.py emits dead-zone rows as
`"-" + area_name`, but the whitelist had no case for it, so every dead-zone line lost its
dash and rendered as an indented name.

Character ids are re-derived from the decomp here rather than copied from the Lua.
P8-2b: repointed from memory_gb.lua's panelWriteRow to lua/gen1/panel.lua. The staging
handshake, the deadline and the write window live in test_gen1_panel.py; what is left here
is the charmap contract plus the two geometry rules that file does not pin.
"""
from __future__ import annotations

import json
import os
import re

import pytest

lupa = pytest.importorskip("lupa")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
COLS, ROWS = 20, 18
BLANK = 0x7F
PANEL_LUA = os.path.join(_REPO, "lua", "gen1", "panel.lua").replace("\\", "/")
with open(os.path.join(_REPO, "data", "games", "gen1_rby", "profile.json"),
          encoding="utf-8") as _f:
    PROFILE = json.load(_f)["titles"]


@pytest.fixture(scope="module")
def panel():
    """The real lua/gen1/panel.lua module table (P.tile_for is a module function)."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    return lua, lua.eval(f'dofile("{PANEL_LUA}")')


def _held_page(lua, P, rows, page=0):
    """Pre-render `rows` through the real P.new(...):hold() and return one page's tiles."""
    mem = bytearray(0x10000)
    io = lua.table(read_u8=lambda a: mem[int(a)], framecount=lambda: 0)
    writes = lua.table(arm=lambda *a: None, disarm=lambda *a: None,
                       write_bytes=lambda *a: None)
    self = P.new(lua.table_from(PROFILE["red"], recursive=True), io, writes, lambda s: s)
    assert self.hold(self, lua.table_from(list(rows))) is True
    return [self.tiles[page + 1][i] for i in range(1, COLS * ROWS + 1)]


def row_tiles(tiles, row):
    return tiles[row * COLS:(row + 1) * COLS]


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


def test_every_supported_character_matches_the_decomp(panel, charmap):
    _, P = panel
    supported = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/- "
    for ch in supported:
        got = P.tile_for(ch)
        assert got == charmap[ch], (
            f"{ch!r} rendered as {got:#04x}, cartridge says {charmap[ch]:#04x}")


def test_the_dash_is_not_a_space(panel, charmap):
    """The specific disagreement with the row generator: server.py builds dead-zone
    rows as "-" + name, so a missing dash silently reindented every one of them."""
    _, P = panel
    assert P.tile_for("-") == charmap["-"] == 0xE3


def test_an_unknown_character_becomes_a_space_never_a_guess(panel):
    """A wrong tile is a glyph the player has to interpret. A space is honest."""
    _, P = panel
    for ch in "@~\x01\x7f":
        assert P.tile_for(ch) == BLANK


def test_no_tile_is_ever_zero(panel):
    """$00 is NullChar. Nothing here calls PlaceString, but anything that later walks
    the map would read it as a terminator."""
    _, P = panel
    assert all(P.tile_for(chr(c)) != 0 for c in range(0, 256))


def test_a_row_is_padded_to_the_full_width(panel):
    """Otherwise a shorter row leaves the previous page's tiles behind it."""
    lua, P = panel
    tiles = _held_page(lua, P, ["AB"])
    assert row_tiles(tiles, 0)[2:] == [BLANK] * (COLS - 2)


def test_an_over_long_row_is_truncated_not_wrapped(panel):
    """Wrapping would push every following row down and corrupt the page."""
    lua, P = panel
    tiles = _held_page(lua, P, ["A" * (COLS + 10), "B"])
    assert row_tiles(tiles, 0) == [0x80] * COLS
    assert row_tiles(tiles, 1)[0] == 0x81, "the overflow was written into the next row"


def test_rows_past_the_bottom_start_a_new_page_rather_than_spilling(panel):
    """memory_gb's panelStage dropped anything past row 17; panel.lua pages instead, and
    a page still occupies exactly one screen."""
    lua, P = panel
    rows = [f"R{i}" for i in range(ROWS + 5)]
    first = _held_page(lua, P, rows, page=0)
    second = _held_page(lua, P, rows, page=1)
    assert len(first) == len(second) == COLS * ROWS
    assert row_tiles(second, 0)[:3] == [0x91, 0xF7, 0xFE]              # "R18"
    assert row_tiles(second, 5) == [BLANK] * COLS, "a short last page must be padded"
