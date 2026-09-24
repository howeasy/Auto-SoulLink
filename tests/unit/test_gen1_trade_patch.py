"""Red/Blue trade patch: clean-byte admission, linked spans, panel coexistence."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from patch.gen1.tools import manifest
from tools._build_tools_bootstrap import ensure_rgbds

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "patch/gen1/build"
SOURCE = ROOT / "patch/gen1/src"
TARGETS = ("red", "blue")
SPAN_SYMBOLS = (
    ("SlinkForeground", "SlinkTradeServiceEnd", 0x4500, 369),
    ("SlinkTradeApply", "SlinkTradeApplyEnd", 0x4800, 656),
    ("SlinkReceptionist", "SlinkReceptionistEnd", 0x4C00, 1260),
    ("SlinkTradeUIWaitReleased", "SlinkTradeUIEnd", 0x5400, 539),
    ("SlinkPartnerPrompt", "SlinkPartnerPromptEnd", 0x5800, 438),
)


@pytest.fixture(autouse=True)
def isolate_data_dir():
    """Override repository's disk-creating state fixture in this patch-only suite."""
    yield


def _clean(key: str) -> bytes:
    path = ROOT / f"patch/build/gen1_{key}.gb"
    if not path.is_file():
        pytest.skip(f"clean Gen 1 {key} dump absent: {path}")
    data = path.read_bytes()
    assert len(data) == 0x100000
    assert hashlib.sha1(data).hexdigest() == manifest.ROMS[key][1]
    return data


def _symbols(path: Path) -> dict[str, tuple[int, int]]:
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+):([0-9a-fA-F]+) (\S+)", line)
        if match:
            result[match[3]] = int(match[1], 16), int(match[2], 16)
    return result


def _rgbds() -> tuple[Path, str]:
    try:
        directory = Path(ensure_rgbds())
    except (OSError, RuntimeError) as exc:
        pytest.skip(f"rgbasm not on PATH and bundled RGBDS unavailable: {exc}")
    suffix = ".exe" if os.name == "nt" else ""
    if not (directory / ("rgbasm" + suffix)).is_file():
        pytest.skip("rgbasm not on PATH or in bundled RGBDS")
    return directory, suffix


@pytest.fixture(scope="module")
def built() -> dict[str, bytes]:
    _rgbds()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, str(ROOT / "patch/gen1/tools/build.py")],
                            cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "assembled 6582 bytes" in result.stderr
    return {key: (BUILD / f"slink_{key}.gb").read_bytes() for key in TARGETS}


@pytest.mark.parametrize("key", TARGETS)
def test_clean_dump_contains_three_exact_before_patterns(key):
    data = _clean(key)
    expected = {
        0x0001: manifest.TRADE_BRIDGE_BEFORE,
        0x20B7: manifest.TRADE_DELAY_BEFORE,
        0x29C3: manifest.TRADE_DISPATCH_BEFORE,
    }
    assert len(expected[0x0001]) == len(manifest.TRADE_BRIDGE_AFTER) == 32
    for offset, original in expected.items():
        assert data[offset:offset + len(original)] == original, (key, hex(offset))
    # pret/home/header.asm:3-38 declares unused RST8..RST30 vector bodies.
    for vector in range(0, 0x38, 8):
        assert data[vector] == 0xFF and data[vector + 1:vector + 8] == bytes(7)


