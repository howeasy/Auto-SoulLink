"""ARM/Thumb helper tests: hand-computed ARM ARM vectors, round trips, refusals, mutation
controls, replay planning, and read-only Black/Black 2 ARM9 measurements.

Hand vectors are computed from the formulas quoted in tools/nds_isa.py, NOT by running the module.
"""
import importlib.util
import os
import random
import struct
import sys
from pathlib import Path

import pytest

from tools import nds_isa as isa

SRC = Path(isa.__file__)


def h(*halfwords):
    return b"".join(x.to_bytes(2, "little") for x in halfwords)


def w(word):
    return word.to_bytes(4, "little")


S = 0x02000000
# (name, call(mod) -> bytes, expected). Each value is derived by hand in the comment.
VECTORS = [
    # Thumb BL: off = 0x100 - 4 = 0xFC -> hi 0, lo 0xFC >> 1 = 0x7E.
    ("t_bl", lambda m: m.thumb_bl(S, S + 0x100), h(0xF000, 0xF87E)),
    # max +0x3FFFFE -> hi 0x3FF, lo 0x7FF; min -0x400000 -> hi 0x400, lo 0.
    ("t_bl_max", lambda m: m.thumb_bl(S, S + 4 + 0x3FFFFE), h(0xF3FF, 0xFFFF)),
    ("t_bl_min", lambda m: m.thumb_bl(S + 0x500000, S + 0x500004 - 0x400000), h(0xF400, 0xF800)),
    # BLX from a word-aligned site: Align(S+4) = S+4, off 0xFC; second half 0xE800 | 0x7E.
    ("t_blx", lambda m: m.thumb_blx(S, S + 0x100), h(0xF000, 0xE87E)),
    # BLX from a site = 2 mod 4: Align(S+6) = S+4, so the same off (0xFC) gives the same halfwords.
    ("t_blx_site2", lambda m: m.thumb_blx(S + 2, S + 0x100), h(0xF000, 0xE87E)),
    # B: off 0xC -> imm11 6; off -8 -> 0x7FC; b . (off -4 -> -2) = 0xE7FE; +2046 -> 0x3FF; -2048 -> 0x400.
    ("t_b", lambda m: m.thumb_b(0x1000, 0x1010), h(0xE006)),
    ("t_b_back", lambda m: m.thumb_b(0x1000, 0x0FFC), h(0xE7FC)),
    ("t_b_dot", lambda m: m.thumb_b(0x1000, 0x1000), h(0xE7FE)),
    ("t_b_max", lambda m: m.thumb_b(0x1000, 0x1004 + 2046), h(0xE3FF)),
    ("t_b_min", lambda m: m.thumb_b(0x1000, 0x1004 - 2048), h(0xE400)),
    # B<cond>: off 0xC -> imm8 6 (beq 0xD006, bne 0xD106); min -256 -> 0x80.
    ("t_beq", lambda m: m.thumb_bcond(0x1000, 0x1010, "eq"), h(0xD006)),
    ("t_bne", lambda m: m.thumb_bcond(0x1000, 0x1010, "ne"), h(0xD106)),
    ("t_bne_min", lambda m: m.thumb_bcond(0x1000, 0x1004 - 256, "ne"), h(0xD180)),
    ("t_bx_r3", lambda m: m.thumb_bx(3), h(0x4718)),
    ("t_bx_lr", lambda m: m.thumb_bx(14), h(0x4770)),
    ("t_blx_r3", lambda m: m.thumb_bx(3, link=True), h(0x4798)),
    # ldr r3,[pc,#0] at aligned 0x1000: literal at Align(0x1004) = 0x1004. At 0x1002: Align(0x1006) = 0x1004.
    ("t_ldr0", lambda m: m.thumb_ldr_literal(0x1000, 3, 0x1004), h(0x4B00)),
    ("t_ldr0_site2", lambda m: m.thumb_ldr_literal(0x1002, 3, 0x1004), h(0x4B00)),
    ("t_ldr1_site2", lambda m: m.thumb_ldr_literal(0x1002, 3, 0x1008), h(0x4B01)),
    ("t_ldr_max", lambda m: m.thumb_ldr_literal(0x1000, 0, 0x1004 + 1020), h(0x48FF)),
    ("t_adr", lambda m: m.thumb_adr(0x1000, 2, 0x1008), h(0xA201)),
    ("t_push", lambda m: m.thumb_push([4, 14]), h(0xB510)),
    ("t_push3", lambda m: m.thumb_push([3, 4, 5, 14]), h(0xB538)),
    ("t_pop", lambda m: m.thumb_pop([4, 15]), h(0xBD10)),
    ("t_nop", lambda m: m.THUMB_NOP, h(0x46C0)),
    ("t_mov_r8_r8", lambda m: m.thumb_mov(8, 8), h(0x46C0)),
    # Gen 3 build.py thumb_entry_jump: 004b 1847 + (dest|1)
    ("t_veneer", lambda m: m.thumb_detour(0x1000, 0x2001, "veneer"), bytes.fromhex("004b1847") + w(0x2001)),
    ("t_veneer_arm", lambda m: m.thumb_detour(0x1000, 0x2000, "veneer"), bytes.fromhex("004b1847") + w(0x2000)),
    # ARM B/BL: off 0x10 - 8 = 8 -> imm24 2; b . = off -8 -> -2 = 0xFFFFFE; max +0x1FFFFFC -> 0x7FFFFF; min -> 0x800000.
    ("a_b", lambda m: m.arm_branch(S, S + 0x10), w(0xEA000002)),
    ("a_bl", lambda m: m.arm_branch(S, S + 0x10, link=True), w(0xEB000002)),
    ("a_b_dot", lambda m: m.arm_branch(S, S), w(0xEAFFFFFE)),
    ("a_bl_max", lambda m: m.arm_branch(S, S + 8 + 0x1FFFFFC, link=True), w(0xEB7FFFFF)),
    ("a_bl_min", lambda m: m.arm_branch(S + 0x4000000, S + 0x4000008 - 0x2000000, link=True), w(0xEB800000)),
    ("a_bne", lambda m: m.arm_branch(S, S + 0x10, cond="ne"), w(0x1A000002)),
    # BLX(1): off 0x12 - 8 = 0xA -> imm24 2, H = (0xA >> 1) & 1 = 1.
    ("a_blx", lambda m: m.arm_blx_imm(S, S + 0x12), w(0xFB000002)),
    ("a_blx_h0", lambda m: m.arm_blx_imm(S, S + 0x10), w(0xFA000002)),
    ("a_bx_lr", lambda m: m.arm_bx(14), w(0xE12FFF1E)),
    ("a_blx_r3", lambda m: m.arm_bx(3, link=True), w(0xE12FFF33)),
    ("a_nop", lambda m: m.ARM_NOP, w(0xE1A00000)),
    ("a_push", lambda m: m.arm_push([4, 14]), w(0xE92D4010)),
    ("a_pop", lambda m: m.arm_pop([4, 15]), w(0xE8BD8010)),
    # ldr r0,[pc,#0x10] = E59F0010; ldr r0,[pc,#-8] = E51F0008; ldr pc,[pc,#-4] = E51FF004.
    ("a_ldr_pos", lambda m: m.arm_ldr_literal(S, 0, S + 8 + 0x10), w(0xE59F0010)),
    ("a_ldr_neg", lambda m: m.arm_ldr_literal(S, 0, S), w(0xE51F0008)),
    ("a_veneer", lambda m: m.arm_detour(S, 0x2001, "veneer"), w(0xE51FF004) + w(0x2001)),
]

