#!/usr/bin/env python3
"""Scan a GBA ROM for runs of free space (repeated fill bytes).

Free space in FireRed/CFRU ROMs is padding the build never touches — almost always
0xFF (and sometimes 0x00). We report long aligned runs as injection candidates, in
both file-offset and ROM-address (0x08000000 + offset) terms.

This is a *cross-validation* tool: its findings are checked against CFRU's documented
0x900000 region and the RR/DPE usage map before anything is injected (see plan §5).

Usage:
    python find_freespace.py <rom.gba> [--fill 0xFF] [--min 0x400] [--align 4] [--top 20]
"""
import argparse
import sys


def find_runs(data: bytes, fill: int, min_len: int, align: int):
    runs = []
    n = len(data)
    i = 0
    while i < n:
        if data[i] != fill:
            i += 1
            continue
        j = i
        while j < n and data[j] == fill:
            j += 1
        # Align the start up to `align`; trim the length accordingly.
        start = (i + align - 1) & ~(align - 1)
        length = j - start
        if length >= min_len:
            runs.append((start, length))
        i = j
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--fill", default="0xFF", help="fill byte, e.g. 0xFF or 0x00")
    ap.add_argument("--min", default="0x400", help="minimum run length (bytes)")
    ap.add_argument("--align", default="4", help="required start alignment")
    ap.add_argument("--top", type=int, default=20, help="show N largest runs")
    args = ap.parse_args()

    fill = int(args.fill, 0)
    min_len = int(args.min, 0)
    align = int(args.align, 0)

    with open(args.rom, "rb") as f:
        data = f.read()

    runs = find_runs(data, fill, min_len, align)
    runs.sort(key=lambda r: r[1], reverse=True)

    total_free = sum(length for _, length in runs)
    print(f"ROM: {args.rom}  size=0x{len(data):X} ({len(data)} bytes)")
    print(f"fill=0x{fill:02X}  min=0x{min_len:X}  align={align}")
    print(f"runs>=min: {len(runs)}   total free in those runs: 0x{total_free:X} "
          f"({total_free} bytes, {100*total_free/len(data):.1f}% of ROM)")
    print(f"\n{'file_off':>10}  {'rom_addr':>10}  {'length':>10}")
    print("-" * 36)
    for start, length in runs[:args.top]:
        print(f"0x{start:08X}  0x{0x08000000+start:08X}  0x{length:08X}")

    # Highlight runs at/after CFRU's conventional 0x900000 (cross-check anchor).
    cfru = [r for r in runs if r[0] >= 0x900000]
    if cfru:
        big = max(cfru, key=lambda r: r[1])
        print(f"\nLargest run at/after CFRU 0x900000 region: "
              f"file 0x{big[0]:08X} / rom 0x{0x08000000+big[0]:08X}, len 0x{big[1]:X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