def test_defs_match_committed_red_and_blue_symbols_and_pret_tables():
    defs = (SOURCE / "trade_defs.inc").read_text(encoding="utf-8")
    assert "data/pret/pokered.sym:" in defs
    red = _symbols(ROOT / "data/pret/pokered.sym")
    blue = _symbols(ROOT / "data/pret/pokeblue.sym")
    project_or_derived = {
        "SLINK_TRADE_BANK", "SLINK_YELLOW", "SLINK_TRADE_UI",
        "SLINK_TRADE_MUSIC_BANK", "SLINK_TRADE_MUSIC_ID",
        "SlinkDelayFrameHalt", "SlinkOverworldReturn", "SlinkOverworldLessReturn",
        "SLINK_SFX_REQUEST", "SLINK_SFX_SAVE",
    }
    definitions = re.findall(r"^DEF (\w+) EQU \$?([0-9A-Fa-f]+)\s*; ([^\n]+)", defs, re.M)
    assert len(definitions) == 146
    values = {name: int(hex_value, 16) for name, hex_value, _citation in definitions}
    assert values["SLINK_TRADE_BANK"] == 0x3F
    assert values["SLINK_YELLOW"] == 0 and values["SLINK_TRADE_UI"] == 1
    assert values["SLINK_TRADE_MUSIC_BANK"] == red["Music_SafariZone"][0] == 2
    assert values["SLINK_TRADE_MUSIC_ID"] == (
        red["Music_SafariZone"][1] - red["SFX_Headers_1"][1]) // 3 == 0xE5
    for bank in ("_1", "_3"):  # the two overworld audio banks; the trade never runs in battle
        assert values["SLINK_SFX_SAVE"] == (
            red["SFX_Save" + bank][1] - red["SFX_Headers" + bank][1]) // 3 == 0xB6
    assert values["SlinkDelayFrameHalt"] == red["DelayFrame.halt"][1]
    assert values["SlinkOverworldReturn"] == red["OverworldLoop"][1] + 3
    assert values["SlinkOverworldLessReturn"] == red["OverworldLoopLessDelay"][1] + 3
    for name, hex_value, citation in definitions:
        value = int(hex_value, 16)
        assert citation and ("sym:" in citation or "pret/" in citation or
                             "trade_" in citation)
        if name in project_or_derived:
            continue
        if name in red and name in blue:
            assert red[name][1] == blue[name][1] == value
        elif name.endswith("Bank"):
            base = name[:-4]
            assert base in red and base in blue, name
            assert red[base][0] == blue[base][0] == value
        else:
            pytest.fail(f"unresolved trade DEF {name}")
    clean = _clean("red")
    order_bank, order_address = red["PokedexOrder"]
    start = order_bank * 0x4000 + order_address % 0x4000
    species = [0] + [int(bool(dex)) for dex in clean[start:start + 190]]
    assert len(species) == 191
    match = re.search(r"MACRO slink_species_table\s+db ([0-9,]+)\s+ENDM", defs)
    assert match and [int(value) for value in match[1].split(",")] == species
    # The name alphabet is selected from pinned pret/constants/charmap.asm,
    # not an ASCII range. Match every one of the 256 gate bits.
    charmap = (ROOT / ".cache/pret/pokered/constants/charmap.asm").read_text(encoding="utf-8")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 é():;[]'-?!.♂♀×/,¥")
    allowed.update(("<PK>", "<MN>", "<DOT>", "<ED>", "'d", "'l", "'s", "'t", "'v", "'r", "'m"))
    glyphs = {int(value, 16) for glyph, value in re.findall(
        r'^\s*charmap\s+"([^"\n]+)",\s*\$([\da-fA-F]+)', charmap, re.M) if glyph in allowed}
    expected = [int(i in glyphs) for i in range(256)]
    match = re.search(r"MACRO slink_name_table\s+db ([0-9,]+)\s+ENDM", defs)
    assert match and [int(value) for value in match[1].split(",")] == expected
    assert red["DelayFrame.halt"] == (0, 0x20B3)
    assert red["OverworldLoop"][1] + 3 == 0x0402
    assert red["OverworldLoopLessDelay"][1] + 3 == 0x0405


def test_text_include_matches_pret_sources():
    pret_src = ROOT / ".cache/pret/pokered"
    if not pret_src.is_dir():
        pytest.skip(f"{pret_src} not present (set SLINK_PRET_SRC or clone pret/pokered there)")
    text = (SOURCE / "pret_text.inc").read_text(encoding="utf-8")
    for relative in ("constants/charmap.asm", "macros/const.asm", "macros/scripts/text.asm"):
        upstream = (pret_src / relative).read_text(encoding="utf-8")
        assert upstream.rstrip("\n") in text


