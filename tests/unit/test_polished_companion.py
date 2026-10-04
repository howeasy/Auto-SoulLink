"""Confinement logic of tools/build_polished_companion.py -- pure-function coverage.

Every fixture here is synthetic bytes. No RGBDS, no w64devkit, no ROM build, no network, and no
read of the real Polished Crystal: `verify_overlay` is handed a hand-built 2 MiB image pair and
hand-built symbol dicts, `verify_symbol_scope`/`_symbols` are handed two tiny `.sym` files in
tmp_path, and the UPS round trip runs on a small synthetic base/target pair. Only `build()`
itself needs a toolchain, and it is deliberately not called (see NOT_CALLABLE).

Falsifier discipline: each test's docstring names the mutation it is the anchor for. Tests that
compare a module constant against itself would survive an edit to that constant, so those use
LITERALS, and `test_pinned_constants_match_their_documented_values` is the independent anchor for
every hard-coded offset.

tools/build_polished_companion.py imports the symbol/verify/UPS helpers from
tools/build_gen2_companion.py (which itself re-exports ups_apply/ups_create from
patch/tools/make_ups.py), so those are exercised through the polished module's own namespace.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import build_polished_companion as pc  # noqa: E402
from make_ups import ups_apply, ups_create  # noqa: E402

# NOT_CALLABLE (needs a toolchain / a real source tree; deliberately untested here):
#   * pc.build()         -- tools/build_polished_companion.py:154 (ensure_rgbds/ensure_w64devkit,
#                           export_source, rgblink); the release-ROM re-application check (:197-202)
#                           and the provenance drift comparison (:237-245) live INSIDE it, so
#                           neither is independently reachable without a build.
#   * pc.apply_overlay() -- tools/build_polished_companion.py:86 (reads SRC_DIR and ABI from the
#                           repo and writes into a source export tree; the POLISHED_EDITS anchors
#                           only occur in a real pokecrystal checkout).

# ------------------------------------------------------------------ synthetic overlay fixture

ROM_SIZE = 0x200000        # the image must span bank $7E, where the service links
DELAY = 0x00E0             # ROM0 lead-in rewritten to `call bridge` + 4 nop
BRIDGE = 0x3000            # ROM0 bridge the call targets
BRIDGE_END = 0x3100
SVC = (0x7E, 0x4000)
SVC_END = (0x7E, 0x4010)
# HEADER_CHECKSUMS is range(0x14D, 0x150) -- THREE bytes. A 4th byte assigned into that slice
# would silently extend the bytearray and make every image a different length.
HEADER_BYTES = bytes((0xDE, 0xAD, 0xBE))
SERVICE_BYTES = bytes(range(0x40, 0x50))     # 16 bytes, exactly the SVC..SVC_END span

CLEAN_SYMS = {"DelayFrame": (0x00, DELAY), "wPlayerPartyCount": (0x10, 0x5D00)}
OVERLAY_SYMS = {
    "DelayFrame": (0x00, DELAY),
    "wPlayerPartyCount": (0x10, 0x5D00),     # every clean symbol survives, unmoved
    "SlinkDelayFrameBridge": (0x00, BRIDGE),
    "SlinkDelayFrameBridgeEnd": (0x00, BRIDGE_END),
    "SlinkService": SVC,
    "SlinkServiceEnd": SVC_END,
    "wSlinkMailbox": (0x00, pc.MAILBOX),
}
EMPTY_BANK = slice(pc._flat(pc.SERVICE_BANK, 0x4000), pc._flat(pc.SERVICE_BANK, 0x8000))


def clean_rom() -> bytes:
    """A ROM with a native DelayFrame lead-in and an EMPTY service bank $7E."""
    rom = bytearray(ROM_SIZE)
    rom[EMPTY_BANK] = b"\xff" * 0x4000
    rom[DELAY:DELAY + 7] = pc.DELAY_NATIVE
    return bytes(rom)


def overlay_rom(base: bytes | None = None) -> bytes:
    """base with exactly the four intended edits: lead-in, bridge, service, header checksums."""
    rom = bytearray(clean_rom() if base is None else base)
    rom[DELAY:DELAY + 7] = b"\xcd" + BRIDGE.to_bytes(2, "little") + bytes(4)
    rom[BRIDGE:BRIDGE + 7] = pc.DELAY_NATIVE
    rom[pc._flat(*SVC):pc._flat(*SVC_END)] = SERVICE_BYTES
    rom[pc.HEADER_CHECKSUMS.start:pc.HEADER_CHECKSUMS.stop] = HEADER_BYTES
    return bytes(rom)


def _write_sym(path: Path, mapping: dict) -> Path:
    path.write_text("".join(f"{bank:02X}:{addr:04X} {name}\n" for name, (bank, addr) in mapping.items()),
                    encoding="utf-8", newline="\n")
    return path


# ------------------------------------------------------------------ (e) selfcheck

def test_selfcheck_passes():
    """The module's own assertions hold.

    ANCHOR FOR: a consistent edit to pc._selfcheck (:254-257), e.g. the expected
    `diff_spans(b"abcdef", b"abXdYY")` literal. Note _selfcheck pins only diff_spans and
    moved_symbols; it does NOT cover verify_overlay, which is why the tests below exist.
    """
    pc._selfcheck()


def test_pinned_constants_match_their_documented_values():
    """The hard-coded offsets the confinement gate is built on, pinned to LITERALS.

    This is the independent anchor. The behavioural tests below each compare a module constant
    against something derived from the same constant, so they would survive an edit to it; these
    literals do not.

    ANCHOR FOR: MAILBOX (:63), SERVICE_BANK (:64), DELAY_NATIVE (:82), HEADER_CHECKSUMS (:83) or
    ABI_VERSION (:62). Any one of them changes a byte this test compares.
    """
    assert pc.MAILBOX == 0xC60B
    assert pc.SERVICE_BANK == 0x7E
    # ldh a,[rLY] / ldh [hDelayFrameLY],a / xor a / ldh [hVBlankOccurred],a
    assert bytes.fromhex("f044e0d7afe08f") == pc.DELAY_NATIVE
    assert range(0x14D, 0x150) == pc.HEADER_CHECKSUMS
    assert pc.ABI_VERSION == 3


# ------------------------------------------------------------------ (a) span confinement

def test_a_diff_entirely_inside_the_allowed_spans_is_accepted():
    """Every changed byte falls inside an intended range, so verify_overlay reports and returns.

    ANCHOR FOR: narrowing HEADER_CHECKSUMS (:140) or the DelayFrame/bridge/service entries in
    `allowed` (:137-140) so an intended edit falls outside -- then this raises
    `unexpected change at`.
    """
    report = pc.verify_overlay(clean_rom(), overlay_rom(), CLEAN_SYMS, OVERLAY_SYMS)
    assert len(report) == 4, report
    joined = "\n".join(report)
    assert "DelayFrame lead-in" in joined
    assert "ROM0 bridge" in joined
    assert f"bank ${pc.SERVICE_BANK:02X} service" in joined
    assert "header checksums" in joined


def test_the_report_labels_each_span_with_its_bank_and_width():
    """The report is the operator's evidence of confinement, not just a pass/fail.

    ANCHOR FOR: `{end - start:>3}` -> `{end - start}` at :146, or the bank divisor `0x4000` ->
    `0x2000`; the asserted "(  7 B)" / "bank $00" text goes missing.
    """
    report = pc.verify_overlay(clean_rom(), overlay_rom(), CLEAN_SYMS, OVERLAY_SYMS)
    assert "bank $00 0x000e0-0x000e6 (  7 B) DelayFrame lead-in" in report
    assert f"bank ${pc.SERVICE_BANK:02X} 0x1f8000-0x1f800f ( 16 B)" in "\n".join(report)


@pytest.mark.parametrize("offset,label", [
    (DELAY - 1, "one byte before the lead-in"),
    (DELAY + 7, "one byte after the lead-in"),
    (BRIDGE - 1, "one byte before the ROM0 bridge"),
    (BRIDGE_END, "one byte after the ROM0 bridge"),
    (pc._flat(*SVC) - 1, "one byte before the service"),
    (pc._flat(*SVC_END), "one byte after the service"),
    (pc.HEADER_CHECKSUMS.start - 1, "one byte before the header checksums"),
    (pc.HEADER_CHECKSUMS.stop, "one byte after the header checksums"),
    (0x04000, "far from every span"),
])
def test_one_byte_outside_any_allowed_span_raises(offset, label):
    """THE FAILING CONTROL: a single byte the builder did not intend is refused by name.

    ANCHOR FOR: changing the containment test at :143 from `lo <= start and end <= hi` to
    `lo <= start` (start-only). A span that merely BEGINS inside an allowance then runs past its
    end, and the DELAY+7 / BRIDGE_END / SVC_END / HEADER_CHECKSUMS.stop cases go red.
    """
    base = clean_rom()
    data = bytearray(overlay_rom())
    data[offset] ^= 0xFF
    with pytest.raises(RuntimeError, match=r"unexpected change at 0x"):
        pc.verify_overlay(base, bytes(data), CLEAN_SYMS, OVERLAY_SYMS)


def test_a_size_change_is_refused_before_any_span_is_considered():
    """A different-length ROM is refused outright, not diffed.

    ANCHOR FOR: deleting the length guard at :121-122 -- diff_spans then walks only the common
    prefix and this assertion fails.
    """
    base = clean_rom()
    with pytest.raises(RuntimeError, match="ROM size differs"):
        pc.verify_overlay(base, overlay_rom() + b"\x00", CLEAN_SYMS, OVERLAY_SYMS)


def test_diff_spans_merges_adjacent_runs_and_reports_half_open_ranges():
    """diff_spans is the primitive the confinement loop iterates; its range convention matters.

    ANCHOR FOR: `spans.append((i, j))` -> `spans.append((i, j - 1))` at :112 -- a 7-byte run becomes
    (start, start+6) and every `end <= hi` containment test fails.
    """
    assert pc.diff_spans(b"abcdef", b"abXdYY") == [(2, 3), (4, 6)]
    assert pc.diff_spans(b"abc", b"abc") == []
    assert pc.diff_spans(b"abc", b"xyz") == [(0, 3)]                   # one merged run, not three
    assert pc.diff_spans(b"abXdYY", b"abcdef") == [(2, 3), (4, 6)]      # direction-independent


def test_flat_matches_the_repo_bus_to_file_conversion():
    """Every confinement offset depends on _flat; ROM0 passes through and ROMX is rebased.

    ANCHOR FOR: `- 0x4000` -> `- 0x8000` at :102. Verified: this test goes red, and so does
    test_a_diff_entirely_inside_the_allowed_spans_is_accepted (every ROMX span shifts).
    """
    assert pc._flat(0, 0x0123) == 0x0123
    assert pc._flat(0x7E, 0x4000) == 0x1F8000
    assert pc._flat(0x7E, 0x8000) == 0x1FC000
    assert pc._flat(0x01, 0x4000) == 0x4000


# ------------------------------------------------------------------ (b) DelayFrame lead-in

def test_a_clean_rom_whose_lead_in_is_not_the_pinned_sequence_is_refused():
    """The lead-in check is anchored on the pinned native bytes, not merely "7 bytes differ".

    The fixture flips one byte of whatever lead-in it wrote, so it holds whichever constant the
    builder has. ANCHOR FOR: deleting the `base[delay:delay + 7] != DELAY_NATIVE` guard at
    :127-128 -- then this raises nothing and goes red.
    """
    base = bytearray(clean_rom())
    base[DELAY + 3] ^= 0xFF
    with pytest.raises(RuntimeError, match="clean DelayFrame lead-in differs"):
        pc.verify_overlay(bytes(base), overlay_rom(), CLEAN_SYMS, OVERLAY_SYMS)


def test_a_lead_in_that_is_not_call_bridge_plus_nops_is_refused():
    """The rewritten lead-in must be exactly `call SlinkDelayFrameBridge` + 4 nop.

    ANCHOR FOR: dropping the `+ bytes(4)` term at :129, or comparing only the opcode byte at
    :129 -- a lead-in with fewer nops, or with a different call target, is accepted.
    """
    base = clean_rom()
    data = bytearray(overlay_rom())
    data[DELAY + 3] = 0xC3                        # wrong call target
    with pytest.raises(RuntimeError, match="DelayFrame lead-in is not"):
        pc.verify_overlay(base, bytes(data), CLEAN_SYMS, OVERLAY_SYMS)


def test_a_bridge_not_starting_with_the_native_lead_in_is_refused():
    """The bridge must carry the bytes it replaced, or frame timing changes.

    ANCHOR FOR: deleting the `data[bridge:bridge + 7] != DELAY_NATIVE` guard at :131-132.
    """
    base = clean_rom()
    data = bytearray(overlay_rom())
    data[BRIDGE] ^= 0xFF
    with pytest.raises(RuntimeError, match="bridge does not start with"):
        pc.verify_overlay(base, bytes(data), CLEAN_SYMS, OVERLAY_SYMS)


def test_the_mailbox_must_sit_at_the_pinned_wram0_address():
    """A mailbox symbol at the wrong WRAM0 address is refused.

    The wrong address is a LITERAL (0xC60C), not `pc.MAILBOX + 1`: a shifted fixture would
    otherwise follow the constant and stay green. ANCHOR FOR: deleting the `wSlinkMailbox` check
    at :123-124.
    """
    moved = dict(OVERLAY_SYMS, wSlinkMailbox=(0x00, 0xC60C))
    with pytest.raises(RuntimeError, match="wSlinkMailbox at"):
        pc.verify_overlay(clean_rom(), overlay_rom(), CLEAN_SYMS, moved)


def test_the_service_bank_must_be_empty_in_the_clean_rom():
    """Linking into a bank the clean ROM already uses would silently overwrite game code.

    ANCHOR FOR: removing the `not empty` term at :135 (`if svc_bank != SERVICE_BANK or not empty`
    -> `if svc_bank != SERVICE_BANK`).
    """
    base = bytearray(clean_rom())
    base[EMPTY_BANK.start] = 0x12                 # bank $7E no longer empty
    base = bytes(base)
    with pytest.raises(RuntimeError, match="must be empty in the clean ROM"):
        pc.verify_overlay(base, overlay_rom(base), CLEAN_SYMS, OVERLAY_SYMS)


def test_the_service_must_link_in_the_pinned_bank():
    """A service in any other bank is refused.

    The other bank is a LITERAL (0x70), not `pc.SERVICE_BANK - 1`, so this stays honest if
    SERVICE_BANK is edited. ANCHOR FOR: deleting the `svc_bank != SERVICE_BANK` term at :135.
    """
    elsewhere = dict(OVERLAY_SYMS, SlinkService=(0x70, 0x4000))
    with pytest.raises(RuntimeError, match="service must link in bank"):
        pc.verify_overlay(clean_rom(), overlay_rom(), CLEAN_SYMS, elsewhere)


# ------------------------------------------------------------------ (c) moved symbols

def test_one_moved_clean_symbol_is_refused_by_verify_symbol_scope(tmp_path):
    """The panel=False scope: no pre-existing symbol may move, Polished has no panel bank.

    ANCHOR FOR: `if not movable and current != location:` at build_gen2_companion.py:673 ->
    `if False:`.
    """
    clean = _write_sym(tmp_path / "clean.sym", CLEAN_SYMS)
    overlay = _write_sym(tmp_path / "overlay.sym", dict(CLEAN_SYMS, wPlayerPartyCount=(0x10, 0x5D04)))
    with pytest.raises(RuntimeError, match="moved outside panel bank 4"):
        pc.verify_symbol_scope(clean, overlay, panel=False)


def test_a_deleted_clean_symbol_is_refused(tmp_path):
    """A symbol the clean build had and the overlay lost is a hard error, not a relocation.

    ANCHOR FOR: dropping the `current is None` clause at build_gen2_companion.py:670.
    """
    clean = _write_sym(tmp_path / "clean.sym", CLEAN_SYMS)
    overlay = _write_sym(tmp_path / "overlay.sym", {"DelayFrame": (0x00, DELAY)})
    with pytest.raises(RuntimeError, match="missing or outside allowed bank"):
        pc.verify_symbol_scope(clean, overlay, panel=False)


def test_added_only_symbols_pass_verify_symbol_scope(tmp_path):
    """The companion may add symbols freely -- that is how the bridge and service get addresses.

    ANCHOR FOR: iterating `new.items()` instead of `old.items()` at build_gen2_companion.py:668 --
    every added-only overlay would then be rejected.
    """
    clean = _write_sym(tmp_path / "clean.sym", CLEAN_SYMS)
    added = {k: v for k, v in OVERLAY_SYMS.items() if k not in CLEAN_SYMS}
    overlay = _write_sym(tmp_path / "overlay.sym", {**CLEAN_SYMS, **added})
    pc.verify_symbol_scope(clean, overlay, panel=False)      # must not raise


def test_panel_true_permits_only_bank_4_movement(tmp_path):
    """Documents the flag the polished builder passes as False, so the panel carve-out is pinned
    by a test rather than by a comment. Bank 4 moves; bank $10 does not.

    ANCHOR FOR: `location[0] == 4` at build_gen2_companion.py:669 -> `True`.
    """
    start_names = ("SlinkStartMenuEntry", "SlinkMenuString", "SlinkMenuDesc")
    panel = dict.fromkeys(start_names, (4, 16400))
    clean = _write_sym(tmp_path / "clean.sym", {"InBank4": (0x04, 0x4000), "InBank10": (0x10, 0x5000)})
    ok = _write_sym(tmp_path / "ok.sym", {**panel, "InBank4": (0x04, 0x4010), "InBank10": (0x10, 0x5000)})
    pc.verify_symbol_scope(clean, ok, panel=True)             # bank 4 may move
    bad = _write_sym(tmp_path / "bad.sym",
                     {**panel, "InBank4": (0x04, 0x4010), "InBank10": (0x10, 0x5010)})
    with pytest.raises(RuntimeError, match="moved outside panel bank 4"):
        pc.verify_symbol_scope(clean, bad, panel=True)


def test_moved_symbols_reports_only_the_changed_ones():
    """The builder logs this list; it must name the moved symbol and both locations.

    ANCHOR FOR: swapping `old.items()` for `new.items()` at :151 -- added symbols then appear.
    """
    assert pc.moved_symbols(CLEAN_SYMS, OVERLAY_SYMS) == []
    assert pc.moved_symbols(CLEAN_SYMS, dict(CLEAN_SYMS, wPlayerPartyCount=(0x10, 0x5D04))) == [
        "wPlayerPartyCount: (16, 23808) -> (16, 23812)"]


def test_symbols_rejects_a_duplicate_and_an_empty_sym_file(tmp_path):
    """_symbols is the parser both verify_overlay and verify_symbol_scope trust.

    ANCHOR FOR: dropping the `if name in symbols: raise` guard at build_gen2_companion.py:508 --
    a duplicate then silently keeps the last definition.
    """
    dup = tmp_path / "dup.sym"
    dup.write_text("00:0040 DelayFrame\n00:0050 DelayFrame\n", encoding="utf-8", newline="\n")
    with pytest.raises(RuntimeError, match="duplicate symbol"):
        pc._symbols(dup)
    empty = tmp_path / "empty.sym"
    empty.write_text("# only a comment\n", encoding="utf-8", newline="\n")
    with pytest.raises(RuntimeError, match="no link symbols"):
        pc._symbols(empty)


# ------------------------------------------------------------------ (d) UPS round trip

def test_ups_round_trip_is_byte_exact_on_a_synthetic_pair():
    """The builder asserts `ups_apply(base, ups) == data` at :195; this pins the primitive.

    ANCHOR FOR: swapping the source and target arguments in the skew arithmetic of
    patch/tools/make_ups.py ups_create -- the round trip stops being the identity.
    """
    base = bytes((i * 7 + 3) & 0xFF for i in range(1024))
    target = bytearray(base)
    target[100:110] = b"SLINKV3\0\0\0"
    target[900] = 0x00
    patch = ups_create(base, bytes(target))
    assert patch.startswith(b"UPS1")
    assert ups_apply(base, patch) == bytes(target)
    assert hashlib.sha1(ups_apply(base, patch)).digest() == hashlib.sha1(bytes(target)).digest()


def test_a_corrupted_ups_raises_instead_of_producing_a_rom():
    """A flipped patch byte must fail the CRC, not yield a plausible-looking ROM.

    ANCHOR FOR: deleting the CRC check in patch/tools/make_ups.py ups_apply.
    """
    base = bytes(range(256)) * 4
    target = bytearray(base)
    target[512:520] = b"CHANGED!"
    patch = bytearray(ups_create(base, bytes(target)))
    patch[len(patch) // 2] ^= 0xFF
    with pytest.raises(ValueError):
        ups_apply(base, bytes(patch))


def test_applying_the_patch_to_the_wrong_base_rom_raises():
    """The polished build also applies the UPS to a cached release ROM (:200); wrong base fails.

    ANCHOR FOR: weakening the source CRC comparison in patch/tools/make_ups.py ups_apply.
    """
    base = bytes((i * 13) & 0xFF for i in range(2048))
    other = bytes((i * 29 + 7) & 0xFF for i in range(2048))
    target = bytearray(base)
    target[1000:1004] = b"\x01\x02\x03\x04"
    patch = ups_create(base, bytes(target))
    with pytest.raises(ValueError):
        ups_apply(other, patch)


def test_a_non_ups_blob_is_rejected():
    """A ROM or a random file handed to ups_apply is refused by magic.

    ANCHOR FOR: changing the magic check at patch/tools/make_ups.py:85 from an equality test
    against b"UPS1" to a prefix test.
    """
    with pytest.raises(ValueError, match="not a UPS1 patch"):
        ups_apply(bytes(2048), bytes(2048))
