#!/usr/bin/env python3
"""The Gen 3 title screens: a SoulLink wordmark joins each game's title; the patch version lives on the MAIN MENU.

Static asset patch, no code. The title's own loader draws the new graphics, so every fade, flash and restart treats the
wordmark as part of the title. tools/gen_gen1_title.py draws the logo (gen3_title_art.py). The title carries no version
text (owner decision 2026-10-02, like Gen 1 / Gen 2): the version is printed on the New Game / Continue screen by the
payload (patch/src/trade_targets/native_menu.h), and this module only validates it (check_version) and encodes it in
the game's charmap (menu_bytes) for build.py. Two layouts, both measured on running titles (tests/fixtures/gen3/title_*.json):

FireRed / LeafGreen / Radical Red (kind "bg1"). CB2_InitTitleScreen is byte-identical in all three. Charizard / Venusaur is
BG1 (4bpp, priority 1, charblock 1, screenblock 30) and its map is empty on rows 14-15, the black band under the flames and
above PRESS START. The logo palette (loaded into BG banks 0-12) has a bank no BG0 pixel indexes. So the patch relocates BG1's
two LZ77 assets (tiles + map) into the ROM's free tail with the wordmark appended, repoints the two literal-pool words that
name them, and overwrites the unused palette bank in the raw palette asset (read by the init AND the early-skip reload).

Emerald (kind "affine"). Its clouds and Rayquaza scroll and blend, so nothing static can live on them; the Pokemon logo is
an affine 8bpp BG (BG2) whose 256x64 canvas maps 1:1 to the screen at x+29 once settled, with rows 8+ of the canvas empty.
The map names all 256 tile ids in raster order, 133 of them blank; those cells go to tile 0 (the same pixels) which frees
the ids, and the wordmark is drawn into them on empty canvas rows under the "Emerald Version" banner, in the logo's OWN
palette indices (8bpp reads the whole palette), so no palette edit.

Toolchain-free: build.py and the unit tests call title_spans().
    python patch/tools/gen3_title.py --target firered --rom <clean.gba> --out <patched.gba>
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

try:  # imported as a bare module (build.py, the CLI) or as patch.tools.gen3_title (tests)
    from gen3_title_art import LOGO
except ImportError:
    from .gen3_title_art import LOGO

ROM_BASE = 0x08000000
LOGO_W, LOGO_H = len(LOGO[0]), len(LOGO)
_INK = [x for x in range(LOGO_W) if any(row[x] != "0" for row in LOGO)]
LOGO_INK_CENTRE = (_INK[0] + _INK[-1]) // 2                        # the wordmark's visible centre column (its canvas has uneven margins)
DEFAULT_VERSION = "dev"
MENU_PREFIX = "SoulLink "
MAX_VERSION_CHARS = 10                                             # the main-menu line's budget, as on the Game Boy menus
_VERSION_RE = re.compile(r"dev|v\d+\.\d+\.\d+(-dev)?")
# The English Gen 3 charmap, identical in FireRed / LeafGreen / Radical Red / Emerald (pret charmap.txt): what a menu line needs
_CHAR_SPACE, _CHAR_DIGIT0, _CHAR_UPPER_A, _CHAR_LOWER_A, _CHAR_PERIOD, _CHAR_EOS = 0x00, 0xA1, 0xBB, 0xD5, 0xAD, 0xFF

# FR / LG / RR: CB2_InitTitleScreen at 0x08078914 and the literal pool that names its BG assets
BG1_PALS_LIT, BG1_TILES_LIT, BG1_MAP_LIT = 0x08078A94, 0x08078AA4, 0x08078AA8
BG1_PALS_RELOAD_LIT = 0x080796C0           # LoadMainTitleScreenPalsAndResetBgs reloads the same palette asset
BG1_PALS_BYTES, BG1_MAP_BYTES = 0x200, 0x500   # raw palette; the map asset is 32 x 20 entries (rows 0-19)
BG1_ROWS, BG1_CENTRE_X = (14, 15), 88          # the wordmark centres on PRESS START (x 40-136), clamped to the game's free columns
# Emerald: CB2_InitTitleScreen at 0x080AA7A4 and its pool
AFF_GFX_LIT, AFF_MAP_LIT, AFF_PALS_LIT = 0x080AA94C, 0x080AA950, 0x080AA958
AFF_SCREEN_DX, AFF_CENTRE_X = 29, 91                               # canvas x + 29 = screen x; the wordmark is centred on screen x 120
AFF_STRIP_ROW, AFF_STRIP_ROWS, AFF_LOGO_Y = 10, 3, 5               # canvas tile rows 10-12 (y 80-103); logo top at y 85

# Per game. bg1: BG1's map is empty on band rows 14-15 from column 0 to cols-1 (Venusaur starts at 17, Charizard at 19), palette bank, BGR555 colours (0 clear, then fill, extrusion, outline), first free ROM address (FR/LG: past
# the payload's linker bound; RR: inside the 1.6 MB 0xFF run at 0x08B71D04). affine: the logo's own palette indices.
# FireRed / LeafGreen use the Pokemon logo's yellow with its blue outline; Radical Red's logo is white with a black outline.
TARGETS = {
    "firered": {"kind": "bg1", "cols": 19, "bank": 5, "colors": (0x0000, 0x17DF, 0x28A5, 0x7C04), "base": 0x08EC4B20},
    "leafgreen": {"kind": "bg1", "cols": 17, "bank": 5, "colors": (0x0000, 0x17DF, 0x28A5, 0x7C04), "base": 0x08EC4E14},
    "radical_red": {"kind": "bg1", "cols": 19, "bank": 1, "colors": (0x0000, 0x7FFF, 0x4A52, 0x0421), "base": 0x08B72D04},
    "emerald": {"kind": "affine", "base": 0x08E50F64,
                "index": {1: (35, 0x17DF), 2: (71, 0x30A5), 3: (27, 0x7C04)}},   # role: (index, colour it must hold)
}


def check_version(version: str) -> str:
    """The text shown: 'dev' or vX.Y.Z; a '-dev' suffix is dropped, like the Game Boy lines. At most MAX_VERSION_CHARS."""
    if not _VERSION_RE.fullmatch(version):
        raise ValueError(f"version must be 'dev' or vX.Y.Z[-dev], got {version!r}")
    text = version.removesuffix("-dev")
    if len(text) > MAX_VERSION_CHARS:
        raise ValueError(f"version {text!r} is longer than the {MAX_VERSION_CHARS} characters the main menu line holds")
    return text


def menu_text(version: str = DEFAULT_VERSION) -> str:
    """The main-menu line: 'SoulLink dev' / 'SoulLink v0.3.0'."""
    return MENU_PREFIX + check_version(version)


def charmap_bytes(text: str) -> bytes:
    """`text` in the game's charmap (no terminator): space, A-Z, a-z, 0-9 and '.' -- what a menu line needs."""
    out = bytearray()
    for ch in text:
        if ch == " ":
            out.append(_CHAR_SPACE)
        elif "A" <= ch <= "Z":
            out.append(_CHAR_UPPER_A + ord(ch) - ord("A"))
        elif "a" <= ch <= "z":
            out.append(_CHAR_LOWER_A + ord(ch) - ord("a"))
        elif "0" <= ch <= "9":
            out.append(_CHAR_DIGIT0 + ord(ch) - ord("0"))
        elif ch == ".":
            out.append(_CHAR_PERIOD)
        else:
            raise ValueError(f"no charmap entry for {ch!r}")
    return bytes(out)


