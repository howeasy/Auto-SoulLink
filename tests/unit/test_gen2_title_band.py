"""Gen 2 title band: a SoulLink wordmark on Crystal / Gold / Silver (patch/gen2/src/title.asm); the version is on the main menu."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "patch/gen2/src"
sys.path.insert(0, str(ROOT / "tools"))
import build_gen2_companion as builder  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_data_dir():
    yield


def _refs(title: str) -> set[int]:
    """BG tile ids ever drawn on the visible title (both maps, every 4 frames from the end of the intro)."""
    return set(json.loads((ROOT / f"tests/fixtures/gen2/title_refs_{title}.json").read_text())["referenced"])


def _row_ids(inc: str, count: int) -> list[list[int]]:
    return [[int(x.strip().lstrip("$"), 16) for x in re.search(rf"SlinkTitleLogoRow{r}:\n\tdb ([^\n]+)", inc).group(1).split(",")]
            for r in range(count)]


def test_crystal_ids_are_never_drawn_on_the_title():
    inc = (SRC / "title_rows_crystal.inc").read_text()
    tiles = int(re.search(r"SLINK_TITLE_LOGO_TILES EQU (\d+)", inc).group(1))
    assert (SRC / "title_logo_crystal.2bpp").stat().st_size == tiles * 16
    logo = {i for row in _row_ids(inc, 2) for i in row}
    assert logo <= set(range(0x60, 0x7F)) and not (logo & _refs("crystal"))
    assert all(len(row) == 9 for row in _row_ids(inc, 2))


@pytest.mark.parametrize("title", ["gold", "silver"])
def test_gold_silver_ids_are_never_drawn_on_the_title(title):
    inc = (SRC / "title_rows_gs.inc").read_text()
    assert (SRC / "title_logo_gs.2bpp").stat().st_size == 16 * 16
    logo = {i for row in _row_ids(inc, 2) for i in row}
    assert logo == set(range(0x70, 0x80)) and not (logo & _refs(title))
    assert all(len(row) == 8 for row in _row_ids(inc, 2))                      # the same wordmark as Crystal's, 8 tiles wide


@pytest.mark.parametrize("title", ["gold", "silver"])
def test_gold_silver_band_cells_are_plain_sky_on_the_measured_title(title):
    """The wordmark takes rows 7-8 (tiles 6-13), directly under the subtitle on row 6; nothing is drawn there but flat sky."""
    m = json.loads((ROOT / f"tests/fixtures/gen2/title_vram_{title}.json").read_text())["map0"]
    cells = {m[row][col] for row in (7, 8) for col in range(6, 14)}
    assert len(cells) == 1, cells
    subtitle = {m[6][col] for col in range(20)}
    assert len(subtitle) == 20                                                  # row 6 is the logo's last row and the subtitle


def test_crystal_band_cells_are_blank_on_the_measured_title():
    """The wordmark takes rows 10-11 (tiles 6-14), directly under the CRYSTAL VERSION pill on row 9."""
    m = json.loads((ROOT / "tests/fixtures/gen2/title_vram_crystal.json").read_text())["map0"]
    blank = {m[row][col] for row in (10, 11) for col in range(6, 15)}
    assert len(blank) == 1, blank


def test_title_asm_agrees_with_the_art_and_the_measured_ids():
    asm = (SRC / "title.asm").read_text()
    for crystal in ("decoord 6, 10", "decoord 6, 11", "hlbgcoord 6, 10", "hlbgcoord 6, 11"):
        assert crystal in asm, crystal                                          # Crystal: rows 10-11, tiles 6-14
    for gs in ("debgcoord 6, 7", "debgcoord 6, 8", "hlbgcoord 6, 7", "hlbgcoord 6, 8", "ld a, 1 ; the Pokemon logo"):
        assert gs in asm, gs                                                    # the Gold/Silver band: rows 7-8, palette 1
    assert "ld a, 6" in asm and asm.count("ld a, 1\n\tldh [rVBK], a") == 2   # palette 6 (Crystal); both bank-1 switches
    # the version lives on the main menu now (version.asm), not in this file or its art
    assert "VERSION" not in asm.replace("CRYSTAL VERSION", "") and "title_version" not in asm
    assert not hasattr(builder, "title_version_tiles")


def test_the_title_hook_is_a_single_same_size_call_rewrite():
    assert builder.TITLE_ANCHOR == "\tcall EnableLCD\n"
    for repo, path in (("pokecrystal", ROOT / ".cache/gen2-build/pokecrystal"), ("pokegold", ROOT / ".cache/gen2-build/pokegold")):
        source = path / "engine/movie/title.asm"
        if not source.is_file():
            pytest.skip(f"pinned {repo} checkout absent")
        text = source.read_text(encoding="utf-8")
        assert text.count(builder.TITLE_ANCHOR) == 1


def test_the_overlay_plan_carries_the_title_with_its_repo_art():
    crystal = {name: src.name for name, src, _inc in builder.overlay_plan("pokecrystal", SRC)}
    gold = {name: src.name for name, src, _inc in builder.overlay_plan("pokegold", SRC)}
    assert crystal["title_logo.2bpp"] == "title_logo_crystal.2bpp" and gold["title_logo.2bpp"] == "title_logo_gs.2bpp"
    assert crystal["title_rows.inc"] == "title_rows_crystal.inc" and gold["title_rows.inc"] == "title_rows_gs.inc"
    assert list(crystal)[-1] == "title.asm" == list(gold)[-1]


# ---- Crystal's entrance shear ---------------------------------------------------------------------------------------------------

def test_the_shear_widening_covers_the_whole_band():
    """The title scrolls the BG up 8 pixels, so 80 sheared lines are map rows 1-10; the band is rows 10-11."""
    lines_per_row, scroll = 8, 8
    old_last_row = (80 + scroll) // lines_per_row - 1
    new_last_row = (builder.SHEAR_LINES + scroll) // lines_per_row - 1
    assert old_last_row == 10 and new_last_row == 11                            # the band's second row joins the entrance
    assert builder.SHEAR_LINES % 2 == 0                                          # the effect alternates lines


def test_shear_edits_are_exact_single_replacements_on_the_pinned_crystal_source():
    checkout = ROOT / ".cache/gen2-build/pokecrystal"
    if not (checkout / "engine/menus/intro_menu.asm").is_file():
        pytest.skip("pinned pokecrystal checkout absent")
    for name, edits in builder.TITLE_SHEAR_EDITS.items():
        text = (checkout / name).read_text(encoding="utf-8")
        for old, new in edits:
            assert text.count(old) == 1 and old != new, (name, old)
    title = builder._title_text(checkout, "pokecrystal")[1]
    assert "ld b, 88 / 2" in title and "wLYOverrides + 88" in title and "wLYOverrides + 80" not in title
    assert "call SlinkTitleBridge" in title
    entrance = builder._title_entrance_text(checkout)[1]
    assert "ld bc, 8 * 11" in entrance and "ld b, 8 * 11 / 2" in entrance and "8 * 10" not in entrance.split("TitleScreenEntrance:")[1][:900]


def test_gold_and_silver_get_no_shear_edit():
    checkout = ROOT / ".cache/gen2-build/pokegold"
    if not (checkout / "engine/movie/title.asm").is_file():
        pytest.skip("pinned pokegold checkout absent")
    text = builder._title_text(checkout, "pokegold")[1]
    assert "wLYOverrides + 88" not in text and "call SlinkTitleBridge" in text


def test_a_source_that_is_not_the_pinned_one_is_refused(tmp_path):
    (tmp_path / "engine/movie").mkdir(parents=True)
    (tmp_path / "engine/movie/title.asm").write_text("\tcall EnableLCD\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="exactly once"):
        builder._title_text(tmp_path, "pokecrystal")


def _entrance_routine(ly: int, height: int, count: int) -> bytes:
    """TitleScreenEntrance's two operands in context: `ld bc, height` and `ld b, count / ld hl, wLYOverrides + 1 / ld [hli], a ...`."""
    return (bytes((0xFA, 0x00, 0xFF, 0xD6, 0x04, 0x01)) + height.to_bytes(2, "little") + bytes((0xCD, 0x12, 0x34))
            + bytes((0x06, count, 0x21)) + (ly + 1).to_bytes(2, "little") + bytes((0x22, 0x23, 0x05, 0x20, 0xFB, 0xC9)))