# (name, call(mod), exception class NAME)
REFUSALS = [
    ("bl_over", lambda m: m.thumb_bl(S, S + 4 + 0x3FFFFE + 2), "IsaRangeError"),
    ("bl_under", lambda m: m.thumb_bl(S + 0x500000, S + 0x500004 - 0x400000 - 2), "IsaRangeError"),
    ("blx_over", lambda m: m.thumb_blx(S, S + 4 + 0x3FFFFC + 4), "IsaRangeError"),
    ("bl_odd_target", lambda m: m.thumb_bl(S, S + 0x101), "IsaAlignmentError"),
    ("bl_odd_site", lambda m: m.thumb_bl(S + 1, S + 0x100), "IsaAlignmentError"),
    ("blx_halfword_target", lambda m: m.thumb_blx(S, S + 0x102), "IsaAlignmentError"),
    ("b_over", lambda m: m.thumb_b(0x1000, 0x1004 + 2048), "IsaRangeError"),
    ("bcond_over", lambda m: m.thumb_bcond(0x1000, 0x1004 + 256, "eq"), "IsaRangeError"),
    ("bcond_al", lambda m: m.thumb_bcond(0x1000, 0x1010, "al"), "IsaEncodingError"),
    ("bx_pc", lambda m: m.thumb_bx(15), "IsaEncodingError"),
    ("ldr_hi_reg", lambda m: m.thumb_ldr_literal(0x1000, 8, 0x1004), "IsaEncodingError"),
    ("ldr_unaligned_lit", lambda m: m.thumb_ldr_literal(0x1000, 0, 0x1006), "IsaAlignmentError"),
    ("ldr_behind", lambda m: m.thumb_ldr_literal(0x1000, 0, 0x1000), "IsaRangeError"),
    ("ldr_far", lambda m: m.thumb_ldr_literal(0x1000, 0, 0x1004 + 1024), "IsaRangeError"),
    ("push_r8", lambda m: m.thumb_push([8]), "IsaEncodingError"),
    ("pop_lr", lambda m: m.thumb_pop([14]), "IsaEncodingError"),
    ("push_empty", lambda m: m.thumb_push([]), "IsaEncodingError"),
    ("veneer_site2", lambda m: m.thumb_detour(0x1002, 0x2001, "veneer"), "IsaAlignmentError"),
    ("veneer_bad_arm_ptr", lambda m: m.thumb_detour(0x1000, 0x2002, "veneer"), "IsaAlignmentError"),
    ("bl_to_arm", lambda m: m.thumb_detour(S, 0x02000100, "bl"), "IsaWrongFormError"),
    ("blx_to_thumb", lambda m: m.thumb_detour(S, 0x02000101, "blx"), "IsaWrongFormError"),
    ("b_to_arm", lambda m: m.thumb_detour(S, 0x02000100, "b"), "IsaWrongFormError"),
    ("bcond_needs_cond", lambda m: m.thumb_detour(S, 0x02000101, "bcond"), "IsaEncodingError"),
    ("thumb_unknown_kind", lambda m: m.thumb_detour(S, 0x02000101, "jmp"), "IsaEncodingError"),
    ("arm_b_over", lambda m: m.arm_branch(S, S + 8 + 0x1FFFFFC + 4), "IsaRangeError"),
    ("arm_b_under", lambda m: m.arm_branch(S + 0x4000000, S + 0x4000008 - 0x2000000 - 4), "IsaRangeError"),
    ("arm_b_misaligned", lambda m: m.arm_branch(S, S + 0x12), "IsaAlignmentError"),
    ("arm_site_misaligned", lambda m: m.arm_branch(S + 2, S + 0x10), "IsaAlignmentError"),
    ("arm_blx_over", lambda m: m.arm_blx_imm(S, S + 8 + 0x1FFFFFE + 2), "IsaRangeError"),
    ("arm_blx_odd", lambda m: m.arm_blx_imm(S, S + 0x11), "IsaAlignmentError"),
    ("arm_b_to_thumb", lambda m: m.arm_detour(S, 0x02000101, "bl"), "IsaWrongFormError"),
    ("arm_blx_to_arm", lambda m: m.arm_detour(S, 0x02000100, "blx"), "IsaWrongFormError"),
    ("arm_blx_cond", lambda m: m.arm_detour(S, 0x02000101, "blx", cond="ne"), "IsaEncodingError"),
    ("arm_bx_pc", lambda m: m.arm_bx(15), "IsaEncodingError"),
    ("arm_ldr_far", lambda m: m.arm_ldr_literal(S, 0, S + 8 + 4096), "IsaRangeError"),
    ("arm_ldr_unaligned", lambda m: m.arm_ldr_literal(S, 0, S + 10), "IsaAlignmentError"),
    ("arm_push_empty", lambda m: m.arm_push([]), "IsaEncodingError"),
    ("arm_push_pc", lambda m: m.arm_push([4, 15]), "IsaEncodingError"),
    ("arm_bad_cond", lambda m: m.arm_branch(S, S + 8, cond="xx"), "IsaEncodingError"),
    ("classify_arm_bit1", lambda m: m.classify_code_address(0x02000102), "IsaAlignmentError"),
    ("interwork_bad_isa", lambda m: m.needs_interwork("thumb", "x86"), "IsaEncodingError"),
]


