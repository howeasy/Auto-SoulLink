"""A real SM83 (Game Boy LR35902) interpreter for the Polished trade asm unit tests.

A plain module (not collected by pytest). It replaces the ad-hoc mini machines of the trade gate / snapshot
tests, which have no SP, no flags beyond Z/carry and recurse in Python for CALL, so they cannot test push/pop
depth, `ld hl, sp+n`, balanced returns, BIT/RES/SET, `rst`, or half-carry.

What it models
--------------
* every non-CB opcode with exact Z/N/H/C flags (DAA, ADC/SBC half-carry, ADD HL,rr, ADD SP,e8 and LD HL,SP+e8
  with the SM83 LOW-BYTE flag semantics, rotates, CPL/SCF/CCF, POP AF masking the low nibble of F, ...) and the
  full CB prefix. The 11 illegal opcodes (D3 DB DD E3 E4 EB EC ED F4 FC FD) raise `Fault`. HALT and STOP raise
  `Fault` unless `allow_halt` is set (then they are no-ops); DI/EI/RETI maintain an `ime` bit only.
* a 64 KiB address space: ROM bank 0 ($0000-$3FFF); a switchable ROM window ($4000-$7FFF) selected by the
  `bank` attribute (tests may change it, `mbc="mbc3"|"mbc5"` additionally lets code write the bank register);
  everything from $8000 up is one plain bytearray (WRAM/HRAM/SRAM/IO; $E000-$FDFF echoes $C000-$DDFF). No VRAM,
  WRAM or SRAM banking, no I/O side effects, no interrupts, no timing.
* writes into ROM are ignored and logged in `rom_writes` (and, with `mbc`, switch the bank); every write that
  reaches RAM is logged in `writes` as `(pc, addr, value)`, the pc being the address of the writing instruction
  (pushes, calls and trap/FarCall stack writes included). Optional `read_hooks` / `write_hooks` per address.
* a real 16-bit SP with a little-endian stack and `min_sp` tracking.
* `call_routine()` runs a routine to its RET back into a sentinel and fails loudly on a step limit, execution
  from non-ROM memory, a RET to any other address, a RET that pops past the entry frame. It reports
  `sp_delta` (final SP minus entry SP; a balanced routine is 0), the instruction count and the stack depth.
* TRAPS: `trap(addr, handler)` stubs a native routine; the handler gets the machine, may set registers and
  then the machine performs a RET (pass `ret=False` to manage pc yourself).
* Polished `rst FarCall` (`rst $10` followed by `dwb target|farjp<<15, bank`) modelled after home/farcall.asm:
  the same stack layout the callee sees, bank switch and restore, farjp as a tail jump through DoNothing.
  `farcall="native"` (with `mbc` and a real ROM) runs the genuine home-bank routine instead, which is how the
  tests cross-check the model.

The interpreter is deliberately small and slow-ish (a Python `if` chain); it is for unit tests.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

SENTINEL = 0xFEFE            # return address pushed under a routine; never a valid code address
DEFAULT_SP = 0xD000          # first push lands at $CFFF
STEP_LIMIT = 100_000

# Polished home bank facts (home/header.asm, home/farcall.asm; the clean sym is pinned by the tests)
FARCALL_VECTOR = 0x0010      # rst FarCall
FARCALL_RETURN = 0x0014      # the `jmp _ReturnFarCall` after `call _RstFarCall` in the FarCall vector
DO_NOTHING = 0x000F          # a bare `ret`; farjp "returns" through it
FARCALL_EXTRA_DEPTH = 13     # the real FarCall dips 13 bytes below the stack pointer seen at the vector

ILLEGAL = frozenset((0xD3, 0xDB, 0xDD, 0xE3, 0xE4, 0xEB, 0xEC, 0xED, 0xF4, 0xFC, 0xFD))


class Fault(Exception):
    """The program did something the hardware (or the test contract) does not allow."""


class StepLimit(Fault):
    """The routine did not return within the step limit."""


@dataclass(frozen=True)
class FarCallRecord:
    kind: str                # "farcall" | "farjp"
    bank: int
    addr: int
    at: int                  # address of the data bytes' owner (the rst instruction)
    from_bank: int           # the bank that executed the rst
    sp: int                  # SP the callee starts with


@dataclass
class Result:
    a: int
    f: int
    b: int
    c: int
    d: int
    e: int
    h: int
    l: int  # noqa: E741
    sp: int
    pc: int
    steps: int
    sp_delta: int            # final SP - entry SP; 0 = balanced
    min_sp: int              # lowest SP reached
    stack_used: int          # entry SP - min_sp (bytes, counting the 2-byte return address slot)
    writes: list[tuple[int, int, int]]
    farcalls: list[FarCallRecord]
    returned: bool
    unmodelled_farcall_scratch: bool = False   # True when a MODEL-mode farcall ran: the real FarCall's scratch stack writes below SP are NOT reproduced (use farcall="native" for memory claims)

    @property
    def bc(self): return self.b << 8 | self.c
    @property
    def de(self): return self.d << 8 | self.e
    @property
    def hl(self): return self.h << 8 | self.l
    @property
    def af(self): return self.a << 8 | self.f
    @property
    def zf(self): return bool(self.f & 0x80)
    @property
    def nf(self): return bool(self.f & 0x40)
    @property
    def hf(self): return bool(self.f & 0x20)
    @property
    def cf(self): return bool(self.f & 0x10)
    @property
    def flags(self): return "".join(k for k, on in zip("znhc", (self.zf, self.nf, self.hf, self.cf), strict=True) if on)


@dataclass
class _Frame:
    sentinel: int
    sentinel_sp: int
    returned: bool = False


class Memory:
    """ROM (bank 0 + switchable window) and one flat RAM array from $8000."""

    def __init__(self, rom=b"", bank: int = 1, mbc: str | None = None):
        self.rom = rom                       # bytes / bytearray; never copied until poke_rom
        self.bank = bank
        self.mbc = mbc
        self.ram = bytearray(0x10000)
        self.read_hooks: dict[int, Callable] = {}
        self.write_hooks: dict[int, Callable] = {}
        self.writes: list[tuple[int, int, int]] = []
        self.rom_writes: list[tuple[int, int, int]] = []
        self.ipc = 0                         # pc of the executing instruction (for the logs)

    def window_bank(self) -> int:
        return 1 if (self.mbc == "mbc3" and self.bank == 0) else self.bank

    def rom_offset(self, addr: int, bank: int | None = None) -> int:
        if addr < 0x4000:
            return addr
        b = self.window_bank() if bank is None else bank
        return b * 0x4000 + (addr - 0x4000)

    def poke_rom(self, addr: int, data: bytes, bank: int | None = None) -> None:
        """Test helper: overwrite ROM bytes (bank-aware for the window)."""
        if not isinstance(self.rom, bytearray):
            self.rom = bytearray(self.rom)
        off = self.rom_offset(addr, bank)
        if off + len(data) > len(self.rom):
            self.rom.extend(bytes(off + len(data) - len(self.rom)))
        self.rom[off:off + len(data)] = data

    def peek(self, addr: int, n: int = 1) -> bytes:
        """Unhooked, unlogged read of n bytes."""
        return bytes(self.read_raw((addr + i) & 0xFFFF) for i in range(n))

    def poke(self, addr: int, data) -> None:
        """Unhooked, unlogged write of RAM bytes (an int is one byte). Refuses ROM addresses."""
        if isinstance(data, int):
            data = bytes([data])
        for i, v in enumerate(data):
            a = (addr + i) & 0xFFFF
            if a < 0x8000:
                raise Fault(f"poke into ROM at {a:#06x} (use poke_rom)")
            self.ram[self.echo(a)] = v & 0xFF

    def image(self) -> bytes:
        """The RAM half of the address space ($8000-$FFFF) as a 32 KiB image, echo RAM mirrored from WRAM."""
        ram = bytearray(self.ram[0x8000:])
        ram[0xE000 - 0x8000:0xFE00 - 0x8000] = ram[0xC000 - 0x8000:0xDE00 - 0x8000]
        return bytes(ram)

    @staticmethod
    def echo(addr: int) -> int:
        return addr - 0x2000 if 0xE000 <= addr < 0xFE00 else addr

    def read_raw(self, addr: int) -> int:
        if addr < 0x8000:
            off = self.rom_offset(addr)
            return self.rom[off] if off < len(self.rom) else 0xFF
        return self.ram[self.echo(addr)]

    def read(self, addr: int) -> int:
        addr &= 0xFFFF
        hook = self.read_hooks.get(addr)
        if hook is not None:
            v = hook(self, addr)
            if v is not None:
                return v & 0xFF
        return self.read_raw(addr)

    def write(self, addr: int, value: int) -> None:
        addr &= 0xFFFF
        value &= 0xFF
        if addr < 0x8000:
            self.rom_writes.append((self.ipc, addr, value))
            if self.mbc and 0x2000 <= addr < 0x4000:
                if self.mbc == "mbc3":
                    self.bank = value & 0x7F
                elif addr < 0x3000:
                    self.bank = (self.bank & 0x100) | value
                else:
                    self.bank = (self.bank & 0xFF) | (value & 1) << 8
            return
        self.writes.append((self.ipc, addr, value))
        hook = self.write_hooks.get(addr)
        if hook is not None and hook(self, addr, value) is False:
            return
        self.ram[self.echo(addr)] = value


class SM83:
    """The CPU. Registers are ints; flags are bools; `r` is B C D E H L (unused) A."""

    def __init__(self, rom=b"", bank: int = 1, *, mbc: str | None = None, farcall: str | None = "model",
                 allow_ram_exec: bool = False, allow_halt: bool = False, hrombank: int | None = None):
        self.mem = Memory(rom, bank, mbc)
        self.r = [0] * 8
        self._f = 0                           # raw F byte; POP AF is what keeps its low nibble 0
        self.sp = DEFAULT_SP
        self.pc = 0
        self.ime = False
        self.allow_ram_exec = allow_ram_exec
        self.allow_halt = allow_halt
        self.hrombank = hrombank              # address of hROMBank; the FarCall model keeps it in step
        self.steps = 0
        self.min_sp = self.sp
        self._entry_sp, self._max_depth = self.sp, 0
        self.farcalls: list[FarCallRecord] = []
        self.farcall_expect: dict[tuple[int, int], str] = {}
        self.farcall_allowed: set[tuple[int, int]] | None = None
        self._traps: dict[int, list] = {}
        self._frame: _Frame | None = None
        if farcall not in (None, "model", "native"):
            raise ValueError(farcall)
        self.farcall_mode = farcall
        if farcall == "model":
            self.trap(FARCALL_VECTOR, SM83._model_farcall, ret=False, builtin=True)
            self.trap(FARCALL_RETURN, SM83._model_farcall_return, builtin=True)
            self.trap(DO_NOTHING, lambda m: None, builtin=True)

    # -- register views
    a = property(lambda s: s.r[7], lambda s, v: s.r.__setitem__(7, v & 0xFF))
    b = property(lambda s: s.r[0], lambda s, v: s.r.__setitem__(0, v & 0xFF))
    c = property(lambda s: s.r[1], lambda s, v: s.r.__setitem__(1, v & 0xFF))
    d = property(lambda s: s.r[2], lambda s, v: s.r.__setitem__(2, v & 0xFF))
    e = property(lambda s: s.r[3], lambda s, v: s.r.__setitem__(3, v & 0xFF))
    h = property(lambda s: s.r[4], lambda s, v: s.r.__setitem__(4, v & 0xFF))
    l = property(lambda s: s.r[5], lambda s, v: s.r.__setitem__(5, v & 0xFF))  # noqa: E741

    @property
    def f(self) -> int:
        return self._f

    @f.setter
    def f(self, v: int) -> None:
        self._f = v & 0xF0                    # hardware: the low nibble of F is wired to 0

    def _flag(bit: int):  # noqa: N805 - property factory
        return property(lambda s: bool(s._f & bit),
                        lambda s, v: setattr(s, "_f", (s._f | bit) if v else (s._f & ~bit & 0xFF)))

    zf = _flag(0x80)
    nf = _flag(0x40)
    hf = _flag(0x20)
    cf = _flag(0x10)
    del _flag

    bc = property(lambda s: s.r[0] << 8 | s.r[1], lambda s, v: s._set_pair(0, 1, v))
    de = property(lambda s: s.r[2] << 8 | s.r[3], lambda s, v: s._set_pair(2, 3, v))
    hl = property(lambda s: s.r[4] << 8 | s.r[5], lambda s, v: s._set_pair(4, 5, v))
    af = property(lambda s: s.r[7] << 8 | s.f, lambda s, v: (s.r.__setitem__(7, (v >> 8) & 0xFF), setattr(s, "f", v & 0xF0)))

    def _set_pair(self, hi: int, lo: int, v: int) -> None:
        self.r[hi], self.r[lo] = (v >> 8) & 0xFF, v & 0xFF

    @property
    def bank(self) -> int:
        return self.mem.bank

    @bank.setter
    def bank(self, v: int) -> None:
        self.mem.bank = v

    @property
    def writes(self):
        return self.mem.writes

    @property
    def rom_writes(self):
        return self.mem.rom_writes

    # -- memory shortcuts
    def rd(self, addr: int) -> int:
        return self.mem.read(addr)

    def wr(self, addr: int, v: int) -> None:
        self.mem.write(addr, v)

    def peek(self, addr: int, n: int = 1) -> bytes:
        return self.mem.peek(addr, n)

    def poke(self, addr: int, data) -> None:
        self.mem.poke(addr, data)

    def stack_bytes(self, n: int, offset: int = 0) -> bytes:
        """The n bytes at SP+offset (what `ld hl, sp+offset` would let code read)."""
        return self.mem.peek((self.sp + offset) & 0xFFFF, n)

    def stack_word(self, offset: int = 0) -> int:
        lo, hi = self.stack_bytes(2, offset)
        return hi << 8 | lo

    def fault(self, msg: str) -> Fault:
        return Fault(f"{msg} [pc={self.mem.ipc:#06x} bank={self.bank:#04x} sp={self.sp:#06x}]")

    # -- stack
    def push16(self, v: int) -> None:
        self.sp = (self.sp - 1) & 0xFFFF
        self.wr(self.sp, v >> 8)
        self.sp = (self.sp - 1) & 0xFFFF
        self.wr(self.sp, v & 0xFF)

    def pop16(self) -> int:
        lo = self.rd(self.sp)
        hi = self.rd(self.sp + 1)
        self.sp = (self.sp + 2) & 0xFFFF
        return hi << 8 | lo

    # -- operand access (B C D E H L [HL] A)
    def get8(self, i: int) -> int:
        return self.rd(self.hl) if i == 6 else self.r[i]

    def set8(self, i: int, v: int) -> None:
        if i == 6:
            self.wr(self.hl, v)
        else:
            self.r[i] = v & 0xFF

    def get16(self, p: int) -> int:
        return (self.bc, self.de, self.hl, self.sp)[p]

    def set16(self, p: int, v: int) -> None:
        v &= 0xFFFF
        if p == 0:
            self.bc = v
        elif p == 1:
            self.de = v
        elif p == 2:
            self.hl = v
        else:
            self.sp = v

    def cond(self, cc: int) -> bool:
        return (not self.zf, self.zf, not self.cf, self.cf)[cc]

    # -- instruction fetch
    def fetch(self) -> int:
        pc = self.pc
        if pc >= 0x8000 and not self.allow_ram_exec:
            raise self.fault(f"instruction fetch from non-ROM memory at {pc:#06x}")
        v = self.mem.read_raw(pc) if pc < 0x8000 else self.rd(pc)
        if pc < 0x8000 and self.mem.rom_offset(pc) >= len(self.mem.rom):
            raise self.fault(f"instruction fetch beyond the ROM image at {pc:#06x} bank {self.bank:#04x}")
        self.pc = (pc + 1) & 0xFFFF
        return v

    def fetch16(self) -> int:
        lo = self.fetch()
        return lo | self.fetch() << 8

    # -- ALU
    def _alu(self, op: int, v: int) -> None:
        a = self.r[7]
        if op < 2:                                   # ADD / ADC
            cin = int(self.cf) if op == 1 else 0
            t = a + v + cin
            self.hf = (a & 15) + (v & 15) + cin > 15
            self.cf = t > 0xFF
            self.nf = False
            self.zf = (t & 0xFF) == 0
            self.r[7] = t & 0xFF
        elif op in (2, 3, 7):                        # SUB / SBC / CP
            cin = int(self.cf) if op == 3 else 0
            t = a - v - cin
            self.hf = (a & 15) - (v & 15) - cin < 0
            self.cf = t < 0
            self.nf = True
            self.zf = (t & 0xFF) == 0
            if op != 7:
                self.r[7] = t & 0xFF
        else:
            res = (a & v, a ^ v, a | v)[op - 4]
            self.zf, self.nf, self.hf, self.cf = res == 0, False, op == 4, False
            self.r[7] = res

    def _daa(self) -> None:
        a = self.r[7]
        if not self.nf:
            if self.cf or a > 0x99:
                a += 0x60
                self.cf = True
            if self.hf or (a & 0x0F) > 9:
                a += 0x06
        else:
            if self.cf:
                a -= 0x60
            if self.hf:
                a -= 0x06
        a &= 0xFF
        self.zf, self.hf = a == 0, False
        self.r[7] = a

    def _sp_plus_e8(self) -> int:
        """SP + signed e8 with the SM83 flags taken from the LOW byte (used by ADD SP,e8 and LD HL,SP+e8)."""
        e = self.fetch()
        sp = self.sp
        self.zf = self.nf = False
        self.hf = (sp & 0x0F) + (e & 0x0F) > 0x0F
        self.cf = (sp & 0xFF) + e > 0xFF
        return (sp + (e - 256 if e > 127 else e)) & 0xFFFF

    def _cb(self) -> None:
        cb = self.fetch()
        x, y, z = cb >> 6, (cb >> 3) & 7, cb & 7
        v = self.get8(z)
        if x == 0:
            cin = int(self.cf)
            if y == 0:
                c, res = v >> 7, (v << 1 | v >> 7) & 0xFF
            elif y == 1:
                c, res = v & 1, v >> 1 | (v & 1) << 7
            elif y == 2:
                c, res = v >> 7, (v << 1 | cin) & 0xFF
            elif y == 3:
                c, res = v & 1, v >> 1 | cin << 7
            elif y == 4:
                c, res = v >> 7, (v << 1) & 0xFF
            elif y == 5:
                c, res = v & 1, v >> 1 | v & 0x80
            elif y == 6:
                c, res = 0, (v << 4 | v >> 4) & 0xFF
            else:
                c, res = v & 1, v >> 1
            self.zf, self.nf, self.hf, self.cf = res == 0, False, False, bool(c)
            self.set8(z, res)
        elif x == 1:                                  # BIT y, r (no write-back)
            self.zf, self.nf, self.hf = not v >> y & 1, False, True
        elif x == 2:
            self.set8(z, v & ~(1 << y))
        else:
            self.set8(z, v | 1 << y)

    # -- control flow
    def _do_ret(self) -> None:
        at = self.sp
        ret = self.pop16()
        fr = self._frame
        if fr is not None:
            above = (at - fr.sentinel_sp) & 0xFFFF            # wrapped distance above the sentinel slot
            if 0 < above < 0x8000:
                raise self.fault("RET popped past the entry frame (more pops than pushes)")
            if ret == fr.sentinel:
                fr.returned = True
            elif above == 0:
                raise self.fault(f"the routine returned to {ret:#06x}, not the sentinel {fr.sentinel:#06x}")
        self.pc = ret

    def _dip(self, sp: int) -> None:
        """Track the deepest stack as a WRAPPED distance below the entry SP, so a stack that wraps through $0000 still
        reports its real depth (a plain min() read a wrapped SP as the shallowest)."""
        depth = (self._entry_sp - sp) & 0xFFFF
        if depth < 0x8000 and depth > self._max_depth:
            self._max_depth = depth
            self.min_sp = sp & 0xFFFF

    def _call(self, target: int) -> None:
        self.push16(self.pc)
        self.pc = target

    def step(self) -> None:
        """Execute one instruction (or one trap)."""
        pc = self.pc
        self.mem.ipc = pc
        traps = self._traps.get(pc)
        if traps:
            for bank, fn, ret in traps:
                if bank is None or pc < 0x4000 or bank == self.bank:
                    fn(self)
                    if ret:
                        self._do_ret()
                    self.steps += 1
                    self._dip(self.sp)
                    return
        self.steps += 1
        op = self.fetch()
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        if x == 1:
            if op == 0x76:
                if not self.allow_halt:
                    raise self.fault("HALT")
            else:
                self.set8(y, self.get8(z))
        elif x == 2:
            self._alu(y, self.get8(z))
        elif x == 0:
            self._x0(op, y, z)
        else:
            self._x3(op, y, z)
        self._dip(self.sp)

    def _x0(self, op: int, y: int, z: int) -> None:
        r = self.r
        p, q = y >> 1, y & 1
        if z == 0:
            if y == 0:
                pass
            elif y == 1:                              # LD (nn), SP
                n = self.fetch16()
                self.wr(n, self.sp & 0xFF)
                self.wr(n + 1, self.sp >> 8)
            elif y == 2:                              # STOP
                self.fetch()
                if not self.allow_halt:
                    raise self.fault("STOP")
            else:                                     # JR e / JR cc, e
                e = self.fetch()
                if y == 3 or self.cond(y - 4):
                    self.pc = (self.pc + (e - 256 if e > 127 else e)) & 0xFFFF
        elif z == 1:
            if q == 0:
                self.set16(p, self.fetch16())
            else:                                     # ADD HL, rr
                hl, v = self.hl, self.get16(p)
                self.hf = (hl & 0xFFF) + (v & 0xFFF) > 0xFFF
                self.cf = hl + v > 0xFFFF
                self.nf = False
                self.hl = hl + v
        elif z == 2:
            if p == 0:
                addr = self.bc
            elif p == 1:
                addr = self.de
            else:
                addr = self.hl
                self.hl = addr + (1 if p == 2 else -1)
            if q == 0:
                self.wr(addr, r[7])
            else:
                r[7] = self.rd(addr)
        elif z == 3:
            self.set16(p, self.get16(p) + (1 if q == 0 else -1))
        elif z == 4:                                  # INC r
            v = self.get8(y)
            res = (v + 1) & 0xFF
            self.zf, self.nf, self.hf = res == 0, False, (v & 15) == 15
            self.set8(y, res)
        elif z == 5:                                  # DEC r
            v = self.get8(y)
            res = (v - 1) & 0xFF
            self.zf, self.nf, self.hf = res == 0, True, (v & 15) == 0
            self.set8(y, res)
        elif z == 6:
            self.set8(y, self.fetch())
        else:
            a = r[7]
            if y == 0:                                # RLCA
                c, a = a >> 7, (a << 1 | a >> 7) & 0xFF
                self.zf, self.nf, self.hf, self.cf = False, False, False, bool(c)
                r[7] = a
            elif y == 1:                              # RRCA
                c, a = a & 1, a >> 1 | (a & 1) << 7
                self.zf, self.nf, self.hf, self.cf = False, False, False, bool(c)
                r[7] = a
            elif y == 2:                              # RLA
                c, a = a >> 7, (a << 1 | int(self.cf)) & 0xFF
                self.zf, self.nf, self.hf, self.cf = False, False, False, bool(c)
                r[7] = a
            elif y == 3:                              # RRA
                c, a = a & 1, a >> 1 | int(self.cf) << 7
                self.zf, self.nf, self.hf, self.cf = False, False, False, bool(c)
                r[7] = a
            elif y == 4:
                self._daa()
            elif y == 5:                              # CPL
                r[7] = a ^ 0xFF
                self.nf = self.hf = True
            elif y == 6:                              # SCF
                self.nf = self.hf = False
                self.cf = True
            else:                                     # CCF
                self.nf = self.hf = False
                self.cf = not self.cf

    def _x3(self, op: int, y: int, z: int) -> None:
        if op in ILLEGAL:
            raise self.fault(f"illegal opcode {op:#04x}")
        p, q = y >> 1, y & 1
        if z == 0:
            if y < 4:
                if self.cond(y):
                    self._do_ret()
            elif y == 4:                              # LDH (n), A
                self.wr(0xFF00 + self.fetch(), self.r[7])
            elif y == 5:                              # ADD SP, e8
                self.sp = self._sp_plus_e8()
            elif y == 6:                              # LDH A, (n)
                self.r[7] = self.rd(0xFF00 + self.fetch())
            else:                                     # LD HL, SP+e8
                self.hl = self._sp_plus_e8()
        elif z == 1:
            if q == 0:
                v = self.pop16()
                if p == 3:
                    self.r[7] = v >> 8
                    self._f = v & 0xF0                # POP AF: the low nibble of F reads back 0
                else:
                    self.set16(p, v)
            elif p == 0:
                self._do_ret()
            elif p == 1:                              # RETI
                self.ime = True
                self._do_ret()
            elif p == 2:                              # JP HL
                self.pc = self.hl
            else:                                     # LD SP, HL
                self.sp = self.hl
        elif z == 2:
            if y < 4:
                n = self.fetch16()
                if self.cond(y):
                    self.pc = n
            elif y == 4:
                self.wr(0xFF00 + self.r[1], self.r[7])
            elif y == 5:
                self.wr(self.fetch16(), self.r[7])
            elif y == 6:
                self.r[7] = self.rd(0xFF00 + self.r[1])
            else:
                self.r[7] = self.rd(self.fetch16())
        elif z == 3:
            if y == 0:
                self.pc = self.fetch16()
            elif y == 1:
                self._cb()
            elif y == 6:
                self.ime = False
            else:                                     # y == 7 (the others are illegal, handled above)
                self.ime = True
        elif z == 4:
            n = self.fetch16()
            if self.cond(y):
                self._call(n)
        elif z == 5:
            if q == 0:
                self.push16(self.af if p == 3 else self.get16(p))
            else:
                self._call(self.fetch16())
        elif z == 6:
            self._alu(y, self.fetch())
        else:                                         # RST
            self._call(y * 8)

    # -- traps and the FarCall model
    def trap(self, addr: int, handler: Callable[[SM83], None], *, bank: int | None = None, ret: bool = True,
             builtin: bool = False) -> None:
        """Run `handler(machine)` instead of the code at `addr` (in `bank` for the switchable window), then RET."""
        entry = (bank, handler, ret)
        lst = self._traps.setdefault(addr, [])
        if builtin:
            lst.append(entry)
        else:
            lst.insert(0, entry)          # user traps win over the built-in model

    def set_bank(self, bank: int) -> None:
        self.bank = bank
        if self.hrombank is not None:
            self.mem.writes.append((self.mem.ipc, self.hrombank, bank & 0xFF))
            self.mem.ram[self.hrombank] = bank & 0xFF

    def _model_farcall(self) -> None:
        """`rst FarCall`: dwb target|farjp, bank follows the rst. Mirrors home/farcall.asm's stack layout.

        The callee starts with [SP]=FARCALL_RETURN, [SP+2]=the caller's bank, [SP+3]=the return location
        (the byte after the data for farcall, DoNothing for farjp: its own `ret` then tail-returns).
        """
        self._dip(self.sp - FARCALL_EXTRA_DEPTH)
        ptr = self.pop16()
        lo, hi, bank = (self.rd(ptr + i) for i in range(3))
        word = lo | hi << 8
        farjp = bool(word & 0x8000)
        target = word & 0x7FFF
        kind = "farjp" if farjp else "farcall"
        want = self.farcall_expect.get((bank, target))
        if want is not None and want != kind:
            raise self.fault(f"expected {want} to {bank:#04x}:{target:#06x}, got {kind}")
        if self.farcall_allowed is not None and (bank, target) not in self.farcall_allowed:
            raise self.fault(f"{kind} to unexpected target {bank:#04x}:{target:#06x}")
        if len(self.mem.rom) and bank * 0x4000 >= len(self.mem.rom):
            raise self.fault(f"{kind} to bank {bank:#04x} beyond the ROM image")
        # home/farcall.asm reads the caller's bank from hROMBank (`ldh a, [hROMBank]`), not from the mapper: a stale shadow
        # is restored as the shadow (that is the real behaviour); without a configured hROMBank the mapper bank is used
        from_bank = self.mem.read_raw(self.hrombank) if self.hrombank is not None else self.bank
        self.push16(DO_NOTHING if farjp else (ptr + 3) & 0xFFFF)
        self.sp = (self.sp - 1) & 0xFFFF
        self.wr(self.sp, from_bank)
        self.push16(FARCALL_RETURN)
        self.farcalls.append(FarCallRecord(kind, bank, target, (ptr - 1) & 0xFFFF, from_bank, self.sp))
        self.set_bank(bank)
        self.pc = target

    def _model_farcall_return(self) -> None:
        """`jmp _ReturnFarCall`: restore the caller's bank, drop the bank byte; the machine then RETs."""
        self.set_bank(self.rd(self.sp))
        self.sp = (self.sp + 1) & 0xFFFF

    # -- running
    def call_routine(self, addr: int, regs: dict | None = None, sp: int | None = None, *, flags: str | None = None,
                     bank: int | None = None, mem: dict | None = None, max_steps: int = STEP_LIMIT,
                     sentinel: int = SENTINEL) -> Result:
        """Run the routine at `addr` until its RET returns to `sentinel`.

        regs: any of a b c d e h l f af bc de hl; flags: letters from "znhc" to set (others cleared);
        mem: {addr: bytes|int} poked first; bank: the ROM window bank to run in (default: the current one).
        The sentinel push is not written to the log. Fails loudly (Fault) on the step limit, a fetch from
        non-ROM memory (unless allow_ram_exec), a RET to any other address, a RET past the entry frame, or
        reaching the sentinel by anything other than that RET. `sp_delta` in the result must be 0.
        """
        if bank is not None:
            self.bank = bank
        for a, data in (mem or {}).items():
            self.poke(a, data)
        for k, v in (regs or {}).items():
            if k in ("a", "b", "c", "d", "e", "h", "l", "bc", "de", "hl", "af"):
                setattr(self, k, v)
            elif k == "f":
                self.f = v
            else:
                raise ValueError(f"unknown register {k!r}")
        if flags is not None:
            self._f = sum(bit for ch, bit in zip("znhc", (0x80, 0x40, 0x20, 0x10), strict=True) if ch in flags)
        entry_sp = (DEFAULT_SP if sp is None else sp) & 0xFFFF
        self.sp = entry_sp
        sentinel_sp = (entry_sp - 2) & 0xFFFF
        self.mem.poke(sentinel_sp, bytes([sentinel & 0xFF, sentinel >> 8]))   # unlogged, through the SAME echo mapping as reads
        self.sp = sentinel_sp
        self.pc = addr
        self.min_sp = self.sp
        self._entry_sp, self._max_depth = entry_sp, 2     # the 2-byte return slot counts
        saved, frame = self._frame, _Frame(sentinel, sentinel_sp)
        self._frame = frame
        w0, f0, s0 = len(self.mem.writes), len(self.farcalls), self.steps
        try:
            while not frame.returned:
                if self.pc == sentinel:
                    raise self.fault("reached the sentinel without a RET")
                if self.steps - s0 >= max_steps:
                    raise StepLimit(f"no return within {max_steps} steps [pc={self.pc:#06x} bank={self.bank:#04x}]")
                self.step()
        finally:
            self._frame = saved
        return Result(a=self.a, f=self.f, b=self.b, c=self.c, d=self.d, e=self.e, h=self.h, l=self.l,
                      sp=self.sp, pc=self.pc, steps=self.steps - s0, sp_delta=(self.sp - entry_sp),
                      min_sp=self.min_sp, stack_used=self._max_depth,
                      writes=list(self.mem.writes[w0:]), farcalls=list(self.farcalls[f0:]), returned=True,
                      unmodelled_farcall_scratch=bool(self.farcalls[f0:]) and self.farcall_mode == "model")


def rom_image(banks: dict[int, bytes] | None = None, *, nbanks: int = 4, bank0: bytes = b"") -> bytearray:
    """A synthetic ROM: `banks` maps bank number -> bytes placed at that bank's start ($4000 for bank >= 1)."""
    rom = bytearray(0x4000 * nbanks)
    rom[0:len(bank0)] = bank0
    for n, data in (banks or {}).items():
        rom[n * 0x4000:n * 0x4000 + len(data)] = data
    return rom