def menu_bytes(version: str = DEFAULT_VERSION) -> bytes:
    """menu_text in the game's charmap, 0xFF-terminated: the bytes native_menu.h prints with the game's own font."""
    return charmap_bytes(menu_text(version)) + bytes((_CHAR_EOS,))


MENU_FIELD = 20        # patch/tools/rom_identity.py FIELD and native_menu.h SLM_FIELD: the version field is this wide for every version


def menu_field(version: str = DEFAULT_VERSION) -> bytes:
    """menu_bytes padded with zeros to MENU_FIELD: the exact bytes the compiler lays down for the payload's slm_text."""
    return menu_bytes(version).ljust(MENU_FIELD, bytes(1))


def menu_define(version: str = DEFAULT_VERSION) -> str:
    """The compiler define build.py hands the payload: -DSLINK_MENU_TEXT=<this>."""
    return "SLINK_MENU_TEXT=" + ",".join(f"0x{x:02X}" for x in menu_bytes(version))


def lz77_decompress(data: bytes, off: int = 0) -> bytes:
    """GBA BIOS LZ77 (type 0x10)."""
    if data[off] != 0x10:
        raise ValueError(f"not an LZ77 stream at {off:#x}")
    size = int.from_bytes(data[off + 1:off + 4], "little")
    out, p = bytearray(), off + 4
    while len(out) < size:
        flags = data[p]
        p += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                b1, b2 = data[p], data[p + 1]
                p += 2
                disp = ((b1 & 15) << 8 | b2) + 1
                if disp > len(out):
                    raise ValueError("LZ77 back-reference before the start")
                for _ in range(3 + (b1 >> 4)):
                    out.append(out[-disp])
            else:
                out.append(data[p])
                p += 1
    return bytes(out)


