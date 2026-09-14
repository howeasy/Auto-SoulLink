"""lua/gen1/entry.lua's cartridge detection, and the rom_type strings it hands the server.

The title is what selects the memory profile, the engine-signal table, the write checkpoint
and the settings the HUD shows, so a false negative here is not a cosmetic failure: the
client builds against the wrong addresses or refuses to build at all (entry.lua
`Entry.build` asserts on an unknown title). Two things must hold and are pinned here:

  * `Entry.detect_title` reads ROM $0134..$0143 the way the cartridge writes it -- a
    zero-padded 16-byte field, name first -- and matches the three titles SLink ships.
  * The strings it produces are the ones `Entry.ROM_TYPE` maps to, and those values are the
    ones the server routes on: `game_id_for_rom_type` (server/adapters/__init__.py:90-95,
    table at :45-46) registers exactly "Red"/"Blue"/"Yellow" for gen1_rby. A third opinion
    about capitalisation here would be a silent mis-route, not a crash.

The real dumps are read when they are present, because a synthetic header proves the
comparison works but not that the cartridges in patch/build carry those titles.
"""
from __future__ import annotations

import os

import pytest

from server.adapters import game_id_for_rom_type

lupa = pytest.importorskip("lupa", reason="lupa is needed to execute the Gen 1 entry module")

_REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_ENTRY_PATH = os.path.join(_REPO, "lua", "gen1", "entry.lua").replace("\\", "/")
_TITLE_OFFSET = 0x134
_TITLE_BYTES = 16
_ROM_FILES = {"red": "gen1_red.gb", "blue": "gen1_blue.gb", "yellow": "gen1_yellow.gbc"}


@pytest.fixture(scope="module")
def entry():
    """The real module, under lupa, with the tuple unpacking its nil-returning path needs."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    return lua.eval(f'dofile("{_ENTRY_PATH}")')


def _reader(image: bytes):
    """A `read_rom_u8(addr)` over an image addressed ABSOLUTELY, as BizHawk's ROM domain is."""
    def read_u8(addr: int) -> int:
        return image[addr] if 0 <= addr < len(image) else 0
    return read_u8


def _header_image(title: str) -> bytes:
    """A ROM image whose $0134 field holds `title`, zero-padded, like the real thing."""
    raw = title.encode("ascii")
    assert len(raw) <= _TITLE_BYTES, f"{title!r} does not fit the 16-byte title field"
    image = bytearray(_TITLE_OFFSET + _TITLE_BYTES)
    image[_TITLE_OFFSET:_TITLE_OFFSET + len(raw)] = raw
    return bytes(image)


def _dump(title: str) -> bytes:
    path = os.path.join(_REPO, "patch", "build", _ROM_FILES[title])
    if not os.path.exists(path):
        pytest.skip(f"{_ROM_FILES[title]} not present — no cartridge to read")
    with open(path, "rb") as f:
        return f.read()


@pytest.mark.parametrize("title,expected", [("POKEMON RED", "red"),
                                            ("POKEMON BLUE", "blue"),
                                            ("POKEMON YELLOW", "yellow")])
def test_the_three_titles_are_recognised(entry, title, expected):
    assert entry.detect_title(_reader(_header_image(title))) == expected


def test_an_unrelated_title_returns_nil_and_the_header_text(entry):
    """The second return value is the failure's evidence, so the caller can say WHICH ROM."""
    got = entry.detect_title(_reader(_header_image("POKEMON CRYSTA")))
    # Two Lua returns arrive as a tuple under unpack_returned_tuples; the nil is the first,
    # so the tuple is (None, name) rather than a trailing-nil list.
    assert isinstance(got, tuple) and len(got) == 2, f"expected (nil, name), got {got!r}"
    assert got[0] is None
    assert got[1] == "POKEMON CRYSTA", f"the header was not reported back: {got[1]!r}"


@pytest.mark.parametrize("title", sorted(_ROM_FILES))
def test_the_real_dumps_report_their_own_title(entry, title):
    """A synthetic header proves the comparison; this proves the dumps say what we ship."""
    rom = _dump(title)
    assert title.upper().encode() in rom[_TITLE_OFFSET:_TITLE_OFFSET + _TITLE_BYTES]
    assert entry.detect_title(_reader(rom)) == title


def test_rom_type_strings_are_the_ones_the_server_routes_on(entry):
    """The Lua table is not allowed to be a third opinion about capitalisation."""
    assert dict(entry.ROM_TYPE.items()) == {"red": "Red", "blue": "Blue", "yellow": "Yellow"}
    for value in ("Red", "Blue", "Yellow"):
        assert game_id_for_rom_type(value) == "gen1_rby", (
            f"{value!r} is not the rom_type the server registers for gen1_rby")
