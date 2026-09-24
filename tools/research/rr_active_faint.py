"""C5-RR-ACTIVE-FAINT-SCOPE: byte facts behind docs/gen3/research/rr_active_faint_parity_scope_2026-09-23.md.

Static, no emulator.  Reuses rr_battle_tuple.py (ldr/detour decoders) and rr_save_callers.py (ROM
pins, FR .sym, BL/LDR census).  Asserts, on BOTH RR artifacts (clean 964f951a, companion ea5352f8),
every byte fact the RR port of mechanism P rests on: where CFRU runs the end-of-turn Perish KO and
what it reads, the struct layout that follows from those instructions, the script and opcode
handlers the KO runs, the action-13 dispatch, and the controller hand-off (the value written, the
engine code that consumes it, and the census of every pointer that can route input back to the
CFRU action-menu body that owns the L-throw RemoveBagItem call).

    python tools/research/rr_active_faint.py             # facts, both RR artifacts
    python tools/research/rr_active_faint.py --selftest  # known-positive / known-negative controls
    python tools/research/rr_save_callers.py --rom clean --disasm 90923c8:0x74   # any listing cited
"""
from __future__ import annotations

import struct
import sys

import rr_battle_tuple as rbt
import rr_save_callers as rsc

hw = lambda rom, a: struct.unpack_from("<H", rom, a - rsc.BASE)[0]  # noqa: E731

