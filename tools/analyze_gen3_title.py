#!/usr/bin/env python3
"""Turn a lua/tests/probe_gen3_title_vram.lua dump into the compact fixture tests/unit/test_gen3_title_screen.py reads.

    python tools/analyze_gen3_title.py <dump dir> <frame tag, e.g. f02800> <game> > tests/fixtures/gen3/title_<game>.json

It records only measured facts the title patch (patch/tools/gen3_title.py) relies on: the BG layout and which palette
indices / banks / tile ids / map cells the settled vanilla title actually uses, and the visible sprites.
"""
import json
import struct
import sys
from pathlib import Path

SIZES = {0: (32, 32), 1: (64, 32), 2: (32, 64), 3: (64, 64)}
OBJ_DIMS = {(0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64), (1, 0): (16, 8), (1, 1): (32, 8),
            (1, 2): (32, 16), (1, 3): (64, 32), (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64)}


def text_map(vram: bytes, screenblock: int) -> dict[tuple[int, int], int]:
    """32x32 text map entries that name a non-blank tile: (col, row) -> entry."""
    out = {}
    for i in range(1024):
        entry = struct.unpack_from("<H", vram, screenblock * 0x800 + i * 2)[0]
        if entry & 0x3FF:
            out[(i % 32, i // 32)] = entry
    return out


def analyze(directory: Path, tag: str, game: str) -> dict:
    io = [int(x, 16) for x in (directory / f"{tag}_io.txt").read_text().split()]
    vram = (directory / f"{tag}_vram.bin").read_bytes()
    pal = struct.unpack("<512H", (directory / f"{tag}_pal.bin").read_bytes())
    oam = (directory / f"{tag}_oam.bin").read_bytes()
    dispcnt = io[0]
    bgs = []
    for i in range(4):
        cnt = io[4 + i]
        bgs.append({"bg": i, "on": bool(dispcnt >> (8 + i) & 1), "priority": cnt & 3, "charblock": cnt >> 2 & 3,
                    "bpp8": cnt >> 7 & 1, "screenblock": cnt >> 8 & 31, "size": SIZES[cnt >> 14 & 3], "cnt": f"{cnt:04X}"})
    out = {"game": game, "tag": tag, "dispcnt": f"{dispcnt:04X}", "mode": dispcnt & 7, "bgs": bgs,
           "empty_obj_palette_banks": [b for b in range(16) if not any(pal[256 + b * 16:256 + b * 16 + 16])]}
    for bg in bgs:
        if not bg["on"] or (dispcnt & 7 == 1 and bg["bg"] == 2):        # mode 1: BG2 is affine, handled below
            continue
        cells = text_map(vram, bg["screenblock"])
        tsize = 64 if bg["bpp8"] else 32
        base = bg["charblock"] * 0x4000
        bg["map_cells"] = sorted([c, r] for c, r in cells)
        bg["map_palette_banks"] = sorted({e >> 12 for e in cells.values()})
        bg["nonzero_tiles"] = [t for t in range(0x4000 // tsize) if any(vram[base + t * tsize:base + (t + 1) * tsize])]
        if bg["bpp8"]:
            used = set()
            for e in cells.values():
                used |= set(vram[base + (e & 0x3FF) * 64:base + ((e & 0x3FF) + 1) * 64])
            bg["palette_indices_used"] = sorted(used)
    if dispcnt & 7 == 1:        # Emerald: BG2 is the affine 8bpp logo, one byte per map cell
        amap = vram[0x4800:0x4800 + 1024]
        blank = [t for t in range(256) if not any(vram[t * 64:(t + 1) * 64])]
        used = set()
        for t in set(amap):
            used |= set(vram[t * 64:(t + 1) * 64])
        out["affine"] = {"screenblock": 9, "map_rows_used": max(r for r in range(32) if any(amap[r * 32:(r + 1) * 32])) + 1,
                         "blank_tile_ids": blank, "palette_indices_used": sorted(used),
                         "colours": {str(i): f"{pal[i]:04X}" for i in sorted(used) if pal[i]}}
    sprites = []
    for n in range(128):
        a0, a1, a2 = struct.unpack_from("<HHH", oam, n * 8)
        y = a0 & 0xFF
        if a0 >> 8 & 3 == 2 or 160 <= y <= 224:
            continue
        w, h = OBJ_DIMS[(a0 >> 14 & 3, a1 >> 14 & 3)]
        x = a1 & 0x1FF
        size = w * h if a0 >> 13 & 1 else w * h // 2                    # bytes of OBJ tile data it can show (1D mapping)
        opaque = any(vram[0x10000 + (a2 & 0x3FF) * 32:0x10000 + (a2 & 0x3FF) * 32 + size])
        sprites.append([x - 512 if x >= 256 else x, y, w, h, a2 & 0x3FF, a2 >> 12, a2 >> 10 & 3, int(opaque)])
    out["sprites_xywh_tile_pal_prio_opaque"] = sprites
    out["bg_palette_nonzero_banks"] = [b for b in range(16) if any(pal[b * 16:b * 16 + 16])]
    out["bg_palette_bank5"] = [f"{c:04X}" for c in pal[80:96]]
    return out


if __name__ == "__main__":
    print(json.dumps(analyze(Path(sys.argv[1]), sys.argv[2], sys.argv[3]), separators=(",", ":")))
