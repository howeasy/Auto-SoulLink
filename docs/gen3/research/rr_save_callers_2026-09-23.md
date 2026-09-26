# RR save-caller completeness, 2026-09-23 (card C5-RR-SAVECALLERS)

This is a static, bytes-only research card for the Gen 3 G5 gate. No emulator was run. It follows
`checkpoint_predicate_audit_2026-09-23.md` ("RR save path after the C4-SAVE change", commit 46549230)
and the G4 draft §5 row "The C4-SAVE checkpoint change on RR".

**Inputs**
- ROMs: RR clean `964f951a`, RR companion `b7d1e075`, FR `41cb23d8` (the vanilla control). The pins
  are the same as in `tools/gen_gen3_write_checkpoint.py`.
- Symbols: pret/pokefirered `c75f3523` (`data/gen3/pret/pokefirered.sym`, `.map`).
- SLink HEAD: `ef5a79fc`.
- Checkpoint: `data/games/gen3_rr/write_checkpoint.json` (`radical_red`), `lua/gen3/safety.lua`.

**Tool:** `tools/research/rr_save_callers.py`. It is new, depends only on numpy (capstone is used only for
`--disasm`), and has a `--selftest` with known-positive and known-negative controls.

Tags: **PROVEN** means read from the bytes, or from pret for a function whose body is byte-identical in
RR. **INFERRED** means reasoned, not read. **OPEN** means not settled.

## Answer to item (1)

Every flash write in both RR artifacts reaches the chip through the vanilla agb_flash function-pointer
variables. Every path from those variables up to a caller ends at one of 12 entry points. Each entry
point runs in a world that a named checkpoint clause refuses, with one exception:
`SaveBattleTowerProgress` (special 0xF0). No script invoking it was found, so it is INFERRED
unreachable. What remains OPEN is the limit of any static scan: a call whose target is built at run
time from something that is not a ROM literal, a table word, an ADR or a script pointer. Nothing in
either RR artifact suggests such a call exists, but only the G5 flash-write tripwire (last section)
can close it.

The companion (`b7d1e075`) produces the same caller tree and the same entry table as the clean ROM,
byte for byte (`diff` of the tool output is empty). The companion code does not reach any flash
writer. **PROVEN**

## 1. Primitive census: who can touch the chip (PROVEN unless noted)

| Check | Result |
|---|---|
| PC-relative literal loads of `ProgramFlashSector` `0x0300741C`, `ProgramFlashByte` `0x03007424`, `EraseFlashSector` `0x03007430`, `EraseFlashChip` `0x0300742C` | The FR set of loaders, plus **one** CFRU function: `0x090B8E08` loads `EraseFlashSector` (`LDR@0x090B8EA2`). There are no new loaders of `ProgramFlashSector` or `ProgramFlashByte`. `EraseFlashChip` is loaded only by `IdentifyFlash`. |
| Other words in `0x03007400-0x0300743F` in the RR-added space (`0x09169DC4`, `0x093D4E94`, `0x09470B0C`, `0x094719D8`, `0x094B0800`, `0x094BE1D8`, `0x0952A6E8`, `0x095BC480`, `0x095DA1A0`) | No PC-relative load reads any of them, so they are data. |
| `gFlash` word `0x094AEAE4` | No PC-relative load reads it, so it is data. |
| Command register `0x0E005555` (`--cmdreg`) | Loaded only by the vanilla driver (`SwitchFlashBank`, `ReadFlashId`, `WaitForFlashWrite_Common`, the `_MX` routines, `ProgramByte`). One raw word at `0x095636FC` is not PC-loaded, and it sits inside the LZ77 blob at `0x095636EC` (header `10 00 08 00`, pointed to by the graphics table word `0x097FC6A4`). |
| `FLASH_BASE 0x0E000000` built with no literal (`movs; lsls`, `--flashbase`) | This is the positive control: the FR driver builds the address this way in 9 functions, and the scan finds all of them. RR adds one site, `0x09554CC2`, which sits inside the LZ77 blob at `0x095549F0` (next blob at `0x09554D3C`, table words `0x097FC4CC` and `0x09813508`). The other hits (`CB_HandleTradeCanceled`, `PrintBattleRecords`, `PrintRecordsText`, `0x08701460`) are byte-identical to FR, and pret shows no flash access in them. |
| `0x0E00xxxx` values read by a PC-relative load in the RR-added space (`0x0901DCEC`, `0x0903A14E`, `0x090A651C`, and so on) | These are data decoded as instructions. For example, `0x090A651C` is itself the literal that `0x090A6510` loads. |
| `_MX` routines | They are reached only through the `sSetupInfos` / `lib_rodata` tables that `IdentifyFlash` copies into the pointer variables. The only direct call is `ProgramFlashSector_MX` calling `EraseFlashSector_MX`. |

