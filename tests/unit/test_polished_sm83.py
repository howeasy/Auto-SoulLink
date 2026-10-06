"""The reusable SM83 interpreter for the Polished trade asm tests (tests/unit/polished_sm83.py).

(a) one hand-assembled program per opcode GROUP, expected registers/flags/memory written out in this file (not
computed by the machine under test), plus independent reference formulations (bit-trick flag formulas, string
rotations, a BCD oracle, a Zilog-style DAA table); (b) CALL/RET/RST/PUSH/POP balance, `ld hl, sp+n`, nested
calls, the sentinel, sp_delta, the write log; (c) illegal opcodes, the step limit, non-ROM execution; (d) traps
and the `rst FarCall` model, cross-checked against the REAL home/farcall.asm bytes of the pinned release ROM;
(e) a differential run of the built bank-$7E routines against the old mini machines and their Python twins;
(f) mutants of the interpreter itself, each caught by a named test.

Absent input skips (no cached release ROM); present-but-wrong input fails.
"""
from __future__ import annotations

import os
import random
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "patch" / "tools"))

from build_gen2_companion import _symbols  # noqa: E402
from make_ups import ups_apply  # noqa: E402

from tests.unit import (  # noqa: E402
    polished_sm83 as sm,
    test_polished_trade_gate as GATE,
    test_polished_trade_snapshot as SNAP,
)

S = sm        # the module under test; the mutant tests swap this name for a broken copy

CODE = 0x0200
WRAM = 0xC100
RELEASE = Path(os.environ.get("SLINK_WORK_ROOT", "F:/slink-work")) / "cache/polished/release/polishedcrystal-3.2.3.gbc"
CLEAN_SYM = REPO / "data/polished/polishedcrystal.sym"
OVERLAY_SYM = REPO / "data/polished/polished_slink.sym"
UPS = REPO / "patch/dist/SLink-Polished.ups"

FLAG_BITS = (("z", 0x80), ("n", 0x40), ("h", 0x20), ("c", 0x10))
REGS = "bcdehl?a"          # operand codes 0..7; 6 is (HL)


RET = bytes([0xC9])


def hx(text: str) -> bytes:
    return bytes.fromhex(text)


def fl(letters: str) -> int:
    return sum(bit for ch, bit in FLAG_BITS if ch in letters)


def flags_of(f: int) -> str:
    return "".join(ch for ch, bit in FLAG_BITS if f & bit)


# ------------------------------------------------------------------ harness

def mk(code: bytes, *, bank: int = 1, extra: dict | None = None, banks: dict | None = None, **kw):
    """A machine whose ROM bank 0 holds `code` at $0200 (and `extra` {addr: bytes} elsewhere in bank 0).

    banks: {(bank, addr in $4000-$7FFF): bytes} placed in the other ROM banks (the image has four).
    """
    rom = bytearray(0x4000 * 4)
    rom[CODE:CODE + len(code)] = code
    for at, data in (extra or {}).items():
        rom[at:at + len(data)] = data
    for (b, at), data in (banks or {}).items():
        off = b * 0x4000 + at - 0x4000
        rom[off:off + len(data)] = data
    return S.SM83(bytes(rom), bank, **kw)


def one(code: bytes, regs: dict | None = None, flags: str = "", sp: int = 0xD000, mem: dict | None = None, **kw):
    """Execute exactly ONE instruction at $0200 and return the machine."""
    m = mk(code, **kw)
    m.pc, m.sp = CODE, sp
    for k, v in (regs or {}).items():
        setattr(m, k, v)
    m.f = fl(flags)
    for at, data in (mem or {}).items():
        m.poke(at, data)
    m.step()
    return m


def run(code: bytes, regs: dict | None = None, flags: str = "", sp: int | None = None, mem: dict | None = None,
        extra: dict | None = None, **kw):
    """Run `code` + RET as a routine; returns (machine, Result)."""
    m = mk(code + b"\xc9", extra=extra, **{k: v for k, v in kw.items() if k not in ("max_steps", "sentinel")})
    r = m.call_routine(CODE, regs, sp, flags=flags, mem=mem, **{k: v for k, v in kw.items() if k in ("max_steps", "sentinel")})
    return m, r


def reg(m, i: int) -> int:
    return getattr(m, REGS[i])


# ------------------------------------------------------------------ (a) LD / LDH / stack-pointer loads

DEF = {"b": 0x11, "c": 0x12, "d": 0x13, "e": 0x14, "h": 0xC1, "l": 0x23, "a": 0x1A}
DEF_VALUES = {0: 0x11, 1: 0x12, 2: 0x13, 3: 0x14, 4: 0xC1, 5: 0x23, 7: 0x1A, 6: 0x77}   # operand 6 = [$C123]


@pytest.mark.parametrize(("dst", "src"), [(d, s) for d in range(8) for s in range(8) if (d, s) != (6, 6)])
def test_ld_r_r_every_pair(dst, src):                 # (6, 6) is 0x76 = HALT, covered by the fault tests
    m = one(bytes([0x40 | dst << 3 | src]), DEF, "zc", mem={0xC123: 0x77})
    new = DEF_VALUES[src]
    for i in (0, 1, 2, 3, 4, 5, 7):
        assert reg(m, i) == (new if i == dst else DEF_VALUES[i]), (dst, src, i)
    assert m.peek(0xC123)[0] == (new if dst == 6 else 0x77)
    assert flags_of(m.f) == "zc"                      # loads never touch flags
    assert m.pc == CODE + 1


@pytest.mark.parametrize("dst", range(8))
def test_ld_r_n(dst):
    m = one(bytes([0x06 | dst << 3, 0x9C]), {"h": 0xC2, "l": 0x00}, "n")
    if dst == 6:
        assert m.peek(0xC200)[0] == 0x9C
    else:
        assert reg(m, dst) == 0x9C
    assert flags_of(m.f) == "n" and m.pc == CODE + 2


def test_ld_rr_nn_and_sp_loads():
    for op, name in ((0x01, "bc"), (0x11, "de"), (0x21, "hl")):
        m = one(bytes([op, 0x34, 0x12]), flags="zc")
        assert getattr(m, name) == 0x1234 and flags_of(m.f) == "zc"
    m = one(hx("31 CD AB"))
    assert m.sp == 0xABCD
    m = one(hx("F9"), {"hl": 0xC0DE}, "h")                   # ld sp, hl
    assert m.sp == 0xC0DE and flags_of(m.f) == "h"


def test_indirect_loads_and_stores_through_bc_de_hli_hld_and_the_write_log():
    # ld [bc],a ; ld [de],a ; ld [hl+],a ; ld [hl-],a  -- each logs exactly one write at its own pc
    m = mk(hx("02 12 22 32") + b"\xc9")
    r = m.call_routine(CODE, {"a": 0x5A, "bc": 0xC000, "de": 0xC001, "hl": 0xC010}, flags="c")
    assert r.writes == [(CODE, 0xC000, 0x5A), (CODE + 1, 0xC001, 0x5A), (CODE + 2, 0xC010, 0x5A),
                        (CODE + 3, 0xC011, 0x5A)]
    assert r.hl == 0xC010 and r.cf and r.sp_delta == 0
    # the loads, including the post-increment / decrement forms
    m = mk(hx("0A 47 1A 4F 2A 57 3A 5F") + b"\xc9")      # a=[bc] b=a a=[de] c=a a=[hl+] d=a a=[hl-] e=a
    for at, v in ((0xC000, 0x01), (0xC001, 0x02), (0xC010, 0x03), (0xC011, 0x04)):
        m.poke(at, v)
    r = m.call_routine(CODE, {"bc": 0xC000, "de": 0xC001, "hl": 0xC010})
    assert (r.b, r.c, r.d, r.e, r.a) == (0x01, 0x02, 0x03, 0x04, 0x04)
    assert r.hl == 0xC010                                    # +1 then -1


def test_ld_nn_forms_and_ldh_forms():
    m = one(hx("08 00 C2"), sp=0xD1F8, flags="z")       # ld [$C200], sp
    assert m.peek(0xC200, 2) == bytes([0xF8, 0xD1]) and flags_of(m.f) == "z"
    assert m.writes == [(CODE, 0xC200, 0xF8), (CODE, 0xC201, 0xD1)]
    m = one(hx("EA 34 C2"), {"a": 0x66})                                  # ld [$C234], a
    assert m.peek(0xC234)[0] == 0x66
    m = one(hx("FA 34 C2"), mem={0xC234: 0x99})                            # ld a, [$C234]
    assert m.a == 0x99
    m = one(hx("E0 85"), {"a": 0x42})                                     # ldh [$FF85], a
    assert m.peek(0xFF85)[0] == 0x42 and m.writes == [(CODE, 0xFF85, 0x42)]
    m = one(hx("F0 85"), mem={0xFF85: 0x24})                               # ldh a, [$FF85]
    assert m.a == 0x24
    m = one(hx("E2"), {"a": 0x77, "c": 0x90})                                # ld [c], a   -> $FF90
    assert m.peek(0xFF90)[0] == 0x77
    m = one(hx("F2"), {"c": 0x91}, mem={0xFF91: 0x31})                    # ld a, [c]
    assert m.a == 0x31


# ------------------------------------------------------------------ (a) 8-bit ALU

