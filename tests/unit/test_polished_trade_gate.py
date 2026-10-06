"""Polished trade slice 2a: the two bank-$7E special gates (patch/polished/src/trade_gate.asm).

The overlay re-points SpecialsPointers entries 2 and 3 (Special_WaitForLinkedFriend,
Special_CheckLinkTimeout) at SlinkTradeWaitGate / SlinkTradeTimeoutGate. A trade request
(wChosenCableClubRoom == LINK_TRADECENTER - 1 == 1) is answered in the gate; a battle request
tail-calls the ORIGINAL special with farjp. No script byte changes.

Evidence here: (a) the committed UPS applied to the pinned release ROM changes exactly the six table
bytes of the table and they equal the gate addresses in the committed sym; (b) source shape;
(c) the REAL gate bytes from that ROM run through a tiny SM83 interpreter (only the opcodes the gates
use; anything else fails closed), with red controls that mutate the ROM bytes.

Absent input skips; present-but-wrong input fails.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "patch" / "tools"))

import build_polished_companion as pc  # noqa: E402
from build_gen2_companion import _symbols  # noqa: E402
from make_ups import ups_apply  # noqa: E402

RELEASE = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"
CLEAN_SYM = REPO / "data/polished/polishedcrystal.sym"
OVERLAY_SYM = REPO / "data/polished/polished_slink.sym"
UPS = REPO / "patch/dist/SLink-Polished.ups"
SRC = REPO / "patch/polished/src/trade_gate.asm"

H_SCRIPT_VAR, H_SCRIPT_BANK, H_SCRIPT_POS = 0xFF85, 0xFFEB, 0xFFEC
ROOM_ADDR = 0xD26B   # wChosenCableClubRoom, from the committed sym (asserted below)
TRADE_ROOM, BATTLE_ROOM = 1, 2


@pytest.fixture(scope="module")
def syms():
    return _symbols(CLEAN_SYM), _symbols(OVERLAY_SYM)


@pytest.fixture(scope="module")
def rom():
    if not RELEASE.is_file():
        pytest.skip(f"pinned Polished release ROM not cached at {RELEASE}")
    return RELEASE.read_bytes(), ups_apply(RELEASE.read_bytes(), UPS.read_bytes())


# ------------------------------------------------------------------ (a) the table bytes in the built ROM

def test_the_table_changes_only_the_two_gated_entries(rom, syms):
    clean, new = syms
    base, patched = rom
    table = pc._flat(*clean["Special_WaitForLinkedFriendSpecial"])
    for i, (native, gate) in enumerate(pc.TRADE_GATES):
        at = table + 3 * i
        assert clean[native + "Special"] == new[native + "Special"] == (3, 0x4030 + 3 * i)
        assert base[at:at + 3] == bytes([clean[native][0]]) + clean[native][1].to_bytes(2, "little")
        assert patched[at:at + 3] == bytes([0x7E]) + new[gate][1].to_bytes(2, "little")
        assert new[gate][0] == 0x7E
    # every OTHER byte of the table (SpecialsPointers .. +3*entries) is the clean ROM's
    start = pc._flat(*clean["SpecialsPointers"])
    changed = [i for i in range(start, start + 3 * 0x80) if base[i] != patched[i]]
    assert changed and all(table <= i < table + 6 for i in changed), changed


# ------------------------------------------------------------------ (b) source shape

def test_source_discriminator_and_native_tail_calls():
    src = SRC.read_text(encoding="utf-8")
    assert src.count("ld a, [wChosenCableClubRoom]") == 2
    assert src.count("cp LINK_TRADECENTER - 1") == 2
    assert src.count("jr nz, .native") == 2
    assert "farjp Special_WaitForLinkedFriend\n" in src and "farjp Special_CheckLinkTimeout\n" in src
    assert "wLinkMode" not in src and "wPlayerLinkAction" not in src
    # the redirect target is the clean ROM's bare `endtext`, checked by label at link time
    assert "ASSERT DayOfWeekSiblingsHousePokedexScript.End == $7595" in src
    assert "ASSERT BANK(DayOfWeekSiblingsHousePokedexScript.End) == $2D" in src


def test_the_gates_are_included_after_the_slice_one_files():
    slink = (REPO / "patch/polished/src/slink.asm").read_text(encoding="utf-8")
    assert slink.index("trade_items.asm") < slink.index("trade_gate.asm")


# ------------------------------------------------------------------ (c) the real gate bytes on a minimal SM83

class Fault(Exception):
    pass


class Machine:
    """The opcodes the gates and the stub use. Unknown opcodes fail closed."""

    def __init__(self, rom: bytes, bank: int = 0x7E):
        self.rom, self.bank = rom, bank
        self.ram: dict[int, int] = {}
        self.a, self.z, self.farjp = 0, False, None
        self.stack: list[int] = []

    def read(self, addr):
        if 0x4000 <= addr < 0x8000:
            return self.rom[pc._flat(self.bank, addr)]
        raise Fault(f"code read outside the banked window: {addr:#06x}")

    def run(self, addr):
        steps = 0
        while True:
            steps += 1
            if steps > 200:
                raise Fault("did not terminate")
            op = self.read(addr)
            n1 = self.read(addr + 1) if op not in (0xC9, 0xAF) else 0
            if op == 0xFA:            # ld a, [nn]
                self.a = self.ram.get(n1 | self.read(addr + 2) << 8, 0)
                addr += 3
            elif op == 0xFE:          # cp n
                self.z = self.a == n1
                addr += 2
            elif op == 0x20:          # jr nz, e
                e = n1 - 256 if n1 > 127 else n1
                addr += 2 if self.z else 2 + e
            elif op == 0x3E:          # ld a, n
                self.a = n1
                addr += 2
            elif op == 0xAF:          # xor a
                self.a, self.z = 0, True
                addr += 1
            elif op == 0xE0:          # ldh [n], a
                self.ram[0xFF00 + n1] = self.a
                addr += 2
            elif op == 0xCD:          # call nn (same bank)
                self.run(n1 | self.read(addr + 2) << 8)
                addr += 3
            elif op == 0xC9:          # ret
                return
            elif op == 0xD7:          # rst FarCall (rst $10): dwb target|$8000 (farjp), bank
                tgt = n1 | self.read(addr + 2) << 8
                bank = self.read(addr + 3)
                if not tgt & 0x8000:
                    raise Fault("expected farjp, got farcall")
                self.farjp = (bank, tgt & 0x7FFF)
                return
            else:
                raise Fault(f"unmodelled opcode {op:#04x} at {addr:#06x}")


def run_gate(rom: bytes, entry: tuple[int, int], room: int, preset: dict | None = None) -> Machine:
    m = Machine(rom)
    m.ram[ROOM_ADDR] = room
    m.ram.update(preset or {})
    m.run(entry[1])
    return m


def observe(rom: bytes, new: dict, clean: dict) -> list[str]:
    """Every behavioural claim of the gates; returns the failures (empty = all hold)."""
    bad = []
    wait, tmo = new["SlinkTradeWaitGate"], new["SlinkTradeTimeoutGate"]
    sentinel = {H_SCRIPT_VAR: 0x5A, H_SCRIPT_BANK: 0x11, H_SCRIPT_POS: 0x22, H_SCRIPT_POS + 1: 0x33}
    m = run_gate(rom, wait, TRADE_ROOM, sentinel)
    if m.ram[H_SCRIPT_VAR] != 1 or m.farjp is not None:
        bad.append(f"trade wait: hScriptVar={m.ram[H_SCRIPT_VAR]:#x} farjp={m.farjp}")
    m = run_gate(rom, tmo, TRADE_ROOM, sentinel)
    got = (m.ram[H_SCRIPT_BANK], m.ram[H_SCRIPT_POS], m.ram[H_SCRIPT_POS + 1])
    if got != (0x2D, 0x95, 0x75) or m.farjp is not None or m.ram[H_SCRIPT_VAR] != 0:
        bad.append(f"trade timeout: bank/pos {got}, var={m.ram[H_SCRIPT_VAR]:#x} farjp={m.farjp}")
    for room in (0, BATTLE_ROOM, 3):
        for name, entry, native in (("wait", wait, "Special_WaitForLinkedFriend"),
                                    ("timeout", tmo, "Special_CheckLinkTimeout")):
            m = run_gate(rom, entry, room, sentinel)
            if m.farjp != clean[native] or any(m.ram[a] != v for a, v in sentinel.items()):
                bad.append(f"room {room} {name}: farjp={m.farjp} (want {clean[native]}) ram={m.ram}")
    return bad


def test_the_built_gates_behave(rom, syms):
    clean, new = syms
    assert clean["wChosenCableClubRoom"] == (1, ROOM_ADDR) and clean["hScriptVar"] == (0, H_SCRIPT_VAR)
    assert clean["hScriptBank"] == (0, H_SCRIPT_BANK) and clean["hScriptPos"] == (0, H_SCRIPT_POS)
    assert clean[pc.SCRIPT_END_LABEL] == (0x2D, 0x7595)
    assert observe(rom[1], new, clean) == []


def _mutant(rom_bytes: bytes, new: dict, gate: str, offset: int, want: int, to: int) -> bytes:
    at = pc._flat(*new[gate]) + offset
    assert rom_bytes[at] == want, (gate, offset, rom_bytes[at])
    out = bytearray(rom_bytes)
    out[at] = to
    return bytes(out)


def _swap_pos_bytes(rom_bytes: bytes, new: dict) -> bytes:
    out = bytearray(rom_bytes)
    at = pc._flat(*new["SlinkTradeTimeoutGate"])
    lo = [i for i in range(at, at + 40) if out[i] == 0xE0 and out[i + 1] == 0xEC]
    hi = [i for i in range(at, at + 40) if out[i] == 0xE0 and out[i + 1] == 0xED]
    assert len(lo) == len(hi) == 1
    out[lo[0] + 1], out[hi[0] + 1] = 0xED, 0xEC
    return bytes(out)


def test_red_controls_each_mutant_of_the_built_gates_is_observed(rom, syms):
    clean, new = syms
    built = rom[1]
    # `ld a,[wChosenCableClubRoom]` is 3 bytes, so `cp n`'s operand is at +4; `ld a,TRUE`'s operand at +8
    assert observe(_mutant(built, new, "SlinkTradeWaitGate", 4, TRADE_ROOM, 2), new, clean)      # wrong room constant
    assert observe(_mutant(built, new, "SlinkTradeTimeoutGate", 4, TRADE_ROOM, 2), new, clean)
    assert observe(_mutant(built, new, "SlinkTradeWaitGate", 8, 1, 0), new, clean)             # wait gate returns FALSE
    assert observe(_swap_pos_bytes(built, new), new, clean)                                       # hScriptPos bytes swapped
    assert observe(built, new, clean) == []


def test_the_trade_gate_is_not_reached_through_other_rooms(rom, syms):
    """Every non-trade room value is native: the discriminator is equality with LINK_TRADECENTER - 1."""
    clean, new = syms
    for room in range(0, 256):
        m = run_gate(rom[1], new["SlinkTradeWaitGate"], room)
        assert (m.farjp is None) == (room == TRADE_ROOM), room


# ------------------------------------------------------------------ builder-level red control

def test_widening_the_builder_span_still_trips_the_old_bytes_check(monkeypatch):
    """A mutant builder that allows the whole table still refuses a clean ROM whose entry is not the native one."""
    from tests.unit import test_polished_companion as T
    real = pc.gate_table_span

    def widened(base, data, old, new):
        lo, hi, why = real(base, data, old, new)
        return lo - 0x100, hi + 0x100, why

    monkeypatch.setattr(pc, "gate_table_span", widened)
    base = bytearray(T.clean_rom())
    base[T.TABLE_AT + 1] ^= 0xFF
    with pytest.raises(RuntimeError, match="Special at 0x.*want"):
        pc.verify_overlay(bytes(base), T.overlay_rom(bytes(base)), T.CLEAN_SYMS, T.OVERLAY_SYMS)
