#!/usr/bin/env python3
"""Locate DoInGameTradeScene on the RR ROM by its call signature.

FR src/trade_scene.c:2774:
    void DoInGameTradeScene(void) {
        LockPlayerFieldControls();
        CreateTask(Task_InGameTrade, 10);          // bl CreateTask (0x807741C), r1 == 10
        BeginNormalPaletteFade(...,16, RGB_BLACK); // bl BeginNormalPaletteFade (0x8070588)
        HelpSystem_Disable();
    }
So it's a tiny function with `bl CreateTask` shortly followed by `bl BeginNormalPaletteFade`. Scan the
ROM (Thumb) for that pairing, then walk back to the function prologue (push {..,lr}) = the entry to
callnative. Cross-checked: Task_InGameTrade's address is the literal loaded just before the CreateTask
call (its own literal pool then points at CB2_InitInGameTrade).
"""
import sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

ROM_BASE = 0x08000000
CREATE_TASK = 0x0807741C
BEGIN_FADE  = 0x08070588

def main():
    rom = sys.argv[1]
    with open(rom, "rb") as f:
        data = f.read()
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = False
    # Brute-force EVERY even offset (Thumb BL is a 4-byte pair; linear disasm desyncs on data).
    start, end = 0x000000, 0x900000
    bls = {}   # addr -> target  (only CreateTask / BeginNormalPaletteFade BLs)
    targets = (CREATE_TASK, BEGIN_FADE)
    for off in range(start, end, 2):
        insn = next(md.disasm(data[off:off + 4], ROM_BASE + off, 1), None)
        if insn is None or insn.mnemonic != "bl":
            continue
        try:
            tgt = int(insn.op_str.lstrip("#"), 0)
        except ValueError:
            continue
        if tgt in targets:
            bls[insn.address] = tgt
    # Find a CreateTask BL followed within 24 bytes by a BeginNormalPaletteFade BL.
    ct = sorted(a for a, t in bls.items() if t == CREATE_TASK)
    bf = set(a for a, t in bls.items() if t == BEGIN_FADE)
    hits = []
    for a in ct:
        for d in range(4, 28, 2):
            if (a + d) in bf:
                hits.append((a, a + d))
                break
    print(f"{rom}: {len(ct)} CreateTask BLs, {len(bf)} BeginNormalPaletteFade BLs, {len(hits)} paired")
    for ct_addr, bf_addr in hits:
        # walk back up to ~0x40 bytes to the prologue `push {..., lr}` (Thumb: B5 xx)
        entry = None
        for back in range(0, 0x44, 2):
            off = ct_addr - back - ROM_BASE
            hw = data[off] | (data[off + 1] << 8)
            if (hw & 0xFF00) == 0xB500:   # push {..., lr}
                entry = ct_addr - back
        print(f"  pair: CreateTask@0x{ct_addr:08X}  Fade@0x{bf_addr:08X}  entry~0x{(entry or 0):08X}")

if __name__ == "__main__":
    main()
