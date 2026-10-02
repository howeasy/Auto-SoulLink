#!/usr/bin/env python3
"""Draw the SoulLink title art for every SLink-patched family and write it where each patch reads it.

The logo is drawn once in the Pokemon logo's style (grey fill, black outline, darker extrusion) and recoloured per game:

    Gen 1 Red/Blue      patch/gen1/tools/title_art.py        9x2 tiles in the 16 pixel band under the Pokemon logo
    pureRGB overlay     patch/gen1/purergb/overlay/title_*   the same art, ids $60-$79
    Crystal             patch/gen2/src/title_logo_crystal.2bpp + title_rows_crystal.inc   gold / blue / white
    Gold / Silver       patch/gen2/src/title_logo_gs.2bpp + title_rows_gs.inc             a stacked "Soul" / "Link"

    python tools/gen_gen1_title.py             # rewrite all of it, preview -> patch/build/gen1_title_logo.png

The version line is NOT drawn here: each patcher renders it from --version with the 5x7 font in title_art.SMALL.
Needs Pillow (dev only); the patchers import plain bytes.
"""
import pathlib
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_PY = ROOT / "patch/gen1/tools/title_art.py"
PREVIEW = ROOT / "patch/build/gen1_title_logo.png"
OVERLAY = ROOT / "patch/gen1/purergb/overlay"          # pureRGB: tiles as a raw .2bpp and the rows as an .inc
PURE_FIRST_ID = 0x60                                    # pureRGB's free run on the vanilla-style title is $60-$79

WHITE, LIGHT, DARK, BLACK = 0, 1, 2, 3
SHADES = (255, 170, 85, 0)
COLS, ROWS = 9, 2
FIRST_ID = 0x6A                                                 # free BG tile ids on the vanilla title: $6A-$7E

# "SoulLink" at 9 rows tall with 2 pixel strokes: the Pokemon logo's style needs room for an outline and an
# extrusion, and a 16 pixel band has none to spare. Lowercase letters sit on the baseline (rows 3-8).
_GLYPHS = {
    "S": (".####.", "##..##", "##....", "##....", ".####.", "....##", "....##", "##..##", ".####."),
    "o": (".####.", "##..##", "##..##", "##..##", "##..##", ".####."),
    "u": ("##..##", "##..##", "##..##", "##..##", "##..##", ".#####"),
    "l": ("##",) * 9,
    "L": ("##...", "##...", "##...", "##...", "##...", "##...", "##...", "#####", "#####"),
    "i": ("##", "##", "..", "##", "##", "##", "##", "##", "##"),
    "n": ("#####.", "##..##", "##..##", "##..##", "##..##", "##..##"),
    "k": ("##....", "##....", "##..##", "##.##.", "####..", "####..", "##.##.", "##..##", "##..##"),
}
WORD, GAP, HEIGHT = "SoulLink", 3, 9


# 5x7 glyphs for the version line and the Pure title's "SoulLink vX.Y.Z" line, rendered at patch time by patch/gen1/tools/title_screen.py
_SMALL = """
S 01111 10000 10000 01110 00001 00001 11110
L 10000 10000 10000 10000 10000 10000 11111
o 00000 00000 01110 10001 10001 10001 01110
u 00000 00000 10001 10001 10001 10011 01101
l 01100 00100 00100 00100 00100 00100 01110
i 00100 00000 01100 00100 00100 00100 01110
n 00000 00000 10110 11001 10001 10001 10001
k 10000 10000 10010 10100 11000 10100 10010
v 00000 00000 10001 10001 10001 01010 00100
d 00001 00001 01101 10011 10001 10011 01101
e 00000 00000 01110 10001 11111 10000 01110
0 01110 10001 10011 10101 11001 10001 01110
1 00100 01100 00100 00100 00100 00100 01110
2 01110 10001 00001 00010 00100 01000 11111
3 11110 00001 00001 01110 00001 00001 11110
4 00010 00110 01010 10010 11111 00010 00010
5 11111 10000 11110 00001 00001 10001 01110
6 00110 01000 10000 11110 10001 10001 01110
7 11111 00001 00010 00100 01000 01000 01000
8 01110 10001 10001 01110 10001 10001 01110
9 01110 10001 10001 01111 00001 00010 01100
. 00000 00000 00000 00000 00000 01100 01100
- 00000 00000 00000 11111 00000 00000 00000
"""
SMALL = {ln.split()[0]: bytes(int(r, 2) for r in ln.split()[1:]) for ln in _SMALL.strip().splitlines()}


