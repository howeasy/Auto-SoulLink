"""Actual RR heap routines, with synthetic CPU memory and no routine stubs.

Reduced-size InitHeap calls model an unimplemented reservation policy. They do not
patch the ROM, prove raw users respect the proposed tail, or establish live capacity.
"""
import hashlib
import struct

import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_SP

from tests.rr.native.test_ghost_placement_cpu import NativeCPU
from tests.rr.reference.test_withdrawal_oracle import ROM_SHA256

HEAP, ORIGINAL_SIZE, REDUCED_SIZE = 0x02000000, 0x1C000, 0x1B800
TAIL, TAIL_SIZE = HEAP + REDUCED_SIZE, 0x800
INIT, ALLOC, FREE, CHECK_BLOCK = 0x08002B80, 0x08002B9C, 0x08002BC4, 0x08002BD8
DIRECT_INIT_CALLS = (0x080003F4, 0x0800ACF6, 0x0804C120, 0x08078956, 0x0807928E, 0x08079BDC, 0x080EC8B4)


@pytest.fixture(scope="module")
def heap_rom(rr_rom_path):
    rom = rr_rom_path.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == ROM_SHA256
    return rom


def cpu(rom):
    native = NativeCPU((rom, {"ghost_cb": 0x08378F70}))
    assert native.stubs == {}  # No callback intercepts any routine in these tests.
    return native


def header(native, address):
    flag, magic, size, previous, following = struct.unpack("<HHIII", native.read(address, 16))
    return {"flag": flag, "magic": magic, "size": size, "previous": previous, "next": following}


def validate_heap(native, size):
    limit = HEAP + size
    current = previous = HEAP
    seen = set()
    while True:
        assert current not in seen and current % 4 == 0 and HEAP <= current < limit
        seen.add(current)
        block = header(native, current)
        assert block["flag"] in (0, 1) and block["magic"] == 0xA3A3
        assert block["size"] % 4 == 0 and current + 16 + block["size"] <= limit
        assert block["previous"] == previous
        if block["next"] == HEAP:
            assert current + 16 + block["size"] == limit
            return seen
        assert block["next"] == current + 16 + block["size"]
        previous, current = current, block["next"]


def test_actual_heap_reset_and_reallocation_keep_stale_payload_magic(heap_rom):
    native = cpu(heap_rom)
    native.call(INIT, [HEAP, ORIGINAL_SIZE])
    assert native.read(0x03000A38, 8) == struct.pack("<II", HEAP, ORIGINAL_SIZE)
    assert header(native, HEAP) == {"flag": 0, "magic": 0xA3A3, "size": ORIGINAL_SIZE - 16,
                                     "previous": HEAP, "next": HEAP}
    owned = native.call(ALLOC, [2048])
    assert owned == HEAP + 16
    token = b"SLink-old-owner-and-generation-token"
    native.cpu.mem_write(owned, token)
    other = native.call(ALLOC, [128])
    native.call(FREE, [other])
    assert native.read(owned, len(token)) == token
    assert native.call(CHECK_BLOCK, [owned]) == 1
    native.call(INIT, [HEAP, ORIGINAL_SIZE])
    assert header(native, HEAP)["flag"] == 0
    assert native.call(CHECK_BLOCK, [owned]) == 1  # Checker does not establish allocated ownership.
    reused = native.call(ALLOC, [2048])
    assert reused == owned and header(native, HEAP)["flag"] == 1
    assert native.read(reused, len(token)) == token
    assert native.call(CHECK_BLOCK, [reused]) == 1


@pytest.mark.parametrize("requested", [1, 3, 4, 5, 31, 32, 33, 0x7FF, 0x800, 0x801,
                                       0x10000, REDUCED_SIZE - 44, REDUCED_SIZE - 16])
