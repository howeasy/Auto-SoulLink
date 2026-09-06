"""Actual RR ancestry/evolution subroutines; no acquisition or taxonomy approval.

Uses the explicit optional Unicorn CPU lane, with no routine stubs or result
replacement. Synthetic mon arguments do not prove such a mon is obtainable.
"""

import hashlib
import struct

import pytest
from unicorn import (
    UC_ARCH_ARM,
    UC_HOOK_CODE,
    UC_HOOK_MEM_READ,
    UC_HOOK_MEM_WRITE,
    UC_MODE_THUMB,
    UC_PROT_EXEC,
    UC_PROT_READ,
    Uc,
)
from unicorn.arm_const import (
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_SP,
)

from tools.rr.reference import BASE_SHA256

ROM, RETURN, MON, STACK = 0x08000000, 0x01000000, 0x02010000, 0x03007E00
EGG_ENTRY, EGG_BODY, EVOLUTION_ENTRY, EVOLUTION_BODY = (
    0x08045970,
    0x093F1AB8,
    0x08042EC4,
    0x09093854,
)


@pytest.fixture(scope="module")
def pinned(rr_rom_path):
    rom = rr_rom_path.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == BASE_SHA256
    assert rom[EGG_ENTRY - ROM : EGG_ENTRY - ROM + 8] == bytes.fromhex("00490847b91a3f09")
    assert rom[EVOLUTION_ENTRY - ROM : EVOLUTION_ENTRY - ROM + 8] == bytes.fromhex(
        "004b184755380909"
    )
    return rom


class PrecursorsCPU:
    def __init__(self, rom):
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for address, size in [
            (ROM, len(rom)),
            (0x02000000, 0x40000),
            (0x03000000, 0x8000),
            (RETURN, 0x1000),
        ]:
            self.cpu.mem_map(address, size)
        self.cpu.mem_write(ROM, rom)
        self.cpu.mem_protect(ROM, len(rom), UC_PROT_READ | UC_PROT_EXEC)
        self.entries, self.reads, self.writes = set(), set(), set()
        for entry in [EGG_ENTRY, EGG_BODY, EVOLUTION_ENTRY, EVOLUTION_BODY]:
            self.cpu.hook_add(UC_HOOK_CODE, self._entry, begin=entry, end=entry)
        self.cpu.hook_add(UC_HOOK_MEM_READ, self._read)
        self.cpu.hook_add(UC_HOOK_MEM_WRITE, self._write)

    def _entry(self, cpu, address, size, user):
        self.entries.add(address)

    def _read(self, cpu, access, address, size, value, user):
        self.reads.add((address, size))

    def _write(self, cpu, access, address, size, value, user):
        self.writes.add((address, size))

    def call(self, entry, argument, mode=0, item=0):
        self.entries.clear()
        self.reads.clear()
        self.writes.clear()
        for register, value in [
            (UC_ARM_REG_SP, STACK),
            (UC_ARM_REG_LR, RETURN | 1),
            (UC_ARM_REG_R0, argument),
            (UC_ARM_REG_R1, mode),
            (UC_ARM_REG_R2, item),
        ]:
            self.cpu.reg_write(register, value)
        self.cpu.emu_start(entry | 1, RETURN, count=2_000_000, timeout=2_000_000)
        assert self.cpu.reg_read(UC_ARM_REG_PC) == RETURN, "actual routine did not return"
        # Every routine write must remain in its synthetic stack frame.
        assert all(
            STACK - 0x400 <= address < address + size <= STACK for address, size in self.writes
        )
        return self.cpu.reg_read(UC_ARM_REG_R0)


@pytest.mark.parametrize(
    "species,expected",
    [
        (1038, 1038),
        (1214, 1214),
        (1224, 1224),
        (1036, 1036),
        (1037, 102),
        (1039, 104),
        (1215, 109),
        (1216, 492),
        (1158, 492),
    ],
)
def test_actual_egg_ancestry_does_not_resolve_the_unused_precursors(pinned, species, expected):
    machine = PrecursorsCPU(pinned)
    assert machine.call(EGG_ENTRY, species) == expected
    assert machine.entries == {EGG_ENTRY, EGG_BODY}
    assert machine.writes and all(address >= STACK - 16 for address, _ in machine.writes)
    assert all(
        ROM <= address < ROM + len(pinned) or STACK - 16 <= address < STACK
        for address, _ in machine.reads
    )
    # The actual scanner ignoresFE and searches16 slots up to species1380.
    # This bound is taken from its literal, not inferred from name-table length.
    assert pinned[0x13F1AF0:0x13F1AF8] == bytes.fromhex("6505000030da7c09")
    assert pinned[0x13F1AD4:0x13F1AE2] == bytes.fromhex("ce5afe2ef4d0ce18b6888642f0d1")


@pytest.mark.parametrize("species", [1038, 1214, 1224])
@pytest.mark.parametrize(
    "mode,item", [(0, 0), (1, 0), (2, 93), (2, 98), (2, 99), (2, 102), (3, 98)]
)
def test_actual_evolution_dispatch_keeps_unknown_record_species(pinned, species, mode, item):
    machine = PrecursorsCPU(pinned)
    raw = bytearray(100)
    struct.pack_into("<II", raw, 0, 1, 222)
    raw[0x12:0x14] = bytes([2, 2])
    struct.pack_into("<H", raw, 0x20, species)
    raw[0x29], raw[0x54] = 255, 100
    raw[0x2C:0x34] = struct.pack("<4H", 102, 0, 0, 0)  # Mimic available where relevant.
    machine.cpu.mem_write(MON, bytes(raw))
    assert machine.call(EVOLUTION_ENTRY, MON, mode, item) == 0
    assert machine.entries == {EVOLUTION_ENTRY, EVOLUTION_BODY}
    assert bytes(machine.cpu.mem_read(MON, 100)) == raw


def test_evolution_probe_has_real_positive_control(pinned):
    machine = PrecursorsCPU(pinned)
    raw = bytearray(100)
    raw[0x12:0x14] = bytes([2, 2])
    struct.pack_into("<H", raw, 0x20, 1216)
    raw[0x54] = 100
    machine.cpu.mem_write(MON, bytes(raw))
    assert machine.call(EVOLUTION_ENTRY, MON) == 1158  # Actual Galar Mr.Mime→Mr.Rime.
    assert machine.entries == {EVOLUTION_ENTRY, EVOLUTION_BODY}
