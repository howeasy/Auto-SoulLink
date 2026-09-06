"""Compile inactive guard and execute an in-memory entry detour against stock RR.

Only the CPU's private ROM mapping is patched. No ROM artifact is emitted. The
test address is outside this harness's stock-ROM mapping, not claimed free space
in the GBA cartridge address space (which also has hardware mirror windows).
"""
import hashlib
import os
import struct
import subprocess
from pathlib import Path

import pytest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (
    UC_ARM_REG_CPSR,
    UC_ARM_REG_LR,
    UC_ARM_REG_PC,
    UC_ARM_REG_R0,
    UC_ARM_REG_R1,
    UC_ARM_REG_R2,
    UC_ARM_REG_R3,
    UC_ARM_REG_R4,
    UC_ARM_REG_R5,
    UC_ARM_REG_R6,
    UC_ARM_REG_R7,
    UC_ARM_REG_R8,
    UC_ARM_REG_R9,
    UC_ARM_REG_R10,
    UC_ARM_REG_R11,
    UC_ARM_REG_R12,
    UC_ARM_REG_SP,
)

from tests.rr.native.test_game_heap_cpu import (
    DIRECT_INIT_CALLS,
    HEAP,
    INIT,
    ORIGINAL_SIZE,
    REDUCED_SIZE,
    TAIL,
    TAIL_SIZE,
    cpu,
)
from tests.rr.reference.test_withdrawal_oracle import ROM_SHA256

TEST_CODE = 0x0A100000
REGISTERS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
             UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
             UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
             UC_ARM_REG_R12, UC_ARM_REG_SP]


