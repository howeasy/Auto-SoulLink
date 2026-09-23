"""C5-RR-BW: byte facts behind docs/gen3/research/rr_battle_tuple_2026-09-23.md.

Static, no emulator.  Reuses tools/research/rr_save_callers.py (ROM pins, FR .sym, the Thumb
BL/LDR decoder) and asserts, on BOTH RR artifacts (clean 964f951a, companion b7d1e075), every
byte fact the frame-phase table cites: which FR bodies RR keeps verbatim, where CFRU detours the
player controller and the battle lifecycle, the literal-pool words that give the parked menu's
controller pointer, and the census of stores that can put HandleTurnActionSelectionState into
gBattleMainFunc.

    python tools/research/rr_battle_tuple.py             # facts, both RR artifacts
    python tools/research/rr_battle_tuple.py --selftest  # known-positive / known-negative controls
    python tools/research/rr_save_callers.py --rom clean --disasm 90a9ea0:0x2d8   # any listing cited
"""
from __future__ import annotations

import struct
import sys

import rr_save_callers as rsc

SYM = {}  # FR name -> (address, size), filled by main()

# FR bodies RR must keep byte-for-byte (so pret describes them).
FR_IDENTICAL = (
    "BattleMainCB1",                  # main func first, then every controller, one frame
    "MarkBattlerForControllerExec",   # the only non-link setter of a battler's exec bit
    "PlayerBufferRunCommand",         # dispatches CHOOSE_ACTION while the bit is set
    "HandleChooseActionAfterDma3",    # stores the parked controller pointer
    "BtlController_EmitTwoReturnValues",
    "OpponentHandleChooseAction", "OpponentHandleLinkStandbyMsg", "OpponentBufferExecCompleted",
    "SetBattleEndCallbacks", "BattleScriptExecute", "DoSoftReset",
)
# entry/interior detours `ldr rX,[pc,#imm]; bx rX` -> CFRU target (Thumb)
DETOURS = {
    0x08032BD4: 0x090AAF39,  # PlayerHandleChooseAction
    0x0802E438: 0x090A9EA1,  # HandleInputChooseAction (player)
    0x0802E34A: 0x0904459B,  # PlayerBufferExecCompleted, after loading &gBattlerControllerFuncs[b]
    0x0800D2CC: 0x09042B99,  # SetUpBattleVars, after gBattleMainFunc/controllers/exec flags reset
    0x0801385C: 0x0906FF21,  # TryDoEventsBeforeFirstTurn (whole body)
    0x08013D14: 0x09042D41,  # BattleTurnPassed tail (stores HTAS, then Random)
    0x080159DC: 0x09002735,  # HandleEndTurn_FinishBattle (stores FreeResetData_...)
    0x080140C8: 0x09042BBD,  # HTAS case 0 gate
    0x080142D8: 0x09042E09,  # HTAS case 1 USE_MOVE
    0x080143D4: 0x09042305,  # HTAS case 1 USE_ITEM gate
    0x08014450: 0x09042C85,  # HTAS case 1 SWITCH
    0x080146AC: 0x09042EED,  # HTAS case 1 common tail
    0x080148C0: 0x090441E9,  # HTAS case 2
}
# `ldr rX,[pc,#imm]` sites -> the literal they load (the report cites each one)
LDRS = {
    0x08032BB6: 0x0802E439,  # HandleChooseActionAfterDma3: controller[b] = HandleInputChooseAction
    0x090A9E76: 0x090A9EA1,  # CFRU L-button sub-UI 0x090A9E40 returns to the CFRU body directly
    0x090AB096: 0x08032B95,  # CFRU PlayerHandleChooseAction (singles): controller = AfterDma3
    0x090445B2: 0x090ACD8D,  # ExecCompleted hook: CFRU flag-bit-24 controller
    0x090445B6: 0x0802E3B5,  # ExecCompleted hook: controller = PlayerBufferRunCommand
    0x090445BC: 0x0802E34F,  # ExecCompleted hook: jump back to the FR tail (link test, then BICS)
    0x0900273A: 0x08015A31,  # FinishBattle hook: gBattleMainFunc = FreeResetData_...
    0x09070628: 0x08014041,  # CFRU TryDoEventsBeforeFirstTurn: gBattleMainFunc = HTAS
}
HTAS = 0x08014041
EXEC_FLAGS = 0x02023BC8
EXEC_COMPLETED = 0x0802E33D
CFRU_HIA = (0x090A9EA0, 0x090AA176)  # CFRU HandleInputChooseAction body (ends at the pool)


def word(rom: bytes, a: int) -> int:
    return struct.unpack_from("<I", rom, a - rsc.BASE)[0]


def ldr_value(rom: bytes, site: int) -> int | None:
    """Literal loaded by the Thumb `ldr rX,[pc,#imm]` at site, else None."""
    hw = struct.unpack_from("<H", rom, site - rsc.BASE)[0]
    if hw & 0xF800 != 0x4800:
        return None
    return word(rom, ((site + 4) & ~3) + (hw & 0xFF) * 4)


def detour(rom: bytes, site: int) -> int | None:
    """Target of `ldr rX,[pc,#imm]; bx rX` at site, else None."""
    hw0, hw1 = struct.unpack_from("<HH", rom, site - rsc.BASE)
    if hw1 != 0x4700 | ((hw0 >> 8) & 7) << 3:
        return None
    return ldr_value(rom, site)