## 2. The caller graph

`--entries` builds the BL-closure of the flash writers: every function that synchronously calls a
pointer-variable user. It then lists every non-BL reference into that closure. A non-BL reference is
an LDR'd Thumb pointer, a table word, an ADR or an unaligned (script) pointer. Each one is a task or
callback registration, a dispatch-table entry, or a CFRU `bl bx_rN` veneer call. These references are
the world boundaries.

- The RR closure has 45 functions. The FR closure has 44; the extra RR function is CFRU `0x090B8E08`.
- No ADR, unaligned pointer, or interior jump-back enters the closure other than the hooks listed below.
- The only interior references are the CFRU hooks' own jump-backs (for example `0x09042E30` into
  `task50_after_link_battle_save`). The other interior references are unreferenced data (checked:
  `0x09430C68`, `0x08A98BA8`, and BL decodes inside FR `.rodata`, which is byte-identical to FR).

CFRU edits inside the save stack (**PROVEN**, disassembly by `--disasm`):

| FR function | RR bytes | Effect |
|---|---|---|
| `HandleSavingData` `0x080DA248` | `ldr r1,=0x090B8E09; bx r1` at entry | The whole body is CFRU `0x090B8E08`: it calls `WriteSaveSectorOrSlot` and `HandleWriteSectorNBytes` through veneers, and calls `EraseFlashSector` directly. Its only reference is this detour, so its callers are exactly `TrySavingData` and `TryWipeDamagedSectors`. The FR body after the detour is dead. |
| `HandleWriteSector` `0x080D9870` | `ldr r2,=0x090B8CB5; bx r2` at entry | CFRU `0x090B8CB4` builds the sector and writes it through `TryWriteSector`, then writes the parasite/extension sectors 30/31 (buffers `0x0203C038`/`0x0203D028`) inside the same synchronous call. Its only reference is this detour. |
| `task50_after_link_battle_save` `0x0806FBB8` | case 1 (`0x0806FC80`): `SetContinueGameWarpStatusToDynamicWarp`, then `ldr r0,=0x09042E29; bx r0` | `0x09042E28` is `bl 0x090B8EF8`, then a jump back to `0x0806FCE6`. `0x090B8EF8` clears byte `0x0203E028`, calls `TrySavingData(0)` and `ClearContinueGameWarpStatus2`, and returns 3, so `data[0] = 3`. The FR case 2 (`WriteSaveBlock1Sector`) can no longer be reached, and `WriteSaveBlock2` has no caller at all on RR. |
| `Task_Hof_InitTeamSaveData` (detoured to `0x090B9122`) | `0x090B91B4`: `str =Task_Hof_TrySaveData, [gTasks + id*0x28]` | The HoF save is still `Task_Hof_TrySaveData`, and it still runs as a task. |
| `CallCallbacks` `0x08000510` | `RunSaveFailedScreen` gate kept at `0x08000512-18`; help-system call NOPed on the clean ROM, companion frame hook at `0x0800051A` | Callbacks stay suspended while the save-failed screen runs. |

