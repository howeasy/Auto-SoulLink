"""Unstubbed RR stage-reset primitive proves the seven bytes used by refresh."""
import hashlib
import struct

import pytest

from tests.rr.native.test_ghost_placement_cpu import NativeCPU
from tools.rr.reference import BASE_SHA256


@pytest.mark.parametrize("count", [2, 4])
def test_actual_rr_stage_reset_preserves_type3_and_resets_evasion(rr_rom_path, count):
    rom = rr_rom_path.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == BASE_SHA256
    # Actual routine: stride88, start gBattleMons+0x19, seven byte stores of6.
    assert rom[0x10A0608:0x10A0618].hex() == "58200b4a1278010051430622094bc918"
    assert struct.unpack_from("<III", rom, 0x10A0638) == (0x02023BCC, 0x02023BFD, 0x02023D74)
    native = NativeCPU((rom, {"ghost_cb": 0x0837A970}))
    raw = bytearray((i * 37 + 17) & 255 for i in range(4 * 88))
    native.cpu.mem_write(0x02023BE4, bytes(raw))
    native.w8(0x02023BCC, count)
    native.w32(0x02023D74, 0x02010000)
    expected = bytearray(raw)
    for bank in range(count):
        expected[bank * 88 + 0x19:bank * 88 + 0x20] = bytes([6] * 7)
    native.call(0x090A0608)
    assert native.read(0x02023BE4, 4 * 88) == expected
    assert struct.unpack("<I", native.read(0x02023D74, 4))[0] == 0x02010001
    assert not native.stubs