def word_mask(size, x, y, word=WORD, gap=GAP):
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for c in word:
        rows = _GLYPHS[c]
        for ry, row in enumerate(rows):
            for rx, bit in enumerate(row):
                if bit == "#":
                    d.point((x + rx, y + HEIGHT - len(rows) + ry), fill=255)
        x += len(rows[0]) + gap
    return m


def paint(img, mask, shade):
    img.paste(shade, mask=mask.point(lambda v: 255 if v else 0))


def dilate(mask):
    return mask.filter(ImageFilter.MaxFilter(3))


def draw() -> Image.Image:
    img = Image.new("L", (COLS * 8, ROWS * 8), WHITE)
    m = word_mask(img.size, 5, 3)
    paint(img, ImageChops.offset(dilate(m), 1, 1), DARK)             # extrusion, down-right
    paint(img, dilate(m), BLACK)                                      # outline
    paint(img, m, LIGHT)
    return img


def stacked() -> Image.Image:
    """Gold/Silver: "Soul" over "Link", two 32x16 boxes (4x2 tiles each), tighter letter spacing."""
    img = Image.new("L", (32, 32), WHITE)
    for word, x, y in (("Soul", 2, 3), ("Link", 2, 19)):
        m = word_mask(img.size, x, y, word, gap=2)
        paint(img, ImageChops.offset(dilate(m), 1, 1), DARK)
        paint(img, dilate(m), BLACK)
        paint(img, m, LIGHT)
    return img


def pack(img, cols, rows, remap):
    """Dedupe the 8x8 cells row-major into 2bpp tiles; `remap` turns the drawing's shades into palette indices."""
    tiles, ids, order = [], {}, []
    for ty in range(rows):
        for tx in range(cols):
            cell = img.crop((tx * 8, ty * 8, tx * 8 + 8, ty * 8 + 8))
            key = cell.tobytes()
            if key not in ids:
                ids[key] = len(tiles)
                tiles.append(cell)
            order.append(ids[key])
    data = bytearray()
    for t in tiles:
        p = t.load()
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = remap[p[x, y]]
                lo |= (v & 1) << (7 - x)
                hi |= (v >> 1) << (7 - x)
            data += bytes((lo, hi))
    return bytes(data), order, len(tiles)


# shade drawn -> palette index. Crystal's logo palette 6 is black, white, gold, blue: the Pokemon logo's own gold
# letters with a blue outline and a white edge. Gold/Silver's logo palette 1 is orange, grey, sky blue, dark blue.
CRYSTAL_ROLES = {WHITE: 0, LIGHT: 2, DARK: 1, BLACK: 3}
GS_ROLES = {WHITE: 2, LIGHT: 0, DARK: 1, BLACK: 3}
GEN2_SRC = ROOT / "patch/gen2/src"


