"""The Gen 1 title screen: a SoulLink logo and the patch version join the "Red Version" line.

Vanilla keeps "Red Version" in a 16 pixel band under the Pokemon logo and scrolls it in from the
right. The band keeps that line, moved right, and gains a SoulLink logo in the Pokemon logo's own
style on the left (tools/gen_gen1_title.py -> title_art.py) and the version under the line, drawn
here in a small pixel font so nothing at patch time needs Pillow or a toolchain.

PrintGameVersionOnTitleScreen (9 bytes) is redirected to a routine in bank $3F that loads the logo
into 18 BG tile ids and the version line into 8 more, all ids the title leaves free (measured on a
running Red: $6A-$7E and $4F-$5F), then places the strings and the version cells. It runs twice per boot, like the
original, and draws the same thing.

The title screen's graphics and the credits are untouched. Toolchain-free, like manifest.py:
build.py and inject.py both call title_spans().
"""
from __future__ import annotations

import re

try:  # imported as patch.gen1.tools.title_screen (tests, server) or as a bare module (build.py, inject.py)
    from .title_art import FIRST_ID, ROW0, ROW1, SMALL, TILE_COUNT, TILES
except ImportError:
    from title_art import FIRST_ID, ROW0, ROW1, SMALL, TILE_COUNT, TILES

BANK = 0x3F
CODE_OFFSET, RV_OFFSET, ROW0_OFFSET, ROW1_OFFSET, TILES_OFFSET, VTILES_OFFSET = (
    0xFE000, 0xFE080, 0xFE090, 0xFE0A0, 0xFE100, 0xFE300)       # bank $3F $6000 ...
FREE_FROM = CODE_OFFSET                                                  # the payload must end below this
END = 0x50

# bank 1: PrintGameVersionOnTitleScreen = `hlcoord 7, 8 / ld de, VersionOnTitleScreenText / jp PlaceString`
SITE, SITE_BEFORE = 0x4598, bytes.fromhex("2147c411a145c35519")
VERSION_TEXT_SITE = 0x45A1               # "Red Version" / "Blue Version" as tile ids, the one thing Red and Blue differ in
VERSION_TEXT_LEN = 9

# home-bank routines and RAM (pret pokered.sym; identical in Red and Blue)
COPY_VIDEO_DATA, PLACE_STRING, BANKSWITCH, WTILEMAP = 0x1848, 0x1955, 0x35D6, 0xC3A0

# the 9x2-tile logo at x=1 on rows 8-9, the 8-tile line at x=11 on row 8, the version under it on row 9
LOGO_X, LINE_X, VER_X, VER_CELLS = 1, 11, 11, 8
VER_FIRST_ID = 0x4F
assert FIRST_ID + TILE_COUNT <= 0x7F and VER_FIRST_ID + VER_CELLS <= 0x60   # the free id runs on the title

DEFAULT_VERSION = "dev"
_VERSION_RE = re.compile(r"dev|v\d+\.\d+\.\d+(-dev)?")


def check_version(version: str) -> str:
    if not _VERSION_RE.fullmatch(version) or len(version) * 6 - 1 > VER_CELLS * 8:
        raise ValueError(f"title version must be 'dev' or vX.Y.Z[-dev] and fit {VER_CELLS * 8} pixels, got {version!r}")
    return version


def _version_tiles(version: str) -> bytes:
    """The version line as 2bpp tiles: 5x7 glyphs, centred, one pixel below the top of the band row."""
    width = VER_CELLS * 8
    rows = [0] * 8
    x = (width - (len(version) * 6 - 1)) // 2
    for c in version:
        for y, bits in enumerate(SMALL[c]):
            rows[y + 1] |= bits << (width - 5 - x)
        x += 6
    out = bytearray()
    for t in range(VER_CELLS):
        for y in range(8):
            b = (rows[y] >> (width - 8 - 8 * t)) & 0xFF
            out += bytes((b, b))                                         # both planes: set bit = colour 3
    return bytes(out)


def _w(v: int) -> bytes:
    return bytes((v & 0xFF, v >> 8))


def _addr(off: int) -> int:
    return 0x4000 + (off & 0x3FFF)


def _code() -> bytes:
    def copy(tiles_off, vram, n):          # ld de, src / ld hl, VRAM / ld bc, bank:n / call CopyVideoData
        return (bytes((0x11,)) + _w(_addr(tiles_off)) + bytes((0x21,)) + _w(vram)
                + bytes((0x01, n, BANK, 0xCD)) + _w(COPY_VIDEO_DATA))

    def place(row, x, text_off):           # ld hl, wTileMap+row*20+x / ld de, text / call PlaceString
        return (bytes((0x21,)) + _w(WTILEMAP + row * 20 + x) + bytes((0x11,)) + _w(_addr(text_off))
                + bytes((0xCD,)) + _w(PLACE_STRING))

    # the version cells are written straight into wTileMap: ids $4F-$56 are PlaceString control codes
    cells = (bytes((0x21,)) + _w(WTILEMAP + 9 * 20 + VER_X) + bytes((0x3E, VER_FIRST_ID, 0x06, VER_CELLS))
             + bytes((0x22, 0x3C, 0x05, 0x20, 0xFB, 0xC9)))                # ld hl / ld a / ld b / loop: ld [hli],a; inc a; dec b; jr nz / ret
    return (copy(TILES_OFFSET, 0x9000 + FIRST_ID * 16, TILE_COUNT)
            + copy(VTILES_OFFSET, 0x9000 + VER_FIRST_ID * 16, VER_CELLS)
            + place(8, LINE_X, RV_OFFSET) + place(8, LOGO_X, ROW0_OFFSET) + place(9, LOGO_X, ROW1_OFFSET) + cells)


def title_spans(rom: bytes, version: str = DEFAULT_VERSION) -> list[tuple[int, bytes, bytes, str]]:
    """(offset, expected original, replacement, why) -- the same shape as manifest.MENU_PATCHES."""
    code, vtiles = _code(), _version_tiles(check_version(version))
    line = rom[VERSION_TEXT_SITE:VERSION_TEXT_SITE + VERSION_TEXT_LEN]
    assert len(code) <= RV_OFFSET - CODE_OFFSET and line[-1] == END
    assert TILES_OFFSET + len(TILES) <= VTILES_OFFSET and VTILES_OFFSET + len(vtiles) <= 0x100000
    hook = bytes((0x06, BANK, 0x21)) + _w(_addr(CODE_OFFSET)) + bytes((0xC3,)) + _w(BANKSWITCH) + bytes((0x00,))
    return [
        (CODE_OFFSET, bytes(len(code)), code, "title band routine, end of bank $3F"),
        (RV_OFFSET, bytes(len(line)), line, "the game's own 'Red Version' / 'Blue Version' tile ids"),
        (ROW0_OFFSET, bytes(len(ROW0) + 1), ROW0 + bytes((END,)), "SoulLink logo, band row 8"),
        (ROW1_OFFSET, bytes(len(ROW1) + 1), ROW1 + bytes((END,)), "SoulLink logo, band row 9"),
        (TILES_OFFSET, bytes(len(TILES)), TILES, "SoulLink logo tiles"),
        (VTILES_OFFSET, bytes(len(vtiles)), vtiles, "version line tiles"),
        (SITE, SITE_BEFORE, hook, "PrintGameVersionOnTitleScreen -> the band routine"),
    ]
