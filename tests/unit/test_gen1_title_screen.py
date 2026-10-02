"""Gen 1 title screen: a SoulLink logo joins the "Red Version" line; the version is on the main menu; graphics stay vanilla."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

from patch.gen1.tools import inject, manifest, title_art as art, title_screen as ts

ROOT = Path(__file__).resolve().parents[2]
# the copyright/GAME FREAK tiles the title's bottom line draws from, and LoadCopyrightTiles +
# CopyrightTextString (the credits' copyright text): all must stay byte-identical
VANILLA_RANGES = ((0x4538, 0x4588), (0x120C8, 0x12288))


@pytest.fixture(autouse=True)
def isolate_data_dir():
    yield


@pytest.fixture(params=("red", "blue"))
def clean(request):
    path = ROOT / f"patch/build/gen1_{request.param}.gb"
    if not path.is_file():
        pytest.skip(f"clean Gen 1 {request.param} dump absent: {path}")
    data = path.read_bytes()
    assert hashlib.sha1(data).hexdigest() == manifest.ROMS[request.param][1]
    return data


@pytest.fixture(params=("red", "blue"))
def vram(request):
    """The settled vanilla title as measured on a running emulator (lua/tests/probe_gen1_title_vram.lua, run on the clean dump)."""
    return json.loads((ROOT / f"tests/fixtures/gen1/title_vram_{request.param}.json").read_text())


@pytest.mark.parametrize("version, shown", [
    ("dev", "SoulLink dev"), ("v0.2.6", "SoulLink v0.2.6"), ("v1.10.3", "SoulLink v1.10.3"), ("v0.2.6-dev", "SoulLink v0.2.6-dev")])
def test_menu_text_is_the_games_own_tile_ids(version, shown):
    """Gen 1's charset: A=$80, a=$A0, 0=$F6, space=$7F, '-'=$E3, '.'=$E8; $50 ends the string."""
    glyph = {" ": 0x7F, "-": 0xE3, ".": 0xE8}
    glyph.update({chr(ord("A") + i): 0x80 + i for i in range(26)})
    glyph.update({chr(ord("a") + i): 0xA0 + i for i in range(26)})
    glyph.update({str(d): 0xF6 + d for d in range(10)})
    text = ts.menu_text(version)
    assert text == bytes(glyph[c] for c in shown) + bytes((0x50,))
    assert min(text[:-1]) >= 0x60 and len(text) - 1 <= 20                   # PlaceString treats everything below $60 as a command


def test_the_charmap_agrees_with_the_roms_own_strings(clean):
    """manifest.SLINK_TEXT and the ROM's own "POKeDEX@" use the same mapping menu_text relies on."""
    assert clean[0x0718F:0x0718F + 8] == bytes.fromhex("8f8e8aba83849750")
    assert ts.menu_text("dev")[:2] == bytes((0x92, 0xAE))                    # "So": S=$92 like manifest.SLINK_TEXT, o=$AE


@pytest.mark.parametrize("bad", ["0.2.6", "v1.2", "v0.2.6-rc1", "v100.200.300-dev", "v100.200.300", "", "DEV"])
def test_bad_versions_are_refused(bad):
    with pytest.raises(ValueError):
        ts.check_version(bad)


def test_ids_are_free_on_the_measured_vanilla_title(vram):
    """Derived from the committed measurement, not restated: a free id has no tile data and is on neither BG map."""
    nonzero = {i for i, c in enumerate(vram["ids_00_7f_nonzero"]) if c == "1"}
    nonzero |= {0x80 + i for i, c in enumerate(vram["ids_80_ff_nonzero"]) if c == "1"}
    referenced = {i for m in ("map0", "map1") for row in vram[m] for i in row}
    taken = nonzero | referenced
    logo = set(art.ROW0) | set(art.ROW1)
    assert not (logo & taken)
    # the band's cells themselves are blank on the vanilla title, outside the game's own line
    row8, row9 = vram["map0"][8], vram["map0"][9]
    assert set(row9) == {0x7F} and set(row8[:7]) == {0x7F} and set(row8[15:]) == {0x7F}


