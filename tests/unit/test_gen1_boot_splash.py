"""Gen 1 boot splash: the copyright lines say SLink, the title screen stays vanilla."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from patch.gen1.tools import boot_splash as bs, inject, manifest

ROOT = Path(__file__).resolve().parents[2]
TILE_BASE = 0x4000 * 4 + (0x60C8 - 0x4000)           # NintendoCopyrightLogoGraphics, bank 4
TILE_END = 0x4000 * 4 + (0x6288 - 0x4000)            # end of GameFreakLogoGraphics: the title screen's tiles


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


def _screen(string: bytes) -> list[str]:
    """What the three lines read as: tile id -> glyph, $7F -> space."""
    assert string.endswith(bytes([bs.END])) and string.count(bytes([bs.NEXT])) == 2
    body = string.split(bytes([bs.END]))[0]
    return ["".join(" " if i == bs.SPACE else bs.GLYPHS[i - bs.FIRST_TILE] for i in ln).strip()
            for ln in body.split(bytes([bs.NEXT]))]


@pytest.mark.parametrize("version", ["dev", "v0.2.6", "v1.1.3-dev"])
def test_text_reads_back_and_fits(version):
    s = bs.text(version)
    assert len(s) == len(bs.TEXT_BEFORE)
    assert _screen(s) == [f"SLINK {version}", *bs.LINES]
    assert all(i == bs.SPACE or bs.FIRST_TILE <= i < bs.FIRST_TILE + len(bs.GLYPHS)
               for i in s.replace(bytes([bs.NEXT]), b"").rstrip(bytes([bs.END])))


@pytest.mark.parametrize("bad", ["0.2.6", "v1.2", "v0.2.6-rc1", "v100.200.300-dev", "", "DEV"])
def test_bad_versions_are_refused(bad):
    with pytest.raises(ValueError):
        bs.check_version(bad)


def test_spans_apply_to_both_clean_roms(clean):
    for off, before, after, why in bs.splash_spans(clean, "v0.2.6"):
        assert clean[off:off + len(before)] == before, why
        assert len(before) == len(after)


def test_tiles_are_the_roms_own_font(clean):
    t = bs.tiles(clean)
    s_row = (ord("S") - ord("A")) * 8
    font = clean[bs.FONT_OFFSET:bs.FONT_OFFSET + 0x400]
    assert t[:16] == b"".join(bytes((r, r)) for r in font[s_row:s_row + 8])
    assert len(t) // 16 == len(bs.GLYPHS)


def test_injected_rom_shows_the_version_and_keeps_the_title_tiles(clean):
    out = inject.inject(clean, version="v1.2.3")
    off = bs.TEXT_SITE
    assert _screen(out[off:off + len(bs.TEXT_BEFORE)])[0] == "SLINK v1.2.3"
    # the title screen draws its bottom line from these tiles: untouched
    assert out[TILE_BASE:TILE_END] == clean[TILE_BASE:TILE_END]
    assert out[bs.TILES_OFFSET:bs.TILES_OFFSET + len(bs.GLYPHS) * 16] == bs.tiles(clean)


def test_glyph_tiles_match_known_font_rows(clean):
    """Independent of _charcode: the rows below were read from the clean font by eye."""
    t = bs.tiles(clean)

    def tile(c):
        i = bs.GLYPHS.index(c)
        return t[i * 16:(i + 1) * 16:2]

    assert tile("S") == bytes.fromhex("7884807c02827c00")
    assert tile("0") == bytes.fromhex("00384cc6c6643800")
    assert tile("-") == bytes.fromhex("000000007e000000")
