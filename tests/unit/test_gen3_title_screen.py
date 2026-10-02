"""The Gen 3 title wordmark (patch/tools/gen3_title.py): the codec, the art, what the measured vanilla titles leave free, how
build.py stamps it, and -- with the owner ROMs (SLINK_GEN3_ROMS) -- the patched assets themselves. The title carries the
wordmark ONLY: the version is on the main menu (tests/unit/test_gen3_menu_version.py).

Absent input skips; present-but-wrong input fails.
"""
from __future__ import annotations

import json
import os
import random
import re
import struct
from pathlib import Path

import pytest

from patch.tools import gen3_title as g

ROOT = Path(__file__).resolve().parents[2]
ROMS = {"firered": "Pokemon - FireRed Version (USA).gba", "leafgreen": "Pokemon - LeafGreen Version (USA).gba",
        "radical_red": "Pokemon - Radical Red.gba", "emerald": "Pokemon - Emerald Version (USA, Europe).gba"}
BG1 = ("firered", "leafgreen", "radical_red")


def fixture(game: str) -> dict:
    return json.loads((ROOT / f"tests/fixtures/gen3/title_{game}.json").read_text())


def owner_rom(game: str) -> bytes:
    root = os.environ.get("SLINK_GEN3_ROMS")
    if not root:
        pytest.skip("SLINK_GEN3_ROMS (the owner ROM directory) is required")
    path = Path(root) / ROMS[game]
    if not path.exists():
        pytest.skip(f"{path} is absent")
    return path.read_bytes()


@pytest.fixture(params=sorted(ROMS))
def rom(request):
    return request.param, owner_rom(request.param)


def patched(clean: bytes, target: str) -> bytes:
    out = bytearray(clean)
    g.apply_title(out, target)
    return bytes(out)


