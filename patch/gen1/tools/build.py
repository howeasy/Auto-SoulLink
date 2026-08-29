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


# ── The START-menu row ──────────────────────────────────────────────────────────────────
# A declarative, bank-qualified manifest. Every span names the bytes it expects to find
# BEFORE it writes, so a ROM that is not the exact dump these offsets were derived from
# fails loudly rather than being silently corrupted -- the same posture as the hook site.
#
# Red and Blue are byte-identical across all of this, verified by reading both dumps, so
# one manifest serves both.
#
# WHAT THIS INCREMENT DOES, AND DELIBERATELY DOES NOT. It adds a SLINK row to the START
# menu and nothing else: selecting it falls through to CloseStartMenu exactly as EXIT does,
# because the dispatch chain in the home bank ends after `cp 5` and everything past it
# closes the menu. That is the point -- the risky structural change ships inert and
# visible, and the panel it will eventually open is a separate step that cannot break the
# menu if it goes wrong.
#
# WHY THE ROW GOES AFTER EXIT. The dispatch is a `cp N / jp z` chain over wCurrentMenuItem
# (home/start_menu.asm), so inserting anywhere earlier would renumber every item below it
# and silently re-point the menu. Appending leaves indices 0-6 exactly where they are.

MENU_STUB_ADDR = 0x00BE      # ROM0 free space, always mapped, reachable from bank 1
SLINK_TEXT_ADDR = 0x00D1     # immediately after the stub

# Gen 1's charset puts 'A' at $80, so a letter is $80 + (c - 'A'); $50 terminates.
# Cross-checked against the ROM's own "POKéDEX@" at 0x0718F, which reads 8F 8E 8A BA 83 84 97 50.
SLINK_TEXT = bytes([0x92, 0x8B, 0x88, 0x8D, 0x8A, 0x50])          # "SLINK@"

# The stub the DrawStartMenu tail is redirected into. It prints EXIT where EXIT already
# went, advances one menu row (two tile rows), then prints SLINK -- so EXIT keeps its
# position and its index, and SLINK becomes the new last item.
MENU_STUB = bytes([
    0xE5,                    # push hl              -- hl is where EXIT belongs
    0x11, 0xAF, 0x71,        # ld de, StartMenuExitText ($71AF, bank 1: the caller's bank)
    0xCD, 0x55, 0x19,        # call PlaceString ($1955, home)
    0xE1,                    # pop hl
    0x11, 0x28, 0x00,        # ld de, 40            -- SCREEN_WIDTH * 2, one menu row
    0x19,                    # add hl, de
    0x11, SLINK_TEXT_ADDR & 0xFF, SLINK_TEXT_ADDR >> 8,   # ld de, SlinkText
    0xCD, 0x55, 0x19,        # call PlaceString
    0xC9,                    # ret
])

# ── Making the row do something ─────────────────────────────────────────────────────────
# The dispatch is a `cp N / jp z` chain in the HOME bank ending in a fallthrough to
# CloseStartMenu, and there is no room to insert a seventh comparison in place. So the last
# comparison is replaced by a jump into ROM0's second free run, which re-does that
# comparison, adds ours, and falls back to the same fallthrough.
#
# ONE COMPARISON COVERS BOTH MENU SHAPES. home/start_menu.asm does `inc a` before
# dispatching when the player has no Pokedex, precisely so the handlers can use fixed
# numbers -- so SLINK is index 7 at the dispatch whether it was drawn as 6 or 7.
TRAMPOLINE_ADDR = 0x3FA6
PANEL_ENTRY_ADDR = 0x3FB3
SLINK_PANEL_ADDR = 0x4100        # pinned by the SECTION in slink.asm
HOOK_BANK_BYTE = 0x3F

TRAMPOLINE = bytes([
    0xFE, 0x05,                  # cp 5
    0xCA, 0xF6, 0x75,            # jp z, StartMenu_Option ($75F6, bank 4 is mapped here)
    0xFE, 0x07,                  # cp 7                    -- SLINK, both menu shapes
    0xCA, PANEL_ENTRY_ADDR & 0xFF, PANEL_ENTRY_ADDR >> 8,
    0xC3, 0x70, 0x2B,            # jp CloseStartMenu       -- the original fallthrough
])

# Bankswitch saves the caller's bank on the stack and restores it when our code returns,
# which is why the panel can live in bank $3F and still come back to a menu that expects
# bank 4. The existing VBlank hook relies on the same property.
PANEL_ENTRY = bytes([
    0x06, HOOK_BANK_BYTE,        # ld b, $3F
    0x21, SLINK_PANEL_ADDR & 0xFF, SLINK_PANEL_ADDR >> 8,
    0xCD, 0xD6, 0x35,            # call Bankswitch
    0xC3, 0xDF, 0x2A,            # jp RedisplayStartMenu   -- reopen the menu behind it
])