def test_art_is_self_consistent():
    assert len(art.TILES) == art.TILE_COUNT * 16 and len(art.ROW0) == len(art.ROW1) == 9
    assert set(art.ROW0) | set(art.ROW1) <= set(range(art.FIRST_ID, art.FIRST_ID + art.TILE_COUNT))
    assert min(art.ROW0 + art.ROW1) >= 0x60                  # PlaceString treats everything below $60 as a command


class _Sm83:
    """Just the opcodes the hand-assembled routines use; anything else is a test failure."""

    def __init__(self, code: bytes):
        self.code = code
        self.r = {"b": 0, "c": 0, "d": 0, "e": 0, "h": 0, "l": 0}
        self.calls = []

    def pair(self, hi, lo):
        return self.r[hi] << 8 | self.r[lo]

    def run(self):
        pc = 0
        while True:
            op = self.code[pc]
            if op in (0x01, 0x11, 0x21):                       # ld bc/de/hl, nn
                hi, lo = {0x01: "bc", 0x11: "de", 0x21: "hl"}[op]
                self.r[lo], self.r[hi] = self.code[pc + 1], self.code[pc + 2]
                pc += 3
            elif op == 0xCD:                                   # call nn: record the register state
                target = self.code[pc + 1] | self.code[pc + 2] << 8
                self.calls.append((target, self.pair("h", "l"), self.pair("d", "e"), self.pair("b", "c")))
                pc += 3
            elif op == 0xC9:                                   # ret
                return
            else:
                raise AssertionError(f"unexpected opcode {op:#04x} at {pc}")


def test_routine_does_what_the_band_needs():
    """Executes the hand-assembled bytes and checks every call, not just the ends."""
    cpu = _Sm83(ts._code())
    cpu.run()
    a = ts._addr
    assert cpu.calls == [
        (ts.COPY_VIDEO_DATA, 0x9000 + art.FIRST_ID * 16, a(ts.TILES_OFFSET), 0x3F00 | art.TILE_COUNT),
        (ts.PLACE_STRING, ts.WTILEMAP + 8 * 20 + ts.LINE_X, a(ts.RV_OFFSET), cpu.calls[1][3]),
        (ts.PLACE_STRING, ts.WTILEMAP + 8 * 20 + ts.LOGO_X, a(ts.ROW0_OFFSET), cpu.calls[2][3]),
        (ts.PLACE_STRING, ts.WTILEMAP + 9 * 20 + ts.LOGO_X, a(ts.ROW1_OFFSET), cpu.calls[3][3]),
    ]


def test_menu_stub_makes_the_original_call_then_prints_the_version_row():
    cpu = _Sm83(ts._menu_stub())
    cpu.run()
    assert [c[0] for c in cpu.calls] == [ts.UPDATE_SPRITES, ts.PLACE_STRING]
    assert cpu.calls[1][1:3] == (ts.WTILEMAP + ts.MENU_ROW * 20, ts.MENU_TEXT_ADDR)
    assert ts.MENU_SITE_BEFORE == bytes((0xCD,)) + ts.UPDATE_SPRITES.to_bytes(2, "little")


