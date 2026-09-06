"""Pinned initializer pattern inventory and synthetic bypass capability proof.

Pattern matches are not a complete call graph. Direct helper invocation below
is a deliberately constructed CPU case, not an observed natural game route.
"""
import hashlib
import struct

import pytest
from lupa import LuaRuntime
from unicorn import UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC

from tests.rr.native.test_game_heap_cpu import (
    ALLOC,
    FREE,
    HEAP,
    INIT,
    ORIGINAL_SIZE,
    REDUCED_SIZE,
    cpu,
)
from tests.rr.native.test_heap_tail_guard_cpu import guard, prepared, run  # noqa: F401
from tools.rr.reference import BASE_SHA256

PUT, FIRST, CHECK_HEAP = 0x0800292C, 0x08002948, 0x08002BEC
ROOT, SIZE = 0x03000A38, 0x03000A3C
INIT_CALLS = (0x080003F4, 0x0800ACF6, 0x0804C120, 0x08078956, 0x0807928E, 0x08079BDC, 0x080EC8B4)


def occurrences(rom, value):
    needle, found, offset = struct.pack("<I", value), [], 0
    while (offset := rom.find(needle, offset)) >= 0:
        found.append(0x08000000 + offset)
        offset += 1
    return found


@pytest.fixture(scope="module")
def inventory(rr_rom_path):
    rom = rr_rom_path.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == BASE_SHA256
    targets = {PUT, FIRST, INIT}

    def interest(address):
        return address in targets or PUT < address < 0x0800295C or INIT < address < 0x08002B92

    words, halves = memoryview(rom).cast("I"), memoryview(rom).cast("H")
    bl, short, conditional, arm, thumb_loads, arm_loads, mirrored_globals = [], [], [], [], [], [], []
    pools = set(occurrences(rom, ROOT) + occurrences(rom, SIZE))
    for index in range(len(halves) - 1):
        first, second = halves[index], halves[index + 1]
        address = 0x08000000 + index * 2
        if first & 0xF800 == 0xF000 and second & 0xF800 == 0xF800:
            delta = (first & 0x7FF) << 12 | (second & 0x7FF) << 1
            if delta & 0x400000:
                delta -= 0x800000
            target = address + 4 + delta
            if interest(target):
                bl.append((address, target))
        if first & 0xF800 == 0xE000:
            delta = (first & 0x7FF) << 1
            if delta & 0x800:
                delta -= 0x1000
            target = address + 4 + delta
            if interest(target):
                short.append((address, target))
        if first & 0xF000 == 0xD000 and ((first >> 8) & 15) < 14:
            delta = (first & 255) << 1
            if delta & 0x100:
                delta -= 0x200
            target = address + 4 + delta
            if interest(target):
                conditional.append((address, target))
        if first & 0xF800 == 0x4800:
            pool = ((address + 4) & ~3) + (first & 255) * 4
            if pool in pools:
                thumb_loads.append((address, pool))
    for index, word in enumerate(words):
        address = 0x08000000 + index * 4
        if word & 0xFF007FFF in (ROOT, SIZE):
            mirrored_globals.append((address, word))
        if word & 0x0E000000 == 0x0A000000 and word >> 28 != 15:
            delta = (word & 0xFFFFFF) << 2
            if delta & 0x2000000:
                delta -= 0x4000000
            target = address + 8 + delta
            if interest(target):
                arm.append((address, target, word))
        if word & 0x0F7F0000 == 0x051F0000 and word >> 28 != 15:
            pool = address + 8 + ((word & 0xFFF) if word & (1 << 23) else -(word & 0xFFF))
            if pool in pools:
                arm_loads.append((address, pool))
    return rom, {"thumb_bl": bl, "thumb_b": short, "thumb_conditional": conditional, "arm_b_bl": arm,
                 "thumb_literal_loads": thumb_loads, "arm_literal_loads": arm_loads,
                 "aligned_iwram_global_literals": mirrored_globals}


def test_direct_initializer_patterns_are_exactly_inventory_not_callgraph(inventory):
    _, found = inventory
    expected = sorted([(address, INIT) for address in INIT_CALLS] + [(0x08002B8A, FIRST), (0x08002952, PUT), (0x080029BA, PUT)])
    assert found["thumb_bl"] == expected
    assert found["thumb_b"] == found["thumb_conditional"] == []
    assert found["arm_b_bl"] == [(0x08507FDC, 0x08002B90, 0xEAEBEAEB)]


def test_exact_pointer_and_global_literal_inventory_with_load_sites(inventory):
    rom, found = inventory
    for address in (PUT, FIRST, INIT):
        assert occurrences(rom, address) == occurrences(rom, address | 1) == []
    # Also inspect every halfword entry inside each initializer, including epilogues.
    aliases = {}
    for address in (*range(PUT, 0x0800295C, 2), *range(INIT, 0x08002B92, 2)):
        for value in (address, address | 1):
            if found_at := occurrences(rom, value):
                aliases[value] = found_at
    assert aliases == {0x08002930: [0x0870467B], 0x08002935: [0x0982A331], 0x08002940: [0x09588268]}
    assert occurrences(rom, ROOT) == [0x08002B94, 0x08002BAC, 0x08002BC0, 0x08002BD4, 0x08002BE8, 0x08002C10, 0x08DAF836]
    assert occurrences(rom, SIZE) == [0x08002B98]
    assert found["thumb_literal_loads"] == [(0x08002B82, 0x08002B94), (0x08002B86, 0x08002B98),
                                            (0x08002BA0, 0x08002BAC), (0x08002BB4, 0x08002BC0),
                                            (0x08002BC8, 0x08002BD4), (0x08002BDC, 0x08002BE8), (0x08002BEE, 0x08002C10)]
    assert found["arm_literal_loads"] == []
    assert found["aligned_iwram_global_literals"] == [(0x08002B94, ROOT), (0x08002B98, SIZE),
                                                      (0x08002BAC, ROOT), (0x08002BC0, ROOT),
                                                      (0x08002BD4, ROOT), (0x08002BE8, ROOT), (0x08002C10, ROOT)]