def lz77_compress(raw: bytes) -> bytes:
    """Greedy LZ77 the BIOS reads, including the VRAM variant the Emerald loader uses (no 1-byte displacement); word padded."""
    out, n, pos = bytearray(b"\x10" + len(raw).to_bytes(3, "little")), len(raw), 0
    heads: dict[bytes, list[int]] = {}
    while pos < n:
        flag_at = len(out)
        out.append(0)
        for bit in range(8):
            if pos >= n:
                break
            best_len, best_disp = 0, 0
            if pos + 3 <= n:
                for cand in reversed(heads.get(raw[pos:pos + 3], ())):
                    if pos - cand > 4096:
                        break
                    if pos - cand < 2:
                        continue
                    length = 3
                    while length < 18 and pos + length < n and raw[cand + length] == raw[pos + length]:
                        length += 1
                    if length > best_len:
                        best_len, best_disp = length, pos - cand
                        if length == 18:
                            break
            step = best_len if best_len >= 3 else 1
            if best_len >= 3:
                out[flag_at] |= 0x80 >> bit
                out += bytes((((best_len - 3) << 4) | ((best_disp - 1) >> 8), (best_disp - 1) & 0xFF))
            else:
                out.append(raw[pos])
            for k in range(pos, min(pos + step, n - 2)):
                heads.setdefault(raw[k:k + 3], []).append(k)
            pos += step
    out += bytes(-len(out) % 4)
    return bytes(out)


def _paint(rows: list[list[int]], x0: int, y0: int) -> None:
    """Role pixels (1 fill, 2 extrusion, 3 outline) of the wordmark with its canvas origin at (x0, y0)."""
    for y, line in enumerate(LOGO):
        for x, ch in enumerate(line):
            if ch != "0":
                rows[y0 + y][x0 + x] = int(ch)


def _u32(rom: bytes, addr: int) -> int:
    return struct.unpack_from("<I", rom, addr - ROM_BASE)[0]


def _asset(rom: bytes, lit: int) -> tuple[int, bytes]:
    ptr = _u32(rom, lit)
    if not ROM_BASE <= ptr < ROM_BASE + len(rom) or ptr & 3:
        raise ValueError(f"the title's asset pointer at {lit:#010x} is not a ROM address")
    return ptr, lz77_decompress(rom, ptr - ROM_BASE)


def _place(rom: bytes, target: str, base: int | None, blobs: list[bytes]) -> list[int]:
    """The ROM addresses of consecutive new blobs at the target's free base; the run must be untouched 0xFF."""
    base = TARGETS[target]["base"] if base is None else base
    if base is None or base & 3 or not ROM_BASE <= base < ROM_BASE + len(rom):
        raise ValueError(f"{target}: no free ROM address for the title assets")
    size = sum(len(b) for b in blobs)
    if rom[base - ROM_BASE:base - ROM_BASE + size] != b"\xff" * size:
        raise ValueError(f"{target}: the ROM is not free at {base:#010x} for {size:#x} bytes")
    return [base + sum(len(b) for b in blobs[:i]) for i in range(len(blobs))]


def _pointer(rom: bytes, lit: int, address: int, why: str) -> tuple[int, bytes, bytes, str]:
    at = lit - ROM_BASE
    return at, rom[at:at + 4], address.to_bytes(4, "little"), why