def test_routine_calls_the_pret_addresses():
    sym = (ROOT / "data/pret/pokered.sym").read_text()

    def addr(name, bank="00"):
        return int(re.search(rf"^{bank}:([0-9a-f]{{4}}) {re.escape(name)}$", sym, re.M).group(1), 16)

    assert (addr("CopyVideoData"), addr("PlaceString"), addr("Bankswitch"), addr("wTileMap"), addr("UpdateSprites")) == (
        ts.COPY_VIDEO_DATA, ts.PLACE_STRING, ts.BANKSWITCH, ts.WTILEMAP, ts.UPDATE_SPRITES)
    assert addr("PrintGameVersionOnTitleScreen", "01") == ts.SITE
    assert addr("VersionOnTitleScreenText", "01") == ts.VERSION_TEXT_SITE
    # MainMenu.next2: ld hl, wStatusFlags5 (3) / res BIT_NO_TEXT_DELAY, [hl] (2) / call UpdateSprites
    assert addr("MainMenu.next2", "01") == ts.MENU_CONTEXT_SITE
    assert ts.MENU_SITE == ts.MENU_CONTEXT_SITE + 5
    # _TitleScroll: ld h, d / ld l, $48 (the immediate is SCROLL_SITE)
    assert 0x4000 * 0x0D + (addr("_TitleScroll", "0d") - 0x4000) + 0x11 == ts.SCROLL_SITE
    code = ts._code()
    assert len(code) <= ts.RV_OFFSET - ts.CODE_OFFSET and code[-1] == 0xC9


def test_menu_stub_sits_in_the_free_tail_after_the_joypad_stub(clean):
    assert ts.MENU_STUB_ADDR == manifest.JOYPAD_STUB_ADDR + len(manifest.JOYPAD_STUB_AFTER)
    end = ts.MENU_TEXT_ADDR + len(ts.menu_text("v0.3.0-dev"))
    assert end <= 0x4000 and not any(clean[ts.MENU_STUB_ADDR:0x4000])         # the tail is zero padding up to the bank edge


def test_no_span_overlaps_another(clean):
    spans = manifest.MENU_PATCHES + ts.title_spans(clean, "v0.3.0-dev")
    ranges = sorted((off, off + len(new)) for off, _before, new, _why in spans)
    assert all(a_end <= b_start for (_s, a_end), (b_start, _e) in zip(ranges, ranges[1:]))


def test_spans_apply_to_both_clean_roms(clean):
    for off, before, after, why in ts.title_spans(clean, "v0.2.6"):
        assert clean[off:off + len(before)] == before, why
        assert len(before) == len(after)


def test_injected_rom_keeps_the_games_own_line_and_vanilla_graphics(clean):
    out = inject.inject(clean, version="v1.2.3")
    line = clean[ts.VERSION_TEXT_SITE:ts.VERSION_TEXT_SITE + ts.VERSION_TEXT_LEN]
    assert out[ts.RV_OFFSET:ts.RV_OFFSET + len(line)] == line               # Red and Blue keep their own words
    assert out[ts.SCROLL_SITE] == 0x50                                      # the swap no longer scrolls band row 9
    for lo, hi in VANILLA_RANGES:
        assert out[lo:hi] == clean[lo:hi]


def test_injected_rom_prints_the_version_on_the_main_menu_not_the_title(clean):
    out = inject.inject(clean, version="v1.2.3")
    assert out[ts.MENU_SITE:ts.MENU_SITE + 3] == bytes((0xCD,)) + ts.MENU_STUB_ADDR.to_bytes(2, "little")
    assert out[ts.MENU_STUB_ADDR:ts.MENU_STUB_ADDR + ts.MENU_STUB_LEN] == ts._menu_stub()
    text = ts.menu_text("v1.2.3")
    assert out[ts.MENU_TEXT_ADDR:ts.MENU_TEXT_ADDR + len(text)] == text
    # no pixel font on the title any more: bank $3F holds the logo tiles and nothing after them
    assert not any(out[ts.TILES_OFFSET + len(art.TILES):ts.TILES_OFFSET + 0x300])


def test_a_rom_whose_title_line_is_not_plain_tile_ids_is_refused_cleanly(clean):
    for bad in (0x4F, 0x50, 0x00):                  # <LINE>, an early terminator, a zero: PlaceString would run commands
        rom = bytearray(clean)
        rom[ts.VERSION_TEXT_SITE + 2] = bad
        with pytest.raises(inject.InjectError):
            inject.inject(bytes(rom))


