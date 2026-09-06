"""Lua heap observations against actual RR allocator headers; no gameplay claim."""
import hashlib

from lupa import LuaRuntime

from tests.rr.native.test_ghost_placement_cpu import NativeCPU
from tools.rr.reference import BASE_SHA256


def test_snapshot_tracks_actual_rr_splits_free_coalescing_and_reinitialization(rr_repo, rr_rom_path):
    rom = rr_rom_path.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == BASE_SHA256
    native = NativeCPU((rom, {"ghost_cb": 0x0837A970}))
    lua = LuaRuntime(unpack_returned_tuples=True)
    heap = lua.execute((rr_repo / "lua/rr/heap_snapshot.lua").read_text())
    io = lua.table_from({"read_u16_le": lambda a: int.from_bytes(native.read(a, 2), "little"),
                         "read_u32_le": lambda a: int.from_bytes(native.read(a, 4), "little")})

    def snapshot():
        before = native.read(0x02000000, 0x40000)
        result, why = heap.read(io, lambda: 1)
        assert why is None
        assert result.free_bytes + result.allocated_bytes + result.header_bytes == result.size
        assert native.read(0x02000000, 0x40000) == before
        return result

    native.call(0x08002B80, [0x02000000, 0x1C000])
    initial = snapshot()
    assert initial.free_bytes == initial.largest_free == 0x1C000 - 16
    allocations = [native.call(0x08002B9C, [size]) for size in (512, 2048, 1024)]
    used = snapshot()
    assert used.block_count == 4 and used.allocated_bytes == 3584
    native.call(0x08002BC4, [allocations[1]])
    fragmented = snapshot()
    assert fragmented.free_bytes > fragmented.largest_free
    for address in (allocations[0], allocations[2]):
        native.call(0x08002BC4, [address])
    cleared = snapshot()
    assert cleared.block_count == 1 and cleared.free_bytes == initial.free_bytes
    native.call(0x08002B80, [0x02000000, 0x1B800])
    reduced = snapshot()
    assert reduced.size == 0x1B800 and reduced.free_bytes == 0x1B800 - 16
    assert not native.stubs
