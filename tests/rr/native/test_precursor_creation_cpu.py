"""Pinned precursor metadata and actual creation-selector CPU observations.

No taxonomy/acquisition approval, game emulator, ROM writes or routine stubs.
"""
import hashlib
import json
import struct

import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_READ
from unicorn.arm_const import (
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_R3,
    UC_ARM_REG_SP,
)

from tests.rr.native.test_regional_precursor_cpu import (
    MON,
    RETURN,
    ROM,
    STACK,
    PrecursorsCPU,
    pinned,  # noqa: F401
)

SELECTOR = 0x09078218
NORMAL = (104, 109, 492)
UNKNOWN = (1038, 1214, 1224)
BASE_STATS = 0x097B98EC
POOLS = (
    (0x09163B98, 1032, "16b136cb398abbfe3782da72512e6f51cc098d0d792905560f066bdf89da08f0", 0x090784A8),
    (0x091643AA, 979, "6a443e6afce6152c1e132936d4dd1bb088401296e9ec5149b0e0653c661dbc5b", 0x090784B4),
    (0x09164B52, 927, "b84203bcc9e27a816cce65e729298625831c0c8b347e26b38101495c054ca7c3", 0x090784BC),
    (0x09165292, 904, "0440fcf8d4142e0202c4ab142f67f3c0fe8073939717f9fd33c8658ae6bed77c", 0x090784C8),
    (0x091659A4, 569, "c210b38b9ced577d60d79767b54beb0b7824ed784c6da5c110a5d99bf4d45f7e", 0x090784D4),
    (0x09165E18, 330, "aab4b7da4e046e43dd974103d3a3bb705049bba20a6470881b3769076ada72c9", 0x090784DC),
)
MEMBERSHIP = (
    (0x09163658, 42, "3c9291d409367ca33f7bfecc81fe23d09ff787c1b6ebcdb654a9f1d4a7fff5ee", 0x090784FC, 0),
    (0x091636EA, 339, "ff251ff0584d5c39d63ef2692df13aac88298a9e36fd3c5ed1e27631d58ae3e9", 0x090784EC, 1),
    (0x09163994, 257, "0452671ec07c33c986a752df4042d47cc29becbc5ca7484f7ef12c2f8f2b73ea", 0x090784F4, 1),
)
SELECTOR_DATA_READS = {
    (MON, 2), (0x02020EEA, 1), (0x02020FE4, 1),
    (0x0203B17B, 1), (0x0203B17C, 1), (0x0203B17D, 1),
    (0x0203B25B, 1), (0x0203B25D, 1), (0x03005008, 4), (0x03005E88, 1),
}


def region(rom, address, size):
    return rom[address - ROM:address - ROM + size]


@pytest.mark.parametrize("normal,unknown,expected_differences", [
    (104, 1038, [(0x17, 4, 31)]),
    (109, 1214, [(0x17, 74, 0), (0x1A, 202, 1)]),
    (492, 1224, []),
])
def test_actual_precursor_record_differences_are_metadata_not_alias_proof(pinned, normal, unknown, expected_differences):  # noqa: F811
    before = region(pinned, BASE_STATS + normal * 28, 28)
    after = region(pinned, BASE_STATS + unknown * 28, 28)
    assert any(before) and any(after)
    assert [(i, a, b) for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b] == expected_differences


def test_actual_creation_call_chain_and_selector_are_pinned(pinned):  # noqa: F811
    # CreateMon -> original CreateBoxMon entry -> RR hook -> RR constructor.
    assert region(pinned, 0x0803DA96, 4) == bytes.fromhex("00f015f8")
    assert region(pinned, 0x0803DAC4, 14) == bytes.fromhex("f0b557464e464546e0b488b0071c")
    assert region(pinned, 0x0803DAD2, 10) == bytes.fromhex("014800470000194b0409")
    assert hashlib.sha256(region(pinned, 0x09044B18, 26)).hexdigest() == "65836e7c3e0eab6d6d94ef99583ac38a262f5770e405868dc596fdae34357ba9"
    assert region(pinned, 0x09044B2A, 4) == bytes.fromhex("33f0f2fc")  # BL09078512
    assert hashlib.sha256(region(pinned, 0x09078512, 774)).hexdigest() == "a1753678bef888b9a772ac6f8fa16028dae89e02019369d501c1990182590d37"
    assert region(pinned, 0x09078530, 4) == bytes.fromhex("fff772fe")  # BL09078218
    assert hashlib.sha256(region(pinned, SELECTOR, 744)).hexdigest() == "46fd5e4a5e0ed15f5db220728d94c0710bf0fd71205ad6c2143b2f5f4c59ada7"
    # The constructor writes its selected species through the actual setter.
    assert region(pinned, 0x090785C0, 10) == bytes.fromhex("32000b21200004f06ffc")
    # This vendored hook label does NOT identify an exported RR ban function.
    assert region(pinned, 0x0801D87C, 12) == bytes.fromhex("22d1197858204843211c5031")


