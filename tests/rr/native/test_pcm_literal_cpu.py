"""Bounded compressed-audio classification; not natural playback or arena ownership."""
import hashlib
import struct

from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R1, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_SP

from tests.rr.native.test_game_heap_cpu import cpu
from tests.rr.reference.test_withdrawal_oracle import ROM_SHA256


def test_ambiguous_tail_word_is_consumed_as_bounded_dpcm_bytes_by_actual_decoder(rr_rom_path):
    rom = rr_rom_path.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == ROM_SHA256
    header, target, entry = 0x09EBFAD0, 0x09EC112C, 0x081DC71C
    # Three exact headers and two format-consistent record boundaries. These
    # corroborate structure; no live channel/reference to this sample is claimed.
    for start, size, next_header, frequency in [
        (0x09EBCBD4, 23260, header, 32768000),
        (header, 98676, 0x09ECC1A8, 45158400),
    ]:
        assert struct.unpack_from("<HHIII", rom, start - 0x08000000) == (1, 0, frequency, 0, size)
        assert (start + 16 + ((size + 63) // 64) * 33 + 3) & ~3 == next_header
    assert struct.unpack_from("<HHIII", rom, 0x01ECC1A8) == (1, 0, 45158400, 0, 59922)
    assert struct.unpack_from("<I", rom, target - 0x08000000)[0] == 0x0201BDE0
    assert rom[entry - 0x08000000:entry - 0x08000000 + 8] == bytes.fromhex("e5402de92303a0e1")
    buffer, deltas = struct.unpack_from("<II", rom, 0x001DC7A0)
    assert (buffer, deltas) == (0x03002088, 0x084899F8)
    delta = struct.unpack_from("<16b", rom, deltas - 0x08000000)
    first = (target - header - 16) // 33
    last = (target + 3 - header - 16) // 33
    all_sample_reads = set()
    for block in range(first, last + 1):
        machine = cpu(rom)
        channel, stack, stop = 0x02010000, 0x03007E00, 0x01000000
        source = header + 16 + block * 33
        raw = rom[source - 0x08000000:source - 0x08000000 + 33]
        expected = [raw[0]]
        current = raw[0]
        for index, value in enumerate(raw[1:], 1):
            codes = (value & 15,) if index == 1 else (value >> 4, value & 15)
            for code in codes:
                current = (current + delta[code]) & 255
                expected.append(current)
        assert len(expected) == 64
        machine.w32(channel + 0x24, header)
        machine.w32(channel + 0x3C, 0xFFFFFFFF)
        reads, writes = [], []
        machine.cpu.hook_add(UC_HOOK_MEM_READ, lambda c, a, p, n, v, u: reads.append((p, n)))
        machine.cpu.hook_add(UC_HOOK_MEM_WRITE, lambda c, a, p, n, v, u: writes.append((p, n)))
        machine.cpu.reg_write(UC_ARM_REG_SP, stack)
        machine.cpu.reg_write(UC_ARM_REG_LR, stop)
        machine.cpu.reg_write(UC_ARM_REG_R3, block * 64)
        machine.cpu.reg_write(UC_ARM_REG_R4, channel)
        machine.cpu.emu_start(entry, stop, timeout=2_000_000, count=10000)
        assert machine.cpu.reg_read(UC_ARM_REG_PC) == stop
        assert machine.read(buffer, 64) == bytes(expected)
        assert machine.cpu.reg_read(UC_ARM_REG_R1) & 0xFFFFFFFF == (expected[0] if expected[0] < 128 else expected[0] - 256) & 0xFFFFFFFF
        sample_reads = [(p, n) for p, n in reads if source <= p < source + 33]
        assert sample_reads == [(source + i, 1) for i in range(33)]
        all_sample_reads.update(p for p, _ in sample_reads)
        assert all((buffer <= p and p + n <= buffer + 64)
                   or (channel + 0x3C <= p and p + n <= channel + 0x40)
                   or (stack - 24 <= p and p + n <= stack) for p, n in writes)
        assert not any(0x0201B800 <= p < 0x0201C000 for p, _ in reads + writes)
    assert set(range(target, target + 4)) <= all_sample_reads
