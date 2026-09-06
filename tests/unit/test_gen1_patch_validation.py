"""Mutations that used to pass the canonical ROM/manifest gate."""
import importlib.util
import json
from pathlib import Path

import pytest

from tools import gen1_patch_validation as validation
from tools.verify_gen1_rom_layout import _rows_for

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def manifest():
    spec = importlib.util.spec_from_file_location(
        "test_manifest_geometry", ROOT / "patch/gen1/tools/manifest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def red():
    path = ROOT / "patch/build/gen1_red.gb"
    if not path.exists():
        pytest.skip("user-supplied clean Red ROM required")
    return path.read_bytes()


@pytest.fixture
def symbols():
    return json.loads((ROOT / "data/pret_rom_syms.json").read_text())["pokered"]["symbols"]


@pytest.mark.parametrize("span,reason", [
    ((0x100, b"\0", b"\1", "header"), "protected"),
    ((0x10, b"\0", b"\1\2", "resize"), "resizing"),
    ((0x100000, b"\0", b"\1", "outside"), "outside ROM"),
    ((-1, b"\0", b"\1", "negative"), "invalid"),
    ((0x3FFF, b"\0\0", b"\1\1", "crossing"), "crosses"),
])
def test_bad_manifest_geometry_fails_before_injection(manifest, span, reason):
    manifest.MENU_PATCHES = [span]
    with pytest.raises(ValueError, match=reason):
        manifest.validated_spans(b"\xc9")


def test_overlapping_spans_fail(manifest):
    manifest.MENU_PATCHES = [(0x200, b"00", b"11", "one"),
                             (0x201, b"00", b"11", "two")]
    with pytest.raises(ValueError, match="overlapping"):
        manifest.validated_spans(b"\xc9")


def test_canonical_gate_does_not_accept_parseable_modified_rom(red):
    changed = bytearray(red)
    changed[0xF0000] = 1
    rows = _rows_for("red", bytes(changed))
    assert any(name == "exact supported canonical ROM" and not ok for name, ok, _ in rows)


def test_canonical_gate_rejects_wrong_title(red):
    rows = _rows_for("blue", red)
    assert any(name == "exact supported canonical ROM" and not ok for name, ok, _ in rows)


def test_source_anchor_drift_rejected_even_when_rom_bytes_match(red, symbols, manifest):
    symbols["DrawStartMenu"] += 1
    with pytest.raises(ValueError, match="does not resolve"):
        validation.verify_anchors(red, symbols, manifest)


def test_cross_bank_target_drift_rejected(red, symbols, manifest):
    symbols["StartMenu_Option"] += 0x10000
    with pytest.raises(ValueError, match="caller bank"):
        validation.verify_anchors(red, symbols, manifest)


def test_unclassified_patch_destination_rejected(red, symbols, manifest):
    manifest.MENU_PATCHES.append((0x400, red[0x400:0x401], b"\0", "unmapped"))
    with pytest.raises(ValueError, match="missing source label"):
        validation.verify_anchors(red, symbols, manifest)


def test_clean_anchors_are_source_backed(red, symbols, manifest):
    assert "verified" in validation.verify_anchors(red, symbols, manifest)
    assert "RET" in validation.verify_future_hook_anchors("red", red, symbols)


@pytest.mark.parametrize("address", [0x20B9, 0x29BF, 0xFC000])
def test_service_trade_prerequisites_detect_damaged_code_or_space(red, symbols, address):
    changed = bytearray(red)
    changed[address] ^= 1
    with pytest.raises(ValueError):
        validation.verify_future_hook_anchors("red", bytes(changed), symbols)


@pytest.mark.parametrize("symbol", [-1, 0x8000, 0x010001, 0x018000, 0x404000])
def test_invalid_banked_symbols_refused(symbol):
    with pytest.raises(ValueError, match="bank-qualified"):
        validation.flat(symbol)


def test_unknown_external_assembly_address_cannot_escape_the_gate(symbols):
    with pytest.raises(ValueError, match="no canonical symbol"):
        validation.verify_assembly_references("DEF Mystery EQU $C000\n", symbols, {})


@pytest.mark.parametrize("source", [
    "DEF Evil EQU $C000 ; trailing comment\nld [Evil], a\n",
    "DEF\tEvil EQU $C000\nld [Evil], a\n",
    "DEF Evil EQU $BFFF + 1\n",
    "DEF SLINK_UNKNOWN EQU $C000\n",
    "call z, $1234\n",
    "jp nz, Unknown\n",
    "ld [$D000], a\n",
    "ld hl, $D000\n",
    "ld [49152], a\n",
    "ld hl, 49152\n",
    "ldh [255], a\n",
])
def test_alternative_assembly_spellings_cannot_bypass_address_validation(symbols, source):
    with pytest.raises(ValueError):
        validation.verify_assembly_references(source, symbols, {})
