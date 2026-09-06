import struct

import pytest

from tools.rr.arena import ROM_BASE, arm_bl_target, audit, reference_candidates, thumb_bl_target


def encode_thumb_call(address, target):
    displacement = (target - address - 4) & 0x7FFFFF
    return 0xF000 | (displacement >> 12), 0xF800 | ((displacement >> 1) & 0x7FF)


@pytest.mark.parametrize("displacement", [0, 2, 4094, -2, -4096, 0x3FFFFE, -0x400000])
def test_thumb_signed_displacement(displacement):
    address = ROM_BASE + 0x400000
    target = address + 4 + displacement
    assert thumb_bl_target(address, *encode_thumb_call(address, target)) == target


def test_ignores_non_call_instructions():
    assert thumb_bl_target(ROM_BASE, 0x4800, 0xF800) is None
    assert thumb_bl_target(ROM_BASE, 0xF000, 0xE800) is None
    assert arm_bl_target(ROM_BASE, 0xEA000000) is None
    assert arm_bl_target(ROM_BASE, 0xFB000000) is None


@pytest.mark.parametrize("displacement", [0, 4, -4, 0x1FFFFFC, -0x2000000])
def test_arm_signed_displacement(displacement):
    instruction = 0xEB000000 | ((displacement >> 2) & 0xFFFFFF)
    assert arm_bl_target(ROM_BASE, instruction) == ROM_BASE + 8 + displacement


def test_scans_calls_literals_and_pointers_without_claiming_context():
    rom = bytearray(64)
    target = ROM_BASE + 48
    struct.pack_into("<HH", rom, 0, *encode_thumb_call(ROM_BASE, target))
    struct.pack_into("<H", rom, 4, 0x4801)  # PC-aligned load at +12.
    struct.pack_into("<I", rom, 12, 0x0203F810)
    struct.pack_into("<I", rom, 20, target | 1)
    result = reference_candidates(bytes(rom), targets={target: "example"})
    assert result["direct_call_candidates"] == [{"at": "0x08000000", "isa": "thumb", "target": "example"}]
    assert {"at": "0x08000004", "literal_at": "0x0800000C", "value": "0x0203F810"} in result["thumb_arena_load_candidates"]
    assert {"at": "0x08000014", "target": "example", "value": "0x08000031", "aligned": True} in result["function_pointer_candidates"]


def test_rom_identity_must_match_before_evidence_generation():
    with pytest.raises(ValueError, match="unsupported ROM identity"):
        audit(bytes(128))


def test_truncated_input_refused():
    with pytest.raises(ValueError, match="divisible"):
        reference_candidates(b"abc")