def write_gen2() -> str:
    """Crystal: the 9x2 logo at ids $60-; Gold/Silver: the stacked 4x4 logo at ids $70-$7F (patch/gen2/src/title.asm)."""
    GEN2_SRC.mkdir(parents=True, exist_ok=True)
    out = []
    ids = lambda b: ",".join(f"${v:02X}" for v in b)                    # noqa: E731
    data, order, n = pack(draw(), COLS, ROWS, CRYSTAL_ROLES)
    (GEN2_SRC / "title_logo_crystal.2bpp").write_bytes(data)
    first = 0x60
    inc = ["; GENERATED by tools/gen_gen1_title.py -- do not edit. Crystal title band: the logo's tile ids (9 wide).",
           f"DEF SLINK_TITLE_LOGO_TILES EQU {n}", f"DEF SLINK_TITLE_FIRST_TILE EQU ${first:02X}"]
    for r in range(ROWS):
        inc += [f"SlinkTitleLogoRow{r}:", f"\tdb {ids(bytes(first + k for k in order[r * COLS:(r + 1) * COLS]))}"]
    (GEN2_SRC / "title_rows_crystal.inc").write_text("\n".join(inc) + "\n", encoding="utf-8", newline="\n")
    out.append(f"crystal {n} tiles")
    data, order, n = pack(stacked(), 4, 4, GS_ROLES)
    assert n <= 16, f"{n} tiles; Gold/Silver's free run $70-$7F holds 16"
    (GEN2_SRC / "title_logo_gs.2bpp").write_bytes(data)
    first = 0x70
    inc = ["; GENERATED by tools/gen_gen1_title.py -- do not edit. Gold/Silver title band: the stacked logo's tile ids (4 wide).",
           f"DEF SLINK_TITLE_LOGO_TILES EQU {n}", f"DEF SLINK_TITLE_FIRST_TILE EQU ${first:02X}"]
    for r in range(4):
        inc += [f"SlinkTitleLogoRow{r}:", f"\tdb {ids(bytes(first + k for k in order[r * 4:(r + 1) * 4]))}"]
    (GEN2_SRC / "title_rows_gs.inc").write_text("\n".join(inc) + "\n", encoding="utf-8", newline="\n")
    out.append(f"gold/silver {n} tiles")
    return ", ".join(out)


def main() -> int:
    print(write_gen2())
    img = draw()
    tiles, ids, order = [], {}, []
    for ty in range(ROWS):
        for tx in range(COLS):
            cell = img.crop((tx * 8, ty * 8, tx * 8 + 8, ty * 8 + 8))
            key = cell.tobytes()
            if key not in ids:
                ids[key] = len(tiles)
                tiles.append(cell)
            order.append(ids[key])
    data = bytearray()
    for t in tiles:
        p = t.load()
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = p[x, y]
                lo |= (v & 1) << (7 - x)
                hi |= (v >> 1) << (7 - x)
            data += bytes((lo, hi))
    rows = [bytes(FIRST_ID + k for k in order[r * COLS:(r + 1) * COLS]) for r in range(ROWS)]
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    prev = Image.new("RGB", img.size)
    prev.putdata([(SHADES[v],) * 3 for v in img.getdata()])
    prev.resize((img.width * 8, img.height * 8), Image.NEAREST).save(PREVIEW)
    h = bytes(data).hex()
    OUT_PY.write_text(
        '"""GENERATED by tools/gen_gen1_title.py -- do not edit. The SoulLink logo for the Gen 1 title screen:\n'
        '2bpp tiles and the two rows of tile ids that place them."""\n\n'
        f"FIRST_ID = {FIRST_ID:#04x}\nTILE_COUNT = {len(tiles)}\n"
        f"SMALL = {SMALL!r}\n"
        f"ROW0 = bytes.fromhex({rows[0].hex()!r})\nROW1 = bytes.fromhex({rows[1].hex()!r})\n"
        "TILES = bytes.fromhex(\n" + "\n".join(f'    "{h[i:i + 96]}"' for i in range(0, len(h), 96)) + "\n)\n",
        encoding="utf-8")
    OVERLAY.mkdir(parents=True, exist_ok=True)
    (OVERLAY / "title_logo.2bpp").write_bytes(bytes(data))
    pure = [bytes(PURE_FIRST_ID + k for k in order[r * COLS:(r + 1) * COLS]) for r in range(ROWS)]
    ids = lambda b: ",".join(f"${v:02X}" for v in b)                  # noqa: E731
    inc = [
        "; GENERATED by tools/gen_gen1_title.py -- do not edit. Tile ids of the SoulLink title band.",
        f"DEF SLINK_TITLE_FIRST_TILE EQU ${PURE_FIRST_ID:02X}",
        f"DEF SLINK_TITLE_LOGO_TILES EQU {len(tiles)}",
        "SlinkTitleLogoRow0:", f"\tdb {ids(pure[0])},$50",
        "SlinkTitleLogoRow1:", f"\tdb {ids(pure[1])},$50",
    ]
    (OVERLAY / "title_band_rows.inc").write_text("\n".join(inc) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(tiles)} tiles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