@pytest.mark.parametrize("start,target,end", [(0xDAF770, 0xDAF836, 0xDAFA21), (0x1587FD4, 0x1588268, 0x1588499)])
def test_pointer_like_literal_is_inside_a_complete_lz_asset(inventory, start, target, end):
    rom, _ = inventory
    assert rom[start:start + 4] == bytes.fromhex("10000800")
    cursor, output = start + 4, bytearray()
    while len(output) < 2048:
        flags = rom[cursor]
        cursor += 1
        for bit in range(8):
            if len(output) == 2048:
                break
            if flags & (0x80 >> bit):
                first, second = rom[cursor:cursor + 2]
                cursor += 2
                distance, length = ((first & 15) << 8 | second) + 1, (first >> 4) + 3
                assert distance <= len(output) and len(output) + length <= 2048
                for _ in range(length):
                    output.append(output[-distance])
            else:
                output.append(rom[cursor])
                cursor += 1
    assert cursor == end and start <= target < cursor
    if start == 0xDAF770:
        assert struct.unpack_from("<IHH", rom, 0x235684) == (0x08DAF770, 2048, 187)
        assert occurrences(rom, 0x08DAF770) == [0x08235684]


def test_arm_pattern_is_inside_bounded_pcm_wave_payload_not_a_confirmed_caller(inventory):
    rom, _ = inventory
    # Data classification only; this does not prove a natural sound consumer or
    # rule out execution through arbitrary corrupted pointers.
    assert struct.unpack_from("<HHIII", rom, 0x506C68) == (0, 0x4000, 27400192, 5495, 13006)
    assert 0x506C68 + 16 <= 0x507FDC < 0x506C68 + 16 + 13006 == 0x509F46
    assert occurrences(rom, 0x08506C68) == [0x0848C534]
    assert struct.unpack_from("<HHIII", rom, 0x509F48) == (0, 0x4000, 3425024, 1121, 2591)
    assert rom[0x507FDC:0x507FE0] == bytes.fromhex("ebeaebea")


def test_executed_malloc_wrapper_global_writes_are_the_two_initializer_stores(inventory):
    rom, _ = inventory
    native, writes = cpu(rom), []
    native.cpu.hook_add(UC_HOOK_MEM_WRITE,
                        lambda c, a, p, s, v, u: writes.append((c.reg_read(UC_ARM_REG_PC), p, s, v)),
                        begin=ROOT, end=SIZE + 3)
    native.call(INIT, [HEAP, REDUCED_SIZE])
    pointer = native.call(ALLOC, [512])
    assert native.call(0x08002BD8, [pointer]) == native.call(CHECK_HEAP) == 1
    native.call(FREE, [pointer])
    assert writes == [(0x08002B84, ROOT, 4, HEAP), (0x08002B88, SIZE, 4, REDUCED_SIZE)]
    assert not native.stubs


@pytest.mark.parametrize("builder", [FIRST, PUT])
def test_direct_header_builder_can_bypass_entry_guard_but_is_not_natural_reachability(guard, rr_repo, builder):  # noqa: F811
    native, _ = prepared(guard, HEAP, ORIGINAL_SIZE, True)
    run(native)
    expected_globals = struct.pack("<II", HEAP, REDUCED_SIZE)
    assert native.read(ROOT, 8) == expected_globals
    args = [HEAP, ORIGINAL_SIZE] if builder == FIRST else [HEAP, HEAP, HEAP, ORIGINAL_SIZE - 16]
    native.call(builder, args)  # Deliberate synthetic entry, not an observed caller.
    assert native.read(ROOT, 8) == expected_globals
    assert native.call(CHECK_HEAP) == 1  # Stock validator omits the size-global bound.
    lua = LuaRuntime(unpack_returned_tuples=True)
    helper = lua.execute((rr_repo / "lua/rr/heap_snapshot.lua").read_text())
    io = lua.table_from({"read_u16_le": lambda a: int.from_bytes(native.read(a, 2), "little"),
                         "read_u32_le": lambda a: int.from_bytes(native.read(a, 4), "little")})
    assert helper.read(io, lambda: 1) == (None, "invalid_block_extent")
    pointer = native.call(ALLOC, [ORIGINAL_SIZE - 16])
    assert pointer == HEAP + 16
    assert pointer < HEAP + REDUCED_SIZE < pointer + ORIGINAL_SIZE - 16 == HEAP + ORIGINAL_SIZE
    assert native.read(ROOT, 8) == expected_globals and not native.stubs
