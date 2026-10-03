"""patch/tools/rom_identity.py: a version stamp changes the exact hash and nothing the canonical identity sees."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "patch" / "tools"))
import rom_identity as ri  # noqa: E402


def _rom(version: bytes, gb: bool = True) -> bytes:
    """A 16 KiB image whose version field holds `version` (the whole text, prefix included when given)."""
    rom = bytearray(range(256)) * 64            # 16 KiB of structure
    field = version + b"\x50" + bytes(ri.FIELD - len(version) - 1)
    rom[0x3F00:0x3F00 + ri.FIELD] = field
    if gb:                                        # a global checksum that really sums everything else
        rom[0x14E] = rom[0x14F] = 0
        total = sum(rom) & 0xFFFF
        rom[0x14E], rom[0x14F] = total >> 8, total & 0xFF
    return bytes(rom)


SLOT = {"offset": 0x3F00, "length": ri.FIELD}


def test_a_stamp_moves_the_exact_hash_and_not_the_canonical_one():
    dev, rel = _rom(b"SoulLink dev"), _rom(b"SoulLink v0.3.0")
    assert hashlib.sha1(dev).hexdigest() != hashlib.sha1(rel).hexdigest()
    assert ri.canonical_sha1(dev, [SLOT], gb=True) == ri.canonical_sha1(rel, [SLOT], gb=True)
    ri.assert_version_only_difference(dev, rel, [SLOT], gb=True)


def test_the_gb_checksum_is_masked_only_when_asked():
    dev, rel = _rom(b"SoulLink dev"), _rom(b"SoulLink v0.3.0")
    assert ri.canonical_sha1(dev, [SLOT]) != ri.canonical_sha1(rel, [SLOT])        # checksum still differs


def test_the_wordmark_in_the_field_is_part_of_the_identity():
    """Review finding: masking the whole field would let a wordmark / charmap change ride as a version stamp."""
    dev = _rom(b"SoulLink dev")
    swapped = bytearray(_rom(b"SoulLink v0.3.0"))
    assert ri.canonical_sha1(dev, [SLOT], gb=True) == ri.canonical_sha1(bytes(swapped), [SLOT], gb=True)
    swapped[SLOT["offset"] + 4] ^= 0x20                                  # "SoulLink" -> "Soul-ink": one prefix byte
    assert ri.canonical_sha1(dev, [SLOT], gb=True) != ri.canonical_sha1(bytes(swapped), [SLOT], gb=True)
    with pytest.raises(ValueError, match="outside the version field"):
        ri.assert_version_only_difference(dev, bytes(swapped), [SLOT], gb=True)


def test_a_change_outside_the_field_is_caught():
    dev = _rom(b"SoulLink dev")
    bad = bytearray(_rom(b"SoulLink v0.3.0"))
    bad[0x2000] ^= 1
    assert ri.canonical_sha1(dev, [SLOT], gb=True) != ri.canonical_sha1(bytes(bad), [SLOT], gb=True)
    with pytest.raises(ValueError, match="outside the version field"):
        ri.assert_version_only_difference(dev, bytes(bad), [SLOT], gb=True)


def test_sizes_and_slots_are_validated():
    with pytest.raises(ValueError, match="size"):
        ri.assert_version_only_difference(b"a" * 10, b"a" * 11, [(0, 2)])
    with pytest.raises(ValueError, match="outside"):
        ri.canonical_bytes(b"a" * 10, [(8, 5)])
    with pytest.raises(ValueError, match="overlap"):
        ri.canonical_bytes(bytes(0x200), [(0x14C, 4)], gb=True)


def test_slot_from_sym_maps_banked_and_home_labels_to_file_offsets():
    sym = "00:3fe2 Home\n3f:6000 Banked\n01:4000 First\n01:3fff Odd\n"
    assert ri.slot_from_sym(sym, "Home") == {"offset": 0x3FE2, "length": ri.FIELD}
    assert ri.slot_from_sym(sym, "Banked")["offset"] == 0x3F * 0x4000 + 0x2000
    assert ri.slot_from_sym(sym, "First")["offset"] == 0x4000
    with pytest.raises(KeyError):
        ri.slot_from_sym(sym, "Nope")
    with pytest.raises(ValueError, match="below"):
        ri.slot_from_sym(sym, "Odd")


def test_slot_from_text_needs_a_unique_field():
    blob = b"xx" + b"FIELD" + b"yy"
    assert ri.slot_from_text(blob, b"FIELD") == {"offset": 2, "length": 5}
    with pytest.raises(ValueError):
        ri.slot_from_text(blob + b"FIELD", b"FIELD")
    with pytest.raises(ValueError):
        ri.slot_from_text(blob, b"MISSING")


def test_canonical_sha256_for_payloads():
    a, b = bytearray(64), bytearray(64)
    a[10:14], b[10:14] = b"dev\xff", b"v1.2"
    assert ri.canonical_sha256(bytes(a), [(10, 4)]) == ri.canonical_sha256(bytes(b), [(10, 4)])


def test_narrow_false_masks_the_whole_field_for_hashes_taken_that_way():
    """Gen 2's published canonical hashes mask the whole field; its builder pins the prefix itself."""
    dev = _rom(b"SoulLink dev")
    other_prefix = bytearray(_rom(b"SoulLink v0.3.0"))
    other_prefix[SLOT["offset"] + 4] ^= 0x20
    assert ri.canonical_sha1(dev, [SLOT], gb=True, narrow=False) == ri.canonical_sha1(bytes(other_prefix), [SLOT], gb=True, narrow=False)
    assert ri.canonical_sha1(dev, [SLOT], gb=True) != ri.canonical_sha1(bytes(other_prefix), [SLOT], gb=True)      # narrowed sees it
    ri.assert_version_only_difference(dev, bytes(other_prefix), [SLOT], gb=True, narrow=False)