FR_IDENTICAL = (
    "BattleScriptExecute", "HandleAction_NothingIsFainted", "sTurnActionsFuncsTable",
    "PlayerHandleLinkStandbyMsg", "sPlayerBufferCommands", "EndBounceEffect",
    "Cmd_printstring", "Cmd_orword", "Cmd_end2", "Cmd_dofaintanimation", "AdjustFriendshipOnBattleFaint",
)
DETOURS = {
    0x08018C98: 0x090936CD,  # HandleWishPerishSongOnTurnEnd -> CFRU body with no Perish code
    0x08018258: 0x090910B5,  # DoBattlerEndTurnEffects -> CFRU end-turn state machine (Perish = state 34)
    0x080155C8: 0x0906F52D,  # RunTurnActionsFunctions -> CFRU (still indexes FR sTurnActionsFuncsTable)
    0x080146AC: 0x09042EED,  # HTAS case-1 default tail (action > 12) -> CFRU forfeit check
}
LDRS = {
    0x090923CA: 0x02023DFC,  # case 34: gStatuses3
    0x090923E0: 0x02023BE4,  # case 34: gBattleMons (hp at +0x28, stride 0x58)
    0x09092402: 0x02023E0C,  # case 34: gDisableStructs
    0x09092412: 0x02023D74,  # case 34: gBattlescriptCurrInstr
    0x0909241C: 0x02023D50,  # case 34: gBattleMoveDamage = hp
    0x09092420: 0x081D8D33,  # case 34, timer 0: BattleScript_PerishSongTakesLife (FR bytes)
    0x09092438: 0x081D8D4E,  # case 34, timer > 0: BattleScript_PerishSongCountGoesDown
    0x08015C7E: 0x0903EF20,  # RunBattleScriptCommands: RR's replacement opcode table
    0x0906F964: 0x08250038,  # CFRU RunTurnActionsFunctions: table[gCurrentActionFuncId]
    0x0801412E: 0x02023D7C,  # HTAS case-0 absent path: gChosenActionByBattler[b] = 13
    0x0909D8C0: 0x00100100,  # CFRU datahpupdate: IGNORE_SUBSTITUTE|PASSIVE_DAMAGE skips Disguise
    0x0909D9D4: 0x00100100,  # ... and Ice Face
    0x0909E644: 0x090031A0,  # CFRU tryfaintmon: faint script
    0x0909E6F0: 0x0802E229,  # CFRU tryfaintmon: AdjustFriendshipOnBattleFaint (player side)
    0x090A9EFE: 0x0802E33D,  # CFRU HandleInputChooseAction commits through PlayerBufferExecCompleted
    0x090AA114: 0x0809A1D9,  # ... and its L-throw calls RemoveBagItem first
}
# (address, halfword, meaning): the instructions that fix the layout the Lua plan writes
HALFWORDS = (
    (0x090923C8, 0x2720, "movs r7,#0x20        STATUS3_PERISH_SONG"),
    (0x090923D2, 0x4239, "tst r1,r7            gStatuses3[b] & 0x20"),
    (0x090923E4, 0x8D1C, "ldrh r4,[r3,#0x28]   gBattleMons[b].hp (skip if 0)"),
    (0x090923F4, 0x3BFC, "subs r3,#0xfc        r3 = 1"),
    (0x090923FC, 0x331B, "adds r3,#0x1b        r3 = 0x1C = sizeof DisableStruct"),
    (0x09092406, 0x3208, "adds r2,#8"),
    (0x09092408, 0x79D3, "ldrb r3,[r2,#7]      perishSongTimer byte at +0x0F"),
    (0x0909240A, 0x071B, "lsls r3,r3,#0x1c"),
    (0x0909240C, 0x0F1B, "lsrs r3,r3,#0x1c     low nibble; Z = (timer == 0)"),
    (0x09092414, 0xD109, "bne -> decrement      timer != 0"),
    (0x09092418, 0x43B9, "bics r1,r7           clear the Perish bit, then KO"),
    (0x08014132, 0x210D, "movs r1,#0xd         B_ACTION_NOTHING_FAINTED"),
    (0x0909DC10, 0x8513, "strh r3,[r2,#0x28]   datahpupdate: hp = 0 when damage >= hp"),
    (0x0909E6DA, 0x2380, "movs r3,#0x80"),
    (0x0909E6DE, 0x03DB, "lsls r3,r3,#0xf      HITMARKER_PLAYER_FAINTED 0x400000"),
)
# printstring 0x97; waitmessage 0x40; orword gHitMarker |= 0x00100100; healthbarupdate,
# datahpupdate, tryfaintmon (BS_ATTACKER); end2
PERISH_TAKES_LIFE = bytes.fromhex("109700 124000 35d03d020200011000 0b01 0c01 19010000000000 3e".replace(" ", ""))
FAINT_SCRIPT_HEAD = bytes.fromhex("5601391000 1a01 101c00 1b01".replace(" ", ""))  # cry, pause, anim, "fainted!", clear
# every literal that can put an action-menu controller (or its draw step) into a slot
PTR_CENSUS = {
    0x0802E438: [0x08032BB6, 0x09068D6C, 0x09069832],                     # store (AfterDma3) + 2 compares
    0x090A9EA0: [0x0802E438, 0x09068A24, 0x09068D72, 0x09069838, 0x090A9E76],  # detour, pool data, 2 cmps, sub-UI store
    0x090A9E40: [0x090AA16E],                                             # sub-UI: stored only from inside the body
    0x08032B94: [0x08032BE0, 0x09068D84, 0x09069864, 0x090AB096],         # dead FR body, 2 cmps, CFRU ChooseAction
}
COMPANION_ONLY = (0x08379000, 0x08380000)  # the companion's own FORCE_MOVE gate reads these pointers
HTAS_CASE3 = (0x08014AA0, 0x08014B44)


