"""The Gen 1 title screen gains a SoulLink logo; the patch version goes on the main menu.

Vanilla keeps "Red Version" in a 16 pixel band under the Pokemon logo and scrolls it in from the
right. The band keeps that line, moved right, and gains a SoulLink logo in the Pokemon logo's own
style on the left (tools/gen_gen1_title.py -> title_art.py). The title carries no version: it stays
as close to vanilla as it can, and the version is printed under the New Game / Continue menu instead.

PrintGameVersionOnTitleScreen (9 bytes) is redirected to a routine in bank $3F that loads the logo
into 18 BG tile ids, all ids the title leaves free (measured on a running Red and Blue:
tests/fixtures/gen1/title_vram_*.json), then places the strings. It runs twice per boot, like the
original, and draws the same thing.

The main menu (bank 1, MainMenu.next2, reached by the New Game and the Continue layouts alike) calls
UpdateSprites once per redraw; that call is redirected to a stub in the free ROM0 tail which makes it
and then PlaceStrings "SoulLink <version>" on the screen's last tile row. That row is the only one
neither menu box nor the Continue info box (rows 7-16) ever covers, ClearScreen wipes it on every
re-entry and the same hook draws it again, and the game's font is resident by then, so the string is
plain tile ids.

The title's mon swap raster-scrolls everything below scanline $48 (tile row 9), which is where the
band's second row lives, so the scroll's start line is moved to $50 (tile row 10, where the mon
starts). Without that the bottom half of the logo shears on every swap.

The title screen's graphics and the credits are untouched. Toolchain-free, like manifest.py:
build.py and inject.py both call title_spans().
"""
from __future__ import annotations

import re

try:  # imported as patch.gen1.tools.title_screen (tests, server) or as a bare module (build.py, inject.py)
    from .title_art import FIRST_ID, ROW0, ROW1, TILE_COUNT, TILES
except ImportError:
    from title_art import FIRST_ID, ROW0, ROW1, TILE_COUNT, TILES

BANK = 0x3F
CODE_OFFSET, RV_OFFSET, ROW0_OFFSET, ROW1_OFFSET, TILES_OFFSET = (
    0xFE000, 0xFE080, 0xFE090, 0xFE0A0, 0xFE100)                         # bank $3F $6000 ...
FREE_FROM = CODE_OFFSET                                                  # the payload must end below this
BANK_END = 0x100000                                                      # the ROM ends with bank $3F
END = 0x50

# bank 1: PrintGameVersionOnTitleScreen = `hlcoord 7, 8 / ld de, VersionOnTitleScreenText / jp PlaceString`
SITE, SITE_BEFORE = 0x4598, bytes.fromhex("2147c411a145c35519")
VERSION_TEXT_SITE = 0x45A1               # "Red Version" / "Blue Version" as tile ids, the one thing Red and Blue differ in
VERSION_TEXT_LEN = 9
# bank $0D, _TitleScroll: `ld h, d / ld l, $48 / call .ScrollBetween`; the immediate is the first scanline scrolled
SCROLL_SITE, SCROLL_BEFORE, SCROLL_AFTER = 0x3727B, bytes((0x48,)), bytes((0x50,))

# home-bank routines and RAM (pret pokered.sym; identical in Red and Blue)
COPY_VIDEO_DATA, PLACE_STRING, BANKSWITCH, WTILEMAP, UPDATE_SPRITES = 0x1848, 0x1955, 0x35D6, 0xC3A0, 0x2429

# the 9x2-tile logo at x=1 on rows 8-9, the game's own line at x=11 on row 8
LOGO_X, LINE_X = 1, 11
assert FIRST_ID + TILE_COUNT <= 0x7F                                     # the free id run on the title

# bank 1, MainMenu.next2 (both the save-file and the no-save-file layout fall into it):
#   ld hl, wStatusFlags5 / res BIT_NO_TEXT_DELAY, [hl] / call UpdateSprites / xor a
MENU_CONTEXT_SITE, MENU_CONTEXT = 0x5B5F, bytes.fromhex("2130d7cbb6cd2924")
MENU_SITE = MENU_CONTEXT_SITE + 5                                        # the call's 3 bytes
MENU_SITE_BEFORE = MENU_CONTEXT[5:]
# ROM0's free tail, straight after SlinkJoypadStub (manifest.JOYPAD_STUB_ADDR + 23): the stub, then its string
MENU_STUB_ADDR, MENU_STUB_LEN = 0x3FD5, 13
MENU_TEXT_ADDR = MENU_STUB_ADDR + MENU_STUB_LEN
MENU_ROW = 17                            # the only tile row no menu box and not the Continue info box (rows 7-16) covers
MENU_PREFIX = "SoulLink "

DEFAULT_VERSION = "dev"
VERSION_MAX = 10                         # "v0.3.0-dev"; keeps the menu line inside the screen's 20 cells
_VERSION_RE = re.compile(r"dev|v\d+\.\d+\.\d+(-dev)?")
assert len(MENU_PREFIX) + VERSION_MAX <= 20