def test_linked_trade_symbols_sizes_bridge_and_dispatch(built):
    symbols = _symbols(BUILD / "slink.sym")
    image = (BUILD / "slink_stub.gb").read_bytes()
    assert symbols["SlinkDelayFrameBridge"] == (0, 1)
    assert symbols["SlinkDelayFrameBridgeEnd"] == (0, 0x21)
    assert image[1:0x21] == manifest.TRADE_BRIDGE_AFTER
    assert symbols["SlinkSfxService"][0] == 0x3F and symbols["SlinkSfxServiceEnd"][1] <= 0x4100
    assert symbols["SlinkForeground"] == (0x3F, 0x4500)
    for start_name, end_name, start, length in SPAN_SYMBOLS:
        assert symbols[start_name] == (0x3F, start)
        assert symbols[end_name] == (0x3F, start + length)
        flat = 0xFC000 + (start - 0x4000)
        assert any(image[flat:flat + length])
        for key in TARGETS:
            assert built[key][flat:flat + length] == image[flat:flat + length]
    original = _symbols(ROOT / "data/pret/pokered.sym")
    hook = bytes((0xC3, symbols["SlinkDelayFrameBridge"][1], 0))
    receptionist = symbols["SlinkReceptionist"][1]
    bankswitch = original["Bankswitch"][1]
    displacement = original["HoldTextDisplayOpen"][1] - (0x29C3 + 10)
    dispatch = bytes((0x21, receptionist & 255, receptionist >> 8, 0x06, 0x3F,
                      0xCD, bankswitch & 255, bankswitch >> 8, 0x18, displacement))
    assert hook == manifest.TRADE_DELAY_AFTER
    assert dispatch == manifest.TRADE_DISPATCH_AFTER


@pytest.mark.parametrize("key", TARGETS)
def test_clean_rom_receives_only_declared_spans_and_full_bank(built, key):
    pristine, patched = _clean(key), built[key]
    assert len(pristine) == len(patched) == 0x100000
    assert patched[1:0x21] == manifest.TRADE_BRIDGE_AFTER
    # the RST slots past the shorter bridge keep the clean ROM's rst $38 traps
    assert patched[0x21:0x38] == pristine[0x21:0x38] == bytes(7) + bytes([0xFF]) + bytes(7) + bytes([0xFF]) + bytes(7)
    assert patched[0x20B7:0x20BA] == manifest.TRADE_DELAY_AFTER
    assert patched[0x29C3:0x29CD] == manifest.TRADE_DISPATCH_AFTER
    assert patched[0x0100:0x0150] == pristine[0x0100:0x0150]
    permitted = set(range(manifest.INJECT_OFFSET, manifest.INJECT_OFFSET + manifest.BANK_SIZE))
    permitted.update(range(manifest.HOOK_SITE, manifest.HOOK_SITE + len(manifest.HOOK_ORIGINAL)))
    for offset, before, after, _why in manifest.MENU_PATCHES:
        assert len(before) == len(after)
        assert pristine[offset:offset + len(before)] == before
        assert patched[offset:offset + len(after)] == after
        permitted.update(range(offset, offset + len(after)))
    assert all(index in permitted for index, (a, b) in enumerate(zip(pristine, patched, strict=True))
               if a != b)
    assert patched[manifest.INJECT_OFFSET:manifest.INJECT_OFFSET + len(
        (ROOT / "patch/gen1/dist/slink_bank3f.bin").read_bytes())] == (
            ROOT / "patch/gen1/dist/slink_bank3f.bin").read_bytes()


def test_panel_payload_is_bit_identical_to_panel_only_link(built):
    rgbds, suffix = _rgbds()
    panel_obj = BUILD / "trade_test_panel_only.o"
    panel_image = BUILD / "trade_test_panel_only.gb"
    subprocess.run([str(rgbds / ("rgbasm" + suffix)), "-o", str(panel_obj),
                    str(SOURCE / "slink.asm")], cwd=ROOT, capture_output=True, check=True)
    subprocess.run([str(rgbds / ("rgblink" + suffix)), "-p", "0x00", "-o",
                    str(panel_image), str(panel_obj)], cwd=ROOT, capture_output=True, check=True)
    panel = panel_image.read_bytes()
    combined = (BUILD / "slink_stub.gb").read_bytes()
    assert panel[0xFC000:0xFC500] == combined[0xFC000:0xFC500]
    assert panel[0xFC500:0xFC600] == bytes(0x100)
    assert built["red"][0xFC000:0xFC500] == combined[0xFC000:0xFC500]
    assert built["red"][0xFC500:0xFC600] == combined[0xFC500:0xFC600]


def test_red_blue_trade_bank_bytes_identical(built):
    red, blue = built["red"], built["blue"]
    assert red[0xFC500:0xFDA00] == blue[0xFC500:0xFDA00]
    assert red[0xFC000:0x100000] == blue[0xFC000:0x100000]