@pytest.mark.parametrize("address,count,digest,literal", POOLS)
def test_actual_counted_creation_candidate_domains(pinned, address, count, digest, literal):  # noqa: F811
    raw = region(pinned, address, 2 + count * 2)
    assert int.from_bytes(raw[:2], "little") == count
    assert hashlib.sha256(raw).hexdigest() == digest
    assert region(pinned, literal, 8) == struct.pack("<II", address, address + 2)
    values = struct.unpack("<" + str(count) + "H", raw[2:])
    assert all(1 <= value <= 1375 for value in values)
    assert all(value not in values for value in UNKNOWN)
    assert all(values.count(value) == 1 for value in NORMAL)


@pytest.mark.parametrize("address,count,digest,literal,normal_count", MEMBERSHIP)
def test_actual_membership_creation_domains(pinned, address, count, digest, literal, normal_count):  # noqa: F811
    raw = region(pinned, address, (count + 1) * 2)
    assert hashlib.sha256(raw).hexdigest() == digest
    assert region(pinned, literal, 4) == struct.pack("<I", address)
    assert raw[-2:] == b"\xfe\xfe"
    values = struct.unpack("<" + str(count) + "H", raw[:-2])
    assert 0xFEFE not in values and all(1 <= value <= 1375 for value in values)
    assert all(value not in values for value in UNKNOWN)
    assert all(values.count(value) == normal_count for value in NORMAL)
    # Independent actual leaf routine recognizes a member and rejects each unknown.
    assert hashlib.sha256(region(pinned, 0x090C1884, 28)).hexdigest() == "7a6951a02a27699b0b770f9098917615bcf3bb214d2ea00fce95ec40289d7b7a"
    machine = PrecursorsCPU(pinned)
    for species, expected in [(values[0], 1), *[(value, 0) for value in UNKNOWN]]:
        assert machine.call(0x090C1884, species, address) == expected
        assert not machine.writes
        assert all(ROM <= a < a + n <= ROM + len(pinned) for a, n in machine.reads)


@pytest.mark.parametrize("species", [104, 1038, 109, 1214, 492, 1224])
def test_actual_all_clear_selector_does_not_normalize_precursor_ids(pinned, species):  # noqa: F811
    machine = PrecursorsCPU(pinned)
    machine.cpu.mem_write(0x03005008, struct.pack("<I", 0x02020000))
    machine.cpu.mem_write(0x0300500C, struct.pack("<I", 0x02026000))
    machine.cpu.mem_write(MON - 16, b"\xa5" * 16 + struct.pack("<H", species) + b"\x5a" * 16)
    before = bytes(machine.cpu.mem_read(MON - 16, 34))
    entries = {SELECTOR, 0x0806E6D0, 0x0806E5C0, 0x09042DEC, 0x090B8FB0}
    for entry in entries:
        machine.cpu.hook_add(UC_HOOK_CODE, machine._entry, begin=entry, end=entry)
    machine.call(SELECTOR, MON)
    assert machine.entries == entries
    assert bytes(machine.cpu.mem_read(MON - 16, 34)) == before
    assert machine.writes and all(STACK - 48 <= a < a + n <= STACK for a, n in machine.writes)
    non_stack_data = {(a, n) for a, n in machine.reads if not ROM <= a < ROM + len(pinned) and not STACK - 48 <= a < STACK}
    assert non_stack_data == SELECTOR_DATA_READS
    for address, size in SELECTOR_DATA_READS - {(MON, 2), (0x03005008, 4)}:
        assert bytes(machine.cpu.mem_read(address, size)) == bytes(size)


