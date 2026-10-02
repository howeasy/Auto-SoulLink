"""Gen 2 title band: a SoulLink logo and the version on Crystal / Gold / Silver (patch/gen2/src/title.asm)."""

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
    version = set(range(0x60 + tiles, 0x60 + tiles + 8))                       # SlinkTitleVersionRow in title.asm
    assert logo | version <= set(range(0x60, 0x7F)) and not ((logo | version) & _refs("crystal"))


@pytest.mark.parametrize("title", ["gold", "silver"])
def test_gold_silver_ids_are_never_drawn_on_the_title(title):
    inc = (SRC / "title_rows_gs.inc").read_text()
    assert (SRC / "title_logo_gs.2bpp").stat().st_size == 16 * 16
    logo = {i for row in _row_ids(inc, 4) for i in row}
    version = {0x60, 0x61, 0x62, 0x63, 0x51}                                    # SlinkTitleVersionRow in title.asm
    assert logo == set(range(0x70, 0x80)) and not ((logo | version) & _refs(title))


def test_title_asm_agrees_with_the_art_and_the_measured_ids():
    asm = (SRC / "title.asm").read_text()
    assert "db $60, $61, $62, $63, $51" in asm                                  # the Gold/Silver version ids
    assert "vTiles2 tile $60" in asm and "vTiles2 tile $51" in asm and "decoord 3, 10" in asm
    assert "ld a, 6" in asm and asm.count("ld a, 1 ;") + asm.count("ld a, 1\n") >= 4   # palette 6 (Crystal), palette 1 (G/S)


def test_version_tiles_are_drawn_in_each_games_palette():
    crystal = builder.title_version_tiles("pokecrystal", "v0.3.0-dev")
    assert len(crystal) == 8 * 16 and all(crystal[i + 1] == 0 for i in range(0, len(crystal), 2))   # colour 1 on 0: low plane only
    assert any(crystal[0::2])
    gold = builder.title_version_tiles("pokegold", "v0.3.0-dev")
    assert len(gold) == 5 * 16 and all(gold[i + 1] == 0xFF for i in range(0, len(gold), 2))        # colour 3 on 2: high plane solid
    assert gold == builder.title_version_tiles("pokegold", "v0.3.0")                               # the suffix does not fit and is dropped


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
