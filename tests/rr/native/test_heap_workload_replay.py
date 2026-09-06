"""Actual allocator metadata replay of run65; Zeroed payload fill is not executed.

No BIOS stubs, game frames, ROM artifacts, capacity approval or arena ownership.
The Zeroed prefix is independently executed to its unsupported CpuSet boundary.
"""
import copy
import hashlib
import json
import os
import struct
from pathlib import Path

import pytest
import unicorn
from unicorn import UC_HOOK_CODE, UC_HOOK_INTR, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_SP,
)

from tests.rr.native.test_game_heap_cpu import (
    ALLOC,
    FREE,
    HEAP,
    INIT,
    ORIGINAL_SIZE,
    REDUCED_SIZE,
    TAIL,
    TAIL_SIZE,
    cpu,
)
from tests.rr.native.test_heap_tail_guard_cpu import TEST_CODE, guard  # noqa: F401
from tools.rr.reference import BASE_SHA256

FIXTURE_HASH = "9e92051e5d06b5bdaf8cb192cf532ed2c489bc1d8b9cd79e7353e40beb480a23"
RESULT_HASH = "2c3d2c472ebb1cf926f5ce9d6d2e784b33fab2e4371218d25e51628012d0c251"
ZEROED, ALLOC_INTERNAL, CPUSET, ASSERT = 0x08002BB0, 0x0800295C, 0x081E3B64, 0x081E3B14
FIELDS = ["root", "size", "free_bytes", "largest_free", "allocated_bytes", "header_bytes", "block_count"]


@pytest.fixture(scope="module")
def workload(rr_repo):
    raw = (rr_repo / "tests/rr/fixtures/heap_workload_65.json").read_bytes()
    # JSON is a text artifact; Git EOL conversion does not alter its identity.
    assert hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest() == FIXTURE_HASH
    result = json.loads(raw)
    assert result["schema"] == "slink-rr-heap-workload-v1" and result["source_result_sha256"] == RESULT_HASH
    assert result["metric_fields"] == FIELDS and len(result["operations"]) == 234
    assert [r["id"] for r in result["operations"]] == list(range(1, 235))
    assert result["initial_observation"] == {"unavailable": "uninitialized_or_invalid_extent"}
    assert all(result[k] is False for k in ("release_ready", "capacity_proof", "ownership_proof", "complete_peak_coverage"))
    return result


@pytest.fixture(scope="module")
def replay_rom(rr_rom_path):
    raw = rr_rom_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BASE_SHA256
    assert unicorn.__version__ == "2.1.4", "Explicit pinned Unicorn dependency required"
    return raw


def metadata(native):
    root, size = struct.unpack("<II", native.read(0x03000A38, 8))
    assert root == HEAP and size in (ORIGINAL_SIZE, REDUCED_SIZE), "unsupported heap extent"
    end, address, previous = root + size, root, root
    seen, free, largest, allocated = set(), 0, 0, 0
    while True:
        assert address not in seen and root <= address <= end - 16 and address % 4 == 0
        seen.add(address)
        flag, magic, length, prev, following = struct.unpack("<HHIII", native.read(address, 16))
        assert flag in (0, 1) and magic == 0xA3A3 and prev == previous
        assert length % 4 == 0 and address + 16 + length <= end
        assert following == (root if address + 16 + length == end else address + 16 + length)
        if flag:
            allocated += length
        else:
            free += length
            largest = max(largest, length)
        if following == root:
            result = [root, size, free, largest, allocated, len(seen) * 16, len(seen)]
            assert free + allocated + len(seen) * 16 == size
            return result
        previous, address = address, following


def reject_services(native):
    def interrupt(machine, number, user):
        raise AssertionError(f"unsupported guest service {number} at {machine.reg_read(UC_ARM_REG_PC):08X}")

    def assertion(machine, address, size, user):
        raise AssertionError("guest AGBAssert: replay allocation/free failed")

    native.cpu.hook_add(UC_HOOK_INTR, interrupt)
    native.cpu.hook_add(UC_HOOK_CODE, assertion, begin=ASSERT, end=ASSERT)
    assert native.stubs == {}


