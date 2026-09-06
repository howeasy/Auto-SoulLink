"""Actual RR pointer initialization/map consumers and compiled companion context.

No routine stubs or emulator/gameplay claims. InitIntrHandlers programs real DMA
registers in this CPU model; its intended copy bytes are inspected from ROM, not
claimed to have been transferred by a hardware DMA implementation here.
"""
import hashlib
import os
import struct
import subprocess
from pathlib import Path

import pytest

from tests.rr.native.test_ghost_placement_cpu import NativeCPU
from tests.rr.native.test_native_build import native_output  # noqa: F401
from tests.rr.reference.test_withdrawal_oracle import ROM_SHA256

SB1_PTR, SB2_PTR, IRQ_SB1, IRQ_SB2 = 0x03005008, 0x0300500C, 0x03003840, 0x03003838
SB1, SB2, OBJECTS, GH, MB = 0x0202552C, 0x02024588, 0x02036E38, 0x0203F850, 0x0203F800


@pytest.fixture(scope="module")
def rom(rr_rom_path):
    data = rr_rom_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == ROM_SHA256
    return data


def word(native, address):
    return struct.unpack("<I", native.read(address, 4))[0]


@pytest.fixture(scope="module")
def companion(native_output):  # noqa: F811
    toolchain = os.environ.get("SLINK_ARMGCC")
    if not toolchain:
        pytest.fail("set SLINK_ARMGCC to the pinned native toolchain", pytrace=False)
    nm = Path(toolchain) / ("arm-none-eabi-nm.exe" if os.name == "nt" else "arm-none-eabi-nm")
    rows = subprocess.run([str(nm), "-n", str(native_output / "handlers.elf")],
                          capture_output=True, text=True, check=True).stdout.splitlines()
    symbols = {parts[2]: int(parts[0], 16) for row in rows if len(parts := row.split()) == 3}
    assert {"ghost_cb", "drive_ghost", "rr_storage_field_ready"} <= symbols.keys()
    return (native_output / "slink_RR.gba").read_bytes(), symbols


def field_cpu(companion):
    n = NativeCPU(companion)
    n.cpu.mem_write(OBJECTS, bytes(16 * 36))
    n.w8(OBJECTS, 1)
    n.w8(OBJECTS + 8, 255)
    n.w8(OBJECTS + 9, 1)
    n.w8(OBJECTS + 10, 3)
    n.w32(SB1_PTR, SB1)
    n.w32(IRQ_SB1, 0x02010000)
    n.w8(SB1 + 4, 3)
    n.w8(SB1 + 5, 19)
    n.w8(0x02010004, 3)
    n.w8(0x02010005, 1)
    n.w8(GH, 1)
    n.w8(GH + 1, 255)
    return n


def test_actual_boot_dma_copy_explains_the_misidentified_lua_pointer_literals(rom):
    n = NativeCPU((rom, {"ghost_cb": 0x0837A970}))
    n.cpu.mem_map(0x04000000, 0x1000)
    n.call(0x08000688)
    source, destination, control = struct.unpack("<III", n.read(0x040000D4, 12))
    assert (source, destination, control) == (0x08000248, 0x03003580, 0x84000200)
    for alias, literal, value in [(IRQ_SB1, 0x08000508, SB1), (IRQ_SB2, 0x08000500, SB2)]:
        assert alias - destination == literal - source
        assert 0 <= alias - destination < 0x800
        assert struct.unpack_from("<I", rom, literal - 0x08000000)[0] == value
    # Exact ordinary startup BLs, not a claim based only on unused stock symbols.
    assert rom[0x3CA:0x3CE] == bytes.fromhex("00f05df9")  # InitIntrHandlers
    assert rom[0x3DE:0x3E2] == bytes.fromhex("00f071f8")  # InitMainCallbacks
    assert not n.stubs


@pytest.mark.parametrize("seed", [0, 1, 0x12345678, 0xFFFFFFFF])
def test_actual_rr_pointer_setter_disables_offset_and_updates_canonical_globals_only(rom, seed):
    n = NativeCPU((rom, {"ghost_cb": 0x0837A970}))
    n.w32(SB1_PTR, 0x02010000)
    n.w32(SB2_PTR, 0x02011000)
    n.w32(IRQ_SB1, 0xDEAD0000)
    n.w32(IRQ_SB2, 0xBEEF0000)
    n.w32(0x03005000, seed)
    assert rom[0x4C062:0x4C066] == bytes.fromhex("00210021")  # RR disables random offset
    n.call(0x0804C058)
    assert (word(n, SB1_PTR), word(n, SB2_PTR), word(n, 0x03005010)) == (SB1, SB2, 0x02029314)
    assert (word(n, IRQ_SB1), word(n, IRQ_SB2)) == (0xDEAD0000, 0xBEEF0000)
    assert not n.stubs


@pytest.mark.parametrize("number,expected_layout", [(1, 0x082DE3E4), (19, 0x082E55CC)])
def test_actual_map_loader_uses_canonical_pointer_even_when_irq_copy_disagrees(rom, number, expected_layout):
    n = NativeCPU((rom, {"ghost_cb": 0x0837A970}))
    n.w32(SB1_PTR, 0x02010000)
    n.w8(0x02010004, 3)
    n.w8(0x02010005, number)
    n.w32(IRQ_SB1, SB1)
    n.w8(SB1 + 4, 3)
    n.w8(SB1 + 5, 19 if number == 1 else 1)
    n.call(0x08055274)
    assert word(n, 0x02036DFC) == expected_layout
    # The real RR connection detour calls ApplyCurrentWarp then resumes this loader.
    assert struct.unpack_from("<III", rom, 0x10436A8) == (0x08055E95, 0x08055199, 0x08055889)
    assert rom[0x55888:0x5588C] == bytes.fromhex("fff7f4fc")
    assert not n.stubs


@pytest.mark.parametrize("prepared_map,expected", [(19, 1), (1, 0)])
def test_native_storage_context_uses_current_map_not_object_spawn_map(companion, prepared_map, expected):
    n = field_cpu(companion)
    args = MB + 16
    n.w8(args + 14, 3)
    n.w8(args + 15, prepared_map)
    n.w32(args + 16, 0x080565B5)
    n.w8(args + 23, 0xC2)
    before = n.read(0x02000000, 0x40000)
    assert n.call("rr_storage_field_ready") == expected
    assert n.read(0x02000000, 0x40000) == before and not n.stubs


def test_native_ghost_map_bookkeeping_uses_current_map_without_allocating_in_script(companion):
    n = field_cpu(companion)
    n.w8(0x03000F9C, 1)  # no ghost exists; real driver defers spawn during a field script
    n.call("drive_ghost")
    assert n.read(GH + 12, 2) == bytes([3, 19])
    assert n.read(GH + 1, 1) == b"\xff" and not n.stubs


@pytest.mark.parametrize("pointer", [0, 0x01FFFFFC, 0x02000001, 0x0203FFFC, 0x03000000])
def test_invalid_canonical_pointer_refuses_guarded_storage_and_new_ghost(companion, pointer):
    n = field_cpu(companion)
    n.w32(SB1_PTR, pointer)
    n.w8(MB + 16 + 23, 0xC2)
    before = n.read(0x02000000, 0x40000)
    assert n.call("rr_storage_field_ready") == 0
    n.call("drive_ghost")
    assert n.read(0x02000000, 0x40000) == before and not n.stubs