def vector_failures(mod):
    """Names of vectors the module gets wrong. Exceptions are failures, not crashes."""
    bad = []
    for name, call, expected in VECTORS:
        try:
            if call(mod) != expected:
                bad.append(name)
        except Exception:
            bad.append(name)
    for name, call, exc in REFUSALS:
        try:
            call(mod)
            bad.append(name)
        except Exception as e:
            if type(e).__name__ != exc:
                bad.append(name)
    return bad


# ------------------------------------------------------------------ vectors
def test_baseline_vectors_all_hold():
    assert vector_failures(isa) == [] and decode_failures(isa) == []


def test_vector_table_is_nontrivial():
    assert len(VECTORS) >= 40 and len(REFUSALS) >= 35


def test_errors_share_one_base():
    for cls in (isa.IsaRangeError, isa.IsaAlignmentError, isa.IsaWrongFormError,
                isa.IsaEncodingError, isa.IsaDecodeError, isa.ReplayRefusedError):
        assert issubclass(cls, isa.NdsIsaError)


def test_gen3_thumb_entry_jump_equivalence():
    # patch/tools/build.py thumb_entry_jump(address, destination): 004b1847 + (destination | 1)
    assert isa.thumb_detour(0x08000100, 0x08A00001, "veneer") == bytes.fromhex("004b1847") + w(0x08A00001)


def test_interworking_table():
    assert isa.classify_code_address(0x02001001) == ("thumb", 0x02001000)
    assert isa.classify_code_address(0x02001000) == ("arm", 0x02001000)
    assert isa.code_pointer("thumb", 0x02001000) == 0x02001001
    assert isa.code_pointer("arm", 0x02001000) == 0x02001000
    with pytest.raises(isa.IsaAlignmentError):
        isa.code_pointer("arm", 0x02001002)
    assert [isa.needs_interwork(a, b) for a, b in
            (("thumb", "thumb"), ("thumb", "arm"), ("arm", "thumb"), ("arm", "arm"))] == [False, True, True, False]
    assert [isa.call_form(a, b) for a, b in
            (("thumb", "thumb"), ("thumb", "arm"), ("arm", "thumb"), ("arm", "arm"))] == ["bl", "blx", "blx", "bl"]


def test_decode_hand_vectors():
    d = isa.decode_thumb(h(0xF000, 0xF87E), 0, S)
    assert (d.kind, d.size, d.target, d.target_isa) == ("bl", 4, S + 0x100, "thumb")
    d = isa.decode_thumb(h(0xF000, 0xE87E), 0, S + 2)
    assert (d.kind, d.target, d.target_isa) == ("blx", S + 0x100, "arm")
    d = isa.decode_thumb(h(0xE7FE), 0, 0x1000)
    assert (d.kind, d.target) == ("b", 0x1000)
    d = isa.decode_thumb(h(0xD106), 0, 0x1000)
    assert (d.kind, d.cond, d.target) == ("bcond", 1, 0x1010)
    d = isa.decode_thumb(h(0x4B01), 0, 0x1002)
    assert (d.kind, d.reg, d.target) == ("ldr_lit", 3, 0x1008)
    assert isa.decode_thumb(h(0x4770), 0, 0).kind == "bx"
    assert isa.decode_thumb(h(0x46C0), 0, 0).kind == "nop"
    d = isa.decode_thumb(h(0xB538), 0, 0)
    assert (d.kind, d.regs) == ("push", (3, 4, 5, 14))
    assert isa.decode_thumb(h(0xBD10), 0, 0).regs == (4, 15)
    d = isa.decode_arm(w(0xEB000002), 0, S)
    assert (d.kind, d.target, d.cond) == ("bl", S + 0x10, 14)
    d = isa.decode_arm(w(0xFB000002), 0, S)
    assert (d.kind, d.target, d.target_isa) == ("blx", S + 0x12, "thumb")
    d = isa.decode_arm(w(0xE51F0008), 0, S)
    assert (d.kind, d.target) == ("ldr_lit", S)
    assert isa.decode_arm(w(0xE92D4010), 0, 0).kind == "push"
    assert isa.decode_arm(w(0xE8BD8010), 0, 0).regs == (4, 15)
    assert isa.decode_arm(w(0xE12FFF1E), 0, 0).kind == "bx"
    assert isa.decode_arm(w(0xE1A0F00E), 0, 0).kind == "pi"           # mov pc, lr
    assert isa.decode_arm(w(0xE28F0004), 0, 0).kind == "pc_read"      # add r0, pc, #4