# (mnemonic op index, a, v, carry-in, expected a, expected flags) -- every row worked out by hand
ALU_ROWS = [
    (0, 0x3A, 0xC6, 0, 0x00, "zhc"),     # ADD  0x3A+0xC6 = 0x100; low nibbles A+6 = 0x10
    (0, 0x0F, 0x01, 0, 0x10, "h"),
    (0, 0x80, 0x80, 0, 0x00, "zc"),      # no half-carry: 0+0
    (0, 0x7F, 0x01, 0, 0x80, "h"),
    (0, 0x00, 0x00, 0, 0x00, "z"),
    (1, 0xFF, 0x00, 1, 0x00, "zhc"),     # ADC  0xFF+0+1: F+0+1 = 0x10 half-carries
    (1, 0x0E, 0x01, 1, 0x10, "h"),       # E+1+1 = 0x10
    (1, 0x0E, 0x01, 0, 0x0F, ""),        # without carry-in: no half-carry
    (1, 0xF0, 0x0F, 1, 0x00, "zhc"),
    (2, 0x10, 0x01, 0, 0x0F, "nh"),      # SUB  borrow from bit 4
    (2, 0x00, 0x01, 0, 0xFF, "nhc"),
    (2, 0x3E, 0x3E, 0, 0x00, "zn"),
    (2, 0x40, 0x0F, 0, 0x31, "nh"),
    (2, 0x05, 0x06, 0, 0xFF, "nhc"),
    (3, 0x10, 0x0F, 1, 0x00, "znh"),     # SBC  0x10-0x0F-1 = 0: low nibble 0-F-1 borrows; no full borrow
    (3, 0x00, 0x00, 1, 0xFF, "nhc"),
    (3, 0x01, 0x00, 1, 0x00, "zn"),      # low 1-0-1 = 0: no borrow
    (3, 0x05, 0x04, 1, 0x00, "zn"),
    (3, 0x05, 0x05, 1, 0xFF, "nhc"),     # low 5-5-1 = -1 borrows even though the nibbles are equal
    (3, 0x00, 0xFF, 1, 0x00, "znhc"),    # 0-0xFF-1 = -0x100 -> 0x00 with both borrows
    (4, 0xF0, 0x0F, 0, 0x00, "zh"),      # AND always sets H
    (4, 0xFF, 0x81, 0, 0x81, "h"),
    (5, 0xFF, 0xFF, 1, 0x00, "z"),       # XOR clears C even when it was set
    (5, 0x0F, 0xF0, 0, 0xFF, ""),
    (6, 0x00, 0x00, 1, 0x00, "z"),       # OR  clears C
    (6, 0x81, 0x7E, 0, 0xFF, ""),
    (7, 0x40, 0x41, 0, 0x40, "nhc"),     # CP leaves A alone
    (7, 0x41, 0x41, 0, 0x41, "zn"),
    (7, 0x50, 0x0F, 0, 0x50, "nh"),
    (7, 0xFF, 0x00, 1, 0xFF, "n"),       # CP ignores carry-in
]


def ref_alu(op: int, a: int, v: int, cin: int) -> tuple[int, str]:
    """An independent formulation: carry/half-carry from bitwise identities, not from comparisons."""
    if op in (0, 1):
        c = cin if op == 1 else 0
        res = (a + v + c) & 0xFF
        half = bool((a ^ v ^ res) & 0x10)
        carry = bool(((a & v) | ((a | v) & ~res)) & 0x80)
        return res, ("z" if res == 0 else "") + ("h" if half else "") + ("c" if carry else "")
    if op in (2, 3, 7):
        c = cin if op == 3 else 0
        res = (a - v - c) & 0xFF
        half = bool((a ^ v ^ res) & 0x10)
        borrow = bool(((~a & v) | (~(a ^ v) & res)) & 0x80)
        out = ("z" if res == 0 else "") + "n" + ("h" if half else "") + ("c" if borrow else "")
        return (a if op == 7 else res), out
    res = (a & v, a ^ v, a | v)[op - 4]
    return res, ("z" if res == 0 else "") + ("h" if op == 4 else "")


def test_add_adc_sub_sbc_cp_and_or_xor_hand_table():
    bad = []
    for op, a, v, cin, want_a, want_f in ALU_ROWS:
        flags = "c" if cin else ""
        for form in ("reg", "imm", "hl"):
            if form == "reg":            # op a, c
                m = one(bytes([0x80 | op << 3 | 1]), {"a": a, "c": v}, flags)
            elif form == "imm":
                m = one(bytes([0xC6 | op << 3, v]), {"a": a}, flags)
            else:
                m = one(bytes([0x80 | op << 3 | 6]), {"a": a, "hl": WRAM}, flags, mem={WRAM: v})
            got = (m.a, flags_of(m.f))
            if got != (want_a, want_f):
                bad.append((form, op, hex(a), hex(v), cin, got, (want_a, want_f)))
    assert bad == []


def test_alu_matches_the_bitwise_reference_for_every_a_and_edge_operands():
    edges = [0x00, 0x01, 0x0F, 0x10, 0x1F, 0x7F, 0x80, 0x81, 0x8F, 0xF0, 0xF1, 0xFE, 0xFF, 0x55, 0xAA, 0x3A, 0xC6,
             0x0E]
    bad = []
    for op in range(8):
        for cin in (0, 1):
            m = mk(bytes([0x80 | op << 3 | 1]))                  # op a, c
            for a in range(256):
                for v in edges:
                    m.pc, m.a, m.c, m.f = CODE, a, v, fl("c" if cin else "")
                    m.step()
                    want = ref_alu(op, a, v, cin)
                    if (m.a, flags_of(m.f)) != want:
                        bad.append((op, hex(a), hex(v), cin, (hex(m.a), flags_of(m.f)), want))
                        break
    assert bad == []


INC_ROWS = [(0x00, 0x01, ""), (0x0F, 0x10, "h"), (0x7F, 0x80, "h"), (0xFF, 0x00, "zh"), (0x1F, 0x20, "h"),
            (0xFE, 0xFF, ""), (0x09, 0x0A, "")]
DEC_ROWS = [(0x01, 0x00, "zn"), (0x00, 0xFF, "nh"), (0x10, 0x0F, "nh"), (0x80, 0x7F, "nh"), (0x0F, 0x0E, "n"),
            (0xFF, 0xFE, "n"), (0x20, 0x1F, "nh")]


def test_inc_dec_8bit_flags_keep_carry_and_use_the_low_nibble_rule():
    bad = []
    for dst in (0, 1, 2, 3, 6, 7):
        for rows, base, name in ((INC_ROWS, 0x04, "inc"), (DEC_ROWS, 0x05, "dec")):
            for v, want, want_f in rows:
                for fin in ("", "c", "zn", "znhc"):
                    if dst == 6:
                        m = one(bytes([base | dst << 3]), {"hl": 0xC100}, fin, mem={0xC100: v})
                        got = m.peek(0xC100)[0]
                    else:
                        m = one(bytes([base | dst << 3]), {REGS[dst]: v}, fin)
                        got = reg(m, dst)
                    exp_f = want_f + ("c" if "c" in fin else "")
                    if (got, flags_of(m.f)) != (want, exp_f):
                        bad.append((name, dst, hex(v), fin, (hex(got), flags_of(m.f)), (hex(want), exp_f)))
    assert bad == []
    for base, v, want, want_f in ((0x04, 0x0F, 0x10, "hc"), (0x05, 0x10, 0x0F, "nhc")):
        for dst, other in ((4, "h"), (5, "l")):                    # inc/dec h and l as plain registers
            m = one(bytes([base | dst << 3]), {other: v}, "c")
            assert getattr(m, other) == want and flags_of(m.f) == want_f


def test_inc_dec_16bit_wrap_and_never_touch_flags():
    for op, name, start, want in ((0x03, "bc", 0xFFFF, 0x0000), (0x13, "de", 0x00FF, 0x0100),
                                  (0x23, "hl", 0x0FFF, 0x1000), (0x0B, "bc", 0x0000, 0xFFFF),
                                  (0x1B, "de", 0x0100, 0x00FF), (0x2B, "hl", 0x1000, 0x0FFF)):
        m = one(bytes([op]), {name: start}, "zhc")
        assert getattr(m, name) == want and flags_of(m.f) == "zhc", (op, name)
    assert one(hx("33"), sp=0xFFFF, flags="n").sp == 0x0000
    assert one(hx("3B"), sp=0x0000, flags="n").sp == 0xFFFF


ADD_HL_ROWS = [  # (hl, rr, result, flags-out for flags-in "")
    (0x0FFF, 0x0001, 0x1000, "h"),
    (0xFFFF, 0x0001, 0x0000, "hc"),          # result zero, Z is NOT set (Z is untouched)
    (0x8000, 0x8000, 0x0000, "c"),
    (0x1234, 0x0001, 0x1235, ""),
    (0xFFFF, 0xFFFF, 0xFFFE, "hc"),
    (0x0800, 0x0800, 0x1000, "h"),
    (0x0F00, 0x0100, 0x1000, "h"),
    (0x0E00, 0x0100, 0x0F00, ""),
]


def test_add_hl_rr_h_is_bit_11_c_is_bit_15_z_untouched_n_cleared():
    bad = []
    for op, name in ((0x09, "bc"), (0x19, "de")):
        for hl, rr, want, want_f in ADD_HL_ROWS:
            for fin in ("", "z", "n", "zn"):
                m = one(bytes([op]), {"hl": hl, name: rr}, fin)
                exp = want_f + ("z" if "z" in fin else "")
                if (m.hl, flags_of(m.f)) != (want, "".join(ch for ch in "znhc" if ch in exp)):
                    bad.append((name, hex(hl), hex(rr), fin, hex(m.hl), flags_of(m.f)))
    for hl, want, want_f in ((0x0800, 0x1000, "h"), (0x8000, 0x0000, "c"), (0x4000, 0x8000, ""), (0x0001, 0x0002, ""),
                             (0xFFFF, 0xFFFE, "hc")):
        m = one(hx("29"), {"hl": hl}, "z")                        # add hl, hl
        if (m.hl, flags_of(m.f)) != (want, "z" + want_f):
            bad.append(("hl,hl", hex(hl), hex(m.hl), flags_of(m.f)))
    m = one(hx("39"), {"hl": 0x0FFF}, sp=0x0001)                   # add hl, sp
    if (m.hl, flags_of(m.f)) != (0x1000, "h") or m.sp != 1:
        bad.append(("hl,sp", hex(m.hl), flags_of(m.f)))
    assert bad == []


