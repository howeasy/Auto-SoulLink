# Are the 18 non-liveness RR engine sites reachable in slink_RR.gba?

Answer: **YES for all 18.** Every pinned function is present, byte-identical at the
pin, and called from the same places as in clean FR US 1.0. No row sits in dead
code, so the "only frame_control fires" observation is **not** a relocation problem.
It is an instrumentation problem (`reference_verify_the_probe_first`).

Scope: static caller census only. Physical receipt: docs/gen3/probes/shadow_rr_explode_2026-09-21.txt.
Expected-kinds analysis: docs/gen3/research/shadow_explode_battle_end.md.

## Method

ROMs: FR `41cb23d8dccc8ebd7c649cd8fbb58eeace6e2fdc` (16 MiB), rr_companion
md5 `bf8e94a01c0aee0aa7eb37c7333329af` (32 MiB). Function starts/sizes from
`data/gen3/pret/pokefirered.sym` via `tools/pin_gen3_site.py::parse_symbols`;
head-detour decode via `decode_thumb_detour` (LDR literal / BX same register).

1. **BL census** - decode every halfword-aligned Thumb-1 BL pair in the whole ROM
   (`0xF000..0xF7FF` then `0xF800..0xFFFF`), sign-extend the 23-bit offset, count
   targets equal to the function start. Geometric scan: data can alias a BL pair,
   so counts are an upper bound, but the *same* bound on both ROMs.
2. **Literal census** - 4-aligned 32-bit LE words equal to `start|1` (callback2 /
   task / command-table pointers) and to `start` (plain; always 0 here).
3. **Ownership** - map each caller site back to its enclosing FR symbol, then check
   whether *that* function is detoured at its head in RR (a head detour makes the
   call site downstream of it dead).
4. **Byte pin** - compare `rom_offset`/`expected_hex` from
   `data/games/gen3_rr/engine_signals.json` against slink_RR.gba.

## Result

BL/LIT columns are caller counts into the function start. "Head" = RR detour at the
entry of the pinned function itself.