def test_decode_refuses_malformed():
    with pytest.raises(isa.IsaDecodeError):
        isa.decode_thumb(b"\x00", 0, 0)
    with pytest.raises(isa.IsaDecodeError):
        isa.decode_arm(b"\0\0\0\0", 2, 0)
    assert isa.decode_thumb(h(0xF000), 0, 0).kind == "split"                 # prefix, no suffix in buffer
    assert isa.decode_thumb(h(0xF000, 0x1234), 0, 0).kind == "unknown"       # prefix then not a suffix
    assert isa.decode_thumb(h(0xF000, 0xE87F), 0, 0).kind == "unknown"      # BLX with bit0 set
    assert isa.decode_thumb(h(0xF800), 0, 0).kind == "unknown"              # stray suffix


# --------------------------------------------------------------- round trip
def rng():
    return random.Random(0x5EED)


def test_roundtrip_thumb_bl_blx_b_bcond_ldr_adr():
    r = rng()
    for _ in range(2000):
        site = r.randrange(0x02000000, 0x02800000, 2)
        off = r.choice((-0x400000, 0x3FFFFE, 0, -2, 2, r.randrange(-0x400000, 0x400000, 2)))
        tgt = site + 4 + off
        d = isa.decode_thumb(isa.thumb_bl(site, tgt), 0, site)
        assert (d.kind, d.target, d.size) == ("bl", tgt, 4)
        # BLX: target word aligned, base Align(site + 4)
        tgt = ((site + 4) & ~3) + r.choice((-0x400000, 0x3FFFFC, 0, r.randrange(-0x400000, 0x400000, 4)))
        d = isa.decode_thumb(isa.thumb_blx(site, tgt), 0, site)
        assert (d.kind, d.target) == ("blx", tgt)
        tgt = site + 4 + r.choice((-2048, 2046, r.randrange(-2048, 2048, 2)))
        assert isa.decode_thumb(isa.thumb_b(site, tgt), 0, site).target == tgt
        cond = r.randrange(0, 14)
        tgt = site + 4 + r.choice((-256, 254, r.randrange(-256, 256, 2)))
        d = isa.decode_thumb(isa.thumb_bcond(site, tgt, cond), 0, site)
        assert (d.kind, d.cond, d.target) == ("bcond", cond, tgt)
        lit = ((site + 4) & ~3) + 4 * r.randrange(0, 256)
        rt = r.randrange(8)
        d = isa.decode_thumb(isa.thumb_ldr_literal(site, rt, lit), 0, site)
        assert (d.kind, d.reg, d.target) == ("ldr_lit", rt, lit)
        d = isa.decode_thumb(isa.thumb_adr(site, rt, lit), 0, site)
        assert (d.kind, d.reg, d.target) == ("adr", rt, lit)


def test_roundtrip_arm_b_bl_blx_ldr():
    r = rng()
    for _ in range(2000):
        site = r.randrange(0x02000000, 0x02800000, 4)
        for link in (False, True):
            tgt = site + 8 + r.choice((-0x2000000, 0x1FFFFFC, 0, r.randrange(-0x2000000, 0x2000000, 4)))
            cond = r.randrange(0, 15)
            d = isa.decode_arm(isa.arm_branch(site, tgt, link, cond), 0, site)
            assert (d.kind, d.target, d.cond) == ("bl" if link else "b", tgt, cond)
        tgt = site + 8 + r.choice((-0x2000000, 0x1FFFFFE, r.randrange(-0x2000000, 0x2000000, 2)))
        d = isa.decode_arm(isa.arm_blx_imm(site, tgt), 0, site)
        assert (d.kind, d.target, d.target_isa) == ("blx", tgt, "thumb")
        lit, rd = site + 8 + 4 * r.randrange(-1023, 1024), r.randrange(16)
        d = isa.decode_arm(isa.arm_ldr_literal(site, rd, lit), 0, site)
        assert (d.kind, d.reg, d.target) == ("ldr_lit", rd, lit)


def test_roundtrip_regs_and_veneers():
    for rm in range(15):
        assert isa.decode_thumb(isa.thumb_bx(rm), 0, 0).reg == rm
        assert isa.decode_thumb(isa.thumb_bx(rm, link=True), 0, 0).kind == "blx_reg"
        d = isa.decode_arm(isa.arm_bx(rm, link=True, cond="eq"), 0, 0)
        assert (d.kind, d.reg, d.cond) == ("blx_reg", rm, 0)
    r = rng()
    for _ in range(200):
        regs = sorted(r.sample(range(8), r.randrange(1, 8)))
        assert isa.decode_thumb(isa.thumb_push(regs + [14]), 0, 0).regs == tuple(regs + [14])
        assert isa.decode_thumb(isa.thumb_pop(regs + [15]), 0, 0).regs == tuple(regs + [15])
        regs = sorted(r.sample(range(15), r.randrange(1, 15)))
        assert isa.decode_arm(isa.arm_push(regs), 0, 0).regs == tuple(regs)
        assert isa.decode_arm(isa.arm_pop(regs + [15]), 0, 0).regs == tuple(regs + [15])
    # Thumb veneer decodes as ldr r3; bx r3; word. ARM veneer as ldr pc literal pointing at its own word.
    v = isa.thumb_detour(0x1000, 0x2001, "veneer")
    a, b = isa.decode_thumb(v, 0, 0x1000), isa.decode_thumb(v, 2, 0x1002)
    assert (a.kind, a.reg, a.target, b.kind, b.reg) == ("ldr_lit", 3, 0x1004, "bx", 3)
    v = isa.arm_detour(0x1000, 0x2001, "veneer")
    d = isa.decode_arm(v, 0, 0x1000)
    assert (d.kind, d.reg, d.target) == ("ldr_lit", 15, 0x1004)
    assert isa.arm_detour(0x1000, 0x2000, "veneer")[4:] == w(0x2000)


