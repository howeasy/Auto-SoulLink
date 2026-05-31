#!/usr/bin/env python3
"""Build the SLink companion patch into the Radical Red ROM.

Pipeline (plan §3):
  1. copy the pinned RR ROM -> build/slink_RR.gba
  2. assemble patch/src/slink_patch.asm into it with armips (via a generated wrapper)
  3. verify the injection by disassembling the hook site + code region
  4. emit dist/SLink-RR.ups and .ips, each self-validated by round-trip

All paths are derived from this file's location; no manual setup.

Usage:
    python patch/tools/build.py [--rom <path to Radical Red.gba>]
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATCH = os.path.dirname(HERE)               # .../patch
ROOT = os.path.dirname(PATCH)               # worktree root
BUILD = os.path.join(PATCH, "build")
DIST = os.path.join(PATCH, "dist")
SRC = os.path.join(PATCH, "src", "slink_patch.asm")
ARMIPS = os.path.join(PATCH, "vendor", "armips", "armips.exe")

RR_MD5 = "8529f3a45d32bce4da637976fcf269d4"
DEFAULT_RR = r"E:/Google Drive/SLink/Pokemon - Radical Red.gba"

sys.path.insert(0, HERE)
import make_ups  # noqa: E402


def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=DEFAULT_RR)
    ap.add_argument("--no-verify-md5", action="store_true")
    args = ap.parse_args()

    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(DIST, exist_ok=True)

    if not os.path.exists(args.rom):
        sys.exit(f"ROM not found: {args.rom}")
    src_md5 = md5(args.rom)
    print(f"[1/4] source ROM {args.rom}\n      md5 {src_md5}")
    if not args.no_verify_md5 and src_md5 != RR_MD5:
        sys.exit(f"ERROR: RR md5 mismatch (expected pinned {RR_MD5}). "
                 f"Re-pin the build before patching.")

    out_rom = os.path.join(BUILD, "slink_RR.gba")
    shutil.copyfile(args.rom, out_rom)
    print(f"[2/4] copied -> {out_rom}")

    # generate the armips wrapper that opens the output ROM in place
    wrapper = os.path.join(BUILD, "_main.asm")
    with open(wrapper, "w") as f:
        f.write(".gba\n")
        f.write(f'.open "{out_rom}",0x08000000\n')
        f.write(f'.include "{SRC}"\n')
        f.write(".close\n")

    if not os.path.exists(ARMIPS):
        sys.exit(f"armips not found at {ARMIPS}")
    res = subprocess.run([ARMIPS, wrapper], capture_output=True, text=True)
    print(res.stdout.strip())
    if res.returncode != 0:
        print(res.stderr.strip())
        sys.exit(f"armips failed (rc={res.returncode})")
    print(f"      assembled OK -> {out_rom} (md5 {md5(out_rom)})")

    # verify injection: hook site must now be a BL; code region must be non-0xFF
    print("[3/4] verifying injection")
    _verify(out_rom)

    # emit patches with self-validating round-trip
    print("[4/4] generating patches")
    with open(args.rom, "rb") as f:
        clean = f.read()
    with open(out_rom, "rb") as f:
        patched = f.read()
    ups = make_ups.ups_create(clean, patched)
    rt = make_ups.ups_apply(clean, ups)
    assert hashlib.md5(rt).hexdigest() == hashlib.md5(patched).hexdigest(), "UPS RT fail"
    out_ups = os.path.join(DIST, "SLink-RR.ups")
    with open(out_ups, "wb") as f:
        f.write(ups)
    print(f"      {out_ups}  ({len(ups)} B)  round-trip OK")
    try:
        ips = make_ups.ips_create(clean, patched)
        rt2 = make_ups.ips_apply(clean, ips)
        assert hashlib.md5(rt2).hexdigest() == hashlib.md5(patched).hexdigest()
        out_ips = os.path.join(DIST, "SLink-RR.ips")
        with open(out_ips, "wb") as f:
            f.write(ips)
        print(f"      {out_ips}  ({len(ips)} B)  round-trip OK")
    except ValueError as e:
        print(f"      IPS skipped: {e}")

    print(f"\nDONE. patched md5 {md5(out_rom)}")
    return 0


def _disasm(rom, addr, count, arm=False):
    cmd = [sys.executable, os.path.join(HERE, "disasm.py"), rom, hex(addr), str(count)]
    if arm:
        cmd.append("--arm")
    return subprocess.run(cmd, capture_output=True, text=True).stdout


def _verify(rom):
    hook = _disasm(rom, 0x0800051A, 3)
    print("   hook site 0x0800051A:")
    for line in hook.splitlines()[1:]:
        print("     " + line.strip())
    if "bl" not in hook or "0x8378ca8" not in hook:
        sys.exit("VERIFY FAIL: hook site is not a BL to the code region")
    code = _disasm(rom, 0x08378CA8, 4)
    print("   code region 0x08378CA8:")
    for line in code.splitlines()[1:]:
        print("     " + line.strip())
    if "push" not in code:
        sys.exit("VERIFY FAIL: code region does not start with push (not assembled?)")
    print("   injection verified OK")


if __name__ == "__main__":
    sys.exit(main())
