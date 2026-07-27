#!/usr/bin/env python3
"""build.py — assemble the Gen 1 companion-patch spike and inject it into Red/Blue.

    python patch/gen1/tools/build.py                 # both ROMs
    python patch/gen1/tools/build.py --rom red
    python patch/gen1/tools/build.py --verify-only   # re-check an existing build

Mirrors patch/tools/build.py (the Radical Red pipeline) with three differences that fall
out of the platform:

  * RGBDS, not arm-none-eabi-gcc. The Game Boy has no practical C toolchain and pret is
    pure assembly, so the module is hand-written SM83 and assembled with the rgbasm the
    repo already auto-downloads for the symbol pipeline. Nothing new to install.
  * Padding is 0x00, not 0xFF — pokered links with `-p 0x00`, so an unused bank is a run
    of zero bytes and that is what we assert before overwriting it.
  * RED AND BLUE ONLY. Yellow has no free WRAM at all (pret's map: `WRAM0: TOTAL EMPTY:
    $0000`) so there is nowhere to put a mailbox.

Every write is verify-then-write: the hook bytes are checked against their expected current
values before being changed, so a ROM that is not the exact expected dump fails loudly
instead of being silently corrupted.
"""
import argparse
import hashlib
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "tools"))

from _build_tools_bootstrap import ensure_rgbds  # noqa: E402

SRC = os.path.join(REPO, "patch", "gen1", "src", "slink.asm")
BUILD = os.path.join(REPO, "patch", "gen1", "build")

# Where the module is linked, and therefore where it is injected.
HOOK_BANK = 0x3F
BANK_SIZE = 0x4000
INJECT_OFFSET = HOOK_BANK * BANK_SIZE          # 0xFC000
HOOK_TARGET = 0x4000                            # bank $3F is mapped at $4000

# The `farcall TrackPlayTime` inside VBlank. Unique in the ROM — verified by scanning.
#   ld b, $06 / ld hl, $4DEE / call Bankswitch($35D6)
HOOK_SITE = 0x2094
HOOK_ORIGINAL = bytes([0x06, 0x06, 0x21, 0xEE, 0x4D, 0xCD, 0xD6, 0x35])

ROMS = {
    "red": ("Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb",
            "ea9bcae617fdf159b045185467ae58b2e4a48b9a"),
    "blue": ("Pokemon - Blue Version (USA, Europe) (SGB Enhanced).gb",
             "d7037c83e1ae5b39bde3c30787637ba1d4c48ce2"),
}


def assemble() -> bytes:
    """rgbasm + rgblink the module; return the raw bytes of bank $3F."""
    rgbds = ensure_rgbds()
    os.makedirs(BUILD, exist_ok=True)
    exe = ".exe" if os.name == "nt" else ""
    obj = os.path.join(BUILD, "slink.o")
    out = os.path.join(BUILD, "slink_stub.gb")

    subprocess.run([os.path.join(rgbds, "rgbasm" + exe), "-o", obj, SRC], check=True)
    # -p 0x00 matches pokered's own RGBLINKFLAGS, so the padding we emit is the padding the
    # target bank already contains.
    subprocess.run([os.path.join(rgbds, "rgblink" + exe), "-p", "0x00",
                    "-o", out, "-n", os.path.join(BUILD, "slink.sym"), obj], check=True)
    with open(out, "rb") as f:
        image = f.read()
    start = INJECT_OFFSET
    if len(image) < start + BANK_SIZE:
        # rgblink emits only as many banks as it needs; the section is pinned to $3F, so a
        # short image means the pin did not take.
        raise SystemExit(f"linked image is {len(image)} bytes — bank {HOOK_BANK:#x} missing")
    return image[start:start + BANK_SIZE]


def code_length(bank: bytes) -> int:
    """Bytes of actual code, i.e. up to the trailing 0x00 padding."""
    end = len(bank)
    while end > 0 and bank[end - 1] == 0:
        end -= 1
    return end


def patch_rom(rom_key: str, bank: bytes, verify_only: bool = False) -> str:
    name, sha1 = ROMS[rom_key]
    src = os.path.join(REPO, name)
    if not os.path.exists(src):
        raise SystemExit(f"ROM not found: {name}")
    with open(src, "rb") as f:
        data = bytearray(f.read())

    actual = hashlib.sha1(bytes(data)).hexdigest()
    if actual != sha1:
        raise SystemExit(f"{rom_key}: expected sha1 {sha1}, got {actual} — wrong dump")

    # 1. The target bank must be untouched padding. If it is not, this is not the ROM the
    #    offsets were derived from and injecting would destroy real code.
    region = data[INJECT_OFFSET:INJECT_OFFSET + BANK_SIZE]
    if any(b != 0 for b in region):
        raise SystemExit(f"{rom_key}: bank {HOOK_BANK:#x} is not empty — refusing to inject")

    # 2. The hook site must still hold the exact instruction we expect to displace.
    site = bytes(data[HOOK_SITE:HOOK_SITE + len(HOOK_ORIGINAL)])
    if site != HOOK_ORIGINAL:
        raise SystemExit(f"{rom_key}: hook site {HOOK_SITE:#x} holds {site.hex()}, "
                         f"expected {HOOK_ORIGINAL.hex()}")
    if verify_only:
        return f"{rom_key}: clean ROM, hook site and target bank both as expected"

    data[INJECT_OFFSET:INJECT_OFFSET + BANK_SIZE] = bank
    # Rewrite only the two immediates: `ld b, $3F` and `ld hl, $4000`. The
    # `call Bankswitch` after them is untouched, so control still flows the same way.
    data[HOOK_SITE + 1] = HOOK_BANK
    data[HOOK_SITE + 3] = HOOK_TARGET & 0xFF
    data[HOOK_SITE + 4] = HOOK_TARGET >> 8

    os.makedirs(BUILD, exist_ok=True)
    dst = os.path.join(BUILD, f"slink_{rom_key}.gb")
    with open(dst, "wb") as f:
        f.write(data)

    # 3. Read the result back and confirm the hook really points at our code.
    with open(dst, "rb") as f:
        check = f.read()
    assert check[HOOK_SITE + 1] == HOOK_BANK
    assert check[HOOK_SITE + 3] | (check[HOOK_SITE + 4] << 8) == HOOK_TARGET
    assert check[INJECT_OFFSET:INJECT_OFFSET + 8] == bank[:8]
    return (f"{rom_key}: {os.path.relpath(dst, REPO)}  "
            f"md5={hashlib.md5(check).hexdigest()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rom", choices=sorted(ROMS), help="only this ROM (default: both)")
    ap.add_argument("--verify-only", action="store_true",
                    help="check the base ROMs and hook site, build nothing")
    args = ap.parse_args()

    bank = assemble()
    n = code_length(bank)
    print(f"[gen1-patch] assembled {n} bytes of code into bank {HOOK_BANK:#x}", file=sys.stderr)

    for rom_key in ([args.rom] if args.rom else sorted(ROMS)):
        print("[gen1-patch] " + patch_rom(rom_key, bank, args.verify_only), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