def test_detour_dispatch_roundtrips_both_isas():
    site = 0x02001000
    assert isa.decode_thumb(isa.thumb_detour(site, 0x02005001, "bl"), 0, site).target == 0x02005000
    assert isa.decode_thumb(isa.thumb_detour(site, 0x02005000, "blx"), 0, site).target == 0x02005000
    assert isa.decode_thumb(isa.thumb_detour(site, 0x02001011, "b"), 0, site).target == 0x02001010
    assert isa.decode_thumb(isa.thumb_detour(site, 0x02001011, "bcond", "lt"), 0, site).cond == 11
    assert isa.decode_arm(isa.arm_detour(site, 0x02005000, "bl"), 0, site).target == 0x02005000
    assert isa.decode_arm(isa.arm_detour(site, 0x02005000, "b", "ne"), 0, site).cond == 1
    assert isa.decode_arm(isa.arm_detour(site, 0x02005001, "blx"), 0, site).target == 0x02005000


# ----------------------------------------------------------- negative sweep
@pytest.mark.parametrize("name,call,exc", REFUSALS, ids=[r[0] for r in REFUSALS])
def test_named_refusals(name, call, exc):
    with pytest.raises(isa.NdsIsaError) as info:
        call(isa)
    assert type(info.value).__name__ == exc


# --------------------------------------------------------- mutation controls
MUTATIONS = {
    "thumb_bl_pc_bias_off_by_two": (
        'off = target - (site + 4)\n        _fit(off, -0x400000, 0x3FFFFE, "thumb bl")',
        'off = target - (site + 2)\n        _fit(off, -0x400000, 0x3FFFFE, "thumb bl")'),
    "thumb_bl_range_off_by_one_step": (
        '_fit(off, -0x400000, 0x3FFFFE, "thumb bl")', '_fit(off, -0x400000, 0x400000, "thumb bl")'),
    "thumb_blx_alignment_mask": (
        "off = target - ((site + 4) & ~3)", "off = target - ((site + 4) & ~1)"),
    "thumb_ldr_literal_missing_align": (
        '_fit(literal_addr - ((site + 4) & ~3), 0, 1020, "thumb ldr literal")',
        '_fit(literal_addr - (site + 4), 0, 1020, "thumb ldr literal")'),
    "thumb_bcond_range": ('-256, 254, "thumb b<cond>"', '-256, 256, "thumb b<cond>"'),
    "thumb_veneer_missing_bit0": (
        "thumb_bx(3) + _pack32(target)", "thumb_bx(3) + _pack32(target & ~1)"),
    "thumb_detour_wrong_isa_guard_removed": (
        'if isa != THUMB:\n            raise IsaWrongFormError("thumb BL', 'if False:\n            raise IsaWrongFormError("thumb BL'),
    "arm_pc_plus4_instead_of_plus8": (
        'off = _fit(target - (site + 8), -0x2000000, 0x1FFFFFC, "arm b/bl")',
        'off = _fit(target - (site + 4), -0x2000000, 0x1FFFFFC, "arm b/bl")'),
    "arm_blx_h_bit_dropped": ("(((off >> 1) & 1) << 24)", "(0 << 24)"),
    "arm_ldr_literal_pc_plus4": (
        'off = _fit(literal_addr - (site + 8), -4095, 4095, "arm ldr literal")',
        'off = _fit(literal_addr - (site + 4), -4095, 4095, "arm ldr literal")'),
    "arm_veneer_literal_offset": (
        "return arm_ldr_literal(site, PC, site + 4) + _pack32(target)",
        "return arm_ldr_literal(site, PC, site + 8) + _pack32(target)"),
    "thumb_decoder_pc_bias": ('return "bl", addr + 4 + off', 'return "bl", addr + 2 + off'),
    "thumb_decoder_blx_mask": ('return "blx", (addr + 4 + off) & ~3', 'return "blx", (addr + 4 + off) & ~1'),
    "thumb_hireg_rm_pc_check_dropped": (
        'return mk("pc_read") if rm == 15 or (rd == 15 and op != 2) else mk("pi")',
        'return mk("pc_read") if (rd == 15 and op != 2) else mk("pi")'),
    "arm_regoffset_pc_check_dropped": (
        'return mk("pc_read") if 15 in (w >> 16 & 15, w & 15) else mk("pi")', 'return mk("pi")'),
    "arm_ldm_rn_pc_check_dropped": (
        'if rn == 15:\n            return mk("pc_read")\n        if w & 0x01FF0000',
        'if False:\n            return mk("pc_read")\n        if w & 0x01FF0000'),
    "arm_decoder_pc_plus4": (
        "target = addr + 8 + (_sext(w & 0xFFFFFF, 24) << 2)\n        return mk(\"bl\"",
        "target = addr + 4 + (_sext(w & 0xFFFFFF, 24) << 2)\n        return mk(\"bl\""),
}


def import_copy(path, modname):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod      # dataclasses resolves string annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


