"""Gen 1 title screen: a SoulLink logo and the version join the 'Red Version' line; graphics stay vanilla."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from patch.gen1.tools import inject, manifest, title_art as art, title_screen as ts

ROOT = Path(__file__).resolve().parents[2]
# the copyright/GAME FREAK tiles the title's bottom line draws from, and LoadCopyrightTiles +
# CopyrightTextString (the credits' copyright text): all must stay byte-identical
VANILLA_RANGES = ((0x4538, 0x4588), (0x120C8, 0x12288))
# BG tile ids the vanilla title leaves free, measured on a running Red (VRAM dump of the settled title)
FREE_IDS = set(range(0x4F, 0x60)) | set(range(0x6A, 0x7F))


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


def _bitmap(tiles: bytes) -> list[str]:
    """The 8 version cells as 8 rows of 64 characters."""
    rows = []
    for y in range(8):
        bits = ""
        for t in range(ts.VER_CELLS):
            b = tiles[t * 16 + y * 2]
            assert tiles[t * 16 + y * 2 + 1] == b                       # colour 3 only
            bits += format(b, "08b")
        rows.append(bits.replace("0", ".").replace("1", "#"))
    return rows


@pytest.mark.parametrize("version", ["dev", "v0.2.6", "v1.10.3", "v0.2.6-dev"])
def test_version_line_draws_the_text(version):
    rows = _bitmap(ts._version_tiles(version))
    glyphs = [[format(r, "05b").replace("0", ".").replace("1", "#") for r in art.SMALL[c]] for c in version]
    # glyph rows land one pixel down, so row 0 is blank; a one pixel gap separates glyphs
    expect = [".".join(g[y - 1] if y else "." * 5 for g in glyphs) for y in range(8)]
    width = len(version) * 6 - 1
    x = (64 - width) // 2
    assert [r[x:x + width] for r in rows] == expect
    assert all(set(r[:x] + r[x + width:]) <= {"."} for r in rows)       # nothing else drawn


@pytest.mark.parametrize("bad", ["0.2.6", "v1.2", "v0.2.6-rc1", "v100.200.300-dev", "", "DEV"])
def test_bad_versions_are_refused(bad):
    with pytest.raises(ValueError):
        ts.check_version(bad)


def test_art_ids_are_free_and_not_control_codes():
    assert len(art.TILES) == art.TILE_COUNT * 16 and art.ROW0 and len(art.ROW0) == len(art.ROW1) == 9
    used = set(art.ROW0) | set(art.ROW1)
    assert used <= set(range(art.FIRST_ID, art.FIRST_ID + art.TILE_COUNT))
    assert used <= FREE_IDS and set(range(ts.VER_FIRST_ID, ts.VER_FIRST_ID + ts.VER_CELLS)) <= FREE_IDS
    assert min(used) >= 0x60                    # PlaceString treats everything below $60 as a control code


def test_routine_calls_the_pret_addresses():
    sym = (ROOT / "data/pret/pokered.sym").read_text()

    def addr(name, bank="00"):
        return int(re.search(rf"^{bank}:([0-9a-f]{{4}}) {name}$", sym, re.M).group(1), 16)

    assert (addr("CopyVideoData"), addr("PlaceString"), addr("Bankswitch"), addr("wTileMap")) == (
        ts.COPY_VIDEO_DATA, ts.PLACE_STRING, ts.BANKSWITCH, ts.WTILEMAP)
    assert addr("PrintGameVersionOnTitleScreen", "01") == ts.SITE
    assert addr("VersionOnTitleScreenText", "01") == ts.VERSION_TEXT_SITE
    code = ts._code()
    assert len(code) <= ts.RV_OFFSET - ts.CODE_OFFSET and code[-1] == 0xC9


def test_spans_apply_to_both_clean_roms(clean):
    for off, before, after, why in ts.title_spans(clean, "v0.2.6"):
        assert clean[off:off + len(before)] == before, why
        assert len(before) == len(after)


def test_injected_rom_keeps_the_games_own_line_and_vanilla_graphics(clean):
    out = inject.inject(clean, version="v1.2.3")
    line = clean[ts.VERSION_TEXT_SITE:ts.VERSION_TEXT_SITE + ts.VERSION_TEXT_LEN]
    assert out[ts.RV_OFFSET:ts.RV_OFFSET + len(line)] == line               # Red and Blue keep their own words
    assert _bitmap(out[ts.VTILES_OFFSET:ts.VTILES_OFFSET + ts.VER_CELLS * 16]) == _bitmap(ts._version_tiles("v1.2.3"))
    for lo, hi in VANILLA_RANGES:
        assert out[lo:hi] == clean[lo:hi]
