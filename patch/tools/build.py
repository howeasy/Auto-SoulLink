#!/usr/bin/env python3
"""Build the SLink companion patch into the Radical Red ROM (C toolchain).

Pipeline (plan §3):
  1. arm-none-eabi-gcc  -> handlers.o   (Thumb, freestanding)
  2. arm-none-eabi-ld   -> handlers.elf (linked at CODE_BASE via slink.ld)
  3. verify slink_hook == CODE_BASE (nm)
  4. objcopy -O binary  -> handlers.bin
  5. copy RR -> build/slink_RR.gba ; inject handlers.bin at CODE_BASE
  6. write the 4-byte Thumb `bl slink_hook` over the CallCallbacks NOP sled
  7. verify by disassembly ; emit UPS/IPS (round-trip self-checked)

Usage: python patch/tools/build.py [--rom <Radical Red.gba>]
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATCH = os.path.dirname(HERE)
BUILD = os.path.join(PATCH, "build")
DIST = os.path.join(PATCH, "dist")
SRC = os.path.join(PATCH, "src")
GCCDIR = os.path.join(PATCH, "vendor", "armgcc",
                      "xpack-arm-none-eabi-gcc-15.2.1-1.1", "bin")
GCC = os.path.join(GCCDIR, "arm-none-eabi-gcc.exe")
LD = os.path.join(GCCDIR, "arm-none-eabi-ld.exe")
OBJCOPY = os.path.join(GCCDIR, "arm-none-eabi-objcopy.exe")
NM = os.path.join(GCCDIR, "arm-none-eabi-nm.exe")

ROM_BASE = 0x08000000
CODE_BASE = 0x08378CA8
HOOK_SITE = 0x0800051A
RR_MD5 = "8529f3a45d32bce4da637976fcf269d4"
DEFAULT_RR = r"E:/Google Drive/SLink/Pokemon - Radical Red.gba"

sys.path.insert(0, HERE)
import make_ups  # noqa: E402

CFLAGS = ["-mthumb", "-mcpu=arm7tdmi", "-mtune=arm7tdmi", "-Os", "-ffreestanding",
          "-fno-builtin", "-fomit-frame-pointer", "-fno-toplevel-reorder",
          "-fno-jump-tables",  # avoid libgcc __gnu_thumb1_case_* switch helpers
          "-mno-unaligned-access", "-Wall", "-std=c11"]


def md5(p):
    with open(p, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(" ".join(cmd))
        print(r.stdout); print(r.stderr)
        sys.exit("command failed")
    return r.stdout


def thumb_bl(src, dst):
    """ARMv4T Thumb BL (two halfwords, 11+11 offset bits, +-4 MB)."""
    off = dst - (src + 4)
    if not -0x400000 <= off < 0x400000:
        sys.exit(f"BL out of range: {hex(src)}->{hex(dst)} ({off:#x})")
    hi = 0xF000 | ((off >> 12) & 0x7FF)
    lo = 0xF800 | ((off >> 1) & 0x7FF)
    return bytes([hi & 0xFF, (hi >> 8) & 0xFF, lo & 0xFF, (lo >> 8) & 0xFF])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=DEFAULT_RR)
    ap.add_argument("--no-verify-md5", action="store_true")
    args = ap.parse_args()
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(DIST, exist_ok=True)
    for t in (GCC, LD, OBJCOPY):
        if not os.path.exists(t):
            sys.exit(f"toolchain missing: {t}")

    obj = os.path.join(BUILD, "handlers.o")
    elf = os.path.join(BUILD, "handlers.elf")
    binf = os.path.join(BUILD, "handlers.bin")
    print("[1/7] compile")
    run([GCC, *CFLAGS, "-c", os.path.join(SRC, "handlers.c"), "-o", obj])
    print("[2/7] link @ %#x" % CODE_BASE)
    run([LD, "-T", os.path.join(SRC, "slink.ld"), "-e", "slink_hook",
         "--no-warn-rwx-segments", obj, "-o", elf])
    print("[3/7] verify slink_hook address")
    syms = run([NM, elf])
    hook_addr = None
    for line in syms.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == "slink_hook":
            hook_addr = int(parts[0], 16)
    if hook_addr != CODE_BASE:
        sys.exit(f"slink_hook at {hook_addr:#x}, expected {CODE_BASE:#x}")
    print(f"      slink_hook @ {hook_addr:#010x} OK")
    print("[4/7] objcopy -> bin")
    run([OBJCOPY, "-O", "binary", elf, binf])
    blob = open(binf, "rb").read()
    print(f"      handlers.bin = {len(blob)} bytes")

    print("[5/7] inject into ROM")
    src_md5 = md5(args.rom)
    if not args.no_verify_md5 and src_md5 != RR_MD5:
        sys.exit(f"RR md5 mismatch (expected {RR_MD5}, got {src_md5})")
    out_rom = os.path.join(BUILD, "slink_RR.gba")
    shutil.copyfile(args.rom, out_rom)
    data = bytearray(open(out_rom, "rb").read())
    code_off = CODE_BASE - ROM_BASE
    data[code_off:code_off + len(blob)] = blob
    print("[6/7] write hook BL")
    bl = thumb_bl(HOOK_SITE, CODE_BASE)
    hook_off = HOOK_SITE - ROM_BASE
    data[hook_off:hook_off + 4] = bl
    with open(out_rom, "wb") as f:
        f.write(data)

    _verify(out_rom)
    print("[7/7] patches")
    clean = open(args.rom, "rb").read()
    patched = bytes(data)
    ups = make_ups.ups_create(clean, patched)
    assert hashlib.md5(make_ups.ups_apply(clean, ups)).hexdigest() == hashlib.md5(patched).hexdigest()
    open(os.path.join(DIST, "SLink-RR.ups"), "wb").write(ups)
    print(f"      SLink-RR.ups ({len(ups)} B) round-trip OK")
    try:
        ips = make_ups.ips_create(clean, patched)
        assert hashlib.md5(make_ups.ips_apply(clean, ips)).hexdigest() == hashlib.md5(patched).hexdigest()
        open(os.path.join(DIST, "SLink-RR.ips"), "wb").write(ips)
        print(f"      SLink-RR.ips ({len(ips)} B) round-trip OK")
    except ValueError as e:
        print(f"      IPS skipped: {e}")
    print(f"\nDONE. patched md5 {md5(out_rom)}")
    return 0


def _disasm(rom, addr, count):
    return subprocess.run([sys.executable, os.path.join(HERE, "disasm.py"),
                           rom, hex(addr), str(count)],
                          capture_output=True, text=True).stdout


def _verify(rom):
    hook = _disasm(rom, HOOK_SITE, 3)
    print("   hook site:")
    for ln in hook.splitlines()[1:]:
        print("     " + ln.strip())
    if "bl" not in hook or f"{CODE_BASE:x}" not in hook:
        sys.exit("VERIFY FAIL: hook not a BL to CODE_BASE")
    code = _disasm(rom, CODE_BASE, 4)
    print("   code region:")
    for ln in code.splitlines()[1:]:
        print("     " + ln.strip())
    print("   injection verified OK")


if __name__ == "__main__":
    sys.exit(main())
