# RR harness symbols: FR referrer retention (G5-RR-BATTERY-2, 2026-09-24)

Evidence for the `radical_red` values in `lua/tests/gen3_title_syms.lua` whose `rr_source` cites
this note. Those values are the test harness's own reads (the duo carrier
`lua/tests/duo/duo_gen3_main.lua` and the scripted helpers `lua/tests/gen3_scripted_play.lua`). The
product client does not use them.

## Method

Radical Red has no pret `.sym`. RR is FireRed with CFRU patched in, so a FireRed address is carried
over only on the following evidence:

- **Every FR literal-pool word holding the value is still there.** These are the words a code site
  loads to reach the address. Each must be at the same ROM address, with the same value, in the RR
  artifact. RR code that keeps all of FireRed's uses of an address is using that address for the
  same thing. CFRU may add referrers of its own; the "RR refs" column counts them. None are lost.
- **Code symbols also report body retention.** This is how many leading bytes of the FR function
  body are byte-identical in RR. A `0/n` or short prefix is a CFRU detour stub at the entry. The
  task pointer the engine stores and compares, the FR address with the Thumb bit, is still the one
  every kept FR site holds.

Inputs are pinned by sha1 and checked first:

- FR 1.0: `41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc`;
- the clean RR 4.1 dump: `964f951a0fdaf209e4ea1344883ef0d557bb3a80`;
- the shipped companion `patch/build/slink_RR.gba`: `ea5352f8a3b9073f8ae20870ad12857925d442cd`.

Function sizes come from `data/gen3/pret/pokefirered.sym`.

Derivation: `python tools/research/rr_harness_syms.py --check`. It exits 1 if any cited entry has
an FR referrer missing in either artifact, has no FR referrer at all, or has an RR value that
differs from FR's. The same rule runs as a unit, `tests/unit/test_e2e_duo_gen3.py`, whenever the
dumps are present.

**Not covered here.** The hand-off pair `PlayerBufferExecCompleted` / `PlayerBufferRunCommand` has
no FR literal to keep, because FR reaches ExecCompleted with `bl`. Its RR proof is the CFRU action
menu's pool word `LDR@0x090A9EFE = 0x0802E33D` and the ExecCompleted hook `0x0904459A`, which
stores `0x0802E3B5`. See `docs/gen3/research/rr_active_faint_parity_scope_2026-09-23.md` §3.2; the
title_syms entries cite that document.

## Additional pins (re-checked by the unit on both artifacts)

- **CB2_UpdatePartyMenu.**
  - Its 0x1A-byte body is identical in RR and FR.
  - Its only referrers are 0x0811EE28 and 0x0811EE70, the party-menu init, at the same addresses in both.
- **Task bodies:**
  - Task_ReturnToChooseMonAfterText is identical.
  - Task_HandleSelectionMenuInput's first 188 bytes are identical.
  - Task_HandleChooseMonInput starts with the CFRU detour stub `00 49 08 47`.
- **gPartyMenu's slotId field (+9).**
  - The FR-identical party-menu region keeps FR's 28 `ldr rd,=gPartyMenu; ldrb rX,[rd,#9]` sites.
  - CFRU's own party code (0x090B0000-0x090B7000) adds 13 more, for example at 0x090B3360.
- **gActiveBattler.** CFRU's action menu loads it: the pool word at 0x090AA178 = 0x02023BC4.
- **HandleInputChooseMove.**
  - FR's four referrers are kept: 0x0802E79C, 0x0802F398, 0x0802F3FC, and HandleChooseMoveAfterDma3's pool at 0x08032C8C.
  - The body starts `00 48 00 47` and branches to CFRU at 0x090AB8B9.
- **The companion's extra referrers.** Its own code adds exactly these, beyond the clean dump:
  - 0x0837A298, holding Task_HandleChooseMonInput;
  - 0x08378F44 and 0x09360318, holding gMoveSelectionCursor;
  - 0x0837992C, holding HandleInputChooseMove.

## The PC entries

`docs/gen3/research/rr_pc_menu.md:65` listed sCursorArea, sCursorPosition, sDepositBoxId and gStorage
as "candidate RR instrumentation, not fully rebound". The retention census below closes that. All 33
/ 45 / 4 / 339 FR code sites that load them are unchanged in RR: the storage UI that reads them is
FR's. CFRU replaces the box backend (25 compressed boxes), but that is a different set of addresses.

## gSpecialVar_Result on RR (G5-RR-LAST)

The live PC-exit lines read `result=0` at every step, including just after B on the owner list.
That raised the question of whether the address is wrong. It is not:

- **The write site is FR's, in both RR artifacts.** Task_MultichoiceMenu_HandleInput's cancel
  path at 0x0809CD18 is `ldr r1,=0x020370D0; movs r0,#0x7f; strh r0,[r1]`. The row path at
  0x0809CD28 stores through the same literal. The 176-byte body is identical in the clean dump and
  in the companion.
- **The exit path is FR's.**
  - EventScript_PC, PCMainMenu, ChoosePCMenu and TurnOffPC at 0x081A6955.. are byte-identical.
  - gScriptCmdTable (0x0815F9B4) has the same entries for every opcode they use (goto, goto_if,
    setvar, switch/case, special, playse, releaseall, end). Only `message` (0x67) differs, and it is
    not on the cancel path.
  - The two turn-off specials, gSpecials 0xD7 (AnimatePcTurnOff) and 0x190 (SetHelpContextForMap),
    point at identical FR bodies.
- **`result=0` during storage is expected.** That value is the owner-list row the PC was entered
  through (0 = the storage PC).
- **After the cancel, 127 is never observed.** The helper latches the variable at every frame end
  from the B onward, and the first sample already reads 0.
  - FR runs see 127, with the same code and the same read.
  - So on RR something writes the variable again within the frame the cancel lands in.
  - RR carries 92 more code referrers of 0x020370D0 than FR. 75 of them are CFRU store sites,
    several of which store 0. For example: 0x0907CE16 and 0x090B21AE are one-line `strh 0`
    returns; 0x090B2382/0x090B23DE clear it before a call.
  - Which one runs on this frame is **OPEN**. It needs a live write watch on 0x020370D0.
- **Consequence.** The helper keeps FR/LG's strict 127 witness. On radical_red it accepts "the owner
  list closed and no PC task took over" (`owner_list_closed` in lua/tests/gen3_scripted_play.lua).
  The field-terminal wait after it proves the PC turned off.

## Census

# RR artifact 964f951a0fdaf209e4ea1344883ef0d557bb3a80 (Pokemon - Radical Red.gba); FR 41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc
| entry | symbol | value | FR refs | RR refs | all FR sites kept | FR body kept |
|---|---|---|---|---|---|---|
| ACTIVE_BATTLER_ADDR | gActiveBattler | 0x02023BC4 | 955 | 1171 | yes | - |
| BAG_MENU_STATE_ADDR | gBagMenuState | 0x0203ACFC | 54 | 63 | yes | - |
| CB2_BAG_MENU_RUN | CB2_BagMenuRun | 0x08107EE1 | 2 | 2 | yes | 26/26 |
| CB2_UPDATE_PARTY_MENU | CB2_UpdatePartyMenu | 0x0811EBA1 | 2 | 2 | yes | 26/26 |
| HANDLE_INPUT_CHOOSE_MOVE | HandleInputChooseMove | 0x0802EA11 | 4 | 8 | yes | 0/972 |
| MOVE_CURSOR_ADDR | gMoveSelectionCursor | 0x02023FFC | 35 | 51 | yes | - |
| PARTY_MENU_ADDR | gPartyMenu | 0x0203B0A0 | 153 | 179 | yes | - |
| PC_CURSOR_AREA | sCursorArea | 0x02039820 | 33 | 33 | yes | - |
| PC_CURSOR_POS | sCursorPosition | 0x02039821 | 45 | 46 | yes | - |
| PC_DEPOSIT_BOX_ID | sDepositBoxId | 0x020397B6 | 4 | 4 | yes | - |
| PC_MENU_BASE | sMenu | 0x0203ADE4 | 19 | 20 | yes | - |
| PC_MULTICHOICE | Task_MultichoiceMenu_HandleInput | 0x0809CC99 | 4 | 5 | yes | 176/176 |
| PC_ON_B_PRESSED | Task_OnBPressed | 0x0808ECE5 | 1 | 2 | yes | 112/308 |
| PC_ON_SELECTED | Task_OnSelectedMon | 0x0808D879 | 1 | 1 | yes | 188/796 |
| PC_RELEASE_MON | Task_ReleaseMon | 0x0808DECD | 1 | 1 | yes | 496/496 |
| PC_RESULT | gSpecialVar_Result | 0x020370D0 | 156 | 248 | yes | - |
| PC_STORAGE_MAIN | Task_PokeStorageMain | 0x0808D2BD | 32 | 32 | yes | 252/1280 |
| PC_STORAGE_PTR | gStorage | 0x020397B0 | 339 | 342 | yes | - |
| SPECIAL_VAR_ITEM_ID_ADDR | gSpecialVar_ItemId | 0x0203AD30 | 110 | 130 | yes | - |
| TASK_ANIMATE_WIN0V | Task_AnimateWin0v | 0x08108CFD | 5 | 5 | yes | 100/100 |
| TASK_BAG_MENU_HANDLE_INPUT | Task_BagMenu_HandleInput | 0x08108F0D | 4 | 4 | yes | 170/464 |
| TASK_CHOOSE_MON | Task_HandleChooseMonInput | 0x0811FB29 | 28 | 29 | yes | 0/124 |
| TASK_RETURN_AFTER_TEXT | Task_ReturnToChooseMonAfterText | 0x081203B9 | 12 | 13 | yes | 104/104 |
| TASK_SELECTION_POPUP | Task_HandleSelectionMenuInput | 0x08122C5D | 4 | 4 | yes | 188/240 |
| TASK_YES_NO_MENU | Task_YesNoMenu_HandleInput | 0x0809CE55 | 1 | 1 | yes | 116/116 |