def zeroed_prefix(rom, ewram, iwram, requested, expected_heap, expected_pointer):
    """Stop before SWI0B; never fill RAM or fabricate a BIOS return."""
    native = cpu(rom)
    native.cpu.mem_write(HEAP, ewram)
    native.cpu.mem_write(0x03000000, iwram)
    reject_services(native)
    calls, stop = [], []

    def observe(machine, address, size, user):
        if address == ALLOC_INTERNAL:
            calls.append(address)
        elif address == CPUSET:
            stop.append([machine.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)])
            machine.emu_stop()

    native.cpu.hook_add(UC_HOOK_CODE, observe)
    for reg, value in ((UC_ARM_REG_SP, 0x03007E00), (UC_ARM_REG_LR, 0x01000001), (UC_ARM_REG_R0, requested)):
        native.cpu.reg_write(reg, value)
    native.cpu.emu_start(ZEROED | 1, 0x01000000, timeout=2_000_000, count=100_000)
    assert native.cpu.reg_read(UC_ARM_REG_PC) == CPUSET and calls == [ALLOC_INTERNAL] and len(stop) == 1
    source, destination, control = stop[0]
    rounded = (requested + 3) & ~3
    assert native.read(source, 4) == bytes(4) and destination == expected_pointer
    assert control == 0x05000000 | (rounded // 4)
    flag, magic, capacity, _, _ = struct.unpack("<HHIII", native.read(destination - 16, 16))
    assert flag == 1 and magic == 0xA3A3 and 0 < rounded <= capacity
    assert native.read(HEAP, ORIGINAL_SIZE) == expected_heap, "Zeroed prefix differs from Alloc metadata/payload"
    # Exact suffix after CpuSet: move retained pointer into r0 and restore stack/registers.
    assert rom[0x2B1C:0x2B26] == bytes.fromhex("281c01b030bc02bc0847")
    assert rom[0x1E3B64:0x1E3B68] == bytes.fromhex("0bdf7047")


def replay(rom, schedule, *, clipped_guard=None, prove_zeroed=False):
    assert unicorn.__version__ == "2.1.4"
    native = cpu(rom)
    reject_services(native)
    clipped = clipped_guard is not None
    if clipped:
        code = clipped_guard
        native.cpu.mem_map(TEST_CODE, 0x1000)
        native.cpu.mem_write(TEST_CODE, code)
        native.cpu.mem_write(INIT, bytes.fromhex("004a1047") + struct.pack("<I", TEST_CODE | 1))
    tail = bytes((i * 29 + 11) & 255 for i in range(TAIL_SIZE))
    if clipped:
        native.cpu.mem_write(TAIL, tail)
    upper = native.read(HEAP + ORIGINAL_SIZE, 0x40000 - ORIGINAL_SIZE)
    writes, scratch_writes = [], []
    boundary = TAIL if clipped else HEAP + ORIGINAL_SIZE
    # Actual AllocInternal uses three EWRAM search globals, separate from the pool.
    assert struct.unpack_from("<III", rom, 0x2998) == (0x02020004, 0x02020008, 0x0202000C)
    scratch_stores = {(0x08002962, 0x02020004), (0x08002966, 0x02020008),
                      (0x080029AE, 0x0202000C), (0x080029E6, 0x02020008)}

    def outside_write(machine, access, address, size, value, user):
        instruction = machine.reg_read(UC_ARM_REG_PC)
        if (instruction, address) in scratch_stores and size == 4:
            scratch_writes.append((instruction, address))
        else:
            writes.append((instruction, address, size))

    native.cpu.hook_add(UC_HOOK_MEM_WRITE, outside_write, begin=boundary, end=0x0203FFFF)
    live, samples, proof_count, reset_discarded, pointer_changes = {}, [], 0, [], 0
    for row in schedule:
        op, args = row["op"], row["args"]
        assert op in ("init", "alloc", "alloc_zeroed", "free")
        # Raw save backups before Init are outside the replay. Preserve unavailable
        # input as unknown; Init constructs real headers without fabricated repair.
        if not clipped and isinstance(row["before"], list):
            assert metadata(native) == row["before"], f"entry metadata gap at {row['id']}"
        elif isinstance(row["before"], dict):
            assert op == "init" and row["before"]["unavailable"] in ("invalid_header", "uninitialized_or_invalid_extent")
        if op == "init":
            assert args == {"root": HEAP, "size": ORIGINAL_SIZE}, "unsupported initialization"
            reset_discarded.append(len(live))
            native.call(INIT, [args["root"], args["size"]])
            live.clear()
        elif op in ("alloc", "alloc_zeroed"):
            old = row["pointer"]
            assert old and old not in live, "duplicate/invalid allocation identity"
            before_e = native.read(HEAP, 0x40000) if prove_zeroed and op == "alloc_zeroed" else None
            before_i = native.read(0x03000000, 0x8000) if before_e is not None else None
            # Deliberate metadata abstraction for Zeroed: actual Alloc, no payload fill.
            pointer = native.call(ALLOC, [args["size"]])
            assert pointer != 0, "allocation did not return owned storage"
            if not clipped:
                assert pointer == old, f"allocation pointer gap at {row['id']}"
            pointer_changes += pointer != old
            live[old] = pointer
            if before_e is not None:
                zeroed_prefix(rom, before_e, before_i, args["size"], native.read(HEAP, ORIGINAL_SIZE), pointer)
                proof_count += 1
        else:
            assert args["pointer"] in live, f"unknown free identity at {row['id']}"
            native.call(FREE, [live.pop(args["pointer"])])
        stats = metadata(native)
        if not clipped:
            assert stats == row["after"], f"post metadata gap at {row['id']}"
        observed_upper = bytearray(native.read(HEAP + ORIGINAL_SIZE, len(upper)))
        scratch_offset = 0x02020004 - (HEAP + ORIGINAL_SIZE)
        observed_upper[scratch_offset:scratch_offset + 12] = upper[scratch_offset:scratch_offset + 12]
        assert observed_upper == upper and not writes, f"unexpected non-pool write at {row['id']}: {writes}"
        if clipped:
            assert stats[1] == REDUCED_SIZE and native.read(TAIL, TAIL_SIZE) == tail
        samples.append(stats)
    return {"pairs": len(schedule), "zeroed_prefix_proofs": proof_count, "reset_discarded": reset_discarded,
            "min_free": min(s[2] for s in samples), "min_largest_free": min(s[3] for s in samples),
            "max_allocated": max(s[4] for s in samples), "pointer_changes": pointer_changes, "final": samples[-1],
            "verified_allocator_scratch_writes": len(scratch_writes),
            "classification": "allocator_metadata_schedule_abstraction", "zeroed_gameplay_execution": False,
            "complete_peak_coverage": False, "capacity_proof": False, "ownership_proof": False, "release_ready": False}


def test_original_heap_replay_exactly_matches_every_observed_pointer_and_post_snapshot(replay_rom, workload, record_property):
    for region in workload["rom_code_regions"]:
        offset = region["address"] - 0x08000000
        assert hashlib.sha256(replay_rom[offset:offset + region["size"]]).hexdigest() == region["sha256"]
    result = replay(replay_rom, workload["operations"], prove_zeroed=True)
    assert result["pairs"] == 234 and result["zeroed_prefix_proofs"] == 42
    assert result["reset_discarded"] == [0, 0, 2, 0, 0, 0, 0]
    assert result["min_free"] == result["min_largest_free"] == 11608
    record_property("source_result_sha256", RESULT_HASH)
    record_property("fixture_canonical_sha256", FIXTURE_HASH)
    record_property("replay", json.dumps(result, sort_keys=True))


def test_reduced_heap_replays_identical_logical_schedule_through_inactive_guard(guard, workload, rr_repo, record_property):  # noqa: F811
    rom, code, _ = guard
    # A reduced result is inadmissible until the same schedule passes baseline.
    replay(rom, workload["operations"])
    result = replay(rom, workload["operations"], clipped_guard=code)
    assert result["pairs"] == 234
    assert result["min_free"] == result["min_largest_free"] == 9560
    assert result["pointer_changes"] == 0 and result["max_allocated"] == 102232
    record_property("source_result_sha256", RESULT_HASH)
    record_property("replay", json.dumps(result, sort_keys=True))
    suffix = ".exe" if os.name == "nt" else ""
    toolchain = Path(os.environ["SLINK_ARMGCC"])
    provenance = {name: hashlib.sha256((toolchain / ("arm-none-eabi-" + name + suffix)).read_bytes()).hexdigest()
                  for name in ("gcc", "ld", "objcopy", "nm", "size", "as")}
    provenance["guard_source_lf"] = hashlib.sha256((rr_repo / "patch/research/heap_tail_guard.S").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    provenance["guard_binary"] = hashlib.sha256(code).hexdigest()
    provenance["unicorn_version"] = unicorn.__version__
    for path in ("tests/rr/native/test_heap_workload_replay.py", "tests/rr/native/test_heap_tail_guard_cpu.py",
                 "tests/rr/native/test_game_heap_cpu.py", "tests/rr/native/test_ghost_placement_cpu.py"):
        provenance[path] = hashlib.sha256((rr_repo / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    record_property("toolchain_and_guard", json.dumps(provenance, sort_keys=True))


@pytest.mark.parametrize("fault", ["unknown_free", "missing_alloc", "pointer_drift", "post_drift", "unsupported_init"])
def test_schedule_gaps_fail_instead_of_manufacturing_metadata(replay_rom, workload, fault):
    rows = copy.deepcopy(workload["operations"])
    if fault == "unknown_free":
        next(r for r in rows if r["op"] == "free")["args"]["pointer"] = HEAP + 0x1234
    elif fault == "missing_alloc":
        rows.pop(next(i for i, r in enumerate(rows) if r["op"] == "alloc"))
    elif fault == "pointer_drift":
        next(r for r in rows if r["op"] == "alloc")["pointer"] += 4
    elif fault == "post_drift":
        rows[0]["after"][2] -= 4
    else:
        rows[0]["args"]["size"] = REDUCED_SIZE
    with pytest.raises(AssertionError, match="identity|gap|initialization"):
        replay(replay_rom, rows)