# (offset, expected original, replacement, why)
MENU_PATCHES = [
    (0x00BE, bytes(len(MENU_STUB)), MENU_STUB,
     "print stub in ROM0 free space (zero run 0x00BE-0x00FF, 66 bytes)"),
    (SLINK_TEXT_ADDR, bytes(len(SLINK_TEXT)), SLINK_TEXT,
     "the string SLINK@"),

    # DrawStartMenu, bank 1. The box is drawn before the item count is known, so both the
    # with-Pokedex and without-Pokedex heights need the extra menu row (two tile rows).
    (0x7114, bytes([0x0E]), bytes([0x10]),
     "TextBoxBorder height, with Pokedex: 14 -> 16 rows"),
    (0x711D, bytes([0x0C]), bytes([0x0E]),
     "TextBoxBorder height, without Pokedex: 12 -> 14 rows"),
    (0x714D, bytes([0x06]), bytes([0x07]),
     "wMaxMenuItem without Pokedex: 6 -> 7"),
    (0x7157, bytes([0x07]), bytes([0x08]),
     "wMaxMenuItem with Pokedex: 7 -> 8"),

    # `ld de, StartMenuExitText` + `call PlaceString` -> `call MenuStub` + padding. The
    # three trailing bytes become nops rather than being removed, because shortening the
    # routine would move everything after it.
    (0x7183, bytes([0x11, 0xAF, 0x71, 0xCD, 0x55, 0x19]),
     bytes([0xCD, MENU_STUB_ADDR & 0xFF, MENU_STUB_ADDR >> 8, 0x00, 0x00, 0x00]),
     "DrawStartMenu tail: print EXIT + SLINK via the stub"),

    # home/start_menu.asm wraps the cursor with its own hardcoded item counts, separate
    # from wMaxMenuItem. Without these the cursor cannot reach the new last row: it would
    # wrap from OPTION back to the top and SLINK would be visible but unselectable.
    (0x2B0C, bytes([0x06]), bytes([0x07]),
     "up-wrap target index: 6 -> 7 (the `dec a` below still handles the no-Pokedex case)"),
    (0x2B25, bytes([0x07]), bytes([0x08]),
     "down-wrap item count: 7 -> 8 (the `dec c` below still handles no-Pokedex)"),

    (TRAMPOLINE_ADDR, bytes(len(TRAMPOLINE)), TRAMPOLINE,
     "dispatch trampoline in ROM0's second free run (0x3FA6-0x3FFF, 90 bytes)"),
    (PANEL_ENTRY_ADDR, bytes(len(PANEL_ENTRY)), PANEL_ENTRY,
     "bank-$3F entry for the panel, returning to the menu"),
    (0x2B6B, bytes([0xFE, 0x05, 0xCA, 0xF6, 0x75]),
     bytes([0xC3, TRAMPOLINE_ADDR & 0xFF, TRAMPOLINE_ADDR >> 8, 0x00, 0x00]),
     "the last dispatch comparison -> jump to the trampoline"),
]

# Never written, at any offset, for any reason: the cartridge header carries the Nintendo
# logo the boot ROM checks and the entrypoint at $0100. The free run found by scanning
# runs 0x00BE-0x0100 INCLUSIVE, and that last byte is the entrypoint's `nop` -- so the
# usable span stops at 0x00FF and this range exists to make that non-negotiable.
PROTECTED_RANGE = (0x0100, 0x014F)


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
    # 3. Every menu span must hold exactly what the manifest expects, and none may touch
    #    the protected header. Checked for ALL spans before ANY is written, so a manifest
    #    that is half-applicable leaves the ROM untouched rather than half-patched.
    lo, hi = PROTECTED_RANGE
    for off, original, new, why in MENU_PATCHES:
        if not (off + len(new) <= lo or off > hi):
            raise SystemExit(
                f"{rom_key}: patch at {off:#06x} ({why}) overlaps the protected cartridge "
                f"header {lo:#06x}-{hi:#06x}")
        found = bytes(data[off:off + len(original)])
        if found != original:
            raise SystemExit(
                f"{rom_key}: {off:#06x} holds {found.hex()}, expected {original.hex()} "
                f"({why}) — this is not the dump these offsets were derived from")

    if verify_only:
        return (f"{rom_key}: clean ROM, hook site, target bank and "
                f"{len(MENU_PATCHES)} menu spans all as expected")

    data[INJECT_OFFSET:INJECT_OFFSET + BANK_SIZE] = bank
    for off, _original, new, _why in MENU_PATCHES:
        data[off:off + len(new)] = new
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
    for off, _original, new, why in MENU_PATCHES:
        assert bytes(check[off:off + len(new)]) == new, f"{why} did not land at {off:#06x}"
    assert check[lo:hi + 1] == bytes(open(src, "rb").read()[lo:hi + 1]),         "the cartridge header changed"
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