def load_mutant(tmp_path, name):
    old, new = MUTATIONS[name]
    text = SRC.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"mutation {name} anchor must match exactly once"
    path = tmp_path / f"nds_isa_mut_{name}.py"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return import_copy(path, f"nds_isa_mut_{name}")


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_mutation_control_is_detected(tmp_path, name):
    mut = load_mutant(tmp_path, name)
    bad = vector_failures(mut)
    # decoder-only mutations are not reached by encode vectors; they are also caught by the decode checks
    if not bad:
        bad = decode_failures(mut)
    assert bad, f"mutation {name} survived every vector"


def decode_failures(mod):
    bad = []
    d = mod.decode_thumb(h(0xF000, 0xF87E), 0, S)
    if (d.kind, d.target) != ("bl", S + 0x100):
        bad.append("t_bl")
    d = mod.decode_thumb(h(0xF000, 0xE87E), 0, S + 2)
    if (d.kind, d.target) != ("blx", S + 0x100):
        bad.append("t_blx")
    d = mod.decode_arm(w(0xEB000002), 0, S)
    if (d.kind, d.target) != ("bl", S + 0x10):
        bad.append("a_bl")
    # PC read through a register field must stay refused for replay
    for name, d in (("t_add_pc", mod.decode_thumb(h(0x4478), 0, 0)),          # add r0, pc
                    ("a_ldr_pc_rn", mod.decode_arm(w(0xE79F0001), 0, 0)),     # ldr r0, [pc, r1]
                    ("a_ldr_pc_rm", mod.decode_arm(w(0xE791000F), 0, 0)),     # ldr r0, [r1, pc]
                    ("a_ldm_pc_rn", mod.decode_arm(w(0xE89F0001), 0, 0))):    # ldmia pc, {r0}
        if d.kind != "pc_read":
            bad.append(name)
    return bad


def test_mutation_harness_has_a_clean_control(tmp_path):
    """The identity 'mutation' (unmodified source) must pass, so detection above is real."""
    path = tmp_path / "nds_isa_clean.py"
    path.write_text(SRC.read_text(encoding="utf-8"), encoding="utf-8")
    mod = import_copy(path, "nds_isa_clean")
    assert vector_failures(mod) == [] and decode_failures(mod) == []


# --------------------------------------------------------------------- scan
def test_scan_synthetic_pairs_and_false_positive_documentation():
    base = 0x02000000
    code = h(0x46C0) + isa.thumb_bl(base + 2, base + 0x200) + isa.thumb_blx(base + 6, base + 0x400)
    sites = isa.find_bl_sites(code, base, "thumb")
    assert [(s.addr, s.kind, s.target) for s in sites] == [(base + 2, "bl", base + 0x200),
                                                            (base + 6, "blx", base + 0x400)]
    assert sites[0].target_pointer == (base + 0x200) | 1 and sites[1].target_pointer == base + 0x400
    # Documented limitation: a data halfword pair that looks like BL IS reported.
    assert len(isa.find_bl_sites(h(0xF000, 0xF800), base, "thumb")) == 1
    # A prefix as the final halfword is not reported.
    assert isa.find_bl_sites(h(0x46C0, 0xF000), base, "thumb") == []
    arm = w(0xE1A00000) + isa.arm_branch(base + 4, base + 0x100, link=True, cond="ne") + isa.arm_blx_imm(base + 8, base + 0x202)
    got = isa.find_bl_sites(arm, base, "arm")
    assert [(s.kind, s.target, s.target_isa, s.cond) for s in got] == [
        ("bl", base + 0x100, "arm", 1), ("blx", base + 0x202, "thumb", 15)]
    assert got[1].target_pointer == base + 0x203
    with pytest.raises(isa.IsaAlignmentError):
        isa.find_bl_sites(code, base + 1, "thumb")


# ------------------------------------------------------------------- replay
def test_replay_thumb_emerald_style_literal_load():
    old = 0x08100000
    lit = old + 0x40
    span = isa.thumb_push([4, 14]) + isa.thumb_ldr_literal(old + 2, 4, lit) + h(0x6820, 0x2800)  # ldr r0,[r4]; cmp r0,#0
    ok = isa.plan_replay(span, old, old + 0x20, "thumb")
    assert ok.ok
    assert [s.action for s in ok.steps] == ["verbatim", "reencoded", "verbatim", "verbatim"]
    moved = ok.replay_bytes()
    d = isa.decode_thumb(moved, 2, old + 0x22)
    assert (d.kind, d.reg, d.target) == ("ldr_lit", 4, lit)           # same absolute literal
    assert moved[:2] == span[:2] and moved[4:] == span[4:]
    # Moved beyond the literal: Thumb LDR literal cannot reach backwards -> refused, never emitted.
    bad = isa.plan_replay(span, old, old + 0x100, "thumb")
    assert not bad.ok and "ldr_lit" in bad.refusals[0]
    with pytest.raises(isa.ReplayRefusedError) as info:
        bad.replay_bytes()
    assert "displacement" in str(info.value)
    # Verbatim replay of the same bytes would silently load a different word; the plan proves it differs.
    assert isa.decode_thumb(span, 2, old + 0x100 + 2).target != lit


def test_replay_thumb_branches_and_far_bl():
    old = 0x02010000
    span = isa.thumb_bl(old, 0x02020000) + isa.thumb_b(old + 4, old + 0x20)
    plan = isa.plan_replay(span, old, old + 0x40, "thumb")
    assert plan.ok and [s.action for s in plan.steps] == ["reencoded", "reencoded"]
    out = plan.replay_bytes()
    assert isa.decode_thumb(out, 0, old + 0x40).target == 0x02020000
    assert isa.decode_thumb(out, 4, old + 0x44).target == old + 0x20
    far = isa.plan_replay(span, old, old + 0x1000000, "thumb")      # BL out of +-4 MB, B out of 11 bits
    assert not far.ok and len(far.refusals) == 2