def test_a_rom_whose_main_menu_is_not_the_one_we_read_is_refused_cleanly(clean):
    rom = bytearray(clean)
    rom[ts.MENU_CONTEXT_SITE + 1] ^= 0xFF
    with pytest.raises(inject.InjectError):
        inject.inject(bytes(rom))


# ---- pureRGB: the same band, built from source into the overlay (patch/gen1/purergb/overlay/title_band.asm) ----

OVERLAY = ROOT / "patch/gen1/purergb/overlay"
PURE_TITLES = ("purered", "pureblue", "puregreen")


@pytest.mark.parametrize("title", PURE_TITLES)
def test_pure_ids_are_free_on_the_measured_vanilla_style_title(title):
    """$60-$79 hold no tile data and appear on neither BG map of the clean pureRGB title (flag off)."""
    d = json.loads((ROOT / f"tests/fixtures/gen1/title_vram_{title}.json").read_text())
    nonzero = {i for i, c in enumerate(d["ids_00_7f_nonzero"]) if c == "1"}
    referenced = {i for m in ("map0", "map1") for row in d[m] for i in row}
    band = set(range(0x60, 0x60 + art.TILE_COUNT))
    assert max(band) < 0x7A                                      # the blinking mon starts at $7A
    assert not (band & (nonzero | referenced))
    assert set(d["map0"][9]) == {0x7F}                           # the band's second row is blank on the vanilla title


def test_pure_overlay_assets_are_the_generated_art():
    assert (OVERLAY / "title_logo.2bpp").read_bytes() == art.TILES
    inc = (OVERLAY / "title_band_rows.inc").read_text()
    for name, row in (("SlinkTitleLogoRow0", art.ROW0), ("SlinkTitleLogoRow1", art.ROW1)):
        ids = re.search(rf"{name}:\n\tdb ([^\n]+)", inc).group(1).split(",")
        assert ids == [f"${0x60 + b - art.FIRST_ID:02X}" for b in row] + ["$50"]
    assert f"DEF SLINK_TITLE_LOGO_TILES EQU {art.TILE_COUNT}" in inc


def test_pure_hooks_leave_the_pure_title_alone_and_move_the_swap_scroll():
    sys.path.insert(0, str(ROOT / "tools"))
    import apply_purergb_overlay as apply_overlay
    edits = {(f, old): new for f, old, new in apply_overlay.EDITS}
    head = edits[("engine/movie/title.asm", "PrintGameVersionOnTitleScreen:\n")]
    assert "call IsPureTitleScreenEnabled" in head and "jr nz, .slinkVanillaPrint" in head
    assert head.index("jr nz") < head.index("farcall SlinkTitleBand")             # the band is skipped on the Pure title
    assert "ld l, $50" in edits[("engine/movie/title2.asm", "\tld h, d\n\tld l, $48\n")]
    assert "SLink title band" in apply_overlay.ROMX_SECTIONS


def _refs(title, pure=False):
    d = json.loads((ROOT / f"tests/fixtures/gen1/title_refs_{title}{'_pure' if pure else ''}.json").read_text())
    return set(d["referenced"])


@pytest.mark.parametrize("title", PURE_TITLES)
def test_pure_band_ids_are_never_drawn_on_the_vanilla_style_title(title):
    """Sampled every 4 frames from the start of the title to idle, both BG maps' visible cells."""
    band = set(range(0x60, 0x60 + art.TILE_COUNT))
    assert not (band & _refs(title))


@pytest.mark.parametrize("title", PURE_TITLES)
def test_pure_line_ids_are_never_drawn_on_the_pure_title(title):
    asm = (OVERLAY / "title_band.asm").read_text()
    ids = [int(x.strip().lstrip("$"), 16) for x in re.search(r"SlinkTitleLineRow:\n\tdb ([^\n]+)", asm).group(1).split(",")]
    assert ids[-1] == 0x50 and len(ids) - 1 == int(re.search(r"SLINK_PURE_LINE_CELLS EQU (\d+)", asm).group(1))
    assert not (set(ids[:-1]) & _refs(title, pure=True)) and min(ids[:-1]) >= 0x60


