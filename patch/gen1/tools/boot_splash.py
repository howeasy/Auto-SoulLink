"""The Gen 1 boot splash: the three copyright lines become SLink's own.

Nothing here is art. The glyphs are the ROM's own menu font, so the screen looks like
vanilla; only the words change. Red and Blue are byte-identical across every span.

WHY NOT JUST OVERWRITE THE COPYRIGHT TILES. DisplayTitleScreen copies the same
NintendoCopyrightLogoGraphics / GameFreakLogoGraphics tiles for the title screen's bottom
line, and the title screen stays vanilla. So the splash loads its own tiles from bank $3F
instead, by repointing two immediates in LoadCopyrightTiles, and rewrites only the tile-ID
string that is used by the splash.

The tiles are version independent; only CopyrightTextString depends on the version.

Toolchain-free, like manifest.py: build.py and inject.py both call splash_spans().
"""
from __future__ import annotations

import hashlib
import re

BANK = 0x3F
TILES_OFFSET = 0xFFC00                   # bank $3F, $7C00: after the 6.6 KB payload, still zeros
TILES_ADDR = 0x4000 + (TILES_OFFSET & 0x3FFF)
FIRST_TILE = 0x60                        # LoadCopyrightTiles copies to vChars2 tile $60; $7F stays the blank
SPACE = 0x7F

# bank 1, LoadCopyrightTiles: `ld de, NintendoCopyrightLogoGraphics` and `ld bc, bank<<8 | count`
LD_DE_SITE, LD_DE_BEFORE = 0x4541, bytes.fromhex("11c860")
LD_BC_SITE, LD_BC_BEFORE = 0x4547, bytes.fromhex("011c04")
# bank 1, CopyrightTextString: 3 lines of tile IDs, `next`-separated, "@"-terminated
TEXT_SITE = 0x4556
TEXT_BEFORE = bytes.fromhex(
    "606162616361647f65666768696a4e"
    "606162616361647f6b6c6d6e6f7071724e"
    "606162616361647f737475767778797a7b50")
NEXT, END = 0x4E, 0x50

# the ROM's own menu font: 1bpp, tile 0 = charcode $80 ('A')
FONT_OFFSET, FONT_LEN = 0x11A80, 0x400
FONT_SHA1 = "cf61e52e0c8375ecdcd260f8cb1726b9ec3d288a"

GLYPHS = "SLINKOUZCEvde0123456789.-"
LINES = ("SOUL LINK", "NUZLOCKE")
WIDTH = 16                               # the text starts at tile x=2: 16 wide stays centred
DEFAULT_VERSION = "dev"
_VERSION_RE = re.compile(r"dev|v\d+\.\d+\.\d+(-dev)?")


def _charcode(c: str) -> int:
    """The Gen 1 text charset for the glyphs the splash uses."""
    if "A" <= c <= "Z":
        return 0x80 + ord(c) - ord("A")
    if "a" <= c <= "z":
        return 0xA0 + ord(c) - ord("a")
    if "0" <= c <= "9":
        return 0xF6 + ord(c) - ord("0")
    return {".": 0xE8, "-": 0xE3}[c]


def check_version(version: str) -> str:
    first = f"SLINK {version}"
    if not _VERSION_RE.fullmatch(version) or len(first) > WIDTH:
        raise ValueError(f"splash version must be 'dev' or vX.Y.Z[-dev] and fit {WIDTH} tiles with "
                         f"'SLINK ', got {version!r}")
    return version


def tiles(rom: bytes) -> bytes:
    """2bpp tiles for GLYPHS, from the ROM's own font."""
    font = rom[FONT_OFFSET:FONT_OFFSET + FONT_LEN]
    if hashlib.sha1(font).hexdigest() != FONT_SHA1:
        raise ValueError("the ROM's menu font is not the one the splash was derived from")
    out = bytearray()
    for c in GLYPHS:
        row0 = (_charcode(c) - 0x80) * 8
        for r in font[row0:row0 + 8]:
            out += bytes((r, r))         # both planes: set bit = colour 3
    return bytes(out)


def text(version: str) -> bytes:
    lines = [f"SLINK {check_version(version)}", *LINES]
    parts = []
    for ln in lines:
        ids = [SPACE] * ((WIDTH - len(ln)) // 2) + [FIRST_TILE + GLYPHS.index(c) if c != " " else SPACE for c in ln]
        parts.append(bytes(ids))
    body = bytes([NEXT]).join(parts) + bytes([END])
    assert len(body) <= len(TEXT_BEFORE)
    return body.ljust(len(TEXT_BEFORE), bytes([END]))


def splash_spans(rom: bytes, version: str = DEFAULT_VERSION) -> list[tuple[int, bytes, bytes, str]]:
    """(offset, expected original, replacement, why) -- the same shape as manifest.MENU_PATCHES."""
    t = tiles(rom)
    assert len(t) // 16 <= SPACE - FIRST_TILE
    return [
        (TILES_OFFSET, bytes(len(t)), t, "splash glyph tiles from the menu font, free end of bank $3F"),
        (LD_DE_SITE, LD_DE_BEFORE, bytes((0x11, TILES_ADDR & 0xFF, TILES_ADDR >> 8)),
         "LoadCopyrightTiles source -> splash tiles"),
        (LD_BC_SITE, LD_BC_BEFORE, bytes((0x01, len(t) // 16, BANK)),
         "LoadCopyrightTiles count and bank -> splash tiles"),
        (TEXT_SITE, TEXT_BEFORE, text(version), "CopyrightTextString -> SLink splash lines"),
    ]