def bg1_band(first_id: int, bank: int, cols: int) -> tuple[dict[bytes, int], dict[tuple[int, int], int]]:
    """FR / LG / RR: the 4bpp tiles (-> BG1 tile id) and the map entries ((col, row) -> entry) of the wordmark, ids from first_id.

    The canvas is cols x 8 by 16 pixels: the wordmark's ink centred on PRESS START and pulled left where the game's other
    art starts sooner."""
    rows = [[0] * (cols * 8) for _ in range(16)]
    x0 = min(BG1_CENTRE_X - LOGO_INK_CENTRE, cols * 8 - LOGO_W)
    if x0 < 0:
        raise ValueError(f"the title wordmark ({LOGO_W} px) does not fit {cols} free columns")
    _paint(rows, x0, 0)
    blobs: dict[bytes, int] = {}
    entries: dict[tuple[int, int], int] = {}
    for r in range(2):
        for c in range(cols):
            cell = [rows[r * 8 + y][c * 8:c * 8 + 8] for y in range(8)]
            if any(any(row) for row in cell):
                tile = bytes(row[x] | row[x + 1] << 4 for row in cell for x in range(0, 8, 2))
                blobs.setdefault(tile, first_id + len(blobs))
                entries[(c, BG1_ROWS[r])] = blobs[tile] | bank << 12
    if first_id + len(blobs) > 512:
        raise ValueError("BG1's charblock cannot hold the title band")
    return blobs, entries


def _bg1_spans(rom: bytes, target: str, base: int | None) -> list[tuple[int, bytes, bytes, str]]:
    spec = TARGETS[target]
    pals = _u32(rom, BG1_PALS_LIT)
    if _u32(rom, BG1_PALS_RELOAD_LIT) != pals:
        raise ValueError("the early-skip palette reload names a different palette than the init")
    if pals & 3 or pals - ROM_BASE + BG1_PALS_BYTES > len(rom):
        raise ValueError("the title's palette pointer is not a ROM address")
    _, vanilla_tiles = _asset(rom, BG1_TILES_LIT)
    _, vanilla_map = _asset(rom, BG1_MAP_LIT)
    if len(vanilla_tiles) % 32 or len(vanilla_map) != BG1_MAP_BYTES or any(vanilla_tiles[:32]):
        raise ValueError("BG1's tiles / map are not the title's Charizard / Venusaur assets")
    first_id = len(vanilla_tiles) // 32
    blobs, entries = bg1_band(first_id, spec["bank"], spec["cols"])
    tilemap = bytearray(vanilla_map)
    for (col, row), entry in entries.items():
        at = (row * 32 + col) * 2
        if int.from_bytes(tilemap[at:at + 2], "little") & 0x3FF:      # empty cells are tile 0 in palette bank 13 (0xD000)
            raise ValueError(f"BG1 map cell ({col}, {row}) is not empty on this ROM")
        tilemap[at:at + 2] = entry.to_bytes(2, "little")
    tiles_lz = lz77_compress(vanilla_tiles + b"".join(blobs))        # dict order is id order
    map_lz = lz77_compress(bytes(tilemap))
    tiles_at, map_at = _place(rom, target, base, [tiles_lz, map_lz])
    bank_at = pals - ROM_BASE + spec["bank"] * 32
    bank = b"".join(c.to_bytes(2, "little") for c in list(spec["colors"]) + [0] * (16 - len(spec["colors"])))
    return [
        (tiles_at - ROM_BASE, b"\xff" * len(tiles_lz), tiles_lz, "BG1 tiles: Charizard / Venusaur plus the SoulLink wordmark"),
        (map_at - ROM_BASE, b"\xff" * len(map_lz), map_lz, "BG1 map: the wordmark on rows 14-15"),
        _pointer(rom, BG1_TILES_LIT, tiles_at, "init loads the new BG1 tiles"),
        _pointer(rom, BG1_MAP_LIT, map_at, "init loads the new BG1 map"),
        (bank_at, rom[bank_at:bank_at + 32], bank, f"logo palette bank {spec['bank']}: no BG0 pixel indexes it"),
    ]


def affine_band(free_ids: list[int], role_index: dict[int, int]) -> tuple[dict[bytes, int], bytearray]:
    """Emerald: the 8bpp tiles (-> logo tile id, taken in order from free_ids) and the map bytes through the band's last row.

    Role pixels become the logo's own palette indices; the wordmark's ink is centred on the screen, a canvas x of AFF_CENTRE_X."""
    x0 = AFF_CENTRE_X - LOGO_INK_CENTRE
    rows = [[0] * 256 for _ in range(AFF_STRIP_ROWS * 8)]
    _paint(rows, x0, AFF_LOGO_Y)
    roles = {0: 0, **role_index}
    blobs: dict[bytes, int] = {}
    new_map = bytearray((AFF_STRIP_ROW + AFF_STRIP_ROWS) * 32)
    for r in range(AFF_STRIP_ROWS):
        for c in range(32):
            cell = [rows[r * 8 + y][c * 8:c * 8 + 8] for y in range(8)]
            if any(any(row) for row in cell):
                tile = bytes(roles[v] for row in cell for v in row)
                if tile not in blobs:
                    if len(blobs) >= len(free_ids):
                        raise ValueError("the logo layer has no free tile ids left for the title wordmark")
                    blobs[tile] = free_ids[len(blobs)]
                new_map[(AFF_STRIP_ROW + r) * 32 + c] = blobs[tile]
    return blobs, new_map


