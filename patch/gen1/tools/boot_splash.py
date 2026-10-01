"""The Gen 1 boot splash: a white screen with the SLink mark replaces the copyright screen.

The art is generated (tools/gen_gen1_splash.py -> splash_art.py) in the game's own four shades.
Only the version row depends on the version, and it is filled in here from glyph tiles that
are part of the art, so nothing at run time needs Pillow or a toolchain.

PlayShootingStar opens with `farcall LoadCopyrightAndTextBoxTiles`. That one call site is
redirected to a 30-byte routine in bank $3F that clears the screen, loads the splash tiles
and copies the splash tile map. The vanilla routine is left in place: the credits still call
its LoadCopyrightTiles half for the ending's copyright text, and the title screen, which
shares the same copyright graphics for its bottom line, is not touched.

Toolchain-free, like manifest.py: build.py and inject.py both call splash_spans().
"""
from __future__ import annotations

import re

try:  # imported as patch.gen1.tools.boot_splash (tests, server) or as a bare module (build.py, inject.py)
    from .splash_art import BLANK_ID, GLYPH_IDS, MAP, TILE_COUNT, TILES, VERSION_COLS, VERSION_ROW
except ImportError:
    from splash_art import BLANK_ID, GLYPH_IDS, MAP, TILE_COUNT, TILES, VERSION_COLS, VERSION_ROW

BANK = 0x3F
CODE_OFFSET, MAP_OFFSET, TILES_OFFSET = 0xFE000, 0xFE100, 0xFE300   # bank $3F $6000 / $6100 / $6300
CODE_ADDR, MAP_ADDR, TILES_ADDR = (0x4000 + (o & 0x3FFF) for o in (CODE_OFFSET, MAP_OFFSET, TILES_OFFSET))
FREE_FROM = CODE_OFFSET                      # the payload must end below this
assert len(MAP) == 360 and CODE_OFFSET + 0x100 <= MAP_OFFSET and MAP_OFFSET + 360 <= TILES_OFFSET
assert TILES_OFFSET + len(TILES) <= 0x100000

# bank $10, PlayShootingStar: `ld b, 1 / ld hl, LoadCopyrightAndTextBoxTiles` of the farcall
SITE, SITE_BEFORE = 0x4188F, bytes.fromhex("0601213845")
SITE_AFTER = bytes((0x06, BANK, 0x21, CODE_ADDR & 0xFF, CODE_ADDR >> 8))

# Home-bank routines the splash calls (pret pokered.sym; identical in Red and Blue)
CLEAR_SCREEN, COPY_VIDEO_DATA, COPY_DATA, WTILEMAP, HWY = 0x190F, 0x1848, 0x00B5, 0xC3A0, 0xB0


def _w(v: int) -> bytes:
    return bytes((v & 0xFF, v >> 8))


def _code() -> bytes:
    return (bytes((0xAF, 0xE0, HWY))                                          # xor a / ldh [hWY], a
            + b"\xcd" + _w(CLEAR_SCREEN)                                       # call ClearScreen
            + b"\x11" + _w(TILES_ADDR) + b"\x21" + _w(0x8800)                  # ld de, tiles / ld hl, vChars1
            + bytes((0x01, TILE_COUNT, BANK)) + b"\xcd" + _w(COPY_VIDEO_DATA)  # ld bc, bank:count / call CopyVideoData
            + b"\x21" + _w(MAP_ADDR) + b"\x11" + _w(WTILEMAP)                  # ld hl, map / ld de, wTileMap
            + b"\x01" + _w(360) + b"\xc3" + _w(COPY_DATA))                     # ld bc, 360 / jp CopyData


DEFAULT_VERSION = "dev"
_VERSION_RE = re.compile(r"dev|v\d+\.\d+\.\d+(-dev)?")


def check_version(version: str) -> str:
    cells = VERSION_COLS[1] - VERSION_COLS[0]
    if not _VERSION_RE.fullmatch(version) or len(version) > cells:
        raise ValueError(f"splash version must be 'dev' or vX.Y.Z[-dev] and fit {cells} tiles, got {version!r}")
    return version


def tilemap(version: str) -> bytes:
    """The art's tile map with the version centred on its row."""
    check_version(version)
    first, end = VERSION_COLS
    cells = [BLANK_ID] * (end - first)
    lead = (len(cells) - len(version)) // 2
    cells[lead:lead + len(version)] = [GLYPH_IDS[c] for c in version]
    out = bytearray(MAP)
    out[VERSION_ROW * 20 + first:VERSION_ROW * 20 + end] = bytes(cells)
    return bytes(out)


def splash_spans(version: str = DEFAULT_VERSION) -> list[tuple[int, bytes, bytes, str]]:
    """(offset, expected original, replacement, why) -- the same shape as manifest.MENU_PATCHES."""
    code = _code()
    return [
        (CODE_OFFSET, bytes(len(code)), code, "splash routine, end of bank $3F"),
        (MAP_OFFSET, bytes(360), tilemap(version), "splash tile map with the version row"),
        (TILES_OFFSET, bytes(len(TILES)), TILES, "splash tiles"),
        (SITE, SITE_BEFORE, SITE_AFTER, "PlayShootingStar's copyright screen -> the splash routine"),
    ]
