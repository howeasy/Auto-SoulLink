#!/usr/bin/env python3
"""Draw the Gen 1 SLink boot splash and write patch/gen1/tools/splash_art.py.

A plain white screen in the game's own four shades: SLINK in the Pokemon logo's style, a red and
a blue Poke Ball joined by a chain, and a version row that is filled in at patch time (so the
art itself never depends on the version).

    python tools/gen_gen1_splash.py             # rewrite splash_art.py, preview -> patch/build/gen1_splash.png

Needs Pillow (dev only). The patcher imports the generated splash_art.py, which is plain bytes.
"""
import pathlib
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT_PY = ROOT / "patch/gen1/tools/splash_art.py"
PREVIEW = ROOT / "patch/build/gen1_splash.png"

W, H = 160, 144
WHITE, LIGHT, DARK, BLACK = 0, 1, 2, 3
SHADES = (255, 170, 85, 0)                                      # BGP %11100100
GLYPHS = "v.-de0123456789"                                      # the version row, one 8x8 cell each
VERSION_ROW, VERSION_COLS = 15, (4, 16)                         # tile row, [first, end) tile columns

_FONT = """
A 01110 10001 10001 11111 10001 10001 10001
C 01110 10001 10000 10000 10000 10001 01110
E 11111 10000 10000 11110 10000 10000 11111
I 01110 00100 00100 00100 00100 00100 01110
K 10001 10010 10100 11000 10100 10010 10001
L 10000 10000 10000 10000 10000 10000 11111
N 10001 11001 10101 10011 10001 10001 10001
O 01110 10001 10001 10001 10001 10001 01110
S 01111 10000 10000 01110 00001 00001 11110
U 10001 10001 10001 10001 10001 10001 01110
Z 11111 00001 00010 00100 01000 10000 11111
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
FONT = {ln.split()[0]: ln.split()[1:] for ln in _FONT.strip().splitlines()}


def glyph_mask(size, x, y, s, u=1, bold=0, gap=1):
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for c in s:
        if c == " ":
            x += 4 * u
            continue
        for ry, row in enumerate(FONT[c]):
            for rx, bit in enumerate(row):
                if bit == "1":
                    d.rectangle([x + rx * u, y + ry * u, x + rx * u + u - 1 + bold, y + ry * u + u - 1 + bold], fill=255)
        x += (5 + gap) * u + bold
    return m


def text_w(s, u=1, bold=0, gap=1):
    return sum(4 * u if c == " " else (5 + gap) * u + bold for c in s) - gap * u


def paint(img, mask, shade):
    img.paste(shade, mask=mask.point(lambda v: 255 if v else 0))


def shifted(mask, dx, dy):
    return ImageChops.offset(mask, dx, dy)


def dilate(mask, n=1):
    for _ in range(n):
        mask = mask.filter(ImageFilter.MaxFilter(3))
    return mask


def ball(img, cx, cy, r, top):
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE, outline=BLACK, width=2)
    d.pieslice([cx - r + 2, cy - r + 2, cx + r - 2, cy + r - 2], 180, 360, fill=top)
    d.rectangle([cx - r + 1, cy - 1, cx + r - 1, cy], fill=BLACK)
    d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=WHITE, outline=BLACK, width=2)
    d.ellipse([cx - 1, cy - 1, cx + 1, cy + 1], fill=LIGHT)


def chain(img, x0, x1, cy):
    d = ImageDraw.Draw(img)
    hl, h = 26, 7
    for xs in (x0, x1 - hl):
        d.rounded_rectangle([xs, cy - h, xs + hl, cy + h], radius=h, fill=LIGHT, outline=BLACK, width=2)
        d.rounded_rectangle([xs + 5, cy - h + 4, xs + hl - 5, cy + h - 4], radius=3, fill=WHITE, outline=BLACK, width=1)
    mid = (x0 + x1) // 2
    d.rounded_rectangle([mid - 11, cy - 4, mid + 11, cy + 4], radius=4, fill=DARK, outline=BLACK, width=2)


def draw() -> Image.Image:
    img = Image.new("L", (W, H), WHITE)
    word, u, bold = "SLINK", 3, 1
    wx, wy = (W - text_w(word, u, bold)) // 2 - 1, 16
    m = glyph_mask((W, H), wx, wy, word, u, bold)
    paint(img, shifted(dilate(m), 2, 2), DARK)                  # the logo's extrusion
    paint(img, dilate(m), BLACK)                                # outline
    paint(img, m, LIGHT)
    paint(img, ImageChops.subtract(m, shifted(m, 0, 1)), WHITE)  # top-edge highlight
    sub = "SOUL LINK NUZLOCKE"
    paint(img, glyph_mask((W, H), (W - text_w(sub)) // 2, 54, sub), BLACK)
    ImageDraw.Draw(img).line([(22, 65), (138, 65)], fill=DARK)
    cy = 94
    ball(img, 32, cy, 14, DARK)
    ball(img, 128, cy, 14, LIGHT)
    chain(img, 50, 110, cy)
    return img


def tileize(img: Image.Image):
    """Dedupe 8x8 cells into 2bpp tiles; ids follow VRAM order from $8800 (128 tiles at $80.., then $00..)."""
    tiles, ids, glyph_cells = [], {}, {}
    for c in GLYPHS:
        m = glyph_mask((8, 8), 1, 0, c)
        cell = Image.new("L", (8, 8), WHITE)
        paint(cell, m, BLACK)
        glyph_cells[c] = cell
    blank = Image.new("L", (8, 8), WHITE)
    work = [blank, *glyph_cells.values()]
    for ty in range(H // 8):
        for tx in range(W // 8):
            work.append(img.crop((tx * 8, ty * 8, tx * 8 + 8, ty * 8 + 8)))
    for cell in work:
        key = cell.tobytes()
        if key not in ids:
            ids[key] = len(tiles)
            tiles.append(cell)
    assert len(tiles) <= 255, f"{len(tiles)} unique tiles; the splash can hold 255"

    def vram_id(k):
        return 0x80 + k if k < 128 else k - 128

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
    tmap = bytearray(vram_id(ids[work[i].tobytes()]) for i in range(len(work) - 360, len(work)))
    glyph_ids = {c: vram_id(ids[glyph_cells[c].tobytes()]) for c in GLYPHS}
    return bytes(data), bytes(tmap), vram_id(ids[blank.tobytes()]), glyph_ids


def wrap(b: bytes, name: str) -> str:
    h = b.hex()
    body = "\n".join(f'    "{h[i:i + 96]}"' for i in range(0, len(h), 96))
    return f"{name} = bytes.fromhex(\n{body}\n)\n"


def main() -> int:
    img = draw()
    data, tmap, blank, glyph_ids = tileize(img)
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    prev = Image.new("RGB", (W, H))
    prev.putdata([(SHADES[v],) * 3 for v in img.getdata()])
    prev.resize((W * 4, H * 4), Image.NEAREST).save(PREVIEW)
    OUT_PY.write_text(
        '"""GENERATED by tools/gen_gen1_splash.py -- do not edit. The Gen 1 boot splash art: 2bpp tiles, the\n'
        '20x18 tile map (version row blank), and where the version glyphs go."""\n\n'
        f"TILE_COUNT = {len(data) // 16}\n"
        f"BLANK_ID = {blank:#04x}\n"
        f"GLYPHS = {GLYPHS!r}\n"
        f"GLYPH_IDS = {glyph_ids!r}\n"
        f"VERSION_ROW = {VERSION_ROW}\n"
        f"VERSION_COLS = {VERSION_COLS!r}\n\n"
        + wrap(data, "TILES") + "\n" + wrap(tmap, "MAP"), encoding="utf-8")
    print(f"{len(data) // 16} tiles, preview {PREVIEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