def _affine_spans(rom: bytes, target: str, base: int | None) -> list[tuple[int, bytes, bytes, str]]:
    spec = TARGETS[target]
    pals = _u32(rom, AFF_PALS_LIT)
    if pals & 3 or pals - ROM_BASE + 0x1E0 > len(rom):
        raise ValueError("the title's palette pointer is not a ROM address")
    for role, (index, colour) in spec["index"].items():
        if struct.unpack_from("<H", rom, pals - ROM_BASE + index * 2)[0] != colour:
            raise ValueError(f"palette index {index} (role {role}) is not the logo colour {colour:#06x} on this ROM")
    _, gfx_raw = _asset(rom, AFF_GFX_LIT)
    gfx = bytearray(gfx_raw)
    _, amap = _asset(rom, AFF_MAP_LIT)
    if len(gfx_raw) != 0x4000 or len(amap) != 1024 or list(amap[:256]) != list(range(256)) or any(amap[256:]):
        raise ValueError("the title logo is not the 256x64 raster the band relies on")
    blank = {t for t in range(256) if not any(gfx[t * 64:(t + 1) * 64])}
    if 0 not in blank:
        raise ValueError("logo tile 0 is not blank")
    amap = bytearray(0 if t in blank else t for t in amap)           # blank cells -> tile 0: the same pixels, ids freed
    blobs, band_map = affine_band(sorted(blank - {0}), {role: index for role, (index, _) in spec["index"].items()})
    new_map = bytearray(len(amap))                                   # same size as the vanilla asset; rows 8+ were empty
    new_map[:len(band_map)] = band_map
    new_map[:256] = amap[:256]                                       # the logo rows, blank cells already pointed at tile 0
    for tile, tid in blobs.items():
        gfx[tid * 64:(tid + 1) * 64] = tile
    gfx_lz, map_lz = lz77_compress(bytes(gfx)), lz77_compress(bytes(new_map))
    gfx_at, map_at = _place(rom, target, base, [gfx_lz, map_lz])
    return [
        (gfx_at - ROM_BASE, b"\xff" * len(gfx_lz), gfx_lz, "logo tiles: the Pokemon logo plus the SoulLink wordmark in its blank ids"),
        (map_at - ROM_BASE, b"\xff" * len(map_lz), map_lz, "logo map: blank cells to tile 0, the wordmark on rows 10-12"),
        _pointer(rom, AFF_GFX_LIT, gfx_at, "init loads the new logo tiles"),
        _pointer(rom, AFF_MAP_LIT, map_at, "init loads the new logo map"),
    ]


def title_spans(rom: bytes, target: str, base: int | None = None) -> list[tuple[int, bytes, bytes, str]]:
    """(rom offset, original bytes, replacement, why). Raises ValueError for anything the ROM does not look like."""
    if target not in TARGETS:
        raise ValueError(f"unknown title target {target!r}")
    build = _bg1_spans if TARGETS[target]["kind"] == "bg1" else _affine_spans
    return build(rom, target, base)


def apply_title(data: bytearray, target: str, base: int | None = None) -> list[dict]:
    """Write the spans into `data` (a clean ROM); returns what changed, for the build receipt and the protected spans."""
    spans = title_spans(bytes(data), target, base)
    for off, _, new, _ in spans:
        data[off:off + len(new)] = new
    return [{"offset": off, "size": len(new), "original": old.hex(), "why": why} for off, old, new, why in spans]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--target", choices=sorted(TARGETS), required=True)
    ap.add_argument("--rom", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    data = bytearray(Path(args.rom).read_bytes())
    for span in apply_title(data, args.target):
        print(f"{span['offset']:#010x} +{span['size']:#x}  {span['why']}")
    Path(args.out).write_bytes(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
