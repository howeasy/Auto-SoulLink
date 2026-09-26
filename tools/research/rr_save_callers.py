"""C5-RR-SAVECALLERS: static census of every flash-writing path in the Radical Red ROMs.

Bytes only, no emulator.  For each admitted RR artifact (clean 964f951a, companion ea5352f8) and
FireRed 41cb23d8 as the vanilla control, this script:

  1. decodes every halfword-aligned Thumb BL pair (target = site + 4 + offset) and every
     `ldr rN, [pc, #imm]` literal, so a pointer counts as a code reference only when some PC-relative
     load actually reads it; words no LDR reads are reported as TABLE-WORD (data tables);
  2. seeds the flash-write primitives: the agb_flash function-pointer variables ProgramFlashSector /
     ProgramFlashByte / EraseFlashSector / EraseFlashChip (IWRAM, FR .sym); --cmdreg / --flashbase
     separately list every direct user of the command register 0x0E005555 and every site that
     builds FLASH_BASE 0x0E000000 arithmetically (a driver that bypasses the pointer variables);
  3. walks callers upward (BL sites, LDR-literal thumb pointers, raw table words) to --depth and
     prints the tree, naming functions from the FR .sym and flagging bodies that differ from FR.

The over-approximation is deliberate: a BL pair decoded inside data only adds a candidate caller,
which the report then classifies by hand.  It cannot see a call whose target is computed at run
time from anything other than a literal-pool word (arithmetic on a register, a RAM table); the
report marks those OPEN.

Usage: python tools/research/rr_save_callers.py [--rom clean|companion|fr] [--depth N] [--seed HEX]
       python tools/research/rr_save_callers.py --rom R --entries     # the classification input
       python tools/research/rr_save_callers.py --rom R --cmdreg | --flashbase | --disasm ADDR:LEN
       python tools/research/rr_save_callers.py --selftest
"""
from __future__ import annotations

import argparse
import bisect
import hashlib
import pathlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = 0x08000000
ROMS = {  # same pins as tools/gen_gen3_write_checkpoint.py ROMS
    "fr": (pathlib.Path("E:/Google Drive/SLink/Pokemon - FireRed Version (USA).gba"),
           "41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc"),
    "clean": (pathlib.Path("E:/Google Drive/SLink/Pokemon - Radical Red.gba"),
              "964f951a0fdaf209e4ea1344883ef0d557bb3a80"),
    "companion": (ROOT / "patch" / "build" / "slink_RR.gba",
                  "97f28ec1a36c8526760da6fa7606cf78e1ceb016"),
}
SYM = ROOT / "data" / "gen3" / "pret" / "pokefirered.sym"
FR_RODATA = 0x081E9F10  # pokefirered.map: .rodata start
# Seeds, not conclusions: IWRAM function-pointer variables set by IdentifyFlash (FR .sym) and the
# command register every chip driver writes.
PTR_VARS = {0x0300741C: "ProgramFlashSector (fn ptr var)", 0x03007424: "ProgramFlashByte (fn ptr var)",
            0x03007430: "EraseFlashSector (fn ptr var)", 0x0300742C: "EraseFlashChip (fn ptr var)"}
# Every chip command sequence writes this address.  Walked only with --cmdreg (depth 1): above
# the driver it is dominated by the READ path (SwitchFlashBank), which is not a write.
CMD_REG = 0x0E005555


def load(kind: str) -> bytes:
    path, sha = ROMS[kind]
    rom = path.read_bytes()
    if hashlib.sha1(rom).hexdigest() != sha:
        raise SystemExit(f"{path}: sha1 differs from the pin")
    return rom


LABELS: dict[int, str] = {}  # size-0 FR labels (gSpecials, gScriptCmdTable, ...) for naming only


def parse_sym():
    names, sizes = {}, {}
    for line in SYM.read_text().splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[3].startswith("."):
            continue
        addr, size = int(parts[0], 16), int(parts[2], 16)
        if not BASE <= addr < 0x0A000000:
            continue
        if size and addr not in names:
            names[addr], sizes[addr] = parts[3], size
        elif not size:
            LABELS.setdefault(addr, parts[3])
    return names, sorted(names), sizes