## 3. Caller table

Clause references:
- `wc`: `data/games/gen3_rr/write_checkpoint.json` `radical_red`.
- `S`: `lua/gen3/safety.lua`. Predicates are at `:92-99`, the CPU clause at `:102-107`, the task
  clause at `:108-120`.
- The task clause refuses any active task whose function is not one of the six in
  `wc.tasks.allowed_overworld_tasks`.
- `callback2` refuses unless `gMain.callback2 == CB2_Overworld|1` (`0x080565B5`).
- `script_context_status` refuses unless `sGlobalScriptContextStatus == 2` (`CONTEXT_SHUTDOWN`, pret
  `src/script.c:21-23`).

No row relies on the CPU clause. Its `pc_min..pc_max = 0..0x3FFF`, System-mode range covers every BIOS
SWI body, so it cannot by itself exclude a frame end inside a synchronous save.

"=FR" means the function's bytes are identical to FR in both RR artifacts, so the pret source applies.

| # | Entry into the closure (RR) | How it is reached | World at every frame end while it writes | Refusing clause | Tag |
|---|---|---|---|---|---|
| 1 | `SaveDialogCB_DoSave` (=FR). It is the only entry into `TrySavingData` from the START menu, through `sSaveDialogCB` (`LDR@0x0806F92C`). | START → SAVE. RR's action table word `0x09149014` is act[4].func = `StartMenuSaveCallback`, run by `Task_StartMenuHandleInput` → `StartCB_Save2` → `RunSaveDialogCB`. | `Task_StartMenuHandleInput` is active and the field is locked. | task, `field_controls_locked` | **PROVEN** (46549230 plus this card: there is no other entry) |
| 2 | Same callback, reached from `Field_AskSaveTheGame` (=FR; special 0x5D) and `CableClub_AskSaveTheGame` (=FR; special 0x23). | Script special, then `CreateTask(task50_save_game)`. | `task50_save_game` (=FR) is active until `RunSaveDialogCB` returns nonzero after the save. | task | **PROVEN** |
| 3 | `task50_after_link_battle_save` (RR-modified) ← `CB2_SetUpSaveAfterLinkBattle` (=FR). | After a Cable Club or Union Room link battle. | The task is active: `DestroyTask` runs only in case 4 (`0x0806FCBE`), after the save. `callback2 = CB2_WhileSavingAfterLinkBattle`. | task, `callback2` | **PROVEN** |
| 4 | `Task_LinkFullSave` (=FR). Registered by `task50_after_link_battle_save` case 5 (Union Room), `SavePokeJump`, `Cmd_SaveGame` (Berry Crush) and `Msg_SavingDontTurnOff` (Dodrio). | `CreateTask`. Every flash call is a BL inside the task body (`0x080DA712`, `0x080DA744`, `0x080DA782`). | The task is active on every step. Link minigames and link-battle `callback2` also apply. | task (also `callback2`) | **PROVEN** |
| 5 | `CB2_SaveAndEndTrade` (=FR) ← `CB2_TryLinkTradeEvolution` (=FR). | `SetMainCallback2`. Its writes are BLs inside it (`0x080541A0`, `0x080541E0`, `0x0805428A`). | `callback2 = CB2_SaveAndEndTrade`. | `callback2` | **PROVEN** |
| 6 | `Task_Hof_TrySaveData` (=FR), registered by CFRU `0x090B91B4` and by the FR `LDR@0x080F21F4`. | `EnterHallOfFame` (special 0x110) → HoF `callback2`. | The task is active during `TrySavingData`. Afterwards its function becomes `Task_Hof_DelayAfterSave`, which is also not allowed. | task | **PROVEN** |
| 7 | `ChatEntryRoutine_SaveAndExit` (=FR) ← `sChatEntryRoutines[9]`. The table's only reader is `Task_HandlePlayerInput` (=FR). | Union Room chat. | `Task_HandlePlayerInput` is active and `callback2 = CB2_UnionRoomChatMain`. | task, `callback2` | **PROVEN** |
| 8 | `Task_MysteryGift` (=FR) ← `CreateMysteryGiftTask` ← `CB2_InitMysteryGift` ← main menu. | Title/main menu. | The task is active and `callback2` is not overworld. | task | **PROVEN** |
| 9 | `Task_EReader` (=FR) → `TryWriteSpecialSaveSector` (RR-modified). `CB2_InitEReader` has **no reference** in FR or RR. | Unreachable. | Even if reached, the task would be active. | task | **PROVEN** |
| 10 | `CB2_LinkTest` (=FR). `LinkTestScreen` has **no reference**. | Unreachable debug screen. | `callback2 = CB2_LinkTest`. | `callback2` | **PROVEN** |
| 11 | `Task_HandleYesNoMenu` (=FR) → `ClearSaveData`. | Title screen clear-save (`CB2_SaveClearScreen_Init`). | The task is active and `callback2` is not overworld. | task | **PROVEN** |
| 12 | `SaveBattleTowerProgress` (=FR) ← `gSpecials[0xF0]` (`WORD@0x08160120`). RR still dispatches through the vanilla `gScriptCmdTable` / `gSpecials` (`ScrCmd_special` at `0x08069F06` loads `0x0815FD60`), and no second table references the function. | `special 0xF0` / `specialvar`. | The synchronous write runs while a global script is `CONTEXT_RUNNING`. See the residual below. | `script_context_status` | **INFERRED** unreachable (details below) |
| 13 | `RunSaveFailedScreen` (RR-modified) → `TryWipeDamagedSectors` → `WipeDamagedSectors` / `HandleSavingData`. It is called from `CallCallbacks`. | `DoSaveFailedScreen` (=FR) only sets `sIsInSaveFailedScreen`. Its callers are `TrySavingData` (rows 1-3, 6-8, 10, 12), `LinkFullSave_*` (rows 4, 5) and `WriteSaveBlock1Sector` (dead on RR). | While the screen runs, `callback1`/`callback2` are not called (RR `0x08000512-18`). `SaveCallbacks`/`RestoreCallbacks` touch only the VBlank/HBlank callbacks (pret `help_system_util.c:139-180`). The triggering world is therefore frozen: tasks, callback pointers, script status and lock keep their values. | Inherits the trigger's clause. | **PROVEN** for triggers in rows 1-11. The row-12 trigger is folded into row 12. |
| 14 | `AgbMain` → `CheckForFlashMemory` → `IdentifyFlash` (all =FR). | Boot, before the main loop. | This is not a data write: it reads the chip ID and fills the pointer variables. | `callback2` (not overworld at boot) | **PROVEN** |
| 15 | CFRU `0x090B8E08` (HandleSavingData body) and `0x090B8CB4` (HandleWriteSector body, sectors 30/31). | Only through the entry detours in §2. | These are internal to rows 1-13. | as the calling row | **PROVEN** |
| 16 | CFRU `0x090B8EF8` / hook `0x09042E28`. | Only from `task50_after_link_battle_save` case 1 (`LDR@0x0806FC84`). | Internal to row 3. | as row 3 | **PROVEN** |
| 17 | Dead writers: `WriteSaveBlock2` (no caller on RR), `ProgramFlashSectorAndVerifyNBytes` (no caller), the FR bodies after the two detours, and RR `task50` case 2. | None | n/a | n/a | **PROVEN** |
| 18 | Direct chip access outside agb_flash. | None (§1). | n/a | n/a | **PROVEN** |
| 19 | Calls through a target built at run time from something that is not a ROM literal, table word, ADR or script pointer (arithmetic on a register, a table decompressed or assembled in RAM). | Not modelled by any static scan. | Unknown | Unknown | **OPEN** |