def bg1_ink(blobs: dict[bytes, int], entries: dict[tuple[int, int], int]) -> set[tuple[int, int]]:
    """Screen pixels (x, y) the 4bpp band draws: a nibble is a palette index within the entry's bank, 0 is clear."""
    by_id = {tile_id: tile for tile, tile_id in blobs.items()}
    return {(col * 8 + x, row * 8 + y) for (col, row), entry in entries.items()
            for y in range(8) for x in range(8)
            if by_id[entry & 0x3FF][y * 4 + x // 2] >> (4 * (x & 1)) & 15}


# ---- the codec -----------------------------------------------------------------------------------------------------

def _tokens(stream: bytes):
    """Yield ('lit', byte) or ('ref', length, displacement) the way the BIOS reads the stream."""
    size, p, made = int.from_bytes(stream[1:4], "little"), 4, 0
    while made < size:
        flags = stream[p]
        p += 1
        for bit in range(8):
            if made >= size:
                break
            if flags & (0x80 >> bit):
                length, disp = 3 + (stream[p] >> 4), ((stream[p] & 15) << 8 | stream[p + 1]) + 1
                p += 2
                made += length
                yield "ref", length, disp
            else:
                p += 1
                made += 1
                yield "lit", stream[p - 1]


RAW = [b"", b"a", bytes(1000), bytes(range(256)) * 20, random.Random(7).randbytes(3000), b"abc" * 500,
       b"\x00\x11" * 300 + random.Random(3).randbytes(200)]


@pytest.mark.parametrize("raw", RAW, ids=[f"{len(r)}b" for r in RAW])
def test_lz77_round_trips_and_is_safe_for_the_vram_loader(raw):
    stream = g.lz77_compress(raw)
    assert stream[0] == 0x10 and len(stream) % 4 == 0
    assert g.lz77_decompress(stream) == raw
    # Emerald's loader is the VRAM variant of the BIOS routine, which cannot copy from one byte back
    assert all(t[2] >= 2 for t in _tokens(stream) if t[0] == "ref")


def test_lz77_refuses_a_stream_that_is_not_lz77():
    with pytest.raises(ValueError, match="LZ77"):
        g.lz77_decompress(b"\x11\x04\x00\x00abcd")


# ---- the wordmark and the art -----------------------------------------------------------------------------------------

def test_the_title_carries_no_version_text():
    """Owner decision 2026-10-02: the version lives on the main menu, not the title. Nothing about the title depends on it."""
    import inspect
    assert "version" not in inspect.signature(g.apply_title).parameters and "version" not in inspect.signature(g.title_spans).parameters
    assert list(inspect.signature(g.bg1_band).parameters) == ["first_id", "bank", "cols"]
    assert list(inspect.signature(g.affine_band).parameters) == ["free_ids", "role_index"]
    assert not hasattr(g, "SMALL") and not hasattr(g, "MAX_TEXT_PX") and not hasattr(g, "TEXT_GAP")


def test_art_is_self_consistent():
    assert len(g.LOGO) == 16 and all(len(row) == 72 and set(row) <= set("0123") for row in g.LOGO)
    assert {r for row in g.LOGO for r in row} == set("0123")                    # background, fill, extrusion, outline
    assert g.LOGO_W == 72 and g.LOGO_H == 16
    ink = [x for x in range(g.LOGO_W) if any(row[x] != "0" for row in g.LOGO)]
    assert (ink[0], ink[-1], g.LOGO_INK_CENTRE) == (4, 66, 35)                  # the canvas margins are uneven: centre the INK


# ---- what the measured vanilla titles leave free (no ROM needed) ------------------------------------------------------------

@pytest.mark.parametrize("game", BG1)
def test_bg1_band_fits_what_the_measured_title_leaves_free(game):
    fx, spec = fixture(game), g.TARGETS[game]
    bg = {b["bg"]: b for b in fx["bgs"]}
    assert fx["mode"] == 0
    # BG1 is the Charizard / Venusaur layer: 4bpp, charblock 1, screenblock 30, in front of BG2 / BG3, behind the logo
    assert (bg[1]["bpp8"], bg[1]["charblock"], bg[1]["screenblock"], bg[1]["priority"]) == (0, 1, 30, 1)
    assert (bg[0]["bpp8"], bg[0]["priority"]) == (1, 0)
    first_id = max(bg[1]["nonzero_tiles"]) + 1
    blobs, entries = g.bg1_band(first_id, spec["bank"], spec["cols"])
    occupied = {tuple(cell) for cell in bg[1]["map_cells"]}
    assert not set(entries) & occupied
    assert all(row in g.BG1_ROWS and col < spec["cols"] for col, row in entries)
    # the free columns are measured, not assumed: the first Charizard / Venusaur cell on the band rows
    assert spec["cols"] == min(col for col, row in occupied if row in g.BG1_ROWS)
    assert first_id + len(blobs) <= 512 and not set(range(first_id, first_id + len(blobs))) & set(bg[1]["nonzero_tiles"])
    # the palette bank is indexed by no BG0 pixel (8bpp reads the whole palette) and by no other layer's map
    assert all(index // 16 != spec["bank"] for index in bg[0]["palette_indices_used"])
    for b in fx["bgs"]:
        if b["on"] and not b["bpp8"]:
            assert spec["bank"] not in b["map_palette_banks"], b["bg"]
    # nothing opaque draws in front of the band (BG1 has priority 1): the sprites above it
    left, right, top, bottom = 0, spec["cols"] * 8, 112, 128
    above = [s for s in fx["sprites_xywh_tile_pal_prio_opaque"]
             if s[6] <= 1 and s[7] and s[0] < right and s[0] + s[2] > left and s[1] < bottom and s[1] + s[3] > top]
    assert above == []


@pytest.mark.parametrize("game", BG1)
def test_bg1_wordmark_is_centred_on_press_start_and_nothing_else_is_drawn(game):
    spec = g.TARGETS[game]
    blobs, entries = g.bg1_band(135, spec["bank"], spec["cols"])
    ink = bg1_ink(blobs, entries)
    xs, ys = [p[0] for p in ink], [p[1] for p in ink]
    assert max(col for col, _ in entries) < spec["cols"]
    # the wordmark alone: its ink is 63 x 12 px, centred on PRESS START (x 40-136 -> 88), in the vertical middle of the 16 px band
    assert (max(xs) - min(xs) + 1, max(ys) - min(ys) + 1) == (63, 12)
    assert (min(xs) + max(xs)) / 2 == g.BG1_CENTRE_X
    assert min(ys) - 112 == 127 - max(ys) == 2
    # a wordmark wider than the free columns is refused, not clipped
    with pytest.raises(ValueError, match="does not fit"):
        g.bg1_band(135, spec["bank"], 8)


def test_emerald_band_fits_what_the_measured_title_leaves_free():
    fx, spec = fixture("emerald"), g.TARGETS["emerald"]
    aff = fx["affine"]
    assert fx["mode"] == 1 and aff["screenblock"] == 9 and aff["map_rows_used"] == 8     # the logo is rows 0-7 of the canvas
    bg2 = next(b for b in fx["bgs"] if b["bg"] == 2)
    assert (bg2["bpp8"], bg2["priority"]) == (1, 1)
    # the band's palette indices are colours the logo itself uses, with the colours the patch expects
    for role, (index, colour) in spec["index"].items():
        assert index in aff["palette_indices_used"] and aff["colours"][str(index)] == f"{colour:04X}", role
    free = [t for t in aff["blank_tile_ids"] if t]
    blobs, new_map = g.affine_band(free, {role: index for role, (index, _) in spec["index"].items()})
    assert len(blobs) <= len(free) and set(blobs.values()) <= set(free)
    assert not any(new_map[:g.AFF_STRIP_ROW * 32]) and len(new_map) == (g.AFF_STRIP_ROW + g.AFF_STRIP_ROWS) * 32
    # the ink: canvas x + 29 is the screen, and no opaque sprite sits on it
    ink = [(c * 8 + x + g.AFF_SCREEN_DX, (g.AFF_STRIP_ROW + r) * 8 + y)
           for r in range(g.AFF_STRIP_ROWS) for c in range(32) if new_map[(g.AFF_STRIP_ROW + r) * 32 + c]
           for tile in [next(t for t, i in blobs.items() if i == new_map[(g.AFF_STRIP_ROW + r) * 32 + c])]
           for y in range(8) for x in range(8) if tile[y * 8 + x]]
    assert ink and all(0 <= x < 240 and 0 <= y < 160 for x, y in ink)
    xs, ys = [p[0] for p in ink], [p[1] for p in ink]
    assert (min(xs) + max(xs)) / 2 == 120 and max(xs) - min(xs) + 1 == 63                # the wordmark alone, centred on the screen
    boxes = [s for s in fx["sprites_xywh_tile_pal_prio_opaque"] if s[7]]
    for x, y, w, h, *_ in boxes:
        assert not (x < max(xs) + 1 and x + w > min(xs) and y < max(ys) + 1 and y + h > min(ys)), (x, y, w, h)


# ---- build.py stamps it, and the assets stay out of the payload's way ---------------------------------------------------

def _header(title: str) -> dict:
    text = (ROOT / f"patch/src/trade_targets/{title}.h").read_text()
    return {k: int(v.rstrip("uU"), 0) for k, v in re.findall(r"#define SLINK_TARGET_(\w+) (0x[0-9A-Fa-f]+u?)\b", text)}


@pytest.mark.parametrize("title", ["firered", "leafgreen", "emerald"])
def test_assets_start_past_the_payloads_linker_region(title):
    spec, header = g.TARGETS[title], _header(title)
    ld = (ROOT / f"patch/src/trade_targets/{title}.ld").read_text()
    length = int(re.search(r"LENGTH = (0x[0-9A-Fa-f]+)", ld).group(1), 16)
    assert spec["base"] >= header["CODE_CANDIDATE"] + length
    assert spec["base"] + 0x2000 <= g.ROM_BASE + header["ROM_SIZE"]


def test_radical_red_assets_avoid_the_payload_and_the_battle_calc():
    base = g.TARGETS["radical_red"]["base"]
    payload = (0x08378F70, 0x08378F70 + 0x14638)                  # slink.ld LENGTH 0x14000 inside the 0x14638 free run
    battle_calc = (0x09360000, 0x09361000)                        # patch/src/ADDRESSES.md: the bundled calc's functions
    for lo, hi in (payload, battle_calc):
        assert not (base < hi and base + 0x2000 > lo)
    assert base + 0x2000 <= g.ROM_BASE + 0x2000000


def test_build_py_stamps_the_title_into_every_production_rom():
    text = (ROOT / "patch/tools/build.py").read_text()
    assert '"--version"' in text and "menu_define" in text and "title_version" not in text
    assert text.count("gen3_title.apply_title(") == 2                          # the vanilla production path and RR's
    assert "gen3_title.apply_title(data, title)" in text and 'gen3_title.apply_title(data, "radical_red")' in text
    vanilla = text[text.index("def build_arena_probe"):text.index("def publish_native")]
    assert "if production:" in vanilla and vanilla.index("apply_title") > vanilla.index("if production:")


# ---- the patched assets, against the owner ROMs ----------------------------------------------------------------------------

def test_spans_are_the_whole_difference_and_start_from_what_the_rom_holds(rom):
    target, clean = rom
    spans = g.title_spans(clean, target)
    out = patched(clean, target)
    assert len(out) == len(clean)
    covered = set()
    for off, original, new, why in spans:
        assert clean[off:off + len(original)] == original and len(new) == len(original), why
        assert not covered & set(range(off, off + len(new))), why                # spans are disjoint
        covered |= set(range(off, off + len(new)))
        assert out[off:off + len(new)] == new
    changed = {i for i in range(len(clean)) if clean[i] != out[i]}
    assert changed and changed <= covered
    assert len(changed) > 0.9 * len(covered) - 64                                  # no span is padding
    assert max(covered) < len(clean)


def test_the_band_is_deterministic_and_a_second_pass_is_refused(rom):
    target, clean = rom
    assert patched(clean, target) == patched(clean, target)
    with pytest.raises(ValueError):
        g.title_spans(patched(clean, target), target)


def test_a_rom_of_the_other_layout_is_refused(rom):
    target, clean = rom
    other = "emerald" if target != "emerald" else "firered"
    with pytest.raises(ValueError):
        g.title_spans(clean, other)


@pytest.mark.parametrize("game", BG1)
def test_bg1_assets_are_vanilla_plus_the_band(game):
    clean = owner_rom(game)
    out = patched(clean, game)
    spec = g.TARGETS[game]
    old_tiles = g.lz77_decompress(clean, g._u32(clean, g.BG1_TILES_LIT) - g.ROM_BASE)
    old_map = g.lz77_decompress(clean, g._u32(clean, g.BG1_MAP_LIT) - g.ROM_BASE)
    new_tiles = g.lz77_decompress(out, g._u32(out, g.BG1_TILES_LIT) - g.ROM_BASE)
    new_map = g.lz77_decompress(out, g._u32(out, g.BG1_MAP_LIT) - g.ROM_BASE)
    blobs, entries = g.bg1_band(len(old_tiles) // 32, spec["bank"], spec["cols"])
    assert new_tiles == old_tiles + b"".join(blobs)
    expected = bytearray(old_map)
    for (col, row), entry in entries.items():
        expected[(row * 32 + col) * 2:(row * 32 + col) * 2 + 2] = entry.to_bytes(2, "little")
    assert new_map == bytes(expected)
    # the vanilla assets are untouched where they were, the new ones sit in free space
    assert new_tiles[:len(old_tiles)] == old_tiles
    pals = g._u32(out, g.BG1_PALS_LIT) - g.ROM_BASE
    assert g._u32(out, g.BG1_PALS_RELOAD_LIT) == g._u32(out, g.BG1_PALS_LIT)       # the early-skip reload reads the same asset
    bank = spec["bank"] * 32
    assert out[pals:pals + bank] == clean[pals:pals + bank]
    assert out[pals + bank + 32:pals + g.BG1_PALS_BYTES] == clean[pals + bank + 32:pals + g.BG1_PALS_BYTES]
    assert struct.unpack_from("<4H", out, pals + bank) == spec["colors"] and not any(out[pals + bank + 8:pals + bank + 32])
    assert g._u32(out, g.BG1_TILES_LIT) >= spec["base"]


def test_emerald_logo_renders_identically_and_carries_the_band():
    clean = owner_rom("emerald")
    out = patched(clean, "emerald")
    spec = g.TARGETS["emerald"]

    def load(rom_bytes):
        return (g.lz77_decompress(rom_bytes, g._u32(rom_bytes, g.AFF_GFX_LIT) - g.ROM_BASE),
                g.lz77_decompress(rom_bytes, g._u32(rom_bytes, g.AFF_MAP_LIT) - g.ROM_BASE))

    def render(gfx, amap, rows):
        return {(c * 8 + x, r * 8 + y): gfx[amap[r * 32 + c] * 64 + y * 8 + x]
                for r in rows for c in range(32) for y in range(8) for x in range(8)}

    old_gfx, old_map = load(clean)
    new_gfx, new_map = load(out)
    assert render(old_gfx, old_map, range(8)) == render(new_gfx, new_map, range(8))          # the Pokemon logo, pixel for pixel
    band = {p: v for p, v in render(new_gfx, new_map, range(g.AFF_STRIP_ROW, g.AFF_STRIP_ROW + g.AFF_STRIP_ROWS)).items() if v}
    assert band and set(band.values()) == {index for index, _ in spec["index"].values()}      # fill, extrusion, outline: no text colour
    assert not any(new_map[8 * 32:g.AFF_STRIP_ROW * 32])
    # no tile the logo rows still name was reused for the band
    logo_ids = set(new_map[:256])
    band_ids = {t for t in new_map[g.AFF_STRIP_ROW * 32:] if t}
    assert not logo_ids & band_ids
    assert logo_ids <= {0} | {t for t in range(256) if any(old_gfx[t * 64:(t + 1) * 64])}
    # the palette asset is untouched: the band uses the logo's own colours
    pals = g._u32(out, g.AFF_PALS_LIT) - g.ROM_BASE
    assert out[pals:pals + 0x1E0] == clean[pals:pals + 0x1E0]
