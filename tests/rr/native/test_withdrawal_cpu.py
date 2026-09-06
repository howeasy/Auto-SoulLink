"""Unstubbed pinned RR CompressedMonToMon execution versus the inactive Lua oracle.

CPU-only synthetic records: no mGBA/storage/duo gameplay or mutation admission.
The code/READ/WRITE hooks below only observe; none intercept routines or alter CPU results.
"""
import hashlib
import json
import struct
from dataclasses import dataclass

import pytest
from lupa import LuaRuntime
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
    UC_ARM_REG_SP,
)

from tests.rr.native.test_native_build import native_output  # noqa: F401
from tests.rr.reference.test_withdrawal_oracle import (
    BASE_STATS,
    EXPERIENCE,
    ROM_SHA256,
    context,
    evidence,
)

SOURCE, DESTINATION = 0x02010000, 0x02011000
MGM, FRONTIER, LEVEL_HP = 0x0203B25A, 0x0203B17A, 0x02023FE7
ENTRY = 0x090B6A24
ENTRIES = {ENTRY, 0x090B6924, 0x0803E774, 0x090788FC, 0x0804101C,
           0x0803E7C4, 0x08042E9C, 0x08043698, 0x0806E6D0}
GROUPS = ("growth_nature", "experience", "iv_ev_species", "pp_bonuses", "move_packing", "captured_treecko")


@dataclass(frozen=True)
class Case:
    label: str
    raw: bytes


def record(species, *, pid=1, exp=125000, ivs=(0, 1, 15, 16, 30, 31),
           evs=(0, 3, 4, 251, 252, 255), bonuses=0xE4, moves=(0, 1, 165, 237), variant=0):
    raw = bytearray(58)
    struct.pack_into("<II", raw, 0, pid, 0xD0C0B000 + variant)
    raw[8:18] = bytes([0xCE, 0xBF, 0xCD, 0xCE] + [0xFF] * 6)
    raw[0x12:0x1C] = bytes([2, 2, 0xBB, 0xBC, 0xBD, 0xFF, 0xFF, 0xFF, 0xFF, variant & 15])
    struct.pack_into("<HHI", raw, 0x1C, species, (0, 1, 173, 255)[variant % 4], exp)
    raw[0x24:0x27] = bytes([bonuses, (0, 70, 255)[variant % 3], variant & 255])
    raw[0x27:0x2C] = sum(move << (10 * index) for index, move in enumerate(moves)).to_bytes(5, "little")
    raw[0x2C:0x32] = bytes(evs)
    raw[0x32:0x36] = bytes([0, 22, 5, 0])
    iv_word = sum(iv << (5 * index) for index, iv in enumerate(ivs)) | ((variant & 1) << 31)
    struct.pack_into("<I", raw, 0x36, iv_word)  # egg bit30 remains clear
    return bytes(raw)


@pytest.fixture(scope="module")
def pinned(rr_rom_path):
    rom = rr_rom_path.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == ROM_SHA256, "exact RR4.1 base ROM required"
    return rom


@pytest.fixture(scope="module")
def selected_candidate(native_output, pinned):  # noqa: F811
    manifest = json.loads((native_output / "native_manifest.json").read_text())
    rom = (native_output / "slink_RR.gba").read_bytes()
    assert manifest["base_rom_sha256"] == ROM_SHA256
    assert hashlib.sha256(rom).hexdigest() == manifest["rom_sha256"]
    assert hashlib.sha1(rom).hexdigest() == manifest["rom_sha1"]
    # The selected companion must retain these stock conversion/data regions.
    for address, size in [(0x090B6924, 0x120), (0x090788FC, 0x34C), (0x0803E774, 0xBC),
                          (0x0804101C, 0x48), (0x08043698, 0x60), (0x097B98EC, 1376 * 28),
                          (0x0915514C, 6 * 1024), (0x091521D0, 1024 * 12), (0x08252B48, 125)]:
        offset = address - 0x08000000
        assert rom[offset:offset + size] == pinned[offset:offset + size], hex(address)
    return rom