**Counts:** 17 PROVEN, 1 INFERRED (row 12), 1 OPEN (row 19).

**Row 12 details**
- RR has five `25 F0 00` byte hits and six `26 .. .. F0 00` byte hits. Every one lies in high-entropy
  graphics data:
  - `0x09B9FAE5` is followed by opcode `0xED`, which is past the last script command `0xD5`.
  - `0x09CA7D6D` and `0x09E7ADDD` are followed by `12 21` and a non-ROM pointer `0xDBF2EED3`.
  - The `specialvar` hits name non-variables (`0xCE51`, `0xF001`, and so on).
  - FR's own three hits are FR graphics.
- If the special were reached, the synchronous write would be refused. But the save-failed freeze
  after it keeps whatever script state exists at the end of that frame. That state is not bounded
  here: a script that ended in the same frame would leave an overworld world. It stays OPEN if a
  script is ever found.
- `RunScriptImmediately` (=FR) runs outside the global status. Its map-load callers run under a
  non-overworld `callback2`. This is INFERRED and was not traced here.

## 4. Item (2) scope: RR's parked battle tuple

The RR battle clause set (`wc.battle.clauses`, `tools/gen_gen3_write_checkpoint.py:555-566`) is:

```
battle_main_func == 0x08014041
battle_comm_0    == 1
battle_exec_flags_idle == 0
battle_not_link
battle_engine_loaded
battle_outcome_open
```

