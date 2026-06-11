#!/usr/bin/env python3
"""Montage a list of PNGs into a labeled grid (so a reviewer can read many shots in one image).
Usage: montage.py <out.png> <cols> <label1> <img1> [<label2> <img2> ...]"""
import sys
from PIL import Image, ImageDraw

out, cols = sys.argv[1], int(sys.argv[2])
rest = sys.argv[3:]
pairs = [(rest[i], rest[i + 1]) for i in range(0, len(rest), 2)]
imgs = []
for label, path in pairs:
    try:
        im = Image.open(path).convert("RGB")
    except Exception as e:
        im = Image.new("RGB", (240, 160), (40, 0, 0))
        ImageDraw.Draw(im).text((4, 70), "MISSING", fill=(255, 80, 80))
    imgs.append((label, im))

if not imgs:
    sys.exit("no images")
cw, ch = imgs[0][1].size
pad, lh, scale = 6, 14, 2
tile_w, tile_h = cw * scale, ch * scale + lh
rows = (len(imgs) + cols - 1) // cols
grid = Image.new("RGB", (cols * tile_w + pad * (cols + 1), rows * tile_h + pad * (rows + 1)), (20, 20, 24))
d = ImageDraw.Draw(grid)
for idx, (label, im) in enumerate(imgs):
    r, c = divmod(idx, cols)
    x = pad + c * (tile_w + pad)
    y = pad + r * (tile_h + pad)
    d.text((x + 2, y), label, fill=(255, 255, 0))
    grid.paste(im.resize((tile_w, ch * scale), Image.NEAREST), (x, y + lh))
grid.save(out)
print("wrote", out, grid.size)
