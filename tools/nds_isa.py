"""Pure-Python ARMv5TE (ARM946E-S) ARM/Thumb-1 branch helpers for NDS ROM detours.

Dependency-free. Encode/decode only; nothing here executes code or models the
pipeline, caches or ARMv5TE extensions beyond the forms listed in the table at
the end of docs/shared-nds-isa.md.

Conventions
  * A "code pointer" carries the ISA in bit 0: odd = Thumb, even = ARM (ARM
    pointers must also have bit 1 clear). A "plain address" has bit 0 cleared.
  * Every encoder takes the site address (plain, where the first byte is
    written) and returns little-endian bytes. Failures raise a named
    NdsIsaError subclass; nothing is silently clamped or truncated.
  * PC rules (ARM ARM, "PC reads"): Thumb PC = site + 4; Thumb literal / ADR /
    BLX-immediate use Align(PC, 4); ARM PC = site + 8.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field, replace

THUMB = "thumb"
ARM = "arm"
LR, PC = 14, 15

COND = {"eq": 0, "ne": 1, "cs": 2, "hs": 2, "cc": 3, "lo": 3, "mi": 4, "pl": 5,
        "vs": 6, "vc": 7, "hi": 8, "ls": 9, "ge": 10, "lt": 11, "gt": 12,
        "le": 13, "al": 14}

ARM_NOP = (0xE1A00000).to_bytes(4, "little")      # mov r0, r0 (ARMv5 has no NOP hint)
THUMB_NOP = (0x46C0).to_bytes(2, "little")        # mov r8, r8


class NdsIsaError(ValueError):
    """Base class: every refusal is a subclass so callers can match by name."""


class IsaRangeError(NdsIsaError):
    """Displacement does not fit the encoding."""


class IsaAlignmentError(NdsIsaError):
    """Site or target violates the form's alignment rule."""


class IsaWrongFormError(NdsIsaError):
    """Form cannot reach that target ISA (e.g. BL to ARM needs BLX)."""


class IsaEncodingError(NdsIsaError):
    """Register, condition or list is not encodable in this form."""


class IsaDecodeError(NdsIsaError):
    """Bytes are not a recognised instruction of the requested form."""