def test_the_entrance_verifier_accepts_exactly_the_two_operand_changes():
    ly = 0xD000
    old = {"TitleScreenEntrance": (5, 0x4100), "TitleScreenTimer": (5, 0x4140), "wLYOverrides": (1, ly)}
    base_routine = _entrance_routine(ly, 80, 40)
    new_routine = _entrance_routine(ly, builder.SHEAR_LINES, builder.SHEAR_LINES // 2)
    at = 5 * 0x4000 + 0x4100 - 0x4000
    size = 0x40

    def rom(routine: bytes) -> bytearray:
        data = bytearray(6 * 0x4000)
        data[at:at + len(routine)] = routine
        return data

    builder.verify_title_entrance(bytes(rom(base_routine)), bytes(rom(new_routine)), old)
    assert len(base_routine) < size
    stray = rom(new_routine)
    stray[at + len(new_routine) - 1] ^= 1
    with pytest.raises(RuntimeError, match="changed more than"):
        builder.verify_title_entrance(bytes(rom(base_routine)), bytes(stray), old)
    with pytest.raises(RuntimeError, match="changed more than"):
        builder.verify_title_entrance(bytes(rom(base_routine)), bytes(rom(base_routine)), old)   # the widening is required
    with pytest.raises(RuntimeError, match="exactly once"):
        builder.verify_title_entrance(bytes(rom(new_routine)), bytes(rom(new_routine)), old)      # not the native routine