def body_same(rom: bytes, fr: bytes, name: str) -> bool:
    a, n = SYM[name]
    o = a - rsc.BASE
    return rom[o:o + n] == fr[o:o + n]


def facts(r: rsc.Rom, fr: bytes) -> list[tuple[str, bool]]:
    rom = r.rom
    out = [(f"FR-identical {n}", body_same(rom, fr, n)) for n in FR_IDENTICAL]
    out += [(f"detour {a:#010x} -> {t:#010x}", detour(rom, a) == t) for a, t in DETOURS.items()]
    out += [(f"ldr {a:#010x} loads {v:#010x}", ldr_value(rom, a) == v) for a, v in LDRS.items()]
    # HTAS: comm[b]==0 -> case 0 (0x080140B8), comm[b]==1 -> the exec poll (0x080141DC); case 0
    # emits CHOOSE_ACTION then runs the shared tail Mark(b) + comm[b]++ (so the parked comm is 1)
    out.append(("HTAS jump table [0]=0x080140B8 [1]=0x080141DC",
                (word(rom, 0x0801409C), word(rom, 0x080140A0)) == (0x080140B8, 0x080141DC)))
    bls = {s: t for s, t in zip(r.bl_site.tolist(), r.bl_tgt.tolist())}
    out.append(("case 0: BL EmitChooseAction @0x080141CC, BL Mark+comm++ tail @0x080141D0",
                bls.get(0x080141CC) == 0x0800E4D4 and bls.get(0x080141D0) == 0x08014B26))
    o = 0x08014B26 - rsc.BASE
    out.append(("Mark+comm++ tail 0x08014B26..0x08014B3A == FR", rom[o:o + 0x14] == fr[o:o + 0x14]))
    # the non-link exec clear PlayerBufferExecCompleted jumps back to is FR's BICS tail
    o = 0x0802E390 - rsc.BASE
    out.append(("FR BICS tail 0x0802E390..0x0802E3A2 kept", rom[o:o + 0x12] == fr[o:o + 0x12]))
    # every store of HTAS into gBattleMainFunc: the three LDR sites the report lists
    sites = sorted(s for k, s, _ in r.refs(HTAS & ~1) if k == "LDR")
    out.append(("HTAS LDR sites == {0x08013A66 (dead FR body), 0x08013CCC, 0x09070628}",
                sites == [0x08013A66, 0x08013CCC, 0x09070628]))
    # the CFRU input handler never names the exec word; it clears only through ExecCompleted
    lo, hi = CFRU_HIA

    def in_body(site: int) -> bool:
        return lo <= site < hi

    out.append(("CFRU HIA loads no &gBattleControllerExecFlags",
                not any(in_body(s) for k, s, _ in r.refs(EXEC_FLAGS, False) if k == "LDR")))
    out.append(("CFRU HIA loads PlayerBufferExecCompleted (the commit)",
                any(in_body(s) for k, s, _ in r.refs(EXEC_COMPLETED & ~1) if k == "LDR")))
    # who LDRs the parked-controller pointer below the companion arena: the AfterDma3 store + two
    # CFRU compare-only sprite callbacks (the companion adds its own reader at 0x08379870)
    hia = sorted(s for k, s, _ in r.refs(0x0802E438) if k == "LDR" and not 0x08379000 <= s < 0x08380000)
    out.append(("0x0802E439 LDR sites == {AfterDma3 0x08032BB6, cmp 0x09068D6C, cmp 0x09069832}",
                hia == [0x08032BB6, 0x09068D6C, 0x09069832]))
    alt = sorted(s for k, s, _ in r.refs(0x090A9EA0) if k == "LDR")
    out.append(("0x090A9EA1 LDR sites == {detour, sub-UI store 0x090A9E76, cmps 0x09068D72/0x09069838,"
                " 0x09068A24 = pool data decoded as LDR}",
                alt == [0x0802E438, 0x09068A24, 0x09068D72, 0x09069838, 0x090A9E76]))
    return out


def selftest() -> None:
    fr = rsc.load("fr")
    r = rsc.Rom(fr, None, rsc.parse_sym())
    # known negative: FR's player HandleInputChooseAction is not detoured
    assert detour(fr, 0x0802E438) is None
    # known positive for the detour decoder: RR clean's HandleInputChooseAction is
    assert detour(rsc.load("clean"), 0x0802E438) == 0x090A9EA1
    # known positive: FR HandleInputChooseAction commits through a BL to PlayerBufferExecCompleted
    assert any(k == "BL" and 0x0802E438 <= s < 0x0802E63E for k, s, _ in r.refs(0x0802E33C))
    # known positive: FR's own HTAS stores are TryDoEventsBeforeFirstTurn + BattleTurnPassed
    assert sorted(s for k, s, _ in r.refs(0x08014040) if k == "LDR") == [0x08013A66, 0x08013CCC]
    print("selftest ok")


def main() -> int:
    names, _, sizes = rsc.parse_sym()
    SYM.update({n: (a, sizes[a]) for a, n in names.items()})
    if "--selftest" in sys.argv:
        selftest()
        return 0
    fr = rsc.load("fr")
    syms = rsc.parse_sym()
    bad = 0
    for kind in ("clean", "companion"):
        r = rsc.Rom(rsc.load(kind), fr, syms)
        for label, ok in facts(r, fr):
            bad += not ok
            print(f"{kind:9} {'PASS' if ok else 'FAIL'}  {label}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