def test_replay_refuses_pc_reads_unknown_and_split_unless_asserted():
    old = 0x02010000
    add_pc = h(0x4478)                       # add r0, pc
    plan = isa.plan_replay(add_pc, old, old + 8, "thumb")
    assert not plan.ok and "PC" in plan.refusals[0]
    asserted = isa.plan_replay(add_pc, old, old + 8, "thumb", pic_offsets=[0])
    assert asserted.ok and asserted.steps[0].action == "asserted_pi" and asserted.replay_bytes() == add_pc
    assert not isa.plan_replay(h(0xDE00), old, old + 8, "thumb").ok          # undefined cond 0xE
    split = isa.plan_replay(h(0x46C0, 0xF000), old, old + 8, "thumb")        # span ends mid BL pair
    assert not split.ok and "BL pair" in split.refusals[0]
    with pytest.raises(isa.IsaAlignmentError):
        isa.plan_replay(add_pc, old, old + 1, "thumb")
    with pytest.raises(isa.IsaEncodingError):
        isa.plan_replay(b"\0\0\0", old, old, "thumb")


def test_replay_arm():
    old = 0x02010000
    span = (w(0xE92D4010)                                   # push {r4, lr}
            + isa.arm_ldr_literal(old + 4, 4, old + 0x40)
            + isa.arm_branch(old + 8, old + 0x1000, link=True)
            + w(0xE1A0F00E))                                # mov pc, lr
    plan = isa.plan_replay(span, old, old + 0x200, "arm")
    assert plan.ok and [s.action for s in plan.steps] == ["verbatim", "reencoded", "reencoded", "verbatim"]
    out = plan.replay_bytes()
    assert isa.decode_arm(out, 4, old + 0x204).target == old + 0x40
    assert isa.decode_arm(out, 8, old + 0x208).target == old + 0x1000
    assert not isa.plan_replay(w(0xE28F0004), old, old + 8, "arm").ok     # add r0, pc, #4
    assert isa.plan_replay(w(0xE28F0004), old, old + 8, "arm", pic_offsets=[0]).ok
    far = isa.plan_replay(isa.arm_ldr_literal(old, 0, old + 0x40), old, old + 0x2000, "arm")
    assert not far.ok                                                      # literal behind and out of 12 bits
    assert not isa.plan_replay(w(0xE0800000 | (15 << 16)), old, old + 8, "arm").ok  # add r0, pc, r0


# ----------------------------------------------------- retail ARM9 (read-only)
ROMS = {
    "black": "Pokemon - Black Version (USA, Europe) (NDSi Enhanced).nds",
    "black2": "Pokemon - Black Version 2 (USA, Europe) (NDSi Enhanced).nds",
}
ARM9_RAM = 0x02004000
_ARM9 = {}


def arm9(key):
    ndspy_rom = pytest.importorskip("ndspy.rom", reason="NDSPY_UNAVAILABLE: ndspy not importable")
    from ndspy import codeCompression
    if key not in _ARM9:
        path = Path(os.environ.get("SLINK_NDS_ROMS", "E:/Google Drive/SLink")) / ROMS[key]
        if not path.is_file():
            pytest.skip(f"NDS_RETAIL_INPUT_ABSENT: {path.name}; set SLINK_NDS_ROMS")
        _ARM9[key] = bytes(codeCompression.decompress(ndspy_rom.NintendoDSRom.fromFile(str(path)).arm9))
    return _ARM9[key]


def fetch(key, addr, n):
    off = addr - ARM9_RAM
    return arm9(key)[off:off + n]


# (rom, symbol) -> (Thumb function address, first 8 bytes). The B538 prologue is the task-supplied
# anchor; the following words were read from the same ROMs.
FUNCS = {
    ("black2", "PokeParty_DecryptPkm"): (0x0201CC0C, "38b5051ca9880024"),
    ("black", "PokeParty_DecryptPkm"): (0x02017D30, "38b5051ca9880024"),
    ("black2", "PokeParty_AddPkm"): (0x0201FD6C, "38b5041c0a1c6168"),
    ("black", "PokeParty_AddPkm"): (0x0201A98C, "38b5041c0a1c6168"),
}


@pytest.mark.parametrize("key,sym", sorted(FUNCS))
def test_real_function_prologues_decode_and_replay(key, sym):
    addr, head = FUNCS[(key, sym)]
    code = fetch(key, addr, 8)
    assert code.hex() == head
    first = isa.decode_thumb(code, 0, addr)
    assert (first.kind, first.regs) == ("push", (3, 4, 5, 14))
    kinds = [isa.decode_thumb(code, o, addr + o).kind for o in (2, 4, 6)]
    assert kinds == ["pi", "pi", "pi"]                  # mov/add/ldr/mov-imm: none read PC
    plan = isa.plan_replay(code, addr, addr + 0x1000, "thumb")
    assert plan.ok and plan.replay_bytes() == code      # position independent: copied verbatim
    # Hand-rebuilt entry detour into the first 8 bytes, as a Gen 4/5 hook would write it.
    veneer = isa.thumb_detour(addr, 0x02380001, "veneer")
    assert veneer[:4] == bytes.fromhex("004b1847") and veneer[4:] == w(0x02380001)