FR/LG use `battle_exec_flags_input == 1` plus `battle_input_controller`, corrected by C4-BW (`:546-554`).

**What the bytes show:**
- `HandleTurnActionSelectionState` `0x08014040` is not detoured at entry. **PROVEN**
  - Its 7-way jump table `0x0801409C` is identical to FR.
  - Case 1 (`STATE_WAIT_ACTION_CHOSEN`, `0x080141DC-0x08014763`) begins with the exec-flag poll
    `0x080141DC-0x08014206`, which is identical to FR.
  - RR changes eight 8-byte ranges. The case-1 hooks all come after the poll: `0x080142D8`
    (→`0x09042E09`), `0x080143D4` (→`0x09042305`), `0x08014450` (→`0x09042C85`), `0x080146AC`
    (→`0x09042EED`), and a changed branch at `0x080142EA`.
  - Case 0 has a hook at `0x080140C8` (→`0x09042BBD`) and case 2 at `0x080148C0` (→`0x090441E9`).
  - The pool word at `0x08014C1C` is also changed.
- `gBattleMainFunc = 0x08014041` is stored by three functions: `TryDoEventsBeforeFirstTurn`
  (`LDR@0x08013A66`) and `BattleTurnPassed` (`LDR@0x08013CCC`), both RR-modified, and CFRU
  `LDR@0x09070628`. **PROVEN**
- `MarkBattlerForControllerExec` is identical to FR: the non-link path sets `gBitTable[battler]` in
  `0x02023BC8`. **PROVEN**
- The player controller is replaced. **PROVEN**
  - `PlayerHandleChooseAction` is detoured at entry (→`0x090AAF39`).
  - The player's `HandleInputChooseAction` `0x0802E438` is detoured at entry.
  - `PlayerBufferExecCompleted` is hooked at `0x0802E34A` (→`0x0904459B`).
- Two more hooks: `ReturnFromBattleToOverworld` has two NOPs at `0x08015BB6`, and `SetUpBattleVars`
  is hooked at `0x0800D2CC` (→`0x09042B99`).

**The finding, and why it is open.** The engine-side code is shaped like FR's: a vanilla-shaped
marker plus an identical poll. With that shape, the parked menu should carry battler 0's exec bit
(`flags == 1`), which is exactly what C4-BW established for FR/LG. If CFRU's controller also keeps
the bit set until the choice, then RR's `battle_exec_flags_idle == 0` has two consequences:
- it **refuses the parked menu**, which is a liveness failure;
- it admits the frame after the choice is committed. The main function reads that choice on the next
  frame (`BattleMainCB1` runs `gBattleMainFunc` before the controllers, pret `src/battle_main.c:2203-2209`), which is the unsafe frame
  in `battle_write_predicate.md` §2.3.