def facts(r: rsc.Rom, fr: bytes) -> list[tuple[str, bool]]:
    rom = r.rom
    out = [(f"FR-identical {n}", rbt.body_same(rom, fr, n)) for n in FR_IDENTICAL]
    out += [(f"detour {a:#010x} -> {t:#010x}", rbt.detour(rom, a) == t) for a, t in DETOURS.items()]
    out += [(f"ldr {a:#010x} loads {v:#010x}", rbt.ldr_value(rom, a) == v) for a, v in LDRS.items()]
    out += [(f"{a:#010x} == {h:#06x} {m}", hw(rom, a) == h) for a, h, m in HALFWORDS]
    bls = dict(zip(r.bl_site.tolist(), r.bl_tgt.tolist(), strict=True))
    out.append(("BattleTurnPassed BL DoBattlerEndTurnEffects @0x08013BF8, BL HandleFaintedMonActions @0x08013C04",
                bls.get(0x08013BF8) == 0x08018258 and bls.get(0x08013C04) == 0x08018F90))
    # CFRU end-turn: `bl case_uhi` at 0x09091108, table at 0x0909110C indexed by state-1; state 34 -> 0x090923C8
    tgt = 0x0909110C + 2 * hw(rom, 0x0909110C + 2 * 33)
    out.append(("end-turn state 34 dispatches to 0x090923C8", bls.get(0x09091108) == 0x090003D6 and tgt == 0x090923C8))
    o = 0x081D8D33 - rsc.BASE
    out.append(("BattleScript_PerishSongTakesLife bytes == FR", rom[o:o + 27] == fr[o:o + 27] == PERISH_TAKES_LIFE))
    o = 0x090031A0 - rsc.BASE
    out.append(("CFRU faint script head", rom[o:o + len(FAINT_SCRIPT_HEAD)] == FAINT_SCRIPT_HEAD))
    tab = lambda op: struct.unpack_from("<I", rom, 0x0903EF20 - rsc.BASE + 4 * op)[0]  # noqa: E731
    out.append(("opcode table: printstring/orword/end2 FR, datahpupdate/tryfaintmon CFRU",
                (tab(0x10), tab(0x35), tab(0x3E), tab(0x0C), tab(0x19))
                == (0x0801FD51, 0x08022B1D, 0x08022CED, 0x0909D7BD, 0x0909E5BD)))
    out.append(("sTurnActionsFuncsTable[13] == HandleAction_NothingIsFainted",
                struct.unpack_from("<I", rom, 0x08250038 + 4 * 13 - rsc.BASE)[0] == 0x08016D3D))
    out.append(("sPlayerBufferCommands[0x35 LINKSTANDBYMSG] == PlayerHandleLinkStandbyMsg",
                struct.unpack_from("<I", rom, 0x0825089C + 4 * 0x35 - rsc.BASE)[0] == 0x080339B5))
    a, b = HTAS_CASE3
    out.append(("HTAS case 3 (standby) body == FR", rom[a - rsc.BASE:b - rsc.BASE] == fr[a - rsc.BASE:b - rsc.BASE]))
    for v, want in PTR_CENSUS.items():
        got = sorted(s for k, s, _ in r.refs(v) if k == "LDR" and not COMPANION_ONLY[0] <= s < COMPANION_ONLY[1])
        out.append((f"LDR sites of {v | 1:#010x} == {[hex(x) for x in want]}", got == want))
    return out


def selftest() -> None:
    fr = rsc.load("fr")
    # known negative: FR's HandleWishPerishSongOnTurnEnd is not detoured, and runs Perish itself
    assert rbt.detour(fr, 0x08018C98) is None
    assert rbt.ldr_value(fr, 0x08018F0E) == 0x081D8D33           # FR's own Perish pool (known positive)
    # known negative for the halfword pins: the Perish mask instruction is not at a neighbouring slot
    assert hw(rsc.load("clean"), 0x090923CA) != 0x2720
    # known positive for the census: FR stores AfterDma3's pointer only from PlayerHandleChooseAction
    r = rsc.Rom(fr, None, rsc.parse_sym())
    assert sorted(s for k, s, _ in r.refs(0x08032B94) if k == "LDR") == [0x08032BE0]
    print("selftest ok")


def main() -> int:
    names, _, sizes = rsc.parse_sym()
    rbt.SYM.update({n: (a, sizes[a]) for a, n in names.items()})
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