# (sp, e8 as signed, result, flags) -- the flags come from the LOW byte: H = bit 3->4, C = bit 7->8 of sp_low + e8
SP_ROWS = [
    (0x00FF, 1, 0x0100, "hc"),        # 0xFF + 0x01
    (0x12F8, 8, 0x1300, "hc"),        # 0xF8 + 0x08 = 0x100, 8+8 = 0x10
    (0x1000, -1, 0x0FFF, ""),         # low 0x00 + 0xFF = 0xFF: neither (a 16-bit borrow view would say otherwise)
    (0x1001, -1, 0x1000, "hc"),       # 0x01 + 0xFF = 0x100, 1+F = 0x10
    (0xFFFF, 1, 0x0000, "hc"),        # Z must stay 0 although the result is 0
    (0x0000, 0, 0x0000, ""),
    (0x00F0, 0x10, 0x0100, "c"),
    (0x000F, 1, 0x0010, "h"),
    (0x8000, -128, 0x7F80, ""),
    (0xFF80, 127, 0xFFFF, ""),
    (0x0008, 8, 0x0010, "h"),
    (0x0070, 0x70, 0x00E0, ""),       # 0x70+0x70 = 0xE0, nibbles 0+0
    (0x0078, 0x78, 0x00F0, "h"),      # 0x78+0x78 = 0xF0: 8+8 half-carries, no byte carry
    (0x0080, -128, 0x0000, "c"),      # 0x80 + 0x80 = 0x100
]


@pytest.mark.parametrize("fin", ["", "znhc", "zn"])
def test_add_sp_and_ld_hl_sp_low_byte_flags(fin):
    bad = []
    for sp, e, want, want_f in SP_ROWS:
        b = e & 0xFF
        m = one(bytes([0xE8, b]), sp=sp, flags=fin)                 # add sp, e8
        if (m.sp, flags_of(m.f)) != (want, want_f):
            bad.append(("add sp", hex(sp), e, hex(m.sp), flags_of(m.f)))
        m = one(bytes([0xF8, b]), {"hl": 0x1111}, fin, sp=sp)         # ld hl, sp+e8
        if (m.hl, m.sp, flags_of(m.f)) != (want, sp, want_f):
            bad.append(("ld hl,sp", hex(sp), e, hex(m.hl), hex(m.sp), flags_of(m.f)))
    assert bad == []


# ------------------------------------------------------------------ (a) DAA and the accumulator ops

DAA_ROWS = [  # (a, flags in, a out, flags out)
    (0x3C, "", 0x42, ""),          # 15 + 27: low nibble C > 9
    (0x9A, "", 0x00, "zc"),        # 99 + 1 = 100
    (0x11, "h", 0x17, ""),         # H forces +6
    (0xA0, "", 0x00, "zc"),        # 50 + 50 = 100
    (0x99, "", 0x99, ""),
    (0xFA, "", 0x60, "c"),
    (0x66, "c", 0xC6, "c"),
    (0x00, "", 0x00, "z"),
    (0x2D, "nh", 0x27, "n"),       # 42 - 15
    (0x0F, "nh", 0x09, "n"),       # 10 - 1
    (0xFF, "nhc", 0x99, "nc"),     # 0 - 1 with borrow
    (0x00, "nhc", 0x9A, "nc"),
    (0x00, "n", 0x00, "zn"),
    (0x50, "nc", 0xF0, "nc"),
    (0x05, "z", 0x05, ""),         # Z is recomputed
    (0xFF, "", 0x65, "c"),         # 0xFF: > 0x99 -> +0x60 (C), low F > 9 -> +6: 0x165
]


def ref_daa(a: int, n: bool, h: bool, c: bool) -> tuple[int, bool]:
    """Zilog-style table: a high-nibble correction and a low-nibble correction chosen from nibble classes."""
    lo, hi = a & 15, a >> 4
    if not n:
        high = c or hi > 9 or (hi > 8 and lo > 9)
        low = h or lo > 9
        diff = (0x60 if high else 0) | (6 if low else 0)
        return (a + diff) & 0xFF, high
    diff = (0x60 if c else 0) | (6 if h else 0)
    return (a - diff) & 0xFF, c


def test_daa_hand_table_and_zilog_table_for_every_a_and_flag_combination():
    for a, fin, want, want_f in DAA_ROWS:
        m = one(hx("27"), {"a": a}, fin)
        assert (m.a, flags_of(m.f)) == (want, want_f), (hex(a), fin)
    m = mk(hx("27"))
    for a in range(256):
        for n in (False, True):
            for h in (False, True):
                for c in (False, True):
                    m.pc, m.a, m.f = CODE, a, fl(("n" if n else "") + ("h" if h else "") + ("c" if c else ""))
                    m.step()
                    res, carry = ref_daa(a, n, h, c)
                    assert (m.a, flags_of(m.f)) == (res, ("z" if res == 0 else "") + ("n" if n else "")
                                                    + ("c" if carry else "")), (hex(a), n, h, c)