| kind | function (FR start) | FR BL/LIT | RR BL/LIT | pin OK | head detour | verdict |
|---|---|---|---|---|---|---|
| frame_control | CallCallbacks 08000510 | 1/0 | 1/0 | yes | no | REACHABLE (fires) |
| battle_begin | CB2_InitBattle 0800FD9C | 0/8 | 0/8 | yes | no | REACHABLE |
| battle_end | ReturnFromBattleToOverworld 08015B58 | 0/2 | 0/2 | yes | no | REACHABLE |
| faint | Cmd_tryfaintmon 080212AC | 0/1 | 0/1 | yes | no | REACHABLE |
| capture_wild | Cmd_givecaughtmon 0802D800 | 0/1 | 0/1 | yes | no | REACHABLE |
| mon_given | GiveMonToPlayer 08040B14 | 3/0 | 3/0 | yes | **yes -> 0907D790** | REACHABLE (body pinned) |
| pc_move | SendMonToPC 08040B90 | 1/0 | 1/0 | yes | **yes -> 090B6E38** | REACHABLE (body pinned) |
| whiteout | CB2_WhiteOut 080566A4 | 0/6 | 0/**9** | yes | no | REACHABLE |
| map_load | CB2_LoadMap2 0805674C | 0/1 | 0/1 | yes | no | REACHABLE |
| evolve_species_store | Task_EvolutionScene 080CE8DC | 0/1 | 0/1 | yes | no | REACHABLE |
| trade_begin | TradeMons 0805080C | 3/0 | 3/0 | yes | no | REACHABLE |
| trade_done | TradeMons 0805080C | 3/0 | 3/0 | yes | no | REACHABLE |
| save | TrySavingData 080DA364 | 7/0 | 7/**1** | yes | no | REACHABLE |
| pc_deposit | TryStorePartyMonInBox 080930E4 | 1/0 | 1/0 | yes | no | REACHABLE |
| pc_withdraw | SetPlacedMonData 08092FD4 | 5/0 | 5/0 | yes | no (in-place) | REACHABLE |
| pc_box_place | SetPlacedMonData 08092FD4 | 5/0 | 5/0 | yes | no (in-place) | REACHABLE |
| pc_release_begin | ReleaseMon 08093218 | 1/0 | 1/0 | yes | no | REACHABLE |
| pc_release | ReleaseMon 08093218 | 1/0 | 1/0 | yes | no | REACHABLE |
| trade_evolve_species_store | Task_TradeEvolutionScene 080CF53C | 0/1 | 0/1 | yes | no | REACHABLE |

**19/19 byte pins hold. Zero rows lost a caller in RR.** RR *gained* callers on two
rows, which is extra evidence of reachability, not of relocation:

- whiteout +3 literals at **090B1550, 090C274C, 090C27B8** - these are the CFRU
  replacement bodies of `CB2_EndTrainerBattle` / `CB2_EndScriptedWildBattle` /
  `CB2_EndWildBattle` (see head detours below) still installing vanilla `CB2_WhiteOut`.
- save +1 literal at **090B8F14** - a relocated caller still pointing at 080DA365.

### Caller sites in RR, with head-detour status of the caller itself

Every site below is byte-identical to the FR site (`same_in_FR=True` on all of them).

- CallCallbacks <- BL 080004BC in `UpdateLinkAndCallCallbacks(+0xC)`, no detour.
- CB2_InitBattle <- LIT 080112DC `SpriteCB_UnusedDebugSprite_Step`, **0807F68C
  `Task_BattleStart(+0x6C)`**, 08081448 `Task_StartWiredCableClubBattle`, 08081618
  `Task_StartWirelessCableClubBattle`, 080E68FC `Task_WaitBT`, 0811C0DC
  `SetUpPartiesAndStartBattle`, 0815BD54 `TeachyTvPreBattleAnim...`, 0815E15C
  `Task_DoTrainerTowerBattle`. **None detoured at head.**
- ReturnFromBattleToOverworld <- LIT 08015A68 `FreeResetData_ReturnToOvOrDoEvolutions(+0x38)`,
  08015B2C `TryEvolvePokemon(+0x8C)`. **Neither detoured.**
- Cmd_tryfaintmon <- LIT 08250180 = `gBattleScriptingCommandsTable + 0x64`
  (opcode 0x19, matches the pin doc). Table itself intact.
- Cmd_givecaughtmon <- LIT 082504DC = `gBattleScriptingCommandsTable + 0x3C0` (opcode 0xF0).
- GiveMonToPlayer <- BL 0802D824 `Cmd_givecaughtmon(+0x24)` (this *is* the capture_wild
  pin address); BL 080A016C `ScriptGiveMon(+0x50)` - **ScriptGiveMon head detours to
  0907767C**, so the script-gift path reaches the CFRU body, not this BL; BL 080A01D8
  `ScriptGiveEgg(+0x2C)`, not detoured.
- SendMonToPC <- BL 08040B82 `GiveMonToPlayer(+0x6E)`; GiveMonToPlayer head detours to
  0907D790, so the live path is body-to-body, and both are already pinned at their RR bodies.
- CB2_WhiteOut <- LIT 0807FB7C `CB2_EndWildBattle` (**head -> 090C2754**), 0807FBDC
  `CB2_EndScriptedWildBattle` (**head -> 090C26F0**), 0807FC2C `CB2_EndMarowakBattle`,
  0808053C `CB2_EndTrainerBattle` (**head -> 090B14C4**), 08080590 `CB2_EndRematchBattle`,
  080CA3D4 `SetCB2WhiteOut`, plus the three relocated bodies listed above.
- CB2_LoadMap2 <- LIT 08056748 `CB2_LoadMap(+0x2C)`, not detoured (matches the doc).
- Task_EvolutionScene <- LIT 080CE0D0 `EvolutionScene(+0x2DC)`, not detoured.
- TradeMons <- BL 08052242 `DoTradeAnim_Cable`, 0805369E `DoTradeAnim_Wireless`,
  08053DCE `CB2_UpdateLinkTrade`. **None detoured** - the exact three callers the pin doc names.
- TrySavingData <- BL 08009A34 `LinkTestProcessKeyInput`, 0806F952 + 0806F962
  `SaveDialogCB_DoSave`, 080E7030 `SaveBattleTowerProgress`, 080F2230 `Task_Hof_TrySaveData`,
  08129156 `ChatEntryRoutine_SaveAndExit`, 08142B7A `SaveOnMysteryGiftMenu`. None detoured.
- TryStorePartyMonInBox <- BL 0808DE1E `Task_DepositMenu(+0x96)`, not detoured.
- SetPlacedMonData <- BL 08092F0C + 08092F34 `PlaceMon`, 080930A0 `SetShiftedMonData`,
  08093110 + 08093134 `TryStorePartyMonInBox`. None detoured.
- ReleaseMon <- BL 0808DF98 `Task_ReleaseMon(+0xCC)`, not detoured.
- Task_TradeEvolutionScene <- LIT 080CE6DC `TradeEvolutionScene(+0x19C)`, not detoured.

### The explode-B expectation specifically

`battle_begin` (CB2_InitBattle 0800FD9C), `faint` (Cmd_tryfaintmon 080212AC) and
`battle_end` (ReturnFromBattleToOverworld 08015B58) are all intact, un-detoured, with
their vanilla caller sets byte-identical to FR - including `Task_BattleStart+0x6C`,
the ordinary overworld trainer-battle entry the B side of `explode` takes. There is
**no binary reason** these three did not fire during that duo run.

## Rows needing re-pinning

**None.** `mon_given` and `pc_move` already point at the RR bodies (0907D7F8 /
090B6E9A); their vanilla trampolines at 08040B14 / 08040B90 are entry stubs only and
are not pinned. `pc_withdraw` / `pc_box_place` are in-place-modified and pin correctly.
The two poison rows stay UNVERIFIED for the reason already recorded (detour to a
`MOVS R0,0; BX LR` stub); they were outside this scan of 18.

Watch-only, no action: `ScriptGiveMon` (-> 0907767C) and the three `CB2_End*Battle`
bodies (-> 090B14C4 / 090C26F0 / 090C2754) are relocated. They kill no pinned row
(each still routes to a pinned body or to CB2_WhiteOut), but caller coverage for
`mon_given` via the script-gift path now runs through the CFRU body, not 080A016C.

## Next probe, not next re-pin

Since exec hooks demonstrably work at 0x0800051A, the discriminator is whether they
work at *higher* ROM addresses at all. Cheapest falsifiable control - both
un-detoured in RR and hot on every frame:

- `AnimateSprites` **08006B5C** (low, near the one site that does fire)
- `RunTasks` **08077578** (mid-range, same order as battle_begin / faint)

If AnimateSprites fires and RunTasks does not, `event.on_bus_exec` registration is
address-limited and every pin here is fine. If both fire, the failure is per-site and
the next suspect is the capture_offset / odd-halfword hook address, not the pins.

## Reproduce

Scratch script, not checked in. Regenerate with `parse_symbols` +
`decode_thumb_detour` from `tools/pin_gen3_site.py`, a numpy BL-pair decode over the
full ROM, and a 4-aligned `start|1` word search. No emulator was run for this note.