@pytest.fixture(scope="module")
def cases(pinned, rr_repo):
    representatives = {}
    for species in range(1, 1376):
        base = pinned[BASE_STATS + species * 28:BASE_STATS + (species + 1) * 28]
        if base[0]:
            representatives.setdefault(base[19], species)
    assert representatives == {3: 1, 0: 10, 4: 35, 5: 58, 1: 301, 2: 306}
    groups = {name: [] for name in GROUPS}
    for growth, species in sorted(representatives.items()):
        thresholds = struct.unpack_from("<256I", pinned, EXPERIENCE + growth * 1024)
        for nature in range(25):
            pid = 0xFFFFFFE1 + nature  # all25 natures, high unsigned PID range
            groups["growth_nature"].append(Case(f"growth{growth}-nature{pid % 25}",
                record(species, pid=pid, exp=thresholds[50], variant=nature)))
        for level in (1, 2, 49, 50, 99, 100, 101, 249, 250):
            for delta in (-1, 0, 1):
                exp = max(0, thresholds[level] + delta)
                groups["experience"].append(Case(f"growth{growth}-level{level}-delta{delta}",
                    record(species, exp=exp, pid=24, ivs=(31,) * 6, evs=(255,) * 6)))
        for exp in (0, 0xFFFFFFFF):
            groups["experience"].append(Case(f"growth{growth}-exp{exp}", record(species, exp=exp)))
    iv_patterns = [(0,) * 6, (31,) * 6, (0, 1, 15, 16, 30, 31), (31, 30, 16, 15, 1, 0)]
    ev_patterns = [(0,) * 6, (1, 2, 3, 4, 7, 8), (0, 3, 4, 251, 252, 255), (252,) * 6, (255,) * 6]
    for species in (25, 113, 303, 1356, 1375):
        for i, ivs in enumerate(iv_patterns):
            for e, evs in enumerate(ev_patterns):
                groups["iv_ev_species"].append(Case(f"species{species}-iv{i}-ev{e}",
                    record(species, pid=i * 5 + e, exp=0xFFFFFFFF, ivs=ivs, evs=evs, variant=i * 5 + e)))
    for bonuses in range(256):
        groups["pp_bonuses"].append(Case(f"pp-bonus-{bonuses:02x}", record(25, bonuses=bonuses)))
    move_patterns = [(0, 0, 0, 0), (1, 33, 85, 120), (237, 165, 120, 85),
                     (0, 0, 0, 700), (700, 0, 0, 0), (512, 700, 237, 0)]
    for index, moves in enumerate(move_patterns):
        for bonuses in (0, 0x55, 0xAA, 0xFF):
            groups["move_packing"].append(Case(f"packing{index}-bonus{bonuses:02x}", record(25, moves=moves, bonuses=bonuses)))
    fixture = json.loads((rr_repo / "tests/rr/reference/fixtures/field_party_08_a.json").read_text())
    captured = bytes.fromhex(fixture["raw_hex"])
    assert hashlib.sha256(captured).hexdigest() == "b9133a60d0c484c4477aadf5e2acd18082c4ce84b735afa285ed2ec98be2490c"
    moves = struct.unpack_from("<4H", captured, 0x2C)
    raw = (captured[:28] + captured[0x20:0x2B] + sum(move << (10 * i) for i, move in enumerate(moves)).to_bytes(5, "little")
           + captured[0x38:0x3E] + captured[0x44:0x4C])
    groups["captured_treecko"].append(Case("captured-field-treecko-represented-fields", raw))
    assert {key: len(value) for key, value in groups.items()} == dict(zip(GROUPS, [150, 174, 100, 256, 24, 1], strict=True))
    assert sum(map(len, groups.values())) == 705
    assert len({case.label for group in groups.values() for case in group}) == 705
    return groups