def test_actual_allocator_respects_reduced_heap_limit_for_aligned_boundary_requests(heap_rom, requested):
    native = cpu(heap_rom)
    tail = bytes((i * 73 + 29) & 255 for i in range(TAIL_SIZE))
    libc = bytes((i * 19 + 101) & 255 for i in range(0x900))
    native.cpu.mem_write(TAIL, tail)
    native.cpu.mem_write(0x0203F700, libc)
    writes = []
    native.cpu.hook_add(UC_HOOK_MEM_WRITE, lambda c, a, p, s, v, u: writes.append((p, s)), begin=TAIL, end=TAIL + TAIL_SIZE - 1)
    native.call(INIT, [HEAP, REDUCED_SIZE])  # Simulate arguments a proposed wrapper would supply.
    pointer = native.call(ALLOC, [requested])
    block = header(native, pointer - 16)
    assert pointer >= HEAP + 16 and pointer + block["size"] <= TAIL
    assert block["size"] >= (requested + 3) & ~3
    validate_heap(native, REDUCED_SIZE)
    native.call(FREE, [pointer])
    assert validate_heap(native, REDUCED_SIZE) == {HEAP}
    assert native.read(TAIL, TAIL_SIZE) == tail and not writes
    assert native.read(0x0203F700, len(libc)) == libc


def test_fragmentation_coalescing_and_reinitialization_stay_below_candidate_tail(heap_rom):
    native = cpu(heap_rom)
    canary = b"\xA7" * TAIL_SIZE
    native.cpu.mem_write(TAIL, canary)
    for _ in range(4):
        native.call(INIT, [HEAP, REDUCED_SIZE])
        pointers = []
        for size in (0x400, 0x1000, 0x800, 0x2000, 1, 0x7F, 0x3000, 0x8000):
            pointers.append(native.call(ALLOC, [size]))
            validate_heap(native, REDUCED_SIZE)
            assert native.read(TAIL, TAIL_SIZE) == canary
        for index in (2, 0, 5, 4, 3, 1, 7, 6):
            native.call(FREE, [pointers[index]])
            validate_heap(native, REDUCED_SIZE)
            assert native.read(TAIL, TAIL_SIZE) == canary
        assert header(native, HEAP)["size"] == REDUCED_SIZE - 16


def test_one_unreduced_init_restores_game_allocator_ownership_of_the_candidate_tail(heap_rom):
    native = cpu(heap_rom)
    native.call(INIT, [HEAP, REDUCED_SIZE])
    native.call(INIT, [HEAP, ORIGINAL_SIZE])
    pointer = native.call(ALLOC, [ORIGINAL_SIZE - 16])
    assert pointer + header(native, pointer - 16)["size"] == HEAP + ORIGINAL_SIZE
    assert pointer < TAIL < pointer + header(native, pointer - 16)["size"]


def test_allocation_exhaustion_reaches_retained_libc_formatting_before_nominal_null_return(heap_rom):
    native = cpu(heap_rom)
    native.call(INIT, [HEAP, REDUCED_SIZE])
    native.call(ALLOC, [REDUCED_SIZE - 16])
    reached = []

    def observe(machine, address, size, user):
        reached.append(address)
        if address == 0x081E5FD4:
            machine.emu_stop()  # Deliberate reachability breakpoint, not a fabricated callee return.

    for address in (0x081E3B14, 0x081E39D8, 0x081E5FD4):
        native.cpu.hook_add(UC_HOOK_CODE, observe, begin=address, end=address)
    native.cpu.reg_write(UC_ARM_REG_SP, 0x03007E00)
    native.cpu.reg_write(UC_ARM_REG_LR, 0x01000001)
    native.cpu.reg_write(UC_ARM_REG_R0, 4)
    native.cpu.emu_start(ALLOC | 1, 0x01000000, timeout=2_000_000, count=100_000)
    assert reached == [0x081E3B14, 0x081E39D8, 0x081E5FD4]
    assert native.cpu.reg_read(UC_ARM_REG_PC) == 0x081E5FD4
    assert heap_rom[0x1E3B38:0x1E3B3A] == b"\xFF\xEF"  # Stop-program debug opcode follows print/flush.
    # This test intentionally makes no claim about later formatter/_malloc_r execution.


