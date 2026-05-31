#!/usr/bin/env python3
"""Disassemble a region of a GBA ROM (Thumb or ARM) with capstone.

The binary half of address cross-validation (plan §5): confirm a symbol from
BPRE.ld / pokefirered actually lands on a sane function prologue in the *real*
Radical Red ROM before we hook or call it.

Usage:
    python disasm.py <rom.gba> <rom_addr> [count] [--arm]
    # rom_addr like 0x8077578 ; file offset = rom_addr - 0x08000000
"""
import argparse
import sys

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

ROM_BASE = 0x08000000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("addr")
    ap.add_argument("count", nargs="?", default="16")
    ap.add_argument("--arm", action="store_true", help="ARM mode (default Thumb)")
    args = ap.parse_args()

    addr = int(args.addr, 0) & ~1   # strip Thumb bit if present
    count = int(args.count, 0)
    off = addr - ROM_BASE

    with open(args.rom, "rb") as f:
        data = f.read()

    mode = CS_MODE_ARM if args.arm else CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, mode)
    blob = data[off:off + count * (4 if args.arm else 4)]
    print(f"{args.rom}  @ rom 0x{addr:08X} (file 0x{off:06X})  "
          f"{'ARM' if args.arm else 'THUMB'}")
    n = 0
    for insn in md.disasm(blob, addr):
        raw = " ".join(f"{b:02X}" for b in insn.bytes)
        print(f"  0x{insn.address:08X}:  {raw:<12}  {insn.mnemonic}\t{insn.op_str}")
        n += 1
        if n >= count:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
