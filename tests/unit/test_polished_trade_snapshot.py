"""Polished trade card 2a: the outgoing 70-byte SNAPSHOT and the INCOMING-MON validity predicate
(patch/polished/src/trade_snapshot.asm, trade_validate.asm; docs/polished/TRADE.md section 14).

Both are INERT in the overlay: nothing calls them yet. Evidence: the REAL assembled bytes (the committed
UPS applied to the pinned release ROM) run on a small SM83 interpreter over a fake WRAM, compared with a
Python twin of the rules, with mutants of the built bytes that must go red.

Absent input skips (no cached release ROM); present-but-wrong input fails.
"""
from __future__ import annotations

import os
import random
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
SRC = REPO / "patch/polished/src"

P, OT, NICK, BLOB = 48, 11, 11, 70
BLOB_AT = 0xC800            # arbitrary fake-WRAM home of an incoming blob
STACK_TOP = 0xDFF0          # the interpreter's stack lives in 0xDF00-0xDFFF; any other write is "a WRAM write"
TERM = 0x53                 # "@"
T = bytes([TERM])


# ------------------------------------------------------------------ a small SM83 interpreter

class Fault(Exception):
    pass


class Machine:
    """Enough of the SM83 for the trade routines. Unknown opcodes, ROM0 code and writes into ROM fail closed.

    Code is read from the banked window at `bank`; WRAM is a flat 64 KiB with the write set recorded.
    """

    def __init__(self, rom: bytes, bank: int = 0x7E):
        self.rom, self.bank = rom, bank
        self.mem = bytearray(0x10000)
        self.writes: set[int] = set()
        self.r = dict.fromkeys("abcdehl", 0)
        self.z = self.n = self.hc = self.cy = False
        self.sp = STACK_TOP
        self.steps = 0

    # -- memory
    def rd(self, addr: int) -> int:
        addr &= 0xFFFF
        if 0x4000 <= addr < 0x8000:
            return self.rom[pc._flat(self.bank, addr)]
        if addr < 0x4000:
            raise Fault(f"read of ROM0 {addr:#06x}")
        return self.mem[addr]

    def wr(self, addr: int, v: int) -> None:
        addr &= 0xFFFF
        if addr < 0x8000:
            raise Fault(f"write into ROM {addr:#06x}")
        self.mem[addr] = v & 0xFF
        self.writes.add(addr)

    def hl(self, v=None):
        if v is None:
            return self.r["h"] << 8 | self.r["l"]
        self.r["h"], self.r["l"] = (v >> 8) & 0xFF, v & 0xFF

    def pair(self, hi, lo, v=None):
        if v is None:
            return self.r[hi] << 8 | self.r[lo]
        self.r[hi], self.r[lo] = (v >> 8) & 0xFF, v & 0xFF

    def push(self, v):
        self.sp = (self.sp - 1) & 0xFFFF
        self.wr(self.sp, v >> 8)
        self.sp = (self.sp - 1) & 0xFFFF
        self.wr(self.sp, v & 0xFF)

    def pop(self):
        lo = self.rd(self.sp)
        hi = self.rd(self.sp + 1)
        self.sp = (self.sp + 2) & 0xFFFF
        return hi << 8 | lo

    # -- operand access by the standard 3-bit code: B C D E H L [HL] A
    def get(self, code):
        if code == 6:
            return self.rd(self.hl())
        return self.r["a" if code == 7 else "bcdehl"[code]]

    def put(self, code, v):
        v &= 0xFF
        if code == 6:
            self.wr(self.hl(), v)
        elif code == 7:
            self.r["a"] = v
        else:
            self.r["bcdehl"[code]] = v

    def cond(self, cc):
        return [not self.z, self.z, not self.cy, self.cy][cc]

    def alu(self, op, v):
        a = self.r["a"]
        if op == 0:       # add
            t = a + v
            self.z, self.n, self.hc, self.cy = (t & 0xFF) == 0, False, (a & 15) + (v & 15) > 15, t > 0xFF
            self.r["a"] = t & 0xFF
        elif op == 2:     # sub
            t = a - v
            self.z, self.n, self.hc, self.cy = (t & 0xFF) == 0, True, (a & 15) < (v & 15), t < 0
            self.r["a"] = t & 0xFF
        elif op == 4:     # and
            self.r["a"] = a & v
            self.z, self.n, self.hc, self.cy = self.r["a"] == 0, False, True, False
        elif op == 5:     # xor
            self.r["a"] = a ^ v
            self.z, self.n, self.hc, self.cy = self.r["a"] == 0, False, False, False
        elif op == 6:     # or
            self.r["a"] = a | v
            self.z, self.n, self.hc, self.cy = self.r["a"] == 0, False, False, False
        elif op == 7:     # cp
            self.z, self.n, self.hc, self.cy = a == v, True, (a & 15) < (v & 15), a < v
        else:
            raise Fault(f"unmodelled alu op {op}")

    def fetch(self):
        v = self.rd(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetch16(self):
        lo = self.fetch()
        return lo | self.fetch() << 8

    def call(self, entry: int, max_steps: int = 20000):
        """Run the routine at `entry` (in `bank`) until its outermost ret."""
        depth0 = self.sp
        self.pc = entry
        self.push(0xFFFF)                       # sentinel return address
        while True:
            self.steps += 1
            if self.steps > max_steps:
                raise Fault("did not terminate")
            if self.pc == 0xFFFF and self.sp == depth0:
                return self
            self.step()

    def step(self):
        at = self.pc
        op = self.fetch()
        if op == 0x00:
            return
        if op in (0x01, 0x11, 0x21, 0x31):                       # ld rr, nn
            v = self.fetch16()
            if op == 0x31:
                self.sp = v
            else:
                self.pair(*{0x01: ("b", "c"), 0x11: ("d", "e"), 0x21: ("h", "l")}[op], v)
        elif op & 0xC7 == 0x06:                                  # ld r, n  (incl. [hl])
            self.put((op >> 3) & 7, self.fetch())
        elif 0x40 <= op < 0x80:
            if op == 0x76:
                raise Fault("halt")
            self.put((op >> 3) & 7, self.get(op & 7))
        elif op == 0x2A:                                         # ld a, [hli]
            self.r["a"] = self.rd(self.hl())
            self.hl(self.hl() + 1)
        elif op == 0x22:                                         # ld [hli], a
            self.wr(self.hl(), self.r["a"])
            self.hl(self.hl() + 1)
        elif op == 0x1A:                                         # ld a, [de]
            self.r["a"] = self.rd(self.pair("d", "e"))
        elif op == 0x12:                                         # ld [de], a
            self.wr(self.pair("d", "e"), self.r["a"])
        elif op == 0xFA:                                         # ld a, [nn]
            self.r["a"] = self.rd(self.fetch16())
        elif op == 0xEA:                                         # ld [nn], a
            self.wr(self.fetch16(), self.r["a"])
        elif op in (0x03, 0x13, 0x23, 0x0B, 0x1B, 0x2B):         # inc/dec rr (no flags)
            hi, lo = {0: ("b", "c"), 1: ("d", "e"), 2: ("h", "l")}[op >> 4]
            self.pair(hi, lo, self.pair(hi, lo) + (1 if op & 8 == 0 else -1))
        elif op & 0xC7 in (0x04, 0x05):                          # inc/dec r
            code, dec = (op >> 3) & 7, op & 1
            v = self.get(code)
            t = (v - 1 if dec else v + 1) & 0xFF
            self.put(code, t)
            self.z, self.n, self.hc = t == 0, bool(dec), (v & 15) == (0 if dec else 15)
        elif op in (0x09, 0x19, 0x29):                           # add hl, rr
            hi, lo = {0x09: ("b", "c"), 0x19: ("d", "e"), 0x29: ("h", "l")}[op]
            t = self.hl() + self.pair(hi, lo)
            self.n, self.cy = False, t > 0xFFFF
            self.hl(t)
        elif 0x80 <= op < 0xC0:
            self.alu((op >> 3) & 7, self.get(op & 7))
        elif op & 0xC7 == 0xC6:
            self.alu((op >> 3) & 7, self.fetch())
        elif op == 0x18 or op in (0x20, 0x28, 0x30, 0x38):       # jr [cc]
            e = self.fetch()
            e = e - 256 if e > 127 else e
            if op == 0x18 or self.cond((op >> 3) & 3):
                self.pc = (self.pc + e) & 0xFFFF
        elif op == 0xC3:
            self.pc = self.fetch16()
        elif op == 0xCD:                                         # call nn (same bank only)
            tgt = self.fetch16()
            if not 0x4000 <= tgt < 0x8000:
                raise Fault(f"call outside the banked window {tgt:#06x} from {at:#06x}")
            self.push(self.pc)
            self.pc = tgt
        elif op == 0xC9 or (op in (0xC0, 0xC8, 0xD0, 0xD8) and self.cond((op >> 3) & 3)):   # ret [cc]
            self.pc = self.pop()
        elif op in (0xC0, 0xC8, 0xD0, 0xD8):
            return
        elif op in (0xC5, 0xD5, 0xE5):
            self.push({0xC5: self.pair("b", "c"), 0xD5: self.pair("d", "e"), 0xE5: self.hl()}[op])
        elif op in (0xC1, 0xD1, 0xE1):
            v = self.pop()
            if op == 0xE1:
                self.hl(v)
            else:
                self.pair(*{0xC1: ("b", "c"), 0xD1: ("d", "e")}[op], v)
        elif op == 0x37:                                         # scf
            self.n = self.hc = False
            self.cy = True
        elif op == 0xCB:
            cb = self.fetch()
            code, bit = cb & 7, (cb >> 3) & 7
            if cb >> 6 == 1:                                     # bit n, r
                self.z, self.n, self.hc = not (self.get(code) >> bit) & 1, False, True
            else:
                raise Fault(f"unmodelled CB opcode {cb:#04x}")
        else:
            raise Fault(f"unmodelled opcode {op:#04x} at {at:#06x}")


def run(rom, entry, *, a=0, bc=0x1234, de=0x5678, hl=0x9ABC, mem=None, bank=0x7E):
    """Call `entry` with registers set and `mem` ({addr: bytes}) loaded; returns the finished Machine."""
    m = Machine(rom, bank)
    for addr, blob in (mem or {}).items():
        m.mem[addr:addr + len(blob)] = blob
    m.r["a"] = a
    m.pair("b", "c", bc)
    m.pair("d", "e", de)
    m.hl(hl)
    m.call(entry)
    return m


def regs(m):
    return m.pair("b", "c"), m.pair("d", "e"), m.hl()


# ------------------------------------------------------------------ fixtures

@pytest.fixture(scope="module")
def syms():
    return _symbols(OVERLAY_SYM)


@pytest.fixture(scope="module")
def built():
    if not RELEASE.is_file():
        pytest.skip(f"pinned Polished release ROM not cached at {RELEASE}")
    return ups_apply(RELEASE.read_bytes(), UPS.read_bytes())


def addr(syms, name):
    bank, a = syms[name]
    assert bank == 0x7E, (name, bank)
    return a


# ------------------------------------------------------------------ the rules, restated in Python (the twin)

def twin_text_ok(field: bytes) -> bool:
    """First "@" within the field, every byte before it >= $5F; no terminator = refused."""
    for byte in field:
        if byte == TERM:
            return True
        if byte < 0x5F:
            return False
    return False


def twin_accepts(b: bytes) -> bool:
    assert len(b) == BLOB
    ext = (b[21] & 0x20) << 3
    s = b[0] + ext
    if not (1 <= s <= 0xFE or 0x101 <= s <= 0x123):
        return False
    if not 1 <= b[31] <= 100:
        return False
    if b[1] >= 0xF5:                       # mail is the tail of the item list (FIRST_MAIL = $F5)
        return False
    if (b[20] & 0x1F) >= 25:
        return False
    return twin_text_ok(b[48:56]) and twin_text_ok(b[59:70])


def good_blob(rng: random.Random | None = None) -> bytearray:
    rng = rng or random.Random(1)
    b = bytearray(rng.randrange(256) for _ in range(BLOB))
    b[0], b[1], b[20], b[21], b[31] = 25, 0x13, 0x03, 0x00, 50
    b[48:59] = bytes.fromhex("928b888d8a") + T + bytes(5)
    b[48 + 8:59] = bytes((0xFC, 0x00, 0x77))          # metadata bytes: never checked
    b[59:70] = bytes.fromhex("8d88828a") + T + bytes(6)
    return b


def set_species(b: bytearray, s: int):
    b[0] = s & 0xFF
    b[21] = (b[21] & ~0x20) | (0x20 if s >= 0x100 else 0)


def validate_incoming(rom, syms, blob: bytes, **kw):
    m = run(rom, addr(syms, "SlinkTradeValidateIncoming"), hl=BLOB_AT, mem={BLOB_AT: bytes(blob)}, **kw)
    return m.cy, m


# ------------------------------------------------------------------ (b) the predicate: hand table

def _case(**kw):
    """A good blob with one field changed: species=, level=, item=, nature=, nick=, ot=, ext=, egg=, tail=."""
    b = good_blob()
    if "species" in kw:
        set_species(b, kw["species"])
    if "level" in kw:
        b[31] = kw["level"]
    if "item" in kw:
        b[1] = kw["item"]
    if "nature" in kw:
        b[20] = (b[20] & 0xE0) | kw["nature"]
    if "egg" in kw:
        b[21] |= 0x40
    if "nick" in kw:
        b[59:70] = kw["nick"].ljust(NICK, b"\x00")
    if "ot" in kw:
        b[48:56] = kw["ot"].ljust(8, b"\x00")
    if "meta" in kw:
        b[56:59] = kw["meta"]
    return bytes(b)


TABLE = [
    # (label, blob, accepted)
    ("good", _case(), True),
    ("species 0", _case(species=0), False),
    ("species 1", _case(species=1), True),
    ("species $FE", _case(species=0xFE), True),
    ("species $FF", _case(species=0xFF), False),
    ("species $100", _case(species=0x100), False),
    ("species $101", _case(species=0x101), True),
    ("species $123", _case(species=0x123), True),
    ("species $124", _case(species=0x124), False),
    ("species $1FF (ext + $FF)", _case(species=0x1FF), False),
    ("species $1FE", _case(species=0x1FE), False),
    ("level 0", _case(level=0), False),
    ("level 1", _case(level=1), True),
    ("level 100", _case(level=100), True),
    ("level 101", _case(level=101), False),
    ("level 255", _case(level=255), False),
    ("item $00", _case(item=0x00), True),
    ("item $F4", _case(item=0xF4), True),
    ("item $F5", _case(item=0xF5), False),
    ("item $FF", _case(item=0xFF), False),
    ("nature 0", _case(nature=0), True),
    ("nature 24", _case(nature=24), True),
    ("nature 25", _case(nature=25), False),
    ("nature 31", _case(nature=31), False),
    ("nickname: no terminator", _case(nick=b"\x5f" * 11), False),
    ("nickname: terminator at 0", _case(nick=T), True),
    ("nickname: terminator at 10 (last)", _case(nick=b"\x5f" * 10 + T), True),
    ("nickname: terminator at 9", _case(nick=b"\x5f" * 9 + T), True),
    ("nickname: $5E before the terminator", _case(nick=bytes((0x80, 0x5E, 0x81)) + T), False),
    ("nickname: $5F before the terminator", _case(nick=bytes((0x80, 0x5F, 0x81)) + T), True),
    ("nickname: $00 before the terminator", _case(nick=b"\x00" + T), False),
    ("nickname: $52 before the terminator", _case(nick=b"\x52" + T), False),
    ("nickname: bytes after the terminator ignored", _case(nick=T + b"\x00\x01\x02\x03\x04\x05"), True),
    ("nickname: $FF glyphs accepted", _case(nick=b"\xff\xff" + T), True),
    ("OT: no terminator in 8", _case(ot=b"\x5f" * 8), False),
    ("OT: terminator at 0", _case(ot=T), True),
    ("OT: terminator at 7 (last)", _case(ot=b"\x5f" * 7 + T), True),
    ("OT: terminator only at byte 8 (metadata)", _case(ot=b"\x5f" * 8, meta=T + b"\x00\x00"), False),
    ("OT: $5E before the terminator", _case(ot=bytes((0x80, 0x5E)) + T), False),
    ("OT: $5F before the terminator", _case(ot=bytes((0x80, 0x5F)) + T), True),
    ("OT: bytes after the terminator ignored", _case(ot=T + b"\x00\x01\x02\x03\x04\x05\x06"), True),
    ("OT metadata arbitrary (all $00)", _case(meta=b"\x00\x00\x00"), True),
    ("OT metadata arbitrary (all $FF)", _case(meta=b"\xff\xff\xff"), True),
    ("egg, valid species", _case(egg=True), True),
    ("egg, ext species $123", _case(egg=True, species=0x123), True),
    ("egg, bad species $FF", _case(egg=True, species=0xFF), False),
    ("egg, bad level", _case(egg=True, level=0), False),
]


def observe_table(rom, syms) -> list[str]:
    bad = []
    for label, blob, want in TABLE:
        assert twin_accepts(blob) == want, f"the hand table disagrees with the twin on {label!r}"
        refused, m = validate_incoming(rom, syms, blob)
        if refused == want:
            bad.append(f"{label}: refused={refused}, want accepted={want}")
        if regs(m) != (0x1234, 0x5678, BLOB_AT):
            bad.append(f"{label}: BC/DE/HL not preserved: {[hex(x) for x in regs(m)]}")
        if m.writes - set(range(0xDF00, 0xE000)):
            bad.append(f"{label}: wrote outside the stack: {sorted(m.writes - set(range(0xDF00, 0xE000)))[:5]}")
        if bytes(m.mem[BLOB_AT:BLOB_AT + BLOB]) != blob:
            bad.append(f"{label}: the blob changed")
    return bad


def fuzz_blobs(n: int, seed: int):
    """Blobs biased toward the boundaries: a good blob with 1-3 fields set to a boundary value, plus noise."""
    rng = random.Random(seed)
    species = [0, 1, 2, 0x7F, 0xFD, 0xFE, 0xFF, 0x100, 0x101, 0x102, 0x122, 0x123, 0x124, 0x1FE, 0x1FF]
    levels = [0, 1, 2, 99, 100, 101, 255]
    items = [0, 1, 0xF3, 0xF4, 0xF5, 0xF6, 0xFE, 0xFF]
    natures = [0, 1, 23, 24, 25, 26, 31]
    glyphs = [0x00, 0x4F, 0x50, 0x52, 0x53, 0x54, 0x5E, 0x5F, 0x60, 0x7F, 0xFF]
    for i in range(n):
        b = good_blob(rng)
        if i % 5 == 0:                                   # one in five: pure noise
            b = bytearray(rng.randrange(256) for _ in range(BLOB))
            yield bytes(b)
            continue
        for _ in range(rng.randint(1, 3)):
            what = rng.randrange(8)
            if what == 0:
                set_species(b, rng.choice(species))
            elif what == 1:
                b[31] = rng.choice(levels)
            elif what == 2:
                b[1] = rng.choice(items)
            elif what == 3:
                b[20] = (b[20] & 0xE0) | rng.choice(natures)
            elif what == 4:
                b[21] ^= 0x40                            # egg flag: no effect
            else:                                        # a text field: random glyphs / terminator placement
                lo, ln = (59, NICK) if what in (5, 6) else (48, 8)
                field = bytearray(rng.choice(glyphs) if rng.random() < .4 else rng.randrange(0x5F, 0x100)
                                  for _ in range(ln))
                if rng.random() < .7:
                    field[rng.randrange(ln)] = TERM
                b[lo:lo + ln] = field
        if rng.random() < .3:
            b[56:59] = bytes(rng.randrange(256) for _ in range(3))
        if rng.random() < .1:                            # an unterminated OT name whose "@" sits in the metadata
            b[48:56] = bytes(rng.randrange(0x5F, 0x100) for _ in range(8))
            b[56 + rng.randrange(3)] = TERM
        yield bytes(b)


def observe_fuzz(rom, syms, n: int, seed: int = 20261006) -> tuple[list[str], int, int]:
    bad, acc = [], 0
    for blob in fuzz_blobs(n, seed):
        refused, m = validate_incoming(rom, syms, blob)
        want = twin_accepts(blob)
        acc += want
        if refused == want or regs(m) != (0x1234, 0x5678, BLOB_AT):
            bad.append(f"{blob.hex()}: refused={refused} want accepted={want}")
            if len(bad) > 5:
                break
    return bad, n, acc


def test_the_incoming_predicate_hand_table(built, syms):
    assert observe_table(built, syms) == []


def test_the_incoming_predicate_matches_the_twin_on_3000_seeded_blobs(built, syms):
    bad, n, accepted = observe_fuzz(built, syms, 3000)
    assert bad == [] and n == 3000
    # the fuzz is not vacuous: both outcomes are well populated
    assert 300 < accepted < 2700, accepted


# ------------------------------------------------------------------ the STAGED wrapper (native OT slot 0 layout)

STAGED_FIELDS = ("wOTPlayerName", "wOTPartyMon1", "wOTPartyMonOTs", "wOTPartyMonNicknames")
NAME_LEN = 11


def staged_addrs(syms):
    return {k: syms[k][1] for k in (*STAGED_FIELDS, "wOTPartyMon2", "wOTPartyMon2End")}


def staged_image(syms, blob: bytes, sender: bytes, rng: random.Random, neighbours: str) -> dict:
    """OT-slot-0 data at its native scattered addresses, with different garbage in every gap and in OT slot 1.

    neighbours: "valid" puts a good blob in slot 1 (record at wOTPartyMon2, OT at wOTPartyMonOTs+11, nickname at
    wOTPartyMonNicknames+11), "invalid" a refused one (zero record, no terminators), "noise" random bytes.
    """
    a = staged_addrs(syms)
    lo, hi = a["wOTPlayerName"], a["wOTPartyMonNicknames"] + 6 * NICK
    img = bytearray(rng.randrange(256) for _ in range(hi - lo))     # garbage in every gap

    def put(at, data):
        img[at - lo:at - lo + len(data)] = data
    if neighbours == "valid":
        g = good_blob(rng)
        put(a["wOTPartyMon2"], g[:P])
        put(a["wOTPartyMonOTs"] + OT, g[P:P + OT])
        put(a["wOTPartyMonNicknames"] + NICK, g[P + OT:])
    elif neighbours == "invalid":
        put(a["wOTPartyMon2"], bytes(P))
        put(a["wOTPartyMonOTs"] + OT, bytes(OT))
        put(a["wOTPartyMonNicknames"] + NICK, bytes(NICK))
    put(a["wOTPlayerName"], sender)
    put(a["wOTPartyMon1"], blob[:P])
    put(a["wOTPartyMonOTs"], blob[P:P + OT])
    put(a["wOTPartyMonNicknames"], blob[P + OT:])
    return {lo: bytes(img)}


def validate_staged(rom, syms, mem):
    m = run(rom, addr(syms, "SlinkTradeValidateIncomingStaged"), mem=mem)
    return m.cy, m


def rand_sender(rng: random.Random) -> bytes:
    """A sender name: mostly valid (glyphs then "@"), sometimes broken in one of the ways the rule names."""
    def glyph(n):
        return bytes(rng.randrange(0x5F, 0x100) for _ in range(n))
    kind = rng.randrange(10)
    if kind < 6:
        k = rng.randrange(NAME_LEN)
        return glyph(k) + T + bytes(rng.randrange(256) for _ in range(NAME_LEN - k - 1))
    if kind == 6:
        return glyph(NAME_LEN)                                           # no terminator
    if kind == 7:
        k = rng.randrange(NAME_LEN - 1)
        return glyph(k) + bytes([rng.choice((0x00, 0x4F, 0x52, 0x5E))]) + glyph(NAME_LEN - k - 1)
    if kind == 8:
        return glyph(NAME_LEN - 1) + T                                   # terminator at the last byte
    return bytes(rng.randrange(256) for _ in range(NAME_LEN))


def observe_staged(rom, syms, n: int, seed: int = 20261007) -> tuple[list[str], int, int]:
    bad, acc, rng = [], 0, random.Random(seed)
    lo = staged_addrs(syms)["wOTPlayerName"]
    own = set(range(0xDF00, 0xE000))
    for i, blob in enumerate(fuzz_blobs(n, seed)):
        sender = rand_sender(rng)
        want = twin_accepts(blob) and twin_text_ok(sender)
        acc += want
        nb = rng.choice(("invalid" if want else "valid", "noise"))
        mem = staged_image(syms, blob, sender, rng, nb)
        refused, m = validate_staged(rom, syms, mem)
        problems = []
        if refused == want:
            problems.append(f"refused={refused} want accepted={want}")
        if m.writes - own:
            problems.append("wrote WRAM")
        if bytes(m.mem[lo:lo + len(mem[lo])]) != mem[lo]:
            problems.append("the staged image changed")
        if problems:
            bad.append(f"#{i} {nb} blob={blob.hex()} sender={sender.hex()}: {problems}")
            if len(bad) > 5:
                break
    return bad, n, acc


def observe_staged_registers(rom, syms) -> list[str]:
    rng = random.Random(3)
    mem = staged_image(syms, bytes(good_blob()), bytes.fromhex("8d88828a") + T + bytes(6), rng, "noise")
    m = run(rom, addr(syms, "SlinkTradeValidateIncomingStaged"), mem=mem)
    bad = []
    if m.cy:
        bad.append("a good staged mon was refused")
    if regs(m) != (0x1234, 0x5678, 0x9ABC):
        bad.append(f"BC/DE/HL not preserved: {[hex(x) for x in regs(m)]}")
    return bad


SENDER_ROWS = [
    ("sender: terminator at 0", T + bytes(10), True),
    ("sender: terminator at 10 (last)", bytes([0x80] * 10) + T, True),
    ("sender: no terminator", bytes([0x80] * 11), False),
    ("sender: $5E before the terminator", bytes((0x80, 0x5E)) + T + bytes(8), False),
    ("sender: $5F before the terminator", bytes((0x80, 0x5F)) + T + bytes(8), True),
    ("sender: bytes after the terminator ignored", T + bytes(range(1, 11)), True),
]


def observe_staged_table(rom, syms) -> list[str]:
    bad, rng = [], random.Random(5)
    good_sender = bytes.fromhex("8d88828a") + T + bytes(6)
    for label, blob, want in TABLE:
        for nb in ("valid", "invalid", "noise"):
            refused, _m = validate_staged(rom, syms, staged_image(syms, blob, good_sender, rng, nb))
            if refused == want:
                bad.append(f"{label} [{nb} neighbours]: refused={refused}, want accepted={want}")
    for label, sender, want in SENDER_ROWS:
        for nb in ("valid", "invalid"):
            refused, _m = validate_staged(rom, syms, staged_image(syms, bytes(good_blob()), sender, rng, nb))
            if refused == want:
                bad.append(f"{label} [{nb} neighbours]: refused={refused}, want accepted={want}")
    return bad


def test_the_staged_wrapper_hand_table_and_registers(built, syms):
    assert observe_staged_table(built, syms) == []
    assert observe_staged_registers(built, syms) == []


def test_the_staged_wrapper_matches_the_twin_on_3000_scattered_images(built, syms):
    bad, n, accepted = observe_staged(built, syms, 3000)
    assert bad == [] and n == 3000
    assert 200 < accepted < 2500, accepted


def test_the_staged_addresses_are_the_native_ot_slot_zero_layout(syms):
    a = staged_addrs(syms)
    assert (a["wOTPlayerName"], a["wOTPartyMon1"], a["wOTPartyMonOTs"], a["wOTPartyMonNicknames"]) \
        == (0xD276, 0xD28B, 0xD3AB, 0xD3ED)
    assert a["wOTPartyMon2"] == a["wOTPartyMon1"] + P        # slot 1 (the snapshot) follows slot 0 immediately


# ------------------------------------------------------------------ (a) the snapshot on a fake WRAM

def wram(syms_sym):
    """Fake WRAM addresses straight from the committed sym."""
    s = syms_sym
    return {k: s[k][1] for k in ("wPartyCount", "wPartyMon1", "wPartyMonOTs", "wPartyMonNicknames", "wOTPartyMon1",
                                 "wOTPartyMon2", "wOTPartyMonOTs", "wOTPartyMonNicknames")}


def party_image(w, rng: random.Random, count: int):
    """A fake party: wPartyCount + six records, six OT fields, six nicknames of distinct random bytes."""
    mem = {w["wPartyCount"]: bytes([count]),
           w["wPartyMon1"]: bytes(rng.randrange(256) for _ in range(6 * P)),
           w["wPartyMonOTs"]: bytes(rng.randrange(256) for _ in range(6 * OT)),
           w["wPartyMonNicknames"]: bytes(rng.randrange(256) for _ in range(6 * NICK)),
           # OT slot 0 (incoming native trade data) and the rest of the OT area: sentinels
           w["wOTPartyMon1"]: b"\xa5" * P, w["wOTPartyMon2"]: b"\x5a" * P,
           w["wOTPartyMonOTs"]: b"\xa5" * OT, w["wOTPartyMonOTs"] + OT: b"\x5a" * OT,
           w["wOTPartyMonNicknames"]: b"\xa5" * NICK, w["wOTPartyMonNicknames"] + NICK: b"\x5a" * NICK}
    return mem


def live_slot(mem, w, slot) -> bytes:
    """The expected 70-byte preimage of `slot`, read straight from the fake WRAM image."""
    flat = bytearray(0x10000)
    for k, v in mem.items():
        flat[k:k + len(v)] = v
    return (bytes(flat[w["wPartyMon1"] + slot * P:][:P]) + bytes(flat[w["wPartyMonOTs"] + slot * OT:][:OT])
            + bytes(flat[w["wPartyMonNicknames"] + slot * NICK:][:NICK]))


def staged(m, w) -> bytes:
    return (bytes(m.mem[w["wOTPartyMon2"]:w["wOTPartyMon2"] + P])
            + bytes(m.mem[w["wOTPartyMonOTs"] + OT:w["wOTPartyMonOTs"] + 2 * OT])
            + bytes(m.mem[w["wOTPartyMonNicknames"] + NICK:w["wOTPartyMonNicknames"] + 2 * NICK]))


def snap(rom, syms, mem, slot, *, name="SlinkTradeSnapshot"):
    """Run a snapshot routine; the returned machine's memory carries on into the next call via `mem`."""
    m = run(rom, addr(syms, name), a=slot, mem=mem)
    return m


def carry_over(m):
    """The whole WRAM image after a run, loadable as `mem` for the next run."""
    return {0x8000: bytes(m.mem[0x8000:])}


def _flip(image, at, mask):
    buf = bytearray(image[0x8000])
    buf[at - 0x8000] ^= mask
    return {0x8000: bytes(buf)}


def observe_snapshot(rom, syms) -> list[str]:
    bad = []
    w = wram(syms)
    rng = random.Random(7)
    for count in (1, 2, 5, 6):
        for slot in range(count):
            mem = party_image(w, rng, count)
            want = live_slot(mem, w, slot)
            m = snap(rom, syms, mem, slot)
            if m.cy:
                bad.append(f"capture refused: count {count} slot {slot}")
                continue
            if staged(m, w) != want:
                bad.append(f"capture count {count} slot {slot}: staging != live preimage")
            if regs(m) != (0x1234, 0x5678, 0x9ABC):
                bad.append(f"capture: BC/DE/HL not preserved: {[hex(x) for x in regs(m)]}")
            expected_writes = (set(range(w["wOTPartyMon2"], w["wOTPartyMon2"] + P))
                               | set(range(w["wOTPartyMonOTs"] + OT, w["wOTPartyMonOTs"] + 2 * OT))
                               | set(range(w["wOTPartyMonNicknames"] + NICK, w["wOTPartyMonNicknames"] + 2 * NICK)))
            stray = m.writes - expected_writes - set(range(0xDF00, 0xE000))
            if stray:
                bad.append(f"capture wrote outside OT slot 1: {sorted(stray)[:4]}")
            # OT slot 0 and wOTPartyMon1 untouched
            if (bytes(m.mem[w["wOTPartyMon1"]:w["wOTPartyMon1"] + P]) != b"\xa5" * P
                    or bytes(m.mem[w["wOTPartyMonOTs"]:w["wOTPartyMonOTs"] + OT]) != b"\xa5" * OT
                    or bytes(m.mem[w["wOTPartyMonNicknames"]:w["wOTPartyMonNicknames"] + NICK]) != b"\xa5" * NICK):
                bad.append("capture touched OT slot 0")
            after = carry_over(m)
            v = snap(rom, syms, after, slot, name="SlinkTradeValidateSnapshot")
            if v.cy:
                bad.append(f"validate-unchanged refused: count {count} slot {slot}")
            if v.writes - set(range(0xDF00, 0xE000)):
                bad.append("validate wrote WRAM")
            if regs(v) != (0x1234, 0x5678, 0x9ABC):
                bad.append("validate: BC/DE/HL not preserved")
    # the exact-equality red control: flip each of the 70 live bytes in turn -> refuse
    mem = party_image(w, rng, 6)
    slot = 3
    m = snap(rom, syms, mem, slot)
    if m.cy:
        return bad + ["capture refused at slot 3"]
    base_after = carry_over(m)
    layout = ([(w["wPartyMon1"] + slot * P + i) for i in range(P)]
              + [(w["wPartyMonOTs"] + slot * OT + i) for i in range(OT)]
              + [(w["wPartyMonNicknames"] + slot * NICK + i) for i in range(NICK)])
    for i, at in enumerate(layout):
        v = snap(rom, syms, _flip(base_after, at, 0x01), slot, name="SlinkTradeValidateSnapshot")
        if not v.cy:
            bad.append(f"validate accepted a flipped live byte {i} ({at:#06x})")
    # ... and flip each STAGED byte too (the snapshot side of the same comparison)
    stage = ([(w["wOTPartyMon2"] + i) for i in range(P)] + [(w["wOTPartyMonOTs"] + OT + i) for i in range(OT)]
             + [(w["wOTPartyMonNicknames"] + NICK + i) for i in range(NICK)])
    for i, at in enumerate(stage):
        v = snap(rom, syms, _flip(base_after, at, 0x80), slot, name="SlinkTradeValidateSnapshot")
        if not v.cy:
            bad.append(f"validate accepted a flipped staged byte {i} ({at:#06x})")
    # bounds: count 0, count 7, slot >= count -> refuse, with no WRAM writes outside the stack
    for count, slot in ((0, 0), (7, 0), (7, 6), (0xFF, 0), (3, 3), (3, 5), (1, 1), (6, 6), (6, 0xFF)):
        for name in ("SlinkTradeSnapshot", "SlinkTradeValidateSnapshot"):
            mem = party_image(w, rng, count)
            m = snap(rom, syms, mem, slot, name=name)
            if not m.cy:
                bad.append(f"{name}: count {count} slot {slot} was accepted")
            if m.writes - set(range(0xDF00, 0xE000)):
                bad.append(f"{name}: count {count} slot {slot} wrote WRAM on refusal")
            if regs(m) != (0x1234, 0x5678, 0x9ABC):
                bad.append(f"{name}: BC/DE/HL not preserved on refusal")
    # release is a plain ret: no carry change needed, no writes, registers kept
    m = run(rom, addr(syms, "SlinkTradeReleaseSnapshot"), a=2, mem=party_image(w, rng, 4))
    if m.writes - set(range(0xDF00, 0xE000)) or regs(m) != (0x1234, 0x5678, 0x9ABC):
        bad.append("release has side effects")
    return bad


def test_the_snapshot_captures_validates_and_refuses_each_of_the_70_bytes(built, syms):
    assert observe_snapshot(built, syms) == []


def test_every_snapshot_byte_counted(syms):
    """70 = 48 + 11 + 11; the OT field keeps its three metadata bytes."""
    s = _symbols(OVERLAY_SYM)
    assert P + OT + NICK == BLOB == 70
    assert s["wOTPartyMon2End"][1] - s["wOTPartyMon2"][1] == P
    assert s["wOTPartyMon3OT"][1] - s["wOTPartyMon2OT"][1] == OT == s["wOTPartyMon2Extra"][1] - s["wOTPartyMon2OT"][1] + 3
    assert s["wOTPartyMon2Nickname"][1] - s["wOTPartyMonNicknames"][1] == NICK
    # the Polished layout facts the predicate hard-codes
    assert (s["wOTPartyMon1Item"][1] - s["wOTPartyMon1"][1], s["wOTPartyMon1Personality"][1] - s["wOTPartyMon1"][1],
            s["wOTPartyMon1ExtSpecies"][1] - s["wOTPartyMon1"][1], s["wOTPartyMon1Level"][1] - s["wOTPartyMon1"][1]) \
        == (1, 20, 21, 31)


# ------------------------------------------------------------------ (c) mutants of the BUILT bytes must go red

def _locate(rom: bytes, syms, start: str, end: str, pattern: bytes, which: int = 0) -> int:
    lo, hi = pc._flat(*syms[start]), pc._flat(*syms[end])
    hits, i = [], rom.find(pattern, lo, hi)
    while i != -1:
        hits.append(i)
        i = rom.find(pattern, i + 1, hi)
    assert len(hits) > which, (start, pattern.hex(), hits)
    return hits[which]


def _patched(rom: bytes, at: int, old: bytes, new: bytes) -> bytes:
    assert rom[at:at + len(old)] == old, (hex(at), rom[at:at + len(old)].hex(), old.hex())
    out = bytearray(rom)
    out[at:at + len(new)] = new
    return bytes(out)


REC = ("SlinkTradeValidateRecord", "SlinkTradeValidateText")
TEXT = ("SlinkTradeValidateText", "SlinkTradeValidateIncomingStaged")
STG = ("SlinkTradeValidateIncomingStaged", "SlinkTradeValidateIncoming")
INC = ("SlinkTradeValidateIncoming", "SlinkTradeValidateEnd")
S = ("SlinkTradeSnapshot", "SlinkTradeSnapshotEnd")


def mutants(rom: bytes, syms) -> dict[str, tuple[bytes, str]]:
    """name -> (mutated ROM, which observer must notice: 'predicate', 'staged' or 'snapshot')."""
    ot, nick = syms["wOTPartyMonOTs"][1] + OT, syms["wOTPartyMonNicknames"][1] + NICK
    out = {}

    def ld_de(at):
        return bytes([0x11, at & 0xFF, at >> 8])

    def ld_hl(at):
        return bytes([0x21, at & 0xFF, at >> 8])

    def mut(name, kind, rng_, pattern, new, which=0, off=0):
        at = _locate(rom, syms, *rng_, pattern, which) + off
        out[name] = (_patched(rom, at, pattern[off:], new), kind)

    mut("species upper bound, extended ($23 -> $24)", "predicate", REC, bytes([0x16, 0x23]), bytes([0x16, 0x24]))
    mut("species upper bound, plain ($FE -> $FF)", "predicate", REC, bytes([0x16, 0xFE]), bytes([0x16, 0xFF]))
    mut("level upper bound off by one (100 -> 101)", "predicate", REC, bytes([0xFE, 100]), bytes([0xFE, 101]))
    mut("level upper bound off by one (100 -> 99)", "predicate", REC, bytes([0xFE, 100]), bytes([0xFE, 99]))
    mut("nature bound off by one (25 -> 26)", "predicate", REC, bytes([0xFE, 25]), bytes([0xFE, 26]))
    mut("nature bound off by one (25 -> 24)", "predicate", REC, bytes([0xFE, 25]), bytes([0xFE, 24]))
    mut("terminator constant $50 instead of $53", "predicate", TEXT, bytes([0xFE, TERM]), bytes([0xFE, 0x50]))
    mut("glyph threshold $60 instead of $5F", "predicate", TEXT, bytes([0xFE, 0x5F]), bytes([0xFE, 0x60]))
    mut("glyph threshold $5E instead of $5F", "predicate", TEXT, bytes([0xFE, 0x5F]), bytes([0xFE, 0x5E]))
    mut("OT text length 9 instead of 8 (reads the metadata)", "predicate", INC, bytes([0x06, 8]), bytes([0x06, 9]))
    # the staged wrapper: wrong source addresses / lengths / a wrapper that treats OT slot 0 as the contiguous blob
    a = staged_addrs(syms)
    mut("staged: OT text length 9 instead of 8", "staged", STG, bytes([0x06, 8]), bytes([0x06, 9]))
    mut("staged: record read from wOTPartyMon2 (slot 1)", "staged", STG, ld_hl(a["wOTPartyMon1"]),
        ld_hl(a["wOTPartyMon2"]))
    mut("staged: nickname read from slot 1", "staged", STG, ld_hl(a["wOTPartyMonNicknames"]),
        ld_hl(a["wOTPartyMonNicknames"] + NICK))
    mut("staged: the sender name is never checked (nickname checked twice)", "staged", STG,
        ld_hl(a["wOTPlayerName"]), ld_hl(a["wOTPartyMonNicknames"]))
    mut("staged: sender name length 8 instead of 11", "staged", STG, bytes([0x06, NAME_LEN]), bytes([0x06, 8]), which=1)
    rec = syms["SlinkTradeValidateRecord"][1]
    inc = syms["SlinkTradeValidateIncoming"][1]
    mut("staged: wrapper passes wOTPartyMon1 as the contiguous blob", "staged", STG,
        ld_hl(a["wOTPartyMon1"]) + bytes([0xCD, rec & 0xFF, rec >> 8]), ld_hl(a["wOTPartyMon1"]) + bytes([0xCD, inc & 0xFF, inc >> 8]))
    # the snapshot: Validate compares one byte short (OT extra / nickname last / record last)
    mut("compare skips the last OT byte (extra)", "snapshot", S, ld_de(ot) + bytes([0x0E, OT]),
        ld_de(ot) + bytes([0x0E, OT - 1]), which=1)
    mut("compare skips the last nickname byte", "snapshot", S, ld_de(nick) + bytes([0x0E, NICK]),
        ld_de(nick) + bytes([0x0E, NICK - 1]), which=1)
    mut("compare skips the last record byte", "snapshot", S,
        ld_de(syms["wOTPartyMon2"][1]) + bytes([0x0E, P]), ld_de(syms["wOTPartyMon2"][1]) + bytes([0x0E, P - 1]), which=1)
    # the capture: copies the OT name only (8), leaving the 3 extra bytes stale
    mut("copy skips the 3 OT extra bytes", "snapshot", S, ld_de(ot) + bytes([0x0E, OT]),
        ld_de(ot) + bytes([0x0E, 8]), which=0)
    mut("copy skips the last nickname byte", "snapshot", S, ld_de(nick) + bytes([0x0E, NICK]),
        ld_de(nick) + bytes([0x0E, NICK - 1]), which=0)
    return out


def test_every_mutant_of_the_built_routines_is_observed(built, syms):
    assert observe_table(built, syms) == [] and observe_snapshot(built, syms) == []
    assert observe_staged_table(built, syms) == [] and observe_staged(built, syms, 800)[0] == []
    survivors = []
    for name, (rom, kind) in mutants(built, syms).items():
        if kind == "predicate":
            bad = observe_table(rom, syms) or observe_fuzz(rom, syms, 800)[0]
        elif kind == "staged":
            bad = observe_staged_table(rom, syms) or observe_staged(rom, syms, 800)[0]
        else:
            bad = observe_snapshot(rom, syms)
        if not bad:
            survivors.append(name)
    assert survivors == []


def test_the_predicate_mutants_are_each_caught_by_the_hand_table_or_the_fuzz(built, syms):
    """Reports WHICH instrument catches each predicate mutant (both must, independently, for the boundary ones)."""
    for name, (rom, kind) in mutants(built, syms).items():
        if kind == "predicate":
            assert observe_table(rom, syms) or observe_fuzz(rom, syms, 800)[0], name
            assert observe_fuzz(rom, syms, 3000)[0], f"the 3000-blob fuzz alone missed: {name}"


# ------------------------------------------------------------------ source shape

def test_the_new_files_are_fixed_sections_in_bank_7e_included_last():
    snap_src = (SRC / "trade_snapshot.asm").read_text(encoding="utf-8")
    val_src = (SRC / "trade_validate.asm").read_text(encoding="utf-8")
    assert 'ROMX[$4500], BANK[SLINK_SERVICE_BANK]' in snap_src and 'ROMX[$4600], BANK[SLINK_SERVICE_BANK]' in val_src
    assert snap_src.count("ASSERT SLINK_SERVICE_BANK == $7E") == 1 == val_src.count("ASSERT SLINK_SERVICE_BANK == $7E")
    assert "_GOLD" not in snap_src + val_src and "_SILVER" not in snap_src + val_src
    slink = (SRC / "slink.asm").read_text(encoding="utf-8")
    assert slink.index("trade_gate.asm") < slink.index("trade_snapshot.asm") < slink.index("trade_validate.asm")
    assert slink.rstrip().endswith('INCLUDE "engine/slink/trade_validate.asm"')


def test_the_new_sections_do_not_overlap_the_gates(syms):
    gates_end = addr(syms, "SlinkTradeGatesEnd")
    assert addr(syms, "SlinkTradeSnapshot") >= gates_end
    assert addr(syms, "SlinkTradeSnapshotEnd") <= 0x4600 <= addr(syms, "SlinkTradeValidateIncoming")
    assert addr(syms, "SlinkTradeValidateEnd") <= 0x4700