If CFRU clears the bit early, the RR tuple may be right. Which one holds depends on the three
replaced controller functions above, so this is **OPEN (INFERRED risk)**. `battle_main_func` itself
is well pinned: the only stores of `0x08014041` are listed above, and the case table is intact.

**Evidence that would close it:**
- (a) **Bytes**, about half a day. Trace `0x090AAF38`, the CFRU `HandleInputChooseAction`
  replacement, and `0x0904459A` for where bit 0 of `0x02023BC8` is cleared relative to the joypad
  wait. Also read what `0x09042B99` (`SetUpBattleVars`) and the `ReturnFromBattleToOverworld` path
  write to `gBattleOutcome` `0x02023E8A`, `gBattleMainFunc` `0x03004F84`, `gBattleCommunication`
  `0x02023E82` and `gBattleMons[0].maxHP`. This decides whether a stale tuple can survive into the
  overworld.
- (b) **Physical**, the cheaper option. On both RR artifacts, trace those five words per frame
  across:
  - a parked wild-battle menu, at least 300 frames;
  - the frame after FIGHT, then a move;
  - the bag and party menus;
  - a trainer battle;
  - 60 frames after `ReturnFromBattleToOverworld`.

  The tuple must admit the parked menu and refuse everything else. The existing battle states
  (`tools/mkstates_gen3.py` kind `battle`) are enough. The `battle_input_wild` row in
  `battle_write_predicate.md` already names RR clean and companion.

Not closed here, because neither option is cheap in a static card.

## 5. What G5 still needs

1. **A flash-write tripwire, to close row 19.** Run it on both RR artifacts under the new client
   routed for RR. The checkpoint change is not live for RR yet: `entry.lua` routes only
   `gen3_frlg`.
   - Mechanism: execution hooks on `EraseFlashSector_MX` `0x081DEED4`, `ProgramFlashByte_MX`
     `0x081DEFA4` and `ProgramFlashSector_MX` `0x081DF070`. An SRAM-domain write callback is an
     alternative.
   - At every frame end between the first and the last flash operation of a save, record the new
     predicate's verdict and clauses. Also record the old predicate's result, as the audit asked.
   - Pass: every such frame is refused, and every flash operation's call stack has a caller from the
     table above.
   - Coverage: the G5 rows already listed in the audit (START first/repeat/overwrite/cancel,
     sectors 30/31, `RunSaveFailedScreen` states 0-8, the post-link-battle save, script/link/HoF
     saves). Add natural-play soak time for "any suspected autosave".
   - A flash operation from any caller not in the table is a defect by definition.
2. **Row 3 live:** the post-link-battle save (`0x090B8EF8`) needs a Cable Club battle on both
   artifacts. It is the one CFRU-added full save.
3. **Row 12:** either accept INFERRED, or run a static script walk from the map-header script
   tables to prove `special 0xF0` is absent. The tripwire in item 1 also catches it if it is ever
   hit.
4. **Item (2):** evidence (a) or (b) from §4 before any RR `battle_faint` / `battle_commit` write
   goes live.

## Reproduce

```
python tools/research/rr_save_callers.py --selftest
python tools/research/rr_save_callers.py --rom clean --entries              # §2/§3 input
python tools/research/rr_save_callers.py --rom companion --entries          # identical to clean
python tools/research/rr_save_callers.py --rom clean --depth 12             # full caller tree
python tools/research/rr_save_callers.py --rom clean --cmdreg
python tools/research/rr_save_callers.py --rom clean --flashbase
python tools/research/rr_save_callers.py --rom clean --disasm 90b8e08:0xf0  # any listing cited
```