class BoxCreationCPU(PrecursorsCPU):
    """Execute a real constructor with explicit synthetic save/map metadata.

    Memory/code callbacks only observe or terminate an out-of-contract attempt.
    They never supply a routine's result or emulate a missing service.
    """

    ENTRIES = {0x0803DAC4, 0x09044B18, 0x09078512, SELECTOR, 0x0803D97C,
               0x080404D0, 0x0803FD44, 0x08056260, 0x08055238, 0x090A8E88, 0x08044EC8}

    def __init__(self, rom):
        super().__init__(rom)
        self.rom_size = len(rom)
        self.unexpected, self.instructions, self.rng_calls = [], 0, 0
        self.allowed_reads = [(ROM, len(rom)), (STACK - 0x400, 0x410), (MON, 80),
                              (0x02020000, 0x1000), (0x02026000, 0x100), (0x0203B174, 0x400),
                              (0x03005008, 8), (0x03005000, 4), (0x03005E88, 1)]
        self.allowed_writes = [(STACK - 0x400, 0x400), (MON, 80), (0x03005000, 4)]
        self.cpu.hook_add(UC_HOOK_CODE, self._code_boundary)
        self.cpu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self._memory_boundary)

    def _code_boundary(self, cpu, address, size, user):
        self.instructions += 1
        if address in self.ENTRIES:
            self.entries.add(address)
        if address == 0x08044EC8:
            self.rng_calls += 1
        if not ROM <= address < address + size <= ROM + self.rom_size:
            self.unexpected.append(("execute", address, size, address))
            cpu.emu_stop()

    def _memory_boundary(self, cpu, access, address, size, value, user):
        allowed = self.allowed_reads if access == UC_MEM_READ else self.allowed_writes
        if not any(start <= address < address + size <= start + length for start, length in allowed):
            self.unexpected.append(("read" if access == UC_MEM_READ else "write", address, size, cpu.reg_read(UC_ARM_REG_PC)))
            cpu.emu_stop()

    def construct(self, species):
        # Actual GetCurrentRegionMapSectionId uses SaveBlock1 location bytes+4/+5.
        # These are synthetic blocks, not writes to a campaign save or free-arena claims.
        self.cpu.mem_write(0x03005008, struct.pack("<II", 0x02020000, 0x02026000))
        self.cpu.mem_write(0x02020004, bytes([3, 1]))
        self.cpu.mem_write(0x02026000, b"\xbb" + b"\xff" * 6 + bytes(3) + struct.pack("<I", 0x12345678))
        self.cpu.mem_write(MON - 32, b"\xa5" * 32 + b"\xcc" * 80 + b"\x5a" * 32)
        # The real no-shiny constructor branch generates OT ID with actual RNG.
        # Args: fixed personality=true, PID1, OT_ID_RANDOM_NO_SHINY=2, unused fixed OT0.
        arguments = struct.pack("<IIII", 1, 1, 2, 0)
        self.cpu.mem_write(STACK, arguments)
        immutable = [(a, bytes(self.cpu.mem_read(a, n))) for a, n in
                     [(0x02020000, 0x1000), (0x02026000, 0x100), (0x0203B174, 0x400), (0x03005008, 8), (0x03005E88, 1)]]
        self.entries.clear()
        self.reads.clear()
        self.writes.clear()
        for register, value in [(UC_ARM_REG_SP, STACK), (UC_ARM_REG_LR, RETURN | 1),
                                (UC_ARM_REG_R0, MON), (UC_ARM_REG_R1, species),
                                (UC_ARM_REG_R2, 5), (UC_ARM_REG_R3, 31)]:
            self.cpu.reg_write(register, value)
        self.cpu.emu_start(0x0803DAC5, RETURN, count=200_000, timeout=2_000_000)
        assert not self.unexpected, self.unexpected
        assert self.cpu.reg_read(UC_ARM_REG_PC) == RETURN, "actual constructor did not return within budget"
        assert self.entries == self.ENTRIES
        assert self.rng_calls == 2
        assert int.from_bytes(self.cpu.mem_read(0x03005000, 4), "little") == 0xE97E7B6A
        assert bytes(self.cpu.mem_read(MON - 32, 32)) == b"\xa5" * 32
        assert bytes(self.cpu.mem_read(MON + 80, 32)) == b"\x5a" * 32
        assert bytes(self.cpu.mem_read(STACK, 16)) == arguments
        assert all(bytes(self.cpu.mem_read(a, len(raw))) == raw for a, raw in immutable)
        assert all(any(start <= a < a + n <= start + length for start, length in self.allowed_writes) for a, n in self.writes)
        return bytes(self.cpu.mem_read(MON, 80))

    def read_species(self):
        # The actual accessor retains two stores per payload word even though RR
        # replaced both XOR instructions with NOPs. It is not a read-only call.
        before = bytes(self.cpu.mem_read(MON, 80))
        trace = []

        def writes(cpu, access, address, size, value, user):
            if not STACK - 0x400 <= address < STACK:
                trace.append((cpu.reg_read(UC_ARM_REG_PC), address, size, value))

        self.allowed_writes = [(STACK - 0x400, 0x400), (MON + 0x20, 48)]
        hook = self.cpu.hook_add(UC_HOOK_MEM_WRITE, writes)
        try:
            for register, value in [(UC_ARM_REG_SP, STACK), (UC_ARM_REG_LR, RETURN | 1),
                                    (UC_ARM_REG_R0, MON), (UC_ARM_REG_R1, 0x0B), (UC_ARM_REG_R2, 0)]:
                self.cpu.reg_write(register, value)
            self.cpu.emu_start(0x0803FD45, RETURN, count=20_000, timeout=2_000_000)
            assert not self.unexpected, self.unexpected
            assert self.cpu.reg_read(UC_ARM_REG_PC) == RETURN, "actual species accessor did not return"
            expected = [(pc, MON + offset, 4, int.from_bytes(before[offset:offset + 4], "little"))
                        for offset in range(0x20, 0x50, 4) for pc in (0x0803F908, 0x0803F90E)]
            assert trace == expected
            assert bytes(self.cpu.mem_read(MON, 80)) == before
            return self.cpu.reg_read(UC_ARM_REG_R0)
        finally:
            self.cpu.hook_del(hook)


