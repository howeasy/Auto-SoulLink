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
import re
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


@pytest.mark.parametrize("pack,title", [
    ("gen3_frlg", "firered"), ("gen3_frlg", "leafgreen"), ("gen3_rr", "radical_red"),
])
def test_badge_first_flag_is_absent_from_every_frlg_rr_title(pack, title):
    """F9/F10: BADGE_FIRST_FLAG is genuinely Emerald-only -- not just missing from firered's
    profile, which the single-title check above would not have caught (leafgreen/radical_red
    ship their own profile.json)."""
    derived = json.loads(
        (REPO / "data" / "games" / pack / "profile.json").read_text(encoding="utf-8")
    )["titles"][title]["derived"]
    assert "BADGE_FIRST_FLAG" not in derived
    assert derived["SB1_BADGE_BYTE_OFFSET"] is not None


def test_read_badges_accepts_the_real_profile_decoded_through_json_codec():
    """FIRST FALSIFIER (F-A, coordinator-verified): decodes the shipped profile.json through
    `lua/json_codec.lua` in lupa, the same way `lua/gen3/entry.lua`'s `load_json` loads it for
    the real client -- NOT the plain `json.loads` the fakes above use, which hides the bug.
    `json_codec.lua` decodes a JSON null to the sentinel `M.null = {}` (json_codec.lua:4,174),
    not Lua `nil`; the real Emerald profile's `SB1_BADGE_BYTE_OFFSET` is JSON null, so it comes
    through as that sentinel table, not nil. Red before the fix: `read_badges`'s old
    `d.SB1_BADGE_BYTE_OFFSET ~= nil` guard saw the non-nil sentinel and refused with "profile
    derived sets both BADGE_FIRST_FLAG and SB1_BADGE_BYTE_OFFSET" even though only
    BADGE_FIRST_FLAG is really set. Physically seen in
    docs/gen3_emerald/probes/reads_pydec_emerald_2026-09-25.txt (RUN B)."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    json_codec = lua.eval(f'dofile("{(REPO / "lua" / "json_codec.lua").as_posix()}")')
    profile_text = (REPO / "data" / "games" / "gen3_emerald" / "profile.json").read_text(
        encoding="utf-8")
    decoded = json_codec.decode(profile_text)
    profile = decoded["titles"]["emerald"]
    # Control: the sentinel, not nil, is really what SB1_BADGE_BYTE_OFFSET decodes to (M.kind
    # tells null from nil by Lua-side identity, since a cross-language `==` on two proxy
    # wrappers of the same table is not reliable from Python) -- if this assertion itself ever
    # goes red, the bug this test targets no longer exists to catch.
    assert json_codec.kind(profile["derived"]["SB1_BADGE_BYTE_OFFSET"]) == "null"
    assert profile["derived"]["SB1_BADGE_BYTE_OFFSET"] is not None

    bus: dict[int, int] = {}

    def poke(addr: int, data: bytes) -> None:
        for i, b in enumerate(data):
            bus[addr + i] = b

    io_ = lua.table(
        read_u8=lambda a: bus.get(int(a), 0),
        read_u16=lambda a: sum(bus.get(int(a) + i, 0) << (8 * i) for i in range(2)),
        read_u32=lambda a: sum(bus.get(int(a) + i, 0) << (8 * i) for i in range(4)),
        read_bytes=lambda a, n: lua.table(*[bus.get(int(a) + i, 0) for i in range(int(n))]),
    )
    Reads = lua.eval(f'dofile("{(REPO / "lua" / "gen3" / "reads.lua").as_posix()}")')
    reads = Reads.new(profile, io_)

    poke(int(profile["ram"]["SB1_PTR_ADDR"]), SB1_ADDR.to_bytes(4, "little"))
    # synthetic SB1.flags: badge index 3 set (flag BADGE_FIRST_FLAG+3, byte 0x10D bit 2)
    poke(SB1_ADDR + SB1_FLAGS_OFFSET + 0x10C, bytes([0x00, 0b0000_0100]))

    result = reads.read_badges()
    assert result == 0b0000_1000, f"expected a badge mask (0b1000), got a refusal: {result!r}"


def test_read_badges_refuses_a_profile_that_sets_both_derived_fields():
    """F10: a profile carrying both BADGE_FIRST_FLAG and a non-null SB1_BADGE_BYTE_OFFSET is
    self-contradictory (one says "straddled, read per-bit", the other "shares one byte") --
    read_badges() refuses by name (nil, reason) rather than silently picking a side."""
    doctored = dict(_PROFILE)
    doctored["derived"] = dict(_PROFILE["derived"])
    doctored["derived"]["SB1_BADGE_BYTE_OFFSET"] = 0x104
    h = ReadsHarness(profile=doctored)
    value, why = h.reads.read_badges()
    assert value is None
    assert "BADGE_FIRST_FLAG" in why and "SB1_BADGE_BYTE_OFFSET" in why


def test_decode_badges_for_profile_refuses_a_profile_that_sets_both_derived_fields():
    """The pydec mirror of the refusal above (F10)."""
    doctored_derived = dict(_PROFILE["derived"])
    doctored_derived["SB1_BADGE_BYTE_OFFSET"] = 0x104
    value, why = pydec.decode_badges_for_profile(bytes(0x20), doctored_derived)
    assert value is None
    assert "BADGE_FIRST_FLAG" in why and "SB1_BADGE_BYTE_OFFSET" in why


def test_decode_badges_for_profile_agrees_with_read_badges_on_the_straddle():
    """The pydec dispatcher (decode_badges_for_profile) picking the straddle path agrees with
    reads.lua's read_badges on the same bytes -- the profile-driven dispatch on both sides of
    PLAN §5.7, not just the raw decoders."""
    h = ReadsHarness()
    flags = _place_flags(h, byte_0x10c=0b1000_0000, byte_0x10d=0b1101_0101)
    got = h.reads.read_badges()
    want, why = pydec.decode_badges_for_profile(bytes(flags), _PROFILE["derived"])
    assert why is None
    assert got == want == 0b1010_1011


def test_p4_c4_2a_emerald_badge_constants_match_the_pinned_pret_header() -> None:
    """F5: re-derive BADGE_FIRST_FLAG and SB1_FLAGS_OFFSET from the pinned pret pokeemerald
    checkout, independent of tools/gen_gen3_profile.py's own EMERALD_DERIVED copies -- the
    FR pattern (tests/unit/test_gen3_profile.py:502-531), so this harness is not
    self-referential against the generator it is meant to check."""
    pin_dir = pathlib.Path("E:/Google Drive/SLink/.cache/pret/pokeemerald")
    if not pin_dir.exists():
        pytest.skip(f"pokeemerald not cloned: {pin_dir} (BADGE_FIRST_FLAG is still "
                    "pinned in tools/gen_gen3_profile.py:EMERALD_DERIVED with a file:line citation)")
    flags_h = (pin_dir / "include" / "constants" / "flags.h").read_text(encoding="utf-8")
    global_h = (pin_dir / "include" / "global.h").read_text(encoding="utf-8")

    # SYSTEM_FLAGS (TRAINER_FLAGS_END + 1) is a chained macro; its pinned value 0x860 is cited
    # in the header's own trailing comment (mirrors test_gen3_profile.py's SYS_FLAGS handling --
    # not re-expanded from TRAINER_FLAGS_END here, just cross-checked).
    m = re.search(r"^#define SYSTEM_FLAGS\s+\(TRAINER_FLAGS_END \+ 1\) // (0x[0-9A-Fa-f]+)",
                  flags_h, re.M)
    assert m, "SYSTEM_FLAGS definition not found in pret's flags.h"
    system_flags = int(m[1], 16)
    m = re.search(r"^#define FLAG_BADGE01_GET\s+\(SYSTEM_FLAGS \+ (0x[0-9A-Fa-f]+)\)",
                  flags_h, re.M)
    assert m, "FLAG_BADGE01_GET definition not found in pret's flags.h"
    badge01_offset = int(m[1], 16)
    assert system_flags + badge01_offset == BADGE_FIRST_FLAG == 0x867

    m = re.search(r"/\*(0x[0-9A-Fa-f]+)\*/ u8 flags\[NUM_FLAG_BYTES\];", global_h)
    assert m, "SaveBlock1.flags[] offset comment not found in pret's global.h"
    assert int(m[1], 16) == SB1_FLAGS_OFFSET == 0x1270
