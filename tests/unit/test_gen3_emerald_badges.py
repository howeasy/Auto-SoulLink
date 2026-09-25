"""E2-ENTRY+BADGE: the Emerald badge straddle (FLAG_BADGE01_GET = SYSTEM_FLAGS+7 = 0x867,
pret include/constants/flags.h:1359) against `lua/gen3/reads.lua` and the independent PYDEC
oracle `tools/gen3_reads_pydec.py`.

Unlike FR/LG/RR, whose 8 badge bits share one SaveBlock1.flags byte (SB1_BADGE_BYTE_OFFSET),
Emerald's flag ids 0x867..0x86E straddle two bytes: byte 0x10C bit 7 (badge 1), then byte
0x10D bits 0-6 (badges 2-8). `profile.derived.BADGE_FIRST_FLAG` (0x867) carries the flag id;
`SB1_BADGE_BYTE_OFFSET` stays null. Standalone lupa harness, deliberately not the shared
`tests/unit/gen3_world.py` World (that fixture's PACK_DIRS only knows gen3_frlg/gen3_rr, and
gen3_emerald must not be routed before EG4) -- lua/gen3/reads.lua is loaded and driven
directly, the same technique test_gen3_reads.py's charmap test uses.
"""
from __future__ import annotations

import json
import pathlib
import sys

import lupa
import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
_PROFILE = json.loads(
    (REPO / "data" / "games" / "gen3_emerald" / "profile.json").read_text(encoding="utf-8")
)["titles"]["emerald"]

sys.path.insert(0, str(REPO / "tools"))
import gen3_reads_pydec as pydec  # noqa: E402

SB1_ADDR = 0x02010000
BADGE_FIRST_FLAG = _PROFILE["derived"]["BADGE_FIRST_FLAG"]
SB1_FLAGS_OFFSET = _PROFILE["derived"]["SB1_FLAGS_OFFSET"]


def test_the_derived_flag_id_and_straddle_are_the_ones_the_card_pins():
    assert BADGE_FIRST_FLAG == 0x867
    assert _PROFILE["derived"]["SB1_BADGE_BYTE_OFFSET"] is None
    # byte 0x10C bit 7 (badge 1: flag 0x867), byte 0x10D bits 0-6 (badges 2-8: 0x868..0x86E)
    assert BADGE_FIRST_FLAG >> 3 == 0x10C and BADGE_FIRST_FLAG & 7 == 7
    assert (BADGE_FIRST_FLAG + 7) >> 3 == 0x10D and (BADGE_FIRST_FLAG + 7) & 7 == 6


class ReadsHarness:
    """A fake GBA bus (sparse dict) + `lua/gen3/reads.lua` loaded and driven directly."""

    def __init__(self, profile=_PROFILE):
        self.bus: dict[int, int] = {}
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        L = self.lua
        io_ = L.table(
            read_u8=lambda a: self.bus.get(int(a), 0),
            read_u16=lambda a: sum(self.bus.get(int(a) + i, 0) << (8 * i) for i in range(2)),
            read_u32=lambda a: sum(self.bus.get(int(a) + i, 0) << (8 * i) for i in range(4)),
            read_bytes=lambda a, n: L.table(*[self.bus.get(int(a) + i, 0) for i in range(int(n))]),
        )
        Reads = L.eval(f'dofile("{(REPO / "lua" / "gen3" / "reads.lua").as_posix()}")')
        self.reads = Reads.new(L.table_from(profile, recursive=True), io_)
        self.poke(profile["ram"]["SB1_PTR_ADDR"], SB1_ADDR.to_bytes(4, "little"))

    def poke(self, addr: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.bus[addr + i] = b


def _place_flags(harness: ReadsHarness, byte_0x10c: int, byte_0x10d: int,
                  neighbour_0x10b: int = 0xA5, neighbour_0x10e: int = 0x5A) -> bytearray:
    """Lay out a synthetic SaveBlock1.flags[] array with the two straddled bytes plus
    adversarial neighbours (catches an off-by-one byte-offset bug that would read one byte
    over or under)."""
    flags = bytearray(0x200)
    flags[0x10B], flags[0x10C], flags[0x10D], flags[0x10E] = (
        neighbour_0x10b, byte_0x10c, byte_0x10d, neighbour_0x10e)
    harness.poke(SB1_ADDR + SB1_FLAGS_OFFSET, bytes(flags))
    return flags


def test_read_badges_isolates_one_bit_per_badge_hand_verified():
    """Hand-verified control, independent of both implementations: only badge index 3 (flag
    0x867+3 = 0x86A, bit 2 of byte 0x10D) is set."""
    h = ReadsHarness()
    _place_flags(h, byte_0x10c=0x00, byte_0x10d=0b0000_0100)
    assert h.reads.read_badges() == 0b0000_1000  # badge index 3 -> out bit 3


def test_read_badges_matches_pydec_on_the_straddle():
    """Adversarial pattern exercising both bytes and every bit, cross-checked against the
    independent PYDEC decoder (tools/gen3_reads_pydec.py:decode_badges_straddle)."""
    h = ReadsHarness()
    flags = _place_flags(h, byte_0x10c=0b1000_0000, byte_0x10d=0b1101_0101)
    got = h.reads.read_badges()
    want = pydec.decode_badges_straddle(bytes(flags), BADGE_FIRST_FLAG)
    assert got == want == 0b1010_1011


@pytest.mark.parametrize("byte_0x10c,byte_0x10d", [
    (0x00, 0x00), (0xFF, 0xFF), (0x80, 0x00), (0x00, 0x7F), (0x7F, 0x80),
])
def test_read_badges_agrees_with_pydec_across_bit_patterns(byte_0x10c, byte_0x10d):
    h = ReadsHarness()
    flags = _place_flags(h, byte_0x10c, byte_0x10d)
    assert h.reads.read_badges() == pydec.decode_badges_straddle(bytes(flags), BADGE_FIRST_FLAG)


def test_a_pack_without_badge_first_flag_keeps_the_single_byte_path():
    """FR/LG/RR unaffected: no derived.BADGE_FIRST_FLAG means read_badges() still reads the
    one SB1_BADGE_BYTE_OFFSET byte, unchanged."""
    frlg = json.loads(
        (REPO / "data" / "games" / "gen3_frlg" / "profile.json").read_text(encoding="utf-8")
    )["titles"]["firered"]
    assert "BADGE_FIRST_FLAG" not in frlg["derived"]
    h = ReadsHarness(profile=frlg)
    byte_addr = frlg["derived"]["SB1_FLAGS_OFFSET"] + frlg["derived"]["SB1_BADGE_BYTE_OFFSET"]
    h.poke(SB1_ADDR + 0, bytes(0x1300))  # pad zeroes up to and past byte_addr
    h.poke(SB1_ADDR + byte_addr, bytes([0b0000_0011]))
    assert h.reads.read_badges() == pydec.decode_badges(0b0000_0011) == 0x03