class ReplayRefusedError(NdsIsaError):
    """A displaced span cannot be replayed at the new address."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


# --------------------------------------------------------------------- basics
def _int(value, name):
    if type(value) is not int or value < 0 or value > 0xFFFFFFFF:
        raise IsaEncodingError(f"{name}: 32-bit unsigned integer required")
    return value


def _sext(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def _cond(cond):
    if isinstance(cond, str):
        if cond.lower() not in COND:
            raise IsaEncodingError(f"unknown condition {cond!r}")
        return COND[cond.lower()]
    if type(cond) is int and 0 <= cond <= 14:
        return cond
    raise IsaEncodingError(f"condition {cond!r} not encodable (0xF is the unconditional space)")


def _reg(r, name="register", high=15):
    if type(r) is not int or not 0 <= r <= high:
        raise IsaEncodingError(f"{name}: r0-r{high} required, got {r!r}")
    return r


def _site(site, align):
    _int(site, "site")
    if site & (align - 1):
        raise IsaAlignmentError(f"site 0x{site:08X} not {align}-byte aligned")
    return site


def _plain_target(target, align, what):
    _int(target, "target")
    if target & 1 and align >= 2:
        raise IsaAlignmentError(f"{what}: target 0x{target:08X} has bit0 set; pass a plain address")
    if target & (align - 1):
        raise IsaAlignmentError(f"{what}: target 0x{target:08X} not {align}-byte aligned")
    return target


def _fit(off, lo, hi, what):
    if not lo <= off <= hi:
        raise IsaRangeError(f"{what}: displacement {off:+#x} outside [{lo:#x}, {hi:#x}]")
    return off


def _pack16(*halfwords):
    return b"".join(h.to_bytes(2, "little") for h in halfwords)


def _pack32(word):
    return word.to_bytes(4, "little")


# ------------------------------------------------------------- interworking
def classify_code_address(pointer, strict=True):
    """Return (isa, plain_address). Odd = Thumb. Even = ARM, which must be word aligned
    (bit1 set with bit0 clear is UNPREDICTABLE for BX; refused when strict)."""
    _int(pointer, "pointer")
    if pointer & 1:
        return THUMB, pointer & ~1
    if strict and pointer & 2:
        raise IsaAlignmentError(f"ARM code pointer 0x{pointer:08X} is not word aligned")
    return ARM, pointer


def code_pointer(isa, address):
    _int(address, "address")
    if isa == THUMB:
        return address | 1
    if isa == ARM:
        if address & 3:
            raise IsaAlignmentError(f"ARM address 0x{address:08X} not word aligned")
        return address
    raise IsaEncodingError(f"isa must be {THUMB!r} or {ARM!r}")


def needs_interwork(caller_isa, callee_isa):
    for isa in (caller_isa, callee_isa):
        if isa not in (THUMB, ARM):
            raise IsaEncodingError(f"isa must be {THUMB!r} or {ARM!r}, got {isa!r}")
    return caller_isa != callee_isa


def call_form(caller_isa, callee_isa):
    """Immediate-form call needed: BL when the ISA is unchanged, BLX (immediate) otherwise."""
    return "blx" if needs_interwork(caller_isa, callee_isa) else "bl"


# ----------------------------------------------------------------- Thumb-1
# ARM ARM, Thumb BL/BLX(1) pair. offset = target - PC with PC = site + 4 (BL) or
# Align(site + 4, 4) (BLX). hw1 = 0xF000 | offset[22:12]; hw2 = 0xF800 | offset[11:1]
# (BL) or 0xE800 | offset[11:1] (BLX, offset[1] = 0 so hw2 bit0 = 0).
# Reach: signed 23 bits, i.e. -0x400000 .. +0x3FFFFE (BL) / +0x3FFFFC (BLX).
def thumb_bl(site, target, exchange=False):
    """Encode the 4-byte BL (target Thumb, plain even) or BLX (exchange=True, target ARM, word-aligned)."""
    _site(site, 2)
    if exchange:
        _plain_target(target, 4, "thumb blx")
        off = target - ((site + 4) & ~3)
        _fit(off, -0x400000, 0x3FFFFC, "thumb blx")
        hw2 = 0xE800
    else:
        _plain_target(target, 2, "thumb bl")
        off = target - (site + 4)
        _fit(off, -0x400000, 0x3FFFFE, "thumb bl")
        hw2 = 0xF800
    return _pack16(0xF000 | ((off >> 12) & 0x7FF), hw2 | ((off >> 1) & 0x7FF))


def thumb_blx(site, target):
    return thumb_bl(site, target, exchange=True)


def thumb_b(site, target):
    """Unconditional 16-bit B: 0xE000 | imm11, target = site + 4 + SignExtend(imm11) * 2 (-2048..+2046)."""
    _site(site, 2)
    _plain_target(target, 2, "thumb b")
    off = _fit(target - (site + 4), -2048, 2046, "thumb b")
    return _pack16(0xE000 | ((off >> 1) & 0x7FF))


def thumb_bcond(site, target, cond):
    """Conditional 16-bit B: 0xD000 | cond << 8 | imm8, target = site + 4 + SignExtend(imm8) * 2 (-256..+254)."""
    c = _cond(cond)
    if c == 14:
        raise IsaEncodingError("thumb conditional branch cannot use AL (0xE is undefined, use thumb_b)")
    _site(site, 2)
    _plain_target(target, 2, "thumb b<cond>")
    off = _fit(target - (site + 4), -256, 254, "thumb b<cond>")
    return _pack16(0xD000 | (c << 8) | ((off >> 1) & 0xFF))


def thumb_bx(rm, link=False):
    """BX Rm = 0x4700 | Rm << 3; BLX Rm = 0x4780 | Rm << 3. PC as Rm is UNPREDICTABLE, refused."""
    _reg(rm, "rm", 14)
    return _pack16((0x4780 if link else 0x4700) | (rm << 3))


def thumb_ldr_literal(site, rt, literal_addr):
    """ldr rt, [pc, #imm]: 0x4800 | rt << 8 | imm8, address = Align(site + 4, 4) + imm8 * 4 (0..1020)."""
    _site(site, 2)
    _reg(rt, "rt", 7)
    _plain_target(literal_addr, 4, "thumb ldr literal")
    imm = _fit(literal_addr - ((site + 4) & ~3), 0, 1020, "thumb ldr literal")
    return _pack16(0x4800 | (rt << 8) | (imm >> 2))


def thumb_adr(site, rd, addr):
    """add rd, pc, #imm: 0xA000 | rd << 8 | imm8, value = Align(site + 4, 4) + imm8 * 4 (0..1020)."""
    _site(site, 2)
    _reg(rd, "rd", 7)
    _plain_target(addr, 4, "thumb adr")
    imm = _fit(addr - ((site + 4) & ~3), 0, 1020, "thumb adr")
    return _pack16(0xA000 | (rd << 8) | (imm >> 2))


def _reglist(regs, extra, extra_name, high=7):
    mask, flag = 0, 0
    for r in regs:
        if r == extra:
            flag = 1
        elif type(r) is int and 0 <= r <= high:
            mask |= 1 << r
        else:
            raise IsaEncodingError(f"register {r!r} not allowed here (r0-r{high} or {extra_name})")
    if not mask and not flag:
        raise IsaEncodingError("empty register list")
    return mask, flag


def thumb_push(regs):
    """PUSH {r0-r7[, lr]} = 0xB400 | lr << 8 | list. regs may name 14 for LR."""
    mask, lr = _reglist(regs, LR, "lr")
    return _pack16(0xB400 | (lr << 8) | mask)


def thumb_pop(regs):
    """POP {r0-r7[, pc]} = 0xBC00 | pc << 8 | list. regs may name 15 for PC."""
    mask, pc = _reglist(regs, PC, "pc")
    return _pack16(0xBC00 | (pc << 8) | mask)


def thumb_mov(rd, rm):
    """MOV rd, rm (high-register form, no flag update): 0x4600 | rd[3] << 7 | rm[3] << 6 | rm[2:0] << 3 | rd[2:0]."""
    _reg(rd, "rd")
    _reg(rm, "rm")
    return _pack16(0x4600 | ((rd >> 3) << 7) | (rm << 3) | (rd & 7))


def thumb_entry_veneer(site, target):
    """8 bytes `ldr r3,[pc]; bx r3; .word target` (same bytes as Gen 3 build.py thumb_entry_jump
    for a Thumb target). `target` is a code pointer (bit0 = ISA). The site must be word aligned
    so the literal sits at site + 4 with imm8 = 0. r3 is clobbered; LR is preserved."""
    _site(site, 4)
    _int(target, "target")
    classify_code_address(target)
    return thumb_ldr_literal(site, 3, site + 4) + thumb_bx(3) + _pack32(target)


def thumb_detour(site_addr, target, kind, cond=None):
    """Replacement bytes for a Thumb site. `target` is a CODE POINTER (odd = Thumb, even = ARM).

    kind: 'bl' (Thumb target only), 'blx' (ARM target only), 'b' (Thumb target, 16-bit),
    'bcond' (needs cond), 'veneer' (either ISA, 8 bytes, word-aligned site).
    """
    isa, plain = classify_code_address(target)
    if kind == "veneer":
        return thumb_entry_veneer(site_addr, target)
    if kind == "bl":
        if isa != THUMB:
            raise IsaWrongFormError("thumb BL cannot enter ARM code: use kind='blx'")
        return thumb_bl(site_addr, plain)
    if kind == "blx":
        if isa != ARM:
            raise IsaWrongFormError("thumb BLX(immediate) always switches to ARM: Thumb target needs kind='bl'")
        return thumb_bl(site_addr, plain, exchange=True)
    if kind in ("b", "bcond"):
        if isa != THUMB:
            raise IsaWrongFormError(f"thumb {kind} cannot change ISA: use 'veneer' or bx")
        if kind == "b":
            return thumb_b(site_addr, plain)
        if cond is None:
            raise IsaEncodingError("kind='bcond' needs cond")
        return thumb_bcond(site_addr, plain, cond)
    raise IsaEncodingError(f"unknown thumb detour kind {kind!r}")


# --------------------------------------------------------------------- ARM
def arm_branch(site, target, link=False, cond="al"):
    """B/BL: cond << 28 | 0x0A000000 | L << 24 | imm24, target = site + 8 + SignExtend(imm24) * 4 (+-32 MB)."""
    c = _cond(cond)
    _site(site, 4)
    _plain_target(target, 4, "arm b/bl")
    off = _fit(target - (site + 8), -0x2000000, 0x1FFFFFC, "arm b/bl")
    return _pack32((c << 28) | 0x0A000000 | (int(bool(link)) << 24) | ((off >> 2) & 0xFFFFFF))


def arm_blx_imm(site, target):
    """BLX(1): 0xFA000000 | H << 24 | imm24, target = site + 8 + SignExtend(imm24) * 4 + H * 2.
    Unconditional only; target is a Thumb plain (even) address."""
    _site(site, 4)
    _plain_target(target, 2, "arm blx")
    off = _fit(target - (site + 8), -0x2000000, 0x1FFFFFE, "arm blx")
    return _pack32(0xFA000000 | (((off >> 1) & 1) << 24) | ((off >> 2) & 0xFFFFFF))


def arm_bx(rm, link=False, cond="al"):
    """BX Rm = cond | 0x012FFF10 | Rm; BLX Rm = cond | 0x012FFF30 | Rm. Rm = PC refused."""
    _reg(rm, "rm", 14)
    return _pack32((_cond(cond) << 28) | (0x012FFF30 if link else 0x012FFF10) | rm)


def arm_ldr_literal(site, rd, literal_addr, cond="al"):
    """ldr rd, [pc, #+-imm12]: cond | 0x051F0000 (U=0) / 0x059F0000 (U=1) | rd << 12 | |off|,
    address = site + 8 + off, |off| <= 4095. Word-aligned literal required."""
    c = _cond(cond)
    _site(site, 4)
    _reg(rd, "rd")
    _plain_target(literal_addr, 4, "arm ldr literal")
    off = _fit(literal_addr - (site + 8), -4095, 4095, "arm ldr literal")
    return _pack32((c << 28) | (0x051F0000 if off < 0 else 0x059F0000) | (rd << 12) | abs(off))


def arm_push(regs, cond="al"):
    """STMFD sp!, {list} (= STMDB sp!): cond | 0x092D0000 | list. r0-r14; PC in the list is
    UNPREDICTABLE for a store and refused."""
    mask = _arm_mask(regs, allow_pc=False)
    return _pack32((_cond(cond) << 28) | 0x092D0000 | mask)


def arm_pop(regs, cond="al"):
    """LDMFD sp!, {list} (= LDMIA sp!): cond | 0x08BD0000 | list. r0-r15; PC in the list is
    allowed (the pop is then a branch, with ARMv5T interworking on bit 0)."""
    mask = _arm_mask(regs)
    return _pack32((_cond(cond) << 28) | 0x08BD0000 | mask)


def _arm_mask(regs, allow_pc=True):
    mask = 0
    for r in regs:
        mask |= 1 << _reg(r, "register", 15 if allow_pc else 14)
    if not mask:
        raise IsaEncodingError("empty register list")
    return mask


def arm_ldr_pc_veneer(site, target):
    """8 bytes `ldr pc, [pc, #-4]; .word target`. `target` is a code pointer; on ARMv5T an LDR
    to PC interworks on bit0, so a Thumb target keeps its bit0 set. Clobbers nothing but PC."""
    _site(site, 4)
    _int(target, "target")
    classify_code_address(target)
    return arm_ldr_literal(site, PC, site + 4) + _pack32(target)


def arm_detour(site_addr, target, kind, cond="al"):
    """Replacement bytes for an ARM site. `target` is a CODE POINTER.

    kind: 'b'/'bl' (ARM target only), 'blx' (Thumb target only, unconditional), 'veneer' (either).
    """
    isa, plain = classify_code_address(target)
    if kind == "veneer":
        return arm_ldr_pc_veneer(site_addr, target)
    if kind in ("b", "bl"):
        if isa != ARM:
            raise IsaWrongFormError(f"arm {kind} cannot enter Thumb code: use kind='blx' (call) or 'veneer'")
        return arm_branch(site_addr, plain, link=kind == "bl", cond=cond)
    if kind == "blx":
        if isa != THUMB:
            raise IsaWrongFormError("arm BLX(immediate) always switches to Thumb: ARM target needs kind='bl'")
        if _cond(cond) != 14:
            raise IsaEncodingError("BLX(immediate) is unconditional")
        return arm_blx_imm(site_addr, plain)
    raise IsaEncodingError(f"unknown arm detour kind {kind!r}")


# ------------------------------------------------------------------ decoding
@dataclass(frozen=True)
class Insn:
    """One decoded instruction.

    kind: bl blx b bcond bx blx_reg ldr_lit adr push pop nop svc  -> named forms
          pi        -> recognised family that never reads or depends on PC
          pc_read   -> reads PC through a register field (cannot be replayed elsewhere)
          split     -> first half of a Thumb BL pair without its second half
          unknown   -> not classified (never assumed position independent)
    target: plain absolute address for branches / literal / adr, else None.
    target_isa: ISA entered by a branch (bl/blx/b/bcond), else None.
    """
    addr: int
    size: int
    kind: str
    word: int
    isa: str
    target: int | None = None
    target_isa: str | None = None
    cond: int | None = None
    reg: int | None = None
    regs: tuple = field(default_factory=tuple)

    @property
    def raw(self):
        return self.word.to_bytes(self.size, "little")


def _thumb_pair(hw1, hw2, addr):
    """(kind, plain target) when hw1/hw2 form a BL or BLX(1) pair at addr, else None."""
    if hw1 & 0xF800 != 0xF000:
        return None
    off = (_sext(hw1 & 0x7FF, 11) << 12) + ((hw2 & 0x7FF) << 1)
    if hw2 & 0xF800 == 0xF800:
        return "bl", addr + 4 + off
    if hw2 & 0xF801 == 0xE800:            # bit0 of a BLX(1) second half must be 0
        return "blx", (addr + 4 + off) & ~3
    return None


def decode_thumb(code, offset, addr):
    """Decode the Thumb-1 instruction at code[offset] (located at `addr`)."""
    if offset < 0 or offset + 2 > len(code) or offset & 1:
        raise IsaDecodeError("thumb decode needs an even in-range offset")
    hw = int.from_bytes(code[offset:offset + 2], "little")

    def mk(kind, size=2, **kw):
        return Insn(addr, size, kind, hw, THUMB, **kw)

    top = hw >> 11
    if top in (0x1E, 0x1F, 0x1D):          # BL prefix / BLX suffix / BL suffix
        if top == 0x1E:
            if offset + 4 > len(code):
                return mk("split")
            hw2 = int.from_bytes(code[offset + 2:offset + 4], "little")
            hit = _thumb_pair(hw, hw2, addr)
            if hit:
                kind, tgt = hit
                return Insn(addr, 4, kind, hw | hw2 << 16, THUMB, target=tgt,
                            target_isa=THUMB if kind == "bl" else ARM)
        return mk("unknown")
    if top == 0x1C:                        # B
        return mk("b", target=addr + 4 + (_sext(hw & 0x7FF, 11) << 1), target_isa=THUMB)
    if top in (0x1A, 0x1B):                # B<cond> / SVC
        c = (hw >> 8) & 15
        if c < 14:
            return mk("bcond", cond=c, target=addr + 4 + (_sext(hw & 0xFF, 8) << 1), target_isa=THUMB)
        return mk("svc") if c == 15 else mk("unknown")
    if top <= 0x07 or 0x0A <= top <= 0x13 or top in (0x15, 0x18, 0x19):
        return mk("pi")                    # shifts, add/sub, imm8 ops, ld/st, add rd,sp, ldm/stm
    if top == 0x09:
        return mk("ldr_lit", reg=(hw >> 8) & 7, target=((addr + 4) & ~3) + ((hw & 0xFF) << 2))
    if top == 0x14:
        return mk("adr", reg=(hw >> 8) & 7, target=((addr + 4) & ~3) + ((hw & 0xFF) << 2))
    if top == 0x08:
        if hw < 0x4400:
            return mk("pi")                # ALU low registers
        op, rm, rd = (hw >> 8) & 3, (hw >> 3) & 15, ((hw >> 4) & 8) | (hw & 7)
        if op == 3:
            if hw & 7:
                return mk("unknown")
            kind = "blx_reg" if hw & 0x80 else "bx"
            return mk("pc_read") if rm == 15 else mk(kind, reg=rm)
        if hw == 0x46C0:
            return mk("nop")
        return mk("pc_read") if rm == 15 or (rd == 15 and op != 2) else mk("pi")
    if top in (0x16, 0x17):                # misc 0xB000-0xBFFF
        if hw & 0xFE00 == 0xB400:
            return mk("push", regs=_thumb_list(hw, LR))
        if hw & 0xFE00 == 0xBC00:
            return mk("pop", regs=_thumb_list(hw, PC))
        if hw & 0xFF00 in (0xB000, 0xBE00):
            return mk("pi")                # add/sub sp, bkpt
    return mk("unknown")


def _thumb_list(hw, extra):
    regs = [r for r in range(8) if hw >> r & 1]
    return tuple(regs + ([extra] if hw & 0x100 else []))


def decode_arm(code, offset, addr):
    """Decode the ARM instruction at code[offset] (located at `addr`)."""
    if offset < 0 or offset + 4 > len(code) or offset & 3:
        raise IsaDecodeError("arm decode needs a word-aligned in-range offset")
    w = int.from_bytes(code[offset:offset + 4], "little")
    cond = w >> 28

    def mk(kind, **kw):
        return Insn(addr, 4, kind, w, ARM, cond=cond, **kw)

    if cond == 15:
        if w >> 25 & 7 == 0b101:           # BLX(1)
            off = (_sext(w & 0xFFFFFF, 24) << 2) + ((w >> 24 & 1) << 1)
            return mk("blx", target=addr + 8 + off, target_isa=THUMB)
        return mk("unknown")
    sel = w >> 25 & 7
    if sel == 0b101:
        target = addr + 8 + (_sext(w & 0xFFFFFF, 24) << 2)
        return mk("bl" if w >> 24 & 1 else "b", target=target, target_isa=ARM)
    if w & 0x0FFFFFD0 == 0x012FFF10:       # BX / BLX Rm
        rm = w & 15
        if rm == 15:
            return mk("pc_read")
        return mk("blx_reg" if w & 0x20 else "bx", reg=rm)
    if w == 0xE1A00000:
        return mk("nop")
    if sel == 0b100:                       # LDM/STM
        rn, regs = w >> 16 & 15, tuple(r for r in range(16) if w >> r & 1)
        if rn == 15:
            return mk("pc_read")
        if w & 0x01FF0000 == 0x012D0000:      # STMDB sp!
            return mk("push", regs=regs)
        if w & 0x01FF0000 == 0x00BD0000:      # LDMIA sp!
            return mk("pop", regs=regs)
        return mk("pi")
    if sel == 0b010:                       # LDR/STR immediate offset
        rn = w >> 16 & 15
        if rn != 15:
            return mk("pi")
        if w >> 24 & 1 and not w >> 21 & 1:
            off = (w & 0xFFF) * (1 if w >> 23 & 1 else -1)
            return mk("ldr_lit", reg=w >> 12 & 15, target=addr + 8 + off)
        return mk("pc_read")
    if sel == 0b011:                       # LDR/STR register offset (bit4 = 1 is media/undefined)
        if w >> 4 & 1:
            return mk("unknown")
        return mk("pc_read") if 15 in (w >> 16 & 15, w & 15) else mk("pi")
    if sel in (0b000, 0b001):
        if sel == 0 and w >> 4 & 1 and w >> 7 & 1:
            return mk("unknown")           # multiplies, halfword/doubleword transfers, swap
        opc, s = w >> 21 & 15, w >> 20 & 1
        if 8 <= opc <= 11 and not s:
            return mk("unknown")           # misc space (MRS/MSR/CLZ/QADD/BKPT ...)
        used = [] if opc in (13, 15) else [w >> 16 & 15]
        if sel == 0:
            used.append(w & 15)
            if w >> 4 & 1:
                used.append(w >> 8 & 15)
        return mk("pc_read") if 15 in used else mk("pi")
    if sel == 0b111 and w >> 24 & 1:
        return mk("svc")
    return mk("unknown")


# ------------------------------------------------------------ call-site scan
@dataclass(frozen=True)
class BranchSite:
    addr: int
    kind: str                  # 'bl' or 'blx'
    target: int                # plain address
    target_isa: str
    cond: int | None = None    # ARM only

    @property
    def target_pointer(self):
        return self.target | 1 if self.target_isa == THUMB else self.target


def find_bl_sites(code, base_addr, isa):
    """Linear scan for BL/BLX(immediate) at every halfword (Thumb) or word (ARM) boundary.

    This is a pattern match, NOT a control-flow walk: literal pools, tables and the other ISA's
    code can contain bit patterns that decode as calls, and a Thumb scan begun mid-instruction
    can desynchronise. A Thumb BL whose first half is the final halfword of `code` is not
    reported (its second half is outside the buffer). Treat results as candidates to be
    confirmed against a symbol or a second source, never as proof that code calls the target.
    """
    _int(base_addr, "base_addr")
    if isa == THUMB:
        if base_addr & 1:
            raise IsaAlignmentError("thumb scan base must be even")
        n = len(code) // 2
        hws = struct.unpack_from(f"<{n}H", code)
        out, i = [], 0
        while i < n - 1:
            if hws[i] & 0xF800 == 0xF000:
                hit = _thumb_pair(hws[i], hws[i + 1], base_addr + 2 * i)
                if hit:
                    kind, tgt = hit
                    out.append(BranchSite(base_addr + 2 * i, kind, tgt, THUMB if kind == "bl" else ARM))
                    i += 2
                    continue
            i += 1
        return out
    if isa == ARM:
        if base_addr & 3:
            raise IsaAlignmentError("arm scan base must be word aligned")
        n = len(code) // 4
        out = []
        for i, w in enumerate(struct.unpack_from(f"<{n}I", code)):
            if w >> 25 & 7 != 0b101:
                continue
            addr, off = base_addr + 4 * i, _sext(w & 0xFFFFFF, 24) << 2
            if w >> 28 == 15:
                out.append(BranchSite(addr, "blx", addr + 8 + off + ((w >> 24 & 1) << 1), THUMB, 15))
            elif w >> 24 & 1:
                out.append(BranchSite(addr, "bl", addr + 8 + off, ARM, w >> 28))
        return out
    raise IsaEncodingError(f"isa must be {THUMB!r} or {ARM!r}")


# ------------------------------------------------------------------- replay
@dataclass(frozen=True)
class ReplayStep:
    offset: int
    size: int
    kind: str
    action: str                # 'verbatim' | 'reencoded' | 'asserted_pi' | 'refused'
    new_bytes: bytes | None
    reason: str = ""


@dataclass(frozen=True)
class ReplayPlan:
    isa: str
    old_addr: int
    new_addr: int
    steps: tuple

    @property
    def refusals(self):
        return [f"+0x{s.offset:X} {s.kind}: {s.reason}" for s in self.steps if s.action == "refused"]

    @property
    def ok(self):
        return not self.refusals

    def replay_bytes(self):
        """Exact bytes to place at new_addr; raises ReplayRefusedError unless every step is safe."""
        if not self.ok:
            raise ReplayRefusedError(self.refusals)
        return b"".join(s.new_bytes for s in self.steps)


_PCREL_KINDS = {"bl", "blx", "b", "bcond", "ldr_lit", "adr"}
_PI_KINDS = {"pi", "push", "pop", "nop", "svc", "bx", "blx_reg"}


def plan_replay(displaced, old_addr, new_addr, isa, pic_offsets=()):
    """Plan to re-run `displaced` (the bytes overwritten at old_addr) from new_addr.

    PC-relative forms (B/BL/BLX, B<cond>, literal loads, ADR) keep their ORIGINAL absolute
    target and are re-encoded for new_addr, or refused when the new displacement does not fit.
    A target inside the displaced span itself moves with the span (new_addr + its offset).
    Instructions that read PC through a register field, unclassified instructions and a span that
    cuts a Thumb BL pair are refused unless their byte offset is listed in `pic_offsets`, which is
    the caller's explicit assertion that the instruction is position independent (it is then copied
    verbatim). A pic_offsets entry that is not the start of a decoded instruction raises
    ReplayRefusedError, never ignored. Replay does not re-create LR: a replayed call returns to
    whatever follows it at the NEW address, which the caller's continuation must account for.
    """
    if isa not in (THUMB, ARM):
        raise IsaEncodingError(f"isa must be {THUMB!r} or {ARM!r}")
    align = 2 if isa == THUMB else 4
    _site(old_addr, align)
    _site(new_addr, align)
    displaced = bytes(displaced)
    if not displaced or len(displaced) % align:
        raise IsaEncodingError(f"displaced span must be a non-empty multiple of {align} bytes")
    pic, steps, off = set(pic_offsets), [], 0
    while off < len(displaced):
        ins = (decode_thumb if isa == THUMB else decode_arm)(displaced, off, old_addr + off)
        here, step = new_addr + off, None
        size = ins.size
        raw = displaced[off:off + size]
        if ins.kind in _PCREL_KINDS and old_addr <= ins.target < old_addr + len(displaced):
            # a target inside the displaced span moves with it
            ins = replace(ins, target=new_addr + (ins.target - old_addr))
        try:
            new = _reencode(ins, here)
        except NdsIsaError as exc:
            step = ReplayStep(off, size, ins.kind, "refused", None, f"cannot re-encode at 0x{here:08X}: {exc}")
        else:
            if new is not None:
                step = ReplayStep(off, size, ins.kind, "reencoded", new)
            elif ins.kind in _PI_KINDS:
                step = ReplayStep(off, size, ins.kind, "verbatim", raw)
        if step is None:
            if off in pic:
                step = ReplayStep(off, size, ins.kind, "asserted_pi", raw)
            else:
                why = {"split": "span cuts a Thumb BL pair", "pc_read": "reads PC through a register",
                       "unknown": "unclassified instruction"}[ins.kind]
                step = ReplayStep(off, size, ins.kind, "refused", None, why)
        steps.append(step)
        off += size
    stray = pic - {s.offset for s in steps}
    if stray:
        raise ReplayRefusedError(
            [f"pic_offsets +0x{o:X} matches no decoded instruction" for o in sorted(stray)])
    return ReplayPlan(isa, old_addr, new_addr, tuple(steps))


def _reencode(ins, here):
    """Bytes for a PC-relative `ins` moved to `here`, or None when it is not PC-relative."""
    k = ins.kind
    if ins.isa == THUMB:
        if k == "bl":
            return thumb_bl(here, ins.target)
        if k == "blx":
            return thumb_bl(here, ins.target, exchange=True)
        if k == "b":
            return thumb_b(here, ins.target)
        if k == "bcond":
            return thumb_bcond(here, ins.target, ins.cond)
        if k == "ldr_lit":
            return thumb_ldr_literal(here, ins.reg, ins.target)
        if k == "adr":
            return thumb_adr(here, ins.reg, ins.target)
        return None
    if k in ("b", "bl"):
        return arm_branch(here, ins.target, link=k == "bl", cond=ins.cond)
    if k == "blx":
        return arm_blx_imm(here, ins.target)
    if k == "ldr_lit":
        off = _fit(ins.target - (here + 8), -4095, 4095, "arm ldr literal")
        word = (ins.word & ~(0x00800000 | 0xFFF)) | (0x00800000 if off >= 0 else 0) | abs(off)
        return _pack32(word)
    return None
