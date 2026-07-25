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
       python patch/tools/build.py --check     # reproducibility gate (see main)
"""
import argparse
import glob
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PATCH = os.path.dirname(HERE)
BUILD = os.path.join(PATCH, "build")
DIST = os.path.join(PATCH, "dist")
SRC = os.path.join(PATCH, "src")
EXE = ".exe" if os.name == "nt" else ""


def _toolchain_dir():
    """Locate the arm-none-eabi bin dir: $SLINK_ARMGCC, then patch/vendor/armgcc/*/bin
    (newest first), then PATH.  Globbed rather than version-pinned so bumping the
    vendored xPack release doesn't silently break the build."""
    cands = [os.environ.get("SLINK_ARMGCC", "")]
    cands += sorted(glob.glob(os.path.join(PATCH, "vendor", "armgcc", "*", "bin")),
                    reverse=True)
    for d in cands:
        if d and os.path.exists(os.path.join(d, "arm-none-eabi-gcc" + EXE)):
            return d
    return "" if shutil.which("arm-none-eabi-gcc") else None


GCCDIR = _toolchain_dir()


def _tool(name):
    return os.path.join(GCCDIR, name + EXE) if GCCDIR else name


GCC = _tool("arm-none-eabi-gcc")
LD = _tool("arm-none-eabi-ld")
OBJCOPY = _tool("arm-none-eabi-objcopy")
NM = _tool("arm-none-eabi-nm")

ROM_BASE = 0x08000000
# 0x08378F70, not 0x08378CA8: the bundled RR4.1_Custom Battle Calc occupies
# 0x08378CA8..0x08378F6F. SLink injects into the 0xFF run that resumes at 0x08378F70
# (~0x14638 free; keep in sync with ORIGIN in slink.ld).
CODE_BASE = 0x08378F70
HOOK_SITE = 0x0800051A
# CFRU BackupParty's two party->backup-buffer memcpy BL sites. We redirect them to
# slink_backup_wrap so the patch learns the EXACT frame a borrowed-party swap begins
# (the authoritative "Party Freeze" signal). Discovered live via
# lua/tests/probe_party_backup_writer.lua (writers of REAL_PARTY_BACKUP 0x02025564).
BACKUP_BL_SITES = (0x0804C10C, 0x0804C212)
BACKUP_MEMCPY = 0x081E5E78  # the engine memcpy the sites originally `bl`'d (sanity-checked pre-redirect)
# The Battle Calc detours BattlePutTextOnWindow's 2nd instruction (0x080D87BE) to this trampoline.
# We re-point that detour to our in-context shim, which falls through to this trampoline. See [6/7].
BATTLE_CALC_TRAMPOLINE = 0x08378CA8
# §6 SOULLINK start-menu entry. RR reads the menu's description and action arrays through one base
# literal with hardcoded offsets, and the two ranges abut (desc[13] IS act[0].text), so a 14th
# action id cannot own a description. We take over id 8 instead — a second PLAYER row only
# SetUpStartMenu_Link ever appends, proven absent from a real field menu by
# lua/tests/test_live_startmenu.lua. Four word writes, each verified against its expected current value
# so a different RR build fails the build instead of producing a subtly wrong ROM.
STARTMENU_TABLE = 0x09148FB4
STARTMENU_DESC8 = STARTMENU_TABLE + 8 + 4 * 8       # 0x09148FDC — desc[8]
STARTMENU_ACT8 = STARTMENU_TABLE + 0x3C + 8 * 8     # 0x09149030 — act[8] = {text, func}
STARTMENU_SETUP_LIT = 0x0806ED58                    # CFRU's SetUpStartMenu redirect literal
STARTMENU_EXPECT = {
    STARTMENU_DESC8: 0x0841A049,       # duplicate of desc[3] (PLAYER)
    STARTMENU_ACT8: 0x0841628E,        # duplicate of act[3].text (PLAYER)
    STARTMENU_ACT8 + 4: 0x0806F56D,    # id 8's own action func (NOT act[3].func)
    STARTMENU_SETUP_LIT: 0x090BE179,   # the original SetUpStartMenu
}

RR_MD5 = "8529f3a45d32bce4da637976fcf269d4"
DEFAULT_RR = r"E:/Google Drive/SLink/Pokemon - Radical Red.gba"
# Committed base-RR -> RR4.1_Custom Battle Calc delta (the in-battle damage / type-
# effectiveness calculator), folded in before SLink injection. Regenerate with
# tools/make_battle_calc_patch.py. UPS because the Battle Calc code is > 16 MB.
BATTLE_CALC_UPS = os.path.join(SRC, "rr41_battle_calc.ups")

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
    global BUILD, DIST
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=DEFAULT_RR)
    ap.add_argument("--no-verify-md5", action="store_true")
    ap.add_argument("--no-battle-calc", action="store_true",
                    help="skip folding in the RR4.1_Custom Battle Calc delta "
                         "(emit base-RR + SLink only)")
    ap.add_argument("--check", action="store_true",
                    help="reproducibility gate: build into a temp dir and assert the "
                         "emitted UPS is byte-identical to the committed dist/SLink-RR.ups. "
                         "Touches nothing in the tree.")
    args = ap.parse_args()
    committed_ups = os.path.join(DIST, "SLink-RR.ups")
    tmp = tempfile.mkdtemp(prefix="slink-build-") if args.check else None
    if args.check:
        if not os.path.exists(committed_ups):
            sys.exit(f"--check: no committed patch at {committed_ups}")
        BUILD = DIST = tmp
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(DIST, exist_ok=True)
    if GCCDIR is None:
        sys.exit("toolchain missing: no arm-none-eabi-gcc in $SLINK_ARMGCC, "
                 "patch/vendor/armgcc/*/bin, or PATH")

    obj = os.path.join(BUILD, "handlers.o")
    elf = os.path.join(BUILD, "handlers.elf")
    binf = os.path.join(BUILD, "handlers.bin")
    print("[1/7] compile")
    run([GCC, *CFLAGS, "-c", os.path.join(SRC, "handlers.c"), "-o", obj])
    print("[2/7] link @ %#x" % CODE_BASE)
    run([LD, "-T", os.path.join(SRC, "slink.ld"), "-e", "slink_hook",
         "--no-warn-rwx-segments", obj, "-o", elf])
    print("[3/7] verify slink_hook address")
    # Every symbol the ROM-side rewrites need to point at. Missing one is fatal: it would mean a
    # detour or table word silently keeping its old target.
    WANTED = ("slink_hook", "slink_battletext_hook", "slink_backup_wrap",
              "slink_startmenu_cb", "slink_setup_start_menu", "sSoulLinkLabel", "sSoulLinkDesc")
    sym = {}
    for line in run([NM, elf]).splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] in WANTED:
            sym[parts[2]] = int(parts[0], 16)
    missing = [s for s in WANTED if s not in sym]
    if missing:
        sys.exit(f"symbols not found in handlers.elf: {', '.join(missing)}")
    if sym["slink_hook"] != CODE_BASE:
        sys.exit(f"slink_hook at {sym['slink_hook']:#x}, expected {CODE_BASE:#x}")
    bt_hook_addr = sym["slink_battletext_hook"]
    backup_wrap_addr = sym["slink_backup_wrap"]
    print(f"      slink_hook @ {sym['slink_hook']:#010x} OK")
    for s in WANTED[1:]:
        print(f"      {s} @ {sym[s]:#010x}")
    print("[4/7] objcopy -> bin")
    run([OBJCOPY, "-O", "binary", elf, binf])
    blob = open(binf, "rb").read()
    print(f"      handlers.bin = {len(blob)} bytes")
    MAX_CODE_SIZE = 0x14000  # slink.ld MEMORY rom LENGTH — keep the two in sync
    if len(blob) > MAX_CODE_SIZE:
        sys.exit(f"handlers.bin {len(blob)} B exceeds slink.ld region LENGTH {MAX_CODE_SIZE:#x}")

    print("[5/7] inject into ROM")
    src_md5 = md5(args.rom)
    if not args.no_verify_md5 and src_md5 != RR_MD5:
        sys.exit(f"RR md5 mismatch (expected {RR_MD5}, got {src_md5})")
    out_rom = os.path.join(BUILD, "slink_RR.gba")
    clean = open(args.rom, "rb").read()  # the user's apply target (base RR), kept un-calc'd
    if args.no_battle_calc:
        data = bytearray(clean)
        print("      Battle Calc SKIPPED (--no-battle-calc) -> base RR + SLink only")
    else:
        # Fold the RR4.1_Custom Battle Calc onto base RR first. ups_apply CRC-gates
        # source == base RR and target == RR4.1_Custom, so a wrong base ROM fails loudly.
        battle_calc = open(BATTLE_CALC_UPS, "rb").read()
        data = bytearray(make_ups.ups_apply(clean, battle_calc))
        print(f"      applied Battle Calc {os.path.relpath(BATTLE_CALC_UPS, PATCH)} "
              f"({len(battle_calc)} B) -> RR4.1_Custom")
    code_off = CODE_BASE - ROM_BASE
    region = data[code_off:code_off + len(blob)]
    if any(b != 0xFF for b in region):
        bad = code_off + next(i for i, b in enumerate(region) if b != 0xFF)
        sys.exit(f"CODE_BASE {CODE_BASE:#010x} not free for {len(blob)} B "
                 f"(non-0xFF at ROM {ROM_BASE + bad:#010x}) — would clobber ROM/Battle-Calc data")
    data[code_off:code_off + len(blob)] = blob
    print("[6/7] write hook BL")
    bl = thumb_bl(HOOK_SITE, CODE_BASE)
    hook_off = HOOK_SITE - ROM_BASE
    data[hook_off:hook_off + 4] = bl
    # Redirect CFRU BackupParty's memcpy BL sites -> slink_backup_wrap (Party Freeze begin signal).
    # Each site must currently be `BL BACKUP_MEMCPY`; bail loudly if the CFRU layout moved.
    for site in BACKUP_BL_SITES:
        s_off = site - ROM_BASE
        if bytes(data[s_off:s_off + 4]) != thumb_bl(site, BACKUP_MEMCPY):
            sys.exit(f"backup BL site {site:#x} is not `BL {BACKUP_MEMCPY:#x}` — CFRU layout changed; re-RE")
        data[s_off:s_off + 4] = thumb_bl(site, backup_wrap_addr)
    print(f"      redirected backup BL sites {', '.join(hex(s) for s in BACKUP_BL_SITES)} "
          f"-> slink_backup_wrap {backup_wrap_addr:#x}")
    # §6: take over start-menu action id 8 -> SOULLINK. Verify-then-write, same discipline as the
    # BL redirects above: if any word is not what we RE'd, the RR/CFRU layout moved and guessing
    # would corrupt a menu the player uses every session.
    def w32(addr, value):
        o = addr - ROM_BASE
        data[o:o + 4] = value.to_bytes(4, "little")

    for addr, expect in STARTMENU_EXPECT.items():
        got = int.from_bytes(bytes(data[addr - ROM_BASE:addr - ROM_BASE + 4]), "little")
        if got != expect:
            sys.exit(f"start-menu word {addr:#x} is {got:#010x}, expected {expect:#010x} — "
                     "RR/CFRU start-menu layout changed; re-run lua/tests/test_live_startmenu.lua and re-RE")
    w32(STARTMENU_DESC8, sym["sSoulLinkDesc"])
    w32(STARTMENU_ACT8, sym["sSoulLinkLabel"])
    w32(STARTMENU_ACT8 + 4, sym["slink_startmenu_cb"] | 1)          # Thumb bit
    w32(STARTMENU_SETUP_LIT, sym["slink_setup_start_menu"] | 1)
    print(f"      start-menu id 8 -> SOULLINK (label {sym['sSoulLinkLabel']:#x}, "
          f"cb {sym['slink_startmenu_cb'] | 1:#x}, setup wrapper "
          f"{sym['slink_setup_start_menu'] | 1:#x})")
    # Re-point the Battle Calc's BattlePutTextOnWindow detour (0x080D87BE: `BL 0x08378CA8`) to our in-context
    # shim, which swaps the text ptr when a notification is active then falls through to the calc trampoline.
    # Only meaningful when the Battle Calc is present (it installs that detour); skip if --no-battle-calc.
    if not args.no_battle_calc:
        BT_DETOUR = 0x080D87BE
        bt_off = BT_DETOUR - ROM_BASE
        if bytes(data[bt_off:bt_off + 4]) != bytes(thumb_bl(BT_DETOUR, BATTLE_CALC_TRAMPOLINE)):
            sys.exit(f"Battle Calc detour @ {BT_DETOUR:#x} not the expected `BL {BATTLE_CALC_TRAMPOLINE:#x}` "
                     "— Battle Calc layout changed; re-RE before re-pointing")
        data[bt_off:bt_off + 4] = thumb_bl(BT_DETOUR, bt_hook_addr)
        print(f"      re-pointed BattlePutTextOnWindow detour @ {BT_DETOUR:#x} -> shim {bt_hook_addr:#x}")
    with open(out_rom, "wb") as f:
        f.write(data)

    _verify(out_rom)
    print("[7/7] patches")
    patched = bytes(data)
    ups = make_ups.ups_create(clean, patched)
    assert hashlib.md5(make_ups.ups_apply(clean, ups)).hexdigest() == hashlib.md5(patched).hexdigest()
    open(os.path.join(DIST, "SLink-RR.ups"), "wb").write(ups)
    print(f"      SLink-RR.ups ({len(ups)} B) round-trip OK")
    if args.check:
        want = open(committed_ups, "rb").read()
        shutil.rmtree(tmp, ignore_errors=True)
        if ups != want:
            sys.exit(f"CHECK FAIL: rebuilt UPS ({len(ups)} B, md5 "
                     f"{hashlib.md5(ups).hexdigest()}) != committed "
                     f"({len(want)} B, md5 {hashlib.md5(want).hexdigest()}) — "
                     "handlers.c and dist/SLink-RR.ups are out of sync; rebuild and commit")
        print(f"\nCHECK OK. dist/SLink-RR.ups reproduces from source "
              f"(patched md5 {hashlib.md5(patched).hexdigest()})")
        return 0
    ips_path = os.path.join(DIST, "SLink-RR.ips")
    try:
        ips = make_ups.ips_create(clean, patched)
        assert hashlib.md5(make_ups.ips_apply(clean, ips)).hexdigest() == hashlib.md5(patched).hexdigest()
        open(ips_path, "wb").write(ips)
        print(f"      SLink-RR.ips ({len(ips)} B) round-trip OK")
    except ValueError as e:
        # The bundled RR4.1_Custom Battle Calc code lives above 16 MB, which IPS's 24-bit
        # offsets cannot reach. Drop any stale IPS so dist/ never ships an inconsistent one.
        if os.path.exists(ips_path):
            os.remove(ips_path)
            print(f"      IPS removed (stale): {e}")
        else:
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