def test_daa_is_a_decimal_adder_and_subtracter_over_every_bcd_pair():
    """The independent oracle: decimal arithmetic. add/adc/sub/sbc then daa on every pair of 2-digit BCD numbers."""
    def bcd(n):
        return (n // 10) << 4 | n % 10
    progs = {"add": (hx("80 27"), 0), "adc": (hx("88 27"), 1), "sub": (hx("90 27"), 0), "sbc": (hx("98 27"), 1)}
    for name, (code, cin) in progs.items():
        m = mk(code)
        for x in range(100):
            for y in range(100):
                m.pc, m.a, m.b, m.f = CODE, bcd(x), bcd(y), fl("c" if cin else "")
                m.step()
                m.step()
                if name in ("add", "adc"):
                    total = x + y + cin
                    want, carry = bcd(total % 100), total >= 100
                else:
                    total = x - y - cin
                    want, carry = bcd(total % 100), total < 0
                assert (m.a, bool(m.f & 0x10)) == (want, carry), (name, x, y)


def test_cpl_scf_ccf_and_the_four_accumulator_rotates():
    m = one(hx("2F"), {"a": 0x35}, "zc")                                # cpl
    assert (m.a, flags_of(m.f)) == (0xCA, "znhc")
    assert flags_of(one(hx("2F"), {"a": 0x00}, "").f) == "nh"
    assert flags_of(one(hx("37"), flags="znh").f) == "zc"                # scf: N,H cleared, Z kept
    assert flags_of(one(hx("3F"), flags="c").f) == ""                    # ccf: C flips, N,H cleared
    assert flags_of(one(hx("3F"), flags="znh").f) == "zc"
    # rlca rrca rla rra: Z is always cleared, even when the result is zero
    rows = [
        (0x07, 0x85, "", 0x0B, "c"), (0x07, 0x00, "zn", 0x00, ""), (0x07, 0x80, "", 0x01, "c"),
        (0x0F, 0x01, "", 0x80, "c"), (0x0F, 0x00, "zh", 0x00, ""), (0x0F, 0x02, "c", 0x01, ""),
        (0x17, 0x80, "", 0x00, "c"), (0x17, 0x00, "c", 0x01, ""), (0x17, 0x40, "z", 0x80, ""),
        (0x1F, 0x01, "", 0x00, "c"), (0x1F, 0x00, "c", 0x80, ""), (0x1F, 0x03, "c", 0x81, "c"),
    ]
    for op, a, fin, want, want_f in rows:
        m = one(bytes([op]), {"a": a}, fin)
        assert (m.a, flags_of(m.f)) == (want, want_f), (hex(op), hex(a), fin)


# ------------------------------------------------------------------ (a) CB prefix

def ref_cb_rot(y: int, v: int, cin: int) -> tuple[int, int]:
    """CB rotate/shift y on v by string manipulation of the 8-bit pattern."""
    b = format(v, "08b")
    if y == 0:
        out, c = b[1:] + b[0], b[0]
    elif y == 1:
        out, c = b[-1] + b[:-1], b[-1]
    elif y == 2:
        out, c = b[1:] + str(cin), b[0]
    elif y == 3:
        out, c = str(cin) + b[:-1], b[-1]
    elif y == 4:
        out, c = b[1:] + "0", b[0]
    elif y == 5:
        out, c = b[0] + b[:-1], b[-1]
    elif y == 6:
        out, c = b[4:] + b[:4], "0"
    else:
        out, c = "0" + b[:-1], b[-1]
    return int(out, 2), int(c)


CB_ROWS = [  # (y, v, carry-in, result, flags) -- by hand
    (0, 0x85, 0, 0x0B, "c"), (0, 0x00, 1, 0x00, "z"), (0, 0x80, 0, 0x01, "c"),
    (1, 0x01, 0, 0x80, "c"), (1, 0x00, 1, 0x00, "z"), (1, 0x02, 1, 0x01, ""),
    (2, 0x80, 0, 0x00, "zc"), (2, 0x00, 1, 0x01, ""), (2, 0x7F, 1, 0xFF, ""),
    (3, 0x01, 0, 0x00, "zc"), (3, 0x00, 1, 0x80, ""), (3, 0xFE, 1, 0xFF, ""),
    (4, 0xFF, 0, 0xFE, "c"), (4, 0x80, 1, 0x00, "zc"), (4, 0x40, 0, 0x80, ""),
    (5, 0x81, 0, 0xC0, "c"), (5, 0x80, 1, 0xC0, ""), (5, 0x01, 0, 0x00, "zc"), (5, 0x7F, 0, 0x3F, "c"),
    (6, 0xF0, 1, 0x0F, ""), (6, 0x00, 1, 0x00, "z"), (6, 0xA5, 0, 0x5A, ""), (6, 0x12, 0, 0x21, ""),
    (7, 0x81, 0, 0x40, "c"), (7, 0x01, 0, 0x00, "zc"), (7, 0xFF, 1, 0x7F, "c"), (7, 0x80, 0, 0x40, ""),
]


def cb_one(op: int, target: int, v: int, flags: str = ""):
    """Run `CB op` on operand `target` holding v ([HL] at $C100 for 6); returns (machine, value after)."""
    regs, mem = {"h": 0xC1, "l": 0x00}, None
    if target == 6:
        mem = {0xC100: v}
    elif target in (4, 5):
        regs = {"h": 0xC1, "l": 0x00}
        regs[REGS[target]] = v
    else:
        regs[REGS[target]] = v
    m = one(bytes([0xCB, op]), regs, flags, mem=mem)
    return m, (m.peek(0xC100)[0] if target == 6 else reg(m, target))


def test_cb_rotates_and_shifts_hand_table_on_every_operand():
    bad = []
    for y, v, cin, want, want_f in CB_ROWS:
        for target in range(8):
            m, got = cb_one(y << 3 | target, target, v, "c" if cin else "")
            if (got, flags_of(m.f)) != (want, want_f) or m.pc != CODE + 2:
                bad.append((y, target, hex(v), cin, hex(got), flags_of(m.f)))
    assert bad == []


def test_cb_rotates_and_shifts_match_the_string_reference_for_all_256_values():
    bad = []
    for y in range(8):
        for target in (0, 6, 7):
            for cin in (0, 1):
                for v in range(256):
                    m, got = cb_one(y << 3 | target, target, v, "c" if cin else "")
                    want, c = ref_cb_rot(y, v, cin)
                    want_f = ("z" if want == 0 else "") + ("c" if c else "")
                    if (got, flags_of(m.f)) != (want, want_f):
                        bad.append((y, target, hex(v), cin, hex(got), flags_of(m.f)))
    assert bad == []


def test_cb_bit_res_set_all_eight_bits_on_all_eight_targets():
    bad = []
    patterns = (0x00, 0xFF, 0xA5, 0x5A, 0x01, 0x80)
    for target in range(8):
        for bit in range(8):
            for v in patterns:
                s = format(v, "08b")
                at = 7 - bit
                bit_set = s[at] == "1"
                # BIT: Z = !bit, N = 0, H = 1, C untouched, no write-back
                for fin in ("", "c", "zn"):
                    m, got = cb_one(0x40 | bit << 3 | target, target, v, fin)
                    exp_f = ("" if bit_set else "z") + "h" + ("c" if "c" in fin else "")
                    if got != v or flags_of(m.f) != "".join(ch for ch in "znhc" if ch in exp_f):
                        bad.append(("bit", target, bit, hex(v), fin, flags_of(m.f)))
                    if target == 6 and m.writes:
                        bad.append(("bit wrote", target, bit))
                # RES / SET: flags untouched
                m, got = cb_one(0x80 | bit << 3 | target, target, v, "znhc")
                if got != int(s[:at] + "0" + s[at + 1:], 2) or flags_of(m.f) != "znhc":
                    bad.append(("res", target, bit, hex(v), hex(got)))
                m, got = cb_one(0xC0 | bit << 3 | target, target, v, "")
                if got != int(s[:at] + "1" + s[at + 1:], 2) or flags_of(m.f) != "":
                    bad.append(("set", target, bit, hex(v), hex(got)))
    assert bad == []


def test_cb_hl_forms_read_once_and_write_once_where_they_write():
    m, _ = cb_one(0x06, 6, 0x85)                 # rlc [hl]
    assert m.writes == [(CODE, 0xC100, 0x0B)]
    m, _ = cb_one(0x86, 6, 0xFF)                 # res 0,[hl]
    assert m.writes == [(CODE, 0xC100, 0xFE)]
    m, _ = cb_one(0x46, 6, 0xFF)                 # bit 0,[hl]
    assert m.writes == []


def test_swap_clears_carry_and_sra_keeps_the_sign():
    m, got = cb_one(0x30, 0, 0xF0, "c")
    assert got == 0x0F and flags_of(m.f) == ""
    for v, want in ((0x80, 0xC0), (0xC0, 0xE0), (0xFE, 0xFF), (0xFF, 0xFF), (0x7E, 0x3F), (0x01, 0x00)):
        m, got = cb_one(0x28 | 7, 7, v)
        assert got == want, hex(v)
        assert bool(m.f & 0x10) == bool(v & 1)


# ------------------------------------------------------------------ (a) PUSH / POP

def test_push_pop_all_pairs_and_pop_af_masks_the_low_nibble_of_f():
    for push, pop, name in ((0xC5, 0xC1, "bc"), (0xD5, 0xD1, "de"), (0xE5, 0xE1, "hl")):
        m = one(bytes([push]), {name: 0xBEEF}, "zc", sp=0xD000)
        assert m.sp == 0xCFFE and m.peek(0xCFFE, 2) == bytes([0xEF, 0xBE])          # little-endian
        assert m.writes == [(CODE, 0xCFFF, 0xBE), (CODE, 0xCFFE, 0xEF)]             # high byte first
        m = one(bytes([pop]), sp=0xCFFE, mem={0xCFFE: bytes([0x34, 0x12])}, flags="zc")
        assert getattr(m, name) == 0x1234 and m.sp == 0xD000 and flags_of(m.f) == "zc"
    m = one(hx("F5"), {"a": 0x12}, "zc")                                            # push af
    assert m.peek(0xCFFE, 2) == bytes([0x90, 0x12])
    m = one(hx("F1"), sp=0xCFFE, mem={0xCFFE: bytes([0xFF, 0x34])})                 # pop af: F=$FF
    assert (m.a, m.f, flags_of(m.f)) == (0x34, 0xF0, "znhc")


def test_pop_af_masks_the_low_nibble():
    """push bc ; pop af ; push af ; pop de -- the low nibble of F is wired to 0, whatever was on the stack."""
    bad = []
    for stacked in (0x00, 0x0F, 0xFF, 0x5A, 0xA5, 0x01, 0xF0):
        m = mk(hx("C5 F1 F5 D1") + RET)
        r = m.call_routine(CODE, {"b": 0x77, "c": stacked})
        if (r.d, r.e, r.f, r.a) != (0x77, stacked & 0xF0, stacked & 0xF0, 0x77) or r.sp_delta != 0:
            bad.append((hex(stacked), hex(r.d), hex(r.e), hex(r.f)))
    assert bad == []


# ------------------------------------------------------------------ (a) control flow groups

@pytest.mark.parametrize("cc", range(4))
@pytest.mark.parametrize("fin", ["", "z", "c", "zc"])
def test_jr_jp_call_ret_conditions(cc, fin):
    taken = {0: "z" not in fin, 1: "z" in fin, 2: "c" not in fin, 3: "c" in fin}[cc]
    # jr cc,+2 ; ld a,$11 -- the ld is skipped when taken
    m, r = run(bytes([0x20 | cc << 3, 0x02, 0x3E, 0x11]), flags=fin)
    assert (r.a == 0) == taken
    # jp cc,nn over the same `ld a,$11`
    m, r = run(bytes([0xC2 | cc << 3, (CODE + 5) & 0xFF, CODE >> 8, 0x3E, 0x11]), flags=fin)
    assert (r.a == 0) == taken
    # call cc,$0300 ; the subroutine sets a=$22
    m, r = run(bytes([0xC4 | cc << 3, 0x00, 0x03]), flags=fin, extra={0x0300: hx("3E 22 C9")})
    assert (r.a == 0x22) == taken and r.sp_delta == 0
    # ret cc inside a called routine: `ret cc ; ld a,$33 ; ret`
    m, r = run(hx("CD 00 03"), flags=fin, extra={0x0300: bytes([0xC0 | cc << 3, 0x3E, 0x33, 0xC9])})
    assert (r.a == 0x33) == (not taken) and r.sp_delta == 0
    assert r.flags == flags_of(fl(fin))                      # control flow never touches flags


def test_jr_backward_loop_jp_hl_jp_nn_and_rst_vectors():
    m, r = run(hx("06 03 05 20 FD"))                           # ld b,3 ; .l: dec b ; jr nz,.l
    assert r.b == 0 and r.zf and r.steps == 1 + 3 * 2 + 1
    m, r = run(hx("21 06 02 E9 3E 11"), regs={"a": 0})         # ld hl,$0206 ; jp hl ; ld a,$11 ; <ret at $0206>
    assert r.a == 0
    m, r = run(bytes([0xC3, (CODE + 5) & 0xFF, CODE >> 8, 0x3E, 0x11]))
    assert r.a == 0
    vectors = {v: hx(f"3E {v:02X} C9") for v in range(0, 0x40, 8)}
    for v in range(0, 0x40, 8):
        m, r = run(bytes([0xC7 | v]), regs={"a": 0xEE}, extra=vectors, farcall=None)
        assert r.a == v and r.sp_delta == 0, hex(v)
    m = one(hx("D7"), farcall=None)                            # rst $10: the pushed return address is pc+1
    assert m.pc == 0x10 and m.stack_word() == CODE + 1


def test_reti_sets_ime_and_returns_di_ei_toggle_it():
    m, r = run(hx("CD 00 03"), extra={0x0300: hx("D9")})       # call ; reti
    assert r.sp_delta == 0 and m.ime
    m = one(hx("F3"))
    assert not m.ime
    m = one(hx("FB"))
    assert m.ime
    m = mk(hx("FB F3"))
    m.pc = CODE
    m.step()
    m.step()
    assert not m.ime


# ------------------------------------------------------------------ (b) stack discipline

def test_balanced_pushes_and_hl_sp_reads_at_the_right_offsets():
    code = hx("C5 D5"                                            # push bc ; push de
              "F8 02 2A EA 00 C3 7E EA 01 C3"                    # ld hl,sp+2 : BC low/high -> [$C300],[$C301]
              "F8 00 2A EA 02 C3 7E EA 03 C3"                    # ld hl,sp+0 : DE low/high -> [$C302],[$C303]
              "F8 04 7E EA 04 C3"                                # ld hl,sp+4 : the return address low -> [$C304]
              "D1 C1")                                           # pop de ; pop bc
    m = mk(code + RET)
    r = m.call_routine(CODE, {"bc": 0x1234, "de": 0x5678}, sentinel=0xFE9C)
    assert m.peek(0xC300, 5) == bytes([0x34, 0x12, 0x78, 0x56, 0x9C])
    assert (r.bc, r.de) == (0x1234, 0x5678) and r.sp_delta == 0 and r.returned
    stack_writes = [w for w in r.writes if w[1] >= 0xCF00]
    assert stack_writes == [(CODE, 0xCFFD, 0x12), (CODE, 0xCFFC, 0x34), (CODE + 1, 0xCFFB, 0x56),
                            (CODE + 1, 0xCFFA, 0x78)]
    assert r.min_sp == 0xCFFA and r.stack_used == 6


def test_ld_hl_sp_n_reads_each_stacked_byte():
    """bc, de, hl pushed in that order: `ld hl, sp+n ; ld a,[hl]` reads hl-lo, hl-hi, de-lo, de-hi, bc-lo, bc-hi."""
    seen = []
    for n in range(6):
        m = mk(hx("C5 D5 E5") + bytes([0xF8, n, 0x7E]) + hx("E1 D1 C1") + RET)
        r = m.call_routine(CODE, {"bc": 0x1122, "de": 0x3344, "hl": 0x5566})
        seen.append(r.a)
        assert r.sp_delta == 0 and (r.bc, r.de, r.hl) == (0x1122, 0x3344, 0x5566)
    assert seen == [0x66, 0x55, 0x44, 0x33, 0x22, 0x11]


def test_nested_calls_track_depth_and_unwind_exactly():
    # main: call A ; A: call B ; B: call C ; C: ret  -- each call pushes 2 bytes
    m = mk(hx("CD 00 03") + b"\xc9", extra={0x0300: hx("CD 00 04 C9"), 0x0400: hx("CD 00 05 C9"), 0x0500: hx("C9")})
    r = m.call_routine(CODE)
    assert r.sp_delta == 0 and r.returned
    assert r.stack_used == 2 * 4                             # sentinel + three nested return addresses
    assert [w[1] for w in r.writes] == [0xCFFD, 0xCFFC, 0xCFFB, 0xCFFA, 0xCFF9, 0xCFF8]


def test_call_routine_reports_a_leaked_frame_as_sp_delta_not_a_pass():
    # pop hl ; push hl ; push hl ; ret  -- pops the sentinel, pushes it twice, returns: one word leaked
    m = mk(hx("E1 E5 E5 C9"))
    r = m.call_routine(CODE)
    assert r.returned and r.sp_delta == -2


def test_returning_to_another_address_and_over_popping_fault():
    m = mk(hx("E1 21 00 03 E5 C9"), extra={0x0300: hx("C9")})  # pop hl ; ld hl,$0300 ; push hl ; ret
    with pytest.raises(S.Fault, match="not the sentinel"):
        m.call_routine(CODE)
    m = mk(hx("C1 C9"))                                        # pop bc (the sentinel) ; ret (pops caller-frame bytes)
    with pytest.raises(S.Fault, match="past the entry frame"):
        m.call_routine(CODE)
    m = mk(hx("C3 FE FE"))                                     # jp sentinel without a ret
    with pytest.raises(S.Fault, match="without a RET"):
        m.call_routine(CODE)


def test_stack_bytes_and_min_sp():
    m = mk(hx("C5 D5 C1 D1") + b"\xc9")
    r = m.call_routine(CODE, {"bc": 0x0102, "de": 0x0304})
    assert r.min_sp == 0xCFFA and r.stack_used == 6
    m = mk(hx("C5 D5") + b"\xc9")
    m.pc, m.sp = CODE, 0xD000
    m.bc, m.de = 0xAABB, 0xCCDD
    m.step()
    m.step()
    assert m.stack_bytes(4) == bytes([0xDD, 0xCC, 0xBB, 0xAA]) and m.stack_bytes(2, 2) == bytes([0xBB, 0xAA])
    assert m.stack_word() == 0xCCDD and m.min_sp == 0xCFFC


# ------------------------------------------------------------------ (c) faults

@pytest.mark.parametrize("op", [0xD3, 0xDB, 0xDD, 0xE3, 0xE4, 0xEB, 0xEC, 0xED, 0xF4, 0xFC, 0xFD])
def test_every_illegal_opcode_faults_loudly(op):
    m = mk(bytes([op, 0, 0]))
    m.pc = CODE
    with pytest.raises(S.Fault, match="illegal opcode"):
        m.step()


def test_every_other_opcode_executes_and_halt_stop_are_explicit_traps():
    illegal = set(S.ILLEGAL)
    assert len(illegal) == 11
    done = 0
    for op in range(256):
        if op in illegal:
            continue
        m = mk(bytes([op, 0x00, 0x00]), farcall=None)
        m.pc = CODE
        if op in (0x76, 0x10):
            with pytest.raises(S.Fault, match="HALT|STOP"):
                m.step()
            m2 = mk(bytes([op, 0x00, 0x00]), farcall=None, allow_halt=True)
            m2.pc = CODE
            m2.step()
            assert m2.pc == CODE + (2 if op == 0x10 else 1)
            continue
        m.step()
        done += 1
    assert done == 256 - 11 - 2
    for cb in range(256):                                      # the whole CB map
        m = mk(bytes([0xCB, cb]))
        m.pc, m.hl = CODE, 0xC100
        m.step()
        assert m.pc == CODE + 2, hex(cb)


def test_step_limit_and_non_rom_execution_fault():
    m = mk(hx("18 FE"))                                        # jr $ : an endless loop
    with pytest.raises(S.StepLimit, match="no return within 500 steps"):
        m.call_routine(CODE, max_steps=500)
    assert issubclass(S.StepLimit, S.Fault)
    m = mk(hx("C3 00 C0"))                                     # jp $C000: WRAM
    with pytest.raises(S.Fault, match="non-ROM"):
        m.call_routine(CODE)
    m = mk(hx("C3 00 C0"), allow_ram_exec=True)
    m.poke(0xC000, hx("3E 7B C9"))
    assert m.call_routine(CODE).a == 0x7B
    m = mk(b"")
    with pytest.raises(S.Fault, match="beyond the ROM image"):
        m.call_routine(0x4000, bank=5)


# ------------------------------------------------------------------ memory map

def test_rom_banks_rom_writes_hooks_echo_and_write_log():
    rom = bytearray(0x4000 * 4)
    for b in range(4):
        rom[b * 0x4000:b * 0x4000 + 4] = bytes([0xB0 | b, 1, 2, 3])
    rom[CODE:CODE + 7] = hx("FA 00 40 EA 00 C0 C9")            # ld a,[$4000] ; ld [$C000],a ; ret
    m = S.SM83(bytes(rom), 2)
    assert m.call_routine(CODE).a == 0xB2
    m.bank = 3                                                  # tests can switch the window
    assert m.call_routine(CODE).a == 0xB3
    assert m.peek(0xC000)[0] == 0xB3
    # a write into ROM is ignored and logged separately
    m = mk(hx("3E 55 EA 00 40 EA 00 20 C9"), bank=1)           # ld a,$55 ; ld [$4000],a ; ld [$2000],a
    r = m.call_routine(CODE)
    assert m.peek(0x4000)[0] == 0 and r.writes == [] and m.bank == 1
    assert m.rom_writes == [(CODE + 2, 0x4000, 0x55), (CODE + 5, 0x2000, 0x55)]
    # mbc3: a write to $2000-$3FFF selects the bank (0 selects 1); mbc5 is 9 bit
    m = mk(hx("3E 02 EA 00 20 C9"), mbc="mbc3")
    m.call_routine(CODE)
    assert m.bank == 2
    m = mk(hx("AF EA 00 20 C9"), mbc="mbc3")
    m.call_routine(CODE)
    assert m.bank == 0 and m.mem.window_bank() == 1
    m = mk(hx("3E 07 EA 00 20 3E 01 EA 00 30 C9"), mbc="mbc5")
    m.call_routine(CODE)
    assert m.bank == 0x107
    # echo RAM and hooks
    m = mk(hx("3E 9A EA 00 E1 FA 00 C1 C9"))                    # ld [$E100],a ; ld a,[$C100]
    r = m.call_routine(CODE)
    assert r.a == 0x9A and m.peek(0xC100)[0] == 0x9A
    m = mk(hx("FA 34 C2 EA 35 C2 C9"))
    m.mem.read_hooks[0xC234] = lambda mm, addr: 0x61
    m.mem.write_hooks[0xC235] = lambda mm, addr, v: False       # swallow the store
    r = m.call_routine(CODE)
    assert r.a == 0x61 and m.peek(0xC235)[0] == 0 and r.writes == [(CODE + 3, 0xC235, 0x61)]
    with pytest.raises(S.Fault, match="poke into ROM"):
        m.poke(0x4000, 1)


# ------------------------------------------------------------------ (d) traps

def test_trap_stubs_a_native_routine_reads_the_stack_and_returns():
    seen = []

    def stub(m):
        seen.append((m.stack_word(), m.pc, m.a))
        m.a, m.de = 0x42, 0x1357

    m = mk(hx("CD 00 03 47") + RET)                            # call $0300 (trapped) ; ld b,a
    m.trap(0x0300, stub)
    r = m.call_routine(CODE, {"a": 0x09})
    assert seen == [(CODE + 3, 0x0300, 0x09)]                  # the stub saw its return address on the stack
    assert (r.a, r.b, r.de, r.sp_delta) == (0x42, 0x42, 0x1357, 0)


def test_trap_in_a_banked_window_only_fires_in_its_bank_and_ram_traps_need_no_exec_flag():
    hits = []
    m = mk(hx("CD 00 40") + RET, banks={(2, 0x4000): hx("3E 11 C9"), (3, 0x4000): hx("3E 22 C9")})
    m.trap(0x4000, lambda mm: (hits.append(mm.bank), setattr(mm, "a", 0x99)), bank=2)
    assert m.call_routine(CODE, bank=2).a == 0x99              # the trap replaced bank 2 code
    assert m.call_routine(CODE, bank=3).a == 0x22              # bank 3 runs its real code
    assert hits == [2]
    m = mk(hx("CD 00 C9") + RET)                                # call $C900 : WRAM, never fetched
    m.trap(0xC900, lambda mm: setattr(mm, "a", 0x5E))
    assert m.call_routine(CODE).a == 0x5E


def test_trap_with_ret_false_manages_pc_itself():
    m = mk(hx("CD 00 03") + RET, extra={0x0400: hx("3E 77 C9")})
    m.trap(0x0300, lambda mm: setattr(mm, "pc", 0x0400), ret=False)    # a tail jump into $0400: ld a,$77 ; ret
    r = m.call_routine(CODE)
    assert r.a == 0x77 and r.sp_delta == 0


# ------------------------------------------------------------------ (d) the rst FarCall model

CALLEE = hx("3E 5A F8 02 46 C9")           # ld a,$5A ; ld hl,sp+2 ; ld b,[hl] (the caller bank) ; ret


def test_farcall_restores_the_bank_and_returns():
    m = mk(hx("D7 00 40 02") + RET, banks={(2, 0x4000): CALLEE}, bank=1, hrombank=0xFF87)
    m.poke(0xFF87, 1)
    r = m.call_routine(CODE, {"bc": 0x1234, "hl": 0x4321})
    assert (r.a, r.b) == (0x5A, 1)                             # the callee ran and saw bank 1 stacked at sp+2
    assert m.bank == 1 and m.peek(0xFF87)[0] == 1              # restored (and hROMBank with it)
    assert r.sp_delta == 0 and r.returned
    assert r.farcalls == [S.FarCallRecord("farcall", 2, 0x4000, CODE, 1, 0xD000 - 2 - 2 - 1 - 2)]
    assert r.stack_used == 2 + 2 + S.FARCALL_EXTRA_DEPTH       # sentinel + rst + the real routine dip


def test_farcall_hands_the_callee_the_caller_registers_and_the_real_stack_layout():
    seen = []

    def spy(m):
        seen.append({"bank": m.bank, "hrom": m.peek(0xFF87)[0], "regs": (m.af, m.bc, m.de, m.hl),
                     "stack": m.stack_bytes(5)})

    m = mk(hx("D7 10 40 02") + RET, banks={(2, 0x4010): b"\x00"}, bank=1, hrombank=0xFF87)
    m.poke(0xFF87, 1)
    m.trap(0x4010, spy, bank=2)
    r = m.call_routine(CODE, {"a": 0x12, "bc": 0x3456, "de": 0x789A, "hl": 0xBCDE}, flags="zc")
    # [sp+0]=the `jmp _ReturnFarCall` address, [sp+2]=the caller bank, [sp+3]=the return location
    assert seen == [{"bank": 2, "hrom": 2, "regs": (0x1290, 0x3456, 0x789A, 0xBCDE),
                     "stack": bytes([S.FARCALL_RETURN & 0xFF, S.FARCALL_RETURN >> 8, 1, (CODE + 4) & 0xFF, CODE >> 8])}]
    assert (r.af, r.bc, r.de, r.hl) == (0x1290, 0x3456, 0x789A, 0xBCDE)      # untouched on the way back
    assert m.bank == 1


def test_nested_farcalls_each_restore_their_own_bank():
    m = mk(hx("D7 00 40 02") + RET,
           banks={(2, 0x4000): hx("D7 00 41 03 C9"), (3, 0x4100): hx("0E 33 F8 02 46 C9")}, bank=1)
    r = m.call_routine(CODE)
    assert (r.c, r.b) == (0x33, 2)                             # bank 3 code saw bank 2 as its caller
    assert m.bank == 1 and r.sp_delta == 0
    assert [(f.kind, f.bank, f.addr, f.from_bank) for f in r.farcalls] == [("farcall", 2, 0x4000, 1),
                                                                            ("farcall", 3, 0x4100, 2)]


def test_farcall_restores_the_bank_from_a_non_default_starting_bank():
    m = mk(hx("D7 00 40 02") + RET, banks={(2, 0x4000): CALLEE}, bank=3)
    r = m.call_routine(CODE)
    assert r.b == 3 and m.bank == 3


def test_farjp_is_a_tail_jump_without_a_return_frame():
    seen = []
    m = mk(hx("D7 00 C0 02 3E EE") + RET, banks={(2, 0x4000): b"\x00"}, bank=1)
    m.trap(0x4000, lambda mm: seen.append((mm.bank, mm.stack_bytes(7))), bank=2)
    r = m.call_routine(CODE, {"a": 0x01})
    # [sp+0]=return stub, [sp+2]=caller bank, [sp+3]=DoNothing (the `ret` the farjp returns through), then the
    # routine own return address (the sentinel): there is no frame for the code after the dwb
    assert seen == [(2, bytes([S.FARCALL_RETURN & 0xFF, S.FARCALL_RETURN >> 8, 1, S.DO_NOTHING & 0xFF,
                               S.DO_NOTHING >> 8, 0xFE, 0xFE]))]
    assert r.a == 0x01                                         # `ld a,$EE` after the data never ran
    assert m.bank == 1 and r.sp_delta == 0 and r.returned
    assert [(f.kind, f.bank, f.addr) for f in r.farcalls] == [("farjp", 2, 0x4000)]


def test_farcall_wrong_form_and_unexpected_targets_fault():
    m = mk(hx("D7 00 40 02") + RET, banks={(2, 0x4000): CALLEE})
    m.farcall_expect[(2, 0x4000)] = "farjp"
    with pytest.raises(S.Fault, match="expected farjp"):
        m.call_routine(CODE)
    m = mk(hx("D7 00 C0 02") + RET, banks={(2, 0x4000): CALLEE})
    m.farcall_expect[(2, 0x4000)] = "farcall"
    with pytest.raises(S.Fault, match="expected farcall.*got farjp"):
        m.call_routine(CODE)
    m = mk(hx("D7 00 40 03") + RET, banks={(3, 0x4000): CALLEE})
    m.farcall_allowed = {(2, 0x4000)}
    with pytest.raises(S.Fault, match="unexpected target"):
        m.call_routine(CODE)
    m = mk(hx("D7 00 40 20") + RET)
    with pytest.raises(S.Fault, match="beyond the ROM image"):
        m.call_routine(CODE)


def test_hrombank_is_kept_in_step_with_the_bank_by_the_model():
    m = mk(hx("D7 00 40 02") + RET, banks={(2, 0x4000): hx("F0 87 C9")}, hrombank=0xFF87)   # ldh a,[hROMBank]
    m.poke(0xFF87, 1)
    assert m.call_routine(CODE).a == 2
    assert m.peek(0xFF87)[0] == 1


# ------------------------------------------------------------------ (d) the model against the REAL FarCall bytes

HROMBANK = 0xFF87


@pytest.fixture(scope="module")
def clean_rom():
    if not RELEASE.is_file():
        pytest.skip(f"pinned Polished release ROM not cached at {RELEASE}")
    return RELEASE.read_bytes()


def _farcall_observation(rom: bytes, mode: str, farjp: bool):
    m = S.SM83(rom, 1, mbc="mbc3", farcall=mode, allow_ram_exec=True, hrombank=HROMBANK)
    m.poke(HROMBANK, 1)
    m.poke(0xC800, bytes([0xD7, 0x00, 0x40 | (0x80 if farjp else 0), 0x20, 0xC9]))      # rst FarCall ; dwb $4000,$20 ; ret
    seen = []
    m.trap(0x4000, lambda mm: seen.append({"bank": mm.bank, "hrom": mm.peek(HROMBANK)[0],
                                           "regs": (mm.af, mm.bc, mm.de, mm.hl), "stack": mm.stack_bytes(8),
                                           "sp": mm.sp}), bank=0x20)
    r = m.call_routine(0xC800, {"a": 0x12, "bc": 0x3456, "de": 0x789A, "hl": 0xBCDE}, flags="zc", sentinel=0xFE9C)
    return seen, (r.af, r.bc, r.de, r.hl, r.sp, r.sp_delta, r.stack_used, m.bank, m.peek(HROMBANK)[0])


@pytest.mark.parametrize("farjp", [False, True])
def test_the_farcall_model_equals_the_native_home_farcall_routine(clean_rom, farjp):
    """Same program under the built-in model and under the genuine rst $10 / _RstFarCall / _ReturnFarCall bytes."""
    model = _farcall_observation(clean_rom, "model", farjp)
    native = _farcall_observation(clean_rom, "native", farjp)
    assert model == native
    seen, final = model
    assert len(seen) == 1 and seen[0]["bank"] == 0x20 and seen[0]["hrom"] == 0x20
    assert final[5] == 0 and final[7] == 1 and final[8] == 1
    assert final[:4] == (0x1290, 0x3456, 0x789A, 0xBCDE)       # AF/BC/DE/HL all preserved across the farcall
    assert final[6] == 2 + 2 + S.FARCALL_EXTRA_DEPTH           # the model stack budget equals the native routine's


def test_the_home_bank_symbols_the_model_hardcodes_are_the_real_ones(clean_rom):
    syms = _symbols(CLEAN_SYM)
    assert syms["FarCall"] == (0, S.FARCALL_VECTOR) and syms["DoNothing"] == (0, S.DO_NOTHING)
    assert clean_rom[S.DO_NOTHING] == 0xC9                                           # DoNothing is a bare ret
    # FarCall: dec sp ; call _RstFarCall ; jmp _ReturnFarCall -- the stub address the callee returns to is +4
    assert clean_rom[0x10] == 0x3B and clean_rom[0x11] == 0xCD and clean_rom[S.FARCALL_RETURN] == 0xC3
    assert syms["_ReturnFarCall"][1] == int.from_bytes(clean_rom[S.FARCALL_RETURN + 1:S.FARCALL_RETURN + 3], "little")
    assert syms["hROMBank"] == (0, HROMBANK)


# ------------------------------------------------------------------ (e) differential on the REAL built bank-$7E bytes
#
# The old mini machines (test_polished_trade_gate.Machine, test_polished_trade_snapshot.Machine) and their Python
# twins are the reference; the real interpreter must agree with them on every observable, and additionally holds
# the properties they cannot see: balanced SP, preserved BC/DE/HL, the stack budget.

VALIDATE_STACK = 22                # measured: sentinel (2) + 20 bytes of the validators own pushes and calls
DIFF: dict[str, int] = {}          # how many runs each differential compared (asserted non-trivial below)


@pytest.fixture(scope="module")
def built(clean_rom):
    return ups_apply(clean_rom, UPS.read_bytes())


@pytest.fixture(scope="module")
def csyms():
    return _symbols(CLEAN_SYM)


@pytest.fixture(scope="module")
def nsyms():
    return _symbols(OVERLAY_SYM)


def _gate_new(rom, clean, entry, room, preset, mode):
    m = S.SM83(rom, 0x7E, mbc="mbc3", farcall=mode, hrombank=HROMBANK)
    m.poke(HROMBANK, 0x7E)
    m.poke(GATE.ROOM_ADDR, room)
    for a, v in preset.items():
        m.poke(a, v)
    seen = []
    for name in ("Special_WaitForLinkedFriend", "Special_CheckLinkTimeout"):
        bank, addr = clean[name]
        m.trap(addr, lambda mm: seen.append((mm.bank, mm.pc)), bank=bank)
    r = m.call_routine(entry[1])
    ram = (m.peek(GATE.H_SCRIPT_VAR)[0], m.peek(GATE.H_SCRIPT_BANK)[0], m.peek(GATE.H_SCRIPT_POS, 2))
    return seen, ram, r


def test_the_gates_agree_with_the_old_machine_in_both_farcall_modes_for_rooms_0_to_255(built, csyms, nsyms):
    sentinel = {GATE.H_SCRIPT_VAR: 0x5A, GATE.H_SCRIPT_BANK: 0x11, GATE.H_SCRIPT_POS: 0x22, GATE.H_SCRIPT_POS + 1: 0x33}
    bad, runs, farjps = [], 0, 0
    for gate in ("SlinkTradeWaitGate", "SlinkTradeTimeoutGate"):
        entry = nsyms[gate]
        for room in range(256):
            old = GATE.run_gate(built, entry, room, sentinel)
            want_seen = [old.farjp] if old.farjp else []
            want_ram = (old.ram.get(GATE.H_SCRIPT_VAR, 0), old.ram.get(GATE.H_SCRIPT_BANK, 0),
                        bytes([old.ram.get(GATE.H_SCRIPT_POS, 0), old.ram.get(GATE.H_SCRIPT_POS + 1, 0)]))
            outs = {}
            for mode in ("model", "native"):
                seen, ram, r = _gate_new(built, csyms, entry, room, sentinel, mode)
                outs[mode] = (seen, ram, r.stack_used)
                if (seen, ram) != (want_seen, want_ram):
                    bad.append((gate, room, mode, seen, ram, "old:", want_seen, want_ram))
                if r.sp_delta != 0 or not r.returned:
                    bad.append((gate, room, mode, "sp_delta", r.sp_delta))
                if seen:
                    farjps += 1
                    if mode == "model" and [(f.kind, f.bank, f.addr) for f in r.farcalls] != [("farjp", *seen[0])]:
                        bad.append((gate, room, "model farcall record", r.farcalls))
                elif r.farcalls:
                    bad.append((gate, room, "unexpected farcall", r.farcalls))
                runs += 1
            if outs["model"] != outs["native"]:                       # incl. the stack budget: model == real FarCall
                bad.append((gate, room, "model != native", outs))
    assert bad == []
    # what the gates promise (hand-stated, not from the old machine): trade room 1 answers inline, everything
    # else tail-jumps to the original special, at a stack budget of sentinel + one farjp
    seen, ram, r = _gate_new(built, csyms, nsyms["SlinkTradeWaitGate"], 1, sentinel, "model")
    assert seen == [] and ram[0] == 1 and r.stack_used == 2
    seen, ram, r = _gate_new(built, csyms, nsyms["SlinkTradeTimeoutGate"], 1, sentinel, "model")
    assert seen == [] and ram == (0, 0x2D, bytes([0x95, 0x75]))
    seen, ram, r = _gate_new(built, csyms, nsyms["SlinkTradeWaitGate"], 2, sentinel, "model")
    assert seen == [csyms["Special_WaitForLinkedFriend"]] and r.stack_used == 2 + 2 + S.FARCALL_EXTRA_DEPTH
    assert farjps == 2 * 255 * 2 and runs == 1024
    DIFF["gates"] = runs


def _new_run(rom, entry, *, a=0, bc=0x1234, de=0x5678, hl=0x9ABC, mem=None):
    m = S.SM83(rom, 0x7E, mbc="mbc3")
    r = m.call_routine(entry, {"a": a, "bc": bc, "de": de, "hl": hl}, sp=SNAP.STACK_TOP, mem=mem, sentinel=0xFFFF)
    return m, r


def _same_as_old(old, m, r, label) -> list[str]:
    """Carry, BC/DE/HL, the whole writable image and the write set must equal the old machine's."""
    bad = []
    if r.cf != old.cy:
        bad.append(f"{label}: carry {r.cf} != old {old.cy}")
    if (r.bc, r.de, r.hl) != SNAP.regs(old):
        bad.append(f"{label}: regs {(r.bc, r.de, r.hl)} != old {SNAP.regs(old)}")
    if m.mem.image()[:0x6000] != bytes(old.mem[0x8000:0xE000]) or m.mem.image()[0x7E00:] != bytes(old.mem[0xFE00:]):
        bad.append(f"{label}: RAM image differs")
    new_writes = {a for _pc, a, _v in r.writes}
    old_writes = set(old.writes) - {SNAP.STACK_TOP - 1, SNAP.STACK_TOP - 2}      # the old machine logs its sentinel push
    if new_writes != old_writes:
        bad.append(f"{label}: write sets differ {sorted(new_writes ^ old_writes)[:6]}")
    if r.sp_delta != 0 or not r.returned:
        bad.append(f"{label}: sp_delta {r.sp_delta}")
    return bad


def test_validate_incoming_matches_the_old_machine_and_the_twin_on_a_few_hundred_blobs(built, nsyms):
    entry = nsyms["SlinkTradeValidateIncoming"][1]
    blobs = [b for _label, b, _want in SNAP.TABLE] + list(SNAP.fuzz_blobs(400, 20261011))
    bad, accepted = [], 0
    for i, blob in enumerate(blobs):
        mem = {SNAP.BLOB_AT: blob}
        old = SNAP.run(built, entry, hl=SNAP.BLOB_AT, mem=mem)
        m, r = _new_run(built, entry, hl=SNAP.BLOB_AT, mem=mem)
        want = SNAP.twin_accepts(blob)
        accepted += want
        bad += _same_as_old(old, m, r, f"blob #{i}")
        if r.cf == want:
            bad.append(f"blob #{i}: refused={r.cf} but the twin accepts={want}")
        if (r.bc, r.de, r.hl) != (0x1234, 0x5678, SNAP.BLOB_AT) or r.stack_used != VALIDATE_STACK:
            bad.append(f"blob #{i}: regs / stack budget {r.stack_used}")
    assert bad == []
    assert 100 < accepted < len(blobs) - 100
    DIFF["validate_incoming"] = len(blobs)


def test_validate_staged_matches_the_old_machine_and_the_twin_on_scattered_images(built, nsyms):
    entry = nsyms["SlinkTradeValidateIncomingStaged"][1]
    rng, bad, n, accepted = random.Random(20261012), [], 250, 0
    for i, blob in enumerate(SNAP.fuzz_blobs(n, 20261012)):
        sender = SNAP.rand_sender(rng)
        want = SNAP.twin_accepts(blob) and SNAP.twin_text_ok(sender)
        accepted += want
        mem = SNAP.staged_image(nsyms, blob, sender, rng, rng.choice(("valid", "invalid", "noise")))
        old = SNAP.run(built, entry, mem=mem)
        m, r = _new_run(built, entry, mem=mem)
        bad += _same_as_old(old, m, r, f"staged #{i}")
        if r.cf == want:
            bad.append(f"staged #{i}: refused={r.cf} but the twin accepts={want}")
        if (r.bc, r.de, r.hl) != (0x1234, 0x5678, 0x9ABC) or r.stack_used > VALIDATE_STACK:
            bad.append(f"staged #{i}: BC/DE/HL not preserved or stack budget {r.stack_used}")
    assert bad == []
    assert 10 < accepted < n - 40
    DIFF["validate_staged"] = n


def test_snapshot_capture_and_validate_match_the_old_machine_for_every_count_and_slot(built, nsyms):
    w = SNAP.wram(nsyms)
    rng = random.Random(20261013)
    cap, val = nsyms["SlinkTradeSnapshot"][1], nsyms["SlinkTradeValidateSnapshot"][1]
    bad, runs = [], 0
    for count in range(1, 7):
        for slot in range(count):
            mem = SNAP.party_image(w, rng, count)
            old = SNAP.run(built, cap, a=slot, mem=mem)
            m, r = _new_run(built, cap, a=slot, mem=mem)
            bad += _same_as_old(old, m, r, f"capture {count}/{slot}")
            if r.cf or SNAP.staged(types.SimpleNamespace(mem=m.mem.ram), w) != SNAP.live_slot(mem, w, slot):
                bad.append(f"capture {count}/{slot}: staging != the live preimage (refused={r.cf})")
            after = {0x8000: m.mem.image()}
            old_after = {0x8000: bytes(old.mem[0x8000:])}
            old_v = SNAP.run(built, val, a=slot, mem=old_after)
            m_v, r_v = _new_run(built, val, a=slot, mem=after)
            bad += _same_as_old(old_v, m_v, r_v, f"validate {count}/{slot}")
            if r_v.cf:
                bad.append(f"validate {count}/{slot}: refused an unchanged snapshot")
            runs += 2
    for count, slot in ((0, 0), (7, 0), (7, 6), (0xFF, 0), (3, 3), (3, 5), (1, 1), (6, 6), (6, 0xFF)):
        for entry in (cap, val):
            mem = SNAP.party_image(w, rng, count)
            old = SNAP.run(built, entry, a=slot, mem=mem)
            m, r = _new_run(built, entry, a=slot, mem=mem)
            bad += _same_as_old(old, m, r, f"bounds {count}/{slot}")
            if not r.cf or any(a < 0xDF00 for _pc, a, _v in r.writes):
                bad.append(f"bounds {count}/{slot}: accepted or wrote outside the stack")
            runs += 1
    assert bad == []
    DIFF["snapshot"] = runs


def test_the_differential_runs_were_non_trivial():
    """A summary of the differentials above. It is ORDER-DEPENDENT by nature (the counters are filled by those tests in
    this process), so it SKIPS rather than fails when run alone, with the ROM absent, or in another worker process
    (review cx-02264cf6); each differential also asserts its own count where it runs."""
    if not DIFF:
        pytest.skip("the differential tests did not run in this process (selected alone, ROM absent or split across workers)")
    assert DIFF.get("gates") == 1024
    assert DIFF.get("validate_incoming", 0) >= 400
    assert DIFF.get("validate_staged", 0) >= 250
    assert DIFF.get("snapshot", 0) >= 21 * 2 + 18


# ------------------------------------------------------------------ (f) mutants of the interpreter itself

SRC = Path(sm.__file__)


def load_mutant(*edits: tuple[str, str]):
    """The interpreter source with each (old, new) text applied exactly once, executed as a fresh module."""
    src = SRC.read_text(encoding="utf-8")
    for old, new in edits:
        assert src.count(old) == 1, f"mutation anchor not unique: {old!r}"
        src = src.replace(old, new)
    name = f"_sm83_mutant_{abs(hash(edits))}"
    mod = types.ModuleType(name)
    mod.__file__ = str(SRC)
    sys.modules[name] = mod
    try:
        exec(compile(src, f"<{name}>", "exec"), mod.__dict__)
    finally:
        sys.modules.pop(name, None)
    return mod


HALF_ADD = "self.hf = (a & 15) + (v & 15) + cin > 15"
HALF_SBC = "self.hf = (a & 15) - (v & 15) - cin < 0"
SP_H = "self.hf = (sp & 0x0F) + (e & 0x0F) > 0x0F"
SP_C = "self.cf = (sp & 0xFF) + e > 0xFF"
POP_AF = "self._f = v & 0xF0                # POP AF: the low nibble of F reads back 0"
FAR_RET = "self.set_bank(self.rd(self.sp))"
DAA_H = "            if self.hf:\n                a -= 0x06"

# name -> (edits, tests that must each go red on the mutant)
MUTANTS = {
    "i: ADD half-carry rule broken (> 15 becomes > 16)": (
        [(HALF_ADD, "self.hf = (a & 15) + (v & 15) + cin > 16")],
        ["test_add_adc_sub_sbc_cp_and_or_xor_hand_table", "test_alu_matches_the_bitwise_reference_for_every_a_and_edge_operands"]),
    "ii: LD HL,SP+e flag source swapped (low byte -> 16 bit, like ADD HL)": (
        [(SP_H, "self.hf = (sp & 0x0FFF) + (e & 0x0FFF) > 0x0FFF"), (SP_C, "self.cf = sp + e > 0xFFFF")],
        ["test_add_sp_and_ld_hl_sp_low_byte_flags"]),
    "iii: POP AF does not mask the low nibble of F": (
        [(POP_AF, "self._f = v & 0xFF")],
        ["test_pop_af_masks_the_low_nibble", "test_push_pop_all_pairs_and_pop_af_masks_the_low_nibble_of_f"]),
    "iv: rst FarCall skips the bank restore": (
        [(FAR_RET, "self.rd(self.sp)")],
        ["test_farcall_restores_the_bank_and_returns", "test_nested_farcalls_each_restore_their_own_bank",
         "test_farjp_is_a_tail_jump_without_a_return_frame"]),
    "v: SBC half-carry ignores the carry-in": (
        [(HALF_SBC, "self.hf = (a & 15) - (v & 15) < 0")],
        ["test_add_adc_sub_sbc_cp_and_or_xor_hand_table", "test_alu_matches_the_bitwise_reference_for_every_a_and_edge_operands"]),
    "vi: DAA after a subtraction ignores H": (
        [(DAA_H, "            if False:\n                a -= 0x06")],
        ["test_daa_hand_table_and_zilog_table_for_every_a_and_flag_combination",
         "test_daa_is_a_decimal_adder_and_subtracter_over_every_bcd_pair"]),
}


def _call(name: str):
    fn = globals()[name]
    return fn("") if name == "test_add_sp_and_ld_hl_sp_low_byte_flags" else fn()


@pytest.mark.parametrize("label", list(MUTANTS))
def test_each_interpreter_mutant_is_caught_by_its_named_tests(label, monkeypatch, request):
    edits, catchers = MUTANTS[label]
    mutant = load_mutant(*edits)
    assert mutant.SM83 is not sm.SM83
    for name in catchers:
        _call(name)                                         # control: green on the real interpreter
    monkeypatch.setattr(sys.modules[__name__], "S", mutant)
    survivors = []
    for name in catchers:
        try:
            _call(name)
        except (AssertionError, mutant.Fault):
            continue
        survivors.append(name)
    assert survivors == [], f"mutant survived: {label}"


# ------------------------------------------------------------------ review cx-02264cf6 regressions

def _prog(*code, at=0x100):
    rom = bytearray(0x8000)
    rom[at:at + len(code)] = bytes(code)
    return bytes(rom)


def test_a_stack_that_wraps_through_zero_still_reports_its_depth():
    # PUSH BC / POP BC / RET with the entry SP at 0: sentinel FFFE -> push FFFC -> pop FFFE -> ret 0000
    r = sm.SM83(_prog(0xC5, 0xC1, 0xC9), 1).call_routine(0x100, regs={}, sp=0)
    assert r.sp_delta == 0 and r.stack_used == 4, (r.sp_delta, r.stack_used)
    assert sm.SM83(_prog(0xC9), 1).call_routine(0x100, regs={}, sp=0).stack_used == 2


def test_the_sentinel_is_installed_through_the_echo_mapping():
    # entry SP in echo RAM: the sentinel must be where RET will read it
    r = sm.SM83(_prog(0xC9), 1).call_routine(0x100, regs={}, sp=0xE102)
    assert r.sp_delta == 0 and r.returned


def test_an_over_pop_onto_sentinel_valued_caller_bytes_faults():
    m = sm.SM83(_prog(0xC1, 0xC9), 1)          # POP BC (eats the real sentinel) / RET (eats the caller's bytes)
    m.poke(0xD000, bytes([0xFE, 0xFE]))        # caller bytes equal to the sentinel value $FEFE
    with pytest.raises(sm.Fault, match="past the entry frame"):
        m.call_routine(0x100, regs={}, sp=0xD000)


def test_the_over_pop_check_survives_stack_wraparound():
    m = sm.SM83(_prog(0xC1, 0xC9), 1)       # entry SP 0: sentinel at $FFFE; POP BC wraps SP to 0; RET reads ROM $0000
    with pytest.raises(sm.Fault, match="past the entry frame"):
        m.call_routine(0x100, regs={}, sp=0)


def test_farcall_returns_to_the_bank_in_hrombank_not_the_mapper_bank():
    # home/farcall.asm: `ldh a, [hROMBank]` supplies the return bank. Mapper at bank 1, shadow says 3.
    rom = bytearray(0x4000 * 4)
    rom[0x100:0x108] = bytes([0x3E, 0x03, 0xE0, 0x87, 0xD7, 0x00, 0x40, 0x02])   # ld a,3 / ldh [$87],a / rst $10 / dw $4000 / db 2
    rom[0x108] = 0xC9
    rom[2 * 0x4000] = 0xC9                                                         # bank 2 $4000: RET
    m = sm.SM83(bytes(rom), 1, farcall="model", hrombank=0xFF87)
    r = m.call_routine(0x100, regs={}, sp=0xDFF0)
    assert r.farcalls[0].from_bank == 3 and m.bank == 3
    assert r.unmodelled_farcall_scratch is True


def test_a_model_farcall_marks_its_result_as_not_memory_faithful_and_a_plain_run_does_not():
    assert sm.SM83(_prog(0xC9), 1).call_routine(0x100, regs={}, sp=0xDFF0).unmodelled_farcall_scratch is False
