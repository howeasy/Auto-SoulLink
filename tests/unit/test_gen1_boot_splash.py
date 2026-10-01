"""Gen 1 boot splash: a white SLink screen replaces the copyright screen; title and credits stay vanilla."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from patch.gen1.tools import boot_splash as bs, inject, manifest, splash_art as art

ROOT = Path(__file__).resolve().parents[2]
# LoadCopyrightTiles + CopyrightTextString (the credits' copyright text) and the copyright/GAME FREAK
# tiles the title screen's bottom line is drawn from: all must stay byte-identical.
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


def _slot(tile_id: int) -> int:
    """Index in the tile blob of a tile id: the blob is loaded linearly from $8800, so $80.. then $00.."""
    return tile_id - 0x80 if tile_id >= 0x80 else tile_id + 128


def _version_row(tmap: bytes) -> str:
    first, end = art.VERSION_COLS
    row = tmap[art.VERSION_ROW * 20 + first:art.VERSION_ROW * 20 + end]
    back = {v: k for k, v in art.GLYPH_IDS.items()}
    return "".join(back[i] for i in row if i != art.BLANK_ID)


@pytest.mark.parametrize("version", ["dev", "v0.2.6", "v1.10.3-dev"])
def test_version_row_reads_back_and_nothing_else_changes(version):
    tmap = bs.tilemap(version)
    assert _version_row(tmap) == version
    first, end = art.VERSION_COLS
    lo, hi = art.VERSION_ROW * 20 + first, art.VERSION_ROW * 20 + end
    assert tmap[:lo] == art.MAP[:lo] and tmap[hi:] == art.MAP[hi:]


@pytest.mark.parametrize("bad", ["0.2.6", "v1.2", "v0.2.6-rc1", "v100.200.300-dev", "", "DEV"])
def test_bad_versions_are_refused(bad):
    with pytest.raises(ValueError):
        bs.check_version(bad)


def test_art_is_self_consistent():
    assert len(art.TILES) == art.TILE_COUNT * 16 and art.TILE_COUNT <= 255
    loaded = {0x80 + k if k < 128 else k - 128 for k in range(art.TILE_COUNT)}
    assert set(art.MAP) <= loaded and set(art.GLYPH_IDS.values()) <= loaded
    assert 0x7F not in loaded                                   # never touch the textbox blank
    b = _slot(art.BLANK_ID) * 16
    assert art.TILES[b:b + 16] == bytes(16)
    assert all(any(art.TILES[_slot(i) * 16:][:16]) for i in art.GLYPH_IDS.values())


def test_routine_calls_the_pret_addresses():
    sym = (ROOT / "data/pret/pokered.sym").read_text()

    def addr(name):
        return int(re.search(rf"^00:([0-9a-f]{{4}}) {name}$", sym, re.M).group(1), 16)

    assert (addr("ClearScreen"), addr("CopyVideoData"), addr("CopyData")) == (
        bs.CLEAR_SCREEN, bs.COPY_VIDEO_DATA, bs.COPY_DATA)
    code = bs._code()
    assert len(code) == 30 and code[3] == 0xCD and code[-3] == 0xC3
    assert bs.SITE_AFTER[1] == bs.BANK == 0x3F and bs.CODE_OFFSET == 0xFE000


def test_spans_apply_to_both_clean_roms(clean):
    for off, before, after, why in bs.splash_spans("v0.2.6"):
        assert clean[off:off + len(before)] == before, why
        assert len(before) == len(after)


def test_injected_rom_shows_the_version_and_keeps_title_and_credits_vanilla(clean):
    out = inject.inject(clean, version="v1.2.3")
    assert _version_row(out[bs.MAP_OFFSET:bs.MAP_OFFSET + 360]) == "v1.2.3"
    assert out[bs.TILES_OFFSET:bs.TILES_OFFSET + len(art.TILES)] == art.TILES
    assert out[bs.SITE:bs.SITE + 5] == bs.SITE_AFTER
    for lo, hi in VANILLA_RANGES:
        assert out[lo:hi] == clean[lo:hi]
