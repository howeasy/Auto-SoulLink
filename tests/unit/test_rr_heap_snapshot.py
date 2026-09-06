from pathlib import Path

import pytest
from lupa import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    lua = LuaRuntime(unpack_returned_tuples=True)
    ram = {}

    def write(address, value, width=4):
        for i in range(width):
            ram[address + i] = value >> (i * 8) & 255

    def read(address, width):
        return sum(ram.get(address + i, 0) << (i * 8) for i in range(width))

    io = lua.table_from({"read_u16_le": lambda a: read(a, 2), "read_u32_le": lambda a: read(a, 4)})
    write(0x03000A38, 0x02000000)
    write(0x03000A3C, 112)
    # One allocated16B block and two free blocks32/16, each with a16B header.
    for address, used, size, prev, nxt in [(0x02000000, 1, 16, 0x02000000, 0x02000020),
                                        (0x02000020, 0, 32, 0x02000000, 0x02000050),
                                        (0x02000050, 0, 16, 0x02000020, 0x02000000)]:
        write(address, used, 2)
        write(address + 2, 0xA3A3, 2)
        write(address + 4, size)
        write(address + 8, prev)
        write(address + 12, nxt)
    module = lua.execute((ROOT / "lua/rr/heap_snapshot.lua").read_text())
    return module, io, ram, write


def test_capacity_and_fragmentation_are_distinct_readonly_observations():
    heap, io, ram, _ = fixture()
    before = dict(ram)
    result, why = heap.read(io, lambda: 123)
    assert why is None
    assert (result.free_bytes, result.largest_free, result.allocated_bytes, result.header_bytes) == (48, 32, 16, 48)
    assert result.block_count == 3 and result.capacity_proof is False and result.ownership_proof is False
    assert result.free_bytes + result.allocated_bytes + result.header_bytes == result.size
    assert ram == before


@pytest.mark.parametrize("address,value,width,reason", [
    (0x03000A38, 0, 4, "uninitialized_or_invalid_extent"),
    (0x02000002, 0, 2, "invalid_header"),
    (0x02000000, 2, 2, "invalid_header"),
    (0x02000004, 10000, 4, "invalid_block_extent"),
    (0x02000028, 0x02000020, 4, "invalid_previous_link"),
    (0x0200002C, 0x02000000, 4, "invalid_next_link"),
    (0x0200005C, 0x02000050, 4, "invalid_next_link"),
])
def test_invalid_heap_never_becomes_free_capacity(address, value, width, reason):
    heap, io, _, write = fixture()
    write(address, value, width)
    assert heap.read(io, lambda: 123) == (None, reason)


def test_frame_change_and_bounded_scan_are_unavailable_not_empty_heap():
    heap, io, _, _ = fixture()
    frames = iter([123, 124])
    assert heap.read(io, lambda: next(frames)) == (None, "context_changed")
    assert heap.read(io, lambda: 123, 2) == (None, "block_budget_exceeded")