def test_pure_line_is_cleared_before_the_pointing_tiles_overwrite_its_ids():
    sys.path.insert(0, str(ROOT / "tools"))
    import apply_purergb_overlay as apply_overlay
    edits = {(f, old): new for f, old, new in apply_overlay.EDITS}
    clear = edits[("engine/movie/title.asm", '\t; load the "player pointing" tiles in\n')]
    assert clear.index("farcall SlinkTitleLinePureClear") < clear.index("; load the")
    draw = edits[("engine/movie/title.asm", "\tcall PureTitleScreenVersionAnimation\n\tjr .skipOldTitleStuff1\n")]
    assert "farcall SlinkTitleLinePure " in draw


PURE_LINE = (                       # "SoulLink" in the PureRed banner's bold dark-red lettering, 6 tiles = 48 x 8 pixels
    "................................................",
    ".....RRRR...........RR.RR....RR......RR.........",
    "....RR.....RRR.RR.R.RR.RR.......RRR..RR.R.......",
    ".....RRR..RR.R.RR.R.RR.RR....RR.RR.R.RRR........",
    ".......RR.RR.R.RR.R.RR.RR....RR.RR.R.RR.R.......",
    "....RRRR...RRR..RRR.RR.RRRRR.RR.RR.R.RR.R.......",
    "................................................",
    "................................................",
)


def test_pure_line_is_soullink_in_the_banners_lettering():
    data = (OVERLAY / "title_line.2bpp").read_bytes()
    assert len(data) == 6 * 16
    rows = []
    for y in range(8):
        line = ""
        for cell in range(6):
            lo, hi = data[cell * 16 + y * 2], data[cell * 16 + y * 2 + 1]
            for dx in range(8):
                v = (lo >> (7 - dx) & 1) | (hi >> (7 - dx) & 1) << 1
                assert v in (0, 2), "the banner's letters are colour index 2 on white, nothing else"
                line += ".R"[v == 2]
        rows.append(line)
    assert tuple(rows) == PURE_LINE
    # no version on the Pure title any more: it is on the main menu
    asm = (OVERLAY / "title_band.asm").read_text()
    assert "SLINK_PURE_LINE_CELLS EQU 6" in asm and "title_line" in asm


@pytest.mark.parametrize("title", PURE_TITLES)
def test_pure_line_cells_are_blank_under_the_banner_on_the_measured_pure_title(title):
    asm = (OVERLAY / "title_band.asm").read_text()
    x = int(re.search(r"SLINK_PURE_LINE_X EQU (\d+)", asm).group(1))
    n = int(re.search(r"SLINK_PURE_LINE_CELLS EQU (\d+)", asm).group(1))
    m = json.loads((ROOT / f"tests/fixtures/gen1/title_vram_{title}_pure.json").read_text())["map0"]
    assert [m[9][c] for c in range(x, x + n)] == [0x7F] * n                     # row 9 is empty space under the banner


def test_pure_line_types_in_one_cell_at_a_time():
    """The PureRed banner above reveals itself letter by letter; the line follows suit instead of popping in."""
    asm = (OVERLAY / "title_band.asm").read_text()
    body = asm[asm.index("SlinkTitleLinePure::"):asm.index("SlinkTitleLinePureClear::")]
    assert ".reveal" in body and "call DelayFrames" in body and "PlaceString" not in body.replace("no PlaceString", "")
    assert "ld b, SLINK_PURE_LINE_CELLS" in body and body.index("DelayFrames") < body.index("jr nz, .reveal")
    delay = body[body.index("push hl"):body.index("dec b")]
    assert delay.count("push") == 3 and delay.count("pop") == 3            # hl (cursor), de (source), bc (count) survive the wait