# RR artifact ea5352f8a3b9073f8ae20870ad12857925d442cd (patch/build/slink_RR.gba); FR 41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc
| entry | symbol | value | FR refs | RR refs | all FR sites kept | FR body kept |
|---|---|---|---|---|---|---|
| ACTIVE_BATTLER_ADDR | gActiveBattler | 0x02023BC4 | 955 | 1173 | yes | - |
| BAG_MENU_STATE_ADDR | gBagMenuState | 0x0203ACFC | 54 | 63 | yes | - |
| CB2_BAG_MENU_RUN | CB2_BagMenuRun | 0x08107EE1 | 2 | 2 | yes | 26/26 |
| CB2_UPDATE_PARTY_MENU | CB2_UpdatePartyMenu | 0x0811EBA1 | 2 | 2 | yes | 26/26 |
| HANDLE_INPUT_CHOOSE_MOVE | HandleInputChooseMove | 0x0802EA11 | 4 | 9 | yes | 0/972 |
| MOVE_CURSOR_ADDR | gMoveSelectionCursor | 0x02023FFC | 35 | 53 | yes | - |
| PARTY_MENU_ADDR | gPartyMenu | 0x0203B0A0 | 153 | 179 | yes | - |
| PC_CURSOR_AREA | sCursorArea | 0x02039820 | 33 | 33 | yes | - |
| PC_CURSOR_POS | sCursorPosition | 0x02039821 | 45 | 46 | yes | - |
| PC_DEPOSIT_BOX_ID | sDepositBoxId | 0x020397B6 | 4 | 4 | yes | - |
| PC_MENU_BASE | sMenu | 0x0203ADE4 | 19 | 20 | yes | - |
| PC_MULTICHOICE | Task_MultichoiceMenu_HandleInput | 0x0809CC99 | 4 | 7 | yes | 176/176 |
| PC_ON_B_PRESSED | Task_OnBPressed | 0x0808ECE5 | 1 | 2 | yes | 112/308 |
| PC_ON_SELECTED | Task_OnSelectedMon | 0x0808D879 | 1 | 1 | yes | 188/796 |
| PC_RELEASE_MON | Task_ReleaseMon | 0x0808DECD | 1 | 1 | yes | 496/496 |
| PC_RESULT | gSpecialVar_Result | 0x020370D0 | 156 | 249 | yes | - |
| PC_STORAGE_MAIN | Task_PokeStorageMain | 0x0808D2BD | 32 | 32 | yes | 252/1280 |
| PC_STORAGE_PTR | gStorage | 0x020397B0 | 339 | 342 | yes | - |
| SPECIAL_VAR_ITEM_ID_ADDR | gSpecialVar_ItemId | 0x0203AD30 | 110 | 130 | yes | - |
| TASK_ANIMATE_WIN0V | Task_AnimateWin0v | 0x08108CFD | 5 | 5 | yes | 100/100 |
| TASK_BAG_MENU_HANDLE_INPUT | Task_BagMenu_HandleInput | 0x08108F0D | 4 | 4 | yes | 170/464 |
| TASK_CHOOSE_MON | Task_HandleChooseMonInput | 0x0811FB29 | 28 | 30 | yes | 0/124 |
| TASK_RETURN_AFTER_TEXT | Task_ReturnToChooseMonAfterText | 0x081203B9 | 12 | 13 | yes | 104/104 |
| TASK_SELECTION_POPUP | Task_HandleSelectionMenuInput | 0x08122C5D | 4 | 4 | yes | 188/240 |
| TASK_YES_NO_MENU | Task_YesNoMenu_HandleInput | 0x0809CE55 | 1 | 1 | yes | 116/116 |