def check_version(version: str) -> str:
    if not _VERSION_RE.fullmatch(version) or len(version) > VERSION_MAX:
        raise ValueError(f"version must be 'dev' or vX.Y.Z[-dev] and at most {VERSION_MAX} characters, got {version!r}")
    return version


def menu_text(version: str) -> bytes:
    """"SoulLink <version>" as the game's tile ids, $50-terminated: the font is resident on the main menu, so no tiles are copied.

    Gen 1's charset puts 'A' at $80, 'a' at $A0, '0' at $F6, space at $7F, '-' at $E3 and '.' at $E8
    (constants/charmap.asm; manifest.SLINK_TEXT is the same mapping)."""
    out = bytearray()
    for c in MENU_PREFIX + check_version(version):
        if c == " ":
            out.append(0x7F)
        elif "A" <= c <= "Z":
            out.append(0x80 + ord(c) - ord("A"))
        elif "a" <= c <= "z":
            out.append(0xA0 + ord(c) - ord("a"))
        elif "0" <= c <= "9":
            out.append(0xF6 + ord(c) - ord("0"))
        else:
            out.append({"-": 0xE3, ".": 0xE8}[c])
    return bytes(out) + bytes((END,))


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

    return (copy(TILES_OFFSET, 0x9000 + FIRST_ID * 16, TILE_COUNT)
            + place(8, LINE_X, RV_OFFSET) + place(8, LOGO_X, ROW0_OFFSET) + place(9, LOGO_X, ROW1_OFFSET)
            + bytes((0xC9,)))                                                # ret


def _menu_stub() -> bytes:
    """What the redirected `call UpdateSprites` runs: the call itself, then the version on the last tile row."""
    stub = (bytes((0xCD,)) + _w(UPDATE_SPRITES)                              # call UpdateSprites -- what vanilla did
            + bytes((0x21,)) + _w(WTILEMAP + MENU_ROW * 20)                  # ld hl, wTileMap + row * 20
            + bytes((0x11,)) + _w(MENU_TEXT_ADDR)                            # ld de, text
            + bytes((0xCD,)) + _w(PLACE_STRING) + bytes((0xC9,)))            # call PlaceString / ret
    assert len(stub) == MENU_STUB_LEN
    return stub


def title_spans(rom: bytes, version: str = DEFAULT_VERSION) -> list[tuple[int, bytes, bytes, str]]:
    """(offset, expected original, replacement, why) -- the same shape as manifest.MENU_PATCHES.

    Raises ValueError for a bad version or a ROM whose title line or main menu is not the one these offsets were read from."""
    text = menu_text(version)
    code = _code()
    line = rom[VERSION_TEXT_SITE:VERSION_TEXT_SITE + VERSION_TEXT_LEN]
    # PlaceString treats every byte below $60 as a command, so the copied line must be plain tile ids plus its terminator
    if len(line) != VERSION_TEXT_LEN or line[-1] != END or any(b < 0x60 for b in line[:-1]):
        raise ValueError(f"the title's version line at {VERSION_TEXT_SITE:#x} is not the game's own tile ids: {line.hex()}")
    found = rom[MENU_CONTEXT_SITE:MENU_CONTEXT_SITE + len(MENU_CONTEXT)]
    if found != MENU_CONTEXT:
        raise ValueError(f"the main menu at {MENU_CONTEXT_SITE:#x} holds {found.hex()}, expected {MENU_CONTEXT.hex()}")
    if len(code) > RV_OFFSET - CODE_OFFSET or TILES_OFFSET + len(TILES) > BANK_END:
        raise ValueError("the title band does not fit its bank $3F layout")
    if MENU_TEXT_ADDR + len(text) > 0x4000:
        raise ValueError("the main menu string does not fit ROM0's free tail")
    hook = bytes((0x06, BANK, 0x21)) + _w(_addr(CODE_OFFSET)) + bytes((0xC3,)) + _w(BANKSWITCH) + bytes((0x00,))
    return [
        (CODE_OFFSET, bytes(len(code)), code, "title band routine, end of bank $3F"),
        (RV_OFFSET, bytes(len(line)), line, "the game's own 'Red Version' / 'Blue Version' tile ids"),
        (ROW0_OFFSET, bytes(len(ROW0) + 1), ROW0 + bytes((END,)), "SoulLink logo, band row 8"),
        (ROW1_OFFSET, bytes(len(ROW1) + 1), ROW1 + bytes((END,)), "SoulLink logo, band row 9"),
        (TILES_OFFSET, bytes(len(TILES)), TILES, "SoulLink logo tiles"),
        (SITE, SITE_BEFORE, hook, "PrintGameVersionOnTitleScreen -> the band routine"),
        (SCROLL_SITE, SCROLL_BEFORE, SCROLL_AFTER, "title mon swap scrolls from tile row 10, so band row 9 stays put"),
        (MENU_STUB_ADDR, bytes(MENU_STUB_LEN), _menu_stub(), "main menu stub: UpdateSprites, then the SoulLink version line"),
        (MENU_TEXT_ADDR, bytes(len(text)), text, "the main menu version string"),
        (MENU_SITE, MENU_SITE_BEFORE, bytes((0xCD,)) + _w(MENU_STUB_ADDR), "MainMenu.next2's call UpdateSprites -> the stub"),
    ]