class StockConversionCPU:
    """ROM is read/execute-only; hooks only record executed entries and accesses."""
    def __init__(self, rom):
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for address, size in [(0x08000000, 0x02000000), (0x02000000, 0x40000),
                              (0x03000000, 0x8000), (0x01000000, 0x1000)]:
            self.cpu.mem_map(address, size)
        self.cpu.mem_write(0x08000000, rom)
        self.cpu.mem_protect(0x08000000, 0x02000000, UC_PROT_READ | UC_PROT_EXEC)
        self.entries, self.reads, self.writes = set(), set(), set()
        for address in ENTRIES:
            self.cpu.hook_add(UC_HOOK_CODE, self._entry, begin=address, end=address)
        self.cpu.hook_add(UC_HOOK_MEM_READ, self._read, begin=0x02000000, end=0x0203FFFF)
        self.cpu.hook_add(UC_HOOK_MEM_WRITE, self._write, begin=0x02000000, end=0x0203FFFF)

    def _entry(self, cpu, address, size, user):
        self.entries.add(address)

    def _read(self, cpu, access, address, size, value, user):
        self.reads.add((address, size))

    def _write(self, cpu, access, address, size, value, user):
        self.writes.add((address, size))

    def convert(self, raw, mgm):
        assert len(raw) == 58 and raw[0x13] & 1 == 0
        # Host seeding is synthetic test setup, not a production vacancy bypass.
        self.cpu.mem_write(0x02000000, bytes(0x40000))
        self.cpu.mem_write(0x03000000, bytes(0x8000))
        self.cpu.mem_write(MGM, bytes([4 if mgm else 0]))
        self.cpu.mem_write(FRONTIER, b"\0")
        canary = bytes((index * 73 + 29) & 255 for index in range(64))
        source_region = canary + raw + canary
        self.cpu.mem_write(SOURCE - 64, source_region)
        self.cpu.mem_write(DESTINATION - 64, canary + bytes([0xA5]) * 100 + canary)
        self.cpu.mem_write(LEVEL_HP, b"\xA5")
        self.entries.clear()
        self.reads.clear()
        self.writes.clear()
        self.cpu.reg_write(UC_ARM_REG_SP, 0x03007E00)
        self.cpu.reg_write(UC_ARM_REG_LR, 0x01000001)
        self.cpu.reg_write(UC_ARM_REG_R0, SOURCE)
        self.cpu.reg_write(UC_ARM_REG_R1, DESTINATION)
        self.cpu.emu_start(ENTRY | 1, 0x01000000, timeout=2_000_000, count=200_000)
        assert self.cpu.reg_read(UC_ARM_REG_PC) == 0x01000000, "stock function did not return"
        assert self.entries == ENTRIES, f"missing actual stock callees: {ENTRIES - self.entries}"
        assert bytes(self.cpu.mem_read(SOURCE - 64, 186)) == source_region
        assert bytes(self.cpu.mem_read(DESTINATION - 64, 64)) == canary
        assert bytes(self.cpu.mem_read(DESTINATION + 100, 64)) == canary
        assert bytes(self.cpu.mem_read(MGM, 1)) == bytes([4 if mgm else 0])
        assert bytes(self.cpu.mem_read(FRONTIER, 1)) == b"\0"
        assert (FRONTIER, 1) in self.reads
        assert not any(address <= MGM < address + size for address, size in self.reads)
        assert self.writes, "empty native-write evidence"
        for address, size in self.writes:
            assert (address >= DESTINATION and address + size <= DESTINATION + 100) or (address, size) == (LEVEL_HP, 1), \
                f"unexpected native EWRAM write: {address:08X}+{size}"
        output = bytes(self.cpu.mem_read(DESTINATION, 100))
        hp = struct.unpack_from("<H", output, 0x58)[0]
        assert self.cpu.mem_read(LEVEL_HP, 1)[0] == (hp & 255 or 1)
        return output


def compare_group(rom, rr_repo, cases, group, mgm):
    lua = LuaRuntime(encoding=None, unpack_returned_tuples=True)
    module = lua.execute((rr_repo / "lua/rr/withdrawal_oracle.lua").read_bytes())
    native = StockConversionCPU(rom)
    digest = hashlib.sha256()
    for case in cases[group]:
        expected = module.derive(case.raw, evidence(lua, rom, case.raw), context(lua, mgm))
        assert not isinstance(expected, tuple), f"{case.label}: oracle refused {expected}"
        actual = native.convert(case.raw, mgm)
        intended = expected[b"party_bytes"]
        differences = [(index, intended[index], actual[index]) for index in range(100) if intended[index] != actual[index]]
        assert not differences, f"{group}/{case.label}/MGM={mgm}: byte expected actual {differences}"
        assert actual[0x4F] == 0x80
        digest.update(case.raw + actual)
    return digest.hexdigest()


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("mgm", [False, True], ids=["mgm_off", "mgm_on"])
def test_base_rr_conversion_matches_full_oracle_without_routine_stubs(pinned, rr_repo, cases, group, mgm, record_property):
    trace_hash = compare_group(pinned, rr_repo, cases, group, mgm)
    record_property("classification", "unstubbed_stock_function_cpu_synthetic_records")
    record_property("case_count", len(cases[group]))
    record_property("rom_sha256", hashlib.sha256(pinned).hexdigest())
    record_property("oracle_sha256", hashlib.sha256((rr_repo / "lua/rr/withdrawal_oracle.lua").read_bytes()).hexdigest())
    record_property("input_output_sha256", trace_hash)


@pytest.mark.parametrize("group", GROUPS)
@pytest.mark.parametrize("mgm", [False, True], ids=["mgm_off", "mgm_on"])
def test_selected_companion_conversion_matches_full_oracle_without_routine_stubs(selected_candidate, rr_repo, cases, group, mgm, record_property):
    trace_hash = compare_group(selected_candidate, rr_repo, cases, group, mgm)
    record_property("classification", "unstubbed_stock_function_cpu_synthetic_records")
    record_property("case_count", len(cases[group]))
    record_property("rom_sha256", hashlib.sha256(selected_candidate).hexdigest())
    record_property("oracle_sha256", hashlib.sha256((rr_repo / "lua/rr/withdrawal_oracle.lua").read_bytes()).hexdigest())
    record_property("input_output_sha256", trace_hash)