@pytest.fixture(scope="module")
def guard(rr_repo, rr_rom_path, tmp_path_factory):
    rom = rr_rom_path.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == ROM_SHA256
    raw = os.environ.get("SLINK_ARMGCC")
    if not raw:
        pytest.fail("set SLINK_ARMGCC to the pinned ARM toolchain", pytrace=False)
    directory = tmp_path_factory.mktemp("inactive_heap_guard")
    tools = Path(raw)
    suffix = ".exe" if os.name == "nt" else ""
    source = rr_repo / "patch/research/heap_tail_guard.S"
    obj, elf, binary = (directory / filename for filename in ("guard.o", "guard.elf", "guard.bin"))
    commands = [
        [str(tools / ("arm-none-eabi-gcc" + suffix)), "-mthumb", "-mcpu=arm7tdmi", "-ffreestanding", "-c", str(source), "-o", str(obj)],
        [str(tools / ("arm-none-eabi-ld" + suffix)), "-Ttext=" + hex(TEST_CODE), "-e", "slink_heap_tail_guard", str(obj), "-o", str(elf)],
        [str(tools / ("arm-none-eabi-objcopy" + suffix)), "-O", "binary", str(elf), str(binary)],
    ]
    for command in commands:
        result = subprocess.run(command, text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
    nm = subprocess.run([str(tools / ("arm-none-eabi-nm" + suffix)), "-n", str(elf)], capture_output=True, text=True, check=True)
    symbols = {parts[2]: int(parts[0], 16) for line in nm.stdout.splitlines() if len(parts := line.split()) == 3}
    # Inactive helper must not introduce a mutable native data section.
    sections = subprocess.run([str(tools / ("arm-none-eabi-size" + suffix)), str(elf)], capture_output=True, text=True, check=True)
    row = sections.stdout.splitlines()[1].split()
    assert int(row[1]) == int(row[2]) == 0
    assert symbols["slink_heap_tail_guard"] == TEST_CODE
    assert rom[INIT - 0x08000000:INIT - 0x08000000 + 8] == bytes.fromhex("00b5044a1060044a")
    return rom, binary.read_bytes(), symbols


def prepared(guard, start, size, patched, stack=0x03007E00):
    rom, code, symbols = guard
    native = cpu(rom)
    native.cpu.mem_write(0x02000000, b"\x5A" * 0x40000)
    native.cpu.mem_write(0x03000000, b"\x6B" * 0x8000)
    native.cpu.mem_map(TEST_CODE, 0x1000)
    native.cpu.mem_write(TEST_CODE, code)
    if patched:
        # Thumb literal detour, in private CPU memory only.
        native.cpu.mem_write(INIT, bytes.fromhex("004a1047") + struct.pack("<I", TEST_CODE | 1))
    for index, reg in enumerate(REGISTERS[:13]):
        native.cpu.reg_write(reg, (0x11223300 + index * 0x10101) & 0xFFFFFFFF)
    native.cpu.reg_write(UC_ARM_REG_SP, stack)
    native.cpu.reg_write(UC_ARM_REG_LR, 0x01000001)
    native.cpu.reg_write(UC_ARM_REG_R0, start)
    native.cpu.reg_write(UC_ARM_REG_R1, size)
    return native, symbols


def run(native):
    native.cpu.emu_start(INIT | 1, 0x01000000, timeout=2_000_000, count=100_000)
    assert native.cpu.reg_read(UC_ARM_REG_PC) == 0x01000000
    return [native.cpu.reg_read(reg) for reg in REGISTERS]


@pytest.mark.parametrize("start,size,effective", [
    (HEAP, ORIGINAL_SIZE, REDUCED_SIZE), (HEAP, REDUCED_SIZE, REDUCED_SIZE),
    (HEAP, 0x1000, 0x1000), (HEAP + 0x1000, 0x1B000, 0x1A800),
    (TAIL - 16, 0x810, 16), (TAIL + TAIL_SIZE, 0x1000, 0x1000),
])
@pytest.mark.parametrize("stack", [0x03007E00, 0x03007DFC])
def test_guard_replays_stock_register_stack_and_header_semantics(guard, start, size, effective, stack):
    observed, _ = prepared(guard, start, size, True, stack)
    reference, _ = prepared(guard, start, effective, False, stack)
    before_tail = observed.read(TAIL, TAIL_SIZE)
    writes = []
    observed.cpu.hook_add(UC_HOOK_MEM_WRITE, lambda c, a, p, s, v, u: writes.append((p, s)), begin=TAIL, end=TAIL + TAIL_SIZE - 1)
    assert run(observed) == run(reference)
    assert observed.read(0x02000000, 0x40000) == reference.read(0x02000000, 0x40000)
    assert observed.read(0x03000000, 0x8000) == reference.read(0x03000000, 0x8000)
    assert observed.read(TAIL, TAIL_SIZE) == before_tail and not writes
    assert observed.cpu.reg_read(UC_ARM_REG_CPSR) & 0xF0000000 == reference.cpu.reg_read(UC_ARM_REG_CPSR) & 0xF0000000


@pytest.mark.parametrize("start,size", [(TAIL, 0x800), (TAIL + 4, 32), (TAIL - 8, 0x810),
                                       (HEAP + 1, 0x100), (HEAP, 15), (HEAP, 17),
                                       (0x01FFFFFC, 32), (0x0203FFF0, 32), (0xFFFFFFFC, 32)])
def test_unsupported_ranges_stop_before_any_ram_or_stack_mutation(guard, start, size):
    native, symbols = prepared(guard, start, size, True)
    ewram, iwram = native.read(0x02000000, 0x40000), native.read(0x03000000, 0x8000)
    before = [native.cpu.reg_read(reg) for reg in REGISTERS[4:]]
    reached = []

    def stop(machine, address, length, user):
        reached.append(address)
        machine.emu_stop()  # Observe rejection; never fabricate a successful InitHeap return.

    native.cpu.hook_add(UC_HOOK_CODE, stop, begin=symbols["slink_heap_tail_reject"], end=symbols["slink_heap_tail_reject"])
    native.cpu.emu_start(INIT | 1, 0x01000000, timeout=2_000_000, count=100_000)
    assert reached == [symbols["slink_heap_tail_reject"]]
    assert native.read(0x02000000, 0x40000) == ewram and native.read(0x03000000, 0x8000) == iwram
    assert [native.cpu.reg_read(reg) for reg in REGISTERS[4:]] == before
    assert native.cpu.reg_read(UC_ARM_REG_LR) == 0x01000001


@pytest.mark.parametrize("caller", DIRECT_INIT_CALLS)
def test_every_decoded_callsite_uses_the_entry_detour_without_changing_its_return(guard, caller):
    native, _ = prepared(guard, HEAP, ORIGINAL_SIZE, True)
    return_address = caller + 4
    reached = []

    def stop(machine, address, size, user):
        reached.append(address)
        machine.emu_stop()

    native.cpu.hook_add(UC_HOOK_CODE, stop, begin=return_address, end=return_address)
    # Caller argument setup was separately decoded; execute its actual BL rather
    # than executing unrelated scene side effects after return.
    native.cpu.emu_start(caller | 1, 0x01000000, timeout=2_000_000, count=100_000)
    assert reached == [return_address]
    assert native.cpu.reg_read(UC_ARM_REG_R0) == return_address | 1
    assert native.cpu.reg_read(UC_ARM_REG_SP) == 0x03007E00
    assert native.read(0x03000A38, 8) == struct.pack("<II", HEAP, REDUCED_SIZE)


def test_research_helper_is_outside_the_production_source_glob(rr_repo):
    source = rr_repo / "patch/research/heap_tail_guard.S"
    assert source.is_file() and not (rr_repo / "patch/src/heap_tail_guard.S").exists()
    build = (rr_repo / "patch/tools/build.py").read_text()
    assert "heap_tail_guard" not in build and "patch/research" not in build


def test_actual_gamecube_size_parser_accepts_a_transfer_crossing_the_candidate_tail(guard):
    native, _ = prepared(guard, HEAP, ORIGINAL_SIZE, True)
    run(native)
    native.cpu.mem_map(0x04000000, 0x1000)
    control, io = 0x03007000, 0x04000120
    native.w8(control + 2, 0)
    native.w32(io + 0x30, 0x3FFF)
    native.cpu.reg_write(UC_ARM_REG_R0, control)
    native.cpu.reg_write(UC_ARM_REG_R3, io)
    stops = []

    def stop(machine, address, size, user):
        stops.append(address)
        machine.emu_stop()

    native.cpu.hook_add(UC_HOOK_CODE, stop, begin=0x081DBF72, end=0x081DBF72)
    # Begin after the earlier receive-complete branch: synthetic peripheral input,
    # not a claim that a supported BizHawk peer can deliver this handshake.
    native.cpu.emu_start(0x081DBF59, 0x01000000, timeout=2_000_000, count=100_000)
    assert stops == [0x081DBF72]
    count = struct.unpack("<H", native.read(control + 0x12, 2))[0]
    base, current = struct.unpack("<II", native.read(control + 0x20, 8))
    assert count == 0x8000 and base == current == HEAP
    assert base + count * 4 == 0x02020000 > TAIL + TAIL_SIZE


def test_actual_gamecube_receive_store_bypasses_the_reduced_allocator(guard):
    native, _ = prepared(guard, HEAP, ORIGINAL_SIZE, True)
    run(native)
    native.cpu.mem_map(0x04000000, 0x1000)
    control, io = 0x03007000, 0x04000120
    native.w32(control + 0x24, TAIL)
    native.w16(control + 0x12, 1)
    native.w32(io + 0x30, 0x13579BDF)
    native.cpu.reg_write(UC_ARM_REG_R0, control)
    native.cpu.reg_write(UC_ARM_REG_R1, 1)  # synthetic receive-complete flag
    native.cpu.reg_write(UC_ARM_REG_R3, io)
    stops = []

    def stop(machine, address, size, user):
        stops.append(address)
        machine.emu_stop()

    native.cpu.hook_add(UC_HOOK_CODE, stop, begin=0x081DBF8C, end=0x081DBF8C)
    native.cpu.emu_start(0x081DBF79, 0x01000000, timeout=2_000_000, count=100_000)
    assert stops == [0x081DBF8C]
    assert native.read(TAIL, 4) == struct.pack("<I", 0x13579BDF)
    assert native.cpu.reg_read(UC_ARM_REG_R2) == TAIL + 4
    assert native.read(0x03000A38, 8) == struct.pack("<II", HEAP, REDUCED_SIZE)


def test_pinned_gamecube_startup_transfer_and_normal_quit_paths(guard):
    rom = guard[0]
    # Actual RR source-literal and instruction anchors. Stop-program execution
    # follows receipt progress2, while progress0 restores the normal serial handler.
    assert struct.unpack_from("<I", rom, 0x0EC770)[0] == 0x0203AAD4
    assert rom[0x0EC7BC:0x0EC7C2] == bytes.fromhex("a87802281dd1")
    assert struct.unpack_from("<I", rom, 0x0EC7EC)[0] == 0x65366347
    assert struct.unpack_from("<I", rom, 0x0EC7F0)[0] == 0x08703860
    assert rom[0x0EC7CE:0x0EC7D6] == bytes.fromhex("80218904a0225202")
    assert (0xA0 << 9) * 2 == 0x28000  # CpuSet halfword-count, not a byte count
    assert rom[0x0EC7F4:0x0EC7F8] == bytes.fromhex("eff0effb")


def test_actual_colosseum_handoff_selects_a_bulk_copy_over_the_reserved_tail(guard):
    native, _ = prepared(guard, HEAP, ORIGINAL_SIZE, True)
    run(native)
    native.w8(0x0203AAD4 + 2, 2)
    native.w32(HEAP + 0xAC, 0x65366347)
    native.cpu.reg_write(UC_ARM_REG_R5, 0x0203AAD4)
    stops = []

    def stop(machine, address, size, user):
        stops.append(address)
        machine.emu_stop()  # Capture the actual BIOS-call arguments, not a synthetic copy result.

    native.cpu.hook_add(UC_HOOK_CODE, stop, begin=0x081E3B64, end=0x081E3B64)
    native.cpu.emu_start(0x080EC7BD, 0x01000000, timeout=2_000_000, count=100_000)
    assert stops == [0x081E3B64]
    assert native.cpu.reg_read(UC_ARM_REG_R0) == 0x08703860
    destination = native.cpu.reg_read(UC_ARM_REG_R1)
    count = native.cpu.reg_read(UC_ARM_REG_R2)
    assert destination == HEAP and count == 0x14000
    assert destination <= TAIL and destination + count * 2 > TAIL + TAIL_SIZE