def bl_decode(hi: np.ndarray, lo: np.ndarray, site: np.ndarray) -> np.ndarray:
    off = ((hi.astype(np.int64) & 0x7FF) << 12) | ((lo.astype(np.int64) & 0x7FF) << 1)
    off = np.where(off & 0x400000, off - 0x800000, off)
    return site + 4 + off


class Rom:
    def __init__(self, rom: bytes, fr: bytes | None, syms):
        self.rom, self.fr = rom, fr
        self.names, self.starts, self.sizes = syms
        hw = np.frombuffer(rom, dtype="<u2")
        addr = BASE + 2 * np.arange(len(hw), dtype=np.int64)
        m = ((hw[:-1] & 0xF800) == 0xF000) & ((hw[1:] & 0xF800) == 0xF800)
        self.bl_site = addr[:-1][m]
        self.bl_tgt = bl_decode(hw[:-1][m], hw[1:][m], self.bl_site)
        m = (hw & 0xF800) == 0x4800
        site = addr[m]
        lit = ((site + 4) & ~3) + (hw[m].astype(np.int64) & 0xFF) * 4
        ok = lit < BASE + len(rom)
        self.ldr_site, self.ldr_lit = site[ok], lit[ok]
        m = (hw & 0xF800) == 0xA000  # adr rN, pc, #imm8*4: a code address built without a literal
        self.adr_site = addr[m]
        self.adr_tgt = ((self.adr_site + 4) & ~3) + (hw[m].astype(np.int64) & 0xFF) * 4
        self.words = np.frombuffer(rom[: len(rom) // 4 * 4], dtype="<u4")
        self.ldr_val = self.words[(self.ldr_lit - BASE) // 4]
        # candidate function starts: FR symbols + BL targets + LDR-loaded thumb pointers into ROM
        tp = self.ldr_val[(self.ldr_val & 1) == 1].astype(np.int64) - 1
        tp = tp[(tp >= BASE) & (tp < BASE + len(rom))]
        self.fstarts = sorted(set(self.starts) | set(self.bl_tgt.tolist()) | set(tp.tolist()))

    def func_of(self, a: int) -> int:
        # inside a sized FR code symbol (FR code ends at .rodata 0x081E9F10): that symbol, so a BL
        # decoded from junk into a function body cannot split it; otherwise the nearest start.
        i = bisect.bisect_right(self.starts, a) - 1
        if i >= 0 and self.starts[i] < FR_RODATA and a < self.starts[i] + self.sizes[self.starts[i]]:
            return self.starts[i]
        i = bisect.bisect_right(self.fstarts, a) - 1
        return self.fstarts[i] if i >= 0 else a

    def name(self, f: int) -> str:
        if f in self.names:
            n = self.names[f]
            if self.fr is not None:
                o, size = f - BASE, self.sizes[f]
                n += "" if self.rom[o:o + size] == self.fr[o:o + size] else " [RR body differs from FR]"
            return n
        i = bisect.bisect_right(self.starts, f) - 1
        if i >= 0 and f < self.starts[i] + self.sizes[self.starts[i]]:
            return f"{self.names[self.starts[i]]}+{f - self.starts[i]:#x}"
        lab = max((a for a in LABELS if a <= f), default=None)
        if lab is not None and f - lab < 0x1000 and (i < 0 or lab > self.starts[i]):
            return f"label {LABELS[lab]}+{f - lab:#x}"
        return "(no FR symbol)"

    def refs(self, target: int, is_code: bool = True):
        """(kind, site, containing function or None) for every reference to `target`."""
        out = []
        if is_code:
            out += [("BL", s, self.func_of(s)) for s in self.bl_site[self.bl_tgt == target].tolist()]
            out += [("ADR", s, self.func_of(s)) for s in self.adr_site[self.adr_tgt == target].tolist()]
        for v in ([target | 1, target] if is_code else [target]):
            hit = self.ldr_val == v
            out += [("LDR", s, self.func_of(s)) for s in self.ldr_site[hit].tolist()]
            lits = set(self.ldr_lit[hit].tolist())
            out += [("WORD", BASE + 4 * i, None) for i in np.nonzero(self.words == v)[0].tolist()
                    if BASE + 4 * i not in lits]
            if is_code and v & 1:
                # unaligned copies: script bytecode (callnative/gotonative, CFRU battle-script
                # callasm) stores pointers at any byte offset
                pat, at = v.to_bytes(4, "little"), self.rom.find(v.to_bytes(4, "little"))
                while at != -1:
                    if at % 4:
                        out.append(("UNALIGNED", BASE + at, None))
                    at = self.rom.find(pat, at + 1)
        return out

    def interior_refs(self, f: int):
        """LDR literals / aligned words pointing strictly INSIDE the function at f (FR size, or up to
        the next candidate start): jump-backs from hooks, or a mid-body entry."""
        end = f + self.sizes[f] if f in self.sizes else self.fstarts[bisect.bisect_right(self.fstarts, f)]
        # only odd (Thumb) pointers from OUTSIDE the body: a hook's jump-back or a mid-body entry.
        # Switch tables are even and live inside the body; they are not entries.
        v = self.words.astype(np.int64)
        hit = np.nonzero((v & 1 == 1) & (v > f + 1) & (v < end))[0]
        lits = set(self.ldr_lit.tolist())
        out = [f"{BASE + 4 * i:#x}{'(LDR)' if BASE + 4 * i in lits else ''}" for i in hit.tolist()
               if not f <= BASE + 4 * i < end]
        bl = (self.bl_tgt > f) & (self.bl_tgt < end) & ((self.bl_site < f) | (self.bl_site >= end))
        return out + [f"{s:#x}(BL)" for s in self.bl_site[bl].tolist()]


def entries(r: Rom):
    """The BL-closure of the flash writers and every non-BL reference INTO it.

    BL edges are synchronous calls.  Anything else that points into the closure (an LDR'd Thumb
    pointer, a table word, an unaligned script pointer) is where a caller registers a task, a
    callback or a dispatch-table routine, or calls through a CFRU `bl bx_rN` veneer: those are the
    world boundaries the report classifies."""
    closure, queue = {}, []
    for v in PTR_VARS:
        for _, _, f in r.refs(v, False):
            if f is not None and f not in closure:
                closure[f] = v
                queue.append(f)
    edges = []
    while queue:
        t = queue.pop()
        for kind, site, f in r.refs(t, True):
            if kind == "BL":
                if f not in closure:
                    closure[f] = t
                    queue.append(f)
            else:
                edges.append((t, kind, site, f))
    return closure, sorted(edges)


def flash_base_builders(r: Rom) -> list[int]:
    """`movs rd, #imm; lsls rd, rd, #sh` building 0x0E000000 (FLASH_BASE) with no literal."""
    hw = np.frombuffer(r.rom, dtype="<u2").astype(np.int64)
    a, b = hw[:-1], hw[1:]
    rd = (a >> 8) & 7
    ok = (((a & 0xF800) == 0x2000) & ((b & 0xF800) == 0) & (rd == (b & 7)) & (rd == ((b >> 3) & 7))
          & (((a & 0xFF) << ((b >> 6) & 0x1F)) == 0x0E000000))
    return (np.nonzero(ok)[0] * 2 + BASE).tolist()


def walk(r: Rom, seeds: dict[int, tuple[str, bool]], depth: int) -> None:
    seen = set()

    def rec(target, label, is_code, d, indent):
        pad = "  " * indent
        print(f"{pad}{target:#010x} {label}")
        if target in seen:
            print(f"{pad}  (expanded above)")
            return
        if d == 0:
            return
        seen.add(target)
        if is_code:
            inner = r.interior_refs(target)
            if inner:
                print(f"{pad}  interior refs at " + ",".join(inner))
        by_fn = {}
        for kind, site, fn in r.refs(target, is_code):
            by_fn.setdefault((fn is None, site if fn is None else fn), []).append((kind, site))
        for (is_word, f), sites in sorted(by_fn.items(), key=lambda x: x[0][1]):
            tag = ",".join(f"{k}@{s:#x}" for k, s in sites)
            if is_word:
                print(f"{pad}  {f:#010x} {sites[0][0]} in {r.name(f)}")
            else:
                rec(f, f"{r.name(f)}  <- {tag}", True, d - 1, indent + 1)

    for t, (label, code) in seeds.items():
        rec(t, label, code, depth, 0)


def selftest() -> None:
    # bl from 0x080D9B50 area: FR HandleReplaceSectorAndVerify (0x080D9B04) calls HandleReplaceSector
    fr = load("fr")
    r = Rom(fr, None, parse_sym())
    callers = {f for k, s, f in r.refs(0x080D9B50) if k == "BL"}
    assert 0x080D9B04 in callers, "BL decode lost a known FR call edge"
    # known-negative: nothing BLs into the middle of TrySavingData
    assert not r.refs(0x080DA366), "BL decode invented an edge"
    assert r.func_of(0x080DA370) == 0x080DA364
    # known positives: the FR driver builds FLASH_BASE in ProgramFlashSector_MX; the link save task
    # is registered (LDR) by task50_after_link_battle_save
    assert 0x081DF0CE in flash_base_builders(r), "flash-base scan lost the FR driver"
    closure, edges = entries(r)
    assert 0x080DA634 in closure and (0x080DA634, "LDR", 0x0806FCC8, 0x0806FBB8) in edges
    print("selftest ok")


def disasm(r: Rom, start: int, length: int) -> None:
    """Thumb listing with literal-pool values resolved (capstone; research aid only)."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
    o = start - BASE
    for ins in md.disasm(r.rom[o:o + length], start):
        note = ""
        if ins.mnemonic == "ldr" and "[pc" in ins.op_str:
            lit = ((ins.address + 4) & ~3) + int(ins.op_str.split("#")[-1].rstrip("]"), 0)
            val = int(r.words[(lit - BASE) // 4])
            note = f"  ; ={val:#010x} {r.name(val & ~1) if BASE <= val < 0x0A000000 else ''}"
        elif ins.mnemonic == "bl":
            tgt = int(ins.op_str.lstrip("#"), 0)
            note = f"  ; {r.name(tgt)}"
        print(f"{ins.address:#010x}: {ins.mnemonic:6} {ins.op_str}{note}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default="clean", choices=ROMS)
    ap.add_argument("--depth", type=int, default=4)
    ap.add_argument("--seed", action="append", default=[], help="extra code address (hex) to walk")
    ap.add_argument("--no-default-seeds", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--cmdreg", action="store_true", help="list references to the command register")
    ap.add_argument("--disasm", help="ADDR:LEN (hex) Thumb listing instead of the walk")
    ap.add_argument("--entries", action="store_true", help="BL-closure of the writers + every entry into it")
    ap.add_argument("--flashbase", action="store_true", help="sites that build 0x0E000000 without a literal")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0
    fr = load("fr")
    r = Rom(load(a.rom), fr if a.rom != "fr" else None, parse_sym())
    if a.entries:
        closure, edges = entries(r)
        print(f"BL-closure of the flash writers: {len(closure)} functions")
        for f in sorted(closure):
            print(f"  {f:#010x} {r.name(f)}")
        print("entries (non-BL references into the closure):")
        for t, kind, site, f in edges:
            src = r.name(f) if f is not None else r.name(site)
            print(f"  {t:#010x} {r.name(t)}  <- {kind}@{site:#x} in {src}")
        return 0
    if a.flashbase:
        for s in flash_base_builders(r):
            print(f"  {s:#010x} {r.name(r.func_of(s))}")
        return 0
    if a.disasm:
        start, length = (int(x, 16) for x in a.disasm.split(":"))
        disasm(r, start, length)
        return 0
    seeds = {} if a.no_default_seeds else {k: (v, False) for k, v in PTR_VARS.items()}
    if a.cmdreg:
        seeds, a.depth = {CMD_REG: ("FLASH 0x5555 command register", False)}, 1
    for s in a.seed:
        seeds[int(s, 16)] = (f"seed {r.name(int(s, 16))}", True)
    walk(r, seeds, a.depth)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