@pytest.mark.parametrize("normal,unknown,normal_hex", [
    (104, 1038, "0100000000007ee9bde9d6e3e2d9ff0000000202bbffffffffffff0000000000680000007d000000003203002d002700000000000f1e000000000000000000000000000000590502ffffff3f00000000"),
    (109, 1214, "0100000000007ee9c5e3dadadde2dbff00000202bbffffffffffff00000000006d0000007d000000003203008b0021007b0000002823140000000000000000000000000000590502ffffff3f00000000"),
    (492, 1224, "0100000000007ee9c7dde1d900c4e6adff000202bbffffffffffff0000000000ec0100007d00000000320300700001005d00c8011423191400000000000000000000000000590502ffffff3f00000000"),
])
def test_actual_box_constructor_preserves_explicit_precursor_species(pinned, normal, unknown, normal_hex, record_property):  # noqa: F811
    # Actual pure-RNG implementation and map lookup inputs, not HLE services.
    assert region(pinned, 0x08044EC8, 32) == bytes.fromhex("044a116804484843044940181060000c70470000005000036d4ec64173600000")
    assert region(pinned, 0x08056260, 36) == bytes.fromhex("00b508480168042008560004000c4979090609160904090cfef7deff007d02bc08470000")
    assert region(pinned, 0x08056284, 4) == struct.pack("<I", 0x03005008)
    assert region(pinned, 0x0805524C, 4) == struct.pack("<I", 0x083526A8)
    assert region(pinned, 0x083526A8 + 3 * 4, 4) == struct.pack("<I", 0x083522F4)
    assert region(pinned, 0x083522F4 + 1 * 4, 4) == struct.pack("<I", 0x08350634)
    assert region(pinned, 0x08350634 + 0x14, 1) == bytes([89])
    assert region(pinned, 0x0803F8F8, 36) == bytes.fromhex("10b5031c00241a1c203210681968c04610605968c04601c201340b2cf5d910bc01bc0047")
    outputs, counts = [], []
    for species in (normal, unknown):
        machine = BoxCreationCPU(pinned)
        raw = machine.construct(species)
        counts.append(machine.instructions)
        expected = bytearray.fromhex(normal_hex)
        expected[0x20:0x22] = struct.pack("<H", species)
        assert raw == expected
        assert raw[0x1C:0x20] == bytes(4)  # No backup-species/alias metadata appeared.
        # Independent actual accessor; exact redundant payload stores are checked.
        assert machine.read_species() == species
        assert bytes(machine.cpu.mem_read(MON, 80)) == raw
        assert not machine.unexpected
        outputs.append(raw)
    assert outputs[0][:0x20] + outputs[0][0x22:] == outputs[1][:0x20] + outputs[1][0x22:]
    record_property("classification", "unstubbed_synthetic_box_construction_not_acquisition")
    record_property("rom_sha256", hashlib.sha256(pinned).hexdigest())
    record_property("species", json.dumps([normal, unknown]))
    record_property("instructions", json.dumps(counts))
    record_property("constructed_80_byte_records", json.dumps([raw.hex() for raw in outputs]))
    record_property("output_sha256", hashlib.sha256(b"".join(outputs)).hexdigest())