# Regression pins measured by this module's own scan on 2026-10-02 (NOT independent evidence:
# they fix the current behaviour so a decoder change shows up). Independent confirmation is the
# hand decode below, which re-derives one hit with its own arithmetic.
PINNED_THUMB_CALLERS = {
    ("black2", "PokeParty_AddPkm"): (0x0201FD6C, [0x0200C2D6, 0x02030A38, 0x02030B36, 0x02030C52, 0x02030D64]),
    ("black", "PokeParty_AddPkm"): (0x0201A98C, [0x0200BB3E, 0x0202A62C, 0x0202A72A, 0x0202A846, 0x0202A958]),
    ("black2", "PokeParty_DecryptPkm"): (0x0201CC0C, [0x0200D572, 0x0200D736, 0x0200F436, 0x0201370A,
                                                     0x02013776, 0x0201C7BA, 0x0201C86A, 0x0201CA0A, 0x0201D5F8]),
    ("black", "PokeParty_DecryptPkm"): (0x02017D30, [0x0200CDEA, 0x0200CFAA, 0x0200EA8A, 0x0201107A,
                                                    0x020110EA, 0x020178DE, 0x0201798E, 0x02017B2E, 0x020185C8]),
}


@pytest.mark.parametrize("key,sym", sorted(PINNED_THUMB_CALLERS))
def test_real_arm9_find_bl_sites_pins_callers(key, sym):
    entry, expected = PINNED_THUMB_CALLERS[(key, sym)]
    sites = isa.find_bl_sites(arm9(key), ARM9_RAM, "thumb")
    hits = sorted(s.addr for s in sites if s.kind == "bl" and s.target_pointer == entry | 1)
    assert hits == expected
    assert len(hits) >= 5
    # No ARM-mode call (BL/BLX) anywhere in ARM9 targets these Thumb entries: pinned absence, same caveat.
    arm_hits = [s for s in isa.find_bl_sites(arm9(key), ARM9_RAM, "arm") if s.target == entry]
    assert arm_hits == []


def test_real_hit_hand_decoded_independently():
    # Independent arithmetic (ARM ARM BL pair), not calling the module's decoder.
    code = arm9("black2")
    site = 0x0200C2D6
    off = site - ARM9_RAM
    hw1, hw2 = struct.unpack_from("<HH", code, off)
    assert hw1 & 0xF800 == 0xF000 and hw2 & 0xF800 == 0xF800
    hi = hw1 & 0x7FF
    hi = hi - 0x800 if hi & 0x400 else hi
    assert site + 4 + (hi << 12) + ((hw2 & 0x7FF) << 1) == 0x0201FD6C
    assert isa.decode_thumb(code, off, site).target == 0x0201FD6C
    # And the module re-encodes the genuine ROM bytes bit-for-bit.
    assert isa.thumb_bl(site, 0x0201FD6C) == code[off:off + 4]


def test_real_arm9_every_pinned_hit_reencodes_to_rom_bytes():
    for key in ("black", "black2"):
        code = arm9(key)
        for site in isa.find_bl_sites(code, ARM9_RAM, "thumb"):
            off = site.addr - ARM9_RAM
            if site.kind == "bl":
                assert isa.thumb_bl(site.addr, site.target) == code[off:off + 4]
            else:
                assert isa.thumb_blx(site.addr, site.target) == code[off:off + 4]


# --------------------------------------------- targets inside the displaced span
def test_replay_span_internal_targets_move_with_the_span():
    old = 0x08100000
    span = isa.thumb_ldr_literal(old, 3, old + 4) + isa.thumb_bx(3) + struct.pack("<I", 0x08A00001)
    for new in (old - 0x20, old + 0x20):
        plan = isa.plan_replay(span, old, new, "thumb")
        assert plan.ok, plan.refusals
        d = isa.decode_thumb(plan.replay_bytes(), 0, new)
        assert (d.kind, d.target) == ("ldr_lit", new + 4)       # decoded target, not the old one
    # Thumb B to the next halfword inside the span (a 2-byte loop head + nop).
    loop = isa.thumb_b(old, old + 2) + isa.THUMB_NOP
    plan = isa.plan_replay(loop, old, old + 0x20, "thumb")
    assert plan.ok and isa.decode_thumb(plan.replay_bytes(), 0, old + 0x20).target == old + 0x22
    # ARM veneer: ldr pc,[pc,#-4] reads its own word, which moves with it.
    ven = isa.arm_detour(old, 0x08A00001, "veneer")
    plan = isa.plan_replay(ven, old, old + 0x20, "arm")
    assert plan.ok
    out = plan.replay_bytes()
    assert isa.decode_arm(out, 0, old + 0x20).target == old + 0x24 and out[4:] == ven[4:]
    # A relocated target that no longer fits the encoding is refused, never emitted:
    # Thumb LDR literal needs a word-aligned literal, but a +2 move misaligns the in-span word.
    plan = isa.plan_replay(span, old, old + 2, "thumb")
    assert not plan.ok and "not 4-byte aligned" in plan.refusals[0]
    with pytest.raises(isa.ReplayRefusedError):
        plan.replay_bytes()


def test_replay_refuses_stray_pic_offsets():
    old = 0x02010000
    nop = h(0x46C0, 0x46C0)
    for bad in (1, 4, 100):                       # mid-instruction, past the end, far past the end
        with pytest.raises(isa.ReplayRefusedError) as info:
            isa.plan_replay(nop, old, old + 8, "thumb", pic_offsets=[bad])
        assert "matches no decoded instruction" in str(info.value)
    assert isa.plan_replay(nop, old, old + 8, "thumb", pic_offsets=[2]).ok
    with pytest.raises(isa.ReplayRefusedError):
        isa.plan_replay(w(0xE1A00000), old, old + 8, "arm", pic_offsets=[2])