def test_pinned_direct_heap_initializers_and_known_raw_heap_spans(heap_rom):
    halfwords = memoryview(heap_rom).cast("H")
    calls = []
    for index in range(len(halfwords) - 1):
        first, second = halfwords[index], halfwords[index + 1]
        if first & 0xF800 == 0xF000 and second & 0xF800 == 0xF800:
            delta = (first & 0x7FF) << 12 | (second & 0x7FF) << 1
            if delta & 0x400000:
                delta -= 0x800000
            if 0x08000000 + index * 2 + 4 + delta == INIT:
                calls.append(0x08000000 + index * 2)
    assert tuple(calls) == DIRECT_INIT_CALLS
    # Actual MoveSaveBlocks_ResetHeap literals give three consecutive raw-copy spans.
    for offset, value in [(0x4C16C, 0xF24), (0x4C174, 0x3D68), (0x4C178, HEAP + 0xF24),
                           (0x4C180, 0x83D0), (0x4C184, HEAP + 0x4C8C)]:
        assert struct.unpack_from("<I", heap_rom, offset)[0] == value
    assert HEAP + 0xF24 + 0x3D68 + 0x83D0 == 0x0200D05C < TAIL
    # The actual legacy battle-frame table is sixteen0x800-byte spans ending02010000.
    for index in range(16):
        pointer, size = struct.unpack_from("<IH", heap_rom, 0x234698 + index * 8)
        assert pointer == HEAP + 0x8000 + index * 0x800 and size == 0x800
        assert pointer + size <= TAIL


def test_direct_tail_literal_inventory_does_not_mistake_asset_bytes_for_owned_ram(heap_rom):
    expected = {
        0x08171C54: 0x0201B925, 0x084087A4: 0x0201BE63, 0x0853F778: 0x0201BEDD,
        0x08D997AC: 0x0201B800, 0x08EA24BC: 0x0201BF02, 0x0941DE40: 0x0201BCE3,
        0x0945E248: 0x0201BE03, 0x0961B5E8: 0x0201B8FF, 0x09626C90: 0x0201BBFE,
        0x09EC112C: 0x0201BDE0,
    }
    found = {0x08000000 + index * 4: value for index, value in enumerate(memoryview(heap_rom).cast("I"))
             if TAIL <= value < TAIL + TAIL_SIZE}
    assert found == expected
    # Seven values lie inside structurally valid LZ77 streams. This is a data
    # classification, not proof that no calculated pointer can reach the RAM tail.
    streams = {
        0x084087A4: (0x08407B9C, 11136), 0x08D997AC: (0x08D994D8, 2048),
        0x08EA24BC: (0x08EA1D68, 20480), 0x0941DE40: (0x0941DD68, 2048),
        0x0945E248: (0x0945E0B8, 2048), 0x0961B5E8: (0x0961B364, 2048),
        0x09626C90: (0x09626AFC, 2048),
    }
    for candidate, (address, size) in streams.items():
        start = address - 0x08000000
        assert heap_rom[start] == 0x10
        assert int.from_bytes(heap_rom[start + 1:start + 4], "little") == size
        cursor, produced = start + 4, 0
        while produced < size:
            flags = heap_rom[cursor]
            cursor += 1
            for bit in range(8):
                if produced >= size:
                    break
                if flags & (0x80 >> bit):
                    first, second = heap_rom[cursor:cursor + 2]
                    cursor += 2
                    distance = ((first & 15) << 8 | second) + 1
                    assert distance <= produced
                    produced += (first >> 4) + 3
                else:
                    cursor += 1
                    produced += 1
        assert address <= candidate < cursor + 0x08000000
    # special0x01B9 + end in the native map script, not a 32-bit RAM operand.
    assert heap_rom[0x171C54:0x171C58] == bytes.fromhex("25b90102")
    # Cry-data and the remaining extended-ROM value stay explicitly unresolved
    # as pointer consumers; this test cannot certify arena ownership.


def test_whole_ewram_resets_are_outside_the_initheap_reservation_contract(heap_rom):
    assert heap_rom[0x1E3B80:0x1E3B84] == bytes.fromhex("01df7047")  # BIOS RegisterRamReset
    assert heap_rom[0x0003AA:0x0003AC] == bytes.fromhex("ff20")  # startup RESET_ALL
    assert heap_rom[0x079B86:0x079B88] == bytes.fromhex("0120")  # ReloadSave RESET_EWRAM
    assert HEAP <= TAIL < TAIL + TAIL_SIZE <= 0x02040000
